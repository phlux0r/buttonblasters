# test_12_boot_ram.py
# Button Blasters -- Boot RAM & fragmentation probe
#
# CAVEAT LEARNED THE HARD WAY: this probe's "clear to build" verdict
# measures fragmentation IMMEDIATELY POST-BOOT, before any menu rendering,
# game session, or Tier B asset install has run. Star Bonk's actual
# StripBufferPool.__enter__() call (games/bonk/game.py's load(), via
# core/sprite_adapter.py) does NOT run at boot -- it runs after all of
# that churn -- and it failed to seat on real hardware (twice) despite
# this test's STRIP_H=32 verdict below. A boot-time "seats cleanly" is
# NOT the same claim as "seats where it's actually called from." STRIP_H
# is 16 in the live code now (see drivers/strip_renderer.py); this file
# is left as a record of the original (misleading, in hindsight)
# measurement rather than rewritten -- re-run it with a realistic
# post-menu/post-install heap state if you want a probe that actually
# predicts the failure mode that bit us.
#
# PURPOSE
#   Measure the REAL free heap and largest contiguous block on the RP2350
#   AFTER firmware v3.0 has finished booting -- i.e. once every peripheral
#   has taken its allocation: ILI9488, FT6236, 4x ST7789, I2S audio buffers,
#   WS2812B PIO SM, MCP23008, and the SD mount. Then trial-allocate the exact
#   strip-renderer buffers to PROVE the STRIP_H=32 + SD-double-buffer plan
#   seats cleanly BEFORE we build it. gc.mem_free() alone lies (it reports
#   total free, not the largest contiguous block) -- our whole MemoryError
#   history was fragmentation, so this probe allocates the real buffers.
#
# HOW TO RUN  (IMPORTANT: post-boot only, never on a cold board)
#   Option A (REPL, preferred):
#       Let the firmware boot fully, drop to the REPL, then:
#           >>> import test_12_boot_ram
#           >>> test_12_boot_ram.run()
#   Option B (inline):
#       Call test_12_boot_ram.run() at the very END of your boot sequence,
#       AFTER the SD mount and JUST BEFORE the asyncio event loop starts.
#
#   This module deliberately re-inits NO hardware and imports no drivers --
#   it allocates only plain bytearrays, so the figures reflect the live
#   firmware footprint rather than a fresh-import double count.

import gc
import micropython

# --- strip-renderer geometry (keep in sync with the renderer) -------------
MAIN_W     = 480
STRIP_H    = 32
RGB666_BPP = 3          # ILI9488 wire format (18-bit, 3 bytes/px)
RGB565_BPP = 2          # source / scratch format

RGB666_STRIP = MAIN_W * STRIP_H * RGB666_BPP   # 46,080 B
RGB565_STRIP = MAIN_W * STRIP_H * RGB565_BPP   # 30,720 B

# Shape Match anchor (existing, known-good ~50KB buffer) as a sanity ref
SHAPE_BUF = 160 * 160 * RGB565_BPP             # 51,200 B

KB = 1024


def _kb(n):
    return "%.1f KB" % (n / KB)


def _largest_contiguous():
    # Binary-search the largest single bytearray that will seat right now.
    # This is the real go/no-go number -- the RGB666 buffers need contiguous
    # space, and this is what fragmentation actually eats into.
    gc.collect()
    lo, hi, best = 0, gc.mem_free(), 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if mid == 0:
            break
        try:
            b = bytearray(mid)
            best = mid
            del b
            lo = mid + 1
        except MemoryError:
            hi = mid - 1
        gc.collect()
    return best


def _try_config(name, sizes):
    # Allocate ALL buffers simultaneously (the renderer holds them at once),
    # report, then release and confirm the heap recovers. Returns True if the
    # whole set seated together.
    gc.collect()
    before = gc.mem_free()
    held = []
    ok = True
    try:
        for s in sizes:
            held.append(bytearray(s))
    except MemoryError:
        ok = False
    gc.collect()                      # held refs keep buffers live here
    after = gc.mem_free()
    total = sum(sizes)
    print("  %-38s need %-9s -> %s" % (name, _kb(total),
                                       "OK" if ok else "FAILED"))
    if ok:
        print("      free with all buffers live: %s" % _kb(after))
    del held
    gc.collect()
    recovered = gc.mem_free()
    if abs(recovered - before) > 2 * KB:
        print("      WARNING: not fully recovered (%s -> %s)" % (
            _kb(before), _kb(recovered)))
    return ok


def run():
    print("=" * 60)
    print("Button Blasters -- Boot RAM probe (run POST-boot only)")
    print("=" * 60)

    gc.collect()
    free  = gc.mem_free()
    alloc = gc.mem_alloc()
    heap  = free + alloc
    print("Heap total : %s" % _kb(heap))
    print("Allocated  : %s   (firmware + all drivers + SD, live)" % _kb(alloc))
    print("Free       : %s" % _kb(free))

    biggest = _largest_contiguous()
    print("Largest contiguous block: %s" % _kb(biggest))
    if free and biggest < free:
        frag = 100 * (1 - biggest / free)
        print("  fragmentation: largest block is %.0f%% below total free" % frag)

    print("-" * 60)
    print("Strip-renderer buffer geometry (STRIP_H=%d):" % STRIP_H)
    print("  RGB666 wire strip : %s  (x2 ping-pong)" % _kb(RGB666_STRIP))
    print("  RGB565 src  strip : %s  (x2 for SD double-buffer)" % _kb(RGB565_STRIP))
    print("-" * 60)
    print("Trial allocations (all buffers held simultaneously):")

    primary = _try_config(
        "STRIP_H=32 + SD double-buffer",
        [RGB666_STRIP, RGB666_STRIP, RGB565_STRIP, RGB565_STRIP])

    _try_config(
        "fallback A: STRIP_H=32, single SD src",
        [RGB666_STRIP, RGB666_STRIP, RGB565_STRIP])

    _try_config(
        "fallback B: STRIP_H=16 + SD double-buffer",
        [RGB666_STRIP // 2, RGB666_STRIP // 2,
         RGB565_STRIP // 2, RGB565_STRIP // 2])

    print("-" * 60)
    print("Sanity anchor:")
    gc.collect()
    try:
        b = bytearray(SHAPE_BUF)
        del b
        gc.collect()
        print("  Shape Match 160x160 buffer (%s): OK" % _kb(SHAPE_BUF))
    except MemoryError:
        print("  Shape Match 160x160 buffer (%s): FAILED (!)" % _kb(SHAPE_BUF))

    print("-" * 60)
    print("Verbose heap map (fragmentation detail):")
    micropython.mem_info(1)

    print("=" * 60)
    if primary:
        print("VERDICT: STRIP_H=32 + SD double-buffer SEATS. Clear to build.")
    else:
        print("VERDICT: primary did NOT seat -- pick a fallback above.")
    print("=" * 60)
    gc.collect()


if __name__ == "__main__":
    run()
