# drivers/spi_bus.py — Button Blasters
# Shared SPI bus manager.
#
# All displays share SPI0. Only one device can be active at a time.
# SpiBus serialises access via an asyncio.Lock so coroutines can
# safely interleave display updates.
#
# Usage:
#   async with spi_bus.device(cs_pin, freq=SPI_FREQ_DISPLAY):
#       spi_bus.write(data)

import asyncio
from machine import SPI, Pin
import config


class SpiBus:
    """Singleton wrapper around SPI0 with cooperative locking."""

    def __init__(self):
        self.spi = SPI(
            config.SPI_ID,
            baudrate=config.SPI_FREQ_DISPLAY,
            sck=Pin(config.PIN_SCK),
            mosi=Pin(config.PIN_MOSI),
            miso=Pin(config.PIN_MISO),
        )
        self._lock = asyncio.Lock()
        self._current_freq = config.SPI_FREQ_DISPLAY

    def _set_freq(self, freq):
        if freq != self._current_freq:
            self.spi.init(baudrate=freq)
            self._current_freq = freq

    def device(self, cs_pin: Pin, freq: int = None):
        """Context manager: acquire lock, assert CS, restore on exit."""
        return _DeviceContext(self, cs_pin,
                              freq or config.SPI_FREQ_DISPLAY)

    def write(self, buf):
        self.spi.write(buf)

    def write_readinto(self, out_buf, in_buf):
        self.spi.write_readinto(out_buf, in_buf)

    def read(self, n, write=0x00):
        return self.spi.read(n, write)


class _DeviceContext:
    def __init__(self, bus: SpiBus, cs: Pin, freq: int):
        self._bus  = bus
        self._cs   = cs
        self._freq = freq

    async def __aenter__(self):
        await self._bus._lock.acquire()
        self._bus._set_freq(self._freq)
        self._cs.value(0)
        return self._bus

    async def __aexit__(self, *_):
        self._cs.value(1)
        self._bus._lock.release()


spi_bus = SpiBus()
