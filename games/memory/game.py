# games/memory/game.py — Button Blasters
# Button Memory — classic Simon-says. The console lights up (and sounds) a
# growing sequence of screen buttons; the child repeats it back in order.
# One mistake ends the round-set. Score = number of rounds successfully
# repeated (the length of the longest sequence played back correctly).
#
# No baked assets — each button screen is just a solid colour fill (bright
# "lit" / dim "rest"), so this game has zero flash/SD dependency and can't
# be broken by a missing sprite sheet. Tones are synthesized via
# AudioManager.play_tone() (drivers/audio.py) rather than sample playback,
# for the same reason.
#
# Button IDs (core/game_base.py): 0-3 = screen buttons, 4 = BACK/HOME.
# Physical layout: 0=top-left 2=top-right / 1=bottom-left 3=bottom-right.

import asyncio
import random
import config
from core.game_base import BaseGame, GameResult
from core.display_manager import rgb, WHITE, RED, GREEN, BLUE, YELLOW, DARK
from drivers.touch import TOUCH_TAP

# ── Content ──────────────────────────────────────────────────────
# Classic 4-colour Simon palette, one per screen button, each with its own
# tone so the sequence is learnable by ear as well as by eye.
BTN_LIT = (RED, BLUE, GREEN, YELLOW)
BTN_DIM = (rgb(60, 8, 8), rgb(8, 8, 60), rgb(8, 50, 8), rgb(70, 65, 0))
BTN_TONE_HZ = (330, 392, 440, 523)   # E4 G4 A4 C5 -- a simple, pleasant chord

MAX_SCORE = 12   # sequence length worth 3 stars -- see BaseGame._stars_for()

STEP_LIT_MS  = 450     # how long a playback step stays lit
STEP_GAP_MS  = 200     # dark gap between playback steps
PRESS_LIT_MS = 220     # how long a player's own press flashes back
ROUND_GAP_MS = 500     # pause after a correct round before the sequence grows

RESULT_BG = rgb(20, 10, 50)


class ButtonMemoryGame(BaseGame):

    GAME_ID      = "memory"
    TITLE        = "Button Memory"
    DESCRIPTION  = "Watch the pattern, then play it back!"
    ICON_FILE    = None
    MIN_AGE      = 4
    MAX_AGE      = 7
    USES_BUTTONS = (0, 1, 2, 3)
    USES_NAV     = False
    USES_COUNTDOWN = False       # the first "watch!" sequence is its own intro
    MENU_HEADER   = rgb(40, 20, 90)   # deep purple, distinct from Match/Bonk
    MAX_SCORE     = MAX_SCORE

    # ── Lifecycle ────────────────────────────────────────────────

    async def load(self):
        await self.display.fill_all_btns(DARK)

    async def run(self) -> GameResult:
        self._running = True
        self.score = 0
        self.sequence = []

        while True:
            self.sequence = []
            self.score = 0
            await self._dim_all()

            while True:
                if await self.check_back():
                    self._running = False
                    break

                self.sequence.append(random.randint(0, 3))
                await self._show_round_intro()
                await self._play_sequence()

                result = await self._collect_input()
                if result == "quit":
                    self._running = False
                    break
                if result:
                    self.score += 1
                    await asyncio.sleep_ms(ROUND_GAP_MS)
                    continue
                else:
                    await self._show_wrong()
                    break

            if not self._running:
                break   # mid-game BACK/HOME -- exit immediately, no end screen

            choice = await self._end_screen()
            if choice == "back":
                break
            # "again" -- straight back into round 1, no countdown

        return self._make_result()

    async def unload(self):
        await super().unload()

    # ── Round display ────────────────────────────────────────────

    async def _dim_all(self):
        for i in range(4):
            await self.display.fill_btn(i, BTN_DIM[i])

    async def _show_round_intro(self):
        await self.display.fill_main(rgb(15, 8, 40))
        prompt = "Watch!"
        await self.display.text_main(
            prompt, config.MAIN_W // 2 - len(prompt) * 16, 40,
            WHITE, rgb(15, 8, 40), scale=4)
        await self.display.draw_score(self.score, color=YELLOW, bg=rgb(15, 8, 40))
        await asyncio.sleep_ms(400)   # a beat before the sequence starts

    async def _play_sequence(self):
        for step in self.sequence:
            await self.display.fill_btn(step, BTN_LIT[step])
            await self.audio.play_tone(BTN_TONE_HZ[step], STEP_LIT_MS)
            await asyncio.sleep_ms(STEP_LIT_MS)
            await self.display.fill_btn(step, BTN_DIM[step])
            await asyncio.sleep_ms(STEP_GAP_MS)

        prompt = "Your turn!"
        await self.display.fill_main(rgb(10, 40, 20))
        await self.display.text_main(
            prompt, config.MAIN_W // 2 - len(prompt) * 12, 40,
            WHITE, rgb(10, 40, 20), scale=3)
        await self.display.draw_score(self.score, color=YELLOW, bg=rgb(10, 40, 20))

    # ── Input ─────────────────────────────────────────────────────

    async def _collect_input(self):
        self.buttons.clear()
        for expected in self.sequence:
            btn = await self._wait_one_press()
            if btn == "quit":
                return "quit"
            await self._flash_press(btn)
            if btn != expected:
                return False
        return True

    async def _wait_one_press(self):
        while True:
            try:
                btn, evt = self.buttons._queue.get_nowait()
            except Exception:
                await asyncio.sleep_ms(15)
                continue
            if evt != "press":
                continue
            if btn == 4:
                self.quit()
                return "quit"
            if btn <= 3:
                return btn

    async def _flash_press(self, btn):
        await self.display.fill_btn(btn, BTN_LIT[btn])
        await self.audio.play_tone(BTN_TONE_HZ[btn], PRESS_LIT_MS)
        await asyncio.sleep_ms(PRESS_LIT_MS)
        await self.display.fill_btn(btn, BTN_DIM[btn])

    # ── Feedback ──────────────────────────────────────────────────

    async def _show_wrong(self):
        if self.leds and self.leds.ready:
            self.leds.start_effect(self.leds.wrong_flash())
        await self.audio.play_sfx("wrong.wav", wait=True)
        await asyncio.sleep_ms(300)

    # ── End screen ───────────────────────────────────────────────

    async def _end_screen(self):
        """Result card + BTN-3 'Back' (bottom-right) / BTN-0,1,2 'Play again'.
        A screen tap also replays, matching Match It! / Star Bonk!. No
        timeout — waits indefinitely for a choice."""
        try:
            self.leds.stop_effect()
        except Exception:
            pass

        score_str = "Round %d" % self.score
        stars     = self._stars_for(self.score)
        star_str  = ("*" * stars) + ("-" * (3 - stars))

        await self.display.show_splash("Nice memory!", score_str, bg_color=RESULT_BG)
        stx = config.MAIN_W // 2 - len(star_str) * 12   # scale 3 -> char 24, half 12
        await self.display.text_main(
            star_str, stx, 168, YELLOW, RESULT_BG, scale=3)

        if not await self._show_back_tile(3):
            pass
        for idx in (0, 1, 2):
            await self._show_replay_tile(idx)

        await self.announce_round_complete()

        return await self.wait_or_timeout_back(self._wait_end_choice())

    async def _wait_end_choice(self):
        self.buttons.clear()
        while True:
            try:
                btn, evt = self.buttons._queue.get_nowait()
            except Exception:
                await asyncio.sleep_ms(20)
                continue
            if btn == TOUCH_TAP and evt == "tap":
                return "again"          # tap anywhere on the score screen -> replay
            if evt != "press":
                continue
            if btn == 3 or btn == 4:      # BTN-3 tile, or hardware BACK/HOME
                return "back"
            if btn in (0, 1, 2):
                return "again"

    async def _show_back_tile(self, idx):
        bg = rgb(60, 15, 15)
        await self.display.fill_btn(idx, bg)
        await self.display.draw_btn_border(idx, rgb(200, 60, 60))
        label = "BACK"
        lx = config.BTN_W // 2 - len(label) * 4
        await self.display.text_btn(idx, label, max(0, lx),
                                    config.BTN_H // 2 - 4, WHITE, bg, scale=1)
        return True

    async def _show_replay_tile(self, idx):
        bg = rgb(15, 60, 20)
        await self.display.fill_btn(idx, bg)
        await self.display.draw_btn_border(idx, rgb(60, 200, 90))
        label = "AGAIN"
        lx = config.BTN_W // 2 - len(label) * 4
        await self.display.text_btn(idx, label, max(0, lx), config.BTN_H // 2 - 4, WHITE, bg, scale=1)
