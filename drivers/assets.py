# drivers/assets.py
# Asset manager — indexes and loads bitmaps and audio from the SD card.
#
# SD card directory layout expected:
#   /sd/
#     images/
#       shared/          ← used by multiple games (icons, UI chrome)
#       <game_id>/       ← per-game bitmaps, e.g. /sd/images/match/
#     audio/
#       sfx/             ← short sound effects  (ding.wav, wrong.wav …)
#       voice/           ← voice clips          (correct.wav, great_job.wav …)
#       music/           ← background loops     (menu.wav, game1.wav …)
#
# Bitmap file format: raw RGB565, little-endian, no header.
# Filename encodes geometry: cat_64x64.raw, shape_240x280.raw
# (Width × height extracted from filename automatically.)
#
# Usage:
#   buf = await assets.load_image("match/cat_64x64.raw")
#   w, h = assets.image_size("cat_64x64.raw")

import asyncio
import os
import config
from drivers.spi_bus import spi_bus
from machine import Pin, SPI


_SD_MOUNT = "/sd"
_IMG_ROOT = _SD_MOUNT + "/images"
_AUD_ROOT = _SD_MOUNT + "/audio"


class AssetManager:

    def __init__(self):
        self._index = {}      # filename → full path
        self._cache = {}      # path → bytearray  (small items only)
        self._cache_limit = 32_000   # bytes — don't cache anything larger

    # ── SD card mount ────────────────────────────────────────────

    def mount_sd(self):
        """Mount the SD card over SPI.  Call once at boot (blocking)."""
        import uos
        try:
            from sdcard import SDCard   # MicroPython SDCard driver
            cs = Pin(config.PIN_CS_SD, Pin.OUT, value=1)
            # Temporarily re-init SPI at SD init speed
            sd_spi = SPI(
                config.SPI_ID,
                baudrate=config.SPI_FREQ_SD_INIT,
                sck=Pin(config.PIN_SCK),
                mosi=Pin(config.PIN_MOSI),
                miso=Pin(config.PIN_MISO),
            )
            sd = SDCard(sd_spi, cs)
            uos.mount(sd, _SD_MOUNT)
            # Bump SPI back to display speed
            spi_bus.spi.init(baudrate=config.SPI_FREQ_DISPLAY)
            print("[assets] SD card mounted at", _SD_MOUNT)
            return True
        except Exception as e:
            print("[assets] SD mount failed:", e)
            return False

    def build_index(self):
        """Walk the SD image tree and record all .raw paths."""
        self._index.clear()
        self._walk(_IMG_ROOT)
        print(f"[assets] indexed {len(self._index)} images")

    def _walk(self, path):
        try:
            for entry in os.listdir(path):
                full = path + "/" + entry
                try:
                    os.stat(full + "/.")   # is it a directory?
                    self._walk(full)
                except OSError:
                    if entry.endswith(".raw"):
                        self._index[entry] = full
        except OSError:
            pass

    # ── Image loading ────────────────────────────────────────────

    @staticmethod
    def image_size(filename: str):
        """Parse WxH from filename like 'cat_64x64.raw' → (64, 64)."""
        name = filename.rsplit(".", 1)[0]   # strip .raw
        part = name.rsplit("_", 1)[-1]      # last segment after _
        try:
            w, h = part.lower().split("x")
            return int(w), int(h)
        except Exception:
            return None, None

    def resolve(self, filename: str) -> str:
        """Return full SD path for a filename, or None if not found."""
        if filename in self._index:
            return self._index[filename]
        # Try treating filename as a relative path directly
        full = _IMG_ROOT + "/" + filename
        try:
            os.stat(full)
            return full
        except OSError:
            return None

    async def load_image(self, filename: str) -> bytearray | None:
        """
        Load a raw RGB565 bitmap into a bytearray.
        Returns None if the file is not found.
        Caches small images in RAM for fast re-use.
        """
        path = self.resolve(filename)
        if path is None:
            print(f"[assets] not found: {filename}")
            return None

        if path in self._cache:
            return self._cache[path]

        try:
            size = os.stat(path)[6]   # file size in bytes
            buf = bytearray(size)
            # Read in chunks to yield to other tasks
            with open(path, "rb") as f:
                mv = memoryview(buf)
                offset = 0
                chunk = 2048
                while offset < size:
                    n = f.readinto(mv[offset:offset+chunk])
                    if n == 0:
                        break
                    offset += n
                    await asyncio.sleep_ms(0)   # yield

            if size <= self._cache_limit:
                self._cache[path] = buf

            return buf
        except OSError as e:
            print(f"[assets] load error {filename}: {e}")
            return None

    def load_image_sync(self, filename: str) -> bytearray | None:
        """Blocking load — use only in init sequences, not during gameplay."""
        path = self.resolve(filename)
        if path is None:
            return None
        if path in self._cache:
            return self._cache[path]
        try:
            size = os.stat(path)[6]
            buf = bytearray(size)
            with open(path, "rb") as f:
                f.readinto(buf)
            if size <= self._cache_limit:
                self._cache[path] = buf
            return buf
        except OSError:
            return None

    def evict_cache(self, prefix: str = None):
        """
        Free cached images.
        prefix: evict only paths starting with this string (e.g. a game id).
        No prefix: evict everything except 'shared/'.
        """
        keys = list(self._cache.keys())
        for k in keys:
            if prefix:
                if prefix in k:
                    del self._cache[k]
            else:
                if "shared" not in k:
                    del self._cache[k]

    # ── Audio path helpers ───────────────────────────────────────

    @staticmethod
    def sfx_path(filename: str) -> str:
        return "sfx/" + filename

    @staticmethod
    def voice_path(filename: str) -> str:
        return "voice/" + filename

    @staticmethod
    def music_path(filename: str) -> str:
        return "music/" + filename

    # ── Listing helpers (for game builders) ─────────────────────

    def list_game_images(self, game_id: str) -> list:
        """Return all indexed filenames belonging to a game folder."""
        prefix = game_id + "/"
        return [v for k, v in self._index.items() if prefix in v]


assets = AssetManager()
