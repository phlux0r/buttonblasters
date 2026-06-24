# tests/test_02g_loop.py — Button Blasters
# Looping pin probe test — runs continuously so you can measure
# CS, DC, SCK, MOSI, RST with a multimeter while it's active.
#
# Same wiring as test_02f:
# SCK=GP2 MOSI=GP3 MISO=GP4 CS=GP6 DC=GP12 RST=GP17 BL=GP13

import time
from machine import SPI, Pin

print("\n" + "="*48)
print("  Button Blasters — TEST 2g: Looping pin probe")
print("  Ctrl+C to stop")
print("="*48)

BL  = Pin(13, Pin.OUT, value=1)
spi = SPI(0, baudrate=20_000_000, sck=Pin(2), mosi=Pin(3), miso=Pin(4))
cs  = Pin(6,  Pin.OUT, value=1)
dc  = Pin(12, Pin.OUT, value=1)
rst = Pin(17, Pin.OUT, value=1)

print("\nPin voltages to expect while running:")
print("  GP2  SCK  : oscillating (SPI clock)")
print("  GP3  MOSI : oscillating (SPI data)")
print("  GP6  CS   : toggles LOW during each command, HIGH between")
print("  GP12 DC   : LOW during commands, HIGH during data")
print("  GP13 BL   : steady HIGH (~3.3V)")
print("  GP17 RST  : steady HIGH (~3.3V) after reset")
print()
print("Measure each pin with multimeter while script loops.")
print("DC average voltage will read ~1.5-2V (toggling)")
print("CS average voltage will read ~2-3V (mostly high, pulses low)")
print()

def cmd(c, *data):
    cs.value(0)
    dc.value(0); spi.write(bytes([c]))
    if data:
        dc.value(1); spi.write(bytes(data))
    cs.value(1)

def init():
    rst.value(0); time.sleep_ms(50)
    rst.value(1); time.sleep_ms(200)
    cmd(0x11); time.sleep_ms(480)
    cmd(0xF7, 0xA9,0x51,0x2C,0x82)
    cmd(0xC0, 0x0F,0x0F)
    cmd(0xC1, 0x47)
    cmd(0xC5, 0x00,0x4D,0x80)
    cmd(0xB1, 0xB0,0x11)
    cmd(0xB4, 0x02)
    cmd(0x36, 0x48)
    cmd(0x3A, 0x55)
    cmd(0x21)
    cmd(0xE9, 0x00)
    cmd(0xF7, 0xA9,0x51,0x2C,0x82)
    cmd(0xE0, 0x00,0x07,0x0B,0x03,0x0F,0x05,0x30,0x56,
              0x47,0x04,0x0B,0x0A,0x2D,0x37,0x0F)
    cmd(0xE1, 0x00,0x0E,0x13,0x04,0x11,0x07,0x39,0x45,
              0x50,0x07,0x10,0x0D,0x32,0x36,0x0F)
    cmd(0x29)

def set_win(x0,y0,x1,y1):
    cs.value(0)
    dc.value(0);spi.write(b'\x2A');dc.value(1)
    spi.write(bytes([x0>>8,x0&0xFF,x1>>8,x1&0xFF]))
    dc.value(0);spi.write(b'\x2B');dc.value(1)
    spi.write(bytes([y0>>8,y0&0xFF,y1>>8,y1&0xFF]))
    dc.value(0);spi.write(b'\x2C');dc.value(1)

def fill(r,g,b,W=480,H=320):
    c=((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)
    hi=c>>8;lo=c&0xFF
    chunk=bytes([hi,lo]*64);total=W*H
    set_win(0,0,W-1,H-1)
    for _ in range(total//64): spi.write(chunk)
    if total%64: spi.write(bytes([hi,lo]*(total%64)))
    cs.value(1)

loop=0
COLOURS=[(255,0,0),(0,255,0),(0,0,255),(255,255,0),(0,255,255)]
try:
    while True:
        loop+=1
        print(f"Loop {loop} — reinitialising and filling colours...")
        init()
        for i,(r,g,b) in enumerate(COLOURS):
            fill(r,g,b)
            print(f"  Fill {i+1}/5: RGB({r},{g},{b}) — probe pins now!")
            time.sleep_ms(2000)   # 2 seconds per colour — plenty of time
        print(f"  Loop {loop} complete\n")
except KeyboardInterrupt:
    print("\nStopped. Press Ctrl+D to reset Pico.")