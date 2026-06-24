# tests/test_02d_combined.py — Button Blasters
# Diagnostic: full init sequence + GPIO-driven backlight together
#
# Wiring: same as Test 2, but LED pin moved to GP13 (not 3.3V)
# This combines the proper ILI9488 init sequence with active backlight
# drive, in case the backlight circuit is gated by controller state.

import time
from machine import SPI, Pin

print("\n" + "="*48)
print("  Button Blasters — TEST 2d: Init + GPIO backlight together")
print("="*48)

LED_PIN = 13
led = Pin(LED_PIN, Pin.OUT, value=0)   # start LOW/off
print(f"\n[1] Backlight GP{LED_PIN} set LOW (off) initially")

spi = SPI(0, baudrate=1_000_000, sck=Pin(2), mosi=Pin(3), miso=Pin(4))
cs  = Pin(6, Pin.OUT, value=1)
dc  = Pin(12, Pin.OUT, value=1)
rst = Pin(17, Pin.OUT, value=1)

print("[2] Hard reset...")
rst.value(0); time.sleep_ms(20)
rst.value(1); time.sleep_ms(150)
print("    ✓ Reset complete")

print("[3] Sending FULL init sequence (same as Test 2)...")
INIT=bytes([
    0xE0,15,0x00,0x03,0x09,0x08,0x16,0x0A,0x3F,0x78,0x4C,0x09,0x0A,0x08,0x16,0x1A,0x0F,
    0xE1,15,0x00,0x16,0x19,0x03,0x0F,0x05,0x32,0x45,0x46,0x04,0x0E,0x0D,0x35,0x37,0x0F,
    0xC0,2,0x17,0x15,0xC1,1,0x41,0xC5,3,0x00,0x12,0x80,
    0x36,1,0x48,0x3A,1,0x66,0xB0,1,0x00,0xB1,2,0xA0,0x11,
    0xB4,1,0x02,0xB6,3,0x02,0x02,0x3B,0xB7,1,0xC6,
    0xF7,4,0xA9,0x51,0x2C,0x82,0x11,0,0xFF,0,0x29,0,
])
i=0
cs.value(0)
while i<len(INIT):
    cmd=INIT[i];i+=1
    if cmd==0xFF:time.sleep_ms(150);continue
    n=INIT[i];i+=1
    dc.value(0);spi.write(bytes([cmd]))
    if n:dc.value(1);spi.write(bytes(INIT[i:i+n]));i+=n
cs.value(1)
print("    ✓ Init sequence sent (display should be 'awake' now)")

time.sleep_ms(200)

print(f"\n[4] NOW enabling backlight on GP{LED_PIN}...")
led.value(1)
print("    GP13 driven HIGH — check the display NOW")
time.sleep_ms(1000)

print("\n[5] Filling screen RED while backlight is on...")
def set_win(x0,y0,x1,y1):
    cs.value(0)
    dc.value(0);spi.write(b'\x2A');dc.value(1);spi.write(bytes([x0>>8,x0&0xFF,x1>>8,x1&0xFF]))
    dc.value(0);spi.write(b'\x2B');dc.value(1);spi.write(bytes([y0>>8,y0&0xFF,y1>>8,y1&0xFF]))
    dc.value(0);spi.write(b'\x2C');dc.value(1)
def fill(r,g,b,W=480,H=320):
    px=bytes([r&0xF8,g&0xFC,b&0xF8]);chunk=px*64;total=W*H
    set_win(0,0,W-1,H-1)
    for _ in range(total//64):spi.write(chunk)
    if total%64:spi.write(px*(total%64))
    cs.value(1)
fill(255,0,0)
print("    ✓ Red fill sent")

print("\n[6] Blinking backlight 5x so it's unmistakable...")
for i in range(5):
    led.value(0); time.sleep_ms(400)
    led.value(1); time.sleep_ms(400)
    print(f"    Blink {i+1}/5")

print()
print("="*48)
print("  TEST 2d COMPLETE")
print("  Backlight enabled AFTER full init sequence this time.")
print("  Did you see ANY light/blink on the display now?")
print("="*48 + "\n")