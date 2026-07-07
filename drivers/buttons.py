# drivers/buttons.py — Button Blasters v3.0
# Button input via MCP23008 I2C GPIO expander.
#
# All 5 physical buttons are wired to MCP23008 GP0-GP4.
# The MCP23008 is polled every BTN_POLL_MS over I2C (shared bus
# with FT6236 touch at 0x38). MCP is at 0x20.
#
# Button IDs:
#   0 = SCREEN-0  (BTN-0 display — PREV ← in menu)
#   1 = SCREEN-1  (BTN-1 display — game preview)
#   2 = SCREEN-2  (BTN-2 display — game preview)
#   3 = SCREEN-3  (BTN-3 display — NEXT → in menu)
#   4 = BACK/HOME
#
# Touch events injected into same queue via attach_touch():
#   10 = TOUCH_TAP        event = "tap"
#   11 = TOUCH_LONG_PRESS event = "long_press"
#   12 = TOUCH_SWIPE      event = direction string
#
# Full event format: (id: int, event: str)
#   Physical: "press" | "release" | "hold"
#   Touch:    gesture string
#
# ── DEBOUNCE FIX ─────────────────────────────────────────────────
# The old run() detected a press edge, slept BTN_DEBOUNCE_MS, then
# re-read to "confirm" — if the button had been RELEASED in that window
# (a quick child tap), it was treated as a glitch and DISCARDED, so the
# press produced no event at all ("I press but nothing happens"). Also
# that blocking sleep sat inside the per-button loop, stalling the scan
# of the other buttons.
#
# New behaviour: fire "press" IMMEDIATELY on the first press edge (never
# dropped), and debounce only the RELEASE — time-based (no blocking
# sleep), so a quick tap always yields a press and bounce on release is
# filtered. Press bounce is naturally absorbed because the momentary
# release during bounce is itself release-debounced.

import asyncio
import time
from machine import I2C, Pin
import config
from drivers.touch import TOUCH_TAP, TOUCH_LONG_PRESS, TOUCH_SWIPE


class _SimpleQueue:
    """Minimal async-compatible queue for MicroPython."""
    def __init__(self, maxsize=32):
        self._buf     = []
        self._maxsize = maxsize
        self._ev      = asyncio.Event()

    def empty(self):
        return len(self._buf) == 0

    def full(self):
        return len(self._buf) >= self._maxsize

    def put_nowait(self, item):
        if not self.full():
            self._buf.append(item)
            self._ev.set()

    def get_nowait(self):
        if self._buf:
            return self._buf.pop(0)
        raise IndexError("empty")

    async def put(self, item):
        while self.full():
            await asyncio.sleep_ms(5)
        self._buf.append(item)
        self._ev.set()

    async def get(self):
        while not self._buf:
            self._ev.clear()
            await self._ev.wait()
        return self._buf.pop(0)

# Button ID constants
BTN_SCREEN_0 = 0
BTN_SCREEN_1 = 1
BTN_SCREEN_2 = 2
BTN_SCREEN_3 = 3
BTN_BACK     = 4

# Menu role aliases
BTN_PREV = BTN_SCREEN_0   # ← shown on BTN-0 display
BTN_NEXT = BTN_SCREEN_3   # → shown on BTN-3 display

# MCP23008 registers
_IODIR    = 0x00
_GPPU     = 0x06
_GPIO_REG = 0x09


class ButtonManager:

    def __init__(self):
        self._i2c        = None
        self._mcp_addr   = config.MCP_I2C_ADDR
        self._queue      = None   # created in init_queue() after asyncio starts
        self._state      = [True] * 5   # True = released (not pressed)
        self._pressed_at = [0]    * 5   # ticks of the press edge (used by games)
        self._touch      = None

    def init_queue(self):
        """Create the queue. Must be called inside async context."""
        self._queue = _SimpleQueue(32)

    def init_mcp(self, i2c: I2C):
        """
        Configure MCP23008 button pins as inputs with pull-ups.
        Call once at boot before asyncio starts.
        i2c: shared I2C bus already initialised by touch driver.
        """
        self._i2c = i2c
        # Read current IODIR — preserve bits 5-7 (other uses)
        current = self._mcp_read(_IODIR)
        self._mcp_write(_IODIR, current | config.MCP_BTN_MASK)
        self._mcp_write(_GPPU,  config.MCP_BTN_MASK)
        print(f"[buttons] MCP23008 button pins configured  "
              f"IODIR=0x{self._mcp_read(_IODIR):02X}  "
              f"GPPU=0x{self._mcp_read(_GPPU):02X}")

    def attach_touch(self, touch_driver):
        """Wire TouchDriver queue so touch events appear alongside buttons."""
        touch_driver._queue = self._queue
        self._touch = touch_driver

    # ── MCP23008 helpers ─────────────────────────────────────────

    def _mcp_write(self, reg, val):
        self._i2c.writeto_mem(self._mcp_addr, reg, bytes([val]))

    def _mcp_read(self, reg):
        return self._i2c.readfrom_mem(self._mcp_addr, reg, 1)[0]

    def _read_buttons(self):
        """Read MCP GPIO register. Returns raw byte."""
        return self._mcp_read(_GPIO_REG)

    @staticmethod
    def _is_pressed(gpio_val, bit):
        """True if button bit is LOW (pressed — active low)."""
        return not (gpio_val >> bit & 1)

    # ── Background tasks ─────────────────────────────────────────

    async def run(self):
        """
        MCP23008 button polling task — runs for lifetime of app.

        Press fires immediately on the first edge (never dropped). Release
        is debounced time-based (no blocking sleep), so quick taps always
        register and release bounce is filtered.
        """
        if self._i2c is None:
            print("[buttons] MCP23008 not initialised — button task idle")
            return

        # Per-button timing state (task-lifetime locals; no blocking sleeps).
        last_change = [0] * 5   # ticks of last accepted state change
        last_hold   = [0] * 5   # ticks of last "hold" repeat

        while True:
            now = time.ticks_ms()
            try:
                gpio_val = self._read_buttons()
            except OSError:
                await asyncio.sleep_ms(config.BTN_POLL_MS)
                continue

            for i in range(5):
                pressed  = self._is_pressed(gpio_val, i)
                released = self._state[i]          # True = currently released

                if pressed and released:
                    # PRESS EDGE — fire IMMEDIATELY, never dropped.
                    self._state[i]      = False
                    self._pressed_at[i] = now
                    last_change[i]      = now
                    last_hold[i]        = now
                    await self._post(i, "press")

                elif (not pressed) and (not released):
                    # RELEASE EDGE — debounce (time-based): only accept once
                    # the line has been stable past the debounce window.
                    # A momentary bounce-high before that is ignored, so the
                    # button stays "pressed" and no spurious release fires.
                    if time.ticks_diff(now, last_change[i]) >= config.BTN_DEBOUNCE_MS:
                        self._state[i] = True
                        last_change[i] = now
                        await self._post(i, "release")

                elif pressed:
                    # Steady pressed — emit repeating "hold" after BTN_HOLD_MS.
                    if (time.ticks_diff(now, self._pressed_at[i]) >= config.BTN_HOLD_MS
                            and time.ticks_diff(now, last_hold[i]) >= config.BTN_HOLD_MS):
                        last_hold[i] = now
                        await self._post(i, "hold")
                # else: steady released — nothing to do.

            await asyncio.sleep_ms(config.BTN_POLL_MS)

    async def run_touch(self):
        """Touch polling task."""
        if self._touch is not None:
            await self._touch.run()

    # ── Core queue API ────────────────────────────────────────────

    async def get(self):
        """Return next (id, event) — physical or touch."""
        while self._queue is None:
            await asyncio.sleep_ms(10)
        return await self._queue.get()

    async def get_press(self) -> int:
        """Block until a physical button press. Returns id 0-4."""
        while True:
            btn, evt = await self.get()
            if evt == "press" and btn <= 4:
                return btn

    def clear(self):
        """Drain the queue — call when entering a new game/screen."""
        if self._queue is None:
            return
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:
                break

    # ── Touch helpers ─────────────────────────────────────────────

    async def get_tap(self):
        """Block until screen tap. Returns (x, y)."""
        while True:
            btn, evt = await self._queue.get()
            if btn == TOUCH_TAP and evt == "tap":
                return self._touch.pos or (0, 0)

    async def get_swipe(self) -> str:
        """Block until swipe. Returns direction string."""
        while True:
            btn, evt = await self._queue.get()
            if btn == TOUCH_SWIPE:
                return evt

    async def get_press_or_tap(self):
        """Block until physical press OR screen tap."""
        while True:
            btn, evt = await self._queue.get()
            if (evt == "press" and btn <= 4) or btn == TOUCH_TAP:
                return btn, evt

    async def get_menu_event(self):
        """
        Block until a menu-relevant event.
        Returns (action, data):
          "prev"   — BTN-0 (PREV ←)
          "next"   — BTN-3 (NEXT →)
          "select" — BTN-1 or BTN-2, data = btn id
          "back"   — BACK/HOME
          "tap"    — screen tap, data = (x, y)
          "swipe"  — swipe gesture, data = direction string
        """
        while True:
            btn, evt = await self._queue.get()
            if evt == "press" and btn <= 4:
                if btn == BTN_PREV: return "prev",   None
                if btn == BTN_NEXT: return "next",   None
                if btn == BTN_BACK: return "back",   None
                return "select", btn
            if btn == TOUCH_TAP:
                return "tap", self._touch.pos or (0, 0)
            if btn == TOUCH_SWIPE:
                return "swipe", evt

    # ── Utility ───────────────────────────────────────────────────

    @property
    def touch_pos(self):
        return self._touch.pos if self._touch else None

    @property
    def touch_gesture(self):
        return self._touch.gesture if self._touch else None

    def hit_test(self, x: int, y: int, rect: tuple) -> bool:
        rx, ry, rw, rh = rect
        return rx <= x < rx + rw and ry <= y < ry + rh

    @staticmethod
    def is_touch_event(btn_id: int) -> bool:
        return btn_id in (TOUCH_TAP, TOUCH_LONG_PRESS, TOUCH_SWIPE)

    @staticmethod
    def is_physical_event(btn_id: int) -> bool:
        return btn_id <= 4

    async def _post(self, idx: int, event: str):
        if self._queue and not self._queue.full():
            await self._queue.put((idx, event))


buttons = ButtonManager()
