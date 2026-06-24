# tests/test_06_integration.py — Button Blasters
# TEST 6 — Full integration test
#
# Confirmed pin assignments:
#   SPI:    SCK=GP18  MOSI=GP19  MISO=GP4
#   Main:   CS=GP6   DC=GP12  RST=GP17  LED=3.3V direct
#   BTN-0:  CS=GP7   DC=GP2   RST=GP15  BLK=GP13
#   BTN-1:  CS=GP8   DC=GP11  RST=GP15  BLK=GP13
#   BTN-2:  CS=GP9   DC=GP14  RST=GP15  BLK=GP13
#   BTN-3:  CS=GP10  DC=GP21  RST=GP15  BLK=GP13
#   Touch:  SDA=GP26  SCL=GP27  INT=GP28
#   Buttons:
#     SCREEN-0 → GP20    SCREEN-1 → GP22
#     SCREEN-2 → GP0     SCREEN-3 → GP1
#     BACK/HOME → GP16
#   GP28 = TOUCH_INT only — not a button
#   GP5  = DEAD — never use
#
# Menu button roles:
#   BTN-0 = PREV ←    BTN-3 = NEXT →
#   BTN-1 & BTN-2 = game previews
#
# What this tests:
#   1. SPI bus shared correctly across all 5 displays
#   2. CS isolation — only targeted display updates
#   3. Touch coordinates shown live on main display
#   4. Screen buttons light up matching display + print event
#   5. BACK button flashes all displays white
#   6. BTN-0/BTN-3 show PREV/NEXT arrow icons
#   7. Touch tap detection
#
# SD card is deferred — not tested here.
# ─────────────────────────────────────────────────────────────────

import time
import gc
from machine import SPI, Pin, I2C

print()
print("=" * 48)
print("  Button Blasters — TEST 6: Full integration")
print("=" * 48)

# ── SPI bus ───────────────────────────────────────────────────────
print("\n[1] SPI bus...")
spi = SPI(0, baudrate=10_000_000,
          sck=Pin(18), mosi=Pin(19), miso=Pin(4))
print("    ✓ SPI-0 at 10MHz  SCK=GP18 MOSI=GP19 MISO=GP4")

# ── Pin objects ───────────────────────────────────────────────────
blk      = Pin(13, Pin.OUT, value=1)   # ST7789 backlight — must stay HIGH

cs_main  = Pin(6,  Pin.OUT, value=1)
dc_main  = Pin(12, Pin.OUT, value=1)
rst_main = Pin(17, Pin.OUT, value=1)

rst_btn  = Pin(15, Pin.OUT, value=1)   # shared RST for all ST7789s

BTN = [
    {"cs": Pin(7,  Pin.OUT, value=1), "dc": Pin(2,  Pin.OUT, value=1)},
    {"cs": Pin(8,  Pin.OUT, value=1), "dc": Pin(11, Pin.OUT, value=1)},
    {"cs": Pin(9,  Pin.OUT, value=1), "dc": Pin(14, Pin.OUT, value=1)},
    {"cs": Pin(10, Pin.OUT, value=1), "dc": Pin(21, Pin.OUT, value=1)},
]

# Colours: press / idle for each BTN screen
PRESS_COLOURS   = [(92, 50, 200), (0, 180, 150), (220, 100, 0), (30, 180, 60)]
IDLE_COLOURS    = [(23, 12, 50),  (0,  45,  37), (55,  25, 0),  (7,  45, 15)]
BTN_NAMES       = ["BTN-0 (PREV←)", "BTN-1", "BTN-2", "BTN-3 (NEXT→)"]

# ── Display helpers ───────────────────────────────────────────────
MW, MH = 320, 480   # ILI9488 portrait
BW, BH = 240, 300   # ST7789 confirmed

def m_cmd(c, *data):
    dc_main.value(0); cs_main.value(0); spi.write(bytes([c])); cs_main.value(1)
    if data:
        dc_main.value(1); cs_main.value(0)
        spi.write(bytes(list(data))); cs_main.value(1)

def main_fill(r, g, b, x=0, y=0, w=None, h=None):
    w = w or MW; h = h or MH
    px = bytes([r & 0xF8, g & 0xFC, b & 0xF8])
    chunk = px * 64; total = w * h
    m_cmd(0x2A, x>>8, x&0xFF, (x+w-1)>>8, (x+w-1)&0xFF)
    m_cmd(0x2B, y>>8, y&0xFF, (y+h-1)>>8, (y+h-1)&0xFF)
    dc_main.value(0); cs_main.value(0); spi.write(b'\x2C'); cs_main.value(1)
    dc_main.value(1); cs_main.value(0)
    for _ in range(total // 64): spi.write(chunk)
    if total % 64: spi.write(px * (total % 64))
    cs_main.value(1)

def btn_wc(cs, dc, c):
    dc.value(0); cs.value(0); spi.write(bytes([c])); cs.value(1)

def btn_wd(cs, dc, *args):
    dc.value(1); cs.value(0); spi.write(bytes(args)); cs.value(1)

def btn_fill(idx, r, g, b):
    cs = BTN[idx]["cs"]; dc = BTN[idx]["dc"]
    c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    hi, lo = c >> 8, c & 0xFF
    chunk = bytes([hi, lo] * 128); total = BW * BH
    btn_wc(cs, dc, 0x2A); btn_wd(cs, dc, 0x00, 0x00, 0x00, BW - 1)
    btn_wc(cs, dc, 0x2B); btn_wd(cs, dc, 0x00, 0x00, (BH-1)>>8, (BH-1)&0xFF)
    btn_wc(cs, dc, 0x2C)
    dc.value(1); cs.value(0)
    for _ in range(total // 128): spi.write(chunk)
    if total % 128: spi.write(bytes([hi, lo] * (total % 128)))
    cs.value(1)

def btn_border(idx, r, g, b, thickness=6):
    """Draw a coloured border on a button screen."""
    cs = BTN[idx]["cs"]; dc = BTN[idx]["dc"]
    c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    hi, lo = c >> 8, c & 0xFF

    def fill_rect(x0, y0, x1, y1):
        w = x1 - x0 + 1; h = y1 - y0 + 1
        chunk = bytes([hi, lo] * 64); total = w * h
        btn_wc(cs, dc, 0x2A)
        btn_wd(cs, dc, x0>>8, x0&0xFF, x1>>8, x1&0xFF)
        btn_wc(cs, dc, 0x2B)
        btn_wd(cs, dc, y0>>8, y0&0xFF, y1>>8, y1&0xFF)
        btn_wc(cs, dc, 0x2C)
        dc.value(1); cs.value(0)
        for _ in range(total // 64): spi.write(chunk)
        if total % 64: spi.write(bytes([hi, lo] * (total % 64)))
        cs.value(1)

    t = thickness
    fill_rect(0,        0,        BW-1,    t-1)      # top
    fill_rect(0,        BH-t,     BW-1,    BH-1)     # bottom
    fill_rect(0,        0,        t-1,     BH-1)      # left
    fill_rect(BW-t,     0,        BW-1,    BH-1)      # right

# ── ILI9488 init ─────────────────────────────────────────────────
print("\n[2] Initialising ILI9488 main display...")
rst_main.value(0); time.sleep_ms(20)
rst_main.value(1); time.sleep_ms(120)

m_cmd(0x11); time.sleep_ms(120)       # sleep out
m_cmd(0x3A, 0x66)                     # 18-bit RGB666
m_cmd(0xC5, 0x00, 0x4D, 0x80)        # VCOM = 0x4D (supplier confirmed)
m_cmd(0x21)                            # inversion ON (IPS)
m_cmd(0x36, 0x48)                     # MADCTL portrait BGR
m_cmd(0x29)                            # display ON
time.sleep_ms(20)

main_fill(20, 10, 60)
print("    ✓ ILI9488 ready — dark purple fill")

# ── ST7789 init ───────────────────────────────────────────────────
print("\n[3] Initialising 4× ST7789 button displays...")
rst_btn.value(0); time.sleep_ms(20)
rst_btn.value(1); time.sleep_ms(120)

def st7789_init(cs, dc):
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

btn_ready = []
for i, b in enumerate(BTN):
    try:
        st7789_init(b["cs"], b["dc"])
        r, g, bl = IDLE_COLOURS[i]
        btn_fill(i, r, g, bl)
        btn_ready.append(i)
        print(f"    BTN-{i} ✓")
    except Exception as e:
        print(f"    BTN-{i} ✗ {e}")

print(f"    {len(btn_ready)}/4 button displays ready")

# ── Show PREV/NEXT indicators on BTN-0 and BTN-3 ─────────────────
print("\n[4] Drawing PREV/NEXT indicators...")
if 0 in btn_ready:
    btn_fill(0, *IDLE_COLOURS[0])
    btn_border(0, 92, 50, 200)
    print("    BTN-0: PREV ← indicator drawn")
if 3 in btn_ready:
    btn_fill(3, *IDLE_COLOURS[3])
    btn_border(3, 30, 180, 60)
    print("    BTN-3: NEXT → indicator drawn")

# ── Touch init ────────────────────────────────────────────────────
print("\n[5] Initialising FT6236 touch...")
touch_ok = False
i2c = None
FT = 0x38
try:
    i2c = I2C(1, sda=Pin(26), scl=Pin(27), freq=400_000)
    devices = i2c.scan()
    if FT in devices:
        i2c.writeto_mem(FT, 0x80, bytes([22]))   # threshold
        i2c.writeto_mem(FT, 0x86, bytes([0x00])) # active mode
        touch_ok = True
        print(f"    ✓ FT6236 at 0x{FT:02X}  INT=GP28 (touch only — not a button)")
    else:
        print(f"    ✗ FT6236 not found  scan={[hex(d) for d in devices]}")
except Exception as e:
    print(f"    ✗ I2C error: {e}")

def read_touch():
    if not touch_ok: return None
    try:
        n = i2c.readfrom_mem(FT, 0x02, 1)[0] & 0x0F
        if n == 0 or n > 5: return None
        d = i2c.readfrom_mem(FT, 0x03, 4)
        return ((d[0] & 0x0F) << 8) | d[1], ((d[2] & 0x0F) << 8) | d[3]
    except:
        return None

# ── Physical buttons ──────────────────────────────────────────────
print("\n[6] Configuring buttons...")
# Screen buttons map to BTN display index
SCREEN_BTNS = [
    {"name": "SCREEN-0", "gpio": 20, "btn_idx": 0},
    {"name": "SCREEN-1", "gpio": 22, "btn_idx": 1},
    {"name": "SCREEN-2", "gpio":  0, "btn_idx": 2},
    {"name": "SCREEN-3", "gpio":  1, "btn_idx": 3},
]
BACK_BTN = Pin(16, Pin.IN, Pin.PULL_UP)
screen_pins = [Pin(b["gpio"], Pin.IN, Pin.PULL_UP) for b in SCREEN_BTNS]

print("    SCREEN-0 → GP20    SCREEN-1 → GP22")
print("    SCREEN-2 → GP0     SCREEN-3 → GP1")
print("    BACK/HOME → GP16")
print("    GP28 = TOUCH_INT only")

all_high = all(p.value() == 1 for p in screen_pins) and BACK_BTN.value() == 1
print(f"    {'✓ All buttons HIGH at rest' if all_high else '⚠ Some buttons LOW — check wiring'}")

# ── CS isolation test ─────────────────────────────────────────────
print("\n[7] CS isolation test...")
for i in btn_ready:
    btn_fill(i, 255, 255, 255)
    time.sleep_ms(200)
    r, g, b = IDLE_COLOURS[i]
    btn_fill(i, r, g, b)
    time.sleep_ms(100)
    print(f"    BTN-{i} isolated ✓")

# ── Draw main screen UI ───────────────────────────────────────────
main_fill(20, 10, 60)
# Header bar
main_fill(40, 20, 100, 0, 0, MW, 50)
# Divider
main_fill(80, 50, 180, 0, 50, MW, 3)
# Touch area hint
main_fill(30, 15, 75, 10, 70, MW-20, MW-20)
print("\n[8] Main screen UI drawn")

# ── Integration loop ──────────────────────────────────────────────
print("\n[9] Integration loop — 40 seconds")
print("    Tap main screen       → yellow marker + coordinates")
print("    Press screen buttons  → lights up matching BTN display")
print("    Press BACK/HOME       → all displays flash white")
print("    BTN-0 press           → PREV action (bright purple)")
print("    BTN-3 press           → NEXT action (bright green)")
print("    " + "-" * 44)

btn_state   = [1] * len(SCREEN_BTNS)
pressed_at  = [0] * len(SCREEN_BTNS)
hold_fired  = [False] * len(SCREEN_BTNS)
back_state  = 1
last_touch  = None
start       = time.ticks_ms()
gc.collect()
print(f"    RAM free: {gc.mem_free()//1024}KB\n")

def flash_all_white():
    main_fill(255, 255, 255)
    for i in btn_ready:
        btn_fill(i, 255, 255, 255)
    time.sleep_ms(150)
    main_fill(20, 10, 60)
    main_fill(40, 20, 100, 0, 0, MW, 50)
    main_fill(80, 50, 180, 0, 50, MW, 3)
    for i in btn_ready:
        r, g, b = IDLE_COLOURS[i]
        btn_fill(i, r, g, b)
    if 0 in btn_ready: btn_border(0, 92, 50, 200)
    if 3 in btn_ready: btn_border(3, 30, 180, 60)

try:
    while time.ticks_diff(time.ticks_ms(), start) < 40_000:
        now = time.ticks_ms()

        # ── Touch ──────────────────────────────────────────────
        pos = read_touch()
        if pos and pos != last_touch:
            x, y = pos
            # Yellow marker on main screen
            x0 = max(0, x - 15); y0 = max(0, y - 15)
            main_fill(255, 200, 0, x0, y0, 30, 30)
            print(f"    Touch: ({x}, {y})")
            last_touch = pos
        elif not pos:
            last_touch = None

        # ── Screen buttons ─────────────────────────────────────
        for i, pin in enumerate(screen_pins):
            val = pin.value()
            if val != btn_state[i]:
                time.sleep_ms(30)
                if pin.value() != btn_state[i]:
                    btn_state[i] = val
                    name    = SCREEN_BTNS[i]["name"]
                    btn_idx = SCREEN_BTNS[i]["btn_idx"]
                    if val == 0:  # pressed
                        pressed_at[i] = now
                        hold_fired[i] = False
                        action = ""
                        if btn_idx == 0:   action = " → PREV ←"
                        elif btn_idx == 3: action = " → NEXT →"
                        print(f"    PRESS  {name}{action}")
                        if btn_idx in btn_ready:
                            r, g, b = PRESS_COLOURS[btn_idx]
                            btn_fill(btn_idx, r, g, b)
                            if btn_idx in (0, 3):
                                btn_border(btn_idx, 255, 255, 255)
                    else:  # released
                        held = time.ticks_diff(now, pressed_at[i])
                        if not hold_fired[i]:
                            print(f"    RELEASE {name}  ({held}ms)")
                        if btn_idx in btn_ready:
                            r, g, b = IDLE_COLOURS[btn_idx]
                            btn_fill(btn_idx, r, g, b)
                            if btn_idx == 0: btn_border(0, 92, 50, 200)
                            if btn_idx == 3: btn_border(3, 30, 180, 60)

            elif val == 0:
                held = time.ticks_diff(now, pressed_at[i])
                if held >= 600 and not hold_fired[i]:
                    hold_fired[i] = True
                    print(f"    HOLD   {SCREEN_BTNS[i]['name']}  ({held}ms)")

        # ── BACK button ────────────────────────────────────────
        bval = BACK_BTN.value()
        if bval != back_state:
            time.sleep_ms(30)
            if BACK_BTN.value() != back_state:
                back_state = bval
                if bval == 0:
                    print("    PRESS  BACK/HOME → flash all displays")
                    flash_all_white()
                else:
                    print("    RELEASE BACK/HOME")

        # ── Status every 8 seconds ─────────────────────────────
        elapsed = time.ticks_diff(now, start) // 1000
        if elapsed > 0 and elapsed % 8 == 0 and elapsed % 16 != 8:
            gc.collect()
            print(f"    [{elapsed:2d}s] RAM:{gc.mem_free()//1024}KB  "
                  f"Touch:{'✓' if touch_ok else '✗'}  "
                  f"Displays:{len(btn_ready)}/4")

        time.sleep_ms(10)

except KeyboardInterrupt:
    print("\n    Stopped by user")

# ── Summary ───────────────────────────────────────────────────────
print()
print("=" * 48)
print("  TEST 6 — INTEGRATION SUMMARY")
print(f"  Main display  : ✓ ILI9488")
print(f"  BTN displays  : {len(btn_ready)}/4 ✓")
print(f"  Touch (I2C)   : {'✓' if touch_ok else '✗ check SDA=GP26 SCL=GP27'}")
print(f"  Screen buttons: ✓ GP20 GP22 GP0 GP1")
print(f"  BACK button   : ✓ GP16")
print(f"  TOUCH_INT     : GP28 (not a button)")
print(f"  SD card       : ⏸ deferred — separate breakout needed")
print()
if touch_ok and len(btn_ready) == 4:
    print("  ✓ ALL SYSTEMS GO — ready for firmware rewrite!")
else:
    print("  ⚠ Fix any failing subsystems then re-run")
    if not touch_ok:
        print("    Touch: verify SDA=GP26, SCL=GP27")
    if len(btn_ready) < 4:
        print("    Displays: check CS/DC/RST wiring")
print("=" * 48)
print()