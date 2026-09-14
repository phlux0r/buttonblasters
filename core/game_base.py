# core/game_base.py — Button Blasters
# BaseGame — abstract base class every game must subclass.
#
# Button ID reference for game code — physical layout is a 2x2 matrix
# (0|2 top row, 1|3 bottom row):
#   0 = SCREEN-0 / BTN-0  (top-left,    context action in game)
#   1 = SCREEN-1 / BTN-1  (bottom-left, PREV ← in menu, context action in game)
#   2 = SCREEN-2 / BTN-2  (top-right,   context action in game)
#   3 = SCREEN-3 / BTN-3  (bottom-right, NEXT → in menu, context action in game)
#   4 = BACK/HOME          (always quits game / returns to menu)
#
# To add a new game:
#   1. Create games/<game_id>/game.py  subclassing BaseGame
#   2. Implement load(), run(), unload()
#   3. Register in games/registry.py

import asyncio
import random
import time
import config
from core.display_manager import WHITE, YELLOW, rgb
from drivers.haptic import haptic
from drivers.touch import TOUCH_TAP

# Shared end-screen tiles (baked once, used by every game): BTN-3 = Back
# to the menu, BTN-0/1/2 = Play again. See BaseGame.show_end_screen().
BACK_TILE_PATH  = "/assets/menu/btn_back_280x240.bz"
AGAIN_TILE_PATH = "/assets/menu/btn_again_280x240.bz"


def shuffle(lst):
    # MicroPython's random has choice() but not shuffle(); Fisher-Yates.
    # Shared here since every game that picks a random subset needs it.
    for i in range(len(lst) - 1, 0, -1):
        j = random.randint(0, i)
        lst[i], lst[j] = lst[j], lst[i]


class GameResult:
    def __init__(self, score=0, stars=0, completed=False, high_score=False,
                 time_s=None, new_best_time=False):
        self.score      = score
        self.stars      = stars
        self.completed  = completed
        self.high_score = high_score
        # time_s: seconds to finish, only meaningful for games that define
        # a "clean run" worth timing (e.g. Match It! only records one on a
        # perfect MAX_SCORE round-set) — None means "not applicable/not a
        # qualifying run", not "zero time". new_best_time is set by
        # AppKernel._save_result() the same way high_score already is.
        self.time_s        = time_s
        self.new_best_time = new_best_time


class BaseGame:
    """
    Subclass this to create a game.

    Hardware singletons injected at init:
        self.display   — DisplayManager
        self.audio     — AudioManager
        self.leds      — LedStrip
        self.buttons   — ButtonManager
        self.assets    — AssetManager
    """

    GAME_ID      = "base"
    TITLE        = "Untitled Game"
    DESCRIPTION  = ""
    ICON_FILE    = None
    MIN_AGE      = 4
    MAX_AGE      = 7
    USES_BUTTONS = (0, 1, 2, 3)
    USES_NAV     = True
    USES_COUNTDOWN = True    # reaction games keep it; override False otherwise
    MENU_HEADER    = None    # RGB565 for a menu-card header band, or None
    MENU_STARS_FG  = 0xe681  # GOLD — menu-card star colour (default)
    MENU_STARS_BG  = 0xffff  # WHITE — flat colour of the card's stars zone
    MAX_SCORE      = None    # override in subclasses with a natural score ceiling
                             # (e.g. total matches) so stars scale to it instead
                             # of the flat fallback below.

    # ── End-screen layout (see show_end_screen) ─────────────────
    RESULT_PATH           = None      # baked 480x320 BE result card, or None
    RESULT_SCORE_Y        = 124       # score line y on the card (scale 2)
    RESULT_STARS_Y        = 152       # star line y on the card (scale 3)
    RESULT_SCORE_COLOR    = 0xEA16    # hot pink, on the card's white zone
    RESULT_EXTRA_GAP      = 28        # extra line's y offset from the stars:
                                      # stars render at scale 3 (24px glyphs),
                                      # so this must clear 24px -- +16 visibly
                                      # overlapped on hardware
    RESULT_FALLBACK_TITLE = "Well done!"          # show_splash() title if no card
    RESULT_FALLBACK_BG    = rgb(10, 60, 20)
    RESULT_FALLBACK_STARS_Y = 172                  # below show_splash's subtitle

    def __init__(self, display, audio, leds, buttons, assets_mgr,
                 best_score=0, best_time_s=None):
        self.display      = display
        self.audio        = audio
        self.leds         = leds
        self.buttons      = buttons
        self.assets       = assets_mgr
        self.score        = 0
        self.lives        = 3
        self.level        = 1
        self.best_score   = best_score      # persisted high score, at game start
        self.best_time_s  = best_time_s     # persisted best clean-run time, if any
        self._running     = False
        self._quit        = False

    # ── Required overrides ───────────────────────────────────────

    async def load(self):
        """Preload assets. Default: clear all displays."""
        await self.display.clear_all()

    async def run(self) -> GameResult:
        """Main game loop. Must return a GameResult."""
        raise NotImplementedError(
            f"{self.GAME_ID}.run() must be implemented")

    async def unload(self):
        """Clean up after game exits."""
        self.audio.stop_all()
        self.assets.evict_cache(self.GAME_ID)
        await self.display.clear_all()

    # ── Helpers ──────────────────────────────────────────────────

    def quit(self):
        self._quit    = True
        self._running = False

    async def wait_any_button(self) -> int:
        self.buttons.clear()
        return await self.buttons.get_press()

    async def wait_screen_button(self) -> int:
        """Block until one of the 4 screen buttons (0-3) is pressed."""
        self.buttons.clear()
        while True:
            btn = await self.buttons.get_press()
            if btn <= 3:
                return btn

    async def wait_tap(self):
        """Block until a screen tap. Returns (x, y)."""
        return await self.buttons.get_tap()

    async def wait_or_timeout_back(self, coro):
        """Await coro (an end-screen's wait-for-choice call) but return
        "back" automatically after config.GAME_RETURN_IDLE_S of no input,
        so a finished round-set doesn't sit waiting forever if the player
        walked away. Deliberately for END-SCREEN waits only -- call sites
        are each game's own _end_screen(), never anything mid-play.
        Interrupting active play would be disruptive in a way a "Play
        again?" prompt nobody's answering just isn't."""
        try:
            return await asyncio.wait_for(coro, config.GAME_RETURN_IDLE_S)
        except asyncio.TimeoutError:
            return "back"

    async def wait_tap_or_button(self):
        """Block until tap OR screen button press."""
        return await self.buttons.get_press_or_tap()

    def tap_hit(self, tx: int, ty: int, rect: tuple) -> bool:
        return self.buttons.hit_test(tx, ty, rect)

    def check_back(self) -> bool:
        """Non-blocking — has BACK (id=4) been pressed? Removes only that
        event; any other queued input is left for the caller's own
        buttons.poll(). (The old version popped ONE event of any kind and
        threw it away if it wasn't BACK, silently eating screen-button
        presses that a game's own loop was about to read.)"""
        if self.buttons.take_back_press():
            self.quit()
            return True
        return False

    async def show_correct(self):
        if self.leds.ready:
            self.leds.start_effect(self.leds.correct_flash())
        await self.audio.play_sfx("correct.wav")
        if haptic.ready:
            await haptic.double_pulse()
        await asyncio.sleep_ms(600)

    async def show_wrong(self):
        if self.leds.ready:
            self.leds.start_effect(self.leds.wrong_flash())
        await self.audio.play_sfx("wrong.wav")
        await asyncio.sleep_ms(500)

    async def show_level_up(self):
        if self.leds.ready:
            self.leds.start_effect(self.leds.level_up())
        await self.audio.play_voice("level_up.wav", wait=True)

    async def announce_round_complete(self):
        """End-of-round-set cheer. Call this once from the game's own end
        screen, after the result is drawn, so the cue lands with "you
        finished" rather than with "you're leaving" (that used to be played
        by the kernel after the player chose to exit back to the carousel).
        Compares against best_score (persisted at game start, and bumped
        in-memory on 'play again' loops) so a beaten high score is caught
        on every round-set, not just the final one before quitting."""
        if not (self.audio and self.audio.ready):
            return
        if self.score > self.best_score:
            self.best_score = self.score
            await self.audio.play_voice("new_high_score.wav", wait=True)
        else:
            await self.audio.play_voice("well_done.wav", wait=True)

    # ── Shared end screen ────────────────────────────────────────
    # Every game ends a round-set the same way: result card on the main
    # screen (score + stars, optional extra line), "Again" tiles on
    # BTN-0/1/2, "Back" on BTN-3, the round-complete cheer, then wait for
    # a choice with the idle auto-return. Layout knobs are the RESULT_*
    # class attributes above; games only supply the score string.

    async def show_end_screen(self, score_str, extra_line=None):
        """Paint the standard end screen and wait for the player.
        extra_line: optional text drawn one line below the stars (e.g. a
        clean-run time). Returns "again" or "back"."""
        try:
            self.leds.stop_effect()
        except Exception:
            pass

        stars    = self._stars_for(self.score)
        star_str = ("*" * stars) + ("-" * (3 - stars))
        cx       = config.MAIN_W // 2

        if self.RESULT_PATH and await self.display.paint_main_bg(self.RESULT_PATH):
            bg, fg, stars_y = WHITE, self.RESULT_SCORE_COLOR, self.RESULT_STARS_Y
            await self.display.text_main(
                score_str, cx - len(score_str) * 8, self.RESULT_SCORE_Y,
                fg, bg, scale=2)
        else:
            bg, fg, stars_y = self.RESULT_FALLBACK_BG, YELLOW, self.RESULT_FALLBACK_STARS_Y
            await self.display.show_splash(self.RESULT_FALLBACK_TITLE, score_str,
                                           bg_color=bg)
        # scale 3 -> 24px per char, half 12
        await self.display.text_main(
            star_str, cx - len(star_str) * 12, stars_y, YELLOW, bg, scale=3)
        if extra_line:
            await self.display.text_main(
                extra_line, cx - len(extra_line) * 8,
                stars_y + self.RESULT_EXTRA_GAP, fg, bg, scale=2)

        await self._paint_end_tiles()

        # All drawing done — now the cheer, so playback never overlaps an
        # SPI write. Fires once per completed round-set, not at exit time.
        await self.announce_round_complete()

        return await self.wait_or_timeout_back(self.wait_end_choice())

    async def _paint_end_tiles(self):
        if not await self.display.paint_btn_bg(3, BACK_TILE_PATH):
            await self._paint_tile_fallback(3, "BACK", rgb(60, 15, 15),
                                            rgb(200, 60, 60))
        for idx in (0, 1, 2):
            if not await self.display.paint_btn_bg(idx, AGAIN_TILE_PATH):
                await self._paint_tile_fallback(idx, "AGAIN", rgb(15, 60, 20),
                                                rgb(60, 200, 90))

    async def _paint_tile_fallback(self, idx, label, bg, border):
        # Procedural stand-in if a shared tile asset is missing.
        await self.display.fill_btn(idx, bg)
        await self.display.draw_btn_border(idx, border)
        lx = config.BTN_W // 2 - len(label) * 4
        await self.display.text_btn(idx, label, max(0, lx),
                                    config.BTN_H // 2 - 4, WHITE, bg, scale=1)

    async def wait_end_choice(self):
        """Block until the player picks on the end screen: "again" for
        BTN-0/1/2 or a tap anywhere, "back" for BTN-3 or BACK/HOME."""
        self.buttons.clear()
        while True:
            ev = self.buttons.poll()
            if ev is None:
                await asyncio.sleep_ms(20)
                continue
            btn, evt = ev
            if btn == TOUCH_TAP and evt == "tap":
                return "again"
            if evt != "press":
                continue
            if btn == 3 or btn == 4:
                return "back"
            if btn in (0, 1, 2):
                return "again"

    async def show_game_over(self):
        if self.leds.ready:
            self.leds.start_effect(self.leds.pulse(150, 0, 0))
        await self.audio.play_voice("game_over.wav", wait=True)
        await self.display.show_splash("GAME OVER",
                                       f"Score: {self.score}")
        await asyncio.sleep_ms(2000)

    # Custom draw, not display.show_splash() — that helper's scale is fixed
    # (title=2) and shared by every splash call site in the app; bumping it
    # there would resize every other splash too. The countdown wants each
    # number (and GO!) to fill most of the screen. Value lives in
    # config.COUNTDOWN_TEXT_SCALE — shared with
    # core/display_manager.py's warm_text_scratch(), which pre-warms the
    # buffer this size renders into. Change it there, not here, so the two
    # can't silently desync (see that config entry for the RAM history).
    _COUNTDOWN_SCALE = config.COUNTDOWN_TEXT_SCALE

    async def _show_countdown_text(self, text, bg_color):
        s = self._COUNTDOWN_SCALE
        await self.display.fill_main(bg_color)
        cx = config.MAIN_W // 2 - len(text) * 4 * s
        cy = config.MAIN_H // 2 - 4 * s
        await self.display.text_main(text, cx, cy, color=0xFFFF,
                                     bg=bg_color, scale=s)

    async def countdown(self, from_n: int = 3):
        # Draw FIRST, then play the clip AWAITED, then sleep whatever is
        # left of the beat. This used to fire the clip and draw at once
        # (to hide the ~80ms full-screen paint as callout latency), which
        # was fine while the count/go names had no files and the synth
        # fallback played from RAM. Real voice samples on the SD card
        # broke it: drivers/audio.py reads the card WITHOUT the SPI0 bus
        # lock (by design), so the clip's file reads landed mid-paint with
        # the ILI9488's CS low -- confirmed on hardware as the countdown
        # background tearing on the 'ready'/'go' samples. Rule for every
        # game: never draw while an SD-backed clip may still be reading.
        for n in range(from_n, 0, -1):
            await self._countdown_beat(str(n), 0x18C3, f"count_{n}.wav", 800)
        await self._countdown_beat("GO!", 0x0320, "go.wav", 500)

    async def _countdown_beat(self, text, bg_color, clip, beat_ms):
        t0 = time.ticks_ms()
        await self._show_countdown_text(text, bg_color)
        await self.audio.play_sfx(clip, wait=True)
        left = beat_ms - time.ticks_diff(time.ticks_ms(), t0)
        if left > 0:
            await asyncio.sleep_ms(left)

    def _make_result(self) -> GameResult:
        return GameResult(
            score=self.score,
            stars=self._stars_for(self.score),
            completed=not self._quit,
        )

    def _stars_for(self, score: int) -> int:
        if self.MAX_SCORE:
            if score <= 0:
                return 0
            pct = score / self.MAX_SCORE
            if pct >= 1.0:
                return 3
            if pct >= 0.65:
                return 2
            return 1
        # Fallback for games with no fixed ceiling (endless/reaction style).
        stars = 0
        if score > 0:   stars = 1
        if score >= 10: stars = 2
        if score >= 20: stars = 3
        return stars
