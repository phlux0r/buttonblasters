# tests/test_03_touch.py  — Button Blasters
# TEST 3: FT6236 capacitive touch
#
# Additional wiring (display already connected):
#  CTP_SDA → GP26   CTP_SCL → GP27
#  CTP_INT → GP2    CTP_RST → 3.3V

import time
from machine import I2C, Pin

print("\n" + "="*48)
print("  Button Blasters — TEST 3: FT6236 touch")
print("="*48)

FT_ADDR=0x38; W,H=480,320

print("\n[1] I2C init...")
try:
    i2c=I2C(1,sda=Pin(26),scl=Pin(27),freq=400_000)
    print("    ✓ I2C-1 on GP26/GP27")
except Exception as e:
    print(f"    ✗ {e}"); raise SystemExit

print("\n[2] Bus scan...")
devices=i2c.scan()
print(f"    Found: {[hex(d) for d in devices]}")
if FT_ADDR not in devices:
    print(f"    ✗ FT6236 not at 0x38 — check CTP_SDA/SCL wiring")
    raise SystemExit
print(f"    ✓ FT6236 at 0x{FT_ADDR:02X}")

print("\n[3] Chip info...")
def rd(reg,n=1): return i2c.readfrom_mem(FT_ADDR,reg,n)
def wr(reg,v): i2c.writeto_mem(FT_ADDR,reg,bytes([v]))
print(f"    Chip ID : 0x{rd(0xA8)[0]:02X}")
print(f"    FW ver  : {rd(0xA6)[0]}")
wr(0x80,22); wr(0x86,0x00)
print("    ✓ Threshold=22, active mode set")

int_pin=Pin(2,Pin.IN,Pin.PULL_UP)
print(f"\n[4] INT pin reads: {'HIGH (idle) ✓' if int_pin.value() else 'LOW — touch or check wiring'}")

def read_pos():
    try:
        n=rd(0x02)[0]&0x0F
        if not n or n>5: return None
        d=rd(0x03,4)
        return ((d[0]&0x0F)<<8)|d[1], ((d[2]&0x0F)<<8)|d[3]
    except: return None

print("\n[5] Live touch — tap the screen (15 seconds)...")
print("    Ctrl+C to stop early")
start=time.ticks_ms(); last=None; taps=0
try:
    while time.ticks_diff(time.ticks_ms(),start)<15_000:
        pos=read_pos()
        if pos and pos!=last:
            x,y=pos
            print(f"    x={x:4d}  y={y:4d}  ({x*100//W}%,{y*100//H}%)")
            last=pos; taps+=1
        elif not pos: last=None
        time.sleep_ms(20)
except KeyboardInterrupt:
    print("\n    Stopped")

print(f"\n    Taps detected: {taps}")

print("\n[6] Axis check — tap TOP-LEFT corner now...")
time.sleep_ms(2000)
samples=[]; end=time.ticks_add(time.ticks_ms(),3000)
while time.ticks_diff(end,time.ticks_ms())>0:
    p=read_pos()
    if p: samples.append(p)
    time.sleep_ms(50)
if samples:
    ax=sum(s[0] for s in samples)//len(samples)
    ay=sum(s[1] for s in samples)//len(samples)
    print(f"    Top-left average: x={ax}, y={ay}")
    if ax<60 and ay<60: print("    ✓ Axes correct")
    elif ax>W-60 and ay<60: print("    ⚠ TOUCH_FLIP_X=True needed in config.py")
    elif ax<60 and ay>H-60: print("    ⚠ TOUCH_FLIP_Y=True needed in config.py")
    else: print(f"    ⚠ Unexpected — check TOUCH_SWAP_XY/FLIP_X/FLIP_Y")
else:
    print("    No touch — check wiring")

print("\n" + "="*48)
print("  TEST 3 COMPLETE")
print("  Coordinates printing = touch working ✓")
print("  Nothing printing = check SDA/SCL/INT wiring")
print("  Note any axis corrections needed for config.py")
print("  Next: Test 4 — ST7789 button displays")
print("="*48 + "\n")
