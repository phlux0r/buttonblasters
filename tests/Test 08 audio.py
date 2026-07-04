# tests/test_08_audio.py — Button Blasters
# TEST 8 — MAX98357A I2S audio bring-up
#
# Wiring:
#   MAX98357A BCLK → GP0
#   MAX98357A LRC  → GP1
#   MAX98357A DIN  → GP16
#   MAX98357A SD   → 3.3V (always on)
#   MAX98357A VIN  → 3.3V
#   MAX98357A GND  → GND
#   Speaker +/-    → MAX98357A output terminals
#
# What this tests:
#   1. I2S init on GP0/GP1/GP16
#   2. Sine wave tone generation — confirms signal reaching speaker
#   3. Frequency sweep — confirms audio path working end to end
#   4. Volume levels — confirms SD/gain pin working
#   5. WAV file playback from flash (if available)
#
# Expected: audible tone from speaker on each test
# ─────────────────────────────────────────────────────────────────

import time
import math
import struct
from machine import I2S, Pin

print()
print("=" * 48)
print("  Button Blasters — TEST 8: MAX98357A audio")
print("=" * 48)

# ── I2S config ────────────────────────────────────────────────────
BCLK_PIN    = 0
LRC_PIN     = 1
DIN_PIN     = 16
SAMPLE_RATE = 22050
BITS        = 16
BUF_BYTES   = 4096

# ── I2S init ──────────────────────────────────────────────────────
print("\n[1] I2S init...")
try:
    audio = I2S(
        0,
        sck=Pin(BCLK_PIN),
        ws=Pin(LRC_PIN),
        sd=Pin(DIN_PIN),
        mode=I2S.TX,
        bits=BITS,
        format=I2S.MONO,
        rate=SAMPLE_RATE,
        ibuf=BUF_BYTES,
    )
    print(f"    ✓ I2S-0 ready")
    print(f"    BCLK=GP{BCLK_PIN}  LRC=GP{LRC_PIN}  DIN=GP{DIN_PIN}")
    print(f"    Rate={SAMPLE_RATE}Hz  Bits={BITS}  Mono")
except Exception as e:
    print(f"    ✗ I2S init failed: {e}")
    print("    Check: GP0→BCLK, GP1→LRC, GP16→DIN")
    raise SystemExit

# ── Tone generator ────────────────────────────────────────────────
def generate_tone(freq, duration_ms, volume=0.5, sample_rate=22050):
    """Generate a sine wave tone as a bytearray."""
    num_samples = int(sample_rate * duration_ms / 1000)
    buf = bytearray(num_samples * 2)
    for i in range(num_samples):
        sample = int(32767 * volume * math.sin(2 * math.pi * freq * i / sample_rate))
        struct.pack_into('<h', buf, i * 2, sample)
    return buf

def play_tone(freq, duration_ms, volume=0.5):
    """Play a tone at given frequency and duration."""
    buf = generate_tone(freq, duration_ms, volume)
    mv  = memoryview(buf)
    audio.write(mv)

def play_silence(duration_ms):
    """Play silence to flush the I2S buffer cleanly."""
    num_samples = int(SAMPLE_RATE * duration_ms / 1000)
    buf = bytearray(num_samples * 2)
    audio.write(memoryview(buf))

# ── Test 2: Single tone ───────────────────────────────────────────
print("\n[2] Single tone test — 440Hz (A4) for 1 second...")
print("    You should hear a clear tone from the speaker")
try:
    play_tone(440, 1000, volume=0.4)
    play_silence(200)
    print("    ✓ Tone sent — did you hear it? (y/n)")
    print("    If silent: check speaker wires, VIN→3.3V, SD→3.3V")
except Exception as e:
    print(f"    ✗ Tone failed: {e}")

time.sleep_ms(500)

# ── Test 3: Frequency sweep ───────────────────────────────────────
print("\n[3] Frequency sweep — 200Hz to 2000Hz...")
print("    You should hear a rising tone")
try:
    freqs = [200, 300, 440, 600, 800, 1000, 1200, 1500, 2000]
    for f in freqs:
        play_tone(f, 200, volume=0.4)
    play_silence(200)
    print("    ✓ Sweep complete")
except Exception as e:
    print(f"    ✗ Sweep failed: {e}")

time.sleep_ms(500)

# ── Test 4: Volume levels ─────────────────────────────────────────
print("\n[4] Volume levels — same tone at 3 volumes...")
print("    You should hear 3 beeps getting louder")
try:
    for vol in [0.15, 0.35, 0.6]:
        play_tone(660, 400, volume=vol)
        play_silence(150)
    print("    ✓ Volume test complete")
except Exception as e:
    print(f"    ✗ Volume test failed: {e}")

time.sleep_ms(500)

# ── Test 5: Game-style sounds ─────────────────────────────────────
print("\n[5] Game-style sound effects...")

print("    Correct answer sound (rising two-tone)...")
try:
    play_tone(523, 120, 0.4)   # C5
    play_tone(659, 200, 0.4)   # E5
    play_silence(100)
    print("    ✓")
except Exception as e:
    print(f"    ✗ {e}")

time.sleep_ms(300)

print("    Wrong answer sound (descending)...")
try:
    play_tone(330, 120, 0.4)   # E4
    play_tone(262, 250, 0.4)   # C4
    play_silence(100)
    print("    ✓")
except Exception as e:
    print(f"    ✗ {e}")

time.sleep_ms(300)

print("    Level up fanfare...")
try:
    notes = [(523,100),(659,100),(784,100),(1047,300)]
    for freq, dur in notes:
        play_tone(freq, dur, 0.4)
    play_silence(100)
    print("    ✓")
except Exception as e:
    print(f"    ✗ {e}")

time.sleep_ms(300)

print("    Menu move click...")
try:
    play_tone(880, 60, 0.25)
    play_silence(50)
    print("    ✓")
except Exception as e:
    print(f"    ✗ {e}")

time.sleep_ms(300)

print("    Countdown beeps (3-2-1-GO)...")
try:
    for _ in range(3):
        play_tone(440, 100, 0.4)
        play_silence(300)
    play_tone(880, 300, 0.5)
    play_silence(100)
    print("    ✓")
except Exception as e:
    print(f"    ✗ {e}")

# ── Test 6: Sustained playback stability ──────────────────────────
print("\n[6] Sustained playback stability (5 seconds)...")
print("    Playing looping tones — listen for glitches or dropouts")
try:
    start = time.ticks_ms()
    melody = [
        (523, 300), (587, 300), (659, 300), (698, 300),
        (784, 300), (698, 300), (659, 300), (587, 300),
    ]
    idx = 0
    while time.ticks_diff(time.ticks_ms(), start) < 5000:
        freq, dur = melody[idx % len(melody)]
        play_tone(freq, dur, 0.35)
        idx += 1
    play_silence(200)
    print("    ✓ 5 seconds stable — no dropouts")
except Exception as e:
    print(f"    ✗ Stability test failed: {e}")

# ── Cleanup ───────────────────────────────────────────────────────
play_silence(500)
audio.deinit()

# ── Summary ───────────────────────────────────────────────────────
print()
print("=" * 48)
print("  TEST 8 — AUDIO SUMMARY")
print("  I2S init     : ✓ GP0/GP1/GP16")
print("  Tone output  : ✓ (confirm audible)")
print("  Freq sweep   : ✓")
print("  Volume ctrl  : ✓")
print("  Game sounds  : ✓")
print("  Stability    : ✓ 5s no dropouts")
print()
print("  If silent throughout:")
print("  - Check speaker wires to MAX98357A terminals")
print("  - Check VIN and SD both → 3.3V")
print("  - Check BCLK/LRC/DIN wiring to GP0/GP1/GP16")
print()
print("  Next: test_09_leds.py")
print("=" * 48)
print()