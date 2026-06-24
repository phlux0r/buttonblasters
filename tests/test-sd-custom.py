# tests/test_sd_read_debug.py
# Debug what CMD17 actually returns on MISO
# Run immediately after fresh power cycle (unplug/replug Pico)

import time
from machine import SPI, Pin

for p in [6,7,8,9,10]: Pin(p, Pin.OUT, value=1)

spi = SPI(0, baudrate=400_000,
          sck=Pin(18), mosi=Pin(19), miso=Pin(4))
cs = Pin(3, Pin.OUT, value=1)

def cmd(c, arg=0, crc=0x01):
    spi.write(b'\xFF')
    cs.value(0)
    spi.write(bytes([0x40|c,(arg>>24)&0xFF,(arg>>16)&0xFF,(arg>>8)&0xFF,arg&0xFF,crc]))
    for _ in range(100):
        r = spi.read(1,0xFF)[0]
        if r != 0xFF: return r
    return 0xFF

def cmd_end(): cs.value(1); spi.write(b'\xFF')

print("Power up...")
cs.value(1); spi.write(bytes([0xFF]*10)); time.sleep_ms(100)

r = cmd(0,0,0x95); cmd_end(); print(f"CMD0: {hex(r)}")
r = cmd(8,0x1AA,0x87); d=spi.read(4,0xFF); cmd_end()
print(f"CMD8: {hex(r)} {[hex(b) for b in d]}")

for i in range(50):
    r=cmd(55); cmd_end()
    r=cmd(41,0x40000000); cmd_end()
    if r==0: break
    time.sleep_ms(10)
print(f"ACMD41: {hex(r)}")

# Now try CMD17 — read block 0 and print ALL bytes returned
print("\nCMD17 (read block 0) raw response:")
cs.value(0)
spi.write(bytes([0x51,0,0,0,0,0x01]))   # CMD17 arg=0
# Print first 20 response bytes
resp = []
for _ in range(20):
    b = spi.read(1,0xFF)[0]
    resp.append(hex(b))
print(f"  First 20 bytes: {resp}")

# Keep reading for data token
found = False
for i in range(1000):
    b = spi.read(1,0xFF)[0]
    if b != 0xFF and b != 0x00:
        print(f"  Non-FF/00 byte at position {i+20}: {hex(b)}")
        if b == 0xFE:
            print("  ✓ Data token 0xFE found!")
            data = spi.read(16,0xFF)
            print(f"  First 16 data bytes: {[hex(x) for x in data]}")
            found = True
        break
if not found:
    print("  No data token found in 1020 bytes")
cs.value(1); spi.write(b'\xFF')

print("\nDone")