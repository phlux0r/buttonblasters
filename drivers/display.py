# drivers/display.py — Button Blasters v3.0
# Confirmed-working display drivers.
#
# ILI9488  4.0" IPS 320×480  — main screen
# ST7789   1.69" 300×240 landscape — ×4 button screens
#
# Every init value is hardware-confirmed. Do not simplify.
#
# ── FIX (display layer) ──────────────────────────────────────────
# Fills/blits previously latched NOTHING (white main, noise buttons)
# even though init worked. Cause: _set_window() ended its RAMWR (0x2C)
# via _wc(), which raises CS HIGH right after the command byte. The
# pixel-data stream that follows was therefore sent with CS HIGH and
# ignored by the panel. RAMWR is a command whose DATA PHASE is the
# pixel stream, so CS must stay LOW from 0x2C through all pixels, then
# rise once (handled by the device-context __aexit__). Fixed below by
# writing RAMWR inline and leaving CS LOW. Fill loops also gained
# periodic `await asyncio.sleep_ms(0)` so a long fill no longer blocks
# the event loop (Ctrl-C / other tasks stay responsive).

import asyncio
import time
from machine import Pin
import config
from drivers.spi_bus import spi_bus
from rgb666_viper import rgb565_to_666   # native RGB565→666 (31x faster)


def _pulse_reset(rst_pin: Pin):
    rst_pin.value(0); time.sleep_ms(20)
    rst_pin.value(1); time.sleep_ms(120)


# ── ILI9488 ──────────────────────────────────────────────────────

class ILI9488:
    """
    ILI9488 4.0" IPS main display driver.
    Critical: per-byte CS toggle, RGB666, VCOM=0x4D, 0x21 inversion.
    """

    def __init__(self):
        self._cs  = Pin(config.PIN_CS_MAIN,  Pin.OUT, value=1)
        self._dc  = Pin(config.PIN_DC_MAIN,  Pin.OUT, value=1)
        self._rst = Pin(config.PIN_RST_MAIN, Pin.OUT, value=1)
        self.w    = config.MAIN_W
        self.h    = config.MAIN_H
        # Reusable RGB666 output buffer for blit_rgb565. Allocated once
        # (grows to the largest blit ever seen) and reused every call, so
        # blits don't allocate per-call — a fresh 76KB alloc per shape blit
        # caused MemoryError from heap fragmentation on the first round.
        self._blit_scratch = None

    def init_blocking(self):
        _pulse_reset(self._rst)
        self._run_init()
        print(f"[display] ILI9488 ready  {self.w}×{self.h}  "
              f"CS=GP{config.PIN_CS_MAIN}  DC=GP{config.PIN_DC_MAIN}")

    def _wc(self, cmd):
        self._dc.value(0); self._cs.value(0)
        spi_bus.spi.write(bytes([cmd]))
        self._cs.value(1)

    def _wd(self, *data):
        self._dc.value(1)
        for b in data:
            self._cs.value(0)
            spi_bus.spi.write(bytes([b]))
            self._cs.value(1)

    def _run_init(self):
        self._wc(0x11); time.sleep_ms(120)      # sleep out — FIRST
        self._wc(0x3A); self._wd(0x66)           # RGB666
        self._wc(0xC5); self._wd(0x00, 0x4D, 0x80)  # VCOM
        self._wc(0x21)                             # inversion ON (IPS)
        self._wc(0x36); self._wd(config.ILI9488_MADCTL)  # MADCTL (landscape via config)
        self._wc(0x29); time.sleep_ms(20)         # display ON

    def _set_window(self, x0, y0, x1, y1):
        # Column + row address windows. These use per-command CS framing
        # (via _wc/_wd) which is correct for the address-setting phase.
        self._wc(0x2A); self._wd(x0>>8, x0&0xFF, x1>>8, x1&0xFF)
        self._wc(0x2B); self._wd(y0>>8, y0&0xFF, y1>>8, y1&0xFF)
        # RAMWR (0x2C): the pixel data that follows is this command's
        # DATA PHASE, so CS must stay LOW through the whole stream. Do
        # NOT use _wc() here — it would raise CS and the pixels would be
        # ignored. Caller runs inside spi_bus.device(), which asserted
        # CS low on enter and raises it on exit.
        self._dc.value(0); self._cs.value(0)
        spi_bus.spi.write(bytes([0x2C]))
        self._dc.value(1)                          # data mode; CS stays LOW

    async def fill(self, color565: int, x=0, y=0, w=None, h=None):
        w = w or self.w; h = h or self.h
        r = (color565 >> 8) & 0xF8
        g = (color565 >> 3) & 0xFC
        b = (color565 << 3) & 0xF8
        px = bytes([r, g, b])
        total = w * h
        # Large chunk (1024 px = 3072 B) so a full-screen fill loops ~150x
        # instead of ~7300x — far less Python overhead per fill. Yield once
        # per chunk so audio/buttons still get loop time during the fill.
        CHUNK_PX = 1024
        chunk = px * CHUNK_PX
        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window(x, y, x+w-1, y+h-1)
            remaining = total
            while remaining >= CHUNK_PX:
                spi_bus.write(chunk)
                remaining -= CHUNK_PX
                await asyncio.sleep_ms(0)
            if remaining:
                spi_bus.write(px * remaining)

    async def fill_rgb(self, r: int, g: int, b: int,
                       x=0, y=0, w=None, h=None):
        w = w or self.w; h = h or self.h
        px = bytes([r & 0xF8, g & 0xFC, b & 0xF8])
        total = w * h
        CHUNK_PX = 1024
        chunk = px * CHUNK_PX
        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window(x, y, x+w-1, y+h-1)
            remaining = total
            while remaining >= CHUNK_PX:
                spi_bus.write(chunk)
                remaining -= CHUNK_PX
                await asyncio.sleep_ms(0)
            if remaining:
                spi_bus.write(px * remaining)

    async def blit_rgb565(self, buf: memoryview, x=0, y=0,
                          w=None, h=None):
        """RGB565 buffer → RGB666, converted and streamed in horizontal
        BANDS. A whole 160x160 RGB666 buffer is 76KB and won't allocate
        in the fragmented heap; a band of BAND_ROWS rows needs only
        ~w*BAND_ROWS*3 bytes (~7.5KB for a 160-wide shape). The small band
        scratch is allocated once (grows only if a wider blit appears) and
        reused per band, so there's no large or per-call allocation."""
        w = w or self.w; h = h or self.h
        BAND_ROWS = 16
        band_bytes = w * BAND_ROWS * 3
        # gc before the (small) allocation so it lands in a clean heap.
        if self._blit_scratch is None or len(self._blit_scratch) < band_bytes:
            import gc
            gc.collect()
            print(f"[display] blit scratch alloc {band_bytes}B  "
                  f"free={gc.mem_free()}")
            self._blit_scratch = bytearray(band_bytes)
        scratch = memoryview(self._blit_scratch)

        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window(x, y, x+w-1, y+h-1)
            row = 0
            while row < h:
                rows = BAND_ROWS if (h - row) >= BAND_ROWS else (h - row)
                n_px = w * rows
                # Convert this band (starting w*row pixels into src) into
                # the front of the scratch, then stream just those bytes.
                rgb565_to_666(buf, scratch, n_px, w * row)
                spi_bus.write(scratch[:n_px * 3])
                row += rows
                if row < h:
                    await asyncio.sleep_ms(0)

    async def clear(self):
        await self.fill(0x0000)


# ── ST7789 ───────────────────────────────────────────────────────

_blk_pin = None

def _ensure_blk():
    global _blk_pin
    if _blk_pin is None:
        _blk_pin = Pin(config.PIN_BLK_BTN, Pin.OUT, value=1)


class ST7789:
    """
    ST7789 1.69" button display driver.
    Critical: full LovyanGFX init, BLK=GP13 HIGH, 300×240 landscape window
    (MADCTL=0x60, config.ST7789_MADCTL — bench-confirmed via
    tests/test_15_button_landscape.py; was 240×300 portrait, MADCTL=0x00).
    """

    def __init__(self, index: int):
        _ensure_blk()
        self._cs  = Pin(config.PIN_CS_BTN[index],  Pin.OUT, value=1)
        self._dc  = Pin(config.PIN_DC_BTN[index],  Pin.OUT, value=1)
        self._rst = (Pin(config.PIN_RST_BTN, Pin.OUT, value=1)
                     if index == 0 else None)
        self.w    = config.BTN_W
        self.h    = config.BTN_H

    def init_blocking(self):
        if self._rst:
            _pulse_reset(self._rst)
        self._run_init()

    def _wc(self, cmd):
        self._dc.value(0); self._cs.value(0)
        spi_bus.spi.write(bytes([cmd])); self._cs.value(1)

    def _wd(self, *data):
        self._dc.value(1); self._cs.value(0)
        spi_bus.spi.write(bytes(data)); self._cs.value(1)

    def _run_init(self):
        self._wc(0x01); time.sleep_ms(150)
        self._wc(0x11); time.sleep_ms(255)
        self._wc(0x3A); self._wd(0x05)
        self._wc(0x36); self._wd(config.ST7789_MADCTL)   # landscape
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
        self._wc(0x21); self._wc(0x13); time.sleep_ms(10)
        self._wc(0x29); time.sleep_ms(255)

    def _set_window(self, x0, y0, x1, y1):
        self._wc(0x2A); self._wd(x0>>8,x0&0xFF,x1>>8,x1&0xFF)
        self._wc(0x2B); self._wd(y0>>8,y0&0xFF,y1>>8,y1&0xFF)
        # RAMWR (0x2C): keep CS LOW so the pixel stream is sent as this
        # command's data phase (see ILI9488._set_window for the full
        # explanation — same bug, same fix).
        self._dc.value(0); self._cs.value(0)
        spi_bus.spi.write(bytes([0x2C]))
        self._dc.value(1)                          # data mode; CS stays LOW

    async def fill(self, color565: int, x=0, y=0, w=None, h=None):
        w = w or self.w; h = h or self.h
        hi = color565 >> 8; lo = color565 & 0xFF
        total = w * h
        # Large chunk (1024 px = 2048 B RGB565) — far fewer loop iterations
        # than the old 64-px chunk. Yield per chunk for audio/button time.
        CHUNK_PX = 1024
        chunk = bytes([hi, lo] * CHUNK_PX)
        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window(x, y, x+w-1, y+h-1)
            remaining = total
            while remaining >= CHUNK_PX:
                spi_bus.write(chunk)
                remaining -= CHUNK_PX
                await asyncio.sleep_ms(0)
            if remaining:
                spi_bus.write(bytes([hi, lo] * remaining))

    async def fill_rgb(self, r: int, g: int, b: int,
                       x=0, y=0, w=None, h=None):
        c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        await self.fill(c, x, y, w, h)

    async def blit_rgb565(self, buf: memoryview, x=0, y=0,
                          w=None, h=None):
        w = w or self.w; h = h or self.h
        total_bytes = w * h * 2
        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window(x, y, x+w-1, y+h-1)
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
