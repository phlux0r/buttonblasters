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

Each background chunk is one 32-row strip (last strip may be shorter).
Each sprite chunk is one whole frame.
"""

import argparse
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

STRIP_H = 32
WBITS = 10                    # 1KB decompressor window on-device
MAGIC = b"BBA1"

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
    """Flatten PNG onto a matte colour and convert to raw RGB565 bytes."""
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=c={matte}:s={w}x{h}",
        "-i", str(png),
        "-filter_complex",
        f"[0:v][1:v]overlay=shortest=1:format=auto,format={pixfmt}",
        "-frames:v", "1", "-f", "rawvideo", "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {png.name}:\n"
                           f"{proc.stderr.decode(errors='replace')}")
    raw = proc.stdout
    expect = w * h * 2
    if len(raw) != expect:
        raise RuntimeError(
            f"{png.name}: ffmpeg produced {len(raw)} bytes, expected {expect}")
    return raw


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


def bake_background(raw: bytes, w: int, h: int, store_raw: bool):
    """Chunk into STRIP_H-row strips; last strip may be partial.
    store_raw=True keeps chunks as raw RGB565 (no zlib) for the fast
    on-device read_strip path -- ~10x cheaper to load, ~5-10x more flash.
    Use for HOT backgrounds that sprites animate over."""
    chunks = []
    row_bytes = w * 2
    y = 0
    while y < h:
        rows = min(STRIP_H, h - y)
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
        chunks = bake_background(raw, w, h, bool(flags & FLAG_RAW))
        size = write_asset(out, kind, STRIP_H, w, h, 1, chunks, flags)

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
