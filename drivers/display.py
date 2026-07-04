# drivers/display.py — Button Blasters v3.0
# Confirmed-working display drivers.
#
# ILI9488  4.0" IPS 320×480  — main screen
# ST7789   1.69" 240×300     — ×4 button screens
#
# Every init value is hardware-confirmed. Do not simplify.

import asyncio
import time
from machine import Pin
import config
from drivers.spi_bus import spi_bus


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
        self._wc(0x36); self._wd(0x48)            # MADCTL portrait BGR
        self._wc(0x29); time.sleep_ms(20)         # display ON

    def _set_window(self, x0, y0, x1, y1):
        self._wc(0x2A); self._wd(x0>>8, x0&0xFF, x1>>8, x1&0xFF)
        self._wc(0x2B); self._wd(y0>>8, y0&0xFF, y1>>8, y1&0xFF)
        self._wc(0x2C); self._dc.value(1)

    async def fill(self, color565: int, x=0, y=0, w=None, h=None):
        w = w or self.w; h = h or self.h
        r = (color565 >> 8) & 0xF8
        g = (color565 >> 3) & 0xFC
        b = (color565 << 3) & 0xF8
        px    = bytes([r, g, b])
        chunk = px * 21
        total = w * h
        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window(x, y, x+w-1, y+h-1)
            for _ in range(total // 21): spi_bus.write(chunk)
            rem = total % 21
            if rem: spi_bus.write(px * rem)

    async def fill_rgb(self, r: int, g: int, b: int,
                       x=0, y=0, w=None, h=None):
        w = w or self.w; h = h or self.h
        px    = bytes([r & 0xF8, g & 0xFC, b & 0xF8])
        chunk = px * 21; total = w * h
        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window(x, y, x+w-1, y+h-1)
            for _ in range(total // 21): spi_bus.write(chunk)
            rem = total % 21
            if rem: spi_bus.write(px * rem)

    async def blit_rgb565(self, buf: memoryview, x=0, y=0,
                          w=None, h=None):
        """RGB565 buffer → RGB666 on the fly."""
        w = w or self.w; h = h or self.h
        total = w * h
        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window(x, y, x+w-1, y+h-1)
            CHUNK = 256
            out   = bytearray(CHUNK * 3)
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


# ── ST7789 ───────────────────────────────────────────────────────

_blk_pin = None

def _ensure_blk():
    global _blk_pin
    if _blk_pin is None:
        _blk_pin = Pin(config.PIN_BLK_BTN, Pin.OUT, value=1)


class ST7789:
    """
    ST7789 1.69" button display driver.
    Critical: full LovyanGFX init, BLK=GP13 HIGH, 240×300 window.
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
        self._wc(0x36); self._wd(0x00)
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
        self._wc(0x2C); self._dc.value(1)

    async def fill(self, color565: int, x=0, y=0, w=None, h=None):
        w = w or self.w; h = h or self.h
        hi = color565 >> 8; lo = color565 & 0xFF
        chunk = bytes([hi, lo] * 64); total = w * h
        async with spi_bus.device(self._cs, freq=config.SPI_FREQ_DISPLAY):
            self._set_window(x, y, x+w-1, y+h-1)
            for _ in range(total // 64): spi_bus.write(chunk)
            rem = total % 64
            if rem: spi_bus.write(bytes([hi, lo] * rem))

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
