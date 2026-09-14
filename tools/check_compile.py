#!/usr/bin/env python3
"""
check_compile.py — compile every source file the way the device will.

Firmware modules (main.py, config.py, sdcard.py, rgb666_viper.py, drivers/,
core/, games/, tests/) are cross-compiled with mpy-cross for the RP2350's
native arch, which catches syntax errors and MicroPython-specific parse
problems (viper/PIO decorators, const(), etc.) that CPython's own compiler
would miss or flag wrongly. Desktop scripts under tools/ are byte-compiled
with CPython instead, since they never run on the Pico.

Nothing is written next to the sources — output goes to a temp dir.

Usage:
  python3 tools/check_compile.py            # exit 1 if anything fails
  python3 tools/check_compile.py -v         # list every file checked

Requires mpy-cross (pip install -r tools/requirements.txt). Run by CI on
every push (.github/workflows/ci.yml); run it locally before deploying.
"""

import argparse
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MPY_ARCH = "armv7emsp"   # RP2350 (Cortex-M33) — keep in step with deploy.py

FIRMWARE = ["main.py", "config.py", "sdcard.py", "rgb666_viper.py",
            "drivers", "core", "games", "tests"]
DESKTOP  = ["tools"]


def _py_files(roots):
    for r in roots:
        p = REPO / r
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*.py")):
                if "__pycache__" not in f.parts:
                    yield f


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--arch", default=MPY_ARCH)
    opts = ap.parse_args()

    mpy_cross = shutil.which("mpy-cross")
    if mpy_cross is None:
        sys.exit("mpy-cross not found — pip install -r tools/requirements.txt")

    failures = []
    checked = 0
    with tempfile.TemporaryDirectory() as tmp:
        for f in _py_files(FIRMWARE):
            out = Path(tmp) / (f.relative_to(REPO).as_posix().replace("/", "_") + ".mpy")
            r = subprocess.run([mpy_cross, "-march=" + opts.arch, "-o", str(out), str(f)],
                               capture_output=True, text=True)
            checked += 1
            if r.returncode != 0:
                failures.append((f, (r.stderr or r.stdout).strip()))
            elif opts.verbose:
                print(f"  ok  {f.relative_to(REPO)}")

    for f in _py_files(DESKTOP):
        checked += 1
        try:
            py_compile.compile(str(f), cfile=None, doraise=True)
            if opts.verbose:
                print(f"  ok  {f.relative_to(REPO)}  (cpython)")
        except py_compile.PyCompileError as e:
            failures.append((f, str(e).strip()))

    for f, msg in failures:
        print(f"FAIL {f.relative_to(REPO)}\n     {msg}")
    print(f"{checked} files checked, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
