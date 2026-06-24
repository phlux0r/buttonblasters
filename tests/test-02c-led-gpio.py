# tests/test_02c_led_gpio.py — Button Blasters
# Diagnostic: drive backlight LED pin from a GPIO instead of tying to 3.3V
#
# REWIRE: move the display's LED pin from 3.3V to GP13 (or any free GPIO)
# Leave everything else from Test 2 wiring as-is.

import time
from machine import Pin

print("\n" + "="*48)
print("  Button Blasters — TEST 2c: Backlight via GPIO")
print("="*48)

# Try a few different free GPIOs in case one specific pin matters
LED_PIN = 13   # rewire display LED pin to this GPIO

print(f"\n[1] Driving GP{LED_PIN} HIGH (backlight should turn on)...")
led = Pin(LED_PIN, Pin.OUT)
led.value(1)
time.sleep_ms(500)
print(f"    GP{LED_PIN} is now HIGH — check the display backlight now")

print("\n[2] Blinking 5 times to make it obvious if it's working...")
for i in range(5):
    led.value(0)
    time.sleep_ms(400)
    led.value(1)
    time.sleep_ms(400)
    print(f"    Blink {i+1}/5")

print("\n[3] Leaving backlight ON (high)")
led.value(1)

print()
print("="*48)
print("  TEST 2c COMPLETE")
print("  Did the backlight blink 5 times?")
print("  YES -> this module needs active GPIO drive, not just 3.3V")
print("         Update config.py: add PIN_BACKLIGHT = 13, drive HIGH at boot")
print("  NO  -> backlight circuit issue is something else entirely")
print("         (worth trying a couple of different GPIO pins too)")
print("="*48 + "\n")