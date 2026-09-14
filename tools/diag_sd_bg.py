# tools/diag_sd_bg.py — run ON THE PICO: mpremote run tools/diag_sd_bg.py
#
# Isolates why a .bz background streamed from the SD card fails to paint
# ("[display] main bg paint failed: ... EINVAL"). EINVAL is what
# deflate.DeflateIO raises when the compressed bytes it reads are invalid,
# so this checks, in order:
#   1. the file exists on the card and its size matches the repo's copy
#   2. sha256 of the whole file (compare with `shasum -a 256` on the desktop)
#   3. the header parses (kind/strip_h/w/h/chunk table)
#   4. strip 0 inflates from the chunk bytes held in RAM (DeflateIO over a
#      BytesIO) -- proves the DATA is good
#   5. strip 0 inflates straight from the FAT file object at SD bus speed,
#      exactly as core/game_cache.py's _SDBackground does -- proves the PATH
#   6. the real thing: game_cache.open_background() + read_strip(0)
# Whichever step fails first is the culprit; a full traceback is printed.

import sys
import io
import os
import gc
import struct
import hashlib
import deflate
import machine
import config

machine.freq(config.MACHINE_FREQ)

from drivers.spi_bus import spi_bus
from drivers.assets import assets
from drivers import flash_assets
from core import game_cache

PATH = "/assets/menu/bgm_menu-match_480x320.bz"      # littlefs path the menu asks for
SD_PATH = "/sd" + PATH

SD = config.SPI_FREQ_SD_DATA
DISP = config.SPI_FREQ_DISPLAY


def step(n, title):
    print("\n-- %d. %s" % (n, title))


def fail(e):
    sys.print_exception(e)
    print("   ^^^ FAILED HERE")


print("=" * 60)
print("SD background streaming diagnostic")
print("=" * 60)
if not assets.mount_sd():
    sys.exit("SD mount failed -- card inserted / formatted FAT32?")

# 1 -------------------------------------------------------------------
step(1, "file present on the card?")
try:
    on_flash = None
    try:
        on_flash = os.stat(PATH)[6]
    except OSError:
        pass
    print("   littlefs %s: %s" % (PATH, "MISSING (good, SD fallback will be used)"
                                  if on_flash is None else "%d bytes -- still on flash!" % on_flash))
    spi_bus.set_freq(SD)
    size = os.stat(SD_PATH)[6]
    spi_bus.set_freq(DISP)
    print("   %s: %d bytes (repo copy is 142014)" % (SD_PATH, size))
except Exception as e:
    spi_bus.set_freq(DISP)
    fail(e)
    sys.exit()

# 2 -------------------------------------------------------------------
step(2, "sha256 of the file read through FAT at SD speed")
try:
    h = hashlib.sha256()
    buf = bytearray(4096)
    mv = memoryview(buf)
    spi_bus.set_freq(SD)
    with open(SD_PATH, "rb") as f:
        while True:
            n = f.readinto(mv)
            if not n:
                break
            h.update(mv[:n])
    spi_bus.set_freq(DISP)
    print("   " + "".join("%02x" % b for b in h.digest()))
    print("   compare: shasum -a 256 assets/menu/bgm_menu-match_480x320.bz")
except Exception as e:
    spi_bus.set_freq(DISP)
    fail(e)

# 3 -------------------------------------------------------------------
step(3, "header parse")
try:
    spi_bus.set_freq(SD)
    with open(SD_PATH, "rb") as f:
        (kind, strip_h, w, h_, frames, flags,
         offsets, lengths, data_start) = flash_assets._read_header(f, SD_PATH)
    spi_bus.set_freq(DISP)
    print("   kind=%d strip_h=%d %dx%d frames=%d flags=%d chunks=%d data@%d"
          % (kind, strip_h, w, h_, frames, flags, len(offsets), data_start))
    print("   chunk0 off=%d len=%d   chunk1 off=%d len=%d"
          % (offsets[0], lengths[0], offsets[1], lengths[1]))
except Exception as e:
    spi_bus.set_freq(DISP)
    fail(e)
    sys.exit()

expect = w * strip_h * 2
gc.collect()
out = bytearray(expect)

# 4 -------------------------------------------------------------------
step(4, "strip 0: inflate from chunk bytes held in RAM (data check)")
try:
    spi_bus.set_freq(SD)
    with open(SD_PATH, "rb") as f:
        f.seek(data_start + offsets[0])
        chunk = f.read(lengths[0])
    spi_bus.set_freq(DISP)
    print("   read %d of %d chunk bytes; zlib hdr %02x %02x"
          % (len(chunk), lengths[0], chunk[0], chunk[1]))
    d = deflate.DeflateIO(io.BytesIO(chunk), deflate.ZLIB)
    got = 0
    mvo = memoryview(out)
    while got < expect:
        n = d.readinto(mvo[got:])
        if not n:
            break
        got += n
    print("   inflated %d of %d bytes -> %s" % (got, expect, "OK" if got == expect else "SHORT"))
except Exception as e:
    spi_bus.set_freq(DISP)
    fail(e)

# 5 -------------------------------------------------------------------
step(5, "strip 0: inflate straight from the FAT file at SD speed (path check)")
try:
    spi_bus.set_freq(SD)
    with open(SD_PATH, "rb") as f:
        f.seek(data_start + offsets[0])
        d = deflate.DeflateIO(f, deflate.ZLIB)
        got = 0
        mvo = memoryview(out)
        while got < expect:
            n = d.readinto(mvo[got:])
            if not n:
                break
            got += n
    spi_bus.set_freq(DISP)
    print("   inflated %d of %d bytes -> %s" % (got, expect, "OK" if got == expect else "SHORT"))
except Exception as e:
    spi_bus.set_freq(DISP)
    fail(e)

# 6 -------------------------------------------------------------------
step(6, "the real path: game_cache.open_background() + read_strip(0)")
try:
    bg = game_cache.open_background(PATH)
    print("   opened via %s  big_endian=%s  n_strips=%d"
          % (type(bg).__name__, bg.big_endian, bg.n_strips))
    rows = bg.read_strip(0, out)
    print("   read_strip(0) -> %d rows OK" % rows)
    rows = bg.read_strip(bg.n_strips - 1, out)
    print("   read_strip(last) -> %d rows OK" % rows)
    bg.close()
except Exception as e:
    spi_bus.set_freq(DISP)
    fail(e)

print("\ndone")
