# tools/device_du.py — run ON THE PICO (paste into the REPL, or
# `mpremote run tools/device_du.py`) to see actual on-device usage per
# top-level folder/file, on BOTH the internal flash (/) and the SD card
# (/sd, if mounted). Repo file sizes are NOT a reliable proxy for what's
# really on the device -- only this tells you the truth. In particular,
# tools/deploy.py's SD push is purely additive (never deletes anything
# already on the card), so a renamed or resized asset leaves every OLD
# name behind forever -- this is the tool that actually shows that.
#
# Usage: mpremote run tools/device_du.py
#     or mpremote connect <port> exec "$(cat tools/device_du.py)"

import os


def _is_dir(path):
    try:
        os.stat(path + "/.")
        return True
    except OSError:
        return False


def _size(path):
    if not _is_dir(path):
        try:
            return os.stat(path)[6]
        except OSError:
            return 0
    total = 0
    try:
        names = os.listdir(path)
    except OSError:
        return 0
    for name in names:
        total += _size(path + "/" + name)
    return total


def _report(root, skip=()):
    print("=== %s ===" % root)
    try:
        stat = os.statvfs(root)
    except OSError as e:
        print("  not mounted:", e)
        return
    free = stat[0] * stat[3]
    total = stat[0] * stat[2]
    print("Filesystem: %d bytes used, %d bytes free (%.2f MB / %.2f MB)"
          % (total - free, free, (total - free) / 1024 / 1024, free / 1024 / 1024))
    print()

    prefix = root if root.endswith("/") else root + "/"
    rows = []
    for name in sorted(os.listdir(root)):
        if name in skip:
            continue
        rows.append((_size(prefix + name), name))
    rows.sort(reverse=True)
    print("Top-level:")
    for size, name in rows:
        print("  %8d  %s" % (size, name))

    assets_dir = prefix + "assets"
    if _is_dir(assets_dir):
        print()
        print("assets/ breakdown:")
        rows = []
        for name in sorted(os.listdir(assets_dir)):
            rows.append((_size(assets_dir + "/" + name), name))
        rows.sort(reverse=True)
        for size, name in rows:
            print("  %8d  assets/%s" % (size, name))


def main():
    _report("/", skip=("boot.py", "webrepl_cfg.py"))
    print()
    _report("/sd")


main()
