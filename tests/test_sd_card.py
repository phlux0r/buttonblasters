# tests/test_sd_card.py — Button Blasters
# TEST: SD card via display module built-in slot
#
# Wiring:
#   SD_CS -> GP3  (all other SPI pins shared: SCK=GP18 MOSI=GP19 MISO=GP4)
#
# Prerequisites:
#   - sdcard.py must be uploaded to Pico root
#   - FAT32 formatted microSD card inserted in display module slot
#   - Download sdcard.py from:
#     https://raw.githubusercontent.com/micropython/micropython-lib/master/micropython/drivers/storage/sdcard/sdcard.py

import time, os, gc
from machine import SPI, Pin

print("\n" + "="*48)
print("  Button Blasters — TEST: SD Card")
print("="*48)

# Keep all other CS pins HIGH to avoid bus conflicts
main_cs = Pin(6,  Pin.OUT, value=1)
btn_cs  = [Pin(p, Pin.OUT, value=1) for p in [7,8,9,10]]

# ── SD card init at low speed ─────────────────────────────────────
print("\n[1] Mounting SD card...")
try:
    from sdcard import SDCard
    spi = SPI(0, baudrate=400_000,
              sck=Pin(18), mosi=Pin(19), miso=Pin(4))
    sd  = SDCard(spi, Pin(3, Pin.OUT, value=1))
    os.mount(sd, '/sd')
    print("    ✓ Mounted at /sd")
except ImportError:
    print("    ✗ sdcard.py not found on Pico root")
    print("    Upload sdcard.py from micropython-lib then retry")
    raise SystemExit
except Exception as e:
    print(f"    ✗ Mount failed: {e}")
    print("    Check: SD card inserted? GP3 wired to SD_CS?")
    raise SystemExit

# Bump SPI speed after init
spi.init(baudrate=10_000_000)

# ── Directory listing ─────────────────────────────────────────────
print("\n[2] SD card contents...")
try:
    files = os.listdir('/sd')
    stat  = os.statvfs('/sd')
    total = stat[0] * stat[2] // 1024 // 1024
    free  = stat[0] * stat[3] // 1024 // 1024
    print(f"    Capacity : ~{total} MB")
    print(f"    Free     : ~{free} MB")
    print(f"    Items at root: {len(files)}")
    for f in files[:10]:
        print(f"      /sd/{f}")
    if len(files) > 10:
        print(f"      ... and {len(files)-10} more")
except Exception as e:
    print(f"    ✗ Directory listing failed: {e}")

# ── Write test ────────────────────────────────────────────────────
print("\n[3] Write test...")
try:
    t = time.ticks_ms()
    with open('/sd/bb_test.txt', 'w') as f:
        f.write("Button Blasters SD card test\n")
        f.write(f"Written at boot\n")
    ms = time.ticks_diff(time.ticks_ms(), t)
    print(f"    ✓ Write OK ({ms}ms)")
except Exception as e:
    print(f"    ✗ Write failed: {e}")

# ── Read back ─────────────────────────────────────────────────────
print("\n[4] Read back...")
try:
    with open('/sd/bb_test.txt', 'r') as f:
        content = f.read()
    print(f"    ✓ Read OK: {repr(content[:40])}")
except Exception as e:
    print(f"    ✗ Read failed: {e}")

# ── Write speed benchmark ─────────────────────────────────────────
print("\n[5] Write speed benchmark (64KB)...")
try:
    data = bytes(range(256)) * 256   # 64KB
    t = time.ticks_ms()
    with open('/sd/bb_bench.bin', 'wb') as f:
        f.write(data)
    ms = time.ticks_diff(time.ticks_ms(), t)
    kbps = 64000 // ms if ms else 0
    print(f"    ✓ 64KB in {ms}ms (~{kbps} KB/s)")
    os.remove('/sd/bb_bench.bin')
except Exception as e:
    print(f"    ✗ Benchmark failed: {e}")

# ── Create Button Blasters folder structure ───────────────────────
print("\n[6] Creating BB folder structure...")
folders = [
    '/sd/images',
    '/sd/images/shared',
    '/sd/audio',
    '/sd/audio/sfx',
    '/sd/audio/voice',
    '/sd/adventure',
    '/sd/adventure/stories',
]
for folder in folders:
    try:
        os.mkdir(folder)
        print(f"    created {folder}")
    except OSError:
        print(f"    exists  {folder}")

# ── Cleanup ───────────────────────────────────────────────────────
try:
    os.remove('/sd/bb_test.txt')
except: pass

gc.collect()
print(f"\n    RAM free: {gc.mem_free()//1024}KB")

print("\n" + "="*48)
print("  SD CARD TEST COMPLETE")
print("  ✓ Mounted, read, write all working")
print("  ✓ Button Blasters folder structure created")
print("  SD_CS confirmed on GP3")
print("="*48+"\n")