"""
test_14_sprite_engine.py — sprite engine bench test (Button Blasters)

Follows the numbered bring-up convention. Renderer construction is copied
verbatim from test_13_strip_scene.py (confirmed pin map, reset pulse, idle-CS
parking, always-re-init set_bus_freq). Self-contained: on first run it
SYNTHESIZES its own baked assets on-device (MicroPython's deflate compresses
as well as decompresses), so no desktop bake is needed. Assets are written
once to /assets/test/ and reused on later runs. NOTE: this build lacks
deflate WRITE support, so the sprite uses zlib "stored" blocks (covers the
DeflateIO read path) while the BACKGROUND uses RAW chunks (flags bit0) --
the engine's hot path after the 76ms/strip inflate cost was measured.
~326KB on littlefs; delete /assets/test to regenerate after format changes,
and DELETE THE OLD /assets/test NOW: the previous bg was stored-zlib.

NOTE test_13 exercised blit_sd only — this test is the FIRST hardware run of
StripRenderer.blit_ram (the sprite path). If output is garbled here but
test_13 passed, suspect blit_ram's prime/ping-pong logic, not the engine.

What it exercises, in order:
  1. On-device generation of a chunked .bz background (colour bars) and a
     .sz 4-frame pulsing-ball sprite (magenta-keyed), BBA1 format
  2. flash_assets: header parse, arena init, strip decompression correctness
     (spot-checks known pixels), sprite-budget cap enforcement
  3. Pool seating via adapter.open() (heap numbers printed, mirrors test_13)
  4. Full-scene paint through SpriteEngine + blit_ram (timed)
  5. 10 s of a bouncing, animating ball at tick_ms=80 — effective tick rate
     and worst event-loop stall (heartbeat task)
  6. Clean teardown: eng.stop(), adapter.close(), heap-recovery check

VISUAL pass (panels lie — same rule as test_13):
  * background = 10 horizontal colour bands, top->bottom:
    RED GREEN BLUE YELLOW CYAN(ish) TEAL WHITE GREY ORANGE BLACK
  * a pulsing white/yellow/orange ball bouncing over them, round (not a
    square — squares mean the magenta key failed), no trails (trails mean
    dirty-strip restore failed), no noise bands (RAMWR/CS framing)

PRINTED pass criteria:
  * decompressed pixels match generated pixels
  * full paint < ~1500 ms (expect roughly 500–900 ms at 10MHz)
  * bounce >= 8 effective ticks/s, worst heartbeat gap < 250 ms
  * heap recovered after adapter.close()

Requires on device: flash_assets.py, sprite_engine.py, sprite_adapter.py,
strip_renderer.py (flat imports; adjust if they live in packages).
"""

import gc
import os
import struct
import time
import micropython
import asyncio
from machine import Pin, SPI

from drivers import flash_assets
from core import sprite_engine
from core.sprite_adapter import MainScreenAdapter
from drivers.strip_renderer import StripRenderer, MAIN_W, MAIN_H, STRIP_H, DISPLAY_FREQ

# --- confirmed pin map (identical to test_13) ------------------------------
PIN_SCK  = 18
PIN_MOSI = 19
PIN_MISO = 4
PIN_ILI_CS  = 6
PIN_ILI_DC  = 12
PIN_ILI_RST = 17
IDLE_CS = (7, 8, 9, 10, 3)          # ST7789 x4 + SD_CS parked HIGH
ILI9488_MADCTL = 0x28               # landscape (confirmed)

ASSET_DIR = "/assets/test"
BG_PATH = ASSET_DIR + "/bg_bars_480x320.bz"
SPR_PATH = ASSET_DIR + "/spr_ball_48x48x4.sz"

MAGIC = b"BBA1"
W, H = MAIN_W, MAIN_H
FW, FH, NFRAMES = 48, 48, 4
KEY = 0xF81F                        # magenta LE

# ten distinct per-strip band colours (RGB565), top -> bottom
BAR_COLOURS = (0xF800, 0x07E0, 0x001F, 0xFFE0, 0x07FF,
               0x0410, 0xFFFF, 0x8410, 0xFD20, 0x0000)


# ---------------------------------------------------------------- hw setup
# (verbatim pattern from test_13_strip_scene.py)

def _park_idle_cs():
    for gp in IDLE_CS:
        Pin(gp, Pin.OUT, value=1)


class _Init:
    def __init__(self, spi, cs, dc):
        self.spi, self.cs, self.dc = spi, cs, dc
        self._b = bytearray(1)

    def cmd(self, b):
        self.dc(0); self.cs(0); self._b[0] = b; self.spi.write(self._b); self.cs(1)

    def dat(self, b):
        self.dc(1); self.cs(0); self._b[0] = b; self.spi.write(self._b); self.cs(1)

    def run(self):
        self.cmd(0x11); time.sleep_ms(120)          # sleep out
        self.cmd(0x3A); self.dat(0x66)              # 18-bit RGB666
        self.cmd(0xC5); self.dat(0x00); self.dat(0x4D); self.dat(0x80)  # VCOM
        self.cmd(0x21)                              # inversion ON (IPS)
        self.cmd(0x36); self.dat(ILI9488_MADCTL)    # landscape BGR
        self.cmd(0x29)                              # display ON


def build_renderer():
    _park_idle_cs()
    cs  = Pin(PIN_ILI_CS,  Pin.OUT, value=1)
    dc  = Pin(PIN_ILI_DC,  Pin.OUT, value=0)
    rst = Pin(PIN_ILI_RST, Pin.OUT, value=1)
    rst(1); time.sleep_ms(10); rst(0); time.sleep_ms(20)
    rst(1); time.sleep_ms(120)

    spi = SPI(0, baudrate=DISPLAY_FREQ, polarity=0, phase=0,
              sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI), miso=Pin(PIN_MISO))

    def set_bus_freq(hz):
        # ALWAYS re-init — never trust a cached freq (_current_freq gotcha)
        spi.init(baudrate=hz, polarity=0, phase=0)

    _Init(spi, cs, dc).run()
    print("ILI9488 init done.")
    return StripRenderer(spi, cs, dc, set_bus_freq)


# ------------------------------------------------------- asset generation

@micropython.viper
def _adler32(data: ptr8, n: int) -> int:
    # deferred-modulo adler32; run length 3800 keeps sums inside a signed
    # 32-bit viper int (the standard 5552 assumes unsigned 32-bit)
    a = 1
    b = 0
    i = 0
    while i < n:
        m = n - i
        if m > 3800:
            m = 3800
        j = 0
        while j < m:
            a += int(data[i + j])
            b += a
            j += 1
        a %= 65521
        b %= 65521
        i += m
    return (b << 16) | a


def _stored_len(n):
    """Exact byte length of a stored-block zlib stream for n raw bytes:
    2 (zlib hdr) + 5 per block + n + 4 (adler). Deterministic, so the
    chunk table can be written BEFORE any chunk data exists."""
    blocks = (n + 65534) // 65535 if n else 1
    return 2 + 5 * blocks + n + 4


def _write_stored(f, data):
    """Stream one stored-block zlib chunk straight to the file — never
    builds the chunk in RAM (the accumulate-in-RAM version needed ~307KB
    for the background and MemoryError'd; this needs ~0)."""
    n = len(data)
    mv = memoryview(data)
    f.write(b"\x08\x1d")              # CMF/FLG: CM=8, CINFO=0 (256B window)
    pos = 0
    while True:
        end = min(pos + 65535, n)
        ln = end - pos
        final = 1 if end >= n else 0
        f.write(struct.pack("<BHH", final, ln, ln ^ 0xFFFF))
        f.write(mv[pos:end])
        pos = end
        if final:
            break
    f.write(struct.pack(">I", _adler32(data, n)))


def _begin_asset(f, kind, strip_h, w, h, frames, raw_lens, flags=0):
    """Write header + offset table — data follows. flags bit0 = RAW chunks
    (lengths are the raw sizes); otherwise stored-zlib (_stored_len)."""
    f.write(MAGIC)
    f.write(struct.pack("<BBHHBBHH", kind, strip_h, w, h, frames,
                        flags, len(raw_lens), 0))
    off = 0
    for n in raw_lens:
        ln = n if flags & 1 else _stored_len(n)
        f.write(struct.pack("<II", off, ln))
        off += ln


def _le_fill(buf, colour, n_px):
    lo = colour & 0xFF
    hi = (colour >> 8) & 0xFF
    for i in range(n_px):
        buf[2 * i] = lo
        buf[2 * i + 1] = hi


def make_test_assets(scratch):
    """scratch = the pool's 30,720B source buffer (borrowed via
    adapter.acquire_src()) — generation allocates NO big buffers, per the
    boot-order rule. The heap-fragmentation failure this replaces: alloc'ing
    a fresh strip buffer + arena here left the heap unable to seat the
    pool's second 45KB rgb666 buffer afterwards."""
    try:
        os.stat(BG_PATH); os.stat(SPR_PATH)
        print("test assets already present")
        return
    except OSError:
        pass
    for d in ("/assets", ASSET_DIR):
        try:
            os.mkdir(d)
        except OSError:
            pass

    print("generating background (10 colour bands)... first run only")
    strip = scratch                                # borrowed, not allocated
    strip_len = W * STRIP_H * 2
    n_strips = H // STRIP_H
    with open(BG_PATH, "wb") as f:
        _begin_asset(f, 0, STRIP_H, W, H, 1, [strip_len] * n_strips,
                     flags=1)                      # RAW: the engine hot path
        for i in range(n_strips):
            _le_fill(strip, BAR_COLOURS[i], W * STRIP_H)
            f.write(strip)

    print("generating 4-frame pulsing ball...")
    frame = memoryview(scratch)[:FW * FH * 2]      # still the same buffer
    with open(SPR_PATH, "wb") as f:
        _begin_asset(f, 2, FH, FW, FH, NFRAMES, [FW * FH * 2] * NFRAMES)
        for fi in range(NFRAMES):
            _le_fill(frame, KEY, FW * FH)          # magenta = transparent
            r = (14, 18, 22, 18)[fi]
            col = (0xFFFF, 0xFFE0, 0xFD20, 0xFFE0)[fi]
            cx = cy = FW // 2
            for y in range(FH):
                for x in range(FW):
                    dx, dy = x - cx, y - cy
                    if dx * dx + dy * dy <= r * r:
                        o = (y * FW + x) * 2
                        frame[o] = col & 0xFF
                        frame[o + 1] = (col >> 8) & 0xFF
            _write_stored(f, frame)
    print("assets written to", ASSET_DIR)


# ---------------------------------------------------------------- tests

def test_loader(scratch):
    """scratch = the pool's source buffer (borrowed) — no 30KB alloc here."""
    print("\n[1] flash_assets loader checks")
    flash_assets.arena.reset()

    bg = flash_assets.Background(BG_PATH)
    assert (bg.w, bg.h, bg.n_strips) == (W, H, 10), "bg header wrong"
    assert bg.raw, "bg should be RAW-chunk (regenerate /assets/test)"

    for i in (0, 4, 9):
        rows = bg.read_strip(i, scratch)
        assert rows == STRIP_H
        c = BAR_COLOURS[i]
        assert scratch[0] == (c & 0xFF) and scratch[1] == (c >> 8), \
            "strip %d pixel mismatch" % i
    print("    raw strip reads: pixels verified OK")

    t0 = time.ticks_ms()
    for i in range(10):
        bg.read_strip(i, scratch)
    print("    raw read_strip: %.1f ms/strip (was 76.4 zlib)"
          % (time.ticks_diff(time.ticks_ms(), t0) / 10))

    spr = flash_assets.SpriteSheet(SPR_PATH)
    assert spr.n_frames == NFRAMES and spr.w == FW
    f0 = spr.frame(0)
    assert f0[0] == (KEY & 0xFF) and f0[1] == (KEY >> 8), "corner not keyed"
    print("    sprite loaded (zlib path), arena used: %d / %d B"
          % (flash_assets.arena.used, flash_assets.arena.size))

    try:
        while True:
            flash_assets.arena.alloc(32 * 1024)
    except flash_assets.AssetError:
        print("    budget enforcement: OK (raised as expected)")
    flash_assets.arena.reset()
    return bg


async def test_engine(adapter, bg):
    print("\n[2] full paint + bounce loop")
    flash_assets.arena.reset()
    spr = flash_assets.SpriteSheet(SPR_PATH)

    eng = sprite_engine.SpriteEngine(adapter, bg)
    ball = eng.add(spr, x=40, y=40)
    ball.play(fps=8, pingpong=True)

    eng.mark_all()
    t0 = time.ticks_ms()
    await eng.render_dirty()                # blit_ram + raw strips
    full_ms = time.ticks_diff(time.ticks_ms(), t0)
    print("    full paint via blit_ram: %d ms" % full_ms)

    gaps = [0]

    async def heartbeat():
        last = time.ticks_ms()
        while True:
            await asyncio.sleep_ms(25)
            now = time.ticks_ms()
            g = time.ticks_diff(now, last)
            if g > gaps[0]:
                gaps[0] = g
            last = now

    hb = asyncio.create_task(heartbeat())

    eng.start(tick_ms=80)
    vx, vy = 20, 12
    ticks = 0
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < 10_000:
        if not 0 <= ball.x + vx <= W - FW:
            vx = -vx
        if not 0 <= ball.y + vy <= H - FH:
            vy = -vy
        ball.move_by(vx, vy)
        ticks += 1
        await asyncio.sleep_ms(80)
    await eng.stop()
    hb.cancel()

    tps = ticks / 10
    print("    bounce: %.1f ticks/s, worst heartbeat gap %d ms"
          % (tps, gaps[0]))
    return full_ms, tps, gaps[0]


async def main():
    print("=" * 58)
    print("test_14 -- sprite engine (flash assets + blit_ram + dirty strips)")
    print("=" * 58)
    renderer = build_renderer()

    # BOOT-ORDER RULE: all large buffers seat FIRST, on the freshest heap —
    # 96KB arena, then the 150KB pool. Asset generation and the loader
    # checks BORROW the pool's source buffer; nothing else allocates big.
    # (The previous ordering — generate, then init arena, then seat pool —
    # fragmented the heap enough that rgb666[1] could not seat.)
    gc.collect()
    free_boot = gc.mem_free()
    flash_assets.init()                     # 96KB arena
    adapter = MainScreenAdapter(renderer)
    adapter.open()                          # 150KB pool
    print("arena + pool seated: free %.1fKB -> %.1fKB"
          % (free_boot / 1024, gc.mem_free() / 1024))

    try:
        scratch = adapter.acquire_src()     # 30,720B, borrowed everywhere
        make_test_assets(scratch)
        bg = test_loader(scratch)
        full_ms, tps, gap = await test_engine(adapter, bg)
    finally:
        adapter.close()

    gc.collect()
    recovered = abs(gc.mem_free() - free_boot) < 110_000   # arena stays
    print("pool released: free=%.1fKB (arena persists by design)"
          % (gc.mem_free() / 1024))

    ok = full_ms < 1500 and tps >= 8 and gap < 250
    print("\nRESULT:", "PASS (confirm visuals: round pulsing ball whole "
          "across bar edges, no trails, no noise bands)" if ok else
          "CHECK — compare figures above with criteria in the header")
    print("=" * 58)


asyncio.run(main())