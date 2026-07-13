# games/match/game.py — Button Blasters
# Match It! — child presses the button whose screen matches the item shown
# on the main display. Items are IMAGE ICONS loaded from the SD card, in
# three category rounds.
#
# Structure (3 rounds, 6 matches each = 18 matches total, max score 18/18):
#   Round 1 : shapes   (circle, square, triangle, star, diamond, hexagon)
#   Round 2 : fruit    (apple, banana, orange, grapes, strawberry, watermelon)
#   Round 3 : animals  (cat, dog, cow, duck, frog, lion)
# Each round shows all six of its items as the target once (shuffled order),
# with three random distractors from the same category on the other buttons.
#
# ASSETS: /sd/games/match/img/<cat>_<item>_120x120.raw
#   raw RGB565 little-endian, 120x120 = 28,800 bytes each (18 files).
#   Transparent PNGs are BAKED onto ICON_BG at ffmpeg time (RGB565 has no
#   alpha), so each tile is already a finished 120x120 image. Fill each
#   surface with the SAME ICON_BG so the baked edges blend with no halo.
#
# LOADING: per-category RAM preload. Six icon buffers (~169KB) are allocated
#   ONCE in load() and REUSED for every category — never per-round, never
#   per-match (memory-conscious, matches the pre-allocate principle). At each
#   round start the six files are read into those buffers behind a "Get
#   ready!" splash; the ~5s SD read at 400kHz is hidden by the transition.
#   Reads use plain open()/readinto() exactly like drivers/audio.py — the
#   display driver's always-reinit restores 10MHz on the next blit, so the
#   game does NOT manage bus frequency itself.
#
# MISSING ASSET: falls back to a coloured placeholder tile (so the mechanic
#   is testable before all 18 PNGs exist) and prints the missing path.
#
# Button IDs (core/game_base.py): 0-3 = screen buttons, 4 = BACK/HOME.

import gc
import time
import asyncio
import random
import framebuf
import config
from core.game_base import BaseGame, GameResult
from core.display_manager import (rgb, WHITE, YELLOW, RED, GREEN, BLUE,
                                   CYAN, MAGENTA, ORANGE, DARK)

# ── Content ──────────────────────────────────────────────────────
ITEMS = {
    "shape":  ("circle", "square", "triangle", "star", "diamond", "hexagon"),
    "fruit":  ("apple", "banana", "orange", "grapes", "strawberry", "watermelon"),
    "animal": ("cat", "dog", "cow", "duck", "bird", "sheep"),
}
CATEGORIES        = ("shape", "fruit", "animal")   # round order
CATEGORY_LABEL    = {"shape": "Shapes", "fruit": "Fruit", "animal": "Animals"}
ITEMS_PER_CATEGORY = 6
MATCHES_PER_ROUND  = 6
MAX_SCORE          = len(CATEGORIES) * MATCHES_PER_ROUND   # 18

IMG_DIR = "/sd/games/match/img/"

# ── Appearance ───────────────────────────────────────────────────
# ICON_BG is the colour baked behind every icon at conversion time AND the
# colour each surface is filled with, so the anti-aliased edges blend cleanly.
# White reads as clean "cards" for ages 4-7; set to DARK to match the old look.
ICON_BG = WHITE

# ── Geometry ─────────────────────────────────────────────────────
ICON = 120
BTN_ICON_X  = (config.BTN_W  - ICON) // 2      # 240 -> 60
BTN_ICON_Y  = (config.BTN_H  - ICON) // 2      # 300 -> 90
MAIN_ICON_X = (config.MAIN_W - ICON) // 2      # 480 -> 180
MAIN_ICON_Y = (config.MAIN_H - ICON) // 2 + 20 # 320 -> 120

_FALLBACK = (RED, GREEN, BLUE, YELLOW, CYAN, MAGENTA)


def _shuffle(lst):
    # MicroPython random has choice() but not shuffle(); Fisher-Yates.
    for i in range(len(lst) - 1, 0, -1):
        j = random.randint(0, i)
        lst[i], lst[j] = lst[j], lst[i]


class ShapeMatchGame(BaseGame):

    GAME_ID      = "match"
    TITLE        = "Match It!"
    DESCRIPTION  = "Find the matching shape, fruit or animal!"
    ICON_FILE    = None
    MIN_AGE      = 4
    MAX_AGE      = 7
    USES_BUTTONS = (0, 1, 2, 3)
    USES_NAV     = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._icon_bufs = None      # six 120x120 RGB565 views borrowed from
        self._icon_map  = None      # the shared assets pool; name -> view

    # ── Lifecycle ────────────────────────────────────────────────

    async def load(self):
        # Borrow six 120x120 icon views from the shared image-load pool that
        # `assets` allocated ONCE at boot (freshest heap). No game-load
        # allocation → the fragmentation MemoryError can't happen here. The
        # views point into the shared block; we never free it (assets owns it).
        gc.collect()
        self._icon_bufs = self.assets.borrow_icons(ITEMS_PER_CATEGORY, ICON, ICON)
        self._icon_map = {}
        gc.collect()

        await self.display.clear_all()
        await self.display.fill_main(DARK)
        await self.display.text_main(
            self.TITLE, config.MAIN_W // 2 - len(self.TITLE) * 8,
            20, WHITE, DARK, scale=2)
        await self.display.fill_all_btns(DARK)

    async def run(self) -> GameResult:
        self._running = True
        self.score = 0

        await self.countdown(3)

        for cat in CATEGORIES:
            if not self._running:
                break
            if await self.check_back():
                break

            await self._show_category_intro(cat)
            await self._preload_category(cat)

            order = list(ITEMS[cat])
            _shuffle(order)                         # each item is target once

            for m in range(MATCHES_PER_ROUND):
                if await self.check_back():
                    self._running = False
                    break

                target = order[m]
                screen_items, correct_idx = self._layout_match(cat, target)
                await self._draw_match(target, screen_items)

                # Timestamp gate: only accept a press whose edge occurs AFTER
                # the match finished drawing, so an eager press made mid-draw
                # isn't consumed/dropped (hard-won; see _wait_answer).
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

        await self._end_screen()
        return self._make_result()

    async def unload(self):
        # Drop our views; the shared pool block stays alive on `assets` for
        # the next game to borrow.
        self._icon_bufs = None
        self._icon_map  = None
        gc.collect()
        await super().unload()

    # ── Category preload ─────────────────────────────────────────

    async def _show_category_intro(self, cat):
        await self.display.show_splash(
            "Get ready!", CATEGORY_LABEL[cat], bg_color=rgb(20, 30, 60))
        # Play the cue with wait=True so it finishes BEFORE the blocking SD
        # preload (which would otherwise starve the audio task's I2S feed).
        if self.audio and self.audio.ready:
            await self.audio.play_sfx("game_start.wav", wait=True)

    async def _preload_category(self, cat):
        # Read all six icons into the reusable buffers. Plain open()/readinto()
        # like audio; the display driver re-inits 10MHz on the next blit, so no
        # manual bus-freq handling here.
        self._icon_map = {}
        for i, name in enumerate(ITEMS[cat]):
            buf  = self._icon_bufs[i]
            path = "%s%s_%s_%dx%d.raw" % (IMG_DIR, cat, name, ICON, ICON)
            if not self._load_icon(path, buf):
                self._fill_fallback(buf, i, name)
                print("[match] missing asset, using fallback:", path)
            self._icon_map[name] = buf
            await asyncio.sleep_ms(0)               # let the loop breathe

    def _load_icon(self, path, buf):
        # Route through assets.read_file so the bus drops to 400kHz for the
        # read and restores display speed after (the shared-bus SD-read fix).
        # Do NOT open() directly here — a raw read runs at whatever speed the
        # last display draw left the bus (10MHz), which EIOs on this breadboard.
        try:
            return self.assets.read_file(path, into=buf) == len(buf)
        except OSError:
            return False

    def _fill_fallback(self, buf, idx, name):
        # Coloured placeholder so matches stay distinguishable without art.
        fb = framebuf.FrameBuffer(buf, ICON, ICON, framebuf.RGB565)
        fb.fill(ICON_BG)
        fb.fill_rect(12, 12, ICON - 24, ICON - 24, _FALLBACK[idx % len(_FALLBACK)])
        fb.text(name[:9].upper(), 10, ICON // 2 - 4, WHITE)

    # ── Match setup ──────────────────────────────────────────────

    def _layout_match(self, cat, target):
        items = ITEMS[cat]
        others = [x for x in items if x != target]
        _shuffle(others)
        distractors = others[:3]

        correct_idx = random.randint(0, 3)
        screen_items = [None, None, None, None]
        screen_items[correct_idx] = target
        d_iter = iter(distractors)
        for i in range(4):
            if screen_items[i] is None:
                screen_items[i] = next(d_iter)
        return screen_items, correct_idx

    # ── Rendering ────────────────────────────────────────────────

    async def _draw_match(self, target, screen_items):
        await self.display.fill_main(DARK)
        prompt = "Find the " + target + "!"
        await self.display.text_main(
            prompt, config.MAIN_W // 2 - len(prompt) * 8, 24,
            WHITE, DARK, scale=2)

        await self.display.main.blit_rgb565(
            memoryview(self._icon_map[target]),
            MAIN_ICON_X, MAIN_ICON_Y, ICON, ICON)
        await self.display.draw_score(self.score)

        for i, name in enumerate(screen_items):
            await self._draw_btn_icon(i, name)

    async def _draw_btn_icon(self, idx, name):
        # Fill with ICON_BG (matches the baked-in tile background) then blit.
        await self.display.fill_btn(idx, ICON_BG)
        await self.display.blit_btn_buf(
            idx, self._icon_map[name], ICON, ICON,
            x=BTN_ICON_X, y=BTN_ICON_Y)

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

    async def _end_screen(self):
        try:
            self.leds.stop_effect()
        except Exception:
            pass

        await self.display.show_splash(
            "You got", "%d of %d" % (self.score, MAX_SCORE),
            bg_color=rgb(10, 60, 20))

        # Any button, or auto-return after 4 seconds.
        self.buttons.clear()
        deadline = time.ticks_add(time.ticks_ms(), 4000)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            try:
                btn, evt = self.buttons._queue.get_nowait()
                if evt == "press":
                    break
            except Exception:
                pass
            await asyncio.sleep_ms(20)
