# main.py — Button Blasters
# Entry point — runs on MicroPython v1.28.0 / RP2350 Pico 2W
#
# Boot sequence:
#   1. Hardware init (displays, touch, audio, LEDs)
#   2. SD card mount + asset index (deferred — non-fatal if absent)
#   3. AppKernel asyncio event loop

import asyncio
from core.kernel import AppKernel


async def boot():
    kernel = AppKernel()
    await kernel.init()
    await kernel.run()


asyncio.run(boot())
