"""
sprite_adapter.py — glue between sprite_engine and strip_renderer / button blit
(MicroPython v1.28, RP2350) — WIRED against the real strip_renderer.py API.

Main-screen path is fully wired:
  * The adapter owns a StripBufferPool for the LIFETIME OF A GAME (open() at
    game load, close() at unload). This is a deliberate departure from the
    pool's per-scene RAII design — sprite animation repaints continuously, so
    the 150KB pool stays seated for the whole game. close() still runs the
    pool's __exit__, so buffer release + display-freq restore stay
    exception-safe; wrap game code so close() is in a finally.
  * The engine's compose buffer is the pool's src565[0] (30,720B) — blit_ram
    never touches src565 (only blit_sd does), so it's free real estate. No
    new allocation anywhere in this file.
  * push_strip() = StripRenderer.blit_ram() windowed to one strip: it does
    the viper 565LE→666 convert, the RAMWR/CS-low framing, the transmit, the
    event-loop yield, and the DISPLAY_FREQ restore in its own finally.

Button path: one seam left (# >>> WIRE:) for blit_btn_buf / blit_rgb565 —
wire when the ST7789 driver object is at hand.

Usage in a game:

    from drivers import strip_renderer            # or wherever it lives
    from core.sprite_adapter import MainScreenAdapter

    adapter = MainScreenAdapter(renderer)         # renderer = StripRenderer
    adapter.open()                                # at load(): seats the pool
    try:
        eng = SpriteEngine(adapter, bg)
        ...
        await eng.stop()
    finally:
        adapter.close()                           # at unload(): frees 150KB
"""

from drivers.strip_renderer import RGB565_STRIP, DISPLAY_FREQ


def _freq_noop(hz):
    pass


class MainScreenAdapter:
    """Adapter for sprite_engine.SpriteEngine on the ILI9488.

    renderer: a constructed StripRenderer (spi, cs, dc, set_bus_freq wired).

    bypass_freq (default True): while the pool is open, set the bus to
    DISPLAY_FREQ once and replace renderer.set_bus_freq with a no-op, so
    blit_ram's per-strip entry+finally freq calls don't do 2 spi.init()s
    per strip (bench: ~97ms/strip unaccounted = the difference between
    ~1.5s and ~0.5s full paints). SAFE because flash-asset games never
    change the bus speed: flash reads don't touch SPI0, and the ST7789
    blits also run at DISPLAY_FREQ. Set bypass_freq=False for any game
    that touches SD mid-game (blit_sd / assets.read on SPI0) — the real
    set_bus_freq is always restored at close(), before the pool's own
    freq-restoring __exit__ runs."""

    def __init__(self, renderer, bypass_freq=True):
        self._r = renderer
        self._pool = None
        self._bypass = bypass_freq
        self._real_freq = None

    # ------------------------------------------------------------ lifetime

    def open(self):
        """Seat the strip buffers. Call at game load(), a quiet heap moment.
        Raises the pool's diagnostic MemoryError if buffers can't seat."""
        if self._pool is not None:
            return
        p = self._r.acquire_strips()
        p.__enter__()                 # manual enter: held across the game
        self._pool = p
        if self._bypass:
            self._real_freq = self._r.set_bus_freq
            self._real_freq(DISPLAY_FREQ)          # once, for the whole game
            self._r.set_bus_freq = _freq_noop

    def close(self):
        """Release buffers + restore display bus freq. Call at unload(),
        ideally from a finally so a crashing game can't leak the pool."""
        if self._real_freq is not None:
            self._r.set_bus_freq = self._real_freq   # BEFORE pool exit,
            self._real_freq = None                   # so __exit__ restores
        if self._pool is not None:                   # the real frequency
            p = self._pool
            self._pool = None
            p.__exit__(None, None, None)

    @property
    def is_open(self):
        return self._pool is not None

    # ------------------------------------------------------- engine seams

    def acquire_src(self):
        """LE RGB565 compose buffer for the engine: the pool's src565[0].
        blit_ram never uses src565, so the engine composes here and blit_ram
        converts straight out of it into the RGB666 ping-pong."""
        if self._pool is None:
            raise RuntimeError("MainScreenAdapter.open() not called")
        return self._pool.src(0, RGB565_STRIP)

    async def push_strip(self, y, rows, src_le):
        """Transmit one composed strip: rows y..y+rows-1, full width.
        blit_ram does convert + window + RAMWR framing + freq restore."""
        await self._r.blit_ram(self._pool, src_le, y0=y, rows=rows)


def make_button_blit(displays):
    """Returns blit_be(btn_id, x, y, w, h, buf_be) for ButtonSprite.

    displays = your button-display driver object/module (the one that owns
    blit_btn_buf / blit_rgb565 for the four ST7789s).
    """
    def blit_be(btn_id, x, y, w, h, buf_be):
        # >>> WIRE: your existing BE blit path, e.g.:
        #   displays.blit_rgb565(btn_id, x, y, w, h, buf_be)
        # (BE assets only — the strip path above is LE; never cross them.)
        raise NotImplementedError("wire blit_be to blit_btn_buf/blit_rgb565")
    return blit_be
