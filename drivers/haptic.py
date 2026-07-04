# drivers/haptic.py — Button Blasters v3.0
# ERM coin haptic motor via 2N3904 NPN transistor — confirmed GP22.
# 1kΩ base resistor, 1N4148 flyback diode across motor.
# Motor: red wire → collector, blue wire → 3.3V.
#
# GP22 is initialised LOW at boot to prevent motor floating.

import asyncio
import config


class HapticDriver:
    """
    Haptic motor driver.
    Confirmed working: GP22 via 2N3904 NPN transistor.
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
            # Initialise LOW immediately — prevents motor floating at boot
            self._pin   = Pin(config.PIN_HAPTIC, Pin.OUT, value=0)
            self._ready = True
            print(f"[haptic] motor ready  GP{config.PIN_HAPTIC}  "
                  f"init LOW (motor off)")
        except Exception as e:
            print(f"[haptic] init failed: {e}")

    @property
    def ready(self) -> bool:
        return self._ready

    def off(self):
        if self._ready:
            self._pin.value(0)

    async def pulse(self, ms: int = None):
        """Single buzz."""
        if not self._ready:
            return
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

    async def triple_pulse(self):
        """Three rapid taps — star earned."""
        for _ in range(3):
            await self.pulse(30)
            await asyncio.sleep_ms(40)

    async def pattern(self, on_ms: int, off_ms: int, count: int):
        """Arbitrary buzz pattern."""
        for _ in range(count):
            await self.pulse(on_ms)
            await asyncio.sleep_ms(off_ms)

    async def game_over(self):
        """Long-short-long — game over pattern."""
        await self.pulse(200)
        await asyncio.sleep_ms(80)
        await self.pulse(60)
        await asyncio.sleep_ms(80)
        await self.pulse(200)


haptic = HapticDriver()
