# drivers/display.py
# Async display driver for:
#   - ST7796   480×320  (4.0" main screen — replaced ILI9488 rev 1.1)
#   - ST7789   240×280  (×4 button screens)
#
# ST7796 key differences vs old ILI9488:
#   - Natively RGB565 over SPI — no 18-bit expansion loop needed
#   - Faster SPI (up to 80 MHz; we run 62 MHz)
#   - Different init sequence (PGAMCTRL/NGAMCTRL, VCMPCTL, DOCA)
#   - Same set_window / blit API as before — DisplayManager unchanged

import asyncio
from machine import Pin
import config
from drivers.spi_bus import spi_bus


def _pulse_reset(rst_pin: Pin):
    """Hard-reset a display (blocking — called at boot only)."""
    import time
    rst_pin.value(0)
    time.sleep_ms(10)
    rst_pin.value(1)
    time.sleep_ms(120)


# ── ST7796 — 4.0" main screen ────────────────────────────────────────────────
# Init sequence validated against ST7796S datasheet and common module configs.
# 0xFF in the stream = delay 150 ms.

_ST7796_INIT = bytes([
    0x01, 0,                    # SW reset
    0xFF, 0,                    # delay 150 ms
    0x11, 0,                    # sleep out
    0xFF, 0,                    # delay 150 ms

    0xF0, 1, 0xC3,              # command set enable (unlock)
    0xF0, 1, 0x96,              # command set enable (unlock)

    0x36, 1, 0x48,              # MADCTL: landscape, BGR colour order
    0x3A, 1, 0x05,              # pixel format: 16-bit RGB565

    0xB4, 1, 0x01,              # inversion control: 2-dot inversion
    0xB7, 1, 0xC6,              # entry mode set

    # Frame rate — 60 Hz at normal mode
    0xB1, 2, 0x80, 0x10,

    # Display function control
    0xB6, 3, 0x80, 0x02, 0x3B,

    # Power control
    0xC0, 2, 0x80, 0x64,
    0xC1, 1, 0x13,
    0xC2, 1, 0xA7,

    # VCOM
    0xC5, 1, 0x09,

    # Positive gamma
    0xE0, 14,
        0xF0, 0x06, 0x0B, 0x07, 0x06, 0x05, 0x2E, 0x33,
        0x47, 0x3A, 0x17, 0x16, 0x2E, 0x31,

    # Negative gamma
    0xE1, 14,
        0xF0, 0x09, 0x0D, 0x09, 0x08, 0x23, 0x2E, 0x33,
        0x46, 0x38, 0x13, 0x13, 0x2C, 0x32,

    0xF0, 1, 0x3C,              # command set disable
    0xF0, 1, 0x69,              # command set disable

    0x13, 0,                    # normal display mode on
    0x29, 0,                    # display on
])


class ST7796:
    """Async driver for the ST7796 4.0\" main display.

    API is identical to the old ILI9488 class so DisplayManager needs
    no changes — just swap the import and class name.
    """

    def __init__(self):
        self._cs  = Pin(config.PIN_CS_MAIN,  Pin.OUT, value=1)
        self._dc  = Pin(config.PIN_DC_MAIN,  Pin.OUT, value=1)
        self._rst = Pin(config.PIN_RST_MAIN, Pin.OUT, value=1)
        self.w    = config.MAIN_W    # 480
        self.h    = config.MAIN_H    # 320

    # ── Boot init (blocking) ─────────────────────────────────────

    def init_blocking(self):
        """Call once at boot before asyncio starts."""
        _pulse_reset(self._rst)
        self._send_init_seq(_ST7796_INIT)

    def _send_init_seq(self, seq):
        import time
        i = 0
        self._cs.value(0)
        while i < len(seq):
            cmd = seq[i]; i += 1
            if cmd == 0xFF:          # delay marker
                time.sleep_ms(150)
                continue
            n = seq[i]; i += 1
            self._dc.value(0)
            spi_bus.spi.write(bytes([cmd]))
            if n:
                self._dc.value(1)
                spi_bus.spi.write(bytes(seq[i:i+n]))
                i += n
        self._cs.value(1)

    # ── Low-level window + pixel ops ─────────────────────────────

    async def set_window(self, x0, y0, x1, y1):
        """Set address window. Must be called inside a spi_bus.device context."""
        self._dc.value(0); spi_bus.write(b'\x2A')
        self._dc.value(1); spi_bus.write(bytes([x0>>8, x0&0xFF, x1>>8, x1&0xFF]))
        self._dc.value(0); spi_bus.write(b'\x2B')
        self._dc.value(1); spi_bus.write(bytes([y0>>8, y0&0xFF, y1>>8, y1&0xFF]))
        self._dc.value(0); spi_bus.write(b'\x2C')
        self._dc.value(1)

    # ── Fill ─────────────────────────────────────────────────────

    async def fill(self, color565: int, x=0, y=0, w=None, h=None):
        """Fill a rectangle with an RGB565 colour.
        ST7796 is natively 16-bit — no conversion needed (unlike old ILI9488).
        """
        w = w or self.w; h = h or self.h
        hi = color565 >> 8
        lo = color565 & 0xFF
        chunk = bytes([hi, lo] * 64)     # 128-byte write chunk = 64 pixels
        total = w * h
        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            await self.set_window(x, y, x+w-1, y+h-1)
            for _ in range(total // 64):
                spi_bus.write(chunk)
            rem = total % 64
            if rem:
                spi_bus.write(bytes([hi, lo] * rem))

    # ── Blit ─────────────────────────────────────────────────────

    async def blit_rgb565(self, buf: memoryview, x=0, y=0, w=None, h=None):
        """Write a raw RGB565 buffer to the display.
        Direct write — no per-pixel conversion required (ST7796 native format).
        Significantly faster than the old ILI9488 18-bit expansion path.
        """
        w = w or self.w; h = h or self.h
        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            await self.set_window(x, y, x+w-1, y+h-1)
            # Write in 4 KB chunks to yield cooperative slices to other tasks
            CHUNK = 4096
            mv = memoryview(buf) if not isinstance(buf, memoryview) else buf
            offset = 0
            total_bytes = w * h * 2
            while offset < total_bytes:
                end = min(offset + CHUNK, total_bytes)
                spi_bus.write(mv[offset:end])
                offset = end
                if offset < total_bytes:
                    await asyncio.sleep_ms(0)   # yield between chunks

    async def clear(self):
        await self.fill(0x0000)


# ── ST7789 — button screens (unchanged from rev 1.0) ────────────────────────

_ST7789_INIT = bytes([
    0x01, 0,            # SW reset
    0xFF, 0,            # delay
    0x11, 0,            # sleep out
    0xFF, 0,            # delay
    0x3A, 1, 0x05,      # pixel format RGB565
    0x36, 1, 0x00,      # MADCTL
    0x21, 0,            # display inversion on (most ST7789 modules need this)
    0x13, 0,            # normal display mode
    0x29, 0,            # display on
])


class ST7789:
    """Async driver for a single ST7789 1.69\" button display."""

    def __init__(self, index: int):
        self._index = index
        self._cs  = Pin(config.PIN_CS_BTN[index],  Pin.OUT, value=1)
        self._dc  = Pin(config.PIN_DC_BTN[index],  Pin.OUT, value=1)
        self._rst = Pin(config.PIN_RST_BTN, Pin.OUT, value=1) if index == 0 else None
        self.w    = config.BTN_W
        self.h    = config.BTN_H

    def init_blocking(self):
        if self._rst:
            _pulse_reset(self._rst)
        self._send_init_seq(_ST7789_INIT)

    def _send_init_seq(self, seq):
        import time
        i = 0
        self._cs.value(0)
        while i < len(seq):
            cmd = seq[i]; i += 1
            if cmd == 0xFF:
                time.sleep_ms(120)
                continue
            n = seq[i]; i += 1
            self._dc.value(0)
            spi_bus.spi.write(bytes([cmd]))
            if n:
                self._dc.value(1)
                spi_bus.spi.write(bytes(seq[i:i+n]))
                i += n
        self._cs.value(1)

    async def set_window(self, x0, y0, x1, y1):
        self._dc.value(0); spi_bus.write(b'\x2A')
        self._dc.value(1); spi_bus.write(bytes([x0>>8,x0&0xFF,x1>>8,x1&0xFF]))
        self._dc.value(0); spi_bus.write(b'\x2B')
        self._dc.value(1); spi_bus.write(bytes([y0>>8,y0&0xFF,y1>>8,y1&0xFF]))
        self._dc.value(0); spi_bus.write(b'\x2C')
        self._dc.value(1)

    async def fill(self, color565: int, x=0, y=0, w=None, h=None):
        w = w or self.w; h = h or self.h
        hi, lo = color565 >> 8, color565 & 0xFF
        chunk = bytes([hi, lo] * 64)
        total = w * h
        async with spi_bus.device(self._cs):
            await self.set_window(x, y, x+w-1, y+h-1)
            for _ in range(total // 64):
                spi_bus.write(chunk)
            rem = total % 64
            if rem:
                spi_bus.write(bytes([hi, lo] * rem))

    async def blit_rgb565(self, buf: memoryview, x=0, y=0, w=None, h=None):
        w = w or self.w; h = h or self.h
        async with spi_bus.device(self._cs):
            await self.set_window(x, y, x+w-1, y+h-1)
            spi_bus.write(buf)

    async def clear(self):
        await self.fill(0x0000)
