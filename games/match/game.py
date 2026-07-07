# games/match/game.py — Button Blasters
# Shape Match — child presses the button whose screen matches the item
# shown on the main display. Items are shapes, then letters, then numbers,
# in a MIXED POOL that expands as the 8 rounds progress.
#
# Content progression (8 rounds total):
#   rounds 1-2 : base shapes (circle, square, triangle, star)
#   rounds 3-4 : + extra shapes (diamond, pentagon, hexagon)
#   rounds 5-6 : + letters A-H
#   rounds 7-8 : + numbers 1-9
# The pool is cumulative and picked at random (mixed), always >= 4 items.
#
# Behaviour:
#   - Correct FIRST press  -> score +1, show_correct(), advance
#   - Wrong press          -> reveal the correct button (green border) +
#                             wrong feedback, advance, NO score
#   - Score counts only correct-on-first-try (perfect game = 8/8)
#   - End screen: "You got X of 8", waits for any button, auto-returns
#     after 4s. BACK/HOME return to the menu (handled by kernel loop).
#
# MEMORY: one 160x160 shape buffer (~50KB) + one 8x8 glyph temp (128B),
# both allocated ONCE in load() and reused. No per-round allocation.
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
from games.match.shapes_draw import render, render_glyph

# ── Colours ──────────────────────────────────────────────────────
SHAPE_COLORS = {
    "circle":   RED,
    "square":   BLUE,
    "triangle": GREEN,
    "star":     YELLOW,
    "diamond":  CYAN,
    "pentagon": MAGENTA,
    "hexagon":  ORANGE,
}
GLYPH_PALETTE = [RED, GREEN, BLUE, YELLOW, CYAN, MAGENTA, ORANGE, WHITE]

# ── Content tiers (item = (kind, value)) ─────────────────────────
_BASE    = [("shape", s) for s in ("circle", "square", "triangle", "star")]
_EXTRA   = [("shape", s) for s in ("diamond", "pentagon", "hexagon")]
_LETTERS = [("glyph", c) for c in "ABCDEFGH"]
_NUMBERS = [("glyph", c) for c in "123456789"]


def _pool_for_round(rnum):        # rnum is 1-based
    pool = list(_BASE)
    if rnum >= 3:
        pool += _EXTRA
    if rnum >= 5:
        pool += _LETTERS
    if rnum >= 7:
        pool += _NUMBERS
    return pool


# ── Geometry ─────────────────────────────────────────────────────
SHAPE_BOX   = 160
SHAPE_SIZE  = 150
GLYPH_SCALE = 16                  # 8*16 = 128px glyph inside the 160 box

BTN_BLIT_X  = (config.BTN_W  - SHAPE_BOX) // 2      # 240 -> 40
BTN_BLIT_Y  = (config.BTN_H  - SHAPE_BOX) // 2      # 300 -> 70
MAIN_BLIT_X = (config.MAIN_W - SHAPE_BOX) // 2      # 480 -> 160
MAIN_BLIT_Y = (config.MAIN_H - SHAPE_BOX) // 2 + 20 # 320 -> 100

NUM_ROUNDS = 8


def _shuffle(lst):
    # MicroPython random has choice() but not shuffle(); Fisher-Yates.
    for i in range(len(lst) - 1, 0, -1):
        j = random.randint(0, i)
        lst[i], lst[j] = lst[j], lst[i]


class ShapeMatchGame(BaseGame):

    GAME_ID      = "match"
    TITLE        = "Shape Match"
    DESCRIPTION  = "Find the matching shape, letter or number!"
    ICON_FILE    = None
    MIN_AGE      = 4
    MAX_AGE      = 7
    USES_BUTTONS = (0, 1, 2, 3)
    USES_NAV     = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.round_num     = 0
        self._shape_buf    = None
        self._shape_fb     = None
        self._glyph_tmp    = None
        self._glyph_tmp_fb = None

    # ── Lifecycle ────────────────────────────────────────────────

    async def load(self):
        gc.collect()
        self._shape_buf = bytearray(SHAPE_BOX * SHAPE_BOX * 2)
        self._shape_fb  = framebuf.FrameBuffer(
            self._shape_buf, SHAPE_BOX, SHAPE_BOX, framebuf.RGB565)
        self._glyph_tmp = bytearray(8 * 8 * 2)
        self._glyph_tmp_fb = framebuf.FrameBuffer(
            self._glyph_tmp, 8, 8, framebuf.RGB565)
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
        self.round_num = 0

        await self.countdown(3)

        while self._running and self.round_num < NUM_ROUNDS:
            if await self.check_back():
                break

            round_no = self.round_num + 1
            target, screen_items, correct_idx = self._new_round(round_no)
            await self._draw_round(target, screen_items)

            # Timestamp gate: only accept presses whose edge occurs AFTER
            # the round has finished drawing, so an eager press made while
            # the shapes are still rendering doesn't get consumed/dropped.
            gate_ms = time.ticks_ms()
            pressed = await self._wait_answer(gate_ms)
            if pressed == "quit":
                break

            if pressed == correct_idx:
                self.score += 1
                await self.show_correct()
            else:
                await self._reveal_correct(correct_idx)

            self.round_num += 1

        await self._end_screen()
        return self._make_result()

    async def unload(self):
        self._shape_fb = self._shape_buf = None
        self._glyph_tmp_fb = self._glyph_tmp = None
        gc.collect()
        await super().unload()

    # ── Round setup ──────────────────────────────────────────────

    def _new_round(self, round_no):
        pool   = _pool_for_round(round_no)
        target = random.choice(pool)
        distractors = [x for x in pool if x != target]
        _shuffle(distractors)
        distractors = distractors[:3]

        correct_idx = random.randint(0, 3)
        screen_items = [None, None, None, None]
        screen_items[correct_idx] = target
        d_iter = iter(distractors)
        for i in range(4):
            if screen_items[i] is None:
                screen_items[i] = next(d_iter)

        return target, screen_items, correct_idx

    # ── Rendering ────────────────────────────────────────────────

    def _label(self, item):
        return item[1]

    def _item_color(self, item):
        kind, val = item
        if kind == "shape":
            return SHAPE_COLORS.get(val, WHITE)
        return GLYPH_PALETTE[ord(val) % len(GLYPH_PALETTE)]

    def _render_item(self, item):
        # Draw the item into the shared shape buffer (no allocation).
        kind, val = item
        color = self._item_color(item)
        if kind == "shape":
            render(self._shape_fb, SHAPE_BOX, val, SHAPE_SIZE, color, DARK)
        else:
            render_glyph(self._shape_fb, SHAPE_BOX, val, GLYPH_SCALE,
                         color, DARK, self._glyph_tmp_fb)

    async def _draw_round(self, target, screen_items):
        await self.display.fill_main(DARK)
        label  = self._label(target)
        prompt = "Find the " + label + "!"
        await self.display.text_main(
            prompt, config.MAIN_W // 2 - len(prompt) * 8, 20,
            WHITE, DARK, scale=2)

        self._render_item(target)
        await self.display.main.blit_rgb565(
            memoryview(self._shape_buf),
            MAIN_BLIT_X, MAIN_BLIT_Y, SHAPE_BOX, SHAPE_BOX)
        await self.display.draw_score(self.score)

        for i, item in enumerate(screen_items):
            await self._draw_btn_item(i, item)

    async def _draw_btn_item(self, idx, item):
        await self.display.fill_btn(idx, DARK)
        self._render_item(item)
        await self.display.blit_btn_buf(
            idx, self._shape_buf, SHAPE_BOX, SHAPE_BOX,
            x=BTN_BLIT_X, y=BTN_BLIT_Y)

    # ── Input + feedback ─────────────────────────────────────────

    async def _wait_answer(self, gate_ms):
        # Poll the queue directly so BACK (id 4) is handled (the helper
        # wait_screen_button() ignores it).
        #
        # TIMESTAMP GATE: a press is only accepted if its press EDGE
        # (buttons._pressed_at[btn]) occurred at/after gate_ms — i.e. after
        # the round finished drawing. This rejects an eager press made
        # while the shapes were still rendering, even if the button task
        # enqueues that press slightly AFTER we drain the queue below (the
        # race that previously made the first press feel missed/delayed).
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
                # else: press edge was before the gate (during the draw) —
                # ignore it and keep waiting for a fresh, post-draw press.

    async def _reveal_correct(self, correct_idx):
        # Wrong answer. ORDER MATTERS: draw the green border FIRST (silent),
        # THEN play wrong.wav and AWAIT it fully before returning — so no
        # display draw (this border, or the next round's main-screen fill)
        # overlaps audio playback. Overlapping audio with a draw is what
        # tore the screen on wrong.wav (blocking the SPI mid-fill).
        await self.display.draw_btn_border(correct_idx, GREEN, thickness=10)
        # Red LED feedback (non-blocking effect, no display SPI contention).
        if self.leds and self.leds.ready:
            self.leds.start_effect(self.leds.wrong_flash())
        # Play wrong.wav and wait for it to finish (wait=True) so the next
        # round's draw starts only after audio is done.
        await self.audio.play_sfx("wrong.wav", wait=True)
        await asyncio.sleep_ms(300)   # brief beat so the child sees the answer

    async def _end_screen(self):
        # Turn LEDs off for the end screen (belt-and-suspenders with the
        # kernel's stop_effect).
        try:
            self.leds.stop_effect()
        except Exception:
            pass

        await self.display.show_splash(
            "You got", f"{self.score} of {NUM_ROUNDS}",
            bg_color=rgb(10, 60, 20))

        # Wait for any button press, or auto-return after 4 seconds.
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
