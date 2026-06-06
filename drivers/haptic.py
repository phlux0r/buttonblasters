# drivers/haptic.py
# Haptic motor driver — ERM coin motor via NPN transistor on GP25.
# Simple on/off pulses; no PWM needed for basic rumble.
#
# Usage:
#   await haptic.pulse()              # single short buzz
#   await haptic.double_pulse()       # two quick taps (correct answer)
#   await haptic.long_pulse()         # long rumble (game over / level up)

import asyncio
from machine import Pin
import config


class HapticDriver:

    def __init__(self):
        self._pin = Pin(config.PIN_HAPTIC, Pin.OUT, value=0)

    async def pulse(self, ms: int = None):
        """Single buzz."""
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
        self._pin.value(0)


haptic = HapticDriver()
