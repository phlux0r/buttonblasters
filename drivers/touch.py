# drivers/touch.py — Button Blasters v3.0
# FT6236 capacitive touch driver — I2C-1, GP26/GP27, address 0x38.
# INT pin GP28 signals touch data ready (TOUCH_INT only — not a button).
#
# Touch events are injected into the shared asyncio.Queue used by
# ButtonManager, so game code uses buttons.get() for everything.
#
# Event IDs:
#   TOUCH_TAP        = 10   clean tap — pos in touch.pos
#   TOUCH_LONG_PRESS = 11   held >= LONG_PRESS_MS
#   TOUCH_SWIPE      = 12   direction string in touch.gesture

import asyncio
import time
from machine import I2C, Pin
import config

TOUCH_TAP        = 10
TOUCH_LONG_PRESS = 11
TOUCH_SWIPE      = 12

_FT_TD_STATUS = 0x02
_FT_TOUCH1_XH = 0x03
_FT_THRESHOLD = 0x80
_FT_CTRL      = 0x86


class TouchDriver:

    def __init__(self):
        self._queue    = None   # injected by ButtonManager.attach_touch()
        self._i2c      = None
        self._int_pin  = None
        self._int_evt  = asyncio.Event()
        self._addr     = config.TOUCH_I2C_ADDR

        self.pos     = None
        self.gesture = None

        self._touch_down = False
        self._down_pos   = (0, 0)
        self._down_time  = 0
        self._long_fired = False
        self._last_pos   = (0, 0)

    def init_blocking(self) -> I2C:
        """
        Set up I²C and configure FT6236.
        Returns the I2C instance so it can be shared with MCP23008.
        Call before asyncio starts.
        """
        self._i2c = I2C(
            config.I2C_ID,
            sda=Pin(config.PIN_I2C_SDA),
            scl=Pin(config.PIN_I2C_SCL),
            freq=config.I2C_FREQ,
        )

        if config.PIN_TOUCH_RST is not None:
            rst = Pin(config.PIN_TOUCH_RST, Pin.OUT)
            rst.value(0); time.sleep_ms(10)
            rst.value(1); time.sleep_ms(50)

        try:
            self._i2c.writeto_mem(self._addr, _FT_THRESHOLD, bytes([22]))
            self._i2c.writeto_mem(self._addr, _FT_CTRL,      bytes([0x00]))
        except OSError as e:
            print(f"[touch] FT6236 config error: {e}")

        self._int_pin = Pin(config.PIN_TOUCH_INT, Pin.IN, Pin.PULL_UP)
        self._int_pin.irq(trigger=Pin.IRQ_FALLING, handler=self._isr)

        print(f"[touch] FT6236 ready  0x{self._addr:02X}  "
              f"SDA=GP{config.PIN_I2C_SDA}  SCL=GP{config.PIN_I2C_SCL}  "
              f"INT=GP{config.PIN_TOUCH_INT}")

        return self._i2c   # return for sharing with MCP23008

    def _isr(self, _pin):
        self._int_evt.set()

    async def run(self):
        while True:
            try:
                await asyncio.wait_for_ms(self._int_evt.wait(), 50)
                self._int_evt.clear()
            except asyncio.TimeoutError:
                pass

            now    = time.ticks_ms()
            points = self._read_points()

            if points:
                x, y = points[0]
                x, y = self._transform(x, y)
                self.pos       = (x, y)
                self._last_pos = (x, y)

                if not self._touch_down:
                    self._touch_down = True
                    self._down_pos   = (x, y)
                    self._down_time  = now
                    self._long_fired = False
                else:
                    held = time.ticks_diff(now, self._down_time)
                    if held >= config.LONG_PRESS_MS and not self._long_fired:
                        self._long_fired = True
                        self.gesture = "long_press"
                        await self._post(TOUCH_LONG_PRESS, "long_press")
            else:
                if self._touch_down:
                    self._touch_down = False
                    elapsed = time.ticks_diff(now, self._down_time)
                    dx = self._last_pos[0] - self._down_pos[0]
                    dy = self._last_pos[1] - self._down_pos[1]
                    travel = (dx*dx + dy*dy) ** 0.5

                    if not self._long_fired:
                        if (travel < config.TAP_MAX_TRAVEL and
                                elapsed < config.LONG_PRESS_MS):
                            self.gesture = "tap"
                            await self._post(TOUCH_TAP, "tap")
                        elif (travel >= config.SWIPE_MIN_PX and
                              elapsed < config.SWIPE_MAX_MS):
                            direction = self._classify_swipe(dx, dy)
                            self.gesture = direction
                            await self._post(TOUCH_SWIPE, direction)

    def _read_points(self) -> list:
        try:
            n = self._i2c.readfrom_mem(
                    self._addr, _FT_TD_STATUS, 1)[0] & 0x0F
            if n == 0 or n > 5:
                return []
            points = []
            for i in range(min(n, 2)):
                base = _FT_TOUCH1_XH + i * 6
                d    = self._i2c.readfrom_mem(self._addr, base, 4)
                x    = ((d[0] & 0x0F) << 8) | d[1]
                y    = ((d[2] & 0x0F) << 8) | d[3]
                points.append((x, y))
            return points
        except OSError:
            return []

    def _transform(self, x: int, y: int):
        if config.TOUCH_SWAP_XY: x, y = y, x
        if config.TOUCH_FLIP_X:  x = config.TOUCH_W - 1 - x
        if config.TOUCH_FLIP_Y:  y = config.TOUCH_H - 1 - y
        return (max(0, min(config.TOUCH_W - 1, x)),
                max(0, min(config.TOUCH_H - 1, y)))

    @staticmethod
    def _classify_swipe(dx: int, dy: int) -> str:
        if abs(dx) >= abs(dy):
            return "swipe_right" if dx > 0 else "swipe_left"
        return "swipe_down" if dy > 0 else "swipe_up"

    async def _post(self, touch_id: int, event: str):
        if self._queue and not self._queue.full():
            await self._queue.put((touch_id, event))


touch = TouchDriver()
