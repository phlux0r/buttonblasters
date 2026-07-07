"""
Button Blasters - Raw SD card SPI probe (diagnostic only, bypasses sdcard.py)

Purpose: see the actual bytes the card sends back for CMD0, instead of
just "no SD card" after 5 retries. Helps distinguish:
  - all 0xFF forever         -> card not responding at all (power/wiring/CS)
  - 0x01 then works          -> actually fine, sdcard.py issue
  - garbage / non-0xFF noise -> signal integrity / SPI mode issue
"""

import time
from machine import Pin, SPI

# Hold all other CS pins high first (shared bus)
for pin_num in [6, 7, 8, 9, 10]:
    Pin(pin_num, Pin.OUT).value(1)

sck = Pin(18)
mosi = Pin(19)
miso = Pin(4)
cs = Pin(3, Pin.OUT, value=1)

spi = SPI(0, baudrate=100000, polarity=0, phase=0, sck=sck, mosi=mosi, miso=miso)

print("Sending 80 clock cycles with CS high (card power-up)...")
cs.value(1)
for _ in range(10):
    spi.write(b"\xff")
time.sleep_ms(10)

print("\nSending CMD0 (GO_IDLE_STATE) with CS low...")
cs.value(0)

cmd0 = bytearray([0x40, 0x00, 0x00, 0x00, 0x00, 0x95])
spi.write(cmd0)

print("Reading up to 16 response bytes...")
responses = []
for i in range(16):
    buf = bytearray(1)
    spi.readinto(buf, 0xFF)
    responses.append(buf[0])

cs.value(1)
spi.write(b"\xff")

print("\nRaw bytes received:", [hex(b) for b in responses])

# Interpret
if all(b == 0xFF for b in responses):
    print("\n=> Card sent NOTHING but idle bytes (0xFF the whole time).")
    print("   This usually means: card not powered, CS not reaching the card,")
    print("   MISO not actually connected, or card not seated properly.")
    print("   Try: reseat card, verify continuity again with multimeter WHILE")
    print("   the Pico is powered (not just continuity on unpowered board),")
    print("   try a different SD card entirely.")
elif 0x01 in responses:
    idx = responses.index(0x01)
    print(f"\n=> Got 0x01 (idle state, GOOD response) at position {idx}!")
    print("   The card IS responding correctly at the SPI level.")
    print("   This means sdcard.py's 5-retry loop may be too strict/fast,")
    print("   or there's a timing issue between attempts. Worth reporting back.")
else:
    print("\n=> Got a response, but not clean 0x01 or all-0xFF.")
    print("   This suggests signal integrity issues (bad connection, wrong")
    print("   baudrate, breadboard noise) rather than 'no card' outright.")
    print("   Try: shorter/better jumper wires, add 0.1uF cap across")
    print("   card's VCC/GND close to the breakout, slower baudrate.")
