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
import config


def shuffle(lst):
    # MicroPython's random has choice() but not shuffle(); Fisher-Yates.
    # Shared here since every game that picks a random subset needs it.
    for i in range(len(lst) - 1, 0, -1):
        j = random.randint(0, i)
        lst[i], lst[j] = lst[j], lst[i]


class GameResult:
    def __init__(self, score=0, stars=0, completed=False, high_score=False):
        self.score      = score
        self.stars      = stars
        self.completed  = completed
        self.high_score = high_score


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

    def __init__(self, display, audio, leds, buttons, assets_mgr, best_score=0):
        self.display    = display
        self.audio      = audio
        self.leds       = leds
        self.buttons    = buttons
        self.assets     = assets_mgr
        self.score      = 0
        self.lives      = 3
        self.level      = 1
        self.best_score = best_score   # persisted high score, at game start
        self._running   = False
        self._quit      = False

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

    async def wait_tap_or_button(self):
        """Block until tap OR screen button press."""
        return await self.buttons.get_press_or_tap()

    def tap_hit(self, tx: int, ty: int, rect: tuple) -> bool:
        return self.buttons.hit_test(tx, ty, rect)

    async def check_back(self) -> bool:
        """Non-blocking check — has BACK (id=4) been pressed?"""
        try:
            btn, evt = self.buttons._queue.get_nowait()
            if btn == 4 and evt == "press":
                self.quit()
                return True
        except Exception:
            pass
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
    # number (and GO!) to fill most of the screen.
    _COUNTDOWN_SCALE = 10

    async def _show_countdown_text(self, text, bg_color):
        s = self._COUNTDOWN_SCALE
        await self.display.fill_main(bg_color)
        cx = config.MAIN_W // 2 - len(text) * 4 * s
        cy = config.MAIN_H // 2 - 4 * s
        await self.display.text_main(text, cx, cy, color=0xFFFF,
                                     bg=bg_color, scale=s)

    async def countdown(self, from_n: int = 3):
        for n in range(from_n, 0, -1):
            await self._show_countdown_text(str(n), 0x18C3)
            await self.audio.play_sfx(f"count_{n}.wav")
            await asyncio.sleep_ms(800)
        await self._show_countdown_text("GO!", 0x0320)
        await self.audio.play_sfx("go.wav")
        await asyncio.sleep_ms(500)

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

# Import haptic here to avoid circular at top of file
from drivers.haptic import haptic
