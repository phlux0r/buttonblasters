#!/usr/bin/env python3
"""
inspect_asset.py — read a baked .bz/.sz asset's header without decompressing
pixel data, and sanity-check it against what this codebase's loaders expect.

Runs on a desktop Python 3 (no MicroPython needed) — check newly baked
files BEFORE copying them to the SD card / device. Only reads the first
16 + n_chunks*8 bytes (the header + chunk table, per drivers/flash_assets.py's
_read_header), never touches pixel data.

Usage:
  python3 tools/inspect_asset.py path/to/bgm_intro-shape_480x320.bz [more files...]

Exit code is nonzero if any file fails a sanity check, so this is usable
in a pre-flight script too.
"""

import struct
import sys
from pathlib import Path

MAGIC = b"BBA1"
HEADER_LEN = 16

KIND_NAMES = {0: "BG_LE", 1: "BG_BE", 2: "SPR_LE", 3: "SPR_BE"}
FLAG_RAW = 0x01

# filename prefix -> expected kind, matching the convention used throughout
# this repo (see documents/HARDWARE_NOTES.md, games/*/game.py headers).
PREFIX_EXPECTATIONS = {
    "bgm_": 1,    # BE background — direct blit_rgb565 path (Match's board/intro/result)
    "bg_":  0,    # LE background — core/sprite_engine.py path (Star Bonk's board)
    "sprb_": 3,   # BE sprite — direct blit path (icons, button legends)
    "spr_": 2,    # LE sprite — sprite_engine, magenta-keyed
    "btn_": 1,    # BE background — menu nav/back/replay tiles (core/menu.py,
                  # games/*/game.py's BACK_TILE_PATH/REPLAY_TILE_PATH)
}

# Single-strip allocation from the 96KB flash_assets arena (see
# drivers/flash_assets.py SPRITE_BUDGET and core/display_manager.py's
# paint_main_bg/paint_btn_bg, which do arena.alloc(w * strip_h * 2) for
# ONE strip at a time). A strip that alone exceeds this is the classic
# "re-baked with a different/default strip_h" failure — it makes
# paint_main_bg/paint_btn_bg raise AssetError, silently caught and
# reported only via the "[display] ... paint failed" print, which reads
# as "the Get Ready fallback showed up instead of the real art."
ARENA_BUDGET = 96 * 1024


def inspect(path: Path) -> bool:
    ok = True
    data = path.read_bytes()
    print(f"\n=== {path.name} ({len(data)} bytes) ===")

    if len(data) < HEADER_LEN or data[0:4] != MAGIC:
        print("  FAIL: bad magic (not a BBA1 asset, or truncated/corrupt file)")
        return False

    kind, strip_h, w, h, frames, flags, n_chunks, _reserved = \
        struct.unpack_from("<BBHHBBHH", data, 4)

    kind_name = KIND_NAMES.get(kind, f"UNKNOWN({kind})")
    raw = bool(flags & FLAG_RAW)
    print(f"  kind={kind} ({kind_name})   {w}x{h}   frames={frames}")
    print(f"  strip_h={strip_h}   n_chunks={n_chunks}   raw_chunks={raw}")

    table_end = HEADER_LEN + n_chunks * 8
    if len(data) < table_end:
        print(f"  FAIL: chunk table truncated (need {table_end} bytes, have {len(data)})")
        return False

    # Chunk table sanity: offsets/lengths should describe data that fits
    # inside the file and (for raw chunks) match the strip/frame size.
    offsets = []
    lengths = []
    for i in range(n_chunks):
        off, ln = struct.unpack_from("<II", data, table_end - n_chunks * 8 + i * 8)
        offsets.append(off)
        lengths.append(ln)
    max_end = max((table_end + o + l for o, l in zip(offsets, lengths)), default=table_end)
    if max_end > len(data):
        print(f"  FAIL: a chunk's data runs past end of file "
             f"(needs byte {max_end}, file is {len(data)})")
        ok = False

    # Prefix-based expectation check.
    expected_kind = None
    for prefix, exp in PREFIX_EXPECTATIONS.items():
        if path.name.startswith(prefix):
            expected_kind = exp
            matched_prefix = prefix
            break
    if expected_kind is not None:
        if kind != expected_kind:
            print(f"  FAIL: filename prefix '{matched_prefix}' implies kind={expected_kind} "
                 f"({KIND_NAMES[expected_kind]}), but header says kind={kind} ({kind_name})")
            print(f"        This is exactly the failure mode that makes paint_main_bg/")
            print(f"        paint_btn_bg raise 'must be BE, got LE' (or vice versa) and")
            print(f"        silently fall back to a text splash.")
            ok = False
    else:
        print(f"  NOTE: filename doesn't match a known prefix "
             f"({', '.join(PREFIX_EXPECTATIONS)}) — skipping kind check")

    # Dimension check against filename-encoded WxH (repo convention).
    import re
    m = re.search(r"_(\d+)x(\d+)", path.stem)
    if m:
        fw, fh = int(m.group(1)), int(m.group(2))
        if (fw, fh) != (w, h):
            print(f"  FAIL: filename says {fw}x{fh} but header says {w}x{h}")
            ok = False

    # Single-strip arena budget check (only meaningful for backgrounds,
    # which paint_main_bg/paint_btn_bg stream strip-by-strip).
    if kind in (0, 1):
        strip_bytes = w * strip_h * 2
        if strip_bytes > ARENA_BUDGET:
            print(f"  FAIL: one strip is {strip_bytes} bytes ({strip_bytes/1024:.1f}KB), "
                 f"exceeds the 96KB flash_assets arena on its own.")
            print(f"        strip_h={strip_h} is too tall for a {w}px-wide background —")
            print(f"        re-bake with a smaller strip_h (32 is the convention used")
            print(f"        elsewhere in this repo; see core/sprite_engine.py STRIP_H).")
            ok = False
        else:
            print(f"  strip size: {strip_bytes} bytes ({strip_bytes/1024:.1f}KB) — "
                 f"fits the 96KB arena OK")

    if kind in (2, 3) and (w > 96 or h > 96):
        print(f"  FAIL: sprite is {w}x{h}, exceeds flash_assets.MAX_FRAME_DIM (96)")
        ok = False
    if kind in (2, 3) and frames > 8:
        print(f"  FAIL: {frames} frames, exceeds flash_assets.MAX_FRAMES (8)")
        ok = False

    print(f"  {'OK' if ok else 'FAILED — see above'}")
    return ok


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    all_ok = True
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"\n=== {arg} ===\n  FAIL: file not found")
            all_ok = False
            continue
        if not inspect(p):
            all_ok = False
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
