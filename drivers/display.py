# drivers/display.py — Button Blasters
# Confirmed-working display drivers
#
# ILI9488  4.0" IPS 320×480  — main screen
# ST7789   1.69" 240×300     — ×4 button screens
#
# Every init value here is hardware-confirmed through bring-up tests.
# Do not "simplify" the ST7789 init — the full LovyanGFX sequence is
# required to activate the frame buffer on these modules.

import asyncio
import time
from machine import Pin
import config
from drivers.spi_bus import spi_bus


def _pulse_reset(rst_pin: Pin):
    """Hard-reset a display. Blocking — call at boot only."""
    rst_pin.value(0)
    time.sleep_ms(20)
    rst_pin.value(1)
    time.sleep_ms(120)


# ── ILI9488 — 4.0" IPS main display ─────────────────────────────

class ILI9488:
    """
    Async driver for the ILI9488 4.0" IPS main display.

    Critical confirmed facts:
      - IPS panel: requires 0x21 (inversion ON) — missing = blank screen
      - VCOM = 0x4D — supplier confirmed, wrong value = no image
      - Pixel format: 18-bit RGB666 (0x66) — not 16-bit
      - Per-byte CS toggle required for every individual byte
      - Sleep out (0x11) FIRST with 120ms delay before other commands
      - LED/backlight wired directly to 3.3V — no GPIO needed
      - SPI at 10MHz confirmed stable
    """

    def __init__(self):
        self._cs  = Pin(config.PIN_CS_MAIN,  Pin.OUT, value=1)
        self._dc  = Pin(config.PIN_DC_MAIN,  Pin.OUT, value=1)
        self._rst = Pin(config.PIN_RST_MAIN, Pin.OUT, value=1)
        self.w    = config.MAIN_W    # 320
        self.h    = config.MAIN_H    # 480

    # ── Boot init (blocking) ─────────────────────────────────────

    def init_blocking(self):
        """Call once at boot before asyncio starts."""
        _pulse_reset(self._rst)
        self._run_init()

    def _wc(self, cmd):
        """Write command byte — CS toggle per byte (ILI9488 requirement)."""
        self._dc.value(0)
        self._cs.value(0)
        spi_bus.spi.write(bytes([cmd]))
        self._cs.value(1)

    def _wd(self, *data):
        """Write data bytes — CS toggle per byte."""
        self._dc.value(1)
        for b in data:
            self._cs.value(0)
            spi_bus.spi.write(bytes([b]))
            self._cs.value(1)

    def _run_init(self):
        """Confirmed working ILI9488 IPS init sequence."""
        # Sleep out FIRST — required before any other command
        self._wc(0x11)
        time.sleep_ms(120)

        # Pixel format: 18-bit RGB666
        self._wc(0x3A); self._wd(0x66)

        # VCOM — supplier confirmed 0x4D is critical
        self._wc(0xC5); self._wd(0x00, 0x4D, 0x80)

        # Display inversion ON — required for IPS panel
        self._wc(0x21)

        # MADCTL — portrait mode, BGR colour order
        self._wc(0x36); self._wd(0x48)

        # Display ON
        self._wc(0x29)
        time.sleep_ms(20)

    # ── Window + pixel ops ───────────────────────────────────────

    def _set_window_blocking(self, x0, y0, x1, y1):
        """Set address window. Blocking version for use inside device context."""
        self._wc(0x2A); self._wd(x0>>8, x0&0xFF, x1>>8, x1&0xFF)
        self._wc(0x2B); self._wd(y0>>8, y0&0xFF, y1>>8, y1&0xFF)
        self._wc(0x2C)
        self._dc.value(1)

    # ── Fill ─────────────────────────────────────────────────────

    async def fill(self, color565: int, x=0, y=0, w=None, h=None):
        """
        Fill a rectangle. Accepts RGB565 colour — converts to RGB666
        internally (ILI9488 native format over SPI).
        """
        w = w or self.w
        h = h or self.h
        # Expand RGB565 → RGB666 (pad lower bits)
        r = (color565 >> 8) & 0xF8
        g = (color565 >> 3) & 0xFC
        b = (color565 << 3) & 0xF8
        px = bytes([r, g, b])
        chunk = px * 21   # 63 bytes = 21 pixels per write
        total = w * h

        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window_blocking(x, y, x+w-1, y+h-1)
            for _ in range(total // 21):
                spi_bus.write(chunk)
            rem = total % 21
            if rem:
                spi_bus.write(px * rem)

    async def fill_rgb(self, r: int, g: int, b: int,
                       x=0, y=0, w=None, h=None):
        """Fill with raw RGB values 0-255. Slightly faster than fill()."""
        w = w or self.w
        h = h or self.h
        px = bytes([r & 0xF8, g & 0xFC, b & 0xF8])
        chunk = px * 21
        total = w * h

        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window_blocking(x, y, x+w-1, y+h-1)
            for _ in range(total // 21):
                spi_bus.write(chunk)
            rem = total % 21
            if rem:
                spi_bus.write(px * rem)

    # ── Blit ─────────────────────────────────────────────────────

    async def blit_rgb565(self, buf: memoryview, x=0, y=0,
                          w=None, h=None):
        """
        Write a raw RGB565 buffer to the display.
        Converts each pixel to RGB666 on the fly (ILI9488 requirement).
        Yields to asyncio between 4KB chunks.
        """
        w = w or self.w
        h = h or self.h
        total = w * h

        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window_blocking(x, y, x+w-1, y+h-1)
            CHUNK = 256   # pixels per iteration
            out = bytearray(CHUNK * 3)
            offset = 0
            while offset < total:
                count = min(CHUNK, total - offset)
                for i in range(count):
                    pi = (offset + i) * 2
                    hi = buf[pi]; lo = buf[pi+1]
                    out[i*3]   = hi & 0xF8
                    out[i*3+1] = ((hi << 5) | (lo >> 3)) & 0xFC
                    out[i*3+2] = (lo << 3) & 0xF8
                spi_bus.write(memoryview(out)[:count*3])
                offset += count
                if offset < total:
                    await asyncio.sleep_ms(0)

    async def clear(self):
        await self.fill(0x0000)


# ── ST7789 — button displays (×4) ────────────────────────────────

# Shared BLK pin — must be driven HIGH from GPIO.
# Tying to 3.3V does NOT work on these modules.
_blk_pin = None

def _ensure_blk():
    global _blk_pin
    if _blk_pin is None:
        _blk_pin = Pin(config.PIN_BLK_BTN, Pin.OUT, value=1)


class ST7789:
    """
    Async driver for a single ST7789 1.69" button display.

    Critical confirmed facts:
      - BLK pin MUST be driven HIGH from GPIO (GP13) — not 3.3V rail
      - Full LovyanGFX power init required — minimal init won't work
      - Working window: 240×300 (fills full physical screen)
      - DC BTN-0 uses GP2 (GP5 is dead on this board)
      - SPI at 10MHz confirmed stable
    """

    def __init__(self, index: int):
        _ensure_blk()
        self._index = index
        self._cs  = Pin(config.PIN_CS_BTN[index],  Pin.OUT, value=1)
        self._dc  = Pin(config.PIN_DC_BTN[index],  Pin.OUT, value=1)
        # Only BTN-0 owns the shared RST pin object
        self._rst = (Pin(config.PIN_RST_BTN, Pin.OUT, value=1)
                     if index == 0 else None)
        self.w    = config.BTN_W    # 240
        self.h    = config.BTN_H    # 300

    # ── Boot init (blocking) ─────────────────────────────────────

    def init_blocking(self):
        """Call once at boot. BTN-0 performs the shared reset."""
        if self._rst is not None:
            _pulse_reset(self._rst)
        self._run_init()

    def _wc(self, cmd):
        self._dc.value(0)
        self._cs.value(0)
        spi_bus.spi.write(bytes([cmd]))
        self._cs.value(1)

    def _wd(self, *data):
        self._dc.value(1)
        self._cs.value(0)
        spi_bus.spi.write(bytes(data))
        self._cs.value(1)

    def _run_init(self):
        """Full LovyanGFX-style init — required for frame buffer activation."""
        self._wc(0x01); time.sleep_ms(150)    # SW reset
        self._wc(0x11); time.sleep_ms(255)    # sleep out
        self._wc(0x3A); self._wd(0x05)        # RGB565
        self._wc(0x36); self._wd(0x00)        # MADCTL
        self._wc(0xB2); self._wd(0x0C,0x0C,0x00,0x33,0x33)
        self._wc(0xB7); self._wd(0x35)
        self._wc(0xBB); self._wd(0x19)
        self._wc(0xC0); self._wd(0x2C)
        self._wc(0xC2); self._wd(0x01)
        self._wc(0xC3); self._wd(0x12)
        self._wc(0xC4); self._wd(0x20)
        self._wc(0xC6); self._wd(0x0F)
        self._wc(0xD0); self._wd(0xA4,0xA1)
        self._wc(0xE0); self._wd(0xD0,0x04,0x0D,0x11,0x13,0x2B,
                                  0x3F,0x54,0x4C,0x18,0x0D,0x0B,0x1F,0x23)
        self._wc(0xE1); self._wd(0xD0,0x04,0x0C,0x11,0x13,0x2C,
                                  0x3F,0x44,0x51,0x2F,0x1F,0x1F,0x20,0x23)
        self._wc(0x21)                         # display inversion ON
        self._wc(0x13); time.sleep_ms(10)      # normal display mode
        self._wc(0x29); time.sleep_ms(255)     # display ON

    # ── Window op ────────────────────────────────────────────────

    def _set_window_blocking(self, x0, y0, x1, y1):
        self._wc(0x2A); self._wd(x0>>8, x0&0xFF, x1>>8, x1&0xFF)
        self._wc(0x2B); self._wd(y0>>8, y0&0xFF, y1>>8, y1&0xFF)
        self._wc(0x2C)
        self._dc.value(1)

    # ── Fill ─────────────────────────────────────────────────────

    async def fill(self, color565: int, x=0, y=0, w=None, h=None):
        """Fill a rectangle with an RGB565 colour (ST7789 native)."""
        w = w or self.w
        h = h or self.h
        hi = color565 >> 8
        lo = color565 & 0xFF
        chunk = bytes([hi, lo] * 64)
        total = w * h

        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window_blocking(x, y, x+w-1, y+h-1)
            for _ in range(total // 64):
                spi_bus.write(chunk)
            rem = total % 64
            if rem:
                spi_bus.write(bytes([hi, lo] * rem))

    async def fill_rgb(self, r: int, g: int, b: int,
                       x=0, y=0, w=None, h=None):
        """Fill with raw RGB values 0-255."""
        c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        await self.fill(c, x, y, w, h)

    # ── Blit ─────────────────────────────────────────────────────

    async def blit_rgb565(self, buf: memoryview, x=0, y=0,
                          w=None, h=None):
        """Write a raw RGB565 buffer. Direct — no conversion needed."""
        w = w or self.w
        h = h or self.h
        total_bytes = w * h * 2

        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window_blocking(x, y, x+w-1, y+h-1)
            CHUNK = 4096
            mv = memoryview(buf) if not isinstance(buf, memoryview) else buf
            offset = 0
            while offset < total_bytes:
                end = min(offset + CHUNK, total_bytes)
                spi_bus.write(mv[offset:end])
                offset = end
                if offset < total_bytes:
                    await asyncio.sleep_ms(0)

    async def clear(self):
        await self.fill(0x0000)
