#!/usr/bin/env python3
"""
deploy.py — stage and install Button Blasters onto the Pico 2 W.

The repo layout mirrors the device layout directly as of 2026-09
(assets/static/<game>/ holds each game's Tier A sprites pre-sorted, same
as it appears on littlefs) -- this script no longer sorts sprites out of
a flat per-game folder by filename prefix, it just mirrors what's
already sorted in the repo. Only the SD-bound Tier B backgrounds still
live in a flat per-game folder (assets/<game>/), since those aren't
part of the on-device littlefs layout at all until game_cache installs
them at game load:

  repo                          device (littlefs)
  ----                          -----------------
  main.py, config.py,           /            (main.py always stays .py)
  sdcard.py, rgb666_viper.py
  drivers/, core/, games/       /drivers, /core, /games
  assets/menu/                  /assets/menu      (Tier A — permanent)
  assets/sys/                   /assets/sys       (Tier A — permanent)
  assets/static/                /assets/static     (Tier A — permanent,
                                                     mirrored as-is)

  repo                          SD card
  ----                          -------
  assets/match/bgm_*.bz         /sd/assets/match  (Tier B — game_cache
  (everything else under a      installs to /assets/<id> at game load)
   per-game assets/<id>/ folder,
   i.e. NOT menu/sys/static)

Never deployed: tests/, documents/, tools/, *.md — they only waste flash.

Audio: WAV clips are not in the repo. Shared clips go on the SD card at
/sd/audio/{sfx,voice,music}/, or to littlefs /assets/audio/ for bus-free
playback; per-game clips go to /sd/assets/<game_id>/audio/{sfx,voice}/ so
game_cache installs them to flash at game load (see drivers/audio.py).

Usage:
  python3 tools/deploy.py                    # stage + install firmware+assets
  python3 tools/deploy.py --mpy              # cross-compile modules to .mpy
  python3 tools/deploy.py --dry-run          # stage into build/ only
  python3 tools/deploy.py --port /dev/tty.usbmodem1101
  python3 tools/deploy.py --sd               # also push SD payload via the
                                             # mounted /sd (firmware must have
                                             # mounted the card this session)

Requires: mpremote (pip install mpremote). --mpy also needs mpy-cross
(pip install mpy-cross) — RP2350 native arch is armv7emsp.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "build"
STAGE_FW = BUILD / "littlefs"
STAGE_SD = BUILD / "sd"

MPY_ARCH = "armv7emsp"   # RP2350 (Cortex-M33)

# Top-level modules; main.py is always deployed as .py (boot entry point).
ROOT_FILES = ["main.py", "config.py", "sdcard.py", "rgb666_viper.py"]
PACKAGES   = ["drivers", "core", "games"]


def stage():
    if BUILD.exists():
        shutil.rmtree(BUILD)
    STAGE_FW.mkdir(parents=True)
    STAGE_SD.mkdir(parents=True)

    for name in ROOT_FILES:
        shutil.copy2(REPO / name, STAGE_FW / name)
    for pkg in PACKAGES:
        shutil.copytree(REPO / pkg, STAGE_FW / pkg,
                        ignore=shutil.ignore_patterns("__pycache__"))

    # Tier A assets — permanent littlefs residents. assets/static/<id>/ is
    # already pre-sorted in the repo (sprb_*/spr_* sprites only, one
    # subfolder per game) -- mirrored wholesale, no filename sniffing
    # needed here any more; that used to happen in this script, now it
    # happens once, by hand, when art is baked (see tools/bake_assets.py).
    shutil.copytree(REPO / "assets" / "menu", STAGE_FW / "assets" / "menu")
    shutil.copytree(REPO / "assets" / "sys",  STAGE_FW / "assets" / "sys")
    static_src = REPO / "assets" / "static"
    if static_src.is_dir():
        shutil.copytree(static_src, STAGE_FW / "assets" / "static")

    # Everything remaining under assets/ (i.e. every per-game folder that
    # isn't menu/sys/static) holds ONLY Tier B backgrounds now -- staged
    # wholesale for the SD card, installed to littlefs by game_cache at
    # game load and evicted at unload (see core/game_cache.py).
    SPRITE_PREFIXES = ("sprb_", "spr_")
    SKIP_DIRS = {"menu", "sys", "static"}
    for game_dir in sorted((REPO / "assets").iterdir()):
        if not game_dir.is_dir() or game_dir.name in SKIP_DIRS:
            continue
        game_id = game_dir.name
        files = sorted(f for f in game_dir.iterdir() if f.is_file())
        if not files:
            continue
        sd_dir = STAGE_SD / "assets" / game_id
        sd_dir.mkdir(parents=True)
        for f in files:
            if f.name.startswith(SPRITE_PREFIXES):
                print(f"[deploy] warning: {f} looks like a Tier A sprite "
                     f"but sits in assets/{game_id}/, not "
                     f"assets/static/{game_id}/ -- staging it to the SD "
                     f"card as a background anyway, but this is probably "
                     f"a misplaced file, not what you want")
            shutil.copy2(f, sd_dir / f.name)


def cross_compile():
    """Replace every staged .py except main.py with a native-arch .mpy —
    roughly halves code flash and cuts import-time RAM."""
    mpy_cross = shutil.which("mpy-cross")
    if mpy_cross is None:
        sys.exit("mpy-cross not found — pip install mpy-cross, "
                 "or rerun without --mpy")
    for py in sorted(STAGE_FW.rglob("*.py")):
        if py.name == "main.py" and py.parent == STAGE_FW:
            continue
        subprocess.run([mpy_cross, "-march=" + MPY_ARCH, str(py)], check=True)
        py.unlink()


def mpremote(port, *args):
    cmd = ["mpremote", "connect", port] + list(args)
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


def install(port, push_sd):
    for child in sorted(STAGE_FW.iterdir()):
        mpremote(port, "cp", "-r", str(child), ":")
    if push_sd:
        # Requires /sd mounted on the device (the firmware mounts it at
        # boot when the card is present). If this fails, copy build/sd/*
        # onto the card with a desktop card reader instead.
        mpremote(port, "cp", "-r", str(STAGE_SD / "assets"), ":/sd/")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--port", default="auto",
                    help="mpremote connect target (default: auto)")
    ap.add_argument("--mpy", action="store_true",
                    help="cross-compile modules to .mpy (needs mpy-cross)")
    ap.add_argument("--sd", action="store_true",
                    help="also push the SD payload via the mounted /sd")
    ap.add_argument("--dry-run", action="store_true",
                    help="stage into build/ without touching the device")
    opts = ap.parse_args()

    stage()
    if opts.mpy:
        cross_compile()
    fw_kb = sum(f.stat().st_size for f in STAGE_FW.rglob("*") if f.is_file()) // 1024
    sd_kb = sum(f.stat().st_size for f in STAGE_SD.rglob("*") if f.is_file()) // 1024
    print(f"staged: littlefs payload {fw_kb}KB, SD payload {sd_kb}KB")

    if opts.dry_run:
        print(f"dry run — inspect {BUILD}")
        return
    install(opts.port, opts.sd)
    print("done — reset the Pico to boot the new firmware")


if __name__ == "__main__":
    main()
