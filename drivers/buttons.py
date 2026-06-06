# drivers/buttons.py
# Debounced button input driver — now unified with touch events.
#
# Rev 1.1 changes:
#   - attach_touch() injects the TouchDriver into the same queue
#   - Touch events arrive as (TOUCH_TAP/LONG_PRESS/SWIPE, gesture_str)
#   - New helper methods: get_tap(), get_swipe(), is_touch_event()
#   - Physical button behaviour completely unchanged
#
# Full event format:  (id: int, event: str)
#
#   Physical buttons:
#     id 0-3  = screen buttons under LCD panels
#     id 4    = BACK nav button
#     id 5    = NEXT nav button
#     event   = "press" | "release" | "hold"
#
#   Touch events (from TouchDriver via attach_touch):
#     id 10   = TOUCH_TAP        event = "tap"
#     id 11   = TOUCH_LONG_PRESS event = "long_press"
#     id 12   = TOUCH_SWIPE      event = "swipe_left" | "swipe_right" |
#                                        "swipe_up"   | "swipe_down"
#
# Game usage examples:
#   btn, evt = await buttons.get()         # any event
#   btn       = await buttons.get_press()  # next physical press only
#   x, y, evt = await buttons.get_tap()    # next screen tap only
#   direction  = await buttons.get_swipe() # next swipe only

import asyncio
from machine import Pin
import config
from drivers.touch import TOUCH_TAP, TOUCH_LONG_PRESS, TOUCH_SWIPE

BTN_BACK = 4
BTN_NEXT = 5
HOLD_MS  = 600


class ButtonManager:

    def __init__(self):
        self._pins = [
            Pin(p, Pin.IN, Pin.PULL_UP)
            for p in list(config.PIN_BTN_SCREEN) + list(config.PIN_BTN_NAV)
        ]
        self._queue       = asyncio.Queue(maxsize=32)
        self._state       = [1] * len(self._pins)
        self._pressed_at  = [0]  * len(self._pins)
        self._touch_driver = None   # set via attach_touch()

    def attach_touch(self, touch_driver):
        """
        Wire the TouchDriver to this queue so touch events appear
        alongside button events.  Call during kernel init, before
        asyncio tasks start.
        """
        touch_driver._queue = self._queue
        self._touch_driver  = touch_driver

    # ── Background tasks ─────────────────────────────────────────

    async def run(self):
        """Physical button polling task."""
        import time
        while True:
            now = time.ticks_ms()
            for i, pin in enumerate(self._pins):
                val = pin.value()
                if val != self._state[i]:
                    await asyncio.sleep_ms(config.BTN_DEBOUNCE_MS)
                    val = pin.value()
                    if val == self._state[i]:
                        continue
                    self._state[i] = val
                    if val == 0:
                        self._pressed_at[i] = now
                        await self._post(i, "press")
                    else:
                        await self._post(i, "release")
                elif val == 0:
                    if time.ticks_diff(now, self._pressed_at[i]) >= HOLD_MS:
                        self._pressed_at[i] = now + HOLD_MS
                        await self._post(i, "hold")
            await asyncio.sleep_ms(10)

    async def run_touch(self):
        """Touch polling task — forward to TouchDriver if attached."""
        if self._touch_driver is not None:
            await self._touch_driver.run()

    # ── Core queue API ────────────────────────────────────────────

    async def get(self):
        """Return next (id, event) tuple — physical or touch."""
        return await self._queue.get()

    async def get_press(self) -> int:
        """Block until a physical button 'press'. Returns button id (0-5)."""
        while True:
            btn, evt = await self._queue.get()
            if evt == "press" and btn <= 5:
                return btn

    def clear(self):
        """Drain the queue — call when entering a new game/screen."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:
                break

    # ── Touch-specific helpers ────────────────────────────────────

    async def get_tap(self):
        """
        Block until a screen tap. Returns (x, y).
        Skips physical button events.
        """
        while True:
            btn, evt = await self._queue.get()
            if btn == TOUCH_TAP and evt == "tap":
                pos = (self._touch_driver.pos
                       if self._touch_driver else (0, 0))
                return pos or (0, 0)

    async def get_swipe(self) -> str:
        """
        Block until a swipe gesture.
        Returns direction string: "swipe_left" | "swipe_right" |
                                  "swipe_up"   | "swipe_down"
        """
        while True:
            btn, evt = await self._queue.get()
            if btn == TOUCH_SWIPE:
                return evt

    async def get_press_or_tap(self):
        """
        Block until either a physical press OR a screen tap.
        Returns (id, event) — games that accept both input modes use this.
        """
        while True:
            btn, evt = await self._queue.get()
            if (evt == "press" and btn <= 5) or (btn == TOUCH_TAP):
                return btn, evt

    @staticmethod
    def is_touch_event(btn_id: int) -> bool:
        """True if the event came from the touch screen."""
        return btn_id in (TOUCH_TAP, TOUCH_LONG_PRESS, TOUCH_SWIPE)

    @staticmethod
    def is_physical_event(btn_id: int) -> bool:
        """True if the event came from a physical button."""
        return btn_id <= 5

    # ── Touch position helpers (for game code) ───────────────────

    @property
    def touch_pos(self):
        """Last known touch position as (x, y), or None."""
        return self._touch_driver.pos if self._touch_driver else None

    @property
    def touch_gesture(self):
        """Last classified gesture string, or None."""
        return self._touch_driver.gesture if self._touch_driver else None

    def hit_test(self, x: int, y: int, rect: tuple) -> bool:
        """
        Test if a point falls inside a rectangle.
        rect: (rx, ry, rw, rh)
        Useful for tap-target detection in game code.
        """
        rx, ry, rw, rh = rect
        return rx <= x < rx+rw and ry <= y < ry+rh

    # ── Internal ─────────────────────────────────────────────────

    async def _post(self, idx: int, event: str):
        if not self._queue.full():
            await self._queue.put((idx, event))


buttons = ButtonManager()
