# core/kernel.py
# AppKernel — the central coordinator.
#
# Responsibilities:
#   - Boot sequence: init all hardware in the right order
#   - Run the asyncio task tree
#   - Cycle between the menu and games
#   - Handle idle timeout and battery warning
#   - Persist high scores to flash (scores.json on SD card)
#
# The kernel never knows what's inside a game — it just calls
# load() / run() / unload() and receives a GameResult.

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
        self._menu        = None
        self._scores      = {}
        self._last_input  = time.ticks_ms()
        self._dimmed      = False

    # ── Boot sequence ────────────────────────────────────────────

    async def init(self):
        """
        Initialise all hardware.  Must complete before asyncio tasks start
        doing display work.  Order matters — SPI bus first, then displays,
        then SD card (shares SPI), then everything else.
        """
        print("[kernel] boot start")

        # 1. Displays (blocking — SPI bus claimed exclusively at boot)
        display.init_all()
        await display.show_splash("BUTTON", "BLASTERS", bg_color=rgb(20,10,60))

        # 1b. Touch controller (I²C — independent of SPI, init now)
        try:
            touch.init_blocking()
            buttons.attach_touch(touch)
            print("[kernel] touch controller ready")
        except Exception as e:
            print(f"[kernel] touch init failed (continuing without touch): {e}")

        # 2. SD card + asset index
        ok = assets.mount_sd()
        if ok:
            assets.build_index()
        else:
            await display.show_splash("NO SD CARD", "insert & reboot")
            await asyncio.sleep_ms(3000)

        # 3. Load persistent scores
        self._load_scores()

        # 4. LED startup animation
        leds.start_effect(leds.chase(80, 40, 255))
        await asyncio.sleep_ms(800)
        leds.off()

        # 5. Play startup sound
        await audio.play_sfx("startup.wav")

        # 6. Build menu
        self._menu = Menu(REGISTRY)
        self._menu._scores = {
            gid: d.get("score", 0) for gid, d in self._scores.items()
        }
        self._menu._stars = {
            gid: d.get("stars", 0) for gid, d in self._scores.items()
        }

        print(f"[kernel] boot complete — {len(REGISTRY)} games registered")

    # ── Main event loop ──────────────────────────────────────────

    async def run(self):
        """Start the button listener and the main game-menu loop."""
        # Background tasks that run for the lifetime of the app
        asyncio.create_task(buttons.run())
        asyncio.create_task(buttons.run_touch())   # touch event task
        asyncio.create_task(self._idle_watchdog())

        while True:
            # ── Menu ─────────────────────────────────────────────
            game_cls = await self._menu.run()
            self._touch()

            # ── Instantiate game ─────────────────────────────────
            game = game_cls(display, audio, leds, buttons, assets)

            # ── Transition in ────────────────────────────────────
            await self._transition_to_game(game)

            # ── Load assets ──────────────────────────────────────
            print(f"[kernel] loading {game.GAME_ID}")
            leds.start_effect(leds.chase(100, 200, 100))
            await game.load()
            leds.off()

            # ── Play ─────────────────────────────────────────────
            print(f"[kernel] running {game.GAME_ID}")
            try:
                result = await game.run()
            except Exception as e:
                print(f"[kernel] game crashed: {e}")
                result = GameResult(score=0, completed=False)

            self._touch()

            # ── Save result ──────────────────────────────────────
            self._save_result(game.GAME_ID, result)
            self._menu.update_result(game.GAME_ID, result.score, result.stars)

            # ── Post-game feedback ───────────────────────────────
            if result.completed:
                await self._game_complete_sequence(result)

            # ── Unload ───────────────────────────────────────────
            await game.unload()
            print(f"[kernel] unloaded {game.GAME_ID}")

    # ── Transitions ──────────────────────────────────────────────

    async def _transition_to_game(self, game):
        """Brief animated transition between menu and game."""
        await audio.play_sfx("game_start.wav")
        leds.start_effect(leds.flash(80, 80, 255, count=2))
        await display.show_splash(game.TITLE, "GET READY!", rgb(20, 60, 20))
        await asyncio.sleep_ms(1200)

    async def _game_complete_sequence(self, result: GameResult):
        """Show score and stars after a completed game."""
        leds.start_effect(leds.level_up())
        stars_str = "★" * result.stars + "☆" * (3 - result.stars)
        await display.show_splash(
            f"SCORE {result.score}",
            stars_str,
            rgb(20, 60, 20),
        )
        if result.high_score:
            await audio.play_voice("new_high_score.wav")
        else:
            await audio.play_voice("well_done.wav")
        await asyncio.sleep_ms(2500)

    # ── Idle watchdog ────────────────────────────────────────────

    async def _idle_watchdog(self):
        """Dim displays after inactivity; return to menu after longer idle."""
        while True:
            await asyncio.sleep_ms(5000)
            idle_s = time.ticks_diff(time.ticks_ms(), self._last_input) // 1000

            if idle_s >= config.SCREEN_DIM_S and not self._dimmed:
                # Dim the LED strip to save battery
                leds.set_brightness(0.05)
                self._dimmed = True
                print("[kernel] display dimmed")

            if idle_s >= config.GAME_RETURN_IDLE_S:
                # Nothing we can do here to interrupt the game directly —
                # but we signal via a flag that game loops should poll.
                # (Games call self.check_back() which also checks this.)
                self._last_input = time.ticks_ms()   # reset to avoid spam

    def _touch(self):
        """Record user activity — resets idle timer."""
        self._last_input = time.ticks_ms()
        if self._dimmed:
            leds.set_brightness(config.LED_BRIGHTNESS)
            self._dimmed = False

    # ── Score persistence ────────────────────────────────────────

    def _load_scores(self):
        try:
            with open(_SCORES_PATH, "r") as f:
                self._scores = json.load(f)
            print(f"[kernel] loaded scores for {len(self._scores)} games")
        except OSError:
            self._scores = {}

    def _save_scores(self):
        try:
            with open(_SCORES_PATH, "w") as f:
                json.dump(self._scores, f)
        except OSError as e:
            print("[kernel] score save failed:", e)

    def _save_result(self, game_id: str, result: GameResult):
        entry = self._scores.get(game_id, {"score": 0, "stars": 0})
        changed = False
        if result.score > entry.get("score", 0):
            entry["score"] = result.score
            result.high_score = True
            changed = True
        if result.stars > entry.get("stars", 0):
            entry["stars"] = result.stars
            changed = True
        self._scores[game_id] = entry
        if changed:
            self._save_scores()
