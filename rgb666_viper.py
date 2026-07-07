# rgb666_viper.py — Button Blasters
# Fast RGB565 → RGB666 conversion using @micropython.viper.
#
# WHY: the ILI9488 needs 18-bit RGB666 (3 bytes/pixel). Doing this in a
# per-pixel Python loop starved the event loop (audio underruns + button
# lag). Viper compiles to native code with raw pointer access.
#
# BYTE ORDER: matches the EXISTING working blit EXACTLY —
#   hi = buf[pi] (first byte), lo = buf[pi+1] (second byte).
# Verified byte-for-byte against the Python reference by
# test_rgb666_viper.py.
#
# ILI9488 RGB666 packing (low bits zeroed):
#   dst[0] = hi & 0xF8                      -> red   (top 5 bits)
#   dst[1] = ((hi << 5) | (lo >> 3)) & 0xFC -> green (top 6 bits)
#   dst[2] = (lo << 3) & 0xF8               -> blue  (top 5 bits)
#
# src_px_off lets the caller convert a BAND starting at an arbitrary
# source pixel (for band-by-band blitting that avoids a large RGB666
# scratch buffer — a full 160x160 RGB666 buffer is 76KB and won't fit
# in the fragmented heap; a 160x16 band is ~7.5KB).

import micropython


@micropython.viper
def rgb565_to_666(src: ptr8, dst: ptr8, n_pixels: int, src_px_off: int):
    i = 0
    si = src_px_off * 2      # start reading this many pixels into src
    di = 0                   # always fill dst from the start
    while i < n_pixels:
        hi = int(src[si])
        lo = int(src[si + 1])
        dst[di]     = hi & 0xF8
        dst[di + 1] = ((hi << 5) | (lo >> 3)) & 0xFC
        dst[di + 2] = (lo << 3) & 0xF8
        si += 2
        di += 3
        i += 1
