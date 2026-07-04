# tests/test_10_buttons_mcp.py — Button Blasters
# TEST 10 — Physical buttons via MCP23008 GPIO expander
#
# Buttons are now wired to MCP23008, not Pico GPIO directly.
# MCP23008 is polled over I2C (GP26/GP27) at address 0x20.
#
# Button wiring (one leg → MCP GPIO pin, other leg → GND):
#   SCREEN-0 → MCP GP0  (pin 9)
#   SCREEN-1 → MCP GP1  (pin 10)
#   SCREEN-2 → MCP GP2  (pin 11)
#   SCREEN-3 → MCP GP3  (pin 12)
#   BACK/HOME → MCP GP4 (pin 13)
#
# MCP23008 internal pull-ups enabled — no external resistors needed.
# Pin reads HIGH (1) at rest, LOW (0) when button pressed.
#
# What this tests:
#   1. MCP23008 found on I2C bus
#   2. All 5 button pins configured as inputs with pull-ups
#   3. All read HIGH at rest
#   4. Each button press detected correctly
#   5. Visual feedback — ST7789 lights up when screen button pressed
#   6. Hold detection (600ms)
#   7. Simultaneous press detection
# ─────────────────────────────────────────────────────────────────

import time
from machine import I2C, SPI, Pin

print()
print("=" * 48)
print("  Button Blasters — TEST 10: Buttons via MCP23008")
print("=" * 48)

# ── MCP23008 registers ────────────────────────────────────────────
MCP_ADDR  = 0x20
IODIR     = 0x00
GPPU      = 0x06   # pull-up resistors
GPIO_REG  = 0x09

DEBOUNCE_MS = 30
HOLD_MS     = 600

BUTTON_MASK = 0x1F   # bits 0-4 = buttons 0-4

BUTTONS = [
    {"name": "SCREEN-0", "bit": 0, "type": "screen", "idx": 0},
    {"name": "SCREEN-1", "bit": 1, "type": "screen", "idx": 1},
    {"name": "SCREEN-2", "bit": 2, "type": "screen", "idx": 2},
    {"name": "SCREEN-3", "bit": 3, "type": "screen", "idx": 3},
    {"name": "BACK/HOME","bit": 4, "type": "nav",    "idx": -1},
]

# ── I2C + MCP23008 init ───────────────────────────────────────────
print("\n[1] I2C + MCP23008 init...")
try:
    i2c = I2C(1, sda=Pin(26), scl=Pin(27), freq=400_000)
    devices = i2c.scan()
    if MCP_ADDR not in devices:
        print(f"    ✗ MCP23008 not found — scan: {[hex(d) for d in devices]}")
        raise SystemExit
    print(f"    ✓ MCP23008 at 0x{MCP_ADDR:02X}")
except Exception as e:
    print(f"    ✗ I2C failed: {e}")
    raise SystemExit

def mcp_write(reg, val):
    i2c.writeto_mem(MCP_ADDR, reg, bytes([val]))

def mcp_read(reg):
    return i2c.readfrom_mem(MCP_ADDR, reg, 1)[0]

def read_buttons():
    """Read GPIO register. Returns byte — bit LOW = button pressed."""
    return mcp_read(GPIO_REG)

def btn_pressed(gpio_val, bit):
    """True if button bit is LOW (pressed)."""
    return not (gpio_val >> bit & 1)

# Configure button pins as inputs with pull-ups enabled
# Bits 0-4 = buttons, bits 5-7 = leave as outputs (other uses)
current_iodir = mcp_read(IODIR)
mcp_write(IODIR, current_iodir | BUTTON_MASK)   # bits 0-4 → inputs
mcp_write(GPPU,  BUTTON_MASK)                    # bits 0-4 → pull-ups on
print("    ✓ Button pins configured as inputs with pull-ups")

# ── Rest state check ──────────────────────────────────────────────
print("\n[2] Rest state check (all buttons should read HIGH)...")
time.sleep_ms(50)
gpio_val = read_buttons()
all_high = True
for b in BUTTONS:
    state = not btn_pressed(gpio_val, b["bit"])
    status = "HIGH ✓" if state else "LOW  ✗ (pressed or short!)"
    print(f"    MCP GP{b['bit']}  {b['name']:12s}  {status}")
    if not state:
        all_high = False

if all_high:
    print("    ✓ All buttons HIGH at rest — pull-ups working")
else:
    print("    ⚠ Some buttons read LOW — check wiring")
    print("    One leg → MCP GPIO pin, other leg → GND")

# ── ST7789 visual feedback (optional) ────────────────────────────
print("\n[3] Attempting ST7789 display init for visual feedback...")

BW, BH = 240, 300
PRESS_COLOURS   = [(92,50,200),(0,180,150),(220,100,0),(30,180,60)]
RELEASE_COLOURS = [(23,12,50),(0,45,37),(55,25,0),(7,45,15)]

displays_ready = []
blk = None
spi_obj = None
BTN_PINS = []

try:
    blk     = Pin(13, Pin.OUT, value=1)
    main_cs = Pin(6,  Pin.OUT, value=1)
    rst     = Pin(15, Pin.OUT, value=1)
    spi_obj = SPI(0, baudrate=10_000_000,
                  sck=Pin(18), mosi=Pin(19), miso=Pin(4))

    BTN_PINS = [
        {"cs": Pin(7,  Pin.OUT, value=1), "dc": Pin(2,  Pin.OUT, value=1)},
        {"cs": Pin(8,  Pin.OUT, value=1), "dc": Pin(11, Pin.OUT, value=1)},
        {"cs": Pin(9,  Pin.OUT, value=1), "dc": Pin(14, Pin.OUT, value=1)},
        {"cs": Pin(10, Pin.OUT, value=1), "dc": Pin(21, Pin.OUT, value=1)},
    ]

    def btn_wc(cs, dc, c):
        dc.value(0); cs.value(0); spi_obj.write(bytes([c])); cs.value(1)

    def btn_wd(cs, dc, *args):
        dc.value(1); cs.value(0); spi_obj.write(bytes(args)); cs.value(1)

    def btn_fill(idx, r, g, b):
        cs = BTN_PINS[idx]["cs"]; dc = BTN_PINS[idx]["dc"]
        c = ((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)
        hi, lo = c>>8, c&0xFF
        chunk = bytes([hi,lo]*128); total = BW*BH
        btn_wc(cs,dc,0x2A); btn_wd(cs,dc,0x00,0x00,0x00,BW-1)
        btn_wc(cs,dc,0x2B); btn_wd(cs,dc,0x00,0x00,(BH-1)>>8,(BH-1)&0xFF)
        btn_wc(cs,dc,0x2C)
        dc.value(1); cs.value(0)
        for _ in range(total//128): spi_obj.write(chunk)
        if total%128: spi_obj.write(bytes([hi,lo]*(total%128)))
        cs.value(1)

    rst.value(0); time.sleep_ms(20)
    rst.value(1); time.sleep_ms(120)

    for i, pins in enumerate(BTN_PINS):
        cs = pins["cs"]; dc = pins["dc"]
        wc = lambda c,cs=cs,dc=dc: btn_wc(cs,dc,c)
        wd = lambda *a,cs=cs,dc=dc: btn_wd(cs,dc,*a)
        wc(0x01); time.sleep_ms(150)
        wc(0x11); time.sleep_ms(255)
        wc(0x3A); wd(0x05)
        wc(0x36); wd(0x00)
        wc(0xB2); wd(0x0C,0x0C,0x00,0x33,0x33)
        wc(0xB7); wd(0x35)
        wc(0xBB); wd(0x19)
        wc(0xC0); wd(0x2C)
        wc(0xC2); wd(0x01)
        wc(0xC3); wd(0x12)
        wc(0xC4); wd(0x20)
        wc(0xC6); wd(0x0F)
        wc(0xD0); wd(0xA4,0xA1)
        wc(0xE0); wd(0xD0,0x04,0x0D,0x11,0x13,0x2B,0x3F,0x54,
                       0x4C,0x18,0x0D,0x0B,0x1F,0x23)
        wc(0xE1); wd(0xD0,0x04,0x0C,0x11,0x13,0x2C,0x3F,0x44,
                       0x51,0x2F,0x1F,0x1F,0x20,0x23)
        wc(0x21); wc(0x13); time.sleep_ms(10)
        wc(0x29); time.sleep_ms(255)
        r,g,b = RELEASE_COLOURS[i]
        btn_fill(i, r, g, b)
        displays_ready.append(i)
        print(f"    BTN-{i} display ✓")

except Exception as e:
    print(f"    ⚠ Display init failed ({e}) — text-only mode")

# ── Live button test ──────────────────────────────────────────────
print("\n[4] Live button test — press each button (30 seconds)")
if displays_ready:
    print("    Screen buttons light up matching display when pressed")
print("    " + "-" * 44)

btn_state    = [True] * len(BUTTONS)   # True = not pressed
pressed_at   = [0]    * len(BUTTONS)
hold_fired   = [False]* len(BUTTONS)
press_counts = [0]    * len(BUTTONS)
start        = time.ticks_ms()

try:
    while time.ticks_diff(time.ticks_ms(), start) < 30_000:
        now      = time.ticks_ms()
        gpio_val = read_buttons()

        for i, b in enumerate(BUTTONS):
            pressed = btn_pressed(gpio_val, b["bit"])

            if pressed != (not btn_state[i]):
                time.sleep_ms(DEBOUNCE_MS)
                gpio_val2 = read_buttons()
                pressed = btn_pressed(gpio_val2, b["bit"])

                if pressed == (not btn_state[i]):
                    continue   # glitch

                btn_state[i] = not pressed

                if pressed:
                    pressed_at[i]   = now
                    hold_fired[i]   = False
                    press_counts[i] += 1
                    print(f"    PRESS   {b['name']}")
                    if b["idx"] >= 0 and b["idx"] in displays_ready:
                        r,g,bl = PRESS_COLOURS[b["idx"]]
                        btn_fill(b["idx"], r, g, bl)
                else:
                    held = time.ticks_diff(now, pressed_at[i])
                    if not hold_fired[i]:
                        print(f"    RELEASE {b['name']}  ({held}ms)")
                    if b["idx"] >= 0 and b["idx"] in displays_ready:
                        r,g,bl = RELEASE_COLOURS[b["idx"]]
                        btn_fill(b["idx"], r, g, bl)

            elif pressed:
                held = time.ticks_diff(now, pressed_at[i])
                if held >= HOLD_MS and not hold_fired[i]:
                    hold_fired[i] = True
                    print(f"    HOLD    {b['name']}  ({held}ms)")
                    if b["idx"] >= 0 and b["idx"] in displays_ready:
                        btn_fill(b["idx"], 255, 255, 255)
                        time.sleep_ms(80)
                        r,g,bl = PRESS_COLOURS[b["idx"]]
                        btn_fill(b["idx"], r, g, bl)

        time.sleep_ms(10)

except KeyboardInterrupt:
    print("\n    Stopped by user")

# ── Results ───────────────────────────────────────────────────────
print("\n[5] Results:")
all_ok = True
for i, b in enumerate(BUTTONS):
    count  = press_counts[i]
    status = "✓" if count > 0 else "✗ not detected"
    print(f"    MCP GP{b['bit']}  {b['name']:12s}  presses: {count}  {status}")
    if count == 0:
        all_ok = False

print()
if all_ok:
    print("    ✓ All 5 buttons detected via MCP23008!")
else:
    print("    ⚠ Some buttons not detected — check wiring:")
    print("    One leg → MCP GP0-GP4 (pins 9-13 on chip)")
    print("    Other leg → GND")
    print("    Pull-ups enabled in firmware — no resistors needed")

# Leave displays in dim idle state
for i in displays_ready:
    r,g,b = RELEASE_COLOURS[i]
    btn_fill(i, r, g, b)

print()
print("=" * 48)
print("  TEST 10 COMPLETE")
print("  Next: update firmware drivers for MCP23008 buttons")
print("=" * 48)
print()
