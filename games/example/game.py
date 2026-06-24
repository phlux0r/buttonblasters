# games/example/game.py — Button Blasters
# ExampleGame — minimal working game demonstrating the full pattern.
#
# Copy games/example/ to games/<your_game_id>/ and build from here.
# Then uncomment the matching line in games/registry.py.
#
# Button IDs in this game:
#   0 = SCREEN-0 → left/option A
#   1 = SCREEN-1 → left-centre/option B
#   2 = SCREEN-2 → right-centre/option C
#   3 = SCREEN-3 → right/option D
#   4 = BACK     → quit game

import asyncio
import random
import time
from core.game_base import BaseGame, GameResult
from core.display_manager import rgb, WHITE, YELLOW, BLACK
import config


class ExampleGame(BaseGame):

    GAME_ID     = "example"
    TITLE       = "Tap It!"
    DESCRIPTION = "Tap the glowing button!"
    ICON_FILE   = "shared/example_icon_64x64.raw"
    MIN_AGE     = 4
    MAX_AGE     = 7
    USES_BUTTONS = (0, 1, 2, 3)
    USES_NAV     = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._target  = 0
        self._timeout = 5000

    async def load(self):
        await self.display.clear_all()
        await self.display.fill_main(rgb(20, 10, 60))
        await self.display.text_main(
            self.TITLE,
            config.MAIN_W // 2 - len(self.TITLE) * 8,
            20, WHITE, rgb(20, 10, 60), scale=2
        )
        for i in range(4):
            await self.display.fill_btn(i, rgb(30, 20, 80))

    async def run(self) -> GameResult:
        self._running = True
        self.score    = 0
        self.lives    = 3

        await self.countdown(3)

        while self._running and self.lives > 0:
            if await self.check_back():
                break

            self._target = random.randint(0, 3)
            await self._show_round()
            answered = await self._wait_answer()

            if not answered:
                self.lives -= 1
                await self.show_wrong()
                await self.display.draw_score(self.score, self.lives)

            await asyncio.sleep_ms(300)

        await self.show_game_over()
        return self._make_result()

    async def unload(self):
        await super().unload()

    async def _show_round(self):
        IDLE_COLOURS = [
            rgb(30, 20, 80), rgb(0, 45, 37),
            rgb(55, 25, 0),  rgb(7, 45, 15),
        ]
        PRESS_COLOURS = [
            rgb(92, 50, 200), rgb(0, 180, 150),
            rgb(220, 100, 0), rgb(30, 180, 60),
        ]
        for i in range(4):
            await self.display.fill_btn(i, IDLE_COLOURS[i])
        await self.display.fill_btn(self._target,
                                    PRESS_COLOURS[self._target])
        await self.display.draw_btn_border(self._target, YELLOW)
        await self.audio.play_sfx("ping.wav")
        await self.display.fill_main(rgb(20, 10, 60))
        await self.display.text_main(
            "TAP IT!",
            config.MAIN_W // 2 - 7 * 16,
            config.MAIN_H // 2 - 16,
            YELLOW, rgb(20, 10, 60), scale=2
        )
        await self.display.draw_score(self.score, self.lives)

    async def _wait_answer(self) -> bool:
        deadline = time.ticks_add(time.ticks_ms(), self._timeout)
        self.buttons.clear()

        while True:
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                return False
            try:
                btn, evt = self.buttons._queue.get_nowait()
                if evt != "press":
                    continue
                if btn == 4:
                    self.quit()
                    return False
                if btn <= 3:
                    if btn == self._target:
                        self.score += 1
                        self.level  = 1 + self.score // 5
                        await self.show_correct()
                        await self.display.draw_score(self.score,
                                                      self.lives)
                        return True
                    else:
                        self.lives -= 1
                        await self.show_wrong()
                        await self.display.draw_score(self.score,
                                                      self.lives)
                        return False
            except Exception:
                pass
            await asyncio.sleep_ms(20)
