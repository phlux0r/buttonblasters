# games/bonk/game.py — Button Blasters
# Star Bonk! — touch-tap reaction game. One target pops up at a random spot
# on the main screen; tap it to score before it disappears.
#
# Structure (3 rounds, ROUND_HITS bonks each = 24 total):
#   Round 1: pool of 2 target types (randomly chosen from the 4)
#   Round 2: pool of 3 target types
#   Round 3: pool of all 4 target types
# Difficulty scales the VARIETY of characters in play, not how many are on
# screen at once — one target shows at a time. The button screens are the
# "which characters are live this round" legend: populated with that
# character's icon if it's in the pool, black if not.
#
# A target's type is chosen at random from the round's pool on each spawn.
# Missing a target (timeout) is NOT penalised — it just disappears and a
# new one spawns elsewhere, matching this console's low-pressure design for
# ages 4-7. SPEED: the reaction deadline shrinks every SPEEDUP_EVERY hits
# (a running total across the whole game, not reset per round), floored at
# MIN_TTL_MS.
#
# RENDERING: unlike Match It!'s direct blit_rgb565 (opaque icon over a
# static board, always the same spot), a target here pops up at a genuinely
# random position every spawn and must cleanly reveal the real board
# underneath when it disappears. That's exactly what core/sprite_engine.py
# + drivers/strip_renderer.py were built for — LE background + LE
# magenta-keyed sprites, dirty-strip compositing — so this is the first
# game to actually wire them up (see core/sprite_adapter.make_main_strip_
# renderer). Each spawn is engine.add(sheet, x, y); each despawn is
# engine.remove(sprite) — the engine's own dirty-rect tracking handles the
# erase-and-reveal, no manual background patching needed.
#
# Button-screen legend icons are a SEPARATE, simpler asset: opaque BE
# (kind 3), same convention as Match's icons, drawn with the plain
# blit_btn_buf path — no colour-key/engine needed for a static per-round
# icon. This means each character needs TWO baked sprites (see ASSETS).
#
# ASSETS (see documents/HARDWARE_NOTES.md's Star Bonk section for the full
# spec — endianness/colour-key mistakes here fail loudly, not silently):
#   bonk/spr_<name>_96x96x1.sz   LE, kind 2, magenta-keyed (0xF81F)  — the
#     main-screen target sprite_engine reads. One file per character:
#     wizard, goblin, star, mushroom.
#   bonk/sprb_<name>_96x96x1.sz  BE, kind 3, opaque — the button-screen
#     legend icon. Same 4 names.
#   bonk/bg_bonk_480x320.bz      LE, kind 0, strip_h=32 — the main board.
#     Can be fully illustrated everywhere (sprite_engine reveals real
#     pixels on despawn, no flat-colour play-zone constraint).
#   menu/bgm_menu-bonk_480x320.bz  BE, kind 1 — menu card (optional;
#     core/menu.py falls back to a procedural card if missing).
#
# MISSING ASSETS: a missing/invalid character sprite drops that character
# from the spawn pool (falls back to fewer live types rather than crashing).
# A missing/invalid board falls back to a flat in-memory colour so the
# mechanic stays testable before bg_bonk_480x320.bz is baked.
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
from drivers.haptic import haptic

# ── Content ──────────────────────────────────────────────────────
TARGETS = ("wizard", "goblin", "star", "mushroom")
TARGET_POINTS = {"wizard": 1, "goblin": 2, "star": 3, "mushroom": 4}
ROUND_POOL_SIZES = (2, 3, 4)      # round 1..3 -- how many of the 4 are live
ROUND_HITS = 8                    # bonks per round (assumption -- tune freely)
TOTAL_HITS = ROUND_HITS * len(ROUND_POOL_SIZES)
MAX_SCORE = TOTAL_HITS * max(TARGET_POINTS.values())   # generous ceiling

ASSET_DIR = "/assets/static/bonk/"          # Tier A: small, always resident
BOARD_PATH = "/assets/bonk/bg_bonk_480x320.bz"   # Tier B: SD-installed at load

# ── Geometry ─────────────────────────────────────────────────────
ICON = 96
HEADER_H = 44
BTN_ICON_X = (config.BTN_W - ICON) // 2
BTN_ICON_Y = (config.BTN_H - ICON) // 2
HIT_PAD = 24   # "tap anywhere NEAR the target" -- generous tolerance for kids

_FALLBACK = (RED, GREEN, BLUE, YELLOW)

# ── Timing / difficulty ──────────────────────────────────────────
BASE_TTL_MS   = 2000
TTL_STEP_MS   = 200
MIN_TTL_MS    = 700
SPEEDUP_EVERY = 10
INTRO_HOLD_MS = 400

# ── Appearance ───────────────────────────────────────────────────
HEADER_COLOR = rgb(40, 20, 90)     # deep purple HUD band
LEGEND_BG    = DARK                 # idle colour for an unpopulated button
FALLBACK_BOARD_COLOR = rgb(30, 70, 40)   # flat meadow, used if the real
                                          # board asset is missing/invalid

REPLAY_TILE_PATH = "/assets/menu/btn_menu-bonk_300x240.bz"   # own menu tile,
                                                              # reused, 0 extra KB
BACK_TILE_PATH   = "/assets/menu/btn_back_300x240.bz"        # shared across games


def _main_asset_path(name):
    return "%sspr_%s_%dx%dx1.sz" % (ASSET_DIR, name, ICON, ICON)


def _btn_asset_path(name):
    return "%ssprb_%s_%dx%dx1.sz" % (ASSET_DIR, name, ICON, ICON)


class _FlatBackground:
    """Background-compatible stub filling every strip with one flat RGB565
    colour (LE). Used only if bg_bonk_480x320.bz is missing/invalid, so
    Star Bonk stays playable/testable before the real art is baked —
    mirrors the "coloured placeholder" fallback Match It! uses per-icon."""
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


async def _guarded(coro):
    # Fire-and-forget bonk-feedback tasks swallow exceptions silently
    # otherwise (documented gotcha — see HARDWARE_NOTES.md).
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print("[bonk] feedback task error:", e)


class StarBonkGame(BaseGame):

    GAME_ID      = "bonk"
    TITLE        = "Star Bonk!"
    DESCRIPTION  = "Tap the target fast before it disappears!"
    ICON_FILE    = None
    MIN_AGE      = 4
    MAX_AGE      = 7
    USES_BUTTONS = ()          # touch-primary; buttons are a passive legend
    USES_NAV     = False
    USES_COUNTDOWN = True      # reaction game -- keep the 3-2-1 (BaseGame default)
    MENU_HEADER   = HEADER_COLOR
    MAX_SCORE     = MAX_SCORE

    # ── Lifecycle ────────────────────────────────────────────────

    async def load(self):
        gc.collect()

        # Persistent LE sprite sheets for the main-screen engine — small
        # enough (4 x 18.4KB = ~74KB) to keep all 4 resident in the global
        # arena for the whole game, unlike Match's per-match reload (which
        # exists because Match rotates through 18 icons, not 4).
        flash_assets.arena.reset()
        self._sheets = {}
        for name in TARGETS:
            try:
                sheet = flash_assets.SpriteSheet(_main_asset_path(name))
                if sheet.big_endian:
                    raise ValueError("main sprite must be LE (kind 2)")
                self._sheets[name] = sheet
            except Exception as e:
                print("[bonk] main sprite load failed:", name, e)
                self._sheets[name] = None

        # Small SEPARATE arena for the button-legend icons (BE, opaque) —
        # kept apart from the global arena because that one holds the LE
        # sprites for the whole game and arena.reset() is all-or-nothing.
        self._legend_arena = flash_assets.SpriteArena(20 * 1024)

        self._adapter = MainScreenAdapter(make_main_strip_renderer())
        self._adapter.open()   # seats the 150KB strip buffer pool

        try:
            bg = game_cache.open_background(BOARD_PATH)
            if bg.big_endian:
                raise ValueError("board must be LE (kind 0)")
            engine = SpriteEngine(self._adapter, bg,
                                  screen_w=config.MAIN_W, screen_h=config.MAIN_H)
        except Exception as e:
            print("[bonk] board asset missing/invalid, using flat placeholder:", e)
            bg = _FlatBackground(config.MAIN_W, config.MAIN_H, STRIP_H,
                                 FALLBACK_BOARD_COLOR)
            engine = SpriteEngine(self._adapter, bg,
                                  screen_w=config.MAIN_W, screen_h=config.MAIN_H)
        self._bg = bg
        self._engine = engine

        await self.display.fill_all_btns(DARK)

    async def run(self) -> GameResult:
        self._running = True
        self.score = 0

        if self.USES_COUNTDOWN:
            await self.countdown(3)   # only ever fires once — never on replay

        while True:
            self._hits = 0   # drives the speed-up curve, whole-game total

            for round_no in range(1, len(ROUND_POOL_SIZES) + 1):
                if not self._running or await self.check_back():
                    self._running = False
                    break

                pool = self._pick_pool(ROUND_POOL_SIZES[round_no - 1])
                await self._show_round_intro(round_no)

                self._engine.mark_all()
                await self._engine.render_dirty()
                await self._paint_target_buttons(pool)
                await self._draw_header(round_no)

                for _ in range(ROUND_HITS):
                    if await self.check_back():
                        self._running = False
                        break
                    if not await self._spawn_and_wait(pool):
                        self._running = False
                        break
                    await self.display.draw_score(self.score, color=WHITE,
                                                  bg=HEADER_COLOR)

                if not self._running:
                    break

            if not self._running:
                break   # mid-game BACK/HOME — exit immediately, no end screen

            choice = await self._end_screen()
            if choice == "back":
                break
            self.score = 0   # "again" — straight back into round 1

        return self._make_result()

    async def unload(self):
        try:
            self._bg.close()
        except Exception:
            pass
        try:
            self._adapter.close()   # releases the 150KB pool, restores freq
        except Exception:
            pass
        flash_assets.arena.reset()
        gc.collect()
        await super().unload()

    # ── Round setup ──────────────────────────────────────────────

    def _pick_pool(self, n):
        pool = list(TARGETS)
        shuffle(pool)
        return pool[:n]

    async def _show_round_intro(self, round_no):
        await self.display.show_splash("Round %d" % round_no, "Get ready!",
                                       bg_color=rgb(20, 10, 60))
        if self.audio and self.audio.ready:
            await self.audio.play_sfx("game_start.wav", wait=True)
        await asyncio.sleep_ms(INTRO_HOLD_MS)

    async def _paint_target_buttons(self, pool):
        for i, name in enumerate(TARGETS):
            if name not in pool:
                await self.display.fill_btn(i, BLACK)
                continue
            await self.display.fill_btn(i, LEGEND_BG)
            self._legend_arena.reset()
            try:
                sheet = flash_assets.SpriteSheet(_btn_asset_path(name),
                                                 use_arena=self._legend_arena)
                if not sheet.big_endian:
                    raise ValueError("legend icon must be BE (kind 3)")
                await self.display.blit_btn_buf(i, sheet.frame(0), ICON, ICON,
                                                x=BTN_ICON_X, y=BTN_ICON_Y)
            except Exception as e:
                print("[bonk] legend icon failed:", name, e)
                col = _FALLBACK[i % len(_FALLBACK)]
                await self.display.fill_btn(i, col)
        self._legend_arena.reset()

    async def _draw_header(self, round_no):
        await self.display.main.fill(HEADER_COLOR, 0, 0, config.MAIN_W, HEADER_H)
        label = "ROUND %d/%d" % (round_no, len(ROUND_POOL_SIZES))
        await self.display.text_main(label, 12, 14, WHITE, HEADER_COLOR, scale=2)
        await self.display.draw_score(self.score, color=WHITE, bg=HEADER_COLOR)

    # ── Spawn / hit ──────────────────────────────────────────────

    def _current_ttl(self):
        steps = self._hits // SPEEDUP_EVERY
        return max(MIN_TTL_MS, BASE_TTL_MS - steps * TTL_STEP_MS)

    async def _spawn_and_wait(self, pool) -> bool:
        """Spawn one target, wait for a hit/timeout/quit, despawn it.
        Returns False only on quit (BACK/HOME)."""
        live_pool = [t for t in pool if self._sheets.get(t) is not None]
        if not live_pool:
            return True   # nothing loadable for this round — skip the slot

        name  = random.choice(live_pool)
        sheet = self._sheets[name]
        x = random.randint(0, config.MAIN_W - ICON)
        y = random.randint(HEADER_H, config.MAIN_H - ICON)

        sprite = self._engine.add(sheet, x, y)
        await self._engine.render_dirty()

        deadline = time.ticks_add(time.ticks_ms(), self._current_ttl())
        result = await self._wait_hit_or_timeout(x, y, deadline)

        self._engine.remove(sprite)
        await self._engine.render_dirty()

        if result == "quit":
            return False
        if result:
            self._hits += 1
            self.score += TARGET_POINTS[name]
            asyncio.create_task(_guarded(self._bonk_feedback()))
        return True

    async def _wait_hit_or_timeout(self, x, y, deadline_ms):
        self.buttons.clear()
        rect = (x - HIT_PAD, y - HIT_PAD, ICON + 2 * HIT_PAD, ICON + 2 * HIT_PAD)
        while True:
            if time.ticks_diff(deadline_ms, time.ticks_ms()) <= 0:
                return False
            try:
                btn, evt = self.buttons._queue.get_nowait()
            except Exception:
                await asyncio.sleep_ms(15)
                continue
            if btn == 4 and evt == "press":
                self.quit()
                return "quit"
            if btn == TOUCH_TAP and evt == "tap":
                tx, ty = self.buttons.touch_pos or (0, 0)
                if self.tap_hit(tx, ty, rect):
                    return True
                # miss — keep waiting, same target still live

    async def _bonk_feedback(self):
        if self.leds and self.leds.ready:
            self.leds.start_effect(self.leds.correct_flash())
        if self.audio and self.audio.ready:
            await self.audio.play_sfx("correct.wav", wait=True)
        if haptic.ready:
            await haptic.double_pulse()

    # ── End screen ────────────────────────────────────────────────

    async def _end_screen(self):
        try:
            self.leds.stop_effect()
        except Exception:
            pass

        score_str = "%d pts" % self.score
        await self.display.show_splash("Great bonking!", score_str,
                                       bg_color=rgb(10, 60, 20))

        if not await self.display.paint_btn_bg(0, BACK_TILE_PATH):
            await self._show_back_fallback(0)
        for idx in (1, 2, 3):
            if not await self.display.paint_btn_bg(idx, REPLAY_TILE_PATH):
                await self._show_replay_fallback(idx)

        # All drawing done — now the cheer, so playback doesn't overlap any
        # SPI writes (same rule as Match It!'s end screen).
        await self.announce_round_complete()

        return await self._wait_end_choice()

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
            if btn == 0 or btn == 4:
                return "back"
            if btn in (1, 2, 3):
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
