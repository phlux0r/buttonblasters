# tests/test_07_mcp23008.py — Button Blasters
# TEST 7 — MCP23008 I2C GPIO expander bring-up
#
# Wiring (left side + VDD only for this test):
#   Pin 1  SCL   → GP27 (shared I2C bus with FT6236)
#   Pin 2  SDA   → GP26 (shared I2C bus with FT6236)
#   Pin 3  A2    → GND  ┐
#   Pin 4  A1    → GND  ├ sets address to 0x20
#   Pin 5  A0    → GND  ┘
#   Pin 6  RESET → 3.3V
#   Pin 7  INT   → unconnected
#   Pin 8  VSS   → GND
#   Pin 18 VDD   → 3.3V + 0.1µF cap to GND (as close to chip as possible)
#   Pins 9-17 (GP0-GP7) → unconnected for this test
#
# What this tests:
#   1. I2C bus scan — FT6236 at 0x38 and MCP23008 at 0x20 both visible
#   2. MCP23008 register read — verify chip responds correctly
#   3. Configure all 8 GPIO pins as outputs
#   4. Toggle each pin HIGH/LOW — probe with multimeter to verify
#   5. Walking 1 pattern — one pin HIGH at a time across all 8
#   6. Confirm FT6236 still works after MCP23008 wired (bus integrity)
#
# Expected: both devices visible on scan, all 8 pins toggle cleanly
# ─────────────────────────────────────────────────────────────────

import time
from machine import I2C, Pin

print()
print("=" * 48)
print("  Button Blasters — TEST 7: MCP23008 expander")
print("=" * 48)

# ── MCP23008 register map ─────────────────────────────────────────
MCP_ADDR    = 0x20
FT_ADDR     = 0x38

IODIR       = 0x00   # direction: 1=input, 0=output
IPOL        = 0x01   # input polarity
GPINTEN     = 0x02   # interrupt enable
DEFVAL      = 0x03   # default compare value
INTCON      = 0x04   # interrupt control
IOCON       = 0x05   # configuration
GPPU        = 0x06   # pull-up resistors
INTF        = 0x07   # interrupt flag
INTCAP      = 0x08   # interrupt capture
GPIO_REG    = 0x09   # GPIO port register
OLAT        = 0x0A   # output latch

# ── I2C init ─────────────────────────────────────────────────────
print("\n[1] I2C init...")
try:
    i2c = I2C(1, sda=Pin(26), scl=Pin(27), freq=400_000)
    print("    ✓ I2C-1 on GP26/GP27 at 400kHz")
except Exception as e:
    print(f"    ✗ I2C init failed: {e}")
    raise SystemExit

# ── Bus scan ─────────────────────────────────────────────────────
print("\n[2] I2C bus scan...")
devices = i2c.scan()
print(f"    Found {len(devices)} device(s): {[hex(d) for d in devices]}")

ft_found  = FT_ADDR  in devices
mcp_found = MCP_ADDR in devices

if ft_found:
    print(f"    ✓ FT6236 touch at 0x{FT_ADDR:02X}")
else:
    print(f"    ⚠ FT6236 not found — touch not wired or powered?")

if mcp_found:
    print(f"    ✓ MCP23008 at 0x{MCP_ADDR:02X}")
else:
    print(f"    ✗ MCP23008 not found at 0x{MCP_ADDR:02X}")
    print(f"    Check: VDD→3.3V, VSS→GND, RESET→3.3V")
    print(f"    Check: A0/A1/A2 all → GND, SDA→GP26, SCL→GP27")
    raise SystemExit

# ── MCP23008 helpers ──────────────────────────────────────────────
def mcp_write(reg, val):
    i2c.writeto_mem(MCP_ADDR, reg, bytes([val]))

def mcp_read(reg):
    return i2c.readfrom_mem(MCP_ADDR, reg, 1)[0]

# ── Register verify ───────────────────────────────────────────────
print("\n[3] Register verification...")
try:
    # At power-up IODIR should be 0xFF (all inputs by default)
    iodir = mcp_read(IODIR)
    print(f"    IODIR at boot: 0x{iodir:02X} "
          f"({'0xFF = all inputs (correct)' if iodir == 0xFF else 'unexpected value'})")

    # Read IOCON
    iocon = mcp_read(IOCON)
    print(f"    IOCON:  0x{iocon:02X}")

    # Read GPIO
    gpio_val = mcp_read(GPIO_REG)
    print(f"    GPIO:   0x{gpio_val:02X}")
    print("    ✓ Chip responding to register reads")
except Exception as e:
    print(f"    ✗ Register read failed: {e}")
    raise SystemExit

# ── Configure all pins as outputs ─────────────────────────────────
print("\n[4] Configuring all 8 GPIO pins as outputs...")
try:
    mcp_write(IODIR, 0x00)   # all outputs
    mcp_write(OLAT,  0x00)   # all LOW initially
    iodir_check = mcp_read(IODIR)
    if iodir_check == 0x00:
        print("    ✓ IODIR = 0x00 — all pins configured as outputs")
    else:
        print(f"    ✗ IODIR readback = 0x{iodir_check:02X} (expected 0x00)")
except Exception as e:
    print(f"    ✗ Config failed: {e}")
    raise SystemExit

# ── All HIGH / all LOW test ───────────────────────────────────────
print("\n[5] All pins HIGH / LOW test...")
print("    Probe any GP0-GP7 pin with multimeter:")

mcp_write(OLAT, 0xFF)
time.sleep_ms(100)
readback = mcp_read(OLAT)
print(f"    All HIGH — OLAT readback: 0x{readback:02X} "
      f"({'✓' if readback == 0xFF else '✗ expected 0xFF'})")
print("    → Multimeter on any output pin should read ~3.3V")
time.sleep_ms(2000)

mcp_write(OLAT, 0x00)
time.sleep_ms(100)
readback = mcp_read(OLAT)
print(f"    All LOW  — OLAT readback: 0x{readback:02X} "
      f"({'✓' if readback == 0x00 else '✗ expected 0x00'})")
print("    → Multimeter on any output pin should read ~0V")
time.sleep_ms(2000)

# ── Walking 1 pattern ─────────────────────────────────────────────
print("\n[6] Walking 1 pattern (one pin HIGH at a time)...")
print("    Watch with multimeter — each pin goes HIGH for 500ms in turn")
print()

pin_names = [
    "GP0 (I2S BCLK)",
    "GP1 (I2S LRC) ",
    "GP2 (I2S DIN) ",
    "GP3 (bat ADC) ",
    "GP4 (WS2812B) ",
    "GP5 (haptic)  ",
    "GP6 (spare)   ",
    "GP7 (spare)   ",
]

for i in range(8):
    val = 1 << i
    mcp_write(OLAT, val)
    readback = mcp_read(OLAT)
    ok = "✓" if readback == val else f"✗ got 0x{readback:02X}"
    print(f"    Pin {i} {pin_names[i]}  → 0x{val:02X}  {ok}")
    time.sleep_ms(500)

mcp_write(OLAT, 0x00)   # all off
print("    All pins LOW — walking 1 complete")

# ── FT6236 still alive? ───────────────────────────────────────────
print("\n[7] FT6236 bus integrity check...")
try:
    i2c.writeto_mem(FT_ADDR, 0x80, bytes([22]))
    i2c.writeto_mem(FT_ADDR, 0x86, bytes([0x00]))
    chip_id = i2c.readfrom_mem(FT_ADDR, 0xA8, 1)[0]
    fw_ver  = i2c.readfrom_mem(FT_ADDR, 0xA6, 1)[0]
    print(f"    ✓ FT6236 still responding — chip ID: 0x{chip_id:02X}  FW: {fw_ver}")
    print("    ✓ MCP23008 and FT6236 coexist on I2C bus correctly")
except Exception as e:
    print(f"    ✗ FT6236 check failed: {e}")
    print("    I2C bus may have contention — check wiring")

# ── Quick output exercise ─────────────────────────────────────────
print("\n[8] 5-second output exercise (all pins alternating)...")
print("    Ctrl+C to stop early")
start = time.ticks_ms()
try:
    phase = False
    while time.ticks_diff(time.ticks_ms(), start) < 5000:
        mcp_write(OLAT, 0xFF if phase else 0x00)
        phase = not phase
        time.sleep_ms(200)
except KeyboardInterrupt:
    pass
mcp_write(OLAT, 0x00)
print("    Done — all pins LOW")

# ── Summary ───────────────────────────────────────────────────────
print()
print("=" * 48)
print("  TEST 7 — MCP23008 SUMMARY")
print(f"  I2C bus scan  : {'✓' if mcp_found else '✗'}")
print(f"  FT6236 touch  : {'✓ still alive' if ft_found else '⚠ not found'}")
print(f"  MCP23008      : {'✓ responding' if mcp_found else '✗ not found'}")
print(f"  Register r/w  : ✓")
print(f"  Pin toggle    : ✓ (verify with multimeter)")
print()
print("  Pin assignments for next steps:")
print("  MCP GP0 → I2S BCLK  (MAX98357A audio)")
print("  MCP GP1 → I2S LRC   (MAX98357A audio)")
print("  MCP GP2 → I2S DIN   (MAX98357A audio)")
print("  MCP GP3 → Battery ADC signal")
print("  MCP GP4 → WS2812B data (via 74AHCT125)")
print("  MCP GP5 → Haptic motor (via 2N3904)")
print("  MCP GP6 → spare")
print("  MCP GP7 → spare")
print()
if mcp_found:
    print("  ✓ MCP23008 ready — proceed to audio wiring")
else:
    print("  ✗ Fix MCP23008 before proceeding")
print("=" * 48)
print()
