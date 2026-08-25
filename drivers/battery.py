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
# ✓ BENCH-CONFIRMED, recalibrated after D1 (the reverse-blocking Schottky
# diode in the battery->VSYS path) made VSYS no longer the same node as
# the battery terminals. read_voltage() below returns the real VSYS
# voltage (config.VSYS_ADC_RATIO=2.985, refit for the as-built board);
# read_percent() subtracts config.VSYS_DROP_V (the measured battery->VSYS
# gap — diode drop + switch/wiring, ~0.37V on this board) from
# BAT_FULL_V/BAT_EMPTY_V before comparing, since those two stay in
# battery-terminal-voltage units. See config.py's battery section for
# the full recalibration writeup and tests/battery_calibration_log.py
# for how to tighten either value further.

import config


class BatteryMonitor:
    """LiPo battery voltage/percentage via VSYS (GP29/ADC3)."""

    _ADC_MAX  = 65535   # read_u16() full scale
    _ADC_VREF = 3.3     # RP2350 ADC reference voltage

    # Two-layer smoothing -- confirmed on hardware that a raw single-sample
    # read visibly jumps with the display's own SPI load: navigating the
    # menu measurably sags VSYS for the instant a redraw is busy, and it
    # "recharges" back the moment things go idle again. The battery hasn't
    # actually changed that fast either way -- only the reading has.
    #   _SAMPLES:   averaged within one read_voltage() call, cheap ADC/
    #               electrical noise reduction.
    #   _EMA_ALPHA: blended ACROSS calls (each menu redraw is one call),
    #               so a single busy-redraw sample only nudges the
    #               displayed value a little instead of snapping straight
    #               to it -- rides through the sag/recover cycle instead
    #               of visibly tracking it.
    _SAMPLES   = 8
    _EMA_ALPHA = 0.15

    def __init__(self):
        self._ready   = False
        self._adc     = None
        self._wifi_cs = None
        self._ema_v   = None
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
        """Sample VSYS (averaged + EMA-smoothed, see class docstring).
        Holds the wireless chip's CS line high (deselected) during the
        read — a no-op in practice since this firmware never drives WiFi,
        but matches the documented safe-read pattern for this board's
        shared ADC3/SPI-CLK pin."""
        if not self._ready:
            return 0.0
        self._wifi_cs.value(1)
        total = 0
        for _ in range(self._SAMPLES):
            total += self._adc.read_u16()
        raw = total / self._SAMPLES
        v   = raw * (self._ADC_VREF * config.VSYS_ADC_RATIO / self._ADC_MAX)
        if self._ema_v is None:
            self._ema_v = v
        else:
            self._ema_v += self._EMA_ALPHA * (v - self._ema_v)
        return self._ema_v

    def read_percent(self) -> int:
        """0-100, linearly interpolated between config.BAT_EMPTY_V and
        config.BAT_FULL_V — both battery-terminal-voltage thresholds, so
        config.VSYS_DROP_V is subtracted from them here to compare against
        read_voltage()'s VSYS-domain reading on equal terms. Not a true
        LiPo discharge curve (which is non-linear) — fine for a coarse
        indicator, not a precision gauge. Returns -1 if not ready."""
        if not self._ready:
            return -1
        v          = self.read_voltage()
        vsys_full  = config.BAT_FULL_V  - config.VSYS_DROP_V
        vsys_empty = config.BAT_EMPTY_V - config.VSYS_DROP_V
        if v >= vsys_full:
            return 100
        if v <= vsys_empty:
            return 0
        span = vsys_full - vsys_empty
        return int((v - vsys_empty) / span * 100)

    @property
    def low(self) -> bool:
        """True at/below config.BAT_WARN_PCT. False (not ready) is not
        the same as "not low" for a caller that cares about the
        distinction — check .ready first if that matters."""
        if not self._ready:
            return False
        return self.read_percent() <= config.BAT_WARN_PCT


battery = BatteryMonitor()
