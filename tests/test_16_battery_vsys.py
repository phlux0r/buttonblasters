# tests/test_16_battery_vsys.py — Button Blasters
# TEST 16 — LiPo battery voltage/percentage via VSYS (GP29/ADC3)
#
# Wiring:
#   LiPo battery + → VSYS (physical pin 39)
#   LiPo battery - → GND (physical pin 38, or any GND)
#   No new components needed — this reads the Pico 2 W's own onboard
#   VSYS monitor circuit. NOT wired through MCP23008 — this uses the
#   RP2350's native ADC3, which happens to share its physical pin (GP29)
#   with the CYW43439 wireless chip's SPI CLK line.
#
# BEFORE RUNNING THIS: config.PIN_BAT_ADC (GP29) was previously marked
# "WiFi internal — never connect anything" in config.py, but that note
# was inherited caution, never an actual observed hardware failure (never
# wired/tested). This project also never imports `network`/uses WLAN
# anywhere, so the "don't read while WiFi chip is mid-SPI-transaction"
# conflict this pin is normally at risk of never actually arises here —
# but this test still does the documented safe-read dance (GP25 high)
# as cheap insurance, matching the standard technique for this board.
#
# What this tests:
#   1. ADC3/GP29 reads a raw 16-bit value without raising
#   2. Computed voltage is a plausible LiPo range (roughly 3.0-4.2V)
#   3. GP25-high dance doesn't crash even though WLAN is never active here
#   4. Percentage interpolation between BAT_EMPTY_V/BAT_FULL_V
#
# ✓ BENCH-CONFIRMED, two data points — the widely-documented Pico-W-family
# divider of 3 was WRONG for this board (first run: ~94% vs a real ~17%,
# not a small error). Two calibration points so far:
#   3.45V multimeter <-> raw≈27520  (implies ratio ≈2.49 alone)
#   3.71V multimeter <-> raw≈28257  (implies ratio ≈2.61 alone)
# They don't fully agree (~4.7% apart) — likely LiPo "surface charge"
# settling right after charging rather than a flaw in the ratio itself.
# Combined zero-intercept fit: ≈2.55 (used below), still ~±0.08V residual
# at each point — good enough for a coarse indicator, not lab-grade. For
# tighter calibration: let the battery rest 15+ min post-charge, take
# both readings close together in time, and get a third point further
# away (e.g. near BAT_EMPTY_V ~3.3V) for a real linear fit. See
# config.VSYS_ADC_RATIO.
# ─────────────────────────────────────────────────────────────────

import time
from machine import ADC, Pin

print()
print("=" * 48)
print("  Button Blasters — TEST 16: Battery VSYS (GP29/ADC3)")
print("=" * 48)

ADC_MAX   = 65535       # read_u16() full scale
ADC_VREF  = 3.3         # RP2350 ADC reference voltage
DIVIDER   = 2.55        # ✓ bench-confirmed on this board, 2-point fit (was 3 — wrong, see header)

BAT_FULL_V  = 4.2
BAT_EMPTY_V = 3.3

print("\n[1] GP25 init (WiFi chip-select line — drive HIGH to deselect)...")
wifi_cs = Pin(25, Pin.OUT, value=1)
print("    OK — GP25 held HIGH")

print("\n[2] ADC3/GP29 init...")
adc = ADC(29)
print("    OK — ADC object created")


def read_voltage():
    wifi_cs.value(1)          # deselect wireless chip before sampling
    raw = adc.read_u16()
    return raw, raw * (ADC_VREF * DIVIDER / ADC_MAX)


def percent_for(v):
    if v >= BAT_FULL_V:
        return 100
    if v <= BAT_EMPTY_V:
        return 0
    return int((v - BAT_EMPTY_V) / (BAT_FULL_V - BAT_EMPTY_V) * 100)


print("\n[3] Sampling every 2s for 30s — compare against a multimeter")
print("    reading of the battery/VSYS rail. Ctrl-C to stop early.\n")

try:
    for i in range(15):
        raw, v = read_voltage()
        pct = percent_for(v)
        print(f"  raw={raw:5d}  voltage={v:.2f}V  ~{pct:3d}%")
        time.sleep(2)
except KeyboardInterrupt:
    pass

print("\n" + "=" * 48)
print("  TEST 16 complete. DIVIDER=2.55 is a 2-point fit (3.45V and")
print("  3.71V) that still leaves ~+/-0.08V residual error at each")
print("  point. A third reading further away (e.g. near BAT_EMPTY_V,")
print("  ~3.3V), taken 15+ min after any charging, would tighten this.")
print("=" * 48)
