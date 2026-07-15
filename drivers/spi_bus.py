# drivers/spi_bus.py — Button Blasters v3.0
# Shared SPI bus manager — SPI0, GP18/GP19/GP4.
# Serialises access via asyncio.Lock.

import asyncio
from machine import SPI, Pin
import config


class SpiBus:

    def __init__(self):
        self.spi = SPI(
            config.SPI_ID,
            baudrate=config.SPI_FREQ_DISPLAY,
            sck=Pin(config.PIN_SCK),
            mosi=Pin(config.PIN_MOSI),
            miso=Pin(config.PIN_MISO),
        )
        self._lock         = asyncio.Lock()
        self._current_freq = config.SPI_FREQ_DISPLAY

    def _set_freq(self, freq):
        if freq != self._current_freq:
            self.spi.init(baudrate=freq)
            self._current_freq = freq

    def device(self, cs_pin: Pin, freq: int = None):
        return _DeviceContext(self, cs_pin,
                              freq or config.SPI_FREQ_DISPLAY)

    def write(self, buf):
        self.spi.write(buf)

    def write_readinto(self, out_buf, in_buf):
        self.spi.write_readinto(out_buf, in_buf)

    def read(self, n, write=0x00):
        return self.spi.read(n, write)

    def raw(self, freq: int):
        """For devices that manage their own CS internally (e.g. SD, via
        sdcard.py's per-block CS toggling) — just serialises bus access
        and sets frequency through the cache-aware path. No CS control."""
        return _RawContext(self, freq)


class _RawContext:
    def __init__(self, bus: SpiBus, freq: int):
        self._bus  = bus
        self._freq = freq

    async def __aenter__(self):
        await self._bus._lock.acquire()
        self._bus._set_freq(self._freq)
        return self._bus

    async def __aexit__(self, *_):
        self._bus._lock.release()

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
