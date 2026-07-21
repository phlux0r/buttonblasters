# drivers/battery.py — Button Blasters
# LiPo battery voltage/percentage via VSYS, read through GP29/ADC3.
#
# GP29/ADC3 shares its physical pin with the CYW43439 wireless chip's SPI
# CLK line on the Pico 2 W — reading it while the wireless chip is mid
# SPI transaction gives garbage. This firmware never activates WiFi
# (confirmed: no `network`/`WLAN` usage anywhere in this codebase), so
# that conflict never actually arises here — but this driver still does
# the documented safe-read dance (GP25 held high) as cheap insurance,
# matching the standard technique for this board.
#
# ✓ BENCH-CONFIRMED (two data points) — the widely-documented Pico-W-family
# divider ratio of 3 was WRONG for this board: reported ~94% charge for a
# battery a multimeter measured at ~17%. Two calibration points (3.45V and
# 3.71V) don't fully agree with each other (~4.7% apart, likely LiPo
# "surface charge" settling right after charging, not a flaw in the
# ratio) — combined fit is config.VSYS_ADC_RATIO=2.55, good enough for a
# coarse indicator, not lab-grade precision. See
# tests/test_16_battery_vsys.py for the full calibration history and how
# to tighten it further (a third point away from these two).

import config


class BatteryMonitor:
    """LiPo battery voltage/percentage via VSYS (GP29/ADC3)."""

    _ADC_MAX  = 65535   # read_u16() full scale
    _ADC_VREF = 3.3     # RP2350 ADC reference voltage

    def __init__(self):
        self._ready   = False
        self._adc     = None
        self._wifi_cs = None
        self._init_hardware()

    def _init_hardware(self):
        if config.PIN_BAT_ADC is None:
            print("[battery] PIN_BAT_ADC not configured — battery monitor disabled")
            return
        try:
            from machine import ADC, Pin
            self._wifi_cs = Pin(config.PIN_WIFI_CS, Pin.OUT, value=1)
            self._adc     = ADC(config.PIN_BAT_ADC)
            self._ready   = True
            print(f"[battery] VSYS monitor ready  "
                  f"GP{config.PIN_BAT_ADC} (ADC3)")
        except Exception as e:
            print(f"[battery] init failed: {e}")

    @property
    def ready(self) -> bool:
        return self._ready

    def read_voltage(self) -> float:
        """Sample VSYS. Holds the wireless chip's CS line high (deselected)
        during the read — a no-op in practice since this firmware never
        drives WiFi, but matches the documented safe-read pattern for this
        board's shared ADC3/SPI-CLK pin."""
        if not self._ready:
            return 0.0
        self._wifi_cs.value(1)
        raw = self._adc.read_u16()
        return raw * (self._ADC_VREF * config.VSYS_ADC_RATIO / self._ADC_MAX)

    def read_percent(self) -> int:
        """0-100, linearly interpolated between config.BAT_EMPTY_V and
        config.BAT_FULL_V. Not a true LiPo discharge curve (which is
        non-linear) — fine for a coarse indicator, not a precision gauge.
        Returns -1 if the monitor isn't ready."""
        if not self._ready:
            return -1
        v = self.read_voltage()
        if v >= config.BAT_FULL_V:
            return 100
        if v <= config.BAT_EMPTY_V:
            return 0
        span = config.BAT_FULL_V - config.BAT_EMPTY_V
        return int((v - config.BAT_EMPTY_V) / span * 100)

    @property
    def low(self) -> bool:
        """True at/below config.BAT_WARN_PCT. False (not ready) is not
        the same as "not low" for a caller that cares about the
        distinction — check .ready first if that matters."""
        if not self._ready:
            return False
        return self.read_percent() <= config.BAT_WARN_PCT


battery = BatteryMonitor()
