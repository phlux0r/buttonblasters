# core/settings.py — Button Blasters
# Volume settings screen. Entered via the gear icon top-left of the menu's
# main card (see core/menu.py's _SETTINGS_ICON), exited via BACK. Not a
# "game" — self-contained, doesn't go through the kernel's load/run/unload
# cycle, so Menu owns entering and returning from it directly.
#
# Adjust with BTN-1 (-) / BTN-3 (+) — same physical buttons as PREV/NEXT
# in the menu, so the mapping is already familiar rather than introducing
# a new gesture.

import json
import config
from core.display_manager import display, WHITE, YELLOW, BLACK, DARK, GREEN, rgb
from drivers.audio import audio
from drivers.buttons import buttons
from drivers.assets import assets
from drivers.spi_bus import spi_bus

_SETTINGS_PATH = "/sd/settings.json"
_VOLUME_STEP   = 0.1


async def load_volume() -> float:
    """Read saved volume from SD at boot. Defaults to 1.0 (unchanged
    behaviour) if there's no SD card or no saved settings yet — same
    graceful-fallback pattern as AppKernel._load_scores()."""
    if not assets.sd_available:
        return 1.0
    try:
        async with spi_bus.raw(config.SPI_FREQ_SD_DATA):
            with open(_SETTINGS_PATH, "r") as f:
                data = f.read()
        vol = json.loads(data).get("volume", 1.0)
        return max(0.0, min(1.0, float(vol)))
    except (OSError, ValueError):
        return 1.0


async def _save_volume(vol: float):
    if not assets.sd_available:
        return
    try:
        async with spi_bus.raw(config.SPI_FREQ_SD_DATA):
            with open(_SETTINGS_PATH, "w") as f:
                f.write(json.dumps({"volume": vol}))
    except OSError as e:
        print("[settings] volume save failed:", e)


class SettingsScreen:

    async def run(self):
        buttons.clear()
        await display.fill_btn(1, DARK)
        await display.text_btn(1, "-", config.BTN_W // 2 - 8,
                               config.BTN_H // 2 - 8, WHITE, DARK, scale=2)
        await display.fill_btn(3, DARK)
        await display.text_btn(3, "+", config.BTN_W // 2 - 8,
                               config.BTN_H // 2 - 8, WHITE, DARK, scale=2)
        await display.fill_btn(0, BLACK)
        await display.fill_btn(2, BLACK)
        await self._render()

        while True:
            action, _data = await buttons.get_menu_event()
            if action == "back":
                return
            elif action == "prev":
                await self._adjust(-_VOLUME_STEP)
            elif action == "next":
                await self._adjust(_VOLUME_STEP)
            # select/tap/swipe: no-op here, this screen is volume-only

    async def _adjust(self, delta: float):
        vol = max(0.0, min(1.0, audio.volume + delta))
        audio.set_volume(vol)
        await _save_volume(vol)
        # wait=True: same SPI0-bus-safety rule as menu.py's scroll sound —
        # the save above may have been a bracketed SD write, and this sfx
        # can resolve via an SD-backed path too, so let it settle before
        # _render() below starts its own display writes.
        await audio.play_sfx("menu_move.wav", wait=True)
        await self._render()

    async def _render(self):
        vol = audio.volume
        await display.fill_main(BLACK)
        cx = config.MAIN_W // 2

        title = "VOLUME"
        await display.text_main(title, cx - len(title) * 12,
                                60, WHITE, BLACK, scale=3)

        pct     = int(round(vol * 100))
        pct_str = f"{pct}%"
        await display.text_main(pct_str, cx - len(pct_str) * 16,
                                140, YELLOW, BLACK, scale=4)

        bar_w = 320
        bar_x = cx - bar_w // 2
        col   = GREEN if pct > 30 else YELLOW if pct > 0 else rgb(255, 60, 0)
        await display.draw_progress_bar(vol, x=bar_x, y=200,
                                        w=bar_w, h=20, color=col)

        hint = "- / + on side buttons - BACK to exit"
        await display.text_main(hint, max(4, cx - len(hint) * 4),
                                260, rgb(140, 140, 140), BLACK, scale=1)


settings = SettingsScreen()
