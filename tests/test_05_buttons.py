# tests/test_05_buttons.py — Button Blasters
# TEST 5 — 6× push buttons with ST7789 visual feedback
#
# Confirmed pin assignments:
#   SPI:    SCK=GP18  MOSI=GP19  MISO=GP4
#   BTN-0:  CS=GP7   DC=GP2   RST=GP15  BLK=GP13
#   BTN-1:  CS=GP8   DC=GP11  RST=GP15  BLK=GP13
#   BTN-2:  CS=GP9   DC=GP14  RST=GP15  BLK=GP13
#   BTN-3:  CS=GP10  DC=GP21  RST=GP15  BLK=GP13
#   Main:   CS=GP6   (held HIGH — not used for display here)
#
#   Buttons (one leg → GPIO, other leg → GND):
#   SCREEN-0 → GP20
#   SCREEN-1 → GP22
#   SCREEN-2 → GP0
#   SCREEN-3 → GP1
#   NAV-BACK → GP16
#   NAV-NEXT → GP28 (also TOUCH_INT — may read LOW if touch wired)

import time
from machine import Pin, SPI

print()
print("=" * 48)
print("  Button Blasters — TEST 5: Push buttons")
print("=" * 48)

# ── Button config ────────────────────────────────────────────────
BUTTONS = [
    {"name": "SCREEN-0", "gpio": 20, "type": "screen", "idx": 0},
    {"name": "SCREEN-1", "gpio": 22, "type": "screen", "idx": 1},
    {"name": "SCREEN-2", "gpio":  0, "type": "screen", "idx": 2},
    {"name": "SCREEN-3", "gpio":  1, "type": "screen", "idx": 3},
    {"name": "NAV-BACK", "gpio": 16, "type": "nav",    "idx": -1},
    {"name": "NAV-NEXT", "gpio": 5, "type": "nav",    "idx": -1},
]

DEBOUNCE_MS = 30
HOLD_MS     = 600

# ── Init button pins ─────────────────────────────────────────────
print("\n[1] Configuring button pins...")
btn_pins = []
for b in BUTTONS:
    pin = Pin(b["gpio"], Pin.IN, Pin.PULL_UP)
    btn_pins.append(pin)
    state = pin.value()
    print(f"    GP{b['gpio']:2d}  {b['name']:12s}  reads: "
          f"{'HIGH (not pressed)' if state else 'LOW  (pressed or short!)'}")

print()
if all(p.value() == 1 for p in btn_pins):
    print("    ✓ All buttons read HIGH at rest — pull-ups working")
else:
    print("    ⚠ Some pins read LOW at rest — check for shorts to GND")

# ── ST7789 display init (confirmed pins) ─────────────────────────
print("\n[2] Initialising ST7789 button displays...")

BW, BH = 240, 300   # confirmed working dimensions

blk = Pin(13, Pin.OUT, value=1)   # shared BLK — must be HIGH
rst = Pin(15, Pin.OUT, value=1)   # shared RST

# Hold main display CS high to avoid bus conflicts
main_cs = Pin(6, Pin.OUT, value=1)

spi = SPI(0, baudrate=10_000_000,
          sck=Pin(18), mosi=Pin(19), miso=Pin(4))

BTN_PINS = [
    {"cs": Pin(7,  Pin.OUT, value=1), "dc": Pin(2,  Pin.OUT, value=1)},
    {"cs": Pin(8,  Pin.OUT, value=1), "dc": Pin(11, Pin.OUT, value=1)},
    {"cs": Pin(9,  Pin.OUT, value=1), "dc": Pin(14, Pin.OUT, value=1)},
    {"cs": Pin(10, Pin.OUT, value=1), "dc": Pin(21, Pin.OUT, value=1)},
]

PRESS_COLOURS   = [(92, 50, 200), (0, 180, 150), (220, 100, 0), (30, 180, 60)]
RELEASE_COLOURS = [(23, 12, 50),  (0, 45, 37),   (55, 25, 0),  (7, 45, 15)]

def btn_wc(cs, dc, c):
    dc.value(0); cs.value(0); spi.write(bytes([c])); cs.value(1)

def btn_wd(cs, dc, *args):
    dc.value(1); cs.value(0); spi.write(bytes(args)); cs.value(1)

def btn_init(cs, dc):
    wc = lambda c: btn_wc(cs, dc, c)
    wd = lambda *a: btn_wd(cs, dc, *a)
    wc(0x01); time.sleep_ms(150)
    wc(0x11); time.sleep_ms(255)
    wc(0x3A); wd(0x05)
    wc(0x36); wd(0x00)
    wc(0xB2); wd(0x0C, 0x0C, 0x00, 0x33, 0x33)
    wc(0xB7); wd(0x35)
    wc(0xBB); wd(0x19)
    wc(0xC0); wd(0x2C)
    wc(0xC2); wd(0x01)
    wc(0xC3); wd(0x12)
    wc(0xC4); wd(0x20)
    wc(0xC6); wd(0x0F)
    wc(0xD0); wd(0xA4, 0xA1)
    wc(0xE0); wd(0xD0,0x04,0x0D,0x11,0x13,0x2B,0x3F,0x54,
                   0x4C,0x18,0x0D,0x0B,0x1F,0x23)
    wc(0xE1); wd(0xD0,0x04,0x0C,0x11,0x13,0x2C,0x3F,0x44,
                   0x51,0x2F,0x1F,0x1F,0x20,0x23)
    wc(0x21); wc(0x13); time.sleep_ms(10)
    wc(0x29); time.sleep_ms(255)

def btn_fill(idx, r, g, b):
    cs = BTN_PINS[idx]["cs"]
    dc = BTN_PINS[idx]["dc"]
    c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    hi, lo = c >> 8, c & 0xFF
    chunk = bytes([hi, lo] * 128)
    total = BW * BH
    btn_wc(cs, dc, 0x2A); btn_wd(cs, dc, 0x00, 0x00, 0x00, BW - 1)
    btn_wc(cs, dc, 0x2B); btn_wd(cs, dc, 0x00, 0x00, (BH-1)>>8, (BH-1)&0xFF)
    btn_wc(cs, dc, 0x2C)
    dc.value(1); cs.value(0)
    for _ in range(total // 128): spi.write(chunk)
    rem = total % 128
    if rem: spi.write(bytes([hi, lo] * rem))
    cs.value(1)

# Reset all ST7789s together
rst.value(0); time.sleep_ms(20)
rst.value(1); time.sleep_ms(120)

displays_ready = []
for i, pins in enumerate(BTN_PINS):
    try:
        btn_init(pins["cs"], pins["dc"])
        r, g, b = RELEASE_COLOURS[i]
        btn_fill(i, r, g, b)
        displays_ready.append(i)
        print(f"    BTN-{i} ✓")
    except Exception as e:
        print(f"    BTN-{i} ✗ {e}")

if displays_ready:
    print(f"    ✓ {len(displays_ready)}/4 displays ready — visual feedback enabled")
else:
    print("    ✗ No displays — text-only mode")

# ── Live button test ─────────────────────────────────────────────
print("\n[3] Live button test — press each button (30 seconds)")
print("    Screen buttons light up their display when pressed")
print("    " + "-" * 44)

btn_state    = [1] * len(BUTTONS)
pressed_at   = [0] * len(BUTTONS)
hold_fired   = [False] * len(BUTTONS)
press_counts = [0] * len(BUTTONS)
start        = time.ticks_ms()

try:
    while time.ticks_diff(time.ticks_ms(), start) < 30_000:
        now = time.ticks_ms()
        for i, pin in enumerate(btn_pins):
            val = pin.value()

            if val != btn_state[i]:
                time.sleep_ms(DEBOUNCE_MS)
                val = pin.value()
                if val == btn_state[i]:
                    continue  # glitch

                btn_state[i] = val
                name = BUTTONS[i]["name"]
                idx  = BUTTONS[i]["idx"]

                if val == 0:  # pressed
                    pressed_at[i]   = now
                    hold_fired[i]   = False
                    press_counts[i] += 1
                    print(f"    PRESS   {name}")
                    if idx >= 0 and idx in displays_ready:
                        r, g, b = PRESS_COLOURS[idx]
                        btn_fill(idx, r, g, b)

                else:  # released
                    held = time.ticks_diff(now, pressed_at[i])
                    if not hold_fired[i]:
                        print(f"    RELEASE {name}  ({held} ms)")
                    if idx >= 0 and idx in displays_ready:
                        r, g, b = RELEASE_COLOURS[idx]
                        btn_fill(idx, r, g, b)

            elif val == 0:
                held = time.ticks_diff(now, pressed_at[i])
                if held >= HOLD_MS and not hold_fired[i]:
                    hold_fired[i] = True
                    name = BUTTONS[i]["name"]
                    idx  = BUTTONS[i]["idx"]
                    print(f"    HOLD    {name}  ({held} ms)")
                    if idx >= 0 and idx in displays_ready:
                        btn_fill(idx, 255, 255, 255)
                        time.sleep_ms(80)
                        r, g, b = PRESS_COLOURS[idx]
                        btn_fill(idx, r, g, b)

        time.sleep_ms(10)

except KeyboardInterrupt:
    print("\n    Stopped by user")

# ── Results ──────────────────────────────────────────────────────
print("\n[4] Results:")
all_ok = True
for i, b in enumerate(BUTTONS):
    count  = press_counts[i]
    status = "✓" if count > 0 else "✗ not pressed"
    print(f"    GP{b['gpio']:2d}  {b['name']:12s}  presses: {count}  {status}")
    if count == 0:
        all_ok = False

print()
if all_ok:
    print("    ✓ All 6 buttons detected!")
else:
    print("    ⚠ Some buttons not detected — check wiring")
    print("    One leg to GPIO pin, other leg to GND")

# ── Leave displays in dim idle state ─────────────────────────────
for i in displays_ready:
    r, g, b = RELEASE_COLOURS[i]
    btn_fill(i, r, g, b)

print()
print("=" * 48)
print("  TEST 5 COMPLETE")
print("  Next: Test 6 — full integration test")
print("=" * 48)
print()