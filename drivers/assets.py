# drivers/assets.py — Button Blasters v3.0
# Asset manager — SD card now CONFIRMED WORKING via separate breakout.
#
# SD card status: WORKING (separate SPI breakout on shared SPI0 bus)
#   Built-in ILI9488 slot is unusable (SDO drives MISO/GP4 low).
#   Separate breakout: SD_CS=GP3, 10kΩ pull-up on MISO (hardware),
#   data transfers at 400kHz. Verified by test_sd_card.py.
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

_SD_MOUNT = "/sd"
_IMG_ROOT = _SD_MOUNT + "/images"
_AUD_ROOT = _SD_MOUNT + "/audio"

# Confirmed-working SD data-transfer rate. NOTE: this deliberately does
# NOT use config.SPI_FREQ_SD_DATA (10MHz) — that value is aspirational
# for a future soldered board. On the current breadboard build, 1.32MHz
# (the sdcard.py default) and 10MHz both throw EIO on readblocks; 400kHz
# is the rate test_sd_card.py actually passed at. Revisit once off
# breadboard.
_SD_DATA_BAUD = 400_000

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
        self._icon_block  = None      # shared contiguous image-load block
        self._icon_stride = 0

    def mount_sd(self) -> bool:
        if config.SD_DEFERRED:
            print("[assets] SD deferred — separate breakout needed")
            return False
        from drivers.spi_bus import spi_bus
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

            # baudrate here is the POST-init data rate. Must be 400kHz on
            # this breadboard (see _SD_DATA_BAUD note above) — the driver
            # default of 1.32MHz fails with EIO on block reads.
            sd = SDCard(sd_spi, cs, baudrate=_SD_DATA_BAUD)
            os.mount(sd, _SD_MOUNT)

            self._sd_mounted = True
            print("[assets] SD mounted at", _SD_MOUNT, "@ 400kHz data")
            return True
        except Exception as e:
            print(f"[assets] SD mount failed: {e}")
            return False
        finally:
            # sd_spi and spi_bus.spi are two Python objects over the same
            # underlying SPI0 peripheral (same config.SPI_ID) — this runs
            # on every exit, success or failure, so a failed mount can
            # never strand the bus at SD speed (the slow-fail-screen /
            # 44s-fill symptom). Goes through _set_freq so the bus's own
            # cache stays correct too, not just the hardware register.
            #
            # SHARED-BUS HAZARD (known, not yet handled): SD and all five
            # displays share SPI0 at different speeds (SD=400kHz,
            # displays=10MHz). sdcard.py sets its speed once at init and
            # does NOT re-assert it per read, so if a display transaction
            # reconfigures the bus to 10MHz between two SD reads, the next
            # SD read can fail with EIO. Harmless today (no game interleaves
            # SD reads with display draws — Shape Match is solid-colour),
            # but must be solved before any game streams SD assets mid-draw
            # (e.g. My Big Day Out). Fix will be per-transaction speed
            # re-assertion around SD reads.
            spi_bus._set_freq(config.SPI_FREQ_DISPLAY)

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

    # ── Shared icon-load pool ────────────────────────────────────
    # One contiguous block, allocated ONCE at boot (freshest heap). Icon games
    # borrow memoryview slices instead of each allocating six buffers at
    # game-load, where the heap is fragmented and six separate 28.8KB requests
    # intermittently fail to place. Sized for the worst icon game: 6x120x120.
    def alloc_icon_pool(self, slots=6, w=120, h=120):
        if self._icon_block is not None:
            return
        import gc
        gc.collect()
        self._icon_stride = w * h * 2
        self._icon_block  = bytearray(self._icon_stride * slots)
        gc.collect()
        print("[assets] icon pool: %d slots x %d B = %d B"
              % (slots, self._icon_stride, len(self._icon_block)))

    def borrow_icons(self, count, w, h):
        # `count` memoryview slices of w*h*2 into the shared block. Only one
        # game runs at a time, so sequential borrows are safe. Hard-fails.
        need = w * h * 2
        if self._icon_block is None:
            self.alloc_icon_pool(count, w, h)     # lazy fallback (less fresh)
        slots = len(self._icon_block) // need
        if count > slots:
            raise MemoryError("icon pool too small: need %d x %dB, holds %d"
                              % (count, need, slots))
        blk = memoryview(self._icon_block)
        return [blk[i * need:(i + 1) * need] for i in range(count)]

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
            size = os.stat(path)[6]
            buf  = bytearray(size)
            with open(path, "rb") as f:
                f.readinto(buf)
            if size <= self._cache_limit:
                self._cache[path] = buf
            return buf
        except OSError:
            return None

    def read_file(self, path, into=None):
        # Speed-managed SD read. The shared SPI0 bus is left at display speed
        # (10MHz) after any draw, but SD reads above ~1.32MHz EIO on this
        # breadboard. Force 400kHz for the read, restore display speed in a
        # finally so a fault can't strand the bus slow (the 44s-fill symptom).
        #
        # SYNCHRONOUS with NO awaits inside the 400kHz window, so a display
        # draw can't sneak in mid-read and reset the clock. Call once per file;
        # let the caller await between files.
        #
        #   into given  -> reads into it, returns bytes read (int)
        #   into None   -> allocates a bytearray of file size, returns it
        if not self._sd_mounted:
            return None
        from drivers.spi_bus import spi_bus
        alloc = into is None
        try:
            spi_bus.spi.init(baudrate=_SD_DATA_BAUD)             # 400kHz for SD
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
            spi_bus.spi.init(baudrate=config.SPI_FREQ_DISPLAY)   # restore 10MHz
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
