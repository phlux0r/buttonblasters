# tests/test_02_working.py — Button Blasters
# TEST 2 WORKING: Confirmed working pin config + minimal IPS init
#
# CONFIRMED WORKING PINS:
#   SCK=GP18  MOSI=GP19  MISO=GP4
#   CS=GP6    DC=GP12    RST=GP17
#   LED -> 3.3V direct

import time
from machine import SPI, Pin

print("\n" + "="*48)
print("  Button Blasters — TEST 2 WORKING")
print("="*48)

spi = SPI(0, baudrate=10_000_000,
          sck=Pin(18), mosi=Pin(19), miso=Pin(4))
cs  = Pin(6,  Pin.OUT, value=1)
dc  = Pin(12, Pin.OUT, value=1)
rst = Pin(17, Pin.OUT, value=1)
print("\n[1] SPI0 @ 10MHz  SCK=18 MOSI=19 MISO=4  CS=6 DC=12 RST=17 ✓")

# Per-byte CS toggle — confirmed required for this panel
def write_cmd(c):
    dc.value(0); cs.value(0)
    spi.write(bytes([c]))
    cs.value(1)

def write_data(d):
    dc.value(1); cs.value(0)
    spi.write(bytes([d]))
    cs.value(1)

# Reset"""  """
print("[2] Reset...")
rst.value(1); time.sleep_ms(10)
rst.value(0); time.sleep_ms(20)
rst.value(1); time.sleep_ms(120)
print("    ✓")

# Minimal IPS init — exact 6 commands from working driver
print("[3] IPS init...")
write_cmd(0x11); time.sleep_ms(120)   # sleep out
write_cmd(0x3A); write_data(0x66)     # 18-bit RGB666
write_cmd(0xC5)                        # VCOM
write_data(0x00); write_data(0x4D); write_data(0x80)
write_cmd(0x21)                        # inversion ON (IPS)
write_cmd(0x36); write_data(0x48)     # MADCTL landscape BGR
write_cmd(0x29); time.sleep_ms(20)    # display ON
print("    ✓")

# Fill helper
W, H = 320, 480
def fill_screen(r, g, b):
    write_cmd(0x2A)
    write_data(0x00); write_data(0x00)
    write_data((W-1)>>8); write_data((W-1)&0xFF)
    write_cmd(0x2B)
    write_data(0x00); write_data(0x00)
    write_data((H-1)>>8); write_data((H-1)&0xFF)
    write_cmd(0x2C)
    pixel = bytes([r, g, b]) * W
    dc.value(1); cs.value(0)
    for _ in range(H):
        spi.write(pixel)
    cs.value(1)

# Colour sweep
print("\n[4] Colour fills — watch the display:")
for name, r, g, b in [
    ("RED",   255,   0,   0),
    ("GREEN",   0, 255,   0),
    ("BLUE",    0,   0, 255),
    ("WHITE", 255, 255, 255),
    ("BLACK",   0,   0,   0),
]:
    t = time.ticks_ms()
    fill_screen(r, g, b)
    ms = time.ticks_diff(time.ticks_ms(), t)
    print(f"    {name:8s}: {ms}ms ✓")
    time.sleep_ms(800)

# Loop
print("\n[5] Looping red/green/blue — Ctrl+C to stop")
try:
    while True:
        fill_screen(255, 0, 0); time.sleep_ms(1000)
        fill_screen(0, 255, 0); time.sleep_ms(1000)
        fill_screen(0, 0, 255); time.sleep_ms(1000)
except KeyboardInterrupt:
    pass

print("\n" + "="*48)
print("  TEST 2 WORKING — COMPLETE")
print("  Colours showing = ✓ PASS — proceed to Test 3")
print("="*48 + "\n")
