# tests/test_01_pico_health.py
# Button Blasters — TEST 1: Pico 2W health check
# Run this FIRST, USB only, nothing else wired.
import sys, gc, time, machine

print("\n" + "="*48)
print("  Button Blasters — TEST 1: Pico 2W health")
print("="*48)

print(f"\n[1] MicroPython : {sys.version}")
print(f"    Platform    : {sys.platform}")

try:
    import rp2
    print("    Chip        : RP2350 (Pico 2W) ✓")
except:
    print("    Chip        : RP2040 (original Pico)")

try:
    import ubinascii
    uid = ubinascii.hexlify(machine.unique_id()).decode()
    print(f"    Board ID    : {uid}")
except Exception as e:
    print(f"    Board ID    : unavailable ({e})")

freq = machine.freq()
print(f"\n[2] CPU freq    : {freq//1_000_000} MHz")
print("    ✓ Full speed" if freq >= 120_000_000 else "    ⚠ Slower than expected")

gc.collect()
free = gc.mem_free(); alloc = gc.mem_alloc(); total = free+alloc
print(f"\n[3] RAM free    : {free:,} ({free//1024} KB)")
print(f"    RAM total   : {total:,} ({total//1024} KB)")
print("    ✓ RP2350 512KB confirmed" if total>=500_000 else "    ✓ RP2040 264KB" if total>=200_000 else "    ⚠ Unexpected")

try:
    import os
    st = os.statvfs('/')
    ft = st[0]*st[2]; ff = st[0]*st[3]
    print(f"\n[4] Flash total : {ft:,} ({ft//1024} KB)")
    print(f"    Flash free  : {ff:,} ({ff//1024} KB)")
    print("    ✓ 4MB confirmed" if ft>=3_000_000 else "    ⚠ Less than expected")
except Exception as e:
    print(f"\n[4] Flash check failed: {e}")

print("\n[5] LED blink — watch for 5 blinks...")
try:
    from machine import Pin
    led = Pin("LED", Pin.OUT)
    for i in range(5):
        led.on(); time.sleep_ms(200); led.off(); time.sleep_ms(200)
        print(f"    Blink {i+1}/5")
    print("    ✓ LED OK")
except Exception as e:
    print(f"    ⚠ LED: {e}")

print("\n[6] Safe GPIO check...")
SAFE = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,26,27,28]
try:
    from machine import Pin
    for p in SAFE: Pin(p, Pin.IN)
    print(f"    ✓ {len(SAFE)} GPIO pins OK")
    print("    ⚠ GP23,24,25,29 skipped (WiFi internal — never connect these)")
except Exception as e:
    print(f"    ✗ {e}")

print("\n" + "="*48)
print("  TEST 1 COMPLETE — proceed to Test 2")
print("  Wire the ILI9488 main display next")
print("="*48 + "\n")
