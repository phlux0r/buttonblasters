# core/kernel.py — Button Blasters
# AppKernel — central coordinator.
#
# Boot sequence:
#   1. All displays init (SPI bus, ILI9488 + 4× ST7789)
#   2. Touch controller (I2C — independent of SPI)
#   3. SD card mount (deferred — graceful if not available)
#   4. Asset index build (skipped if no SD)
#   5. Persistent scores load (skipped if no SD)
#   6. LED startup animation (skipped if LEDs not wired)
#   7. Startup sound (skipped if audio not wired)
#   8. Menu build + hand-off to asyncio event loop

import asyncio
import json
import time

from core.display_manager import display, rgb, BLACK
from core.menu import Menu
from core.game_base import GameResult
from games.registry import REGISTRY
from drivers.buttons import buttons
from drivers.touch import touch
from drivers.audio import audio
from drivers.leds import leds
from drivers.haptic import haptic
from drivers.assets import assets
import config

_SCORES_PATH = "/sd/scores.json"


class AppKernel:

    def __init__(self):
        self._menu       = None
        self._scores     = {}
        self._last_input = time.ticks_ms()
        self._dimmed     = False

    # ── Boot sequence ────────────────────────────────────────────

    async def init(self):
        print("[kernel] boot start")

        # 1. Displays — blocking, SPI bus claimed exclusively
        display.init_all()
        await display.show_splash("BUTTON", "BLASTERS",
                                  bg_color=rgb(20, 10, 60))

        # 2. Touch controller
        try:
            touch.init_blocking()
            buttons.attach_touch(touch)
            print("[kernel] touch ready")
        except Exception as e:
            print(f"[kernel] touch init failed (continuing): {e}")

        # 3. SD card mount (deferred — non-fatal)
        sd_ok = assets.mount_sd()
        if sd_ok:
            assets.build_index()
            self._load_scores()
        else:
            await display.show_no_sd_warning()
            await asyncio.sleep_ms(2000)
            # Continue without SD — games with no assets still work

        # 4. LEDs startup (skipped if not wired)
        if leds.ready:
            leds.start_effect(leds.chase(80, 40, 255))
            await asyncio.sleep_ms(800)
            leds.off()
        else:
            await asyncio.sleep_ms(200)

        # 5. Startup sound (skipped if not wired)
        await audio.play_sfx("startup.wav")

        # 6. Build menu
        self._menu = Menu(REGISTRY)
        self._menu._scores = {
            gid: d.get("score", 0)
            for gid, d in self._scores.items()
        }
        self._menu._stars = {
            gid: d.get("stars", 0)
            for gid, d in self._scores.items()
        }

        print(f"[kernel] boot complete — {len(REGISTRY)} games registered")

    # ── Main event loop ──────────────────────────────────────────

    async def run(self):
        asyncio.create_task(buttons.run())
        asyncio.create_task(buttons.run_touch())
        asyncio.create_task(self._idle_watchdog())

        while True:
            # ── Menu ─────────────────────────────────────────
            game_cls = await self._menu.run()
            self._touch()

            # ── Instantiate + transition ─────────────────────
            game = game_cls(display, audio, leds, buttons, assets)
            await self._transition_to_game(game)

            # ── Load assets ──────────────────────────────────
            print(f"[kernel] loading {game.GAME_ID}")
            if leds.ready:
                leds.start_effect(leds.chase(100, 200, 100))
            await game.load()
            leds.off()

            # ── Play ─────────────────────────────────────────
            print(f"[kernel] running {game.GAME_ID}")
            try:
                result = await game.run()
            except Exception as e:
                print(f"[kernel] game crashed: {e}")
                result = GameResult(score=0, completed=False)

            self._touch()

            # ── Save + feedback ──────────────────────────────
            self._save_result(game.GAME_ID, result)
            self._menu.update_result(game.GAME_ID,
                                     result.score, result.stars)

            if result.completed:
                await self._game_complete_sequence(result)

            # ── Unload ───────────────────────────────────────
            await game.unload()
            print(f"[kernel] unloaded {game.GAME_ID}")

    # ── Transitions ──────────────────────────────────────────────

    async def _transition_to_game(self, game):
        await audio.play_sfx("game_start.wav")
        if leds.ready:
            leds.start_effect(leds.flash(80, 80, 255, count=2))
        await display.show_splash(game.TITLE, "GET READY!",
                                  rgb(20, 60, 20))
        await asyncio.sleep_ms(1200)

    async def _game_complete_sequence(self, result: GameResult):
        if leds.ready:
            leds.start_effect(leds.level_up())
        stars_str = ("*" * result.stars) + ("-" * (3 - result.stars))
        await display.show_splash(f"SCORE {result.score}",
                                  stars_str, rgb(20, 60, 20))
        if result.high_score:
            await audio.play_voice("new_high_score.wav")
        else:
            await audio.play_voice("well_done.wav")
        await asyncio.sleep_ms(2500)

    # ── Idle watchdog ────────────────────────────────────────────

    async def _idle_watchdog(self):
        while True:
            await asyncio.sleep_ms(5000)
            idle_s = (time.ticks_diff(time.ticks_ms(),
                                      self._last_input) // 1000)
            if idle_s >= config.SCREEN_DIM_S and not self._dimmed:
                if leds.ready:
                    leds.set_brightness(0.05)
                self._dimmed = True
                print("[kernel] idle — dimmed")
            if idle_s >= config.GAME_RETURN_IDLE_S:
                self._last_input = time.ticks_ms()

    def _touch(self):
        self._last_input = time.ticks_ms()
        if self._dimmed:
            if leds.ready:
                leds.set_brightness(config.LED_BRIGHTNESS)
            self._dimmed = False

    # ── Score persistence ─────────────────────────────────────────

    def _load_scores(self):
        try:
            with open(_SCORES_PATH, "r") as f:
                self._scores = json.load(f)
            print(f"[kernel] loaded scores for {len(self._scores)} games")
        except OSError:
            self._scores = {}

    def _save_scores(self):
        if not assets.sd_available:
            return
        try:
            with open(_SCORES_PATH, "w") as f:
                json.dump(self._scores, f)
        except OSError as e:
            print("[kernel] score save failed:", e)

    def _save_result(self, game_id: str, result: GameResult):
        entry   = self._scores.get(game_id, {"score": 0, "stars": 0})
        changed = False
        if result.score > entry.get("score", 0):
            entry["score"]    = result.score
            result.high_score = True
            changed           = True
        if result.stars > entry.get("stars", 0):
            entry["stars"] = result.stars
            changed        = True
        self._scores[game_id] = entry
        if changed:
            self._save_scores()
