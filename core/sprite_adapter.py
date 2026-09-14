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
    the viper 565LE→666 convert, the RAMWR/CS-low framing, the transmit and
    the event-loop yield, all while holding the shared SPI0 bus lock (see
    drivers/strip_renderer.py's BUS LOCKING note).

Button path: one seam left (# >>> WIRE:) for blit_btn_buf / blit_rgb565 —
wire when the ST7789 driver object is at hand.

Usage in a game:

    from core.sprite_adapter import MainScreenAdapter, make_main_strip_renderer

    adapter = MainScreenAdapter(make_main_strip_renderer())
    adapter.open()                                # at load(): seats the pool
    try:
        eng = SpriteEngine(adapter, bg)
        ...
        await eng.stop()
    finally:
        adapter.close()                           # at unload(): frees 150KB
"""

from machine import Pin
from drivers.spi_bus import spi_bus
from drivers.strip_renderer import StripRenderer, RGB565_STRIP
import config


def make_main_strip_renderer():
    """Construct a StripRenderer wired to the ILI9488 main display's real
    CS/DC pins and the shared SPI0 bus. Each call makes its own Pin handles
    for GP{PIN_CS_MAIN,PIN_DC_MAIN} — MicroPython allows multiple Pin
    objects for the same GPIO, and the renderer and the normal ILI9488
    fill/blit path serialise on the bus lock, so they never drive the
    panel at the same time."""
    cs = Pin(config.PIN_CS_MAIN, Pin.OUT, value=1)
    dc = Pin(config.PIN_DC_MAIN, Pin.OUT, value=1)
    return StripRenderer(spi_bus, cs, dc)


# Persistent, module-level (like flash_assets.arena) instead of the pool's
# original per-game-session RAII scope. STRIP_H already dropped 32->16->8,
# each step forced by a confirmed on-hardware MemoryError from repeated
# per-session alloc/free fragmenting the heap (see HARDWARE_NOTES.md) -- at
# STRIP_H=8 it STILL failed, confirming the docs' own predicted "next lever":
# seat once, on the freshest heap, never free until power-off.
_shared_pool = None


def seat_shared_pool():
    """Seat the main-screen strip buffer pool once, called from
    core/kernel.py at boot before menu/subsystem churn exists. Idempotent —
    a no-op if already seated. The pool then lives for the whole power-on
    session (not just one game's), so MainScreenAdapter.close() below
    intentionally never frees it."""
    global _shared_pool
    if _shared_pool is None:
        renderer = make_main_strip_renderer()
        p = renderer.acquire_strips()
        p.__enter__()
        _shared_pool = p


class MainScreenAdapter:
    """Adapter for sprite_engine.SpriteEngine on the ILI9488.

    renderer: a constructed StripRenderer (bus, cs, dc wired).

    Bus clock: blit_ram() sets it through spi_bus's cache-aware path on
    every strip, which is a compare (not an spi.init()) whenever the clock
    is already at DISPLAY_FREQ — so there's no longer any need for the
    old open()-time "set once and no-op the setter" bypass (that hack
    existed to dodge ~97ms/strip of redundant spi.init() calls, before the
    bus wrapper cached the current frequency). A game that reads SD mid-
    scene just leaves the clock at SD speed for that read; the next strip
    pushes it back."""

    def __init__(self, renderer):
        self._r = renderer
        self._pool = None

    # ------------------------------------------------------------ lifetime

    def open(self):
        """Attach to the shared strip buffer pool (seated at boot by
        seat_shared_pool() — this call is just a defensive fallback). Call
        at game load()."""
        if self._pool is not None:
            return
        seat_shared_pool()
        self._pool = _shared_pool

    def close(self):
        """Detach from the shared pool. Call at unload(). Does NOT free the
        pool's buffers — it's shared/persistent for the whole power-on
        session, not scoped to one game (see seat_shared_pool())."""
        self._pool = None

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
        blit_ram does convert + window + RAMWR framing, under the bus lock."""
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
