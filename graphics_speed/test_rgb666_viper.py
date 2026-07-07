# test_rgb666_viper.py — verify viper RGB565→666 matches the reference
#
# Run standalone on the Pico. Converts the SAME input two ways:
#   1. The exact per-pixel Python loop from the old ILI9488.blit_rgb565
#      (the known-correct reference — colours already right on hardware)
#   2. The new @micropython.viper rgb565_to_666
# and asserts the outputs are byte-for-byte identical. Also times both
# so we can see the speedup.
#
# PASS here = safe to wire viper into display.py.

import time
from rgb666_viper import rgb565_to_666


def _reference(buf, total):
    # EXACT copy of the old blit's inner conversion loop.
    out = bytearray(total * 3)
    for i in range(total):
        pi = i * 2
        hi = buf[pi]; lo = buf[pi + 1]
        out[i*3]   = hi & 0xF8
        out[i*3+1] = ((hi << 5) | (lo >> 3)) & 0xFC
        out[i*3+2] = (lo << 3) & 0xF8
    return out


def main():
    # Build a representative test buffer: 160x160 pixels (a shape buffer),
    # filled with a spread of RGB565 values so every bit path is exercised.
    N = 160 * 160
    src = bytearray(N * 2)
    for i in range(N):
        val = (i * 2654435761) & 0xFFFF   # cheap pseudo-random spread
        src[i*2]   = val & 0xFF
        src[i*2+1] = (val >> 8) & 0xFF

    print("=" * 50)
    print(f"RGB565->666 VIPER CORRECTNESS TEST  ({N} px)")
    print("=" * 50)

    # Reference (Python)
    t0 = time.ticks_ms()
    ref = _reference(src, N)
    t_ref = time.ticks_diff(time.ticks_ms(), t0)
    print(f"Python reference: {t_ref} ms")

    # Viper
    dst = bytearray(N * 3)
    t0 = time.ticks_ms()
    rgb565_to_666(src, dst, N)
    t_viper = time.ticks_diff(time.ticks_ms(), t0)
    print(f"Viper:            {t_viper} ms")

    # Compare byte-for-byte
    mismatches = 0
    first_bad = -1
    for i in range(len(ref)):
        if ref[i] != dst[i]:
            mismatches += 1
            if first_bad < 0:
                first_bad = i
    print("-" * 50)
    if mismatches == 0:
        speedup = (t_ref / t_viper) if t_viper > 0 else float('inf')
        print(f"MATCH: identical output. Speedup ~{speedup:.1f}x")
        print("=> PASS — safe to wire viper into display.py")
    else:
        print(f"MISMATCH: {mismatches} bytes differ, first at index {first_bad}")
        pi = (first_bad // 3) * 2
        print(f"  src pixel bytes: {src[pi]:#04x} {src[pi+1]:#04x}")
        print(f"  ref: {ref[first_bad]:#04x}  viper: {dst[first_bad]:#04x}")
        print("=> FAIL — do NOT wire in; report this output to Claude")


main()
