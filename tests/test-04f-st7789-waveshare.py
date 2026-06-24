# tests/test_04_working.py — Button Blasters
# TEST 4 WORKING: Exact approach that showed colours
# DC=GP2 (GP5 dead)  CS=GP7  SCK=GP18  MOSI=GP19
# RES=GP15  BLK=GP13 (GPIO HIGH)

import time, gc
from machine import SPI, Pin

blk     = Pin(13, Pin.OUT, value=1)   # BLK must be GPIO not 3.3V
main_cs = Pin(6,  Pin.OUT, value=1)   # keep main display off bus

spi = SPI(0, baudrate=10_000_000,
          sck=Pin(18), mosi=Pin(19), miso=Pin(4))
cs  = Pin(7,  Pin.OUT, value=1)
dc  = Pin(2,  Pin.OUT, value=1)   # GP2 — GP5 is dead on this board
rst = Pin(15, Pin.OUT, value=1)

def wc(c): dc.value(0);cs.value(0);spi.write(bytes([c]));cs.value(1)
def wd(*args): dc.value(1);cs.value(0);spi.write(bytes(args));cs.value(1)

print("\n"+"="*48)
print("  Button Blasters — TEST 4 WORKING")
print("  DC=GP2  CS=GP7  BLK=GP13")
print("="*48)

# Hard reset
rst.value(0); time.sleep_ms(100)
rst.value(1); time.sleep_ms(200)

print("\n[1] Full init sequence...")
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
wc(0x21)
wc(0x13); time.sleep_ms(10)
wc(0x29); time.sleep_ms(255)
print("    ✓")

def fill(r, g, b, rows=240):
    c=((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)
    hi=c>>8; lo=c&0xFF
    chunk=bytes([hi,lo]*128); total=240*rows
    wc(0x2A); wd(0x00,0x00,0x00,0xEF)
    wc(0x2B); wd(0x00,0x00,(rows-1)>>8,(rows-1)&0xFF)
    wc(0x2C)
    dc.value(1); cs.value(0)
    for _ in range(total//128): spi.write(chunk)
    if total%128: spi.write(bytes([hi,lo]*(total%128)))
    cs.value(1)

gc.collect()
print(f"    RAM free: {gc.mem_free()//1024}KB")

print("\n[2] Colour fills:")
for name,r,g,b in [
    ("RED",   255,0,0),
    ("GREEN", 0,255,0),
    ("BLUE",  0,0,255),
    ("WHITE", 255,255,255),
    ("BLACK", 0,0,0),
]:
    t=time.ticks_ms(); fill(r,g,b)
    ms=time.ticks_diff(time.ticks_ms(),t)
    print(f"    {name:8s}: {ms}ms")
    time.sleep_ms(800)

print("\n[3] Loop — Ctrl+C to stop")
try:
    while True:
        fill(255,0,0); time.sleep_ms(700)
        fill(0,255,0); time.sleep_ms(700)
        fill(0,0,255); time.sleep_ms(700)
except KeyboardInterrupt:
    pass

print("\n"+"="*48)
print("  TEST 4 WORKING — COMPLETE ✓")
print("  DC=GP2  CS=GP7  BLK=GP13 GPIO HIGH")
print("  Next: wire BTN-1/2/3 and expand")
print("="*48+"\n")