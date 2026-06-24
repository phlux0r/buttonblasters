# tests/test_03c_axis_finder.py — Button Blasters
# TEST 3c: Axis finder — NO display reinit
#
# IMPORTANT: Run test_02_working.py FIRST, let it show colours,
# press Ctrl+C to stop it, then immediately run this script.
# This script skips display init entirely — uses existing state.
#
# Wiring: same as before, touch pins also connected
#   CTP_SDA=GP26  CTP_SCL=GP27  CTP_INT=GP28

import time
from machine import SPI, Pin, I2C

# ── Reconnect to already-initialised display ──────────────────────
spi = SPI(0, baudrate=10_000_000,
          sck=Pin(18), mosi=Pin(19), miso=Pin(4))
cs  = Pin(6,  Pin.OUT, value=1)
dc  = Pin(12, Pin.OUT, value=1)

W, H = 320, 480

def write_cmd(c):
    dc.value(0); cs.value(0); spi.write(bytes([c])); cs.value(1)
def write_data(d):
    dc.value(1); cs.value(0); spi.write(bytes([d])); cs.value(1)

def fill(r, g, b):
    write_cmd(0x2A)
    write_data(0x00); write_data(0x00)
    write_data((W-1)>>8); write_data((W-1)&0xFF)
    write_cmd(0x2B)
    write_data(0x00); write_data(0x00)
    write_data((H-1)>>8); write_data((H-1)&0xFF)
    write_cmd(0x2C)
    pixel = bytes([r,g,b]) * W
    dc.value(1); cs.value(0)
    for _ in range(H): spi.write(pixel)
    cs.value(1)

def draw_dot(x, y, sz=15, r=255, g=255, b=0):
    x0=max(0,x-sz); x1=min(W-1,x+sz)
    y0=max(0,y-sz); y1=min(H-1,y+sz)
    w=x1-x0+1; h=y1-y0+1
    if w<=0 or h<=0:
        print(f"    dot clipped: ({x},{y}) out of range")
        return
    write_cmd(0x2A)
    write_data(x0>>8); write_data(x0&0xFF)
    write_data(x1>>8); write_data(x1&0xFF)
    write_cmd(0x2B)
    write_data(y0>>8); write_data(y0&0xFF)
    write_data(y1>>8); write_data(y1&0xFF)
    write_cmd(0x2C)
    px = bytes([r,g,b]) * w
    dc.value(1); cs.value(0)
    for _ in range(h): spi.write(px)
    cs.value(1)

def draw_screen():
    """Dark background with green dot at (0,0) and orange at other corners."""
    fill(10, 10, 40)
    draw_dot(20,    20,    15, 0,   255, 0)    # GREEN = screen (0,0)
    draw_dot(W-20,  20,    12, 255, 100, 0)    # orange = top-right
    draw_dot(20,    H-20,  12, 255, 100, 0)    # orange = bottom-left
    draw_dot(W-20,  H-20,  12, 255, 100, 0)    # orange = bottom-right

# ── Confirm drawing works first ───────────────────────────────────
print("\n[1] Testing draw — screen should turn blue...")
fill(0, 0, 180)
time.sleep_ms(800)
print("    If screen went blue: drawing works ✓")
print("    If still red/dark: display lost init state — rerun test_02_working first")

# ── Touch init ────────────────────────────────────────────────────
print("\n[2] Touch init...")
i2c = I2C(1, sda=Pin(26), scl=Pin(27), freq=400_000)
FT = 0x38
try:
    i2c.writeto_mem(FT, 0x80, bytes([22]))
    i2c.writeto_mem(FT, 0x86, bytes([0x00]))
    print("    ✓ FT6236 ready")
except Exception as e:
    print(f"    ✗ Touch init failed: {e}")
    raise SystemExit

def read_raw():
    try:
        n = i2c.readfrom_mem(FT, 0x02, 1)[0] & 0x0F
        if not n or n > 5: return None
        d = i2c.readfrom_mem(FT, 0x03, 4)
        return ((d[0]&0x0F)<<8)|d[1], ((d[2]&0x0F)<<8)|d[3]
    except: return None

# ── Axis combinations ─────────────────────────────────────────────
COMBOS = [
    (False, False, False, "No flip"),
    (True,  False, False, "FLIP_X only"),
    (False, True,  False, "FLIP_Y only"),
    (True,  True,  False, "FLIP_X + FLIP_Y"),
]

print("\n" + "="*48)
print("  GREEN dot = screen top-left (0,0)")
print("  Tap your physical top-left corner.")
print("  When yellow lands ON green = correct!")
print("  Ctrl+C to advance to next combo.")
print("="*48)

for flip_x, flip_y, swap, label in COMBOS:
    draw_screen()
    print(f"\n--- {label} ---")
    print(f"    Tap physical top-left corner now...")
    last = None
    try:
        while True:
            raw = read_raw()
            if raw and raw != last:
                rx, ry = raw
                x, y = rx, ry
                if swap:   x, y = y, x
                if flip_x: x = W - 1 - x
                if flip_y: y = H - 1 - y
                x = max(0, min(W-1, x))
                y = max(0, min(H-1, y))
                draw_dot(x, y, 15, 255, 255, 0)
                print(f"    raw=({rx:3d},{ry:3d}) → ({x:3d},{y:3d})")
                last = raw
            elif not raw:
                last = None
            time.sleep_ms(20)
    except KeyboardInterrupt:
        print("    Next combo...")
        time.sleep_ms(300)

print("\n✓ Note which combo put yellow ON the green dot")
print("  Update config.py with those FLIP_X/FLIP_Y values\n")