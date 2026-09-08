#!/usr/bin/env python3
"""
bake_assets.py — Button Blasters asset baker (desktop, Python 3.8+, needs ffmpeg)

Walks an art/ tree of PNGs and bakes them into chunked, zlib-compressed
RGB565 assets for the Pico 2W (littlefs or SD).

Filename convention (prefix picks the pipeline):
  bg_<name>_480x320.png     main-screen background  -> .bz  (RGB565 LITTLE-endian)
  bgraw_<name>_480x320.png  same, RAW chunks (no zlib): ~10x faster on-device
                            strip loads, ~5-10x more flash. Use for the HOT
                            backgrounds sprites animate over.
  btn_<name>_240x300.png    button-screen background-> .bz  (RGB565 BIG-endian)
  btnraw_<name>_240x300.png same, RAW chunks (see bgraw)
  spr_<name>_48x48x6.png    main-screen sprite sheet-> .sz  (LE, magenta 0xF81F key)
  sprb_<name>_48x48x4.png   button-screen sprite    -> .sz  (BE, magenta key)

Sprite sheets: frames laid out in ONE horizontal row, transparent background.
Sheet PNG width must equal frame_w * frames; height must equal frame_h.

Usage:
  ./bake_assets.py art/ build/ [--budget 2560] [--force]

Output file format ("BBA1", all header ints little-endian):
  0   4  magic  b'BBA1'
  4   1  kind   0=bg LE  1=bg BE  2=spr LE  3=spr BE
  5   1  strip_h  rows per chunk (bg) / frame height (sprites)
  6   2  width    pixels (frame width for sprites)
  8   2  height   pixels (frame height for sprites)
  10  1  frames   1 for backgrounds
  11  1  reserved
  12  2  n_chunks
  14  2  reserved
  16  n_chunks * (u32 offset, u32 comp_len)   offsets relative to data start
  ... data (each chunk an independent zlib stream, wbits=10 -> 1KB window)

Each background chunk is one strip -- 8 rows for kind 0 (LE, bg_/bgraw_,
must match core/sprite_engine.py's hard-enforced STRIP_H), 32 rows for
kind 1 (BE, bgm_/btn_, no such runtime constraint) -- last strip may be
shorter. Each sprite chunk is one whole frame.
"""

import argparse
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

# Kind 1 (BE, bgm_/btn_) backgrounds only ever get read strip-by-strip via
# paint_main_bg()/paint_btn_bg(), which has no fixed-size expectation --
# any chunk height works, this is just a size/chunk-count tuning knob.
BG_CHUNK_H = 32

# Kind 0 (LE, bg_/bgraw_) backgrounds are different: they're the only kind
# fed to core/sprite_engine.py's SpriteEngine, and
# SpriteEngine.set_background() hard-requires bg.strip_h == STRIP_H (the
# constant imported there from drivers/strip_renderer.py) before it will
# accept the background at all -- a mismatch raises ValueError immediately,
# which is exactly the "background strip_h != 8" failure this constant
# used to cause for every kind-0 asset (this file baked them all at 32).
# MUST match drivers/strip_renderer.py's STRIP_H; can't import it here,
# this tool runs on desktop Python, not MicroPython on the device.
MAIN_STRIP_H = 8

WBITS = 10                    # 1KB decompressor window on-device
MAGIC = b"BBA1"
ALPHA_THRESHOLD = 128         # hard cutout point -- see ffmpeg_to_raw()

# Caps (must match flash_assets.py on-device)
MAX_FRAME_DIM = 96
MAX_FRAMES = 8

NAME_RE = re.compile(
    r"^(bgraw|btnraw|bg|bgm|btn|sprb|spr)_([A-Za-z0-9\-]+)_(\d+)x(\d+)(?:x(\d+))?\.png$"
)

FLAG_RAW = 0x01     # chunks are raw RGB565, no zlib (fast read_strip path)

KINDS = {
    # prefix: (kind, pixfmt, matte, ext, is_sprite, flags)
    "bg":     (0, "rgb565le", "0xFFFFFF", ".bz", False, 0),
    "bgraw":  (0, "rgb565le", "0xFFFFFF", ".bz", False, FLAG_RAW),
    "bgm":    (1, "rgb565be", "0xFFFFFF", ".bz", False, 0),
    "btn":    (1, "rgb565be", "0xFFFFFF", ".bz", False, 0),
    "btnraw": (1, "rgb565be", "0xFFFFFF", ".bz", False, FLAG_RAW),
    "spr":    (2, "rgb565le", "0xFF00FF", ".sz", True, 0),
    "sprb":   (3, "rgb565be", "0xFF00FF", ".sz", True, 0),
}


def png_dimensions(path: Path):
    """Read width/height straight from the PNG IHDR (no dependencies)."""
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError(f"{path.name}: not a valid PNG")
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def ffmpeg_to_raw(png: Path, w: int, h: int, pixfmt: str, matte: str) -> bytes:
    """Flatten PNG onto a matte colour and convert to raw RGB565 bytes.

    Colour-keyed sprites (spr_/sprb_) need every non-key pixel to survive
    RGB565 packing bit-exact, and every "background" pixel to come out
    bit-exact matte -- the on-device compositor (core/sprite_engine.py's
    _blit_key) does a plain != comparison against the key colour, no
    tolerance. A plain `overlay` alpha-BLENDS the source over the matte,
    so any source pixel with partial alpha (anti-aliased art edges, or a
    fill/bucket tool that only clears fully-transparent pixels and leaves
    a ring of low-alpha pixels right at the silhouette) comes out as a
    blended near-matte colour instead of the matte itself -- confirmed on
    real baked sprites as a magenta fringe hugging every character, and
    reproduced+fixed with a synthetic alpha=128 test PNG. Fix: hard-
    threshold alpha to 0/255 BEFORE compositing, so overlay always either
    keeps the source pixel's exact RGB or reveals the exact matte -- never
    a blend of the two, regardless of what alpha the source PNG actually
    has at its edges.

    THIRD, ROOT-CAUSE fringe source, found 2026-09 -- confirmed by baking
    4 sprites from source art that tested 100% opaque (alpha=255
    everywhere) with a pixel-exact matte background (zero blended edge
    pixels, verified by decoding the PNGs directly), yet ~30% of pixels
    in the BAKED output -- not just at edges, scattered across the whole
    frame, including pure-matte background pixels -- differed from a
    plain bit-truncated RGB565 pack of the source, with the largest
    excursions clustered at sharp silhouette edges. That's the signature
    of error-diffusion DITHERING, which ffmpeg's libswscale applies by
    default when narrowing 8-bit/channel RGBA down to 5-6-5 RGB565
    (standard behaviour to reduce banding in photos -- actively harmful
    for a hard colour-key where EVERY matte pixel must survive bit-
    exact). Dithering explains everything the two fixes above don't:
    they only ever touch pixels near an alpha transition, but a
    perfectly flat, fully-opaque matte fill gets its exact colour
    perturbed too.

    First attempted fix was `-sws_dither none` as a global ffmpeg option
    -- re-tested on-device and it did NOT change the output at all
    (byte-identical to the un-fixed bake), meaning that option either
    isn't reaching this conversion's internal swscale context or isn't a
    real global CLI flag for this build (sws_dither is documented as a
    private AVOption of the `scale`/`zscale` filters, not necessarily a
    generic top-level flag -- a mismatch here would silently no-op
    rather than error, and dithering is a deterministic algorithm, so
    "same input, same ignored setting" reproducing byte-identical output
    is exactly what a no-op looks like).

    ACTUAL fix: stop asking ffmpeg to do the bit-depth reduction at all.
    The filter graph now ends at `format=rgba` (8-bit/channel, same
    depth as the source -- nothing for swscale to dither) and this
    function packs RGBA to RGB565 itself in Python (see _pack_rgb565),
    one line of bit-shifting per pixel, fully deterministic by
    construction. This sidesteps the whole "does this ffmpeg flag
    actually take effect" question rather than continuing to chase it.
    The alpha-erosion fix above stays as real, separate protection for
    source art that DOES have genuine antialiased/partial-alpha edges
    (this batch happened not to), but on its own could never have fixed
    a fully-opaque source like these -- there's no alpha edge for it to
    erode."""
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=c={matte}:s={w}x{h}",
        "-i", str(png),
        "-filter_complex",
        f"[1:v]format=rgba,split=2[rgba1][rgba2];"
        f"[rgba1]alphaextract,lut=y='if(gte(val,{ALPHA_THRESHOLD}),255,0)',erosion[hardalpha];"
        f"[rgba2][hardalpha]alphamerge[hardsrc];"
        f"[0:v][hardsrc]overlay=shortest=1:format=auto,format=rgba",
        "-frames:v", "1", "-f", "rawvideo", "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {png.name}:\n"
                           f"{proc.stderr.decode(errors='replace')}")
    rgba = proc.stdout
    expect = w * h * 4
    if len(rgba) != expect:
        raise RuntimeError(
            f"{png.name}: ffmpeg produced {len(rgba)} bytes, expected {expect}")
    return _pack_rgb565(rgba, pixfmt.endswith("be"))


def _pack_rgb565(rgba: bytes, big_endian: bool) -> bytes:
    """Deterministic RGBA8 -> RGB565 pack -- plain bit truncation, no
    dithering possible since there's no rounding decision being made
    (see ffmpeg_to_raw()'s docstring for why ffmpeg itself doesn't do
    this step any more)."""
    n = len(rgba) // 4
    out = bytearray(n * 2)
    for i in range(n):
        r = rgba[i * 4]; g = rgba[i * 4 + 1]; b = rgba[i * 4 + 2]
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        oi = i * 2
        if big_endian:
            out[oi] = (v >> 8) & 0xFF; out[oi + 1] = v & 0xFF
        else:
            out[oi] = v & 0xFF; out[oi + 1] = (v >> 8) & 0xFF
    return bytes(out)


def compress_chunk(data: bytes) -> bytes:
    co = zlib.compressobj(9, zlib.DEFLATED, WBITS)
    return co.compress(data) + co.flush()


def write_asset(out: Path, kind: int, strip_h: int, w: int, h: int,
                frames: int, chunks: list, flags: int = 0):
    n = len(chunks)
    table = bytearray()
    offset = 0
    for c in chunks:
        table += struct.pack("<II", offset, len(c))
        offset += len(c)
    header = MAGIC + struct.pack("<BBHHBBHH", kind, strip_h, w, h,
                                 frames, flags, n, 0)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        f.write(header)
        f.write(table)
        for c in chunks:
            f.write(c)
    return len(header) + len(table) + offset


def bake_background(raw: bytes, w: int, h: int, store_raw: bool, chunk_h: int):
    """Chunk into chunk_h-row strips; last strip may be partial.
    store_raw=True keeps chunks as raw RGB565 (no zlib) for the fast
    on-device read_strip path -- ~10x cheaper to load, ~5-10x more flash.
    Use for HOT backgrounds that sprites animate over."""
    chunks = []
    row_bytes = w * 2
    y = 0
    while y < h:
        rows = min(chunk_h, h - y)
        chunk = raw[y * row_bytes:(y + rows) * row_bytes]
        chunks.append(chunk if store_raw else compress_chunk(chunk))
        y += rows
    return chunks


def bake_sprite(raw: bytes, sheet_w: int, fw: int, fh: int, frames: int):
    """Slice horizontal sheet into frames; each frame = one chunk."""
    chunks = []
    row_bytes = sheet_w * 2
    frame_row = fw * 2
    for f in range(frames):
        x0 = f * frame_row
        frame = bytearray(fw * fh * 2)
        for row in range(fh):
            src = row * row_bytes + x0
            frame[row * frame_row:(row + 1) * frame_row] = \
                raw[src:src + frame_row]
        chunks.append(compress_chunk(bytes(frame)))
    return chunks


def bake_file(png: Path, art_root: Path, build_root: Path, force: bool):
    m = NAME_RE.match(png.name)
    if not m:
        return None  # ignore non-conforming files
    prefix, name, w_s, h_s, frames_s = m.groups()
    kind, pixfmt, matte, ext, is_sprite, flags = KINDS[prefix]
    w, h = int(w_s), int(h_s)
    frames = int(frames_s) if frames_s else 1

    rel = png.relative_to(art_root)
    out = (build_root / rel).with_suffix(ext)

    if not force and out.exists() and out.stat().st_mtime >= png.stat().st_mtime:
        return ("skip", rel, out.stat().st_size)

    if is_sprite:
        if not frames_s:
            raise ValueError(f"{png.name}: sprite needs WxHxFRAMES in name")
        if w > MAX_FRAME_DIM or h > MAX_FRAME_DIM:
            raise ValueError(
                f"{png.name}: frame {w}x{h} exceeds {MAX_FRAME_DIM}px cap")
        if frames > MAX_FRAMES:
            raise ValueError(f"{png.name}: {frames} frames exceeds "
                             f"{MAX_FRAMES}-frame cap")
        sheet_w, sheet_h = w * frames, h
    else:
        if frames_s:
            raise ValueError(f"{png.name}: backgrounds must not have a "
                             f"frame count in the name")
        sheet_w, sheet_h = w, h

    pw, ph = png_dimensions(png)
    if (pw, ph) != (sheet_w, sheet_h):
        raise ValueError(f"{png.name}: PNG is {pw}x{ph}, filename says "
                         f"{sheet_w}x{sheet_h}")

    raw = ffmpeg_to_raw(png, sheet_w, sheet_h, pixfmt, matte)

    if is_sprite:
        chunks = bake_sprite(raw, sheet_w, w, h, frames)
        size = write_asset(out, kind, h, w, h, frames, chunks, flags)
    else:
        chunk_h = MAIN_STRIP_H if kind == 0 else BG_CHUNK_H
        chunks = bake_background(raw, w, h, bool(flags & FLAG_RAW), chunk_h)
        size = write_asset(out, kind, chunk_h, w, h, 1, chunks, flags)

    ratio = size / len(raw)
    return ("bake", rel, size, len(raw), ratio, out)


def main():
    ap = argparse.ArgumentParser(description="Button Blasters asset baker")
    ap.add_argument("art_dir", type=Path)
    ap.add_argument("build_dir", type=Path)
    ap.add_argument("--budget", type=int, default=2560,
                    help="flash budget in KB (default 2560)")
    ap.add_argument("--force", action="store_true",
                    help="re-bake even if output is up to date")
    args = ap.parse_args()

    pngs = sorted(args.art_dir.rglob("*.png"))
    if not pngs:
        print(f"No PNGs found under {args.art_dir}")
        return 1

    total = 0
    baked = skipped = ignored = 0
    errors = []
    for png in pngs:
        print(f"png {png}")
        try:
            result = bake_file(png, args.art_dir, args.build_dir, args.force)
        except (ValueError, RuntimeError) as e:
            errors.append(str(e))
            continue
        if result is None:
            ignored += 1
            continue
        if result[0] == "skip":
            _, rel, size = result
            total += size
            skipped += 1
            print(f"  = {rel}  ({size/1024:.1f} KB, up to date)")
        else:
            _, rel, size, raw_len, ratio, out = result
            total += size
            baked += 1
            print(f"  + {rel} -> {out.name}  "
                  f"{raw_len/1024:.1f} KB raw -> {size/1024:.1f} KB "
                  f"({ratio*100:.0f}%)")

    print()
    print(f"Baked {baked}, up-to-date {skipped}, ignored {ignored}")
    budget = args.budget * 1024
    pct = total / budget * 100
    print(f"Total build size: {total/1024:.1f} KB "
          f"of {args.budget} KB budget ({pct:.0f}%)")
    if total > budget:
        print("WARNING: over flash budget!")
    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  ! {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
