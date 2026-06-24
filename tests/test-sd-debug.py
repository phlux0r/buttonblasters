from machine import SPI, Pin
import time

# Hold all display CS pins high
for p in [6,7,8,9,10]: Pin(p, Pin.OUT, value=1)

# SD CS high initially
sd_cs = Pin(3, Pin.OUT, value=1)
spi = SPI(0, baudrate=400_000, sck=Pin(18), mosi=Pin(19), miso=Pin(4))

# Step 1: Send 80 clock pulses with CS HIGH (required for SD card power-up)
sd_cs.value(1)
spi.write(bytes([0xFF]*10))
print("80 clock pulses sent")

# Step 2: Pull CS low, send CMD0 (reset / go to SPI mode)
sd_cs.value(0)
time.sleep_ms(1)
cmd0 = bytes([0x40, 0x00, 0x00, 0x00, 0x00, 0x95])
spi.write(cmd0)
print("CMD0 sent")

# Step 3: Read up to 16 bytes looking for 0x01 response
response = None
for i in range(16):
    b = spi.read(1, 0xFF)[0]
    print(f"  byte {i}: 0x{b:02X}")
    if b == 0x01:
        response = b
        break
    if b != 0xFF:
        response = b
        break

sd_cs.value(1)
spi.write(bytes([0xFF]))  # extra clocks

if response == 0x01:
    print("SUCCESS: Card responded 0x01 (idle) — SPI mode entered")
elif response is None:
    print("FAIL: No response — all 0xFF. Card not seeing CLK/MOSI, or CS not reaching card")
else:
    print(f"FAIL: Unexpected response 0x{response:02X}")