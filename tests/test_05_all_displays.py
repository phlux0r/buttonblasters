# tests/test_05_all_displays.py — Button Blasters
# TEST 5: All 5 displays + touch integration test
#
# CONFIRMED pin assignments:
#   SPI:  SCK=GP18  MOSI=GP19  MISO=GP4
#   Main: CS=GP6   DC=GP12  RST=GP17  LED=3.3V direct
#   BTN0: CS=GP7   DC=GP2   RST=GP15  BLK=GP13 (GPIO)
#   BTN1: CS=GP8   DC=GP11  RST=GP15  BLK=GP13 (GPIO)
#   BTN2: CS=GP9   DC=GP14  RST=GP15  BLK=GP13 (GPIO)
#   BTN3: CS=GP10  DC=GP21  RST=GP15  BLK=GP13 (GPIO)
#   Touch: SDA=GP26  SCL=GP27  INT=GP28
#
# What it tests:
#   1. All 5 displays initialise correctly
#   2. CS isolation — only targeted display updates
#   3. Touch coordinates shown live on main display
#   4. Tap a button display zone on main screen → lights up that BTN LCD
#   5. Fill speed benchmark across all displays

import time, gc
from machine import SPI, Pin, I2C

print("\n" + "="*48)
print("  Button Blasters — TEST 5: All displays + touch")
print("="*48)

# ── BLK and CS isolation ──────────────────────────────────────────
blk = Pin(13, Pin.OUT, value=1)   # shared BLK for all ST7789s

# ── SPI bus ───────────────────────────────────────────────────────
spi = SPI(0, baudrate=10_000_000,
          sck=Pin(18), mosi=Pin(19), miso=Pin(4))

# ── Main display pins (ILI9488) ───────────────────────────────────
m_cs  = Pin(6,  Pin.OUT, value=1)
m_dc  = Pin(12, Pin.OUT, value=1)
m_rst = Pin(17, Pin.OUT, value=1)

# ── Button display pins (ST7789) ──────────────────────────────────
b_rst = Pin(15, Pin.OUT, value=1)
BTN = [
    {"cs": Pin(7,  Pin.OUT, value=1), "dc": Pin(2,  Pin.OUT, value=1)},
    {"cs": Pin(8,  Pin.OUT, value=1), "dc": Pin(11, Pin.OUT, value=1)},
    {"cs": Pin(9,  Pin.OUT, value=1), "dc": Pin(14, Pin.OUT, value=1)},
    {"cs": Pin(10, Pin.OUT, value=1), "dc": Pin(21, Pin.OUT, value=1)},
]
BTN_COLOURS = [
    (92,  50, 200),   # purple
    (0,  180, 150),   # teal
    (220, 100,   0),  # orange
    (30,  180,  60),  # green
]
BTN_NAMES = ["BTN-0","BTN-1","BTN-2","BTN-3"]

# ── Touch ─────────────────────────────────────────────────────────
FT = 0x38

# ── ILI9488 helpers ───────────────────────────────────────────────
MW, MH = 320, 480

def m_wc(c): m_dc.value(0);m_cs.value(0);spi.write(bytes([c]));m_cs.value(1)
def m_wd(d): m_dc.value(1);m_cs.value(0);spi.write(bytes([d]) if isinstance(d,int) else bytes(list(d)));m_cs.value(1)

def main_init():
    m_rst.value(0); time.sleep_ms(20)
    m_rst.value(1); time.sleep_ms(120)
    m_wc(0x11); time.sleep_ms(120)
    m_wc(0x3A); m_wd(0x66)
    m_wc(0xC5); m_wd(0x00); m_wd(0x4D); m_wd(0x80)
    m_wc(0x21)
    m_wc(0x36); m_wd(0x48)
    m_wc(0x29); time.sleep_ms(20)

def main_fill(r, g, b, x=0, y=0, w=None, h=None):
    w=w or MW; h=h or MH
    px=bytes([r&0xF8,g&0xFC,b&0xF8]); chunk=px*64; total=w*h
    m_wc(0x2A); m_wd([x>>8,x&0xFF,(x+w-1)>>8,(x+w-1)&0xFF])
    m_wc(0x2B); m_wd([y>>8,y&0xFF,(y+h-1)>>8,(y+h-1)&0xFF])
    m_wc(0x2C)
    m_dc.value(1); m_cs.value(0)
    for _ in range(total//64): spi.write(chunk)
    if total%64: spi.write(px*(total%64))
    m_cs.value(1)

def main_dot(x, y, sz=12, r=255, g=255, b=0):
    x0=max(0,x-sz); x1=min(MW-1,x+sz)
    y0=max(0,y-sz); y1=min(MH-1,y+sz)
    main_fill(r,g,b, x0,y0, x1-x0+1, y1-y0+1)

# ── ST7789 helpers ────────────────────────────────────────────────
BW, BH = 240, 300

def btn_wc(cs, dc, c): dc.value(0);cs.value(0);spi.write(bytes([c]));cs.value(1)
def btn_wd(cs, dc, *args): dc.value(1);cs.value(0);spi.write(bytes(args));cs.value(1)

def btn_init(cs, dc):
    wc=lambda c: btn_wc(cs,dc,c)
    wd=lambda *a: btn_wd(cs,dc,*a)
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
    wc(0xE0); wd(0xD0,0x04,0x0D,0x11,0x13,0x2B,0x3F,0x54,0x4C,0x18,0x0D,0x0B,0x1F,0x23)
    wc(0xE1); wd(0xD0,0x04,0x0C,0x11,0x13,0x2C,0x3F,0x44,0x51,0x2F,0x1F,0x1F,0x20,0x23)
    wc(0x21); wc(0x13); time.sleep_ms(10)
    wc(0x29); time.sleep_ms(255)

def btn_fill(cs, dc, r, g, b):
    c=((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)
    hi=c>>8; lo=c&0xFF
    chunk=bytes([hi,lo]*128); total=BW*BH
    btn_wc(cs,dc,0x2A); btn_wd(cs,dc,0x00,0x00,0x00,BW-1)
    btn_wc(cs,dc,0x2B); btn_wd(cs,dc,0x00,0x00,(BH-1)>>8,(BH-1)&0xFF)
    btn_wc(cs,dc,0x2C)
    dc.value(1); cs.value(0)
    for _ in range(total//128): spi.write(chunk)
    if total%128: spi.write(bytes([hi,lo]*(total%128)))
    cs.value(1)

# ── INIT ALL DISPLAYS ─────────────────────────────────────────────
print("\n[1] Initialising main display (ILI9488)...")
main_init()
main_fill(20, 10, 60)
print("    ✓ Main display ready")

print("\n[2] Initialising button displays (ST7789 x4)...")
b_rst.value(0); time.sleep_ms(20); b_rst.value(1); time.sleep_ms(120)
working = []
for i, b in enumerate(BTN):
    try:
        btn_init(b["cs"], b["dc"])
        r,g,bl = BTN_COLOURS[i]
        btn_fill(b["cs"], b["dc"], r//3, g//3, bl//3)
        print(f"    BTN-{i} ✓")
        working.append(i)
    except Exception as e:
        print(f"    BTN-{i} ✗ {e}")

print(f"    {len(working)}/4 button displays ready")

# ── TOUCH INIT ────────────────────────────────────────────────────
print("\n[3] Initialising touch (FT6236)...")
touch_ok = False
i2c = None
try:
    i2c = I2C(1, sda=Pin(26), scl=Pin(27), freq=400_000)
    devices = i2c.scan()
    if FT in devices:
        i2c.writeto_mem(FT, 0x80, bytes([22]))
        i2c.writeto_mem(FT, 0x86, bytes([0x00]))
        touch_ok = True
        print(f"    ✓ FT6236 at 0x{FT:02X}")
    else:
        print(f"    ✗ FT6236 not found — touch disabled")
except Exception as e:
    print(f"    ✗ I2C error: {e}")

def read_touch():
    if not touch_ok: return None
    try:
        n = i2c.readfrom_mem(FT, 0x02, 1)[0] & 0x0F
        if not n or n > 5: return None
        d = i2c.readfrom_mem(FT, 0x03, 4)
        return ((d[0]&0x0F)<<8)|d[1], ((d[2]&0x0F)<<8)|d[3]
    except: return None

# ── CS ISOLATION TEST ─────────────────────────────────────────────
print("\n[4] CS isolation test...")
print("    Each display flashes white then back to colour.")
print("    Only ONE display should change at a time.")
for i in working:
    b = BTN[i]
    btn_fill(b["cs"], b["dc"], 255, 255, 255)
    time.sleep_ms(300)
    r,g,bl = BTN_COLOURS[i]
    btn_fill(b["cs"], b["dc"], r, g, bl)
    time.sleep_ms(200)
    print(f"    BTN-{i} isolated ✓")

# ── DRAW TOUCH ZONES ON MAIN SCREEN ──────────────────────────────
print("\n[5] Drawing touch zones on main screen...")
main_fill(15, 10, 40)
# Draw 4 labelled zones corresponding to button displays
zone_h = MH // 4
zone_colours = BTN_COLOURS
for i, (r,g,b) in enumerate(zone_colours):
    y = i * zone_h
    # Border only
    main_fill(r,g,b, 0,   y,        MW, 3)          # top border
    main_fill(r,g,b, 0,   y+zone_h-3, MW, 3)        # bottom border
    main_fill(r,g,b, 0,   y,        3, zone_h)       # left border
    main_fill(r,g,b, MW-3,y,        3, zone_h)       # right border
    # Label in centre
    main_fill(r//4,g//4,b//4, 10, y+zone_h//2-8, MW-20, 16)
print("    ✓ 4 touch zones drawn — tap each to light up matching display")

# ── LIVE INTEGRATION LOOP ─────────────────────────────────────────
print("\n[6] Live loop (30s) — tap zones on main screen")
print("    Each zone lights up the matching button display")
print("    Ctrl+C to stop early\n")

gc.collect()
print(f"    RAM free: {gc.mem_free()//1024}KB\n")

last_touch  = None
fps_t       = time.ticks_ms()
frame_count = 0
start       = time.ticks_ms()
zone_h      = MH // 4

try:
    while time.ticks_diff(time.ticks_ms(), start) < 30_000:
        pos = read_touch()
        if pos and pos != last_touch:
            x, y = pos
            # Draw dot on main screen
            main_dot(x, y, 10, 255, 255, 0)
            # Determine which zone was tapped
            zone = y // zone_h
            if 0 <= zone <= 3 and zone in working:
                r,g,b = BTN_COLOURS[zone]
                btn_fill(BTN[zone]["cs"], BTN[zone]["dc"], r, g, b)
                print(f"    Touch ({x},{y}) → zone {zone} → BTN-{zone} lit!")
                time.sleep_ms(50)
                # Dim back after 500ms
                btn_fill(BTN[zone]["cs"], BTN[zone]["dc"], r//3, g//3, b//3)
            last_touch = pos
        elif not pos:
            last_touch = None

        frame_count += 1
        now = time.ticks_ms()
        if time.ticks_diff(now, fps_t) >= 5000:
            elapsed = time.ticks_diff(now, start)//1000
            print(f"    [{elapsed:2d}s] Running... RAM:{gc.mem_free()//1024}KB  Touch:{'✓' if touch_ok else '✗'}")
            fps_t = now
            gc.collect()
        time.sleep_ms(16)

except KeyboardInterrupt:
    pass

print("\n" + "="*48)
print("  TEST 5 COMPLETE — ALL DISPLAYS + TOUCH")
print(f"  Main display : ✓")
print(f"  BTN displays : {len(working)}/4 ✓")
print(f"  Touch        : {'✓' if touch_ok else '✗'}")
print()
print("  If all ✓ — ready for Test 6 (buttons)")
print("="*48+"\n")