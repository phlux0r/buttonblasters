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
# ✓ BENCH-CONFIRMED, recalibrated after D1 (the reverse-blocking Schottky
# diode in the battery->VSYS path) made VSYS no longer the same node as
# the battery terminals. IMPORTANT: this test's DIVIDER converts raw ->
# VSYS voltage, NOT battery voltage -- on battery-only power, VSYS reads
# ~0.365V (config.VSYS_DROP_V) below the battery's own terminal voltage
# now (diode drop + switch/wiring). On USB power this test measures
# something different again (VSYS dominated by VBUS through the Pico's
# own internal diode, not the battery path at all) -- for real battery
# calibration, use tests/battery_calibration_log.py instead, which runs
# untethered on battery power and logs to SD instead of the console.
#
# raw -> VSYS: now a real two-point zero-intercept fit (3.80V and
# 3.58V, measured directly at the pin), independently agreeing to
# ~0.2% -- ratio 2.988, ~3.5mV residual at each point. See config.py's
# battery section for the full writeup.
# ─────────────────────────────────────────────────────────────────

import time
from machine import ADC, Pin

print()
print("=" * 48)
print("  Button Blasters — TEST 16: Battery VSYS (GP29/ADC3)")
print("=" * 48)

ADC_MAX   = 65535       # read_u16() full scale
ADC_VREF  = 3.3         # RP2350 ADC reference voltage
DIVIDER   = 2.988       # ✓ bench-confirmed, 2-point zero-intercept fit -- converts raw to VSYS, not battery voltage (see header)

VSYS_DROP_V = 0.365     # battery -> VSYS: diode + switch/wiring (see header)
BAT_FULL_V  = 4.2 - VSYS_DROP_V    # in VSYS-domain terms, to match read_voltage()
BAT_EMPTY_V = 3.3 - VSYS_DROP_V

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
print("  TEST 16 complete. DIVIDER=2.988 is a 2-point zero-intercept fit")
print("  (VSYS 3.80V and 3.58V) with only ~3.5mV residual at each point.")
print("  A third reading nearer BAT_EMPTY_V (~2.93V in VSYS terms) would")
print("  tighten this further if ever needed. See config.py.")
print("=" * 48)
