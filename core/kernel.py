# core/kernel.py — Button Blasters v3.0
# AppKernel — central coordinator.
#
# Boot sequence:
#   1. Displays (SPI bus, ILI9488 + 4× ST7789)
#   2. Touch + I2C bus init — returns shared I2C instance
#   3. MCP23008 button init (shares I2C with touch)
#   4. Audio (I2S)
#   5. LEDs (PIO)
#   6. Haptic (GPIO — init LOW immediately to prevent float)
#   7. SD card mount (deferred — non-fatal)
#   8. Asset index + score load
#   9. Startup effects + menu

import asyncio
import json
import time

from core.display_manager import display, rgb, BLACK
from core.menu import Menu
from core.game_base import GameResult
from core import game_cache
from games.registry import REGISTRY
from drivers.buttons import buttons
from drivers.touch import touch
from drivers.audio import audio
from drivers.leds import leds
from drivers.haptic import haptic
from drivers.assets import assets
from drivers import flash_assets
import config

_SCORES_PATH = "/sd/scores.json"
_BOOT_BG = "/assets/sys/bgm_boot_480x320.bz"
_NOSD_BG = "/assets/sys/bgm_nosd_480x320.bz"

class AppKernel:

    def __init__(self):
        self._menu       = None
        self._scores     = {}
        self._last_input = time.ticks_ms()
        self._dimmed     = False

    async def init(self):
        print("[kernel] boot start")

        # 0. Init asyncio queue (must be inside async context)
        buttons.init_queue()

        # 1. Displays
        display.init_all()

        # 1b. Seat the flash-asset sprite arena on the FRESHEST heap — before
        # any subsystem (touch/audio/LEDs/SD) churns it, and before the boot
        # card paints (paint_main_bg borrows the arena). One 96KB alloc.
        flash_assets.init()

        # Boot splash — baked card if present, else the text splash.
        if not await display.paint_main_bg(_BOOT_BG):
            await display.show_splash("BUTTON", "BLASTERS",
                                      bg_color=rgb(20, 10, 60))

        # 2. Touch + shared I2C bus
        try:
            i2c = touch.init_blocking()   # returns I2C instance
            buttons.attach_touch(touch)
            print("[kernel] touch ready")
        except Exception as e:
            print(f"[kernel] touch init failed: {e}")
            i2c = None

        # 3. MCP23008 buttons (share same I2C bus)
        if i2c is not None:
            try:
                buttons.init_mcp(i2c)
                print("[kernel] buttons ready via MCP23008")
            except Exception as e:
                print(f"[kernel] MCP23008 init failed: {e}")
        else:
            print("[kernel] skipping MCP23008 — no I2C bus")

        # 4. Audio (already initialised at import — just confirm)
        if audio.ready:
            print("[kernel] audio ready")
        else:
            print("[kernel] audio not ready — check I2S wiring")

        # 5. LEDs
        if leds.ready:
            leds.start_effect(leds.chase(80, 40, 255))
            await asyncio.sleep_ms(600)
            leds.off()
        else:
            print("[kernel] LEDs not ready")
            await asyncio.sleep_ms(200)

        # 6. Haptic — already initialised LOW at import
        if haptic.ready:
            print("[kernel] haptic ready")

        # 7. SD card (deferred — non-fatal)
        sd_ok = assets.mount_sd()
        if sd_ok:
            assets.build_index()
            self._load_scores()
        else:
            if not await display.paint_main_bg(_NOSD_BG):
                await display.show_no_sd_warning()
            await asyncio.sleep_ms(1500)

        # 8. Startup sound
        await audio.play_sfx("startup.wav")

        # 9. Build menu
        self._menu = Menu(REGISTRY)
        self._menu._scores = {
            gid: d.get("score", 0) for gid, d in self._scores.items()}
        self._menu._stars = {
            gid: d.get("stars", 0) for gid, d in self._scores.items()}

        print(f"[kernel] boot complete — {len(REGISTRY)} games registered")

    # Two edits inside AppKernel.run(). These fix:
    #   #2  LEDs staying on (rainbow) at game end
    #   #3  BACK/HOME doing nothing on game end (2.5s blocking splash removed)
    #
    # The game (Shape Match) now owns its own end screen with a button-wait,
    # so the kernel no longer needs the blocking _game_complete_sequence.

    async def run(self):
        asyncio.create_task(buttons.run())
        asyncio.create_task(buttons.run_touch())
        asyncio.create_task(self._idle_watchdog())

        while True:
            game_cls = await self._menu.run()
            self._touch()

            game = game_cls(display, audio, leds, buttons, assets)
            await self._transition_to_game(game)
            await self._menu.show_loading()
            audio.stop_all()             # NEW — clean silence during install, not a stall

            print(f"[kernel] loading {game.GAME_ID}")
            if leds.ready:
                leds.start_effect(leds.chase(100, 200, 100))
            await game_cache.install(game.GAME_ID)      # NEW — Tier B install
            await game.load()
            leds.stop_effect()          # FIX: was leds.off() — off() left the
                                        # chase effect task running, which kept
                                        # rewriting the strip. stop_effect()
                                        # cancels the task AND clears the strip.

            print(f"[kernel] running {game.GAME_ID}")
            try:
                result = await game.run()
            except Exception as e:
                print(f"[kernel] game crashed: {e}")
                result = GameResult(score=0, completed=False)

            self._touch()
            self._save_result(game.GAME_ID, result)
            self._menu.update_result(game.GAME_ID,
                                     result.score, result.stars)

            # FIX #2/#3: stop any lingering LED effect and turn the strip
            # off at game end. The game already showed its own end screen
            # and handled BACK/HOME, so we DON'T run the old blocking
            # _game_complete_sequence (that 2.5s splash swallowed BACK).
            leds.stop_effect()
            
            # Optional non-blocking end voice (does not block BACK).
            if result.completed and audio.ready:
                if result.high_score:
                    await audio.play_voice("new_high_score.wav", wait=True)
                else:
                    await audio.play_voice("well_done.wav", wait=True)

            await game.unload()
            game_cache.evict(game.GAME_ID)        # NEW — Tier B evict
            print(f"[kernel] unloaded {game.GAME_ID}")

    # NOTE: _game_complete_sequence() can stay defined in the file (unused
    # now) or be deleted — your choice. Nothing calls it after this change.
    # The menu's idle_rainbow still runs while in the menu (by design); if
    # you want the strip fully dark in the menu too, tell me and I'll adjust
    # menu.run().

    # ── core/kernel.py — game_start transition tear fix ─────────────────
    # Replace AppKernel._transition_to_game() with this version.
    #
    # BEFORE: played game_start.wav, THEN drew the "GET READY!" splash — the
    # full-screen splash fill ran while the sound played, tearing the main
    # screen (same overlap class as the wrong.wav bug in game.py).
    #
    # AFTER: draw the splash FIRST (silent), THEN play the sound — so no
    # display SPI write overlaps audio playback. The LED flash is a
    # non-blocking effect (no SPI contention), so it's fine to start first.

    async def _transition_to_game(self, game):
        # Each game now owns its own intro (e.g. Match It!'s category card), so
        # the kernel no longer draws a generic GET READY splash or plays
        # game_start.wav here — that removes a duplicated cue and a redundant
        # transition. The LED flash stays: non-blocking, no SPI contention.
        if leds.ready:
            leds.start_effect(leds.flash(80, 80, 255, count=2))


    async def _game_complete_sequence(self, result: GameResult):
        if leds.ready:
            leds.start_effect(leds.level_up())
        if haptic.ready:
            asyncio.create_task(haptic.triple_pulse())
        stars_str = ("*" * result.stars) + ("-" * (3 - result.stars))
        await display.show_splash(f"SCORE {result.score}",
                                  stars_str, rgb(20, 60, 20))
        if result.high_score:
            await audio.play_voice("new_high_score.wav")
        else:
            await audio.play_voice("well_done.wav")
        await asyncio.sleep_ms(2500)

    async def _idle_watchdog(self):
        while True:
            await asyncio.sleep_ms(5000)
            idle_s = time.ticks_diff(
                time.ticks_ms(), self._last_input) // 1000
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
