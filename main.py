# main.py — Button Blasters
# Entry point — runs on MicroPython v1.28.0 / RP2350 Pico 2W
#
# Boot sequence:
#   1. Hardware init (displays, touch, audio, LEDs)
#   2. SD card mount + asset index (deferred — non-fatal if absent)
#   3. AppKernel asyncio event loop

import asyncio
import machine
import config

# Set the core clock BEFORE importing the kernel. drivers/spi_bus.py builds
# its SPI object at import time and the baud rate is derived from sysclk at
# that moment, so the overclock must already be in place — hence this runs
# before `from core.kernel import ...` below (intentionally not at top).
# Tune config.MACHINE_FREQ per the notes in config.py.
machine.freq(config.MACHINE_FREQ)

from core.kernel import AppKernel


async def boot():
    kernel = AppKernel()
    await kernel.init()
    await kernel.run()


asyncio.run(boot())
