# strip_renderer.py
# Button Blasters -- DMA-ready strip renderer for the ILI9488 main display.
#
# WHAT THIS IS
#   Paints full-screen illustrated scenes (My Big Day Out, Garden Grow,
#   Magic Bakery, Shadow Match, Star Bonk's board) that are too large to hold
#   as a full framebuffer (480x320 RGB565 = 300KB won't fit). It streams the
#   scene to the panel in 480x16 strips ("bands"), converting RGB565 -> RGB666
#   with the viper band converter and writing each band under the hard-won
#   RAMWR/CS rule. Shape Match and the menus keep their existing fill+blit
#   path -- this is ONLY for the illustrated full-screen scenes.
#
# MEASURED BUDGET -- TRUST WITH CAUTION
#   test_12_boot_ram.py measured 446KB heap, ~352KB free / 187KB
#   largest-contiguous, 47% frag, IMMEDIATELY POST-BOOT, and called a
#   STRIP_H=32 (150KB) pool "verified" there. That measurement is real but
#   was misleading for this pool's actual usage: Star Bonk's load() (the
#   first real caller) doesn't run at boot, it runs after menu carousel
#   rendering, LED effects, and a Tier B asset install have all churned the
#   heap -- and it failed to seat there TWICE on real hardware (~205-211KB
#   free, but no single ~45KB contiguous block), even after fixing an
#   allocation-order bug in games/bonk/game.py's load(). STRIP_H is now 16
#   (75KB pool, 22.5KB largest single block) specifically because "verified
#   at boot" did not mean "verified where it's actually used" -- re-measure
#   at the ACTUAL call site if you're validating a heap budget claim here,
#   not at boot.
#
# DESIGN
#   * StripRenderer is always alive but holds NO big buffers at rest.
#   * StripBufferPool is a scoped RAII resource: gc.collect() then allocate
#     hardest-first (2x 45KB RGB666, then 2x 30KB RGB565), HARD-FAIL with a
#     diagnostic MemoryError if any buffer can't seat -- no silent fallback.
#   * Used as a context manager so buffer release AND display-bus-freq restore
#     both happen in __exit__, exception-safe (an SD fault can't strand the
#     bus at 400kHz or leak the buffers):
#         with hw.display.acquire_strips() as strips:
#             await hw.display.blit_ram(strips, scene565)     # or blit_sd(...)
#   * The transmit seam (_start_transmit / _wait_transmit) is the ONLY thing
#     DMA changes later. Window setup, CS framing, viper convert, and the
#     public API stay identical. See the DMA note on _start_transmit.
#
# INTEGRATION SEAMS you wire to the existing firmware by hand:
#   1. Import geometry/freqs from config instead of the local consts below.
#   2. Pass the real ILI9488 raw `spi`, `cs`, `dc` pins into __init__.
#   3. Pass `set_bus_freq(hz)` -- wire it to the shared-bus wrapper. Per the
#      _current_freq desync gotcha it MUST always re-init the hardware, never
#      trust the cache. blit_* restores DISPLAY_FREQ in a finally regardless.
#   4. For blit_sd, supply a `read_band` callback that handles SD_CS/vfs and
#      the 400kHz bus switch (template in the docstring). SD and the display
#      share SPI0, so this is inherently serial -- see the shared-bus note.
#
# BENCH-CONFIRM before trusting output (project rule: panels lie):
#   RGB565 byte order. The converter below assumes LITTLE-ENDIAN source (asset
#   pipeline default). If red/blue are swapped or colours are garbled, flip
#   the two byte reads in the viper fn -- same class of bench-confirm as the
#   touch handedness. It cannot be reliably predicted from the datasheet.

import gc
import asyncio
import micropython
from micropython import const
import config

# --- geometry / freqs, sourced from config (single source of truth) -------
MAIN_W       = config.MAIN_W
MAIN_H       = config.MAIN_H
STRIP_H      = const(8)                # compositing granularity -- single
                                        # source of truth; core/sprite_engine.py
                                        # imports this rather than redefining
                                        # it.
                                        #
                                        # History: 32 -> 16 -> 8, each step
                                        # forced by a CONFIRMED on-hardware
                                        # MemoryError, not preemptive tuning.
                                        # 32 (150KB pool, 45KB largest block)
                                        # failed even after fixing load()'s
                                        # allocation order. 16 (75KB pool,
                                        # 22.5KB largest block) ALSO failed on
                                        # a later attempt in the same
                                        # power-on session (222KB free
                                        # overall, but no 22.5KB contiguous
                                        # run). 8 (37.5KB pool, 11.25KB
                                        # largest block) is the next step in
                                        # the same lever, at ~4x the original
                                        # strip count (40 vs 10 for a full
                                        # 320-row repaint) -- not yet
                                        # bench-confirmed either way.
                                        #
                                        # This recurring pattern -- same
                                        # class of failure resurfacing after
                                        # each halving -- suggests the REAL
                                        # fix may be structural, not size:
                                        # MainScreenAdapter.open()/close()
                                        # allocates and frees this pool once
                                        # per Bonk game SESSION (not once per
                                        # boot), so repeated play across one
                                        # power-on period churns the heap
                                        # with same-shape alloc/free cycles a
                                        # non-compacting allocator can't
                                        # perfectly reclaim. If STRIP_H=8
                                        # still fails, the next lever isn't a
                                        # smaller buffer -- it's making this
                                        # pool persistent (seated once,
                                        # module-level, like
                                        # flash_assets.arena already is)
                                        # instead of per-session. That's a
                                        # bigger architectural change
                                        # (permanent heap reservation whether
                                        # or not Bonk is played) and hasn't
                                        # been applied here -- confirm
                                        # STRIP_H=8 is insufficient first.
DISPLAY_FREQ = config.SPI_FREQ_DISPLAY
SD_FREQ      = config.SPI_FREQ_SD_DATA

RGB666_STRIP = MAIN_W * STRIP_H * 3   # 46,080 B  (wire format)
RGB565_STRIP = MAIN_W * STRIP_H * 2   # 30,720 B  (SD source strip)

# ILI9488 commands
_CASET = const(0x2A)
_RASET = const(0x2B)
_RAMWR = const(0x2C)


# --------------------------------------------------------------------------
# viper band converter: RGB565 (little-endian) -> RGB666 (18-bit, 3 bytes/px)
# Module-level (viper must be), takes a src BYTE offset so each band starts at
# the right row -- matches the existing convert-in-bands pipeline contract.
# ILI9488 18-bit mode uses the top 6 bits of each byte; 5-bit channels are
# expanded 5->6 by bit replication so whites stay clean.
# --------------------------------------------------------------------------
@micropython.viper
def rgb565_to_rgb666_band(src: ptr8, src_off: int, dst: ptr8, n: int):
    i = 0
    while i < n:
        so = src_off + (i << 1)
        b0 = int(src[so])          # low byte  : GGG BBBBB   (little-endian)
        b1 = int(src[so + 1])      # high byte : RRRRR GGG
        px = (b1 << 8) | b0
        r5 = (px >> 11) & 0x1F
        g6 = (px >> 5) & 0x3F
        b5 = px & 0x1F
        do = i * 3
        dst[do]     = (r5 << 3) | (r5 >> 2)   # 6-bit R in bits [7:2]
        dst[do + 1] = g6 << 2                  # 6-bit G in bits [7:2]
        dst[do + 2] = (b5 << 3) | (b5 >> 2)   # 6-bit B in bits [7:2]
        i += 1


class StripBufferPool:
    """Scoped RAII owner of the strip buffers. Acquire hardest-first, hard-fail
    with diagnostics, release + restore display bus freq on exit."""

    def __init__(self, renderer):
        self._r = renderer
        self.rgb666 = (None, None)     # ping-pong wire buffers (both paths)
        self.src565 = (None, None)     # SD source strips (blit_sd; [1] reserved)
        self._mv666 = (None, None)
        self._mv565 = (None, None)

    def _fail(self, which):
        gc.collect()
        raise MemoryError(
            "StripBufferPool: %s did not seat "
            "(free=%d, largest~needs %d contiguous). "
            "Heap too fragmented for STRIP_H=%d at this point in play -- "
            "acquire earlier / at a quieter load moment."
            % (which, gc.mem_free(), RGB666_STRIP, STRIP_H))

    def __enter__(self):
        gc.collect()                               # max defrag before we grab
        try:
            a666 = bytearray(RGB666_STRIP)
        except MemoryError:
            self._fail("rgb666[0]")
        try:
            b666 = bytearray(RGB666_STRIP)
        except MemoryError:
            del a666
            self._fail("rgb666[1]")
        try:
            a565 = bytearray(RGB565_STRIP)
        except MemoryError:
            del a666, b666
            self._fail("src565[0]")
        try:
            b565 = bytearray(RGB565_STRIP)
        except MemoryError:
            del a666, b666, a565
            self._fail("src565[1]")

        self.rgb666 = (a666, b666)
        self.src565 = (a565, b565)
        self._mv666 = (memoryview(a666), memoryview(b666))
        self._mv565 = (memoryview(a565), memoryview(b565))
        return self

    def __exit__(self, *exc):
        # Release buffers and restore the display bus speed together, so an
        # SD-sourced scene that faulted mid-band cannot leave the bus at
        # 400kHz (the 44-second-fill symptom) or leak 150KB.
        self.rgb666 = (None, None)
        self.src565 = (None, None)
        self._mv666 = (None, None)
        self._mv565 = (None, None)
        gc.collect()
        try:
            self._r.set_bus_freq(DISPLAY_FREQ)
        except Exception:
            pass
        return False                               # never swallow exceptions

    # memoryview of RGB666 band `idx` sliced to `nbytes`
    def wire(self, idx, nbytes):
        return self._mv666[idx][:nbytes]

    # memoryview of RGB565 source strip `idx` sliced to `nbytes`
    def src(self, idx, nbytes):
        return self._mv565[idx][:nbytes]


class StripRenderer:
    """Cheap-at-rest renderer for ILI9488 illustrated scenes.

    __init__ args (wire to the real firmware objects):
      spi          -- raw machine.SPI for pixel/command bytes on SPI0
      cs, dc       -- ILI9488 CS (GP6) and DC (GP12) Pin objects, manual OUT
      set_bus_freq -- callable(hz): set + ALWAYS re-init the shared bus freq
    """

    def __init__(self, spi, cs, dc, set_bus_freq):
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.set_bus_freq = set_bus_freq
        self._b1 = bytearray(1)        # reused 1-byte scratch, no per-call alloc
        # transmit-seam state (used by the DMA impl later)
        self._tx_evt = asyncio.Event()

    # ---- context manager entry point -------------------------------------
    def acquire_strips(self):
        return StripBufferPool(self)

    # ---- per-byte CS-framed command/param (ILI9488 confirmed rule) -------
    def _cmd(self, b):
        self.dc(0); self.cs(0)
        self._b1[0] = b; self.spi.write(self._b1)
        self.cs(1)

    def _par(self, b):
        self.dc(1); self.cs(0)
        self._b1[0] = b; self.spi.write(self._b1)
        self.cs(1)

    def _set_window(self, x0, y0, x1, y1):
        self._cmd(_CASET)
        self._par(x0 >> 8); self._par(x0 & 0xFF)
        self._par(x1 >> 8); self._par(x1 & 0xFF)
        self._cmd(_RASET)
        self._par(y0 >> 8); self._par(y0 & 0xFF)
        self._par(y1 >> 8); self._par(y1 & 0xFF)

    # ---- THE TRANSMIT SEAM -----------------------------------------------
    # RAMWR + one band of pixels under a SINGLE continuous CS-LOW.
    # CS goes LOW at 0x2C and rises ONCE after the pixels (never mid-stream).
    #
    # _start_transmit / _wait_transmit are the ONLY thing DMA changes:
    #   BLOCKING (now): spi.write() returns when the band has drained.
    #   DMA (later): _start_transmit kicks an rp2.DMA channel into the PL022
    #     SPI TX FIFO (correct DREQ) and returns immediately; its completion
    #     IRQ sets self._tx_evt; _wait_transmit awaits it. CS stays a plain
    #     manual GPIO the primitive never touches -- which is exactly what
    #     lets DMA leave it alone. The rp2.DMA<->PL022 wiring on RP2350 /
    #     v1.28 is UNVERIFIED and must be bench-confirmed before trusting it;
    #     nothing outside these two methods depends on getting it right.
    def _start_transmit(self, wire_mv):
        # BLOCKING impl: synchronous; the band is on the wire when this returns.
        self.spi.write(wire_mv)
        self._tx_evt.set()

    async def _wait_transmit(self):
        # BLOCKING impl: already done -- yield once so the loop breathes
        # (prevents the audio-tearing / button-lag freeze from a long fill).
        await asyncio.sleep_ms(0)
        self._tx_evt.clear()

    def _ramwr_begin(self):
        self.dc(0); self.cs(0)         # CS LOW -- stays low through the band
        self._b1[0] = _RAMWR; self.spi.write(self._b1)
        self.dc(1)                     # data mode; CS still LOW

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def _band_rows(i, total_rows):
        r = total_rows - i * STRIP_H
        return STRIP_H if r >= STRIP_H else r

    # ======================================================================
    # RAM-sourced scene: the whole image already lives in one RGB565 buffer.
    # No SD strip needed -- convert straight from the big buffer at each band
    # offset. DMA overlaps convert(N+1) with the transmit of band N via the
    # 666 ping-pong; in the blocking build it's serial (correct, just no
    # parallelism). Assumes bus already at DISPLAY_FREQ.
    #   scene565 : bytes-like, width*rows RGB565, little-endian
    # ======================================================================
    async def blit_ram(self, strips, scene565, y0=0, rows=MAIN_H,
                       x0=0, width=MAIN_W):
        self.set_bus_freq(DISPLAY_FREQ)
        try:
            n_bands = (rows + STRIP_H - 1) // STRIP_H
            cur = 0
            # prime band 0 into wire[0]
            r0 = self._band_rows(0, rows)
            rgb565_to_rgb666_band(scene565, 0, strips.rgb666[0], width * r0)
            for i in range(n_bands):
                ri = self._band_rows(i, rows)
                yb = y0 + i * STRIP_H
                nbytes = width * ri * 3
                self._set_window(x0, yb, x0 + width - 1, yb + ri - 1)
                self._ramwr_begin()
                self._start_transmit(strips.wire(cur, nbytes))
                # prefetch next band while this one is on the wire (DMA win)
                if i + 1 < n_bands:
                    nxt = cur ^ 1
                    rn = self._band_rows(i + 1, rows)
                    off = (i + 1) * STRIP_H * width * 2      # byte offset
                    rgb565_to_rgb666_band(scene565, off,
                                          strips.rgb666[nxt], width * rn)
                await self._wait_transmit()
                self.cs(1)                                   # end band i
                cur ^= 1
        finally:
            self.set_bus_freq(DISPLAY_FREQ)                  # never stranded

    # ======================================================================
    # SD-sourced scene: stream band-by-band from the card.
    #
    # SHARED-BUS REALITY: SD and the ILI9488 are both on SPI0. You cannot read
    # the next band from SD while the current band is transmitting -- the bus
    # is busy AND at the wrong clock (400kHz vs 10MHz). So this path is
    # inherently SERIAL: read(400kHz) -> convert -> write(10MHz) -> read...
    # The second src565 buffer therefore buys NO overlap on this wiring; it's
    # allocated (validated footprint) and reserved for a future board that
    # moves SD to SPI1. The 666 ping-pong still lets DMA overlap convert with
    # transmit within the write phase.
    #
    # read_band(dst565_mv, band_index, band_rows) -- YOU supply this. It must:
    #   1. self.set_bus_freq(SD_FREQ)
    #   2. read band_rows*width*2 bytes from the open scene file into dst565_mv
    #      (via the mounted SD / vfs -- SD_CS handled by the SD driver)
    #   3. self.set_bus_freq(DISPLAY_FREQ)   # leave bus ready for transmit
    # It MUST return with the bus at DISPLAY_FREQ.
    # ======================================================================
    async def blit_sd(self, strips, read_band, y0=0, rows=MAIN_H,
                      x0=0, width=MAIN_W):
        try:
            n_bands = (rows + STRIP_H - 1) // STRIP_H
            cur = 0
            for i in range(n_bands):
                ri = self._band_rows(i, rows)
                yb = y0 + i * STRIP_H
                npx = width * ri
                nbytes = npx * 3
                # read (400kHz) then convert -- read_band restores display freq
                read_band(strips.src(cur, npx * 2), i, ri)
                rgb565_to_rgb666_band(strips.src565[cur], 0,
                                      strips.rgb666[cur], npx)
                self._set_window(x0, yb, x0 + width - 1, yb + ri - 1)
                self._ramwr_begin()
                self._start_transmit(strips.wire(cur, nbytes))
                await self._wait_transmit()
                self.cs(1)                                   # end band i
                cur ^= 1
        finally:
            self.set_bus_freq(DISPLAY_FREQ)                  # never stranded
