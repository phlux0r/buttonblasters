# test_fill_speed.py — Button Blasters diagnostic
# Confirms whether the slow main-screen fill is an SPI frequency desync
# caused by the SD mount, or something else.
#
# Run this standalone (not via main.py). It:
#   1. Inits displays + spi_bus (bus should be at 10MHz)
#   2. Times a full main-screen fill  -> EXPECT ~0.5s
#   3. Mounts the SD card (the suspected culprit)
#   4. Times an identical fill again   -> if now many seconds, SD mount
#      left the bus slow and spi_bus's cached _current_freq is lying
#   5. Prints spi_bus._current_freq vs a freshly forced re-init

import time
import config
from drivers.spi_bus import spi_bus
from core.display_manager import display
from drivers.assets import assets


def _time_fill(label):
    t0 = time.ticks_ms()
    # Fill main screen red via the same path the menu uses.
    import asyncio
    asyncio.run(display.fill_main(0xF800))
    dt = time.ticks_diff(time.ticks_ms(), t0)
    print(f"  {label}: {dt} ms  (spi_bus._current_freq={spi_bus._current_freq})")
    return dt


print("Init displays...")
display.init_all()

print("\n--- Fill BEFORE SD mount (expect ~500ms) ---")
before = _time_fill("fill #1 (pre-SD)")

print("\n--- Mounting SD card ---")
ok = assets.mount_sd()
print("  mount_sd() returned:", ok)

print("\n--- Fill AFTER SD mount ---")
after = _time_fill("fill #2 (post-SD)")

print("\n--- Forcing bus back to 10MHz explicitly ---")
spi_bus.spi.init(baudrate=config.SPI_FREQ_DISPLAY)
spi_bus._current_freq = config.SPI_FREQ_DISPLAY
after_fix = _time_fill("fill #3 (after forced re-init)")

print("\n=== RESULT ===")
print(f"  pre-SD:  {before} ms")
print(f"  post-SD: {after} ms")
print(f"  fixed:   {after_fix} ms")
if after > before * 3:
    print("  => CONFIRMED: SD mount slowed the bus. The frequency-desync")
    print("     fix is correct — forced re-init restores speed.")
else:
    print("  => NOT a bus-speed desync. Slowness is elsewhere (likely the")
    print("     per-round framebuf allocation in shape drawing). Tell Claude.")