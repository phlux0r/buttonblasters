# games/match/game.py — Button Blasters
# Match It! — child presses the button whose screen matches the item shown
# on the main display. Items are 96x96 icon sprites decompressed from FLASH
# (littlefs) through flash_assets, in three category rounds.
#
# Structure (3 rounds, 6 matches each = 18 matches total, max score 18/18):
#   Round 1 : shapes   (circle, square, triangle, star, diamond, hexagon)
#   Round 2 : fruit    (apple, banana, orange, grapes, strawberry, watermelon)
#   Round 3 : animals  (cat, dog, cow, duck, bird, sheep)
# Each round shows all six of its items as the target once (shuffled order),
# with three random distractors from the same category on the other buttons.
#
# ASSETS: /assets/match/sprb_<cat>-<item>_96x96x1.sz  (18 files)
#   Baked by bake_assets.py: single-frame BE RGB565 sprite (kind 3), opaque
#   on WHITE (no magenta key). The loader enforces BE-ness, so a mis-baked LE
#   asset fails loudly at load() instead of showing colour corruption.
#
# BOARD: /assets/match/bgm_match_480x320.bz — full-screen main-screen
#   background, BE RGB565 (kind 1, bgm_ prefix). Painted ONCE per round via
#   main.blit_rgb565 (the same BE path as the tiles/text — NOT the strip
#   renderer, whose converter is LE and needs the 150KB pool). Streamed
#   strip-by-strip from flash through an arena-borrowed ~30KB buffer. The
#   board supplies the white match-card and all decoration; each match then
#   repaints ONLY the pink header strip (variable-width prompt + score) and
#   blits the new target/tiles over the old, so the decoration persists.
#
# LOADING: flash load-and-discard, one match's working set at a time. The
#   panels retain their pixels after a blit, so nothing needs to stay in RAM
#   once it's on screen. Per match we reset the shared sprite arena, load the
#   four distinct icons for that match (target + 3 distractors, 4x18.4KB =
#   ~74KB, fits the 96KB arena), blit them, and the next match resets/reloads.
#   No boot-time icon pool, no per-category preload, no SD access — SD stays
#   reserved for My Big Day Out. The arena itself is seated ONCE at boot by
#   flash_assets.init() (core/kernel.py step 7b), on the freshest heap, so no
#   post-boot large allocation can fragment — the old MemoryError-under-churn
#   is gone by construction.
#
# MISSING ASSET: falls back to a coloured placeholder tile drawn straight to
#   the display (so the mechanic stays testable before all 18 PNGs exist) and
#   prints the missing path.
#
# Button IDs (core/game_base.py): 0-3 = screen buttons, 4 = BACK/HOME.

import gc
import time
import asyncio
import random
import config
from core.game_base import BaseGame, GameResult, shuffle
from core.display_manager import (rgb, WHITE, YELLOW, RED, GREEN, BLUE,
                                   CYAN, MAGENTA, ORANGE, DARK)
from drivers import flash_assets

# ── Content ──────────────────────────────────────────────────────
ITEMS = {
    "shape":  ("circle", "square", "triangle", "star", "diamond", "hexagon"),
    "fruit":  ("apple", "banana", "orange", "grapes", "strawberry", "watermelon"),
    "animal": ("cat", "dog", "cow", "duck", "bird", "sheep"),
}
CATEGORIES         = ("shape", "fruit", "animal")   # round order
CATEGORY_LABEL     = {"shape": "Shapes", "fruit": "Fruit", "animal": "Animals"}
ITEMS_PER_CATEGORY = 6
MATCHES_PER_ROUND  = 6
MAX_SCORE          = len(CATEGORIES) * MATCHES_PER_ROUND   # 18

ASSET_DIR = "/assets/static/match/"

# ── Appearance ───────────────────────────────────────────────────
# Icons are baked opaque on WHITE, so we fill each surface WHITE first and the
# tile edges blend into a clean card with no halo. Set to DARK for the old look.
ICON_BG = WHITE

# ── Geometry ─────────────────────────────────────────────────────
ICON = 96
BTN_ICON_X  = (config.BTN_W  - ICON) // 2       # 240 -> 72
BTN_ICON_Y  = (config.BTN_H  - ICON) // 2       # 300 -> 102
MAIN_ICON_X = (config.MAIN_W - ICON) // 2       # 480 -> 192
MAIN_ICON_Y = (config.MAIN_H - ICON) // 2       # 320 -> 112

_FALLBACK = (RED, GREEN, BLUE, YELLOW, CYAN, MAGENTA)

# ── Background board ─────────────────────────────────────────────
BOARD_PATH   = "/assets/match/bgm_match_480x320.bz"  # BE, kind 1 (bgm_)
REPLAY_TILE_PATH = "/assets/menu/btn_menu-match_300x240.bz"  # reused, 0 extra KB
BACK_TILE_PATH   = "/assets/menu/btn_back_300x240.bz"          # shared across games
HEADER_COLOR = 0xEA16      # #EB42B5 hot pink, quantized to RGB565
HEADER_H     = 44          # pink flat zone the prompt+score live in: (0,0,480,44)
PROMPT_Y     = 24          # prompt y inside the header (score sits at y=4)
# The white match-card painted into the board art must contain the centered
# target tile:  card (120, 104, 240, 152)  ⊃  tile (192, 132, 96, 96).
INTRO_PATH    = "/assets/match/bgm_intro-%s_480x320.bz"  # % cat; BE, kind 1
INTRO_HOLD_MS = 400       # extra beat the category card stays up (tunable)
RESULT_PATH    = "/assets/match/bgm_result_480x320.bz"  # BE, kind 1
RESULT_SCORE_Y = 124      # score overlay y (scale-4, in the card's flat zone)
                          # -- one line above RESULT_STARS_Y to make room
                          # for the star rating underneath
RESULT_STARS_Y = 152      # star rating overlay y, scale-3, below the score


def _fb_idx(name):
    # Stable placeholder colour per item name.
    s = 0
    for c in name:
        s += ord(c)
    return s % len(_FALLBACK)


def _format_time(seconds: float) -> str:
    total = int(seconds)
    return "%d:%02d" % (total // 60, total % 60)


class ShapeMatchGame(BaseGame):

    GAME_ID      = "match"
    TITLE        = "Match It!"
    DESCRIPTION  = "Find the matching shape, fruit or animal!"
    ICON_FILE    = None
    MIN_AGE      = 4
    MAX_AGE      = 7
    USES_BUTTONS = (0, 1, 2, 3)
    USES_NAV     = False
    USES_COUNTDOWN = False       # no clock in Match It! — skip the 3-2-1
    MENU_HEADER   = 0xEA16        # hot pink menu-card header (matches the board)
    MENU_STARS_FG = 0xe681     # GOLD — menu-card star colour (default)
    MENU_STARS_BG = 0xffff     # WHITE — flat colour of the card's stars zone
    MAX_SCORE     = MAX_SCORE   # module constant (18) — reuses the value
                                # already used for the "X of 18" end-screen text

    # ── Lifecycle ────────────────────────────────────────────────

    async def load(self):
        # No allocation here — icons are decompressed from flash into the
        # shared arena at draw time (seated at boot by flash_assets.init()).
        # No title screen: the menu already showed the title and the category
        # card announces each round, so we just clear the button screens and
        # leave the main display for the first category card in run().
        gc.collect()
        await self.display.fill_all_btns(DARK)

    async def run(self) -> GameResult:
        self._running = True
        self.score = 0
        self._round_start_ms = time.ticks_ms()
        self._finish_time_s  = None   # set only on a perfect (MAX_SCORE) run

        if self.USES_COUNTDOWN:
            await self.countdown(3)   # only ever fires once — never on replay

        while True:
            for cat in CATEGORIES:
                if not self._running:
                    break
                if await self.check_back():
                    break

                await self._show_category_intro(cat)
                if not await self.display.paint_main_bg(BOARD_PATH):
                    await self.display.fill_main(DARK)

                order = list(ITEMS[cat])
                shuffle(order)

                for m in range(MATCHES_PER_ROUND):
                    if await self.check_back():
                        self._running = False
                        break

                    target = order[m]
                    screen_items, correct_idx = self._layout_match(cat, target)
                    await self._draw_match(cat, target, screen_items)

                    gate_ms = time.ticks_ms()
                    pressed = await self._wait_answer(gate_ms)
                    if pressed == "quit":
                        self._running = False
                        break

                    if pressed == correct_idx:
                        self.score += 1
                        await self.show_correct()
                    else:
                        await self._reveal_correct(correct_idx)

            if not self._running:
                break   # mid-game BACK/HOME — exit immediately, no end screen

            # Only a perfect round-set has a meaningful "time to finish" —
            # a run with wrong answers isn't comparable to one without, so
            # there's nothing to time unless every match was right.
            if self.score == MAX_SCORE:
                self._finish_time_s = time.ticks_diff(
                    time.ticks_ms(), self._round_start_ms) / 1000

            choice = await self._end_screen()
            if choice == "back":
                break
            self.score = 0   # "again" — straight back into round 1, no countdown
            self._round_start_ms = time.ticks_ms()
            self._finish_time_s  = None

        return self._make_result()

    def _make_result(self) -> GameResult:
        result = super()._make_result()
        if self._finish_time_s is not None:
            result.time_s = self._finish_time_s
        return result

    async def unload(self):
        # Nothing game-owned to free; the arena persists on flash_assets for
        # the next game. Just tidy up and defer to the base cleanup.
        flash_assets.arena.reset()
        gc.collect()
        await super().unload()

    # ── Category intro ───────────────────────────────────────────

    async def _show_category_intro(self, cat):
        # Paint the baked category card; fall back to the text splash if the
        # asset is missing so the round is still announced.
        if not await self.display.paint_main_bg(INTRO_PATH % cat):
            await self.display.show_splash(
                "Get ready!", CATEGORY_LABEL[cat], bg_color=rgb(20, 30, 60))
        if self.audio and self.audio.ready:
            await self.audio.play_sfx("game_start.wav", wait=True)
        await asyncio.sleep_ms(INTRO_HOLD_MS)     # let the card breathe

    # ── Match setup ──────────────────────────────────────────────

    def _layout_match(self, cat, target):
        items = ITEMS[cat]
        others = [x for x in items if x != target]
        shuffle(others)
        distractors = others[:3]

        correct_idx = random.randint(0, 3)
        screen_items = [None, None, None, None]
        screen_items[correct_idx] = target
        d_iter = iter(distractors)
        for i in range(4):
            if screen_items[i] is None:
                screen_items[i] = next(d_iter)
        return screen_items, correct_idx

    # ── Asset loading (flash, per-match) ─────────────────────────

    def _asset_path(self, cat, name):
        return "%ssprb_%s-%s_%dx%dx1.sz" % (ASSET_DIR, cat, name, ICON, ICON)

    def _load_frame(self, cat, name, frames):
        # Decompress one icon from flash into the shared arena and cache its
        # memoryview for the duration of this match (so the target isn't loaded
        # twice — it appears big on main AND on its button). Returns the BE
        # RGB565 memoryview, or None if the asset is missing/bad.
        f = frames.get(name)
        if f is not None or (name in frames):
            return f
        try:
            sheet = flash_assets.SpriteSheet(self._asset_path(cat, name))
            f = sheet.frame(0)
        except Exception as e:
            print("[match] asset load failed:", self._asset_path(cat, name), e)
            f = None
        frames[name] = f
        return f

    # ── Rendering ────────────────────────────────────────────────

    async def _draw_match(self, cat, target, screen_items):
        # Fresh arena for this match's working set (<=4 icons, ~74KB).
        flash_assets.arena.reset()
        frames = {}

        # Clear ONLY the pink header strip — the prompt is variable-width, so a
        # shorter new prompt wouldn't fully erase a longer old one without this.
        # The white card + decoration come from the board and are left intact;
        # the new target tile simply overwrites the old (same 96x96 rect).
        await self.display.main.fill(HEADER_COLOR, 0, 0, config.MAIN_W, HEADER_H)
        prompt = "Find the " + target + "!"
        await self.display.text_main(
            prompt, config.MAIN_W // 2 - len(prompt) * 8, PROMPT_Y,
            WHITE, HEADER_COLOR, scale=2)

        # Big target on the main screen (over the board's white card).
        tf = self._load_frame(cat, target, frames)
        if tf is not None:
            await self.display.main.blit_rgb565(
                memoryview(tf), MAIN_ICON_X, MAIN_ICON_Y, ICON, ICON)
        else:
            await self.display.main.fill(
                _FALLBACK[_fb_idx(target)],
                MAIN_ICON_X, MAIN_ICON_Y, ICON, ICON)
        # White digits blend better than yellow on the pink header; bg matches
        # the header so the score box is invisible. (color=YELLOW to revert.)
        await self.display.draw_score(self.score, color=WHITE, bg=HEADER_COLOR)

        # Four option tiles on the button screens.
        for i, name in enumerate(screen_items):
            await self._draw_btn_icon(cat, i, name, frames)

    async def _draw_btn_icon(self, cat, idx, name, frames):
        await self.display.fill_btn(idx, ICON_BG)
        f = self._load_frame(cat, name, frames)
        if f is not None:
            await self.display.blit_btn_buf(
                idx, f, ICON, ICON, x=BTN_ICON_X, y=BTN_ICON_Y)
        else:
            col = _FALLBACK[_fb_idx(name)]
            await self.display.fill_btn(idx, col)
            lbl = name[:9].upper()
            await self.display.text_btn(
                idx, lbl, max(0, config.BTN_W // 2 - len(lbl) * 4),
                config.BTN_H // 2 - 4, WHITE, col, scale=1)

    # ── Input + feedback ─────────────────────────────────────────

    async def _wait_answer(self, gate_ms):
        # Poll the queue directly so BACK (id 4) is handled (the helper
        # wait_screen_button() ignores it).
        #
        # TIMESTAMP GATE: a press is accepted only if its press EDGE
        # (buttons._pressed_at[btn]) occurred at/after gate_ms — i.e. after
        # the match finished drawing. Rejects an eager press made while the
        # icons were still rendering, even if that press enqueues just AFTER
        # we drain the queue below (the race that made the first press feel
        # missed/delayed).
        self.buttons.clear()
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
                pressed_at = self.buttons._pressed_at[btn]
                if time.ticks_diff(pressed_at, gate_ms) >= 0:
                    return btn
                # else: edge was before the gate (during the draw) — ignore
                # and keep waiting for a fresh, post-draw press.

    async def _reveal_correct(self, correct_idx):
        # Wrong answer. ORDER MATTERS: draw the green border FIRST (silent),
        # THEN play wrong.wav and AWAIT it fully before returning — so no draw
        # (this border, or the next match's main fill) overlaps audio. Overlap
        # is what tore the screen on wrong.wav (blocking SPI mid-fill).
        await self.display.draw_btn_border(correct_idx, GREEN, thickness=10)
        if self.leds and self.leds.ready:
            self.leds.start_effect(self.leds.wrong_flash())
        await self.audio.play_sfx("wrong.wav", wait=True)
        await asyncio.sleep_ms(300)   # a beat so the child sees the answer

    # ── End screen ────────────────────────────────────────────────

    async def _end_screen(self):
        """Result card + BTN-3 'Back' (bottom-right) / BTN-0,1,2 'Play again'
        (all three show the same reused tile). No timeout — waits
        indefinitely for a choice."""
        try:
            self.leds.stop_effect()
        except Exception:
            pass

        score_str = "%d of %d" % (self.score, MAX_SCORE)
        stars     = self._stars_for(self.score)
        star_str  = ("*" * stars) + ("-" * (3 - stars))

        # Only a perfect round-set has a time worth showing. new_best is
        # compared/updated in-memory here (same pattern as
        # announce_round_complete()'s self.best_score bump) so consecutive
        # "Play again" runs in one session compare against each other too,
        # not just against what was persisted at game start.
        time_str = None
        if self._finish_time_s is not None:
            new_best = self.best_time_s is None or self._finish_time_s < self.best_time_s
            if new_best:
                self.best_time_s = self._finish_time_s
            time_str = ("NEW BEST! " if new_best else "TIME ") + \
                _format_time(self._finish_time_s)

        if await self.display.paint_main_bg(RESULT_PATH):
            ssx = config.MAIN_W // 2 - len(score_str) * 8
            await self.display.text_main(
                score_str, ssx, RESULT_SCORE_Y, 0xEA16, WHITE, scale=2)
            stx = config.MAIN_W // 2 - len(star_str) * 12   # scale 3 -> char 24, half 12
            await self.display.text_main(
                star_str, stx, RESULT_STARS_Y, YELLOW, WHITE, scale=3)
            if time_str:
                tx = config.MAIN_W // 2 - len(time_str) * 8
                await self.display.text_main(
                    time_str, tx, RESULT_STARS_Y + 28, 0xEA16, WHITE, scale=2)
        else:
            await self.display.show_splash(
                "You got", score_str, bg_color=rgb(10, 60, 20))
            stx = config.MAIN_W // 2 - len(star_str) * 12
            await self.display.text_main(   # below show_splash's subtitle line
                star_str, stx, 172, YELLOW, rgb(10, 60, 20), scale=3)
            if time_str:
                tx = config.MAIN_W // 2 - len(time_str) * 8
                await self.display.text_main(
                    time_str, tx, 200, YELLOW, rgb(10, 60, 20), scale=2)

        if not await self.display.paint_btn_bg(3, BACK_TILE_PATH):
            await self._show_back_fallback(3)
        for idx in (0, 1, 2):
            if not await self.display.paint_btn_bg(idx, REPLAY_TILE_PATH):
                await self._show_replay_fallback(idx)

        # All drawing for this screen is done — now the cheer, so playback
        # doesn't overlap any SPI writes. This fires once per completed
        # round-set (all 3 rounds), not at carousel-exit time.
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
            if evt != "press":
                continue
            if btn == 3 or btn == 4:      # BTN-3 tile, or hardware BACK/HOME
                return "back"
            if btn in (0, 1, 2):
                return "again"

    async def _show_back_fallback(self, idx):
        # Procedural stand-in until btn_back_300x240.bz is baked & uploaded.
        bg = rgb(60, 15, 15)
        await self.display.fill_btn(idx, bg)
        await self.display.draw_btn_border(idx, rgb(200, 60, 60))
        label = "BACK"
        lx = config.BTN_W // 2 - len(label) * 4
        await self.display.text_btn(idx, label, max(0, lx),
                                    config.BTN_H // 2 - 4, WHITE, bg, scale=1)

    async def _show_replay_fallback(self, idx):
        bg = rgb(15, 60, 20)
        await self.display.fill_btn(idx, bg)
        await self.display.draw_btn_border(idx, rgb(60, 200, 90))
        label = "AGAIN"
        lx = config.BTN_W // 2 - len(label) * 4
        await self.display.text_btn(idx, label, max(0, lx), config.BTN_H // 2 - 4, WHITE, bg, scale=1)
