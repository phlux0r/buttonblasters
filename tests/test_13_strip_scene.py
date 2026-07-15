# test_13_strip_scene.py
# Button Blasters -- StripRenderer bench test (main ILI9488 display).
#
# WHAT IT PROVES (go/no-go before wiring the renderer into a real game):
#   * StripBufferPool seats on real hardware (ties back to test_12's numbers).
#   * The 480x32 band loop covers the full 480x320 screen with no gaps/overlap.
#   * RGB565 -> RGB666 viper convert produces correct colour  <-- ENDIANNESS.
#   * RAMWR/CS framing holds: CS low at 0x2C, streams a whole band, rises once.
#     (Broken framing = noise or blank, not a clean image.)
#   * The event loop breathes between bands (no freeze).
#
# It uses a SYNTHETIC band provider (computes the pattern into the pool's own
# buffers) so it needs NO big scene buffer -- a full 480x320 RGB565 image is
# 300KB and won't fit, which is the whole reason the renderer streams. The
# real SD read_band (with the 400kHz bus switch) is tested separately once
# wired; this validates everything from the convert onward.
#
# THE ACTUAL PASS CRITERION IS VISUAL. Watch the panel:
#   Test A -- solid RED fill. Must be RED. If it's blue -> RGB565 byte order is
#             wrong: flip the two byte reads in rgb565_to_rgb666_band.
#   Test B -- 8 vertical bars, left->right:
#             WHITE YELLOW CYAN GREEN MAGENTA RED BLUE BLACK
#             White must be clean (5->6 expansion), bars crisp, no noise bands
#             (noise in a band = RAMWR/CS framing broke for that strip).
#
# SETUP: put strip_renderer.py on the Pico. If you placed it in a package
# (e.g. display/), change the import below to match.

import gc
import time
import asyncio
from machine import Pin, SPI

from strip_renderer import StripRenderer, MAIN_W, MAIN_H, STRIP_H, DISPLAY_FREQ

# --- confirmed pin map (main display on SPI0) -----------------------------
PIN_SCK  = 18
PIN_MOSI = 19
PIN_MISO = 4
PIN_ILI_CS  = 6
PIN_ILI_DC  = 12
PIN_ILI_RST = 17
# every other device CS held HIGH to avoid bus contention during the test
IDLE_CS = (7, 8, 9, 10, 3)          # ST7789 x4 + SD_CS
ILI9488_MADCTL = 0x28               # landscape (confirmed)


def _park_idle_cs():
    for gp in IDLE_CS:
        Pin(gp, Pin.OUT, value=1)


# --- minimal ILI9488 init (confirmed sequence, per-byte CS framing) -------
class _Init:
    def __init__(self, spi, cs, dc):
        self.spi, self.cs, self.dc = spi, cs, dc
        self._b = bytearray(1)

    def cmd(self, b):
        self.dc(0); self.cs(0); self._b[0] = b; self.spi.write(self._b); self.cs(1)

    def dat(self, b):
        self.dc(1); self.cs(0); self._b[0] = b; self.spi.write(self._b); self.cs(1)

    def run(self):
        self.cmd(0x11); time.sleep_ms(120)          # sleep out
        self.cmd(0x3A); self.dat(0x66)              # 18-bit RGB666
        self.cmd(0xC5); self.dat(0x00); self.dat(0x4D); self.dat(0x80)  # VCOM
        self.cmd(0x21)                              # inversion ON (IPS)
        self.cmd(0x36); self.dat(ILI9488_MADCTL)    # landscape BGR
        self.cmd(0x29)                              # display ON


# --- synthetic patterns (RGB565 little-endian, one row = MAIN_W*2 bytes) --
def _row_solid(color565, width=MAIN_W):
    row = bytearray(width * 2)
    lo = color565 & 0xFF
    hi = (color565 >> 8) & 0xFF
    for x in range(width):
        row[x * 2] = lo
        row[x * 2 + 1] = hi
    return row


def _row_bars(width=MAIN_W):
    bars = (0xFFFF, 0xFFE0, 0x07FF, 0x07E0, 0xF81F, 0xF800, 0x001F, 0x0000)
    bw = width // len(bars)
    row = bytearray(width * 2)
    for x in range(width):
        c = bars[min(x // bw, len(bars) - 1)]
        row[x * 2] = c & 0xFF
        row[x * 2 + 1] = (c >> 8) & 0xFF
    return row


def _make_reader(row_bytes):
    """Return a read_band(dst_mv, band_index, band_rows) that tiles one row
    down the band. Leaves the bus untouched (synthetic -- no SD, no freq
    switch); the test keeps the bus at DISPLAY_FREQ throughout."""
    rw = len(row_bytes)

    def read_band(dst_mv, band_index, band_rows):
        for r in range(band_rows):
            dst_mv[r * rw:(r + 1) * rw] = row_bytes

    return read_band


async def main():
    print("=" * 58)
    print("test_13 -- StripRenderer scene test (ILI9488, landscape)")
    print("=" * 58)

    _park_idle_cs()
    cs  = Pin(PIN_ILI_CS,  Pin.OUT, value=1)
    dc  = Pin(PIN_ILI_DC,  Pin.OUT, value=0)
    rst = Pin(PIN_ILI_RST, Pin.OUT, value=1)

    # hardware reset pulse
    rst(1); time.sleep_ms(10); rst(0); time.sleep_ms(20); rst(1); time.sleep_ms(120)

    spi = SPI(0, baudrate=DISPLAY_FREQ, polarity=0, phase=0,
              sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI), miso=Pin(PIN_MISO))

    def set_bus_freq(hz):
        # ALWAYS re-init -- never trust a cached freq (the _current_freq
        # desync gotcha). Here it also proves the finally/restore path.
        spi.init(baudrate=hz, polarity=0, phase=0)

    _Init(spi, cs, dc).run()
    print("ILI9488 init done.")

    r = StripRenderer(spi, cs, dc, set_bus_freq)

    gc.collect()
    free_before = gc.mem_free()
    with r.acquire_strips() as strips:
        free_live = gc.mem_free()
        print("pool seated: free before=%.1fKB, with buffers live=%.1fKB"
              % (free_before / 1024, free_live / 1024))

        # -- Test A: solid RED (uniform-field colour + framing sanity) -----
        red_reader = _make_reader(_row_solid(0xF800))
        t = time.ticks_ms()
        await r.blit_sd(strips, red_reader)
        print("Test A  solid RED fill : %d ms   (must look RED, not blue)"
              % time.ticks_diff(time.ticks_ms(), t))
        await asyncio.sleep_ms(1200)

        # -- Test B: vertical colour bars (convert + endianness + framing) -
        bars_reader = _make_reader(_row_bars())
        t = time.ticks_ms()
        await r.blit_sd(strips, bars_reader)
        print("Test B  colour bars    : %d ms" % time.ticks_diff(time.ticks_ms(), t))
        print("        expect L->R: WHITE YELLOW CYAN GREEN MAGENTA RED BLUE BLACK")

    gc.collect()
    free_after = gc.mem_free()
    print("pool released: free=%.1fKB (recovered %s)"
          % (free_after / 1024,
             "yes" if abs(free_after - free_before) < 4096 else "CHECK"))
    print("-" * 58)
    print("VISUAL CHECK is the real pass. If bars are correct and clean,")
    print("the band loop, convert, endianness, and RAMWR/CS framing all pass.")
    print("=" * 58)


if __name__ == "__main__":
    asyncio.run(main())
