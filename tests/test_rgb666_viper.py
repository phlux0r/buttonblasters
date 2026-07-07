# test_rgb666_viper.py — verify viper RGB565→666 matches the reference,
# including BAND conversion with a source pixel offset.
#
# Run standalone on the Pico. PASS = safe to use in display.py.

import time
from rgb666_viper import rgb565_to_666


def _reference(buf, total):
    out = bytearray(total * 3)
    for i in range(total):
        pi = i * 2
        hi = buf[pi]; lo = buf[pi + 1]
        out[i*3]   = hi & 0xF8
        out[i*3+1] = ((hi << 5) | (lo >> 3)) & 0xFC
        out[i*3+2] = (lo << 3) & 0xF8
    return out


def main():
    W, H = 160, 160
    N = W * H
    src = bytearray(N * 2)
    for i in range(N):
        val = (i * 2654435761) & 0xFFFF
        src[i*2]   = val & 0xFF
        src[i*2+1] = (val >> 8) & 0xFF

    print("=" * 52)
    print(f"RGB565->666 VIPER TEST (whole + banded)  {N} px")
    print("=" * 52)

    ref = _reference(src, N)

    # 1) Whole-buffer (offset 0) must still match.
    whole = bytearray(N * 3)
    t0 = time.ticks_ms()
    rgb565_to_666(src, whole, N, 0)
    t_whole = time.ticks_diff(time.ticks_ms(), t0)
    whole_ok = bytes(whole) == bytes(ref)
    print(f"whole-buffer: {t_whole} ms  match={whole_ok}")

    # 2) Banded: convert 16-row bands with src offset, assemble, compare.
    BAND = 16
    band_buf = bytearray(W * BAND * 3)
    assembled = bytearray(N * 3)
    apos = 0
    row = 0
    t0 = time.ticks_ms()
    while row < H:
        rows = BAND if (H - row) >= BAND else (H - row)
        n_px = W * rows
        rgb565_to_666(src, band_buf, n_px, W * row)
        assembled[apos:apos + n_px*3] = band_buf[:n_px*3]
        apos += n_px * 3
        row += rows
    t_band = time.ticks_diff(time.ticks_ms(), t0)
    band_ok = bytes(assembled) == bytes(ref)
    print(f"banded:       {t_band} ms  match={band_ok}")

    print("-" * 52)
    if whole_ok and band_ok:
        print("=> PASS — whole and banded both match reference.")
    else:
        print("=> FAIL — report which mode mismatched to Claude.")


main()
