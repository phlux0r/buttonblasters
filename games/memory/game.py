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
from drivers.touch import TOUCH_TAP

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
BORDER_THICKNESS = 15   # was 10 -- thicker, more visible against the icon
BORDER_INSET     = 4    # pulls the border in from the raw edge -- the left
                         # edge was visibly clipped flush against 0

MAX_SCORE = 12   # sequence length worth 3 stars -- see BaseGame._stars_for()

STEP_LIT_MS  = 450     # how long a playback step stays lit
STEP_GAP_MS  = 200     # dark gap between playback steps
PRESS_LIT_MS = 220     # how long a player's own press flashes back
ROUND_GAP_MS = 500     # pause after a correct round before the sequence grows

RESULT_BG = rgb(20, 10, 50)
BACK_TILE_PATH  = "/assets/menu/btn_back_300x240.bz"     # shared across games
AGAIN_TILE_PATH = "/assets/menu/btn_again_300x240.bz"    # shared across games
RESULT_PATH     = "/assets/memory/bgm_result_480x320.bz"
RESULT_SCORE_Y  = 125   # score overlay y, scale-2 (was 120 -- lowered 5px per feedback
                         # on the real art)
RESULT_STARS_Y  = 148   # star rating overlay y, scale-3, below the score

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

    # ── Lifecycle ────────────────────────────────────────────────

    async def load(self):
        # Defensive reseed -- see the RANDOMNESS NOTE above. Cheap, and
        # rules out "fixed seed every boot" if a skew is ever reported
        # again after this change.
        random.seed(time.ticks_us())
        self._base_bg   = [LEGEND_BG] * 4
        self._icon_frame = [None] * 4
        # Loaded once and kept for the whole game -- nothing else touches
        # the shared arena while this game is active, so the frames stay
        # valid without the per-round reset/reload Match It! needs (it
        # cycles many more icons than fit in the arena at once; our 4 all
        # fit together for the session).
        flash_assets.arena.reset()
        for i, name in enumerate(CHAR_NAMES):
            await self._load_icon(i, name)

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

    # ── Icon setup ───────────────────────────────────────────────

    async def _load_icon(self, idx, name):
        """Decode one Star Bonk! legend icon into the shared arena and paint
        its base (neutral, unlit) tile. Missing/bad asset -> flat colour
        fallback, same convention as Match It!/Star Bonk!."""
        try:
            sheet = flash_assets.SpriteSheet(_btn_asset_path(name))
            if not sheet.big_endian:
                raise ValueError("legend icon must be BE (kind 3)")
            self._icon_frame[idx] = sheet.frame(0)
            self._base_bg[idx] = LEGEND_BG
        except Exception as e:
            print("[memory] icon load failed:", name, e)
            self._icon_frame[idx] = None
            self._base_bg[idx] = _FALLBACK[idx]
        await self._paint_base(idx)

    async def _paint_base(self, idx):
        """(Re)draw one button's icon + neutral border, from the cached
        frame -- no flash access, safe to call every replay."""
        await self.display.fill_btn(idx, self._base_bg[idx])
        frame = self._icon_frame[idx]
        if frame is not None:
            await self.display.blit_btn_buf(
                idx, frame, ICON, ICON, x=BTN_ICON_X, y=BTN_ICON_Y)
        await self.display.draw_btn_border(
            idx, self._base_bg[idx], thickness=BORDER_THICKNESS, inset=BORDER_INSET)

    async def _paint_all_bases(self):
        for i in range(4):
            await self._paint_base(i)

    async def _set_lit(self, idx, on):
        color = BTN_ACCENT[idx] if on else self._base_bg[idx]
        await self.display.draw_btn_border(
            idx, color, thickness=BORDER_THICKNESS, inset=BORDER_INSET)

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

        if await self.display.paint_main_bg(RESULT_PATH):
            ssx = config.MAIN_W // 2 - len(score_str) * 8
            await self.display.text_main(
                score_str, ssx, RESULT_SCORE_Y, 0xEA16, WHITE, scale=2)
            stx = config.MAIN_W // 2 - len(star_str) * 12   # scale 3 -> char 24, half 12
            await self.display.text_main(
                star_str, stx, RESULT_STARS_Y, YELLOW, WHITE, scale=3)
        else:
            await self.display.show_splash("Nice memory!", score_str, bg_color=RESULT_BG)
            stx = config.MAIN_W // 2 - len(star_str) * 12
            await self.display.text_main(
                star_str, stx, 168, YELLOW, RESULT_BG, scale=3)

        if not await self.display.paint_btn_bg(3, BACK_TILE_PATH):
            await self._show_back_fallback(3)
        for idx in (0, 1, 2):
            if not await self.display.paint_btn_bg(idx, AGAIN_TILE_PATH):
                await self._show_replay_fallback(idx)

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

    async def _show_back_fallback(self, idx):
        # Only used if btn_back_300x240.bz is somehow missing -- normally
        # paint_btn_bg() above finds the shared asset every other game uses.
        bg = rgb(60, 15, 15)
        await self.display.fill_btn(idx, bg)
        await self.display.draw_btn_border(idx, rgb(200, 60, 60))
        label = "BACK"
        lx = config.BTN_W // 2 - len(label) * 4
        await self.display.text_btn(idx, label, max(0, lx),
                                    config.BTN_H // 2 - 4, WHITE, bg, scale=1)

    async def _show_replay_fallback(self, idx):
        # Only used if btn_again_300x240.bz is somehow missing.
        bg = rgb(15, 60, 20)
        await self.display.fill_btn(idx, bg)
        await self.display.draw_btn_border(idx, rgb(60, 200, 90))
        label = "AGAIN"
        lx = config.BTN_W // 2 - len(label) * 4
        await self.display.text_btn(idx, label, max(0, lx), config.BTN_H // 2 - 4, WHITE, bg, scale=1)
