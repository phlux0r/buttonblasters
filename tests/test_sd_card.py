"""
Button Blasters - Test SD Card breakout (separate module, NOT the
ILI9488's built-in unusable slot).

Confirmed pin map used here:
  SPI0: SCK=GP18, MOSI=GP19, MISO=GP4
  SD_CS = GP3 (reserved)

CRITICAL: All other CS pins on the shared SPI0 bus must be held HIGH
before SD init, or bus contention will cause init to fail/hang. This
bit us before with the ILI9488's dead built-in slot, so we're explicit
about it here.
"""

import time
from machine import Pin, SPI
import os
import sdcard

# --- Step 1: hold every other CS pin HIGH so nothing else responds ---
OTHER_CS_PINS = [6, 7, 8, 9, 10]  # ILI9488 CS, ST7789 BTN-0..3 CS
print("Setting all display CS pins HIGH to avoid SPI bus contention...")
for pin_num in OTHER_CS_PINS:
    p = Pin(pin_num, Pin.OUT)
    p.value(1)
print("  Done:", OTHER_CS_PINS)

# --- Step 2: set up SPI0 bus (shared bus, confirmed pins) ---
# NOTE: constructed at 100kHz directly (matching the raw probe that worked),
# rather than at 1MHz and letting sdcard.py re-init it down. Re-initializing
# an already-constructed SPI object to a different baudrate is one more
# variable to eliminate while debugging.
print("\nInitializing SPI0 (SCK=GP18, MOSI=GP19, MISO=GP4)...")
spi = SPI(0, baudrate=100000, polarity=0, phase=0,
          sck=Pin(18), mosi=Pin(19), miso=Pin(4))
sd_cs = Pin(3, Pin.OUT, value=1)
print("  SPI0 ready")

# --- Step 3: initialize the SD card over SPI ---
print("\nInitializing SD card (this will auto-negotiate v1/v2 card + speed)...")
try:
    sd = sdcard.SDCard(spi, sd_cs)
    print("  SD card responded and initialized OK")
except OSError as e:
    print("  FAILED to init SD card:", e)
    print("  Check: wiring (VCC=3.3V!), card seated, CS on GP3, MISO/MOSI/SCK not swapped")
    raise SystemExit

# --- Step 4: mount as a filesystem ---
print("\nMounting SD card as /sd ...")
vfs = os.VfsFat(sd)
try:
    os.mount(vfs, "/sd")
    print("  Mounted at /sd")
except OSError as e:
    print("  Mount failed:", e)
    print("  Card may need formatting as FAT32. Try formatting on a computer first.")
    raise SystemExit

# --- Step 5: write + read back a test file ---
print("\nWrite/read test...")
test_path = "/sd/bb_test.txt"
test_payload = "Button Blasters SD test - hello!\n"

with open(test_path, "w") as f:
    f.write(test_payload)
print("  Wrote:", test_path)

with open(test_path, "r") as f:
    readback = f.read()

if readback == test_payload:
    print("  Readback matches. SD card read/write CONFIRMED WORKING.")
else:
    print("  MISMATCH! wrote:", repr(test_payload), "read:", repr(readback))

# --- Step 6: list root directory contents ---
print("\nRoot directory listing (/sd):")
for entry in os.listdir("/sd"):
    print("  -", entry)

# --- Step 7: clean up test file, unmount ---
os.remove(test_path)
os.umount("/sd")
print("\nTest file removed, SD unmounted cleanly.")
print("\n=== SD CARD TEST: PASS ===")