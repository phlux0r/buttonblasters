# core/game_cache.py — Tier B per-game asset cache (install at load, evict at unload)
#
# Split:
#   /assets/static/<game_id>/   Tier A — baked once, never touched here
#                                (e.g. Match It!'s icon sprites — must stay resident)
#   /assets/<game_id>/          Tier B — installed from SD at load(), deleted at
#                                unload(). Whole-folder mirror, one file at a time.
#
# Per-file fallback: if a single file won't fit, it's left OFF littlefs and
# streamed straight from its SD mirror at read time (see open_background()).
# SD mirror path is always the littlefs path with "/sd" prepended:
#   littlefs  /assets/match/bgm_match_480x320.bz
#   SD        /sd/assets/match/bgm_match_480x320.bz

import os
import asyncio
from drivers.assets import assets
from drivers.spi_bus import spi_bus
from drivers import flash_assets
import config

_SAFETY_MARGIN = 8 * 1024   # leave headroom, don't run littlefs to the wire
_SD_DATA_BAUD  = config.SPI_FREQ_SD_DATA
_COPY_CHUNK = 4096   # one reusable buffer for the whole install() call

def _free_bytes():
    st = os.statvfs('/')
    return st[0] * st[3]        # f_bsize * f_bfree


def _is_dir(path):
    try:
        os.stat(path + "/.")    # same idiom drivers/assets.py._walk uses
        return True
    except OSError:
        return False


def _walk_sd(dirpath):
    """Yield (sd_path, size) for every file under an SD dir, recursively."""
    try:
        names = os.listdir(dirpath)
    except OSError:
        return
    for name in names:
        full = dirpath + "/" + name
        if _is_dir(full):
            for item in _walk_sd(full):
                yield item
        else:
            try:
                yield full, os.stat(full)[6]
            except OSError:
                continue


def _makedirs(path):
    parts = path.split("/")[1:-1]     # drop leading '' and filename
    cur = ""
    for p in parts:
        cur += "/" + p
        try:
            os.mkdir(cur)
        except OSError:
            pass                       # already exists — fine


def _rm_tree(path):
    if not _is_dir(path):
        try:
            os.remove(path)
        except OSError:
            pass
        return
    try:
        names = os.listdir(path)
    except OSError:
        return
    for name in names:
        _rm_tree(path + "/" + name)
    try:
        os.rmdir(path)
    except OSError:
        pass


# ── Install / evict ──────────────────────────────────────────────────

async def _copy_file_chunked(sd_path, cache_path, size, chunk):
    mv = memoryview(chunk)
    with open(sd_path, "rb") as fsrc, open(cache_path, "wb") as fdst:
        remaining = size
        while remaining > 0:
            async with spi_bus.raw(_SD_DATA_BAUD):
                n = fsrc.readinto(mv[:min(_COPY_CHUNK, remaining)])
            if not n:
                break
            fdst.write(mv[:n])          # littlefs = internal flash, no SPI0, no lock needed
            remaining -= n
            await asyncio.sleep_ms(0)   # let audio (or anything else) take a turn


async def install(game_id):
    if not assets.sd_available:
        return 0, 0
    sd_root = "/sd/assets/" + game_id
    installed = skipped = 0
    chunk = bytearray(_COPY_CHUNK)
    for sd_path, size in _walk_sd(sd_root):
        cache_path = "/assets" + sd_path[len("/sd/assets"):]
        if _free_bytes() - size < _SAFETY_MARGIN:
            # Which file, not just a count -- a skipped file falls back to
            # per-strip SD streaming at 400kHz every time it's shown
            # (see open_background()'s fallback path), which is dramatically
            # slower than a flash read. Without the path here, that shows up
            # as "one specific screen is slow" with no way to tell which
            # asset is actually the cause short of guessing from file sizes.
            print("[game_cache] %s: skipped (low space, %dB needed): %s"
                  % (game_id, size, cache_path))
            skipped += 1
            continue
        try:
            _makedirs(cache_path)
            await _copy_file_chunked(sd_path, cache_path, size, chunk)
            installed += 1
        except OSError as e:
            print("[game_cache] install failed:", cache_path, e)
            skipped += 1
    print("[game_cache] %s: installed=%d skipped=%d" % (game_id, installed, skipped))
    return installed, skipped


def evict(game_id):
    """Delete /assets/<game_id>/ from littlefs. Never touches
    /assets/static/<game_id>/ — that tier is permanent."""
    _rm_tree("/assets/" + game_id)


# ── Per-file streaming fallback ──────────────────────────────────────

class _SDBackground(flash_assets.Background):
    """Same as Background, but every strip read is bracketed at 400kHz
    (bus is otherwise left at display speed) — mirrors assets.read_file()'s
    speed-management exactly, just applied per-strip instead of whole-file."""

    def read_strip(self, i, buf):
        spi_bus.set_freq(_SD_DATA_BAUD)
        try:
            return super().read_strip(i, buf)
        finally:
            spi_bus.set_freq(config.SPI_FREQ_DISPLAY)


def open_background(path):
    """Open a Background at `path` (littlefs, Tier A or a successfully
    installed Tier B file). If it's not there — meaning install() skipped
    it for space — fall back to its SD mirror, speed-managed per strip.
    Raises the same errors as flash_assets.Background if missing from both."""
    try:
        return flash_assets.Background(path)
    except OSError:
        sd_path = "/sd" + path
        spi_bus.set_freq(_SD_DATA_BAUD)
        try:
            bg = _SDBackground(sd_path)     # header+table read, also bracketed
        finally:
            spi_bus.set_freq(config.SPI_FREQ_DISPLAY)
        return bg