# games/memory/game.py — Button Blasters
# Button Memory — classic Simon-says. The console lights up (and sounds) a
# growing sequence of screen buttons; the child repeats it back in order.
# One mistake ends the round-set. Score = number of rounds successfully
# repeated (the length of the longest sequence played back correctly).
#
# ASSETS: reuses Star Bonk!'s already-baked button-screen legend icons
# (wizard/goblin/star/mushroom) instead of baking new art -- each button
# permanently shows one character; "lit" is a coloured border flash around
# the icon, not a fill swap, so a step's icon never needs re-decoding from
# flash mid-round (just a cheap border redraw). Falls back to a flat colour
# tile (same convention as Match It!/Star Bonk!) if an icon is missing.
#   bonk/sprb_<name>_96x96x1.sz  BE, kind 3, opaque -- see games/bonk/game.py
#     for the full asset spec. wizard, goblin, star, mushroom.
#
# Tones are synthesized via AudioManager.play_tone() (drivers/audio.py)
# rather than sample playback -- no audio asset dependency either.
#
# RANDOMNESS NOTE: no random.seed() call exists anywhere in this codebase,
# so the PRNG relies entirely on the port's default boot-time seeding. If a
# single button seems to dominate a session, the much more likely cause is
# structural, not a biased PRNG: every round replays the FULL sequence from
# step 0, so whichever button was drawn first is shown far more often over
# a session than later steps purely from repetition -- that's inherent to
# Simon-style play, not a fairness bug. Reseeding here with a live timer
# reading is cheap insurance against the other, less likely possibility
# (a fixed/weak default seed producing the same sequence every boot).
#
# Button IDs (core/game_base.py): 0-3 = screen buttons, 4 = BACK/HOME.
# Physical layout: 0=top-left 2=top-right / 1=bottom-left 3=bottom-right.

import asyncio
import random
import time
import config
from core.game_base import BaseGame, GameResult
from core.display_manager import rgb, WHITE, RED, GREEN, BLUE, YELLOW
from drivers import flash_assets

# ── Content ──────────────────────────────────────────────────────
# Reuse Star Bonk!'s 4 characters/icons -- same names, same button order,
# so the two games feel like part of one family instead of introducing a
# fifth colour language.
ASSET_DIR  = "/assets/static/bonk/"
ICON       = 96
CHAR_NAMES = ("wizard", "goblin", "star", "mushroom")   # -> buttons 0,1,2,3
BTN_ACCENT = (RED, BLUE, GREEN, YELLOW)   # lit-border colour per button
BTN_TONE_HZ = (330, 392, 440, 523)        # E4 G4 A4 C5 -- one tone per button
LEGEND_BG   = WHITE                       # icon tile background (Bonk's convention)
_FALLBACK   = (RED, BLUE, GREEN, YELLOW)  # flat-colour stand-in if an icon is missing

BTN_ICON_X = (config.BTN_W - ICON) // 2
BTN_ICON_Y = (config.BTN_H - ICON) // 2
BORDER_THICKNESS   = 24   # quite thick, per on-device feedback -- was 10, then 15
BORDER_INSET       = 0    # flush on all 4 sides
BORDER_LEFT_EXTRA  = 0    # was 10 -- that was compensating in-game for the
                           # panel's real ~20px left column crop, now fixed
                           # at the source (config.BTN_COL_OFFSET, applied
                           # centrally in ST7789._set_window()). Left at 10
                           # here too it just double-compensates, showing as
                           # a white gap between the true edge and the bar.

MAX_SCORE = 12   # sequence length worth 3 stars -- see BaseGame._stars_for()

STEP_LIT_MS  = 450     # how long a playback step stays lit
STEP_GAP_MS  = 200     # dark gap between playback steps
PRESS_LIT_MS = 220     # how long a player's own press flashes back
ROUND_GAP_MS = 500     # pause after a correct round before the sequence grows


# One background covers both the "Watch!" and "Your turn!" phases of a
# round -- only the overlay text/colour changes between them (same trick
# Match It! uses: one board, header text repainted per match). Saves a
# second asset and a second flash decode every round.
WATCH_PATH   = "/assets/memory/bgm_watch_480x320.bz"
HEADER_H     = 48      # the art's plain overlay zone -- ask for this exact
                        # band to be baked in HEADER_COLOR so our repaint is
                        # a seamless patch, same trick as Match It!'s pink strip
HEADER_COLOR = rgb(20, 10, 50)
PROMPT_Y     = 12       # overlay text y within the header band


def _btn_asset_path(name):
    return "%ssprb_%s_%dx%dx1.sz" % (ASSET_DIR, name, ICON, ICON)


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
    RESULT_PATH    = "/assets/memory/bgm_result_480x320.bz"
    RESULT_SCORE_Y = 135   # was 120, then 125 -- lowered per feedback on the real art
    RESULT_STARS_Y = 148
    RESULT_FALLBACK_TITLE   = "Nice memory!"
    RESULT_FALLBACK_BG      = rgb(20, 10, 50)
    RESULT_FALLBACK_STARS_Y = 168

    # ── Lifecycle ────────────────────────────────────────────────

    async def load(self):
        # Defensive reseed -- see the RANDOMNESS NOTE above. Cheap, and
        # rules out "fixed seed every boot" if a skew is ever reported
        # again after this change.
        random.seed(time.ticks_us())
        self._base_bg = [LEGEND_BG] * 4
        await self._paint_all_bases()

    async def unload(self):
        flash_assets.arena.reset()
        await super().unload()

    async def run(self) -> GameResult:
        self._running = True
        self.score = 0
        self.sequence = []

        while True:
            self.sequence = []
            self.score = 0
            await self._paint_all_bases()

            while True:
                if self.check_back():
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

    # ── Icon setup ───────────────────────────────────────────────
    # Each icon is decoded from flash and discarded on every call -- NOT
    # cached across draws. Nothing else in this game needs the shared
    # flash_assets.arena, and four ~18KB flash decodes per "Play Again"
    # is cheap (once per replay, not per round), so there's no reason to
    # keep frames resident.

    async def _paint_base(self, idx):
        """Decode button idx's icon fresh from flash and draw it + a
        neutral border. Missing/bad asset -> flat colour fallback, same
        convention as Match It!/Star Bonk!."""
        name = CHAR_NAMES[idx]
        flash_assets.arena.reset()
        try:
            sheet = flash_assets.SpriteSheet(_btn_asset_path(name))
            if not sheet.big_endian:
                raise ValueError("legend icon must be BE (kind 3)")
            self._base_bg[idx] = LEGEND_BG
            await self.display.fill_btn(idx, LEGEND_BG)
            await self.display.blit_btn_buf(
                idx, sheet.frame(0), ICON, ICON, x=BTN_ICON_X, y=BTN_ICON_Y)
        except Exception as e:
            print("[memory] icon load failed:", name, e)
            self._base_bg[idx] = _FALLBACK[idx]
            await self.display.fill_btn(idx, _FALLBACK[idx])
        flash_assets.arena.reset()
        await self.display.draw_btn_border(
            idx, self._base_bg[idx], thickness=BORDER_THICKNESS,
            inset=BORDER_INSET, left_extra=BORDER_LEFT_EXTRA)

    async def _paint_all_bases(self):
        for i in range(4):
            await self._paint_base(i)

    async def _set_lit(self, idx, on):
        color = BTN_ACCENT[idx] if on else self._base_bg[idx]
        await self.display.draw_btn_border(
            idx, color, thickness=BORDER_THICKNESS,
            inset=BORDER_INSET, left_extra=BORDER_LEFT_EXTRA)

    # ── Round display ────────────────────────────────────────────
    # One background (WATCH_PATH) covers the whole round -- "Watch!" and
    # "Your turn!" are just different text drawn into its header band, not
    # separate images. Painted once per round at intro time; the button
    # screens are what change during playback/input, so the main screen
    # never needs repainting until the next round.

    async def _show_round_intro(self):
        if not await self.display.paint_main_bg(WATCH_PATH):
            await self.display.fill_main(HEADER_COLOR)
        await self._draw_prompt("Watch!", WHITE)
        await asyncio.sleep_ms(400)   # a beat before the sequence starts

    async def _draw_prompt(self, text, color):
        # Clear only the header band -- the art's own scene stays intact
        # below it (and is a no-op-looking fill if the background is the
        # flat HEADER_COLOR fallback).
        await self.display.main.fill(HEADER_COLOR, 0, 0, config.MAIN_W, HEADER_H)
        # Left-aligned, not centered -- "Your turn!" at scale=3 centered ran
        # into draw_score's top-right box ("SCORE:0000" starts ~x=316); a
        # fixed left x always clears it regardless of prompt length.
        await self.display.text_main(
            text, 16, PROMPT_Y, color, HEADER_COLOR, scale=3)
        await self.display.draw_score(self.score, color=YELLOW, bg=HEADER_COLOR)

    async def _play_sequence(self):
        for step in self.sequence:
            await self._set_lit(step, True)
            await self.audio.play_tone(BTN_TONE_HZ[step], STEP_LIT_MS)
            await asyncio.sleep_ms(STEP_LIT_MS)
            await self._set_lit(step, False)
            await asyncio.sleep_ms(STEP_GAP_MS)

        await self._draw_prompt("Your turn!", YELLOW)

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
            ev = self.buttons.poll()
            if ev is None:
                await asyncio.sleep_ms(15)
                continue
            btn, evt = ev
            if evt != "press":
                continue
            if btn == 4:
                self.quit()
                return "quit"
            if btn <= 3:
                return btn

    async def _flash_press(self, btn):
        await self._set_lit(btn, True)
        await self.audio.play_tone(BTN_TONE_HZ[btn], PRESS_LIT_MS)
        await asyncio.sleep_ms(PRESS_LIT_MS)
        await self._set_lit(btn, False)

    # ── Feedback ──────────────────────────────────────────────────

    async def _show_wrong(self):
        if self.leds and self.leds.ready:
            self.leds.start_effect(self.leds.wrong_flash())
        await self.audio.play_sfx("wrong.wav", wait=True)
        await asyncio.sleep_ms(300)

    # ── End screen ───────────────────────────────────────────────

    async def _end_screen(self):
        return await self.show_end_screen("Round %d" % self.score)

