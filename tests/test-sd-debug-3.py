from machine import SPI, Pin
import time

# Pull MISO high and read it bare — no SPI, just GPIO
miso = Pin(4, Pin.IN, Pin.PULL_UP)

print("MISO pin reading (should be 1 if line is free):")
for i in range(5):
    print(f"  {miso.value()}")
    time.sleep_ms(10)

# Now hold ALL CS pins high including display
for p in [6,7,8,9,10]: Pin(p, Pin.OUT, value=1)
sd_cs = Pin(3, Pin.OUT, value=1)

print("\nMISO with all CS high:")
for i in range(5):
    print(f"  {miso.value()}")
    time.sleep_ms(10)

# Now pull display CS low (select main display)
main_cs = Pin(6, Pin.OUT, value=0)
print("\nMISO with ILI9488 CS LOW:")
for i in range(5):
    print(f"  {miso.value()}")
    time.sleep_ms(10)
main_cs.value(1)

print("\nMISO after ILI9488 CS back HIGH:")
for i in range(5):
    print(f"  {miso.value()}")
    time.sleep_ms(10)