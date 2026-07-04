# drivers/assets.py — Button Blasters v3.0
# Asset manager — SD card deferred, graceful fallback throughout.
#
# SD card status: DEFERRED
#   ILI9488 SDO permanently drives MISO (GP4) low.
#   Separate SPI breakout needed. GP3 reserved for SD_CS.
#   All methods are safe to call with no SD — they return None/False.
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
import config

_SD_MOUNT = "/sd"
_IMG_ROOT = _SD_MOUNT + "/images"
_AUD_ROOT = _SD_MOUNT + "/audio"


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
            from machine import SPI, Pin
            from drivers.spi_bus import spi_bus
            cs     = Pin(config.PIN_CS_SD, Pin.OUT, value=1)
            sd_spi = SPI(config.SPI_ID,
                         baudrate=config.SPI_FREQ_SD_INIT,
                         sck=Pin(config.PIN_SCK),
                         mosi=Pin(config.PIN_MOSI),
                         miso=Pin(config.PIN_MISO))
            sd = SDCard(sd_spi, cs)
            os.mount(sd, _SD_MOUNT)
            spi_bus.spi.init(baudrate=config.SPI_FREQ_DISPLAY)
            self._sd_mounted = True
            print("[assets] SD mounted at", _SD_MOUNT)
            return True
        except Exception as e:
            print(f"[assets] SD mount failed: {e}")
            return False

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
