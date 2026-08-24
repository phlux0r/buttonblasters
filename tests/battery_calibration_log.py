# tests/battery_calibration_log.py — Button Blasters
# Battery-only VSYS calibration logger — for recalibrating
# config.VSYS_ADC_RATIO now that D1 (the reverse-blocking Schottky diode
# in the battery->VSYS path) is permanently in the circuit. The original
# 2.55 ratio was calibrated with the battery wired straight to VSYS, no
# diode -- D1's forward drop shifts every battery-only reading down by
# however many tenths of a volt it drops, and this script gets fresh
# bench data against the CURRENT as-built hardware instead of guessing
# at the diode's exact drop.
#
# WHY THIS ISN'T JUST test_16_battery_vsys.py: that test print()s to the
# USB serial console, which requires being tethered to a computer -- but
# VSYS reads differently on USB power (dominated by VBUS through the
# Pico's own internal diode) than on battery-only power, which is
# exactly the case that needs calibrating. This logs to the SD card
# instead, so it works fully untethered.
#
# HOW TO USE:
#   1. While still on USB (for the copy step), back up your real main.py:
#        mpremote connect <port> cp :main.py :main_backup.py
#   2. Copy this file in as main.py:
#        mpremote connect <port> cp tests/battery_calibration_log.py :main.py
#   3. Unplug USB. Flip the power switch on. Start a stopwatch (phone
#      timer is fine) the moment power comes on.
#   4. Take multimeter readings directly on the LiPo cell's own terminals
#      (or TP4056 B+/B-, same net) -- NOT on VSYS, that's the value being
#      calibrated against. Note the elapsed time (from your stopwatch)
#      each time you take a reading. Get one point on a fresher charge
#      and one closer to empty (~3.3V) if you can, not two close together.
#   5. Power off. Reconnect USB, restore the real firmware:
#        mpremote connect <port> cp :main_backup.py :main.py
#   6. Pull the log off the SD card (card reader, or mpremote):
#        mpremote connect <port> cp :/sd/battery_calibration_log.txt .
#   7. For each multimeter reading, find the log line with the closest
#      elapsed_ms and send both (multimeter volts + that line's raw
#      value) back for the ratio to be recomputed.

import os
import time
from machine import ADC, Pin, SPI
import config

_LOG_PATH   = "/sd/battery_calibration_log.txt"
_INTERVAL_S = 2
_ADC_MAX    = 65535
_ADC_VREF   = 3.3
_DIVIDER    = 2.985  # current best-known VSYS ratio (config.VSYS_ADC_RATIO)
                      # -- logged raw value is what actually matters for
                      # recalibration, this column is just a live sanity check

wifi_cs = Pin(25, Pin.OUT, value=1)
adc     = ADC(29)


def read_voltage():
    wifi_cs.value(1)
    raw = adc.read_u16()
    return raw, raw * (_ADC_VREF * _DIVIDER / _ADC_MAX)


def _mount_sd() -> bool:
    # Standalone as main.py, this never goes through the kernel's normal
    # boot sequence (drivers/assets.py's mount_sd()) -- nothing else has
    # mounted the card, so this has to do it itself. Same parameters
    # already confirmed working there: all other CS pins held high first
    # to avoid bus contention, SD_INIT baudrate for the handshake, then
    # SDCard's own baudrate= is the post-init data rate.
    try:
        from sdcard import SDCard
        other_cs = (config.PIN_CS_MAIN, config.PIN_CS_BTN[0],
                    config.PIN_CS_BTN[1], config.PIN_CS_BTN[2],
                    config.PIN_CS_BTN[3])
        for pin_num in other_cs:
            Pin(pin_num, Pin.OUT, value=1)
        cs     = Pin(config.PIN_CS_SD, Pin.OUT, value=1)
        sd_spi = SPI(config.SPI_ID,
                     baudrate=config.SPI_FREQ_SD_INIT,
                     sck=Pin(config.PIN_SCK),
                     mosi=Pin(config.PIN_MOSI),
                     miso=Pin(config.PIN_MISO))
        sd = SDCard(sd_spi, cs, baudrate=config.SPI_FREQ_SD_DATA)
        os.mount(sd, "/sd")
        return True
    except Exception as e:
        print("[battery_cal] SD mount failed:", e)
        return False


def run():
    start = time.ticks_ms()
    if not _mount_sd():
        # Nothing else this script does matters without a place to log
        # to -- stop here rather than silently producing an empty run.
        return
    try:
        f = open(_LOG_PATH, "a")
    except OSError as e:
        print("[battery_cal] can't open log file:", e)
        return

    f.write("=== battery_calibration_log start ===\n")
    f.flush()
    try:
        while True:
            elapsed_ms = time.ticks_diff(time.ticks_ms(), start)
            raw, v = read_voltage()
            line = "elapsed_ms=%d  raw=%d  voltage(old ratio)=%.2f\n" % (
                elapsed_ms, raw, v)
            f.write(line)
            f.flush()   # so a reboot/power-loss mid-run doesn't lose data
            time.sleep(_INTERVAL_S)
    except KeyboardInterrupt:
        pass
    finally:
        f.close()


run()
