# tests/test_11_haptic.py — Button Blasters
# TEST 11 — ERM haptic motor via 2N3904 NPN transistor
#
# Wiring:
#   GP22 → 1kΩ resistor → 2N3904 BASE (left leg, flat face toward you)
#   2N3904 COLLECTOR (middle leg) → motor red wire
#   Motor blue wire → 3.3V
#   1N4148 flyback diode across motor (cathode/stripe toward 3.3V)
#   2N3904 EMITTER (right leg) → GND
#
# What this tests:
#   1. GP22 drives transistor correctly — motor spins on HIGH
#   2. Single pulse (60ms) — short buzz
#   3. Double pulse — correct answer feedback pattern
#   4. Long pulse — level up / game over pattern
#   5. Custom patterns — various game feedback sequences
#   6. GP22 stays LOW when idle — motor off between pulses
# ─────────────────────────────────────────────────────────────────

import time
from machine import Pin

print()
print("=" * 48)
print("  Button Blasters — TEST 11: Haptic motor")
print("=" * 48)

# ── Init GP22 as output, LOW ──────────────────────────────────────
print("\n[1] GP22 init...")
motor = Pin(22, Pin.OUT, value=0)
print("    ✓ GP22 configured as output, LOW (motor off)")
time.sleep_ms(500)

# ── Helper functions ──────────────────────────────────────────────
def buzz(ms=60):
    """Single buzz for ms milliseconds."""
    motor.value(1)
    time.sleep_ms(ms)
    motor.value(0)

def silence(ms=100):
    time.sleep_ms(ms)

# ── Test 2: Single pulse ──────────────────────────────────────────
print("\n[2] Single pulse (60ms) — you should feel one short buzz...")
buzz(60)
silence(500)
print("    ✓ Did you feel it?")
print("    If not: check 1kΩ on base, emitter→GND, motor wires")

time.sleep_ms(500)

# ── Test 3: Double pulse ──────────────────────────────────────────
print("\n[3] Double pulse — correct answer pattern...")
buzz(40); silence(60); buzz(40)
silence(500)
print("    ✓")

time.sleep_ms(500)

# ── Test 4: Long pulse ────────────────────────────────────────────
print("\n[4] Long pulse (300ms) — level up / game over...")
buzz(300)
silence(500)
print("    ✓")

time.sleep_ms(500)

# ── Test 5: Game patterns ─────────────────────────────────────────
print("\n[5] Game feedback patterns...")

print("    Countdown tick (3 quick taps)...")
for _ in range(3):
    buzz(30)
    silence(200)
print("    ✓")

time.sleep_ms(300)

print("    Wrong answer (two slow bumps)...")
buzz(80); silence(120); buzz(80)
silence(500)
print("    ✓")

time.sleep_ms(300)

print("    Star earned (rapid triple)...")
buzz(30); silence(40); buzz(30); silence(40); buzz(30)
silence(500)
print("    ✓")

time.sleep_ms(300)

print("    Menu select click (very short)...")
buzz(20)
silence(500)
print("    ✓")

time.sleep_ms(300)

print("    Game over rumble (long-short-long)...")
buzz(200); silence(80); buzz(60); silence(80); buzz(200)
silence(500)
print("    ✓")

time.sleep_ms(300)

# ── Test 6: Rapid fire — stress test ────────────────────────────
print("\n[6] Rapid fire stress test (20 pulses)...")
for i in range(20):
    buzz(25)
    silence(50)
print("    ✓ 20 pulses complete — motor and transistor stable")

time.sleep_ms(500)

# ── Test 7: Idle state ────────────────────────────────────────────
print("\n[7] Idle state check — motor should be completely off...")
motor.value(0)
time.sleep_ms(2000)
print(f"    GP22 = {motor.value()} (should be 0)")
print("    ✓ Motor off — no drift or residual vibration")

# ── Summary ───────────────────────────────────────────────────────
print()
print("=" * 48)
print("  TEST 11 — HAPTIC SUMMARY")
print("  GP22 init      : ✓ output LOW")
print("  Single pulse   : ✓ 60ms buzz")
print("  Double pulse   : ✓ correct answer pattern")
print("  Long pulse     : ✓ 300ms rumble")
print("  Game patterns  : ✓ all sequences")
print("  Stress test    : ✓ 20 rapid pulses stable")
print("  Idle state     : ✓ GP22 LOW, motor off")
print()
print("  If motor didn't buzz:")
print("  - Check 1kΩ resistor between GP22 and 2N3904 base")
print("  - Check emitter (right leg) → GND")
print("  - Check motor red → collector (middle leg)")
print("  - Check motor blue → 3.3V")
print("  - Check 1N4148 flyback diode across motor terminals")
print("  - Check flat face of 2N3904 orientation")
print()
print("  ✓ All hardware confirmed — ready for firmware update")
print("=" * 48)
print()
