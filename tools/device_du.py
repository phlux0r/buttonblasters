# tools/device_du.py — run ON THE PICO (paste into the REPL, or
# `mpremote run tools/device_du.py`) to see actual on-device flash usage
# per top-level folder/file. Repo file sizes are NOT a reliable proxy for
# what's really on the device -- only this tells you the truth.
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


def main():
    stat = os.statvfs('/')
    free = stat[0] * stat[3]
    total = stat[0] * stat[2]
    print("Filesystem: %d bytes used, %d bytes free (%.2f MB / %.2f MB)"
          % (total - free, free, (total - free) / 1024 / 1024, free / 1024 / 1024))
    print()

    rows = []
    for name in sorted(os.listdir("/")):
        if name in ("boot.py", "webrepl_cfg.py"):
            continue
        rows.append((_size("/" + name), name))
    rows.sort(reverse=True)
    print("Top-level:")
    for size, name in rows:
        print("  %8d  %s" % (size, name))

    if _is_dir("/assets"):
        print()
        print("assets/ breakdown:")
        rows = []
        for name in sorted(os.listdir("/assets")):
            rows.append((_size("/assets/" + name), name))
        rows.sort(reverse=True)
        for size, name in rows:
            print("  %8d  assets/%s" % (size, name))


main()
