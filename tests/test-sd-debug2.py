from machine import SPI, Pin
import time

for p in [6,7,8,9,10]: Pin(p, Pin.OUT, value=1)
sd_cs = Pin(3, Pin.OUT, value=1)
spi = SPI(0, baudrate=400_000, sck=Pin(18), mosi=Pin(19), miso=Pin(4))

def send_cmd(cmd, arg=0, crc=0x01):
    sd_cs.value(0)
    spi.write(bytes([0x40 | cmd, (arg>>24)&0xFF, (arg>>16)&0xFF, (arg>>8)&0xFF, arg&0xFF, crc]))
    for _ in range(16):
        b = spi.read(1, 0xFF)[0]
        if b != 0xFF:
            return b
    return 0xFF

def send_acmd(cmd, arg=0):
    send_cmd(55)   # APP_CMD prefix
    sd_cs.value(1)
    spi.write(bytes([0xFF]))
    time.sleep_ms(1)
    return send_cmd(cmd, arg)

# Power-up sequence
sd_cs.value(1)
spi.write(bytes([0xFF]*10))
time.sleep_ms(1)

# CMD0
r = send_cmd(0, 0, 0x95)
sd_cs.value(1); spi.write(bytes([0xFF]))
print(f"CMD0:  0x{r:02X} ({'OK - idle' if r==1 else 'FAIL'})")

time.sleep_ms(1)

# CMD8 - check voltage range, required for SD v2 / SDHC
r = send_cmd(8, 0x1AA, 0x87)
extra = spi.read(4, 0xFF)
sd_cs.value(1); spi.write(bytes([0xFF]))
print(f"CMD8:  0x{r:02X} extra={[hex(x) for x in extra]}")
if r == 0x01:
    print("       SD v2 card (SDHC/SDXC capable)")
elif r == 0x05:
    print("       SD v1 card (old, SDSC only)")
else:
    print("       Unexpected")

time.sleep_ms(1)

# ACMD41 - init, up to 2 seconds
print("ACMD41 loop (init)...")
hcs = 0x40000000  # set HCS bit for SDHC support
deadline = time.ticks_add(time.ticks_ms(), 2000)
while True:
    r = send_acmd(41, hcs)
    sd_cs.value(1); spi.write(bytes([0xFF]))
    print(f"  ACMD41: 0x{r:02X}")
    if r == 0x00:
        print("  Card init complete!")
        break
    if r != 0x01:
        print(f"  Unexpected response, stopping")
        break
    if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
        print("  TIMEOUT after 2s")
        break
    time.sleep_ms(50)

# CMD58 - read OCR to confirm SDHC
time.sleep_ms(1)
r = send_cmd(58)
ocr = spi.read(4, 0xFF)
sd_cs.value(1); spi.write(bytes([0xFF]))
print(f"CMD58: 0x{r:02X} OCR={[hex(x) for x in ocr]}")
if r == 0:
    if ocr[0] & 0x40:
        print("       SDHC/SDXC confirmed")
    else:
        print("       SDSC (standard capacity)")