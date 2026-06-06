# games/example/game.py
# ExampleGame — minimal working game that demonstrates the full pattern.
#
# Copy this folder to games/<your_game_id>/ and build from here.
# Then uncomment the matching line in games/registry.py.
#
# This example implements a trivial "tap the right button" game
# to show asset loading, button handling, scoring, and clean exit.

import asyncio
from core.game_base import BaseGame, GameResult
from core.display_manager import rgb, WHITE, YELLOW, BLACK
import config


class ExampleGame(BaseGame):

    # ── Metadata ─────────────────────────────────────────────────
    GAME_ID     = "example"
    TITLE       = "Tap It!"
    DESCRIPTION = "Tap the glowing button!"
    ICON_FILE   = "shared/example_icon_64x64.raw"
    MIN_AGE     = 4
    MAX_AGE     = 7
    USES_BUTTONS = (0, 1, 2, 3)
    USES_NAV     = True

    # ── Per-game state ────────────────────────────────────────────
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._target  = 0      # which button is the correct one
        self._images  = []     # preloaded button images
        self._timeout = 5000   # ms to answer before penalty

    # ── Lifecycle ─────────────────────────────────────────────────

    async def load(self):
        """Preload all assets we'll need during gameplay."""
        await self.display.clear_all()

        # Fill the main screen with the game background
        await self.display.fill_main(rgb(20, 10, 60))
        await self.display.text_main(
            self.TITLE,
            config.MAIN_W // 2 - len(self.TITLE) * 8,
            20, WHITE, rgb(20, 10, 60), scale=2
        )

        # Preload button images from SD (one per button)
        # In a real game these would be your cute animal/shape images.
        # Here we just use fill colours as a fallback.
        self._images = []
        for i in range(4):
            fn = f"example/btn_{i}_64x64.raw"
            buf = await self.assets.load_image(fn)
            self._images.append(buf)

        # Fill button screens with base colour
        for i in range(4):
            await self.display.fill_btn(i, rgb(30, 20, 80))

    async def run(self) -> GameResult:
        """Main game loop."""
        self._running = True
        self.score    = 0
        self.lives    = 3

        await self.countdown(3)

        while self._running and self.lives > 0:
            # Check BACK button to allow quitting
            if await self.check_back():
                break

            # Pick a random target button
            import random
            self._target = random.randint(0, 3)

            # Show the round
            await self._show_round()

            # Wait for response with timeout
            answered = await self._wait_answer()

            if not answered:
                # Timed out — lose a life
                self.lives -= 1
                await self.show_wrong()
                await self.display.draw_score(self.score, self.lives)
                if self.lives == 0:
                    break
            await asyncio.sleep_ms(300)

        await self.show_game_over()
        return self._make_result()

    async def unload(self):
        """Clean up — called by kernel after run() returns."""
        self._images.clear()
        await super().unload()   # stops audio, evicts cache, clears screens

    # ── Private round logic ───────────────────────────────────────

    async def _show_round(self):
        """Highlight the target button and update the main screen prompt."""
        # Dim all button screens
        for i in range(4):
            await self.display.fill_btn(i, rgb(30, 20, 80))
            await self.display.draw_btn_highlight(i, on=False)

        # Highlight the target
        await self.display.fill_btn(self._target, rgb(255, 200, 0))
        await self.display.draw_btn_highlight(self._target, on=True)
        await self.audio.play_sfx("ping.wav")

        # Update main screen
        await self.display.fill_main(rgb(20, 10, 60))
        await self.display.text_main(
            "TAP IT!",
            config.MAIN_W // 2 - 7 * 8 * 2 // 2,
            config.MAIN_H // 2 - 16,
            YELLOW, rgb(20, 10, 60), scale=2
        )
        await self.display.draw_score(self.score, self.lives)

    async def _wait_answer(self) -> bool:
        """
        Wait up to self._timeout ms for the player to press a button.
        Returns True if answered correctly, False if wrong or timed out.
        """
        import time
        deadline = time.ticks_add(time.ticks_ms(), self._timeout)
        self.buttons.clear()

        while True:
            # Check timeout
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                return False   # timed out

            # Non-blocking queue check
            try:
                btn, evt = self.buttons._queue.get_nowait()
                if evt != "press":
                    continue
                if btn == 4:   # BACK
                    self.quit()
                    return False
                if btn <= 3:
                    if btn == self._target:
                        self.score += 1
                        self.level  = 1 + self.score // 5
                        await self.show_correct()
                        await self.display.draw_score(self.score, self.lives)
                        return True
                    else:
                        self.lives -= 1
                        await self.show_wrong()
                        await self.display.draw_score(self.score, self.lives)
                        return False
            except Exception:
                pass

            await asyncio.sleep_ms(20)
