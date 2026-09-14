# drivers/assets.py — Button Blasters v3.0
# Asset manager — SD card now CONFIRMED WORKING via separate breakout.
#
# SD card status: WORKING (separate SPI breakout on shared SPI0 bus)
#   Built-in ILI9488 slot is unusable (SDO drives MISO/GP4 low).
#   Separate breakout: SD_CS=GP3, 10kΩ pull-up on MISO (hardware),
#   data transfers at config.SPI_FREQ_SD_DATA. Verified by test_sd_card.py.
#   All methods remain safe to call with no SD — they return None/False.
#
# Directory layout (when SD available):
#   /sd/images/shared/       — shared UI assets
#   /sd/images/<game_id>/    — per-game bitmaps
#   /sd/audio/sfx/           — sound effects
#   /sd/audio/voice/         — voice clips
#   /sd/audio/music/         — background music
#   /sd/adventure/stories/   — My Big Day Out JSON data
#
# Bitmap format: raw RGB565 little-endian, filename encodes size.
# e.g. cat_64x64.raw  →  64×64 pixels, 8192 bytes

import asyncio
import os
from machine import Pin
import config
from drivers.spi_bus import spi_bus

_SD_MOUNT = "/sd"
_IMG_ROOT = _SD_MOUNT + "/images"
_AUD_ROOT = _SD_MOUNT + "/audio"

# SD data-transfer rate. Tune it in config.py (see the bench notes there),
# never here.
_SD_DATA_BAUD = config.SPI_FREQ_SD_DATA

# Other CS pins on the shared SPI0 bus. Held HIGH before SD init so no
# display controller drives the bus during the SD handshake (bus
# contention otherwise causes init failure — same issue that made the
# ILI9488's built-in slot unusable).
_OTHER_CS_PINS = (
    config.PIN_CS_MAIN,
    config.PIN_CS_BTN[0], config.PIN_CS_BTN[1],
    config.PIN_CS_BTN[2], config.PIN_CS_BTN[3],
)


class AssetManager:

    def __init__(self):
        self._index       = {}
        self._cache       = {}
        self._cache_limit = 32_000
        self._sd_mounted  = False

    def mount_sd(self) -> bool:
        if config.SD_DEFERRED:
            print("[assets] SD deferred — separate breakout needed")
            return False
        try:
            from sdcard import SDCard
            from machine import SPI

            # Safety: ensure no other device on the shared SPI0 bus is
            # selected during SD init. Display drivers already idle CS
            # high, but we assert it explicitly to match the confirmed
            # test_sd_card.py sequence.
            for pin_num in _OTHER_CS_PINS:
                Pin(pin_num, Pin.OUT, value=1)

            cs     = Pin(config.PIN_CS_SD, Pin.OUT, value=1)
            sd_spi = SPI(config.SPI_ID,
                         baudrate=config.SPI_FREQ_SD_INIT,
                         sck=Pin(config.PIN_SCK),
                         mosi=Pin(config.PIN_MOSI),
                         miso=Pin(config.PIN_MISO))

            # baudrate here is the POST-init data rate (config-driven; the
            # driver's own 1.32MHz default EIO'd on the breadboard build).
            sd = SDCard(sd_spi, cs, baudrate=_SD_DATA_BAUD)
            os.mount(sd, _SD_MOUNT)

            self._sd_mounted = True
            print("[assets] SD mounted at %s @ %dkHz data"
                  % (_SD_MOUNT, _SD_DATA_BAUD // 1000))
            return True
        except Exception as e:
            print(f"[assets] SD mount failed: {e}")
            return False
        finally:
            # Restore the shared bus to display speed for the displays —
            # on EVERY exit, not just success. sd_spi above is a SEPARATE
            # machine.SPI(SPI_ID, ...) instance from spi_bus.spi — same
            # physical peripheral, but SDCard's own init_spi() call on it
            # changes the real clock to 400kHz without spi_bus's cache
            # knowing. invalidate() so set_freq() below doesn't wrongly
            # skip the reinit because the (stale) cache happens to already
            # say SPI_FREQ_DISPLAY.
            #
            # This has to be a finally, not a tail call after os.mount():
            # when the SD card isn't found, SDCard()/os.mount() raises and
            # a tail call is skipped entirely, leaving the bus stranded at
            # SD speed — every display draw after a failed mount ran at SD
            # speed instead of display speed (the slow-fail-screen symptom).
            #
            # SHARED-BUS RULE: SD and all five displays share SPI0 at
            # different speeds (SPI_FREQ_SD_DATA vs SPI_FREQ_DISPLAY), and
            # sdcard.py does NOT re-assert its speed per read. Every SD
            # access after a successful mount must therefore run inside a
            # bracketed window — spi_bus.raw(config.SPI_FREQ_SD_DATA) or an
            # explicit set_freq()/finally pair — as load_image(),
            # read_file(), game_cache, and the kernel's score I/O all do. A
            # bare open() on /sd runs at display speed and EIOs (or
            # collides with a display transaction).
            spi_bus.invalidate()
            spi_bus.set_freq(config.SPI_FREQ_DISPLAY)

    def build_index(self):
        if not self._sd_mounted:
            return
        self._index.clear()
        self._walk(_IMG_ROOT)
        print(f"[assets] indexed {len(self._index)} images")

    def _walk(self, path):
        try:
            for entry in os.listdir(path):
                full = path + "/" + entry
                try:
                    os.stat(full + "/."); self._walk(full)
                except OSError:
                    if entry.endswith(".raw"):
                        self._index[entry] = full
        except OSError:
            pass

    @staticmethod
    def image_size(filename: str):
        name = filename.rsplit(".", 1)[0]
        part = name.rsplit("_", 1)[-1]
        try:
            w, h = part.lower().split("x")
            return int(w), int(h)
        except Exception:
            return None, None

    def resolve(self, filename: str):
        if not self._sd_mounted:
            return None
        if filename in self._index:
            return self._index[filename]
        full = _IMG_ROOT + "/" + filename
        try:
            os.stat(full); return full
        except OSError:
            return None

    async def load_image(self, filename: str):
        if not self._sd_mounted:
            return None
        path = self.resolve(filename)
        if path is None:
            return None
        if path in self._cache:
            return self._cache[path]
        try:
            # Whole read under the bus lock at SD speed (SHARED-BUS RULE
            # above): holding the lock across the yields is what keeps a
            # display draw from resetting the clock mid-file.
            async with spi_bus.raw(_SD_DATA_BAUD):
                size = os.stat(path)[6]
                buf  = bytearray(size)
                with open(path, "rb") as f:
                    mv = memoryview(buf); offset = 0
                    while offset < size:
                        n = f.readinto(mv[offset:offset+2048])
                        if n == 0: break
                        offset += n
                        await asyncio.sleep_ms(0)
            if size <= self._cache_limit:
                self._cache[path] = buf
            return buf
        except OSError as e:
            print(f"[assets] load error {filename}: {e}")
            return None

    def load_image_sync(self, filename: str):
        if not self._sd_mounted:
            return None
        path = self.resolve(filename)
        if path is None:
            return None
        if path in self._cache:
            return self._cache[path]
        try:
            spi_bus.set_freq(_SD_DATA_BAUD)       # SHARED-BUS RULE (see mount_sd)
            try:
                size = os.stat(path)[6]
                buf  = bytearray(size)
                with open(path, "rb") as f:
                    f.readinto(buf)
            finally:
                spi_bus.set_freq(config.SPI_FREQ_DISPLAY)
            if size <= self._cache_limit:
                self._cache[path] = buf
            return buf
        except OSError:
            return None

    def read_file(self, path, into=None):
        # Speed-managed SD read. The shared SPI0 bus is left at display speed
        # after any draw; force SD speed for the read and restore display
        # speed in a finally so a fault can't strand the bus slow (the
        # 44s-fill symptom).
        #
        # SYNCHRONOUS with NO awaits inside the SD-speed window, so a display
        # draw can't sneak in mid-read and reset the clock. Call once per file;
        # let the caller await between files.
        #
        #   into given  -> reads into it, returns bytes read (int)
        #   into None   -> allocates a bytearray of file size, returns it
        if not self._sd_mounted:
            return None
        alloc = into is None
        try:
            spi_bus.set_freq(_SD_DATA_BAUD)
            if alloc:
                into = bytearray(os.stat(path)[6])
            mv   = memoryview(into)
            need = len(mv)
            off  = 0
            with open(path, "rb") as f:
                while off < need:
                    n = f.readinto(mv[off:])
                    if not n:
                        break
                    off += n
        finally:
            spi_bus.set_freq(config.SPI_FREQ_DISPLAY)
        return into if alloc else off

    def evict_cache(self, prefix: str = None):
        keys = list(self._cache.keys())
        for k in keys:
            if prefix:
                if prefix in k: del self._cache[k]
            else:
                if "shared" not in k: del self._cache[k]

    @staticmethod
    def sfx_path(fn):   return _AUD_ROOT + "/sfx/"   + fn
    @staticmethod
    def voice_path(fn): return _AUD_ROOT + "/voice/" + fn
    @staticmethod
    def music_path(fn): return _AUD_ROOT + "/music/" + fn

    def list_game_images(self, game_id: str) -> list:
        return [v for k, v in self._index.items()
                if game_id + "/" in v]

    @property
    def sd_available(self) -> bool:
        return self._sd_mounted


assets = AssetManager()
