# tests/test_15_button_landscape.py — Button Blasters
# BENCH TEST: probe ST7789 button screens for landscape orientation.
#
# WHY: config.py currently runs the button screens portrait (MADCTL=0x00,
# confirmed working window 240x300 -- see test_04_button_displays.py and
# HARDWARE_NOTES.md). If the shell moves to a 2x2 button layout, landscape
# may fit better mechanically, but rotation is NOT a safe assumption:
#   - The confirmed portrait window (300 rows) is already a surprise vs.
#     the panel's 280-row spec, so the landscape window is not guaranteed
#     to be a clean 300x240 swap -- it could have its own row/column
#     surprise, the same way portrait did.
#   - Display<->orientation handedness (mirroring) is NOT predictable from
#     the datasheet, same class of gotcha as the main display's touch
#     mapping -- must be confirmed by looking at the actual panel.
#
# This script:
#   [1] Runs the confirmed portrait init, but stops short of the final
#       MADCTL write so you can pick a candidate.
#   [2] For each candidate MADCTL (0x60, 0xA0 -- the two 90-degree
#       rotations of the confirmed-working 0x00, WITHOUT touching the RGB
#       bit, which is already confirmed correct in portrait -- do not add
#       0x08 to these), fills the screen at a guessed W x H, then draws a
#       single coloured square in the TOP-LEFT corner only.
#   [3] You look at the physical panel (mounted the way you intend to use
#       it) and answer two questions for each candidate:
#         a) Is the fill using the WHOLE panel -- no black dead strip on
#            any edge, no wrapped/garbage pixels? If there's a dead strip,
#            the guessed W/H is too small; if there's garbage, too large.
#            Adjust PROBE_W/PROBE_H below and rerun.
#         b) Is the corner square actually in the top-left as YOU will
#            view the mounted panel? If it's in the wrong corner, that
#            candidate is mirrored/rotated the wrong way -- try the other
#            MADCTL value (or its ^0x40 / ^0x80 variant -- see CANDIDATES).
#   [4] Once one candidate looks right on this unit, physically move the
#       cable to each of the other 3 button positions (or edit CS_IDX
#       below) and repeat the corner-square check on all four -- same
#       part number, but the portrait-window surprise means "confirm on
#       one, trust all four" is exactly the assumption that bit us before.
#
# Record the winning MADCTL + confirmed W/H here and in HARDWARE_NOTES.md,
# then update config.py (BTN_W/BTN_H) and drivers/display.py's ST7789
# MADCTL write to match -- every baked button-screen asset (icons, menu
# tiles, back/replay tiles) will need re-baking at the new dimensions.

import time, gc
from machine import SPI, Pin

# ── Which physical button position to test (index into config's CS/DC
#    arrays: 0,1,2,3). Defaults to BTN-2 (CS=GP9, DC=GP14), matching
#    test_04_button_displays.py. Change to check a different position
#    without re-wiring.
CS_PINS = (7, 8, 9, 10)
DC_PINS = (2, 11, 14, 21)
CS_IDX  = 2

# ── Candidates. 0x00 is the confirmed-working portrait value (bit3=RGB,
#    already correct -- do not add 0x08/BGR to these). 0x20 = MV (row/col
#    exchange, the actual "make it landscape" bit); MX/MY pick which of
#    the two 90-degree rotations you get.
CANDIDATES = {
    "0x60 (MV+MX)": 0x60,
    "0xA0 (MV+MY)": 0xA0,
}

# ── First guess at the landscape window. Portrait's confirmed window was
#    240x300 against a 240x280 spec (+20 rows) -- so don't assume a clean
#    swap to 300x240. Try this first; if the fill leaves a dead strip or
#    shows garbage at an edge, adjust and rerun.
PROBE_W = 300
PROBE_H = 240

blk     = Pin(13, Pin.OUT, value=1)
main_cs = Pin(6,  Pin.OUT, value=1)   # keep the main display CS idle-high
spi     = SPI(0, baudrate=10_000_000,
              sck=Pin(18), mosi=Pin(19), miso=Pin(4))
cs  = Pin(CS_PINS[CS_IDX], Pin.OUT, value=1)
dc  = Pin(DC_PINS[CS_IDX], Pin.OUT, value=1)
rst = Pin(15, Pin.OUT, value=1)


def wc(c): dc.value(0); cs.value(0); spi.write(bytes([c])); cs.value(1)
def wd(*args): dc.value(1); cs.value(0); spi.write(bytes(args)); cs.value(1)


def init(madctl):
    rst.value(0); time.sleep_ms(100)
    rst.value(1); time.sleep_ms(200)
    wc(0x01); time.sleep_ms(150)
    wc(0x11); time.sleep_ms(255)
    wc(0x3A); wd(0x05)
    wc(0x36); wd(madctl)   # the only line that changes vs test_04
    wc(0xB2); wd(0x0C, 0x0C, 0x00, 0x33, 0x33)
    wc(0xB7); wd(0x35)
    wc(0xBB); wd(0x19)
    wc(0xC0); wd(0x2C)
    wc(0xC2); wd(0x01)
    wc(0xC3); wd(0x12)
    wc(0xC4); wd(0x20)
    wc(0xC6); wd(0x0F)
    wc(0xD0); wd(0xA4, 0xA1)
    wc(0xE0); wd(0xD0, 0x04, 0x0D, 0x11, 0x13, 0x2B, 0x3F, 0x54, 0x4C, 0x18, 0x0D, 0x0B, 0x1F, 0x23)
    wc(0xE1); wd(0xD0, 0x04, 0x0C, 0x11, 0x13, 0x2C, 0x3F, 0x44, 0x51, 0x2F, 0x1F, 0x1F, 0x20, 0x23)
    wc(0x21)
    wc(0x13); time.sleep_ms(10)
    wc(0x29); time.sleep_ms(255)


def fill_rect(r, g, b, x0, y0, x1, y1):
    c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    hi = c >> 8; lo = c & 0xFF
    total = (x1 - x0 + 1) * (y1 - y0 + 1)
    chunk = bytes([hi, lo] * 128)
    wc(0x2A); wd(x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)
    wc(0x2B); wd(y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)
    wc(0x2C)
    dc.value(1); cs.value(0)
    for _ in range(total // 128):
        spi.write(chunk)
    if total % 128:
        spi.write(bytes([hi, lo] * (total % 128)))
    cs.value(1)


def fill(r, g, b, w, h):
    fill_rect(r, g, b, 0, 0, w - 1, h - 1)


print("\n" + "=" * 60)
print("  Button Blasters — TEST 15: button-screen landscape probe")
print(f"  Testing position {CS_IDX}: CS=GP{CS_PINS[CS_IDX]}  DC=GP{DC_PINS[CS_IDX]}")
print(f"  Probe window: {PROBE_W} x {PROBE_H}")
print("=" * 60)

for label, madctl in CANDIDATES.items():
    print(f"\n[{label}]")
    init(madctl)
    gc.collect()

    print(f"  Filling BLUE, full probe window ({PROBE_W}x{PROBE_H})...")
    fill(0, 0, 255, PROBE_W, PROBE_H)
    print("  -> Look at the panel now:")
    print("     - Dead black strip on any edge?  Window is too SMALL.")
    print("     - Garbage/wrapped pixels at an edge? Window is too LARGE.")
    print("     - Clean edge-to-edge blue? Window size is correct.")
    time.sleep_ms(2500)

    print("  Drawing a WHITE square in the top-left 40x40 corner...")
    fill_rect(255, 255, 255, 0, 0, 39, 39)
    print("  -> Is that square in the TOP-LEFT as YOU view the mounted")
    print("     panel? If not, this MADCTL value is mirrored/rotated the")
    print("     wrong way for your mounting -- note it and try the other.")
    time.sleep_ms(3000)

print("\n" + "=" * 60)
print("  Done. Once a candidate looks right:")
print("   1. Note the winning MADCTL value and confirmed W/H (adjust")
print("      PROBE_W/PROBE_H above and rerun if the fill wasn't clean).")
print("   2. Repeat on the other 3 CS_IDX positions (0,1,2,3) --")
print("      confirm on one, trust all four is what bit us on portrait.")
print("   3. Update config.py (BTN_W/BTN_H) and the ST7789 MADCTL write")
print("      in drivers/display.py, and HARDWARE_NOTES.md.")
print("   4. Every baked button-screen asset needs re-baking at the new")
print("      dimensions (icons, menu tiles, back/replay tiles).")
print("=" * 60 + "\n")
