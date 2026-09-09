# tools/mount_sd.py — run ON THE PICO (`mpremote run tools/mount_sd.py`)
# to guarantee /sd is the REAL physical SD card before deploy.py pushes
# Tier B assets to it.
#
# Why this exists: tools/deploy.py's SD push assumes /sd is already
# mounted "because the firmware mounts it at boot" -- but that's only
# true if main.py's own asyncio boot sequence actually ran and reached
# its SD-mount step (core/kernel.py step 7) BEFORE deploy.py's mpremote
# session took over the REPL. If it didn't (device freshly reset/flashed,
# or interrupted before getting that far), /sd is just an ordinary,
# empty-to-start directory on the tiny INTERNAL flash -- os.mount() was
# never called, so nothing distinguishes "/sd" from any other folder
# name. Every subsequent `cp -r ... :/sd/` then silently fills up the
# internal flash instead of the card: confirmed on hardware as "No space
# left on device" mid-copy despite 32GB genuinely free on the physical
# card, because the data never reached it.
#
# This script: detects that fake-mount case (statvfs("/sd") identical to
# statvfs("/") means it's the same underlying filesystem, not a separate
# one), deletes whatever stale data accumulated in it, then mounts the
# real card the same way drivers/assets.py's mount_sd() does at normal
# boot (reused directly, not reimplemented here).
#
# Usage: mpremote connect <port> run tools/mount_sd.py
# Prints SD_MOUNT_OK or SD_MOUNT_FAILED as the last line -- deploy.py
# checks for that exact string.
#
# IMPORTANT: deploy.py does NOT run this as a separate `mpremote` command
# followed by a separate `cp -r ... :/sd/` -- each `mpremote connect`
# invocation is its own subprocess that reconnects from scratch, and
# disconnecting commonly leaves the board soft-reset (so its normal
# firmware resumes running) rather than sitting in the mounted state this
# script just set up. A soft reset unmounts /sd immediately, and the
# freshly-rebooted app hasn't reached its OWN SD-mount step (deep in
# AppKernel.init()) by the time the next connect+cp arrives -- so the
# push silently falls back to the internal-flash fake-mount all over
# again, confirmed on hardware. deploy.py instead appends this file's own
# per-game _rm_if_exists() cleanup calls after this source and chains the
# result with `+ cp -r ... :/sd/` in ONE mpremote invocation -- one
# continuous session, so the mount can't be lost in between.

import os


def _is_dir(path):
    try:
        os.stat(path + "/.")
        return True
    except OSError:
        return False


def _rm(path):
    if not _is_dir(path):
        os.remove(path)
        return
    for name in os.listdir(path):
        _rm(path + "/" + name)
    os.rmdir(path)


def _rm_if_exists(path):
    """Best-effort recursive delete -- a path that doesn't exist is fine
    to skip (a first-ever deploy, or a game folder never pushed before).
    Used by deploy.py's generated per-game cleanup, appended after this
    file's own source (see deploy.py's install()) so the whole mount +
    clean + copy sequence runs as ONE mpremote session -- no disconnect,
    so no chance of the mount getting lost in between (see module note)."""
    try:
        _rm(path)
    except OSError:
        pass


def _real_mount(path):
    """True if `path` is its own distinct filesystem. Same statvfs()
    tuple as '/' means it's just a plain directory on internal flash,
    never actually mounted."""
    if not _is_dir(path):
        return False
    return os.statvfs(path) != os.statvfs("/")


if _is_dir("/sd") and not _real_mount("/sd"):
    print("[mount_sd] /sd is a plain internal-flash directory, not a real "
          "mount -- removing stale data from an earlier fake-mounted push")
    _rm("/sd")

if _real_mount("/sd"):
    print("[mount_sd] /sd already mounted")
    print("SD_MOUNT_OK")
else:
    from drivers.assets import assets
    ok = assets.mount_sd()
    print("SD_MOUNT_OK" if ok else "SD_MOUNT_FAILED")
