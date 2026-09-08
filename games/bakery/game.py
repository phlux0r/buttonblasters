# games/bakery/game.py — Button Blasters
# Magic Bakery — 3 recipes (randomly drawn from a pool of 6), each needing
# 4 ingredients. Ingredients drift right-to-left across a conveyor belt in
# the lower half of the main screen; tap the right ones, avoid the wrong
# ones. A tapped ingredient (right OR wrong) parks on one of the 4 button
# screens: correct ones lock in place, wrong ones must be cleared by
# pressing that same button before another item can use the slot. Score
# is elapsed time (lower is better, same "new_best_time" convention Match
# It! already uses) — setup/reveal time is excluded, only time spent with
# the belt actually running counts.
#
# ENGINEERING NOTE — first game to use SpriteEngine.start()'s CONTINUOUS
# tick loop (every other game either doesn't animate the main screen, or
# like Star Bonk!, only calls render_dirty() once per discrete spawn/
# despawn). documents/HARDWARE_NOTES.md flags this combination explicitly
# as an unreasoned-through hazard: audio that resolves via the SD-card
# fallback shares SPI0 with the display, and a fire-and-forget audio call
# racing the engine's background render tick caused real screen tearing in
# Bonk (fixed there by awaiting the clip instead). Every audio call in this
# file is awaited (wait=True) for the same reason, and every per-game clip
# (voice names + recipe intros) should be baked/installed as Tier B audio
# for this game (not left to the SD fallback) so the fast path is used.
#
# MEMORY NOTE — the ingredient pool is 10 items, but flash_assets.arena is
# a shared 96KB bump arena and each 96x96 LE sprite is ~18.4KB — all 10 of
# them (~184KB) would blow that budget outright, unlike Star Bonk!'s fixed 4
# characters (~74KB) which fit for the whole game. So unlike Bonk, this
# game reloads its LE sprite pool PER ROUND (same discipline Match It!
# uses for its 18-icon rotation): each round only loads the 4 ingredients
# that recipe needs plus DECOYS_PER_ROUND extra (currently 1) — 5 sprites
# (~92KB) fits with a little headroom. Button-screen icons (BE, opaque,
# for the "parked on a button" display) are decoded fresh and discarded
# every time, exactly like games/memory/game.py's icons — see that file's
# comment for why caching them in the shared arena would risk the same
# "wizard/goblin corruption on Play Again" bug this project already hit
# once. A small scratch arena handles button icons + the recipe/baked
# card + end-screen paints, kept separate from the shared arena that holds
# the round's persistent LE belt sprites -- this is literally Star Bonk!'s
# own already-boot-seated _scratch_arena, reused rather than a second one
# of Bakery's own (see the load() comment for why: a second lazy 32KB
# allocation hit the exact fragmentation failure Bonk's already fought).
#
# LAYOUT — main screen is 480x320. The recipe card (280x169) sits at
# (x=100, y=15), matching the pre-composed frame baked into the board art;
# its bottom edge is row 183 (15+169-1). This position matters at the
# sprite_engine dirty-tracking granularity (STRIP_H=8 in
# drivers/strip_renderer.py, NOT the unrelated 32-row chunking
# tools/bake_assets.py uses when BAKING a file): the card is painted via
# plain paint_main_bg(), entirely outside sprite_engine's tracking, so if
# a drifting sprite's dirty strip ever overlapped the card's rows, the
# engine would repaint straight from the board art and erase the card.
# The visible conveyor-belt track measured off the board art runs from
# (65,285) to (420,285) at its bottom edge; items are bottom-aligned to
# y=285 and (being 96px tall) their top row is fixed at y=189 all round
# (only x ever changes) -- 189 // STRIP_H = strip 23, rows 184-191. 169px
# is the exact height that clears this: the card's last row (183) sits
# one row below strip 23, so the two never share a strip and the overlap
# that 175px (and 200px before it) left behind is fully closed.
#
# The baked reveal at the end of a round is a separate, full-screen
# (480x320) asset, not a card blit -- shown after the belt loop's
# `finally: await self._engine.stop()` has ended the round's background
# tick task, so there's no live sprite_engine repaint left to fight over
# the frame and no dirty-tracking concern for it.
#
# ASSETS:
#   bakery/bg_bakery_480x320.bz        LE, kind 0, strip_h=8 -- the belt
#     board. sprite_engine composites drifting ingredients over this; the
#     card-sized region at (100,15,280,169) should be a flat/neutral colour
#     or a matching frame in this art (the recipe card blits on top of it
#     separately, at the same x=100,y=15 offset).
#   bakery/bgm_recipe-<name>_280x169.bz   BE, kind 1 -- one per recipe (6),
#     card-sized, shown while that recipe is active.
#   bakery/bgm_baked-<name>_480x320.bz    BE, kind 1 -- one per recipe (6),
#     FULL SCREEN (not a card blit) -- shown once the recipe is complete,
#     after the belt/engine has already stopped for the round, so there's
#     no live sprite_engine repaint left to fight over the frame.
#   bakery/bgm_result_480x320.bz       BE, kind 1 -- end-of-game screen.
#   static/bakery/spr_<ingredient>_96x96x1.sz   LE, kind 2, magenta-keyed --
#     main-screen belt sprite. One per ingredient (10): flour, egg, sugar,
#     butter, milk, chocolate, cheese, tomato-sauce, sprinkles, mushrooms.
#   static/bakery/sprb_<ingredient>_96x96x1.sz  BE, kind 3, opaque -- the
#     button-screen "parked ingredient" icon. Same 10 names.
#   menu/bgm_menu-bakery_480x320.bz, menu/btn_menu-bakery_280x240.bz --
#     carousel card/tile, same convention as every other game.
#
# MISSING ASSETS: a missing/invalid ingredient sprite drops that ingredient
# from the spawn pool for the round (same "degrade, don't crash" contract
# as Star Bonk!'s missing-character handling) -- if a NEEDED ingredient's
# sprite is missing, the ingredient stays part of the win condition but
# simply won't appear on the belt, so that recipe becomes uncompletable;
# rare enough (only on a broken/incomplete asset set) not to special-case
# further. A missing board/card/result falls back to a flat colour or the
# procedural splash, matching every other game.
#
# Button IDs (core/game_base.py): 0-3 = screen buttons, 4 = BACK/HOME.

import gc
import time
import asyncio
import random
import config
from core.game_base import BaseGame, GameResult, shuffle
from core.display_manager import rgb, WHITE, RED, GREEN, BLUE, YELLOW, DARK, BLACK
from core import game_cache
from core.sprite_engine import SpriteEngine, STRIP_H
from core.sprite_adapter import MainScreenAdapter, make_main_strip_renderer
from drivers import flash_assets
from drivers.touch import TOUCH_TAP
import games.bonk.game as _bonk

# ── Content ──────────────────────────────────────────────────────
INGREDIENTS = ("flour", "egg", "sugar", "butter", "milk", "chocolate",
               "cheese", "tomato-sauce", "sprinkles", "mushrooms")

RECIPES = {
    "cake":     ("flour", "egg", "sugar", "butter"),
    "cookies":  ("flour", "sugar", "butter", "chocolate"),
    "cupcake":  ("flour", "egg", "sugar", "sprinkles"),
    "pancakes": ("flour", "egg", "milk", "butter"),
    "pizza":    ("flour", "tomato-sauce", "cheese", "mushrooms"),
    "donut":    ("flour", "egg", "sugar", "chocolate"),
}
RECIPE_NAMES = tuple(RECIPES.keys())
ROUNDS_PER_GAME  = 3
DECOYS_PER_ROUND = 1     # see MEMORY NOTE above -- 4 needed + 1 decoy = 5
                         # sprites (~92KB), stays under the 96KB shared arena

ASSET_DIR   = "/assets/static/bakery/"           # Tier A: always resident
BOARD_PATH  = "/assets/bakery/bg_bakery_480x320.bz"        # Tier B
RESULT_PATH = "/assets/bakery/bgm_result_480x320.bz"       # Tier B
RECIPE_CARD_PATH = "/assets/bakery/bgm_recipe-%s_280x169.bz"
BAKED_CARD_PATH  = "/assets/bakery/bgm_baked-%s_480x320.bz"   # full screen, not
                                                               # a card blit --
                                                               # see _play_round
BACK_TILE_PATH   = "/assets/menu/btn_back_280x240.bz"      # shared across games
AGAIN_TILE_PATH  = "/assets/menu/btn_again_280x240.bz"     # shared across games

# ── Geometry ─────────────────────────────────────────────────────
ICON = 96
CARD_W, CARD_H = 280, 169
CARD_X = (config.MAIN_W - CARD_W) // 2   # 100
CARD_Y = 15                               # card occupies rows 15-183

# Belt track corners as measured off the board art: bottom-left (65,285),
# bottom-right (420,285). Items are bottom-aligned to y=285 and their
# left edge ranges over [BELT_X_LEFT, BELT_X_RIGHT - ICON] so the full
# 96x96 bbox never pokes outside the drawn track horizontally.
#
# Card/belt dirty-strip overlap, now closed: a 96px icon bottom-aligned
# to y=285 has its top row fixed at y=189 all round (only x ever moves),
# which sprite_engine always dirties as strip 23 (189 // STRIP_H, rows
# 184-191). CARD_H=169 puts the card's last row at 183 -- CARD_Y +
# CARD_H - 1 = 15+169-1 -- one row clear of strip 23, so render_dirty()
# (which repaints a dirty strip from raw board pixels across the FULL
# screen width, with no idea the card is blitted on top of it) never
# touches a row the card occupies. 200px and then 175px both left a
# real overlap here (26 rows, then 6); 169 is the first height with none.
BELT_X_LEFT  = 65
BELT_X_RIGHT = 420
BELT_SPRITE_Y = 285 - ICON                # 189, bottom-aligned to y=285
BELT_SLOTS = 4        # concurrent drifting ingredients
DRIFT_PX_PER_TICK = 5
BELT_TICK_MS = 90
LOOP_TICK_MS = 40      # input-poll granularity; independent of the belt tick
HIT_PAD = 20

BTN_ICON_X = (config.BTN_W - ICON) // 2
BTN_ICON_Y = (config.BTN_H - ICON) // 2

LEGEND_BG      = WHITE                    # correct (locked) slot tile
WRONG_BG       = rgb(70, 20, 20)          # wrong (removable) slot tile
LOCKED_BORDER  = rgb(60, 200, 90)         # green -- can't be cleared
REMOVABLE_BORDER = rgb(230, 150, 40)      # orange -- press to clear
HEADER_COLOR   = rgb(120, 60, 20)         # warm bakery brown
FALLBACK_BOARD_COLOR = rgb(90, 60, 30)
RESULT_SCORE_Y = 124
RESULT_STARS_Y = 152

_FALLBACK = (RED, BLUE, GREEN, YELLOW, rgb(200, 120, 0), rgb(150, 60, 200),
             rgb(0, 150, 150), rgb(180, 180, 0), rgb(120, 80, 40))


def _main_asset_path(name):
    return "%sspr_%s_%dx%dx1.sz" % (ASSET_DIR, name, ICON, ICON)


def _btn_asset_path(name):
    return "%ssprb_%s_%dx%dx1.sz" % (ASSET_DIR, name, ICON, ICON)


def _voice_file(name):
    return name.replace("-", "_") + ".wav"


class _FlatBackground:
    """Same convention as Star Bonk!'s placeholder -- fills every strip
    with one flat LE colour so the game stays testable before the real
    board art exists."""
    big_endian = False

    def __init__(self, w, h, strip_h, color565):
        self.w = w
        self.h = h
        self.strip_h = strip_h
        self.n_strips = (h + strip_h - 1) // strip_h
        self._lo = color565 & 0xFF
        self._hi = (color565 >> 8) & 0xFF

    def strip_rows(self, i):
        if i == self.n_strips - 1:
            r = self.h - i * self.strip_h
            return r if r else self.strip_h
        return self.strip_h

    def read_strip(self, i, buf):
        rows = self.strip_rows(i)
        row = bytes([self._lo, self._hi]) * self.w
        mv = memoryview(buf)
        off = 0
        for _ in range(rows):
            mv[off:off + len(row)] = row
            off += len(row)
        return rows

    def close(self):
        pass


class MagicBakeryGame(BaseGame):

    GAME_ID      = "bakery"
    TITLE        = "Magic Bakery"
    DESCRIPTION  = "Collect the right ingredients and bake!"
    ICON_FILE    = None
    MIN_AGE      = 4
    MAX_AGE      = 7
    USES_BUTTONS = (0, 1, 2, 3)
    USES_NAV     = False
    USES_COUNTDOWN = False     # each recipe's own reveal is its intro
    MENU_HEADER   = HEADER_COLOR
    MAX_SCORE     = ROUNDS_PER_GAME   # score = recipes completed (0-3)

    # ── Lifecycle ────────────────────────────────────────────────

    async def load(self):
        gc.collect()

        self._adapter = MainScreenAdapter(make_main_strip_renderer())
        self._adapter.open()

        # Small scratch arena for button icons + card/end-screen paints --
        # kept separate from flash_assets.arena, which holds the round's
        # persistent LE belt sprites. This USED to lazy-allocate its own
        # 32KB SpriteArena here, and that hit exactly the fragmentation
        # failure Bonk's own arena already fought and lost to once (see
        # games/bonk/game.py's module comment): "heap before bakery.load():
        # free=68176" / "allocating 32768 bytes" failed anyway -- plenty of
        # free heap, no single 32KB gap, because the other boot-seated
        # blocks (strip pool, flash_assets.arena, text scratch) are fixed
        # non-moving walls a non-compacting GC can't route around. Rather
        # than fight for a SECOND boot-time 32KB reservation (real risk of
        # blowing the boot budget instead -- see core/kernel.py's ordering
        # comment), just reuse Bonk's already boot-seated one: only one
        # game runs at a time, so nothing else needs it while Bakery does.
        _bonk.seat_scratch_arena()
        self._scratch_arena = _bonk._scratch_arena

        try:
            bg = game_cache.open_background(BOARD_PATH)
            if bg.big_endian:
                raise ValueError("board must be LE (kind 0)")
            engine = SpriteEngine(self._adapter, bg,
                                  screen_w=config.MAIN_W, screen_h=config.MAIN_H)
        except Exception as e:
            print("[bakery] board asset missing/invalid, using flat placeholder:", e)
            bg = _FlatBackground(config.MAIN_W, config.MAIN_H, STRIP_H,
                                 FALLBACK_BOARD_COLOR)
            engine = SpriteEngine(self._adapter, bg,
                                  screen_w=config.MAIN_W, screen_h=config.MAIN_H)
        self._bg = bg
        self._engine = engine

        await self.display.fill_all_btns(DARK)

    async def unload(self):
        try:
            self._bg.close()
        except Exception:
            pass
        try:
            self._adapter.close()
        except Exception:
            pass
        flash_assets.arena.reset()
        gc.collect()
        await super().unload()

    # ── Main loop ────────────────────────────────────────────────

    async def run(self) -> GameResult:
        self._running = True
        self.score = 0            # recipes completed this game
        self._total_elapsed_ms = 0
        self._best_elapsed_ms = None

        while True:
            recipes = list(RECIPE_NAMES)
            shuffle(recipes)
            recipes = recipes[:ROUNDS_PER_GAME]

            self.score = 0
            self._total_elapsed_ms = 0

            for recipe_no, recipe in enumerate(recipes, 1):
                if not self._running or await self.check_back():
                    self._running = False
                    break

                gc.collect()   # quiet point -- same discipline as Star Bonk!
                completed = await self._play_round(recipe, recipe_no)
                if not self._running:
                    break
                if completed:
                    self.score += 1

            if not self._running:
                break   # mid-game BACK/HOME -- exit immediately, no end screen

            if self.score == ROUNDS_PER_GAME:
                elapsed_s = self._total_elapsed_ms / 1000
                if self._best_elapsed_ms is None or self._total_elapsed_ms < self._best_elapsed_ms:
                    self._best_elapsed_ms = self._total_elapsed_ms

            choice = await self._end_screen()
            if choice == "back":
                break
            # "again" -- straight back into a fresh set of 3 random recipes

        return self._make_result()

    def _make_result(self) -> GameResult:
        result = super()._make_result()
        if self.score == ROUNDS_PER_GAME and self._total_elapsed_ms:
            result.time_s = self._total_elapsed_ms / 1000
        return result

    # ── One recipe round ─────────────────────────────────────────

    async def _play_round(self, recipe, recipe_no) -> bool:
        """Returns True if the recipe was completed, False on quit."""
        needed = RECIPES[recipe]
        pool = self._build_pool(needed)

        flash_assets.arena.reset()
        sheets = {}
        for name in pool:
            try:
                sheet = flash_assets.SpriteSheet(_main_asset_path(name))
                if sheet.big_endian:
                    raise ValueError("belt sprite must be LE (kind 2)")
                sheets[name] = sheet
            except Exception as e:
                print("[bakery] belt sprite load failed:", name, e)
                sheets[name] = None
        live_pool = [n for n in pool if sheets.get(n) is not None]

        self._slots = [None, None, None, None]
        for i in range(4):
            await self._paint_slot_empty(i)

        # Full clean board paint FIRST -- render_dirty() always repaints a
        # dirty strip from raw board pixels across the whole screen width,
        # with no idea anything's blitted on top of it. Doing this before
        # the card paint (not after, as this used to) means the card is
        # the last thing drawn and survives; doing it after would erase
        # the card immediately, since mark_all() dirties every strip.
        self._engine.mark_all()
        await self._engine.render_dirty()

        if not await self.display.paint_main_bg(
                RECIPE_CARD_PATH % recipe, arena=self._scratch_arena,
                x=CARD_X, y=CARD_Y):
            await self._show_card_fallback(recipe)

        if self.audio and self.audio.ready:
            await self.audio.play_voice("bake_%s.wav" % recipe, wait=True)
        await asyncio.sleep_ms(400)

        belt = self._spawn_belt(live_pool or pool, sheets)
        self._engine.start(tick_ms=BELT_TICK_MS)

        collected = set()
        touch_was_down = False
        round_start_ms = time.ticks_ms()   # setup/reveal above doesn't count
        quit_requested = False

        try:
            while len(collected) < len(needed) and self._running:
                if await self.check_back():
                    self._running = False
                    quit_requested = True
                    break

                for entry in belt:
                    entry["sprite"].move_by(-DRIFT_PX_PER_TICK, 0)
                    if entry["sprite"].x < BELT_X_LEFT:
                        self._respawn_belt_entry(entry, live_pool or pool, sheets)

                touch_down = self.buttons.touch_down
                if touch_down and not touch_was_down:
                    tx, ty = self.buttons.touch_pos or (0, 0)
                    hit = self._find_belt_hit(belt, tx, ty)
                    if hit is not None:
                        done = await self._handle_tap(
                            hit, belt, needed, collected, live_pool or pool, sheets)
                        if done:
                            break
                touch_was_down = touch_down

                try:
                    btn, evt = self.buttons._queue.get_nowait()
                    if evt == "press" and btn in (0, 1, 2, 3):
                        await self._on_button_press(btn)
                except Exception:
                    pass

                await asyncio.sleep_ms(LOOP_TICK_MS)
        finally:
            await self._engine.stop()

        if quit_requested:
            return False

        elapsed_ms = time.ticks_diff(time.ticks_ms(), round_start_ms)
        self._total_elapsed_ms += elapsed_ms

        # Full-screen reveal, not a card-rect blit -- the belt loop's
        # `finally: await self._engine.stop()` above has already ended the
        # background tick task, so there's no live sprite_engine repaint
        # left to fight over the frame; a plain full-screen paint_main_bg()
        # (default x=0,y=0) is all this needs.
        if await self.display.paint_main_bg(
                BAKED_CARD_PATH % recipe, arena=self._scratch_arena):
            pass
        else:
            await self._show_baked_fallback(recipe)

        if self.leds and self.leds.ready:
            self.leds.start_effect(self.leds.correct_flash())
        if self.audio and self.audio.ready:
            await self.audio.play_voice("well_done.wav", wait=True)
        await asyncio.sleep_ms(900)
        try:
            self.leds.stop_effect()
        except Exception:
            pass

        return True

    def _build_pool(self, needed):
        decoys_available = [n for n in INGREDIENTS if n not in needed]
        shuffle(decoys_available)
        pool = list(needed) + decoys_available[:DECOYS_PER_ROUND]
        shuffle(pool)
        return pool

    # ── Belt sprites ─────────────────────────────────────────────

    def _spawn_belt(self, pool, sheets):
        # Evenly space initial left-edges across [BELT_X_LEFT, BELT_X_RIGHT
        # - ICON] so every slot starts fully inside the visible track
        # instead of staggered off-screen (there's no off-screen anymore --
        # the whole belt lives within x=65..420).
        span = (BELT_X_RIGHT - ICON) - BELT_X_LEFT
        belt = []
        for i in range(BELT_SLOTS):
            name = random.choice(pool)
            sheet = sheets.get(name)
            x = (BELT_X_RIGHT - ICON) - (i * span) // max(1, BELT_SLOTS - 1)
            if sheet is not None:
                sprite = self._engine.add(sheet, x, BELT_SPRITE_Y)
            else:
                sprite = None
            belt.append({"sprite": sprite, "name": name, "x": x})
        return belt

    def _respawn_belt_entry(self, entry, pool, sheets):
        name = random.choice(pool)
        sheet = sheets.get(name)
        entry["name"] = name
        if entry["sprite"] is not None and sheet is not None:
            entry["sprite"].sheet = sheet
            entry["sprite"].w = sheet.w
            entry["sprite"].h = sheet.h
            entry["sprite"].frame = 0
            entry["sprite"].x = BELT_X_RIGHT - ICON
            entry["sprite"]._dirty = True

    def _find_belt_hit(self, belt, tx, ty):
        for entry in belt:
            s = entry["sprite"]
            if s is None:
                continue
            rect = (s.x - HIT_PAD, s.y - HIT_PAD, ICON + 2 * HIT_PAD, ICON + 2 * HIT_PAD)
            if self.tap_hit(tx, ty, rect):
                return entry
        return None

    # ── Tap / slot handling ──────────────────────────────────────

    async def _handle_tap(self, entry, belt, needed, collected, pool, sheets):
        """Returns True if this tap completed the recipe."""
        name = entry["name"]
        is_correct = name in needed and name not in collected
        slot_idx = self._first_empty_slot()

        if slot_idx is None:
            await self.show_wrong()
            return False

        await self._place_slot(slot_idx, name, correct=is_correct)
        if self.audio and self.audio.ready:
            await self.audio.play_voice(_voice_file(name), wait=True)

        if is_correct:
            collected.add(name)
            if self.leds and self.leds.ready:
                self.leds.start_effect(self.leds.correct_flash())
            if self.audio and self.audio.ready:
                await self.audio.play_sfx("correct.wav", wait=True)
            self._update_progress_leds(len(collected), len(needed))
        else:
            if self.audio and self.audio.ready:
                await self.audio.play_sfx("wrong.wav", wait=True)

        self._respawn_belt_entry(entry, pool, sheets)
        return len(collected) == len(needed)

    def _first_empty_slot(self):
        for i, slot in enumerate(self._slots):
            if slot is None:
                return i
        return None

    async def _place_slot(self, idx, name, correct):
        self._slots[idx] = {"name": name, "correct": correct}
        bg = LEGEND_BG if correct else WRONG_BG
        border = LOCKED_BORDER if correct else REMOVABLE_BORDER
        await self.display.fill_btn(idx, bg)
        self._scratch_arena.reset()
        try:
            sheet = flash_assets.SpriteSheet(_btn_asset_path(name),
                                             use_arena=self._scratch_arena)
            if not sheet.big_endian:
                raise ValueError("button icon must be BE (kind 3)")
            await self.display.blit_btn_buf(idx, sheet.frame(0), ICON, ICON,
                                            x=BTN_ICON_X, y=BTN_ICON_Y)
        except Exception as e:
            print("[bakery] button icon failed:", name, e)
            col = _FALLBACK[hash(name) % len(_FALLBACK)]
            await self.display.fill_btn(idx, col)
        self._scratch_arena.reset()
        await self.display.draw_btn_border(idx, border, thickness=8)

    async def _paint_slot_empty(self, idx):
        self._slots[idx] = None
        await self.display.fill_btn(idx, DARK)

    async def _on_button_press(self, idx):
        slot = self._slots[idx]
        if slot is not None and not slot["correct"]:
            await self._paint_slot_empty(idx)

    def _update_progress_leds(self, collected_n, needed_n):
        if not (self.leds and self.leds.ready):
            return
        n = self.leds.num_leds
        lit = round(n * collected_n / needed_n)
        for i in range(n):
            if i < lit:
                self.leds.set_pixel(i, 255, 180, 40)
            else:
                self.leds.set_pixel(i, 0, 0, 0)
        self.leds.show()

    # ── Fallback drawing (missing assets) ─────────────────────────

    async def _show_card_fallback(self, recipe):
        label = "Bake a " + recipe + "!"
        bg = rgb(60, 40, 15)
        await self.display.main.fill(bg, CARD_X, CARD_Y, CARD_W, CARD_H)
        tx = CARD_X + CARD_W // 2 - len(label) * 8
        await self.display.text_main(label, max(CARD_X, tx), CARD_Y + CARD_H // 2 - 8,
                                     WHITE, bg, scale=2)

    async def _show_baked_fallback(self, recipe):
        """BAKED_CARD_PATH is a full-screen (480x320) asset now, not a card
        blit -- fallback fills the whole main screen to match."""
        label = "Baked: " + recipe + "!"
        bg = rgb(60, 40, 15)
        await self.display.main.fill(bg, 0, 0, config.MAIN_W, config.MAIN_H)
        tx = config.MAIN_W // 2 - len(label) * 8
        await self.display.text_main(label, max(0, tx), config.MAIN_H // 2 - 8,
                                     WHITE, bg, scale=2)

    # ── End screen ───────────────────────────────────────────────

    async def _end_screen(self):
        try:
            self.leds.stop_effect()
        except Exception:
            pass

        if self.score == ROUNDS_PER_GAME:
            total_s = self._total_elapsed_ms / 1000
            score_str = "%d:%02d" % (int(total_s) // 60, int(total_s) % 60)
        else:
            score_str = "%d of %d baked" % (self.score, ROUNDS_PER_GAME)
        stars = self._stars_for(self.score)
        star_str = ("*" * stars) + ("-" * (3 - stars))

        if await self.display.paint_main_bg(RESULT_PATH, arena=self._scratch_arena):
            ssx = config.MAIN_W // 2 - len(score_str) * 8
            await self.display.text_main(
                score_str, ssx, RESULT_SCORE_Y, 0xEA16, WHITE, scale=2)
            stx = config.MAIN_W // 2 - len(star_str) * 12
            await self.display.text_main(
                star_str, stx, RESULT_STARS_Y, YELLOW, WHITE, scale=3)
        else:
            await self.display.show_splash("Bakery done!", score_str,
                                           bg_color=rgb(60, 30, 10))
            stx = config.MAIN_W // 2 - len(star_str) * 12
            await self.display.text_main(
                star_str, stx, 172, YELLOW, rgb(60, 30, 10), scale=3)

        if not await self.display.paint_btn_bg(3, BACK_TILE_PATH, arena=self._scratch_arena):
            await self._show_back_fallback(3)
        for idx in (0, 1, 2):
            if not await self.display.paint_btn_bg(idx, AGAIN_TILE_PATH, arena=self._scratch_arena):
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
                return "again"
            if evt != "press":
                continue
            if btn == 3 or btn == 4:
                return "back"
            if btn in (0, 1, 2):
                return "again"

    async def _show_back_fallback(self, idx):
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
        await self.display.text_btn(idx, label, max(0, lx),
                                    config.BTN_H // 2 - 4, WHITE, bg, scale=1)
