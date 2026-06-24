# drivers/haptic.py — Button Blasters
# Haptic motor driver — ERM coin motor via NPN transistor.
#
# ⚠ NOT YET WIRED — PIN_HAPTIC is None in config.
#    All public methods are safe to call — they no-op silently
#    until the hardware is connected and pin assigned.
#
# When wired: set PIN_HAPTIC in config.py — activates on next boot.

import asyncio
import config


class HapticDriver:
    """
    Simple on/off haptic motor driver.
    Safe to import and call when hardware is not yet wired.
    """

    def __init__(self):
        self._pin   = None
        self._ready = False
        self._init_hardware()

    def _init_hardware(self):
        if config.PIN_HAPTIC is None:
            print("[haptic] PIN_HAPTIC not configured — haptic disabled")
            return
        try:
            from machine import Pin
            self._pin   = Pin(config.PIN_HAPTIC, Pin.OUT, value=0)
            self._ready = True
            print(f"[haptic] motor ready on GP{config.PIN_HAPTIC}")
        except Exception as e:
            print(f"[haptic] init failed: {e}")

    @property
    def ready(self) -> bool:
        return self._ready

    async def pulse(self, ms: int = None):
        """Single buzz. No-op if not wired."""
        if not self._ready: return
        ms = ms or config.HAPTIC_PULSE_MS
        self._pin.value(1)
        await asyncio.sleep_ms(ms)
        self._pin.value(0)

    async def double_pulse(self):
        """Two quick taps — correct answer feedback."""
        await self.pulse(40)
        await asyncio.sleep_ms(60)
        await self.pulse(40)

    async def long_pulse(self, ms: int = 300):
        """Long rumble — level up / game over."""
        await self.pulse(ms)

    async def pattern(self, on_ms: int, off_ms: int, count: int):
        """Arbitrary buzz pattern."""
        for _ in range(count):
            await self.pulse(on_ms)
            await asyncio.sleep_ms(off_ms)

    def off(self):
        if self._ready:
            self._pin.value(0)


haptic = HapticDriver()
