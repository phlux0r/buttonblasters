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
#   bonk/bg_bonk_480x320.bz      LE, kind 0, strip_h=8 — the main board.
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
from core.display_manager import (rgb, WHITE, RED, GREEN, BLUE, YELLOW, DARK,
                                  BLACK, seat_bg_scratch)
from core import game_cache
from core.sprite_engine import SpriteEngine, FlatBackground, STRIP_H
from core.sprite_adapter import MainScreenAdapter, make_main_strip_renderer
from drivers import flash_assets
from drivers.haptic import haptic

# ── Content ──────────────────────────────────────────────────────
TARGETS = ("wizard", "goblin", "star", "mushroom")
TARGET_POINTS = {"wizard": 1, "goblin": 2, "star": 3, "mushroom": 4}
ROUND_POOL_SIZES = (2, 3, 4)      # round 1..3 -- how many of the 4 are live
ROUND_HITS = 8                    # bonks per round (assumption -- tune freely)
TOTAL_HITS = ROUND_HITS * len(ROUND_POOL_SIZES)
# NOT max(TARGET_POINTS)*TOTAL_HITS (96) -- the player never chooses which
# target spawns, only whether they hit it in time, so a flawless run still
# only AVERAGES ~2.5 pts/hit (mean of 1,2,3,4) = ~60, not 96. A worst-case
# ceiling made 2-3 stars practically unreachable regardless of how well a
# child actually plays -- the score would keep improving but stars would
# look "stuck". Calibrate to the average-case perfect run instead.
MAX_SCORE = round(TOTAL_HITS * (sum(TARGET_POINTS.values()) / len(TARGET_POINTS)))

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
LEGEND_BG    = WHITE                 # populated-target tile bg -- matches
                                      # Match It!'s ICON_BG convention (icons
                                      # are baked opaque-on-white, so they
                                      # blend seamlessly on a white tile)
FALLBACK_BOARD_COLOR = rgb(30, 70, 40)   # flat meadow, used if the real
                                          # board asset is missing/invalid


def _main_asset_path(name):
    return "%sspr_%s_%dx%dx1.sz" % (ASSET_DIR, name, ICON, ICON)


def _btn_asset_path(name):
    return "%ssprb_%s_%dx%dx1.sz" % (ASSET_DIR, name, ICON, ICON)


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
    RESULT_PATH   = "/assets/bonk/bgm_result_480x320.bz"   # Tier B, like BOARD_PATH
    RESULT_FALLBACK_TITLE = "Great bonking!"

    # ── Lifecycle ────────────────────────────────────────────────

    async def load(self):
        gc.collect()

        # Acquire hardest-first: the strip buffer pool (currently ~37.5KB at
        # STRIP_H=8, two ~11.25KB CONTIGUOUS RGB666 blocks + two 7.5KB
        # RGB565 blocks — see drivers/strip_renderer.py for the STRIP_H
        # history) is still the biggest/most placement-sensitive ask in
        # this game's load(). Seat it FIRST, before any other new heap
        # allocation gets a chance to land in the middle of what would
        # otherwise be a large contiguous free run and split it.
        # MicroPython's GC here doesn't compact/move live objects, so once
        # something smaller stakes a claim it stays there for the rest of
        # the session — order matters, not just gc.collect() (which the
        # pool already calls on its own, right before allocating).
        # Historically confirmed the hard way: loading it after the legend
        # arena produced a real MemoryError on hardware ("rgb666[1] did not
        # seat") despite ~200KB free overall.
        self._adapter = MainScreenAdapter(make_main_strip_renderer())
        self._adapter.open()   # seats the strip buffer pool

        # Persistent LE sprite sheets for the main-screen engine — small
        # enough (4 x 18.4KB = ~74KB) to keep all 4 resident in the global
        # arena for the whole game, unlike Match's per-match reload (which
        # exists because Match rotates through 18 icons, not 4). Writes
        # into the arena's already-seated 96KB buffer (boot-time alloc via
        # flash_assets.init()), not a new heap allocation, so it's safe
        # after the pool regardless of ordering.
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

        # Button-legend icons (BE, opaque) decode into the display
        # manager's boot-seated scratch arena — NOT the shared
        # flash_assets.arena above, which holds this game's LE sprites for
        # the whole session and whose reset() is all-or-nothing.
        # paint_main_bg()/paint_btn_bg() default to that same scratch
        # arena, so the end-screen paints can't clobber the sprites either.
        self._scratch_arena = seat_bg_scratch()
        self._scratch_arena.reset()

        try:
            bg = game_cache.open_background(BOARD_PATH)
            if bg.big_endian:
                raise ValueError("board must be LE (kind 0)")
            engine = SpriteEngine(self._adapter, bg,
                                  screen_w=config.MAIN_W, screen_h=config.MAIN_H)
        except Exception as e:
            print("[bonk] board asset missing/invalid, using flat placeholder:", e)
            bg = FlatBackground(config.MAIN_W, config.MAIN_H, STRIP_H,
                                 FALLBACK_BOARD_COLOR)
            engine = SpriteEngine(self._adapter, bg,
                                  screen_w=config.MAIN_W, screen_h=config.MAIN_H)
        self._bg = bg
        self._engine = engine

        await self.display.fill_all_btns(DARK)

    async def run(self) -> GameResult:
        self._running = True
        self.score = 0
        self._session_best = 0   # best round-set score THIS session -- "Play
                                  # Again" resets self.score, so without this
                                  # only your LAST attempt before quitting
                                  # would ever be reported, even if an
                                  # earlier attempt this session scored higher

        if self.USES_COUNTDOWN:
            await self.countdown(3)   # only ever fires once — never on replay

        while True:
            self._hits = 0   # drives the speed-up curve, whole-game total

            for round_no in range(1, len(ROUND_POOL_SIZES) + 1):
                if not self._running or self.check_back():
                    self._running = False
                    break

                # Quiet-point collect: _bonk_feedback() churns a fresh 4KB
                # buffer + I2S object per hit (drivers/audio.py), and this
                # port's GC is non-moving mark-and-sweep — those dead
                # objects sit as unreclaimed, unmerged holes until the next
                # collect. Confirmed on hardware: a full playthrough hit
                # "MemoryError: memory allocation failed, allocating 8192
                # bytes" mid-round without this. Once per round (no
                # audio/display/sprite work in flight here), matching the
                # "collect at a quiet moment" discipline used elsewhere in
                # this codebase (load()/unload(), StripBufferPool).
                gc.collect()

                pool = self._pick_pool(ROUND_POOL_SIZES[round_no - 1])
                await self._show_round_intro(round_no)

                self._engine.mark_all()
                await self._engine.render_dirty()
                await self._paint_target_buttons(pool)
                await self._draw_header(round_no)

                for _ in range(ROUND_HITS):
                    if self.check_back():
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

            self._session_best = max(self._session_best, self.score)
            choice = await self._end_screen()
            if choice == "back":
                break
            self.score = 0   # "again" — straight back into round 1

        # Report the best completed round-set this session, not just
        # whatever self.score happens to be at the moment of quitting (which
        # is 0/low if BACK was pressed mid-round on a "Play Again" replay,
        # even though an earlier attempt this session scored higher).
        self.score = max(self.score, self._session_best)
        return self._make_result()

    async def unload(self):
        try:
            self._bg.close()
        except Exception:
            pass
        try:
            self._adapter.close()   # detaches from the shared strip pool
                                     # (persistent now, not freed here),
                                     # restores display freq
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
        # Custom draw, not display.show_splash() — that helper's scale is
        # fixed (title=2, subtitle=1) and shared by every game; bumping it
        # there would resize Match's/other games' splashes too. Bonk wants
        # this specific announcement bigger.
        bg = rgb(20, 10, 60)
        await self.display.fill_main(bg)
        title = "Round %d" % round_no
        tscale = 4
        tx = config.MAIN_W // 2 - len(title) * 4 * tscale
        await self.display.text_main(title, tx, 100, WHITE, bg, scale=tscale)
        sub = "Get ready!"
        sscale = 2
        sx = config.MAIN_W // 2 - len(sub) * 4 * sscale
        await self.display.text_main(sub, sx, 180, YELLOW, bg, scale=sscale)

        if self.audio and self.audio.ready:
            await self.audio.play_sfx("game_start.wav", wait=True)
        await asyncio.sleep_ms(INTRO_HOLD_MS)

    async def _paint_target_buttons(self, pool):
        for i, name in enumerate(TARGETS):
            if name not in pool:
                await self.display.fill_btn(i, BLACK)
                continue
            await self.display.fill_btn(i, LEGEND_BG)
            self._scratch_arena.reset()
            try:
                sheet = flash_assets.SpriteSheet(_btn_asset_path(name),
                                                 use_arena=self._scratch_arena)
                if not sheet.big_endian:
                    raise ValueError("legend icon must be BE (kind 3)")
                await self.display.blit_btn_buf(i, sheet.frame(0), ICON, ICON,
                                                x=BTN_ICON_X, y=BTN_ICON_Y)
            except Exception as e:
                print("[bonk] legend icon failed:", name, e)
                col = _FALLBACK[i % len(_FALLBACK)]
                await self.display.fill_btn(i, col)
        self._scratch_arena.reset()

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

        # Randomised pre-spawn delay (0-1500ms) so targets don't appear in
        # an instant, metronomic back-to-back rhythm -- some anticipation,
        # not just random position/type. Range deliberately does NOT scale
        # with the difficulty ramp (_current_ttl) so the two unpredictability
        # sources don't compound into something too frantic by round 3.
        if not await self._wait_before_spawn(random.randint(0, 1500)):
            return False   # quit during the delay

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
            await self._bonk_feedback()
        return True

    async def _wait_before_spawn(self, delay_ms) -> bool:
        """Idle for delay_ms before the next spawn, staying responsive to
        BACK/HOME so a kid mashing it doesn't have to wait out the delay
        first. Returns False only on quit — same convention as
        _wait_hit_or_timeout below."""
        if delay_ms <= 0:
            return True
        self.buttons.clear()
        deadline_ms = time.ticks_add(time.ticks_ms(), delay_ms)
        while True:
            if time.ticks_diff(deadline_ms, time.ticks_ms()) <= 0:
                return True
            ev = self.buttons.poll()
            if ev is None:
                await asyncio.sleep_ms(15)
                continue
            btn, evt = ev
            if btn == 4 and evt == "press":
                self.quit()
                return False
            # Other events (stray touch, screen buttons) are just drained —
            # nothing to hit yet during this delay.

    async def _wait_hit_or_timeout(self, x, y, deadline_ms):
        self.buttons.clear()
        rect = (x - HIT_PAD, y - HIT_PAD, ICON + 2 * HIT_PAD, ICON + 2 * HIT_PAD)
        while True:
            if time.ticks_diff(deadline_ms, time.ticks_ms()) <= 0:
                return False

            # Live touch polling, not the discrete TOUCH_TAP queue event —
            # TOUCH_TAP only fires on finger-lift and is dropped entirely if
            # held past LONG_PRESS_MS or dragged past TAP_MAX_TRAVEL, both
            # common for a 4-7yo stabbing at a fast-moving target. Checking
            # touch_down/touch_pos directly catches a hit the instant a
            # finger lands in the target zone, whether or not it's ever
            # lifted cleanly, and needs no debounce of its own since a miss
            # just keeps the loop going until the real deadline.
            if self.buttons.touch_down:
                tx, ty = self.buttons.touch_pos or (0, 0)
                if self.tap_hit(tx, ty, rect):
                    return True

            ev = self.buttons.poll()
            if ev is None:
                await asyncio.sleep_ms(15)
                continue
            btn, evt = ev
            if btn == 4 and evt == "press":
                self.quit()
                return "quit"
            # Discrete touch events (TOUCH_TAP/SWIPE/LONG_PRESS) are just
            # drained here so they don't pile up in the queue — live polling
            # above already owns hit detection.

    async def _bonk_feedback(self):
        # LED (non-blocking, PIO — no SPI0) and haptic (fire-and-forget GPIO
        # pulse — no SPI0) can safely overlap the next target's render.
        # Audio is AWAITED, not fire-and-forget: correct.wav most likely
        # resolves via the /sd/audio/sfx/ fallback (no Tier B audio baked
        # for this game yet), and drivers/audio.py reads the card WITHOUT
        # the SPI0 bus lock by design. The sprite engine's render now holds
        # that lock per strip, but a lock can't protect against a reader
        # that never takes it — so a fire-and-forget clip's SD read could
        # still overlap the NEXT target's render (confirmed on hardware as
        # screen tearing right when the next target appeared, back when
        # neither side locked). Awaiting the clip keeps them sequential.
        if self.leds and self.leds.ready:
            self.leds.start_effect(self.leds.correct_flash())
        if haptic.ready:
            asyncio.create_task(_guarded(haptic.double_pulse()))
        if self.audio and self.audio.ready:
            await self.audio.play_sfx("correct.wav", wait=True)

    # ── End screen ────────────────────────────────────────────────

    async def _end_screen(self):
        return await self.show_end_screen("%d pts" % self.score)

