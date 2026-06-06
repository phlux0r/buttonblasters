# main.py
# Button Blasters — entry point
# Runs on MicroPython v1.23+ / RP2040 Pico (8 MB flash)
#
# Boot sequence:
#   1. Hardware init (SPI bus, all displays, buttons, audio, LEDs)
#   2. SD card mount + asset index
#   3. Hand off to AppKernel which runs the asyncio event loop

import asyncio
from core.kernel import AppKernel

async def boot():
    kernel = AppKernel()
    await kernel.init()
    await kernel.run()

asyncio.run(boot())
