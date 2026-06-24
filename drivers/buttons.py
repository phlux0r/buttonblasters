# drivers/buttons.py — Button Blasters
# Unified button + touch input driver.
#
# Physical buttons (confirmed GPIO):
#   SCREEN-0  GP20  → id 0    SCREEN-1  GP22  → id 1
#   SCREEN-2  GP0   → id 2    SCREEN-3  GP1   → id 3
#   BACK/HOME GP16  → id 4
#
# NAV-NEXT removed — BTN-0 and BTN-3 serve as PREV/NEXT in menu
# context via screen button presses (arrow icons shown on displays).
#
# Touch events share the same queue (injected by attach_touch):
#   id 10 = TOUCH_TAP        event = "tap"
#   id 11 = TOUCH_LONG_PRESS event = "long_press"
#   id 12 = TOUCH_SWIPE      event = "swipe_left" | "swipe_right" | ...
#
# GP28 = TOUCH_INT only — not polled as a button.
#
# Full event format: (id: int, event: str)
#   Physical: event = "press" | "release" | "hold"
#   Touch:    event = gesture string (see above)

import asyncio
import time
from machine import Pin
import config
from drivers.touch import TOUCH_TAP, TOUCH_LONG_PRESS, TOUCH_SWIPE

# Button ID constants
BTN_SCREEN_0 = 0
BTN_SCREEN_1 = 1
BTN_SCREEN_2 = 2
BTN_SCREEN_3 = 3
BTN_BACK     = 4

# Menu role aliases — which screen buttons act as nav in menu
BTN_PREV = BTN_SCREEN_0   # ← arrow shown on BTN-0 display
BTN_NEXT = BTN_SCREEN_3   # → arrow shown on BTN-3 display


class ButtonManager:

    def __init__(self):
        # Screen buttons 0-3 + BACK button
        _screen_gpios = list(config.PIN_BTN_SCREEN)  # (20, 22, 0, 1)
        _nav_gpios    = [config.PIN_BTN_BACK]         # [16]
        all_gpios     = _screen_gpios + _nav_gpios

        self._pins       = [Pin(p, Pin.IN, Pin.PULL_UP) for p in all_gpios]
        self._queue      = asyncio.Queue(maxsize=32)
        self._state      = [1] * len(self._pins)
        self._pressed_at = [0] * len(self._pins)
        self._touch      = None   # set via attach_touch()

    def attach_touch(self, touch_driver):
        """
        Wire the TouchDriver queue so touch events appear alongside
        button events. Call during kernel init before asyncio starts.
        """
        touch_driver._queue = self._queue
        self._touch = touch_driver

    # ── Background tasks ─────────────────────────────────────────

    async def run(self):
        """Physical button polling task — runs for lifetime of app."""
        while True:
            now = time.ticks_ms()
            for i, pin in enumerate(self._pins):
                val = pin.value()

                if val != self._state[i]:
                    await asyncio.sleep_ms(config.BTN_DEBOUNCE_MS)
                    val = pin.value()
                    if val == self._state[i]:
                        continue   # glitch
                    self._state[i] = val
                    if val == 0:   # pressed
                        self._pressed_at[i] = now
                        await self._post(i, "press")
                    else:          # released
                        await self._post(i, "release")

                elif val == 0:
                    held = time.ticks_diff(now, self._pressed_at[i])
                    if held >= config.BTN_HOLD_MS:
                        self._pressed_at[i] = now + config.BTN_HOLD_MS
                        await self._post(i, "hold")

            await asyncio.sleep_ms(10)

    async def run_touch(self):
        """Touch polling task."""
        if self._touch is not None:
            await self._touch.run()

    # ── Core queue API ────────────────────────────────────────────

    async def get(self):
        """Return next (id, event) — physical or touch."""
        return await self._queue.get()

    async def get_press(self) -> int:
        """Block until a physical button press. Returns button id 0-4."""
        while True:
            btn, evt = await self._queue.get()
            if evt == "press" and btn <= 4:
                return btn

    def clear(self):
        """Drain the queue — call when entering a new game/screen."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:
                break

    # ── Touch helpers ─────────────────────────────────────────────

    async def get_tap(self):
        """Block until a screen tap. Returns (x, y)."""
        while True:
            btn, evt = await self._queue.get()
            if btn == TOUCH_TAP and evt == "tap":
                return self._touch.pos or (0, 0)

    async def get_swipe(self) -> str:
        """Block until a swipe. Returns direction string."""
        while True:
            btn, evt = await self._queue.get()
            if btn == TOUCH_SWIPE:
                return evt

    async def get_press_or_tap(self):
        """Block until a physical press OR screen tap."""
        while True:
            btn, evt = await self._queue.get()
            if (evt == "press" and btn <= 4) or btn == TOUCH_TAP:
                return btn, evt

    # ── Menu nav helpers ──────────────────────────────────────────

    async def get_menu_event(self):
        """
        Block until a menu-relevant event.
        Returns (action, data) where action is one of:
          "prev"    — BTN-0 pressed (PREV ←)
          "next"    — BTN-3 pressed (NEXT →)
          "select"  — BTN-1 or BTN-2 pressed
          "back"    — BACK/HOME pressed
          "tap"     — screen tapped, data = (x, y)
          "swipe"   — swipe gesture, data = direction string
        """
        while True:
            btn, evt = await self._queue.get()
            if evt == "press" and btn <= 4:
                if btn == BTN_PREV:   return "prev",   None
                if btn == BTN_NEXT:   return "next",   None
                if btn == BTN_BACK:   return "back",   None
                return "select", btn   # BTN-1 or BTN-2
            if btn == TOUCH_TAP:
                return "tap", self._touch.pos or (0, 0)
            if btn == TOUCH_SWIPE:
                return "swipe", evt

    # ── Utility ───────────────────────────────────────────────────

    @property
    def touch_pos(self):
        """Last known touch position as (x, y), or None."""
        return self._touch.pos if self._touch else None

    @property
    def touch_gesture(self):
        """Last classified gesture string, or None."""
        return self._touch.gesture if self._touch else None

    def hit_test(self, x: int, y: int, rect: tuple) -> bool:
        """True if (x, y) falls inside rect (rx, ry, rw, rh)."""
        rx, ry, rw, rh = rect
        return rx <= x < rx + rw and ry <= y < ry + rh

    @staticmethod
    def is_touch_event(btn_id: int) -> bool:
        return btn_id in (TOUCH_TAP, TOUCH_LONG_PRESS, TOUCH_SWIPE)

    @staticmethod
    def is_physical_event(btn_id: int) -> bool:
        return btn_id <= 4

    async def _post(self, idx: int, event: str):
        if not self._queue.full():
            await self._queue.put((idx, event))


buttons = ButtonManager()
