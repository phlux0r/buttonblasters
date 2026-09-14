#!/usr/bin/env python3
"""
verify_bake.py — check a baked .sz sprite against its source PNG for the
colour-key dithering/fringe bug (see tools/bake_assets.py's ffmpeg_to_raw
docstring for the full history: hard-alpha-threshold fix, then alpha-
erosion fix, then the real root cause -- ffmpeg dithering RGBA->RGB565).

For a source that's fully opaque (uniform alpha) with an exact matte
background -- true of source art with no antialiasing/soft edges, which
this project's sprite art is meant to be -- the baked output should be a
DETERMINISTIC pixel-for-pixel RGB565 truncation of the source: zero
mismatches, and the matte colour must appear bit-exact everywhere the
source has it, with zero near-matte-but-not-exact pixels anywhere
(colour-key compositing in core/sprite_engine.py does a plain != compare,
no tolerance -- any near-key pixel shows up as a visible fringe).

For source art that DOES have genuine antialiased/partial-alpha edges,
some non-key pixels near the silhouette boundary are expected and fine
(they're real edge colour, not fringe) -- this script only flags the
things that are never legitimate: matte-should-be-exact pixels that
aren't, and near-key contamination.

Usage:
  python3 tools/verify_bake.py <source.png> <baked.sz> [--key 0xF81F]

Requires: Pillow (pip install pillow).
"""

import argparse
import struct
import sys
import zlib
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow required: pip install pillow")


def load_sz(path):
    data = Path(path).read_bytes()
    if data[:4] != b"BBA1":
        sys.exit(f"{path}: not a BBA1 asset (bad magic)")
    kind, strip_h, w, h, frames, flags, n_chunks, _res = struct.unpack(
        "<BBHHBBHH", data[4:16])
    off = 16
    chunks = []
    for _ in range(n_chunks):
        coff, clen = struct.unpack("<II", data[off:off + 8])
        chunks.append((coff, clen))
        off += 8
    return dict(kind=kind, strip_h=strip_h, w=w, h=h, frames=frames,
                flags=flags, data=data[off:], chunks=chunks)


def decode_frame(info, idx=0):
    coff, clen = info["chunks"][idx]
    raw = info["data"][coff:coff + clen]
    if info["flags"] & 0x01:      # FLAG_RAW -- no zlib
        return raw
    return zlib.decompressobj(10).decompress(raw)


def to_rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def unpack565(v):
    return (v >> 11) & 0x1F, (v >> 5) & 0x3F, v & 0x1F


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("png", type=Path)
    ap.add_argument("sz", type=Path)
    ap.add_argument("--key", default="0xF81F",
                    help="expected RGB565 colour key (default 0xF81F = magenta)")
    ap.add_argument("--endian", choices=["le", "be", "auto"], default="auto",
                    help="baked pixel byte order (auto = infer from .sz kind byte)")
    args = ap.parse_args()

    key = int(args.key, 16) if args.key.startswith("0x") else int(args.key)

    img = Image.open(args.png).convert("RGBA")
    w, h = img.size
    px = img.load()

    info = load_sz(args.sz)
    if (info["w"], info["h"]) != (w, h):
        sys.exit(f"size mismatch: PNG is {w}x{h}, .sz says "
                 f"{info['w']}x{info['h']}")

    endian = args.endian
    if endian == "auto":
        # kind 2 = spr_ (LE), kind 3 = sprb_ (BE) -- see bake_assets.py's KINDS
        endian = "be" if info["kind"] in (1, 3) else "le"
    fmt = (">" if endian == "be" else "<") + f"{w*h}H"
    pixels = struct.unpack(fmt, decode_frame(info))

    alpha_values = set()
    matte_mismatches = []      # source==key-colour-when-truncated but baked != key
    contamination = []         # baked pixel is near-key but not exact, and source wasn't matte
    other_mismatches = 0
    checked_opaque = 0

    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            alpha_values.add(a)
            actual = pixels[y * w + x]
            src_is_matte = to_rgb565(r, g, b) == key

            if a == 255:
                checked_opaque += 1
                expected = to_rgb565(r, g, b)
                if expected != actual:
                    if src_is_matte:
                        matte_mismatches.append((x, y, actual))
                    else:
                        other_mismatches += 1
                        ar, ag, ab = unpack565(actual)
                        # near-key but shouldn't be, and isn't a legitimate
                        # edge (edges only make sense where alpha < 255)
                        if ar >= 18 and ab >= 18 and ag <= 24 and actual != key:
                            contamination.append((x, y, (r, g, b), actual))

    print(f"{args.png.name} -> {args.sz.name}  ({w}x{h}, key=0x{key:04X}, {endian.upper()})")
    print(f"  source alpha values present: {sorted(alpha_values)}")
    print(f"  opaque pixels checked: {checked_opaque}/{w*h}")
    print(f"  matte pixels that should be exact key but aren't: {len(matte_mismatches)}")
    print(f"  near-key contamination (fringe) pixels: {len(contamination)}")
    print(f"  other truncation mismatches (only expected on real antialiased edges): {other_mismatches}")

    if matte_mismatches:
        print("\n  Sample matte mismatches (x, y, actual_hex):")
        for x, y, actual in matte_mismatches[:10]:
            print(f"    ({x},{y}) -> 0x{actual:04X}")

    if contamination:
        print("\n  Sample fringe pixels (x, y, source_rgb, actual_hex):")
        for x, y, rgb, actual in contamination[:10]:
            print(f"    ({x},{y}) src={rgb} -> 0x{actual:04X}")

    fail = bool(matte_mismatches) or bool(contamination)
    print()
    if fail:
        print("FAIL -- dithering/fringe bug still present. If you've already "
              "added -sws_dither none to bake_assets.py, re-bake and re-run "
              "this check; if it still fails, the ffmpeg build in use may "
              "route this conversion through a path -sws_dither doesn't "
              "reach, worth reporting back.")
        sys.exit(1)
    else:
        print("PASS -- matte pixels are bit-exact, no fringe contamination.")


if __name__ == "__main__":
    main()
