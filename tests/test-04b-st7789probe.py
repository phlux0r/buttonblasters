# tests/test_04b_st7789_probe.py — Button Blasters
# ST7789 window offset probe
# Finds the correct x/y offsets for this specific module
# Run standalone — no need to run test_02 first

import time
from machine import SPI, Pin

spi = SPI(0, baudrate=10_000_000, sck=Pin(18), mosi=Pin(19), miso=Pin(4))
cs   = Pin(7,  Pin.OUT, value=1)
dc   = Pin(2,  Pin.OUT, value=1)
rst  = Pin(15, Pin.OUT, value=1)
main_cs = Pin(6, Pin.OUT, value=1)   # keep main display off bus

print("\n" + "="*48)
print("  TEST 4b: ST7789 window offset probe")
print("="*48)

def wc(c): dc.value(0); cs.value(0); spi.write(bytes([c])); cs.value(1)
def wd(d): dc.value(1); cs.value(0); spi.write(bytes(d));   cs.value(1)

# ── Init ──────────────────────────────────────────────────────────
print("\n[1] Init...")
rst.value(0); time.sleep_ms(20); rst.value(1); time.sleep_ms(120)
wc(0x11); time.sleep_ms(120)
wc(0x3A); wd([0x05])    # RGB565
wc(0x36); wd([0x00])    # MADCTL
wc(0x21)                # inversion on
wc(0x13)                # normal mode
wc(0x29)                # display on
time.sleep_ms(50)
print("    ✓")

def fill(r, g, b, x0=0, y0=0, x1=239, y1=239):
    """Fill window with RGB565 colour."""
    hi = ((r&0xF8)<<8 | (g&0xFC)<<3 | b>>3) >> 8
    lo =  (r&0xF8)<<8 | (g&0xFC)<<3 | b>>3  & 0xFF
    c = ((r&0xF8)<<8) | ((g&0xFC)<<3) | (b>>3)
    hi = c>>8; lo = c&0xFF
    w = x1-x0+1; h = y1-y0+1
    wc(0x2A); wd([x0>>8, x0&0xFF, x1>>8, x1&0xFF])
    wc(0x2B); wd([y0>>8, y0&0xFF, y1>>8, y1&0xFF])
    wc(0x2C)
    chunk = bytes([hi,lo]*64); total = w*h
    dc.value(1); cs.value(0)
    for _ in range(total//64): spi.write(chunk)
    if total%64: spi.write(bytes([hi,lo]*(total%64)))
    cs.value(1)

# ── Test 1: fill 240x240 ──────────────────────────────────────────
print("\n[2] Filling 240x240 RED (y0=0, y1=239)...")
fill(255, 0, 0, 0, 0, 239, 239)
time.sleep_ms(1500)
print("    Note: full screen? partial? black border where?")

# ── Test 2: fill 240x280 with offset 0 ───────────────────────────
print("\n[3] Filling 240x280 GREEN (y0=0, y1=279)...")
fill(0, 255, 0, 0, 0, 239, 279)
time.sleep_ms(1500)
print("    Did display go dark? (too tall for this window)")

# ── Test 3: try common ST7789 y offset of 20 (0x14) ──────────────
# Many 240x280 modules have a 20px y offset in controller RAM
print("\n[4] Filling with y offset 20 (y0=20, y1=299)...")
wc(0x29)  # ensure display on
fill(0, 0, 255, 0, 20, 239, 299)
time.sleep_ms(1500)
print("    Full screen blue? Black border at top?")

# ── Test 4: try y offset 20, height 280 ──────────────────────────
print("\n[5] Filling YELLOW: x=0-239, y=0-279 with offset baked in...")
wc(0x29)
# Use MADCTL offset approach — try writing 240x280 from y=0
# with controller offset correction
fill(255, 255, 0, 0, 0, 239, 279)
time.sleep_ms(1500)

# ── Test 5: solid colours cycling with 240x240 ───────────────────
print("\n[6] Cycling colours at 240x240 — check coverage on screen")
print("    Ctrl+C to stop")
try:
    while True:
        for r,g,b,name in [(255,0,0,"RED"),(0,255,0,"GRN"),(0,0,255,"BLU")]:
            wc(0x29)
            fill(r,g,b,0,0,239,239)
            print(f"    {name} — full screen or partial?")
            time.sleep_ms(1500)
except KeyboardInterrupt:
    pass

print("\n" + "="*48)
print("  TEST 4b COMPLETE")
print("  Note which fill covered the full screen")
print("  and what offset/dimensions were used.")
print("="*48 + "\n")