"""
flash_assets.py — Button Blasters on-device asset loader (MicroPython v1.28, RP2350)

Loads .bz / .sz assets baked by bake_assets.py from littlefs (or SD).

Design rules honoured:
  * One sprite arena allocated ONCE at boot (after gc.collect()) — sprites are
    carved out of it with a bump allocator, reset at each game load(). No large
    allocation ever happens after boot, so heap fragmentation can't bite.
  * Backgrounds are never held whole in RAM — strips are decompressed on
    demand into a caller-supplied buffer (your StripBufferPool source buffer).
  * Per-strip DeflateIO window is ~1KB (assets baked with wbits=10).
  * Endianness split is enforced by the 'kind' byte:
      kind 0 = bg  RGB565 LITTLE-endian (main-screen strip/viper path)
      kind 1 = bg  RGB565 BIG-endian    (button-screen blit path)
      kind 2 = spr RGB565 LE, magenta 0xF81F colour key (main screen)
      kind 3 = spr RGB565 BE, magenta key reads as 0x1FF8 via ptr16 (buttons)

Boot-time setup (in main.py, BEFORE menus/audio/LED effects run):

    import flash_assets
    flash_assets.init()            # allocates the 96KB sprite arena

Per game load():

    flash_assets.arena.reset()
    bg  = flash_assets.Background('/assets/match/bg_farm_480x320.bz')
    cow = flash_assets.SpriteSheet('/assets/match/spr_cow_48x48x6.sz')
"""

import gc
import struct
import deflate

# ---------------------------------------------------------------- constants

MAGIC = b"BBA1"
HEADER_LEN = 16

KIND_BG_LE = 0
KIND_BG_BE = 1
KIND_SPR_LE = 2
KIND_SPR_BE = 3

FLAG_RAW = 0x01     # chunks are raw RGB565 (no zlib) -- fast strip loads

# Caps (must match bake_assets.py)
SPRITE_BUDGET = 96 * 1024
MAX_FRAME_DIM = 96
MAX_FRAMES = 8


class AssetError(Exception):
    pass


# ---------------------------------------------------------------- header

def _read_header(f, path):
    hdr = f.read(HEADER_LEN)
    if len(hdr) != HEADER_LEN or hdr[0:4] != MAGIC:
        raise AssetError("bad magic: " + path)
    kind, strip_h, w, h, frames, flags, n_chunks, _r1 = \
        struct.unpack("<BBHHBBHH", hdr[4:16])
    table = f.read(n_chunks * 8)
    if len(table) != n_chunks * 8:
        raise AssetError("truncated table: " + path)
    offsets = []
    lengths = []
    for i in range(n_chunks):
        off, ln = struct.unpack_from("<II", table, i * 8)
        offsets.append(off)
        lengths.append(ln)
    data_start = HEADER_LEN + n_chunks * 8
    return kind, strip_h, w, h, frames, flags, offsets, lengths, data_start


def _inflate_into(f, comp_len, dst_mv, expect, path):
    """Decompress one chunk (an independent zlib stream) into dst_mv."""
    d = deflate.DeflateIO(f, deflate.ZLIB)
    got = 0
    while got < expect:
        n = d.readinto(dst_mv[got:expect])
        if not n:
            raise AssetError("short chunk in " + path)
        got += n


# ---------------------------------------------------------------- backgrounds

class Background:
    """Random-access, strip-at-a-time background. Holds the file open."""

    def __init__(self, path):
        self.path = path
        self._f = open(path, "rb")
        try:
            (kind, strip_h, w, h, frames, flags,
             self._offsets, self._lengths, self._data) = \
                _read_header(self._f, path)
        except Exception:
            self._f.close()
            raise
        if kind not in (KIND_BG_LE, KIND_BG_BE) or frames != 1:
            self._f.close()
            raise AssetError("not a background: " + path)
        self.kind = kind
        self.raw = bool(flags & FLAG_RAW)
        self.big_endian = (kind == KIND_BG_BE)
        self.w = w
        self.h = h
        self.strip_h = strip_h
        self.n_strips = len(self._offsets)

    def strip_rows(self, i):
        """Row count of strip i (last strip may be partial)."""
        if i == self.n_strips - 1:
            r = self.h - i * self.strip_h
            return r if r else self.strip_h
        return self.strip_h

    def read_strip(self, i, buf):
        """Decompress strip i into buf (bytearray/memoryview, LE or BE
        per self.kind). Returns the number of rows written."""
        if not 0 <= i < self.n_strips:
            raise AssetError("strip index out of range")
        rows = self.strip_rows(i)
        expect = self.w * rows * 2
        if len(buf) < expect:
            raise AssetError("strip buffer too small")
        self._f.seek(self._data + self._offsets[i])
        if self.raw:
            # fast path: chunk IS the pixels -- one seek + readinto
            if self._lengths[i] != expect:
                raise AssetError("raw chunk length mismatch: " + self.path)
            mv = memoryview(buf)[:expect]
            got = 0
            while got < expect:
                n = self._f.readinto(mv[got:])
                if not n:
                    raise AssetError("short raw chunk in " + self.path)
                got += n
        else:
            _inflate_into(self._f, self._lengths[i],
                          memoryview(buf), expect, self.path)
        return rows

    def close(self):
        self._f.close()


# ---------------------------------------------------------------- sprite arena

class SpriteArena:
    """One boot-time allocation; bump-allocated sprite frame storage.
    Call reset() at every game load() before loading that game's sheets."""

    def __init__(self, size=SPRITE_BUDGET):
        gc.collect()
        self._buf = bytearray(size)
        self._mv = memoryview(self._buf)
        self.size = size
        self.used = 0

    def alloc(self, n):
        if self.used + n > self.size:
            raise AssetError(
                "sprite budget exceeded: need %d, %d free of %d"
                % (n, self.size - self.used, self.size))
        mv = self._mv[self.used:self.used + n]
        self.used += n
        return mv

    def reset(self):
        self.used = 0

    @property
    def free(self):
        return self.size - self.used


arena = None


def init(budget=SPRITE_BUDGET):
    """Call ONCE at boot, before the heap gets churned."""
    global arena
    if arena is None:
        arena = SpriteArena(budget)
    return arena


# ---------------------------------------------------------------- sprites

class SpriteSheet:
    """All frames decompressed into the arena at load(); file then closed.
    frame(i) returns a memoryview of raw RGB565 (endianness per kind)."""

    def __init__(self, path, use_arena=None):
        a = use_arena or arena
        if a is None:
            raise AssetError("flash_assets.init() not called")
        f = open(path, "rb")
        try:
            (kind, strip_h, w, h, frames, flags,
             offsets, lengths, data) = _read_header(f, path)
            if kind not in (KIND_SPR_LE, KIND_SPR_BE):
                raise AssetError("not a sprite: " + path)
            if w > MAX_FRAME_DIM or h > MAX_FRAME_DIM:
                raise AssetError("frame >%dpx in %s" % (MAX_FRAME_DIM, path))
            if frames > MAX_FRAMES or frames != len(offsets):
                raise AssetError("bad frame count in " + path)
            self.kind = kind
            self.big_endian = (kind == KIND_SPR_BE)
            self.w = w
            self.h = h
            self.n_frames = frames
            fb = w * h * 2
            self._frames = []
            raw = bool(flags & FLAG_RAW)
            for i in range(frames):
                mv = a.alloc(fb)
                f.seek(data + offsets[i])
                if raw:
                    if lengths[i] != fb:
                        raise AssetError("raw frame length mismatch: " + path)
                    got = 0
                    while got < fb:
                        n = f.readinto(mv[got:])
                        if not n:
                            raise AssetError("short raw frame in " + path)
                        got += n
                else:
                    _inflate_into(f, lengths[i], mv, fb, path)
                self._frames.append(mv)
        finally:
            f.close()

    def frame(self, i):
        return self._frames[i]
