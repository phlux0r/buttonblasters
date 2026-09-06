# tests/test_16_button_edge_probe.py — Button Blasters
# BENCH TEST: precisely measure how many pixels (if any) are cropped on
# each edge of a button screen, instead of guessing from a photo.
#
# WHY THIS EXISTS: several rounds of guessing BTN_W (300 -> 280 -> back to
# 300) each produced a different, confusing symptom -- clipping, an empty
# strip, a fill that doesn't cover the full width -- because none of them
# were measured precisely, just eyeballed. This draws a RULER: a full-width
# fill, a border, and 10px tick marks in a contrasting colour every 10px
# from each edge, so you can COUNT exactly how many ticks are visible vs
# missing on each side, on the REAL physical panel.
#
# Uses the confirmed-working init sequence and BTN_W/BTN_H from config.py
# as the addressing window (currently 300x240) -- this test does NOT
# change that window, it just marks it up so you can see precisely what's
# happening inside it.
#
# HOW TO READ THE RESULT:
#   - Solid colour fills the WHOLE visible glass edge-to-edge, no gaps,
#     on every side? The addressing window (BTN_W/BTN_H) is correct.
#   - A strip of the LAST-drawn colour (background, not filled by the
#     ticks) is visible on one edge? That's dead/unaddressed native
#     columns/rows -- the window is too SMALL on that side.
#   - Tick marks are visible for a while from the edge, then MISSING for
#     the rest of that edge (e.g. ticks at 0,10,20 show but 30+ don't, or
#     vice versa)? That's a genuine crop of that many pixels -- count
#     which ticks you CAN see to get the exact number.
#   - Report back: which edge(s), and how many px are missing based on
#     which ticks disappeared.
#
# Run standalone via mpremote/Thonny/REPL. Tests BTN-0 only (CS_IDX=0);
# change CS_IDX to check a different button.

import time
from machine import SPI, Pin
import config

CS_IDX = 0   # which button to probe: 0-3 (indices into config.PIN_CS_BTN)

W, H = config.BTN_W, config.BTN_H
TICK_EVERY = 10     # a tick mark every 10px from each edge
TICK_LEN   = 40     # was 6 -- too short to clear the rounded-corner bezel
                     # cutting off content right at the edge, and short
                     # enough that the WHOLE left-edge tick column (x=2..7)
                     # could sit entirely inside a crop deeper than that,
                     # explaining "no ticks visible on the left at all"
                     # rather than just the corner-adjacent ones
TICK_THICK = 2       # tick mark thickness

blk     = Pin(config.PIN_BLK_BTN, Pin.OUT, value=1)
main_cs = Pin(6, Pin.OUT, value=1)   # keep main display CS idle-high
spi     = SPI(0, baudrate=10_000_000,
              sck=Pin(18), mosi=Pin(19), miso=Pin(4))
cs  = Pin(config.PIN_CS_BTN[CS_IDX], Pin.OUT, value=1)
dc  = Pin(config.PIN_DC_BTN[CS_IDX], Pin.OUT, value=1)
rst = Pin(config.PIN_RST_BTN, Pin.OUT, value=1) if CS_IDX == 0 else None


def wc(c): dc.value(0); cs.value(0); spi.write(bytes([c])); cs.value(1)
def wd(*args): dc.value(1); cs.value(0); spi.write(bytes(args)); cs.value(1)


def init():
    if rst:
        rst.value(0); time.sleep_ms(100)
        rst.value(1); time.sleep_ms(200)
    wc(0x01); time.sleep_ms(150)
    wc(0x11); time.sleep_ms(255)
    wc(0x3A); wd(0x05)
    wc(0x36); wd(config.ST7789_MADCTL[CS_IDX])
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
    if x0 < 0: x0 = 0
    if y0 < 0: y0 = 0
    if x1 >= W: x1 = W - 1
    if y1 >= H: y1 = H - 1
    if x1 < x0 or y1 < y0:
        return
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


print("\n" + "=" * 60)
print("  Button Blasters — TEST 16: button-screen edge ruler probe")
print(f"  Testing BTN-{CS_IDX}  window {W}x{H}")
print("=" * 60)

init()

# Background: WHITE, so any unaddressed/dead area shows as whatever the
# panel defaults to (usually black or garbage), clearly different from
# both white and the coloured ticks.
fill_rect(255, 255, 255, 0, 0, W - 1, H - 1)

# Border: thin BLACK frame flush at the true logical edges (0, W-1, H-1).
BORDER_T = 2
fill_rect(0, 0, 0, 0,         0,         W - 1,     BORDER_T - 1)   # top
fill_rect(0, 0, 0, 0,         H - BORDER_T, W - 1,  H - 1)          # bottom
fill_rect(0, 0, 0, 0,         0,         BORDER_T - 1, H - 1)       # left
fill_rect(0, 0, 0, W - BORDER_T, 0,      W - 1,     H - 1)          # right

# Tick marks every 10px along the TOP edge (x direction) in RED, and
# every 10px along the LEFT edge (y direction) in BLUE -- alternate
# colours every other tick so you can count in groups of 2 at a glance.
x = 0
i = 0
while x < W:
    color = (255, 0, 0) if (i % 2 == 0) else (255, 140, 0)
    fill_rect(color[0], color[1], color[2], x, BORDER_T, x + TICK_THICK - 1, BORDER_T + TICK_LEN - 1)
    x += TICK_EVERY
    i += 1

y = 0
i = 0
while y < H:
    color = (0, 0, 255) if (i % 2 == 0) else (0, 180, 255)
    fill_rect(color[0], color[1], color[2], BORDER_T, y, BORDER_T + TICK_LEN - 1, y + TICK_THICK - 1)
    y += TICK_EVERY
    i += 1

print(f"  Ruler drawn: {TICK_LEN}px stripes every {TICK_EVERY}px from top")
print(f"  (RED/ORANGE) and left (BLUE/CYAN) edges -- long enough to overlap")
print(f"  each other (that's expected, alternating colour still marks each")
print(f"  10px position) and to clear a rounded-corner bezel. Black border")
print(f"  flush at the logical 0..{W-1} x 0..{H-1} window.")
print()
print("  Look at the panel now:")
print("   - Is there a white gap between the black border and the true")
print("     physical edge of the glass, on any side? That side has that")
print("     many pixels of dead/unaddressed space (window too SMALL).")
print("   - Is the black border itself partly or fully off the visible")
print("     glass (cut by the bezel) on any side? Count how many tick")
print("     marks from that edge are ALSO cut off -- that number is the")
print("     exact crop, whatever's causing it (bezel or addressing).")
print("   - Clean: border flush with the true edge, all ticks visible on")
print("     every side? This window (currently %dx%d) is correct." % (W, H))
print()
print("  Leaving the ruler on screen -- Ctrl+C or reset when done looking.")

try:
    while True:
        time.sleep_ms(1000)
except KeyboardInterrupt:
    pass
