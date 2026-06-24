# tests/test_sd_read_debug2.py
# SD read debug with extended init and CMD16 forced

import time
from machine import SPI, Pin

for p in [6,7,8,9,10]: Pin(p, Pin.OUT, value=1)

spi = SPI(0, baudrate=400_000,
          sck=Pin(18), mosi=Pin(19), miso=Pin(4))
cs = Pin(3, Pin.OUT, value=1)

def cmd(c, arg=0, crc=0x01):
    spi.write(b'\xFF')
    cs.value(0)
    spi.write(bytes([0x40|c,
                     (arg>>24)&0xFF,(arg>>16)&0xFF,
                     (arg>>8)&0xFF,arg&0xFF,crc]))
    for _ in range(200):
        r = spi.read(1,0xFF)[0]
        if r != 0xFF: return r
    return 0xFF

def cmd_r4(c, arg=0, crc=0x01):
    r1 = cmd(c, arg, crc)
    d  = spi.read(4, 0xFF)
    cs.value(1); spi.write(b'\xFF')
    return r1, d

def cmd_end():
    cs.value(1); spi.write(b'\xFF')
    time.sleep_ms(1)

print("="*40)
print("SD Read Debug 2 — Extended init")
print("="*40)

# Power up
cs.value(1); spi.write(bytes([0xFF]*20)); time.sleep_ms(200)
print("Power up done")

# CMD0
r = cmd(0,0,0x95); cmd_end()
print(f"CMD0: {hex(r)}")

# CMD8
r, d = cmd_r4(8,0x1AA,0x87)
print(f"CMD8: {hex(r)} {[hex(b) for b in d]}")

# ACMD41 — more iterations, longer delay
print("ACMD41 loop...")
for i in range(100):
    r = cmd(55); cmd_end()
    r = cmd(41, 0x40000000); cmd_end()
    if r == 0:
        print(f"  Ready at iteration {i+1}")
        break
    time.sleep_ms(50)   # longer delay between attempts
else:
    print("  TIMEOUT")

# CMD58 — multiple attempts
for attempt in range(3):
    time.sleep_ms(100)
    r1, ocr = cmd_r4(58)
    print(f"CMD58 attempt {attempt+1}: R1={hex(r1)} OCR={[hex(b) for b in ocr]}")
    if any(b != 0 for b in ocr):
        break

# CMD16 — force 512 byte blocks even for SDHC
r = cmd(16, 512); cmd_end()
print(f"CMD16: {hex(r)}")

# Extra settling time
time.sleep_ms(500)
print("Settling...")

# Try CMD17 multiple times
for attempt in range(3):
    print(f"\nCMD17 attempt {attempt+1}...")
    cs.value(0)
    spi.write(bytes([0x51,0,0,0,0,0x01]))
    # Read response
    for _ in range(100):
        r = spi.read(1,0xFF)[0]
        if r != 0xFF:
            print(f"  R1={hex(r)}")
            break
    # Read for data token
    found = False
    raw = []
    for i in range(2000):
        b = spi.read(1,0xFF)[0]
        if i < 30: raw.append(hex(b))
        if b == 0xFE:
            print(f"  ✓ Data token at byte {i}!")
            data = spi.read(16,0xFF)
            print(f"  Data: {[hex(x) for x in data]}")
            found = True
            break
        elif b not in (0xFF, 0x00) and i < 5:
            print(f"  Token candidate at {i}: {hex(b)}")
    if not found:
        print(f"  No token. First 30 bytes: {raw[:30]}")
    cs.value(1); spi.write(b'\xFF')
    time.sleep_ms(200)

print("\nDone")