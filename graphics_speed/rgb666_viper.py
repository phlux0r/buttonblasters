# rgb666_viper.py — Button Blasters
# Fast RGB565 → RGB666 conversion using @micropython.viper.
#
# WHY: the ILI9488 needs 18-bit RGB666 (3 bytes/pixel). The old blit did
# this conversion in a per-pixel Python loop, which starved the event
# loop (audio underruns + button lag) during a shape blit. Viper compiles
# to native code with raw pointer access, removing the per-pixel Python
# object overhead entirely.
#
# BYTE ORDER: matches the EXISTING working blit EXACTLY —
#   hi = buf[pi]      (first byte)
#   lo = buf[pi + 1]  (second byte)
# The displayed colours are already correct on hardware with this order,
# so the viper output MUST reproduce it byte-for-byte (verified by
# test_rgb666_viper.py before this is wired into display.py).
#
# ILI9488 RGB666 packing (low bits zeroed):
#   dst[0] = hi & 0xF8                      -> red   (top 5 bits)
#   dst[1] = ((hi << 5) | (lo >> 3)) & 0xFC -> green (top 6 bits)
#   dst[2] = (lo << 3) & 0xF8               -> blue  (top 5 bits)

import micropython


@micropython.viper
def rgb565_to_666(src: ptr8, dst: ptr8, n_pixels: int):
    i = 0
    si = 0
    di = 0
    while i < n_pixels:
        hi = int(src[si])          # first byte  (matches buf[pi])
        lo = int(src[si + 1])      # second byte (matches buf[pi+1])
        dst[di]     = hi & 0xF8
        dst[di + 1] = ((hi << 5) | (lo >> 3)) & 0xFC
        dst[di + 2] = (lo << 3) & 0xF8
        si += 2
        di += 3
        i += 1
