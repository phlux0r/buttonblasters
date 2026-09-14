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
        # Skip the re-init when the cache already matches — re-init is a
        # real hardware reconfigure, and paying it on every SPI transaction
        # (e.g. every ~4KB audio chunk, ~10x/sec) is audible as stutter.
        # This is only safe because EVERY direct spi.init() call in the
        # codebase now goes through set_freq() below instead of touching
        # self.spi directly — that was the actual desync bug (not caching
        # itself): a caller changing the real clock without telling this
        # cache. If you add a new direct spi.init() call anywhere, this
        # cache goes stale again — route it through set_freq() instead.
        if freq != self._current_freq:
            self.spi.init(baudrate=freq)
            self._current_freq = freq

    def set_freq(self, freq):
        """Public, cache-aware equivalent of spi.init(baudrate=freq) for
        callers that manage their own CS/locking (e.g. sdcard.py's block
        driver) and just need the shared bus at a given speed."""
        self._set_freq(freq)

    def invalidate(self):
        """Call after something OUTSIDE this module's control may have
        reconfigured the physical SPI0 clock without going through
        set_freq() — the one known case is SD mount, which constructs its
        own machine.SPI(config.SPI_ID, ...) instance and SDCard.init_spi()
        calls .init() on THAT object. Same physical peripheral, invisible
        to this cache. Forces the next set_freq() call to really reinit
        instead of trusting a cache that can no longer be trusted."""
        self._current_freq = None

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
