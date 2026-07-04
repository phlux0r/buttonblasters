# tests/test_09_leds.py — Button Blasters
# TEST 9 — WS2812B LED strip bring-up
#
# Wiring:
#   GP20 → 330Ω resistor → 74AHCT125 A1 input (pin 2)
#   74AHCT125 /OE1 (pin 1) → GND
#   74AHCT125 Y1 output (pin 3) → WS2812B DIN
#   74AHCT125 VCC (pin 14) → VBUS (5V)
#   74AHCT125 GND (pin 7)  → GND
#   WS2812B 5V → VBUS
#   WS2812B GND → GND
#   (100µF cap across WS2812B power rail recommended — add when available)
#
# What this tests:
#   1. PIO state machine init for WS2812B protocol
#   2. All LEDs white — confirms all 8 LEDs addressable
#   3. Individual LED addressing — one at a time
#   4. RGB colour channels — red/green/blue isolation
#   5. Brightness control
#   6. Game effects — correct flash, wrong flash, rainbow, chase
#
# Expected: 8 LEDs respond to all commands
# ─────────────────────────────────────────────────────────────────

import time
import array
import rp2
from machine import Pin

print()
print("=" * 48)
print("  Button Blasters — TEST 9: WS2812B LEDs")
print("=" * 48)

# ── Config ────────────────────────────────────────────────────────
LED_PIN  = 20
NUM_LEDS = 8

# ── PIO program ───────────────────────────────────────────────────
print("\n[1] PIO state machine init...")
try:
    @rp2.asm_pio(
        sideset_init=rp2.PIO.OUT_LOW,
        out_shiftdir=rp2.PIO.SHIFT_LEFT,
        autopull=True,
        pull_thresh=24,
    )
    def _ws2812():
        T1, T2, T3 = 2, 5, 3
        wrap_target()
        label("bitloop")
        out(x, 1)           .side(0) [T3-1]
        jmp(not_x, "zero")  .side(1) [T1-1]
        jmp("bitloop")      .side(1) [T2-1]
        label("zero")
        nop()               .side(0) [T2-1]
        wrap()

    sm = rp2.StateMachine(
        0, _ws2812,
        freq=8_000_000,
        sideset_base=Pin(LED_PIN),
    )
    sm.active(1)
    print(f"    ✓ PIO state machine ready on GP{LED_PIN}")
except Exception as e:
    print(f"    ✗ PIO init failed: {e}")
    raise SystemExit

# ── LED helpers ───────────────────────────────────────────────────
buf = array.array('I', [0] * NUM_LEDS)

def grb(r, g, b, brightness=1.0):
    """Pack RGB into GRB word with brightness scaling."""
    r = int(r * brightness)
    g = int(g * brightness)
    b = int(b * brightness)
    return (g << 16) | (r << 8) | b

def show():
    sm.put(buf, 8)
    time.sleep_ms(1)

def fill(r, g, b, brightness=1.0):
    for i in range(NUM_LEDS):
        buf[i] = grb(r, g, b, brightness)
    show()

def set_pixel(i, r, g, b, brightness=1.0):
    buf[i] = grb(r, g, b, brightness)

def off():
    fill(0, 0, 0)

# ── Test 2: All white ─────────────────────────────────────────────
print("\n[2] All LEDs white (low brightness)...")
print("    All 8 LEDs should light up white")
fill(255, 255, 255, brightness=0.2)
time.sleep_ms(2000)
off()
time.sleep_ms(300)
print("    ✓ Done — did all 8 light up?")

# ── Test 3: Individual addressing ────────────────────────────────
print("\n[3] Individual LED addressing (walking light)...")
print("    One LED should light up at a time, left to right")
off()
for i in range(NUM_LEDS):
    buf[i] = grb(0, 0, 255, 0.4)   # blue
    show()
    time.sleep_ms(200)
    buf[i] = grb(0, 0, 0)
show()
time.sleep_ms(300)
print("    ✓ Walking light complete")

# ── Test 4: RGB channel isolation ────────────────────────────────
print("\n[4] RGB channel isolation...")
print("    RED — all LEDs should be red")
fill(255, 0, 0, brightness=0.35)
time.sleep_ms(1500)

print("    GREEN — all LEDs should be green")
fill(0, 255, 0, brightness=0.35)
time.sleep_ms(1500)

print("    BLUE — all LEDs should be blue")
fill(0, 0, 255, brightness=0.35)
time.sleep_ms(1500)

off()
time.sleep_ms(300)
print("    ✓ RGB channels confirmed")

# ── Test 5: Brightness levels ────────────────────────────────────
print("\n[5] Brightness levels...")
print("    White — stepping from dim to bright")
for bri in [0.05, 0.15, 0.30, 0.50, 0.80]:
    fill(255, 255, 255, brightness=bri)
    time.sleep_ms(500)
off()
time.sleep_ms(300)
print("    ✓ Brightness levels confirmed")

# ── Test 6: Game effects ─────────────────────────────────────────
print("\n[6] Game effects...")

print("    Correct answer flash (green)...")
for _ in range(3):
    fill(0, 255, 80, brightness=0.5)
    time.sleep_ms(80)
    off()
    time.sleep_ms(60)
time.sleep_ms(300)
print("    ✓")

print("    Wrong answer flash (red)...")
for _ in range(2):
    fill(255, 0, 0, brightness=0.5)
    time.sleep_ms(80)
    off()
    time.sleep_ms(60)
time.sleep_ms(300)
print("    ✓")

print("    Chase effect...")
for cycle in range(3):
    for pos in range(NUM_LEDS):
        for i in range(NUM_LEDS):
            if i == pos:
                buf[i] = grb(80, 40, 255, 1.0)
            elif i == (pos - 1) % NUM_LEDS:
                buf[i] = grb(12, 6, 38, 1.0)
            else:
                buf[i] = 0
        show()
        time.sleep_ms(60)
off()
time.sleep_ms(300)
print("    ✓")

print("    Rainbow cycle...")
def hsv_to_rgb(h):
    h = h % 360
    hi = h // 60
    f  = (h / 60) - hi
    lut = [
        (255, int(255*f), 0),
        (int(255*(1-f)), 255, 0),
        (0, 255, int(255*f)),
        (0, int(255*(1-f)), 255),
        (int(255*f), 0, 255),
        (255, 0, int(255*(1-f))),
    ]
    return lut[hi]

for hue in range(0, 360, 5):
    for i in range(NUM_LEDS):
        h = (hue + i * (360 // NUM_LEDS)) % 360
        r, g, b = hsv_to_rgb(h)
        buf[i] = grb(r, g, b, 0.35)
    show()
    time.sleep_ms(30)
off()
time.sleep_ms(300)
print("    ✓")

print("    Level up (rainbow chase x3)...")
for _ in range(3):
    for hue in range(0, 360, 15):
        for i in range(NUM_LEDS):
            h = (hue + i * 30) % 360
            r, g, b = hsv_to_rgb(h)
            buf[i] = grb(r, g, b, 0.4)
        show()
        time.sleep_ms(25)
off()
time.sleep_ms(300)
print("    ✓")

print("    Idle rainbow (5 seconds)...")
start = time.ticks_ms()
hue = 0
while time.ticks_diff(time.ticks_ms(), start) < 5000:
    for i in range(NUM_LEDS):
        h = (hue + i * (360 // NUM_LEDS)) % 360
        r, g, b = hsv_to_rgb(h)
        buf[i] = grb(r, g, b, 0.25)
    show()
    hue = (hue + 2) % 360
    time.sleep_ms(30)
off()
print("    ✓")

# ── Summary ───────────────────────────────────────────────────────
print()
print("=" * 48)
print("  TEST 9 — LED SUMMARY")
print("  PIO init         : ✓ GP20 via 74AHCT125")
print("  All LEDs white   : ✓ (confirm 8 lit)")
print("  Individual addr  : ✓ walking light")
print("  RGB channels     : ✓ red/green/blue isolated")
print("  Brightness       : ✓ dim to bright")
print("  Game effects     : ✓ all patterns")
print()
print("  If LEDs didn't light:")
print("  - Check 74AHCT125 VCC → VBUS (5V, not 3.3V)")
print("  - Check /OE1 (pin 1) → GND")
print("  - Check 330Ω resistor on data line")
print("  - Check WS2812B 5V → VBUS, GND → GND")
print("  - Check GP20 → 330Ω → 74AHCT125 pin 2")
print()
print("  Next: test_10_buttons_mcp.py")
print("=" * 48)
print()
