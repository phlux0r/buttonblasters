# core/game_base.py
# BaseGame — abstract base class every game must subclass.
#
# A game is a self-contained async coroutine that:
#   1. Receives the shared hardware singletons (display, audio, leds, buttons)
#   2. Runs its own loop until it decides to exit
#   3. Returns a GameResult to the kernel
#
# To add a new game:
#   1. Create  games/<your_game>/game.py
#   2. Subclass BaseGame
#   3. Implement the three required methods: load(), run(), unload()
#   4. Register it in games/registry.py
#
# That's it.  The kernel handles everything else.

import asyncio
from dataclasses import dataclass


@dataclass
class GameResult:
    """What a game hands back to the kernel when it exits."""
    score:      int   = 0
    stars:      int   = 0     # 0-3 — shown on menu card after play
    completed:  bool  = False  # True = finished normally, False = quit/back
    high_score: bool  = False  # True = new personal best


class BaseGame:
    """
    Subclass this to create a game.

    Lifecycle called by the kernel:
        await game.load()       — preload assets, set up state
        result = await game.run()  — main loop, returns GameResult
        await game.unload()     — free assets, clean up displays

    Hardware singletons are available as instance attributes after __init__:
        self.display   — DisplayManager
        self.audio     — AudioManager
        self.leds      — LedStrip
        self.buttons   — ButtonManager
        self.assets    — AssetManager
    """

    # ── Class-level metadata (set these in your subclass) ────────
    GAME_ID      = "base"          # unique short string, matches folder name
    TITLE        = "Untitled Game"
    DESCRIPTION  = ""
    ICON_FILE    = None            # filename of 64×64 menu icon
    MIN_AGE      = 4
    MAX_AGE      = 7
    USES_BUTTONS = (0, 1, 2, 3)   # which screen buttons this game uses
    USES_NAV     = True            # whether BACK/NEXT are active

    def __init__(self, display, audio, leds, buttons, assets_mgr):
        self.display  = display
        self.audio    = audio
        self.leds     = leds
        self.buttons  = buttons
        self.assets   = assets_mgr

        # Runtime state — reset each play
        self.score    = 0
        self.lives    = 3
        self.level    = 1
        self._running = False
        self._quit    = False

    # ── Required overrides ───────────────────────────────────────

    async def load(self):
        """
        Preload all assets needed for this game.
        Called once before run().  Pre-cache bitmaps here so gameplay
        is smooth.  Default: clears all displays.
        """
        await self.display.clear_all()

    async def run(self) -> GameResult:
        """
        Main game loop.  Must return a GameResult.
        Call self.quit() internally to break out and return early.
        """
        raise NotImplementedError(f"{self.GAME_ID}.run() must be implemented")

    async def unload(self):
        """
        Clean up after game exits.
        Evict per-game image cache, stop audio/effects.
        Default: stops audio and evicts this game's cached images.
        """
        self.audio.stop_all()
        self.assets.evict_cache(self.GAME_ID)
        await self.display.clear_all()

    # ── Convenience helpers available to all games ────────────────

    def quit(self):
        """Signal the game loop to exit gracefully."""
        self._quit = True
        self._running = False

    async def wait_any_button(self) -> int:
        """Block until any button is pressed. Returns button id."""
        self.buttons.clear()
        return await self.buttons.get_press()

    async def wait_screen_button(self) -> int:
        """Block until one of the 4 screen buttons is pressed (0-3)."""
        self.buttons.clear()
        while True:
            btn = await self.buttons.get_press()
            if btn <= 3:
                return btn

    async def wait_tap(self):
        """Block until a screen tap. Returns (x, y)."""        return await self.buttons.get_tap()

    async def wait_tap_or_button(self):
        """
        Block until a tap OR a physical screen button press.
        Returns (btn_id, event) — games supporting dual input use this.
        btn_id == 10 means touch tap; check buttons.touch_pos for (x, y).
        """
        return await self.buttons.get_press_or_tap()

    def tap_hit(self, tx: int, ty: int, rect: tuple) -> bool:
        """
        Check if a tap at (tx, ty) is inside rect (rx, ry, rw, rh).
        Use after wait_tap() or wait_tap_or_button() to detect which
        on-screen zone was tapped.
        """
        return self.buttons.hit_test(tx, ty, rect)

    async def check_back(self) -> bool:
        """
        Non-blocking check — has BACK been pressed?
        Call this in your game loop to allow the player to quit.
        """
        try:
            btn, evt = self.buttons._queue.get_nowait()
            if btn == 4 and evt == "press":   # BTN_BACK
                self.quit()
                return True
        except Exception:
            pass
        return False

    async def show_correct(self):
        """Standard 'correct answer' feedback — reusable across games."""
        self.leds.start_effect(self.leds.correct_flash())
        await self.audio.play_sfx("correct.wav")
        await asyncio.sleep_ms(600)

    async def show_wrong(self):
        """Standard 'wrong answer' feedback."""
        self.leds.start_effect(self.leds.wrong_flash())
        await self.audio.play_sfx("wrong.wav")
        await asyncio.sleep_ms(500)

    async def show_level_up(self):
        """Level-up fanfare."""
        self.leds.start_effect(self.leds.level_up())
        await self.audio.play_voice("level_up.wav", wait=True)

    async def show_game_over(self):
        """Game over sequence."""
        self.leds.start_effect(self.leds.pulse(150, 0, 0))
        await self.audio.play_voice("game_over.wav", wait=True)
        await self.display.show_splash("GAME OVER",
                                       f"Score: {self.score}")
        await asyncio.sleep_ms(2000)

    async def countdown(self, from_n: int = 3):
        """3-2-1-GO! countdown on main screen before a game starts."""
        for n in range(from_n, 0, -1):
            await self.display.show_splash(str(n), bg_color=0x18C3)
            await self.audio.play_sfx(f"count_{n}.wav")
            await asyncio.sleep_ms(800)
        await self.display.show_splash("GO!", bg_color=0x0320)
        await self.audio.play_sfx("go.wav")
        await asyncio.sleep_ms(500)

    def _make_result(self) -> GameResult:
        """Build a GameResult from current state. Call at end of run()."""
        stars = 0
        if self.score > 0:   stars = 1
        if self.score >= 10: stars = 2
        if self.score >= 20: stars = 3
        return GameResult(
            score=self.score,
            stars=stars,
            completed=not self._quit,
        )
