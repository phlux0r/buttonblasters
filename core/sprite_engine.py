"""
sprite_engine.py — Button Blasters sprite/animation engine
(MicroPython v1.28, RP2350)

Composes flash-streamed backgrounds + RAM sprites per 32-row strip, tracks
dirty strips, and re-renders only what changed. All heavy pixel work is
@micropython.viper; the tick loop is an asyncio task with an exception guard
(fire-and-forget tasks otherwise swallow errors silently).

Caps enforced/assumed:
  * <= 8 sprites per scene (MAX_ACTIVE)
  * velocity clamped to <= 32 px per tick per axis (one strip height)
  * sprite frames come from flash_assets.SpriteSheet (<=96x96, <=8 frames,
    96KB arena budget — enforced there)

Colour key: magenta. In LE assets a native ptr16 read sees 0xF81F; in BE
assets (button screens) the byte-swapped read sees 0x1FF8. The engine picks
the right key from the sheet's endianness automatically.

------------------------------------------------------------------------
INTEGRATION SEAM — strip_renderer adapter
------------------------------------------------------------------------
The engine doesn't touch SPI. It needs an adapter with two methods, which
you wire to your existing strip_renderer.py:

    class MainScreenAdapter:
        def acquire_src(self):
            # return (or borrow from StripBufferPool) a bytearray/memoryview
            # of at least 480*32*2 bytes for LE RGB565 source pixels
        def push_strip(self, y, rows, src_le):
            # your existing path: viper RGB565LE -> RGB666 band conversion
            # + RAMWR window (y .. y+rows) + transmit. May be a coroutine
            # or a plain function — the engine awaits it if awaitable.

For button screens, ButtonSprite needs one callable:

    def blit_be(btn_id, x, y, w, h, buf_be):  # your blit_btn_buf/blit_rgb565

------------------------------------------------------------------------
Typical game usage
------------------------------------------------------------------------
    import flash_assets, sprite_engine

    # at game load() (arena.reset() first, per flash_assets docs)
    bg  = flash_assets.Background('/assets/match/bg_farm_480x320.bz')
    cow = flash_assets.SpriteSheet('/assets/match/spr_cow_48x48x6.sz')

    eng = sprite_engine.SpriteEngine(adapter, bg)
    c = eng.add(cow, x=100, y=80)
    c.play(fps=10, pingpong=True)
    eng.mark_all()                       # first full paint
    eng.start(tick_ms=80)                # ~12 ticks/s

    ...
    c.move_to(140, 80)                   # engine dirties old+new strips

    await eng.stop()                     # at game unload
"""

import micropython
import uasyncio as asyncio
from drivers.strip_renderer import STRIP_H   # single source of truth

MAX_ACTIVE = 8
MAX_STEP = 32          # px per tick per axis
KEY_LE = 0xF81F        # magenta, native u16 read of LE data
KEY_BE = 0x1FF8        # magenta, native u16 read of BE data


# ---------------------------------------------------------------- viper blit

@micropython.viper
def _blit_key(dst: ptr16, dst_w: int, dx: int, dy: int,
              src: ptr16, src_w: int, sx: int, sy: int,
              cw: int, ch: int, key: int):
    """Copy a cw x ch region of src (offset sx,sy) into dst at (dx,dy),
    skipping pixels equal to key. All coords pre-clipped by caller.
    Works for LE and BE data alike (key differs)."""
    for row in range(ch):
        so = (sy + row) * src_w + sx
        do = (dy + row) * dst_w + dx
        for col in range(cw):
            p = int(src[so + col])
            if p != key:
                dst[do + col] = p


# ---------------------------------------------------------------- sprite

class Sprite:
    def __init__(self, sheet, x, y):
        self.sheet = sheet
        self.x = x
        self.y = y
        self.w = sheet.w
        self.h = sheet.h
        self.frame = 0
        self.visible = True
        # animation state
        self._playing = False
        self._ms_per_frame = 100
        self._pingpong = False
        self._dir = 1
        self._acc = 0
        # dirty bookkeeping (previous drawn bbox)
        self._px = x
        self._py = y
        self._dirty = True

    def play(self, fps=10, pingpong=False):
        self._ms_per_frame = max(1, 1000 // fps)
        self._pingpong = pingpong
        self._playing = True

    def stop(self):
        self._playing = False

    def set_frame(self, i):
        i %= self.sheet.n_frames
        if i != self.frame:
            self.frame = i
            self._dirty = True

    def move_to(self, x, y):
        # clamp to <= one strip height per tick so a mover dirties
        # at most ~4 strips (old + new bbox)
        dx = x - self.x
        dy = y - self.y
        if dx > MAX_STEP:
            dx = MAX_STEP
        elif dx < -MAX_STEP:
            dx = -MAX_STEP
        if dy > MAX_STEP:
            dy = MAX_STEP
        elif dy < -MAX_STEP:
            dy = -MAX_STEP
        nx = self.x + dx
        ny = self.y + dy
        if nx != self.x or ny != self.y:
            self.x = nx
            self.y = ny
            self._dirty = True

    def move_by(self, dx, dy):
        self.move_to(self.x + dx, self.y + dy)

    def show(self, visible=True):
        if visible != self.visible:
            self.visible = visible
            self._dirty = True

    def _advance(self, dt_ms):
        """Advance animation clock; returns True if the frame changed."""
        if not self._playing or self.sheet.n_frames < 2:
            return False
        self._acc += dt_ms
        changed = False
        while self._acc >= self._ms_per_frame:
            self._acc -= self._ms_per_frame
            n = self.sheet.n_frames
            if self._pingpong:
                f = self.frame + self._dir
                if f >= n:
                    self._dir = -1
                    f = n - 2
                elif f < 0:
                    self._dir = 1
                    f = 1
                self.frame = f
            else:
                self.frame = (self.frame + 1) % n
            changed = True
        return changed


# ---------------------------------------------------------------- engine

class SpriteEngine:
    """Main-screen engine: LE background + LE sprites, strip compositing."""

    def __init__(self, adapter, background=None, screen_w=480, screen_h=320):
        self.adapter = adapter
        self.w = screen_w
        self.h = screen_h
        self.n_strips = (screen_h + STRIP_H - 1) // STRIP_H
        self.sprites = []
        self._dirty = 0                # bitmask of strips
        self._task = None
        self._running = False
        self.bg = None
        if background is not None:
            self.set_background(background)

    # -------------------------------------------------- scene setup

    def set_background(self, bg):
        if bg.big_endian:
            raise ValueError("main-screen background must be LE (kind 0)")
        if bg.w != self.w or bg.h != self.h:
            raise ValueError("background size mismatch")
        if bg.strip_h != STRIP_H:
            raise ValueError("background strip_h != %d" % STRIP_H)
        self.bg = bg
        self.mark_all()

    def add(self, sheet, x=0, y=0):
        if len(self.sprites) >= MAX_ACTIVE:
            raise ValueError("max %d sprites per scene" % MAX_ACTIVE)
        if sheet.big_endian:
            raise ValueError("main-screen sprites must be LE (kind 2)")
        s = Sprite(sheet, x, y)
        self.sprites.append(s)
        self._mark_rect(s.x, s.y, s.w, s.h)
        return s

    def remove(self, sprite):
        if sprite in self.sprites:
            self._mark_rect(sprite.x, sprite.y, sprite.w, sprite.h)
            self.sprites.remove(sprite)

    # -------------------------------------------------- dirty tracking

    def mark_all(self):
        self._dirty = (1 << self.n_strips) - 1

    def _mark_rect(self, x, y, w, h):
        if w <= 0 or h <= 0:
            return
        y0 = max(0, y) // STRIP_H
        y1 = min(self.h - 1, y + h - 1) // STRIP_H
        if y0 > y1:
            return
        for i in range(y0, y1 + 1):
            self._dirty |= (1 << i)

    def _collect_dirty(self, dt_ms):
        for s in self.sprites:
            if s._advance(dt_ms):
                s._dirty = True
            if s._dirty:
                self._mark_rect(s._px, s._py, s.w, s.h)   # old position
                self._mark_rect(s.x, s.y, s.w, s.h)       # new position
                s._px = s.x
                s._py = s.y
                s._dirty = False

    # -------------------------------------------------- rendering

    async def render_dirty(self):
        """Recompose + transmit every dirty strip. Awaits between strips
        so audio/buttons stay live.

        Sprite state is SNAPSHOTTED at the start of the pass: the awaits
        let game tasks move sprites mid-render, and compositing strip N
        from an older position than strip N+1 cuts sprites at strip
        boundaries (bench-observed). Every strip in one pass composites
        from the same snapshot; a mid-render move dirties strips for the
        NEXT pass via _px/_py, which hold the snapshot position."""
        if self.bg is None or not self._dirty:
            return
        dirty = self._dirty
        self._dirty = 0
        snap = []
        for s in self.sprites:
            if s.visible:
                snap.append((s, s.x, s.y, s.frame))
        src = self.adapter.acquire_src()
        for i in range(self.n_strips):
            if not (dirty >> i) & 1:
                continue
            rows = self.bg.read_strip(i, src)      # background band
            sy0 = i * STRIP_H
            for (s, sx, sy, fr) in snap:
                self._blit_into_strip(src, s, sx, sy, fr, sy0, rows)
            r = self.adapter.push_strip(sy0, rows, src)
            if hasattr(r, "__await__") or hasattr(r, "send"):
                await r                             # coroutine adapter
            await asyncio.sleep_ms(0)               # yield between strips

    def _blit_into_strip(self, src_buf, s, sx, sy, fr, strip_y, strip_rows):
        # intersect snapshot bbox with this strip and the screen
        x0 = max(sx, 0)
        x1 = min(sx + s.w, self.w)
        y0 = max(sy, strip_y)
        y1 = min(sy + s.h, strip_y + strip_rows)
        if x0 >= x1 or y0 >= y1:
            return
        _blit_key(src_buf, self.w,
                  x0, y0 - strip_y,
                  s.sheet.frame(fr), s.w,
                  x0 - sx, y0 - sy,
                  x1 - x0, y1 - y0,
                  KEY_LE)

    # -------------------------------------------------- tick loop

    def start(self, tick_ms=80):
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._guarded_loop(tick_ms))

    async def stop(self):
        self._running = False
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _guarded_loop(self, tick_ms):
        # fire-and-forget tasks swallow exceptions — guard and report
        try:
            while self._running:
                self._collect_dirty(tick_ms)
                await self.render_dirty()
                await asyncio.sleep_ms(tick_ms)
        except Exception as e:
            import sys
            print("sprite_engine tick loop died:")
            sys.print_exception(e)
        finally:
            self._task = None


# ---------------------------------------------------------------- buttons

class ButtonSprite:
    """One animated sprite over a BE background on one ST7789 button screen.

    blit_be(btn_id, x, y, w, h, buf) must push a BE RGB565 rect to the
    screen (wrap your existing blit_btn_buf / blit_rgb565 path).
    scratch must be a caller-owned bytearray >= bg.w * STRIP_H * 2 bytes
    (borrow a StripBufferPool buffer or allocate once at load())."""

    def __init__(self, btn_id, background, sheet, blit_be, scratch):
        if not background.big_endian or not sheet.big_endian:
            raise ValueError("button assets must be BE (kinds 1/3)")
        if sheet.w > 64 or sheet.h > 64:
            raise ValueError("button sprites capped at 64x64")
        if sheet.n_frames > 4:
            raise ValueError("button sprites capped at 4 frames")
        if len(scratch) < background.w * STRIP_H * 2:
            raise ValueError("scratch buffer too small")
        self.btn = btn_id
        self.bg = background
        self.sprite = Sprite(sheet, 0, 0)
        self._blit = blit_be
        self._scratch = scratch

    def full_paint(self):
        """Paint the whole background + sprite (call once at load)."""
        for i in range(self.bg.n_strips):
            self._paint_strip(i)

    def tick(self, dt_ms):
        """Call from your game loop / a slow asyncio task. Repaints only
        the strips the sprite touches, and only when something changed."""
        s = self.sprite
        changed = s._advance(dt_ms) or s._dirty
        if not changed:
            return
        strips = set()
        for (x, y) in ((s._px, s._py), (s.x, s.y)):
            y0 = max(0, y) // STRIP_H
            y1 = min(self.bg.h - 1, y + s.h - 1) // STRIP_H
            for i in range(y0, y1 + 1):
                strips.add(i)
        s._px, s._py = s.x, s.y
        s._dirty = False
        for i in sorted(strips):
            self._paint_strip(i)

    def _paint_strip(self, i):
        rows = self.bg.read_strip(i, self._scratch)
        sy0 = i * STRIP_H
        s = self.sprite
        if s.visible:
            x0 = max(s.x, 0)
            x1 = min(s.x + s.w, self.bg.w)
            y0 = max(s.y, sy0)
            y1 = min(s.y + s.h, sy0 + rows)
            if x0 < x1 and y0 < y1:
                _blit_key(self._scratch, self.bg.w,
                          x0, y0 - sy0,
                          s.sheet.frame(s.frame), s.w,
                          x0 - s.x, y0 - s.y,
                          x1 - x0, y1 - y0,
                          KEY_BE)
        self._blit(self.btn, 0, sy0, self.bg.w, rows, self._scratch)
