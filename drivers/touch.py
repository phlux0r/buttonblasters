# drivers/touch.py
# Capacitive touch driver — supports FT6336 and GT911 touch ICs.
#
# Both ICs live on the I²C bus (GP0/GP1).  An interrupt pin (GP2) signals
# when new touch data is ready — zero polling overhead during idle.
#
# Touch events are injected into the same asyncio.Queue used by physical
# buttons, so game code uses the identical await buttons.get() API with
# no changes.  Touch adds three new event strings:
#
#   "tap"          — finger touched and lifted (< LONG_PRESS_MS, < TAP_MAX_TRAVEL px)
#   "long_press"   — finger held down for LONG_PRESS_MS ms
#   "swipe_left"   — fast horizontal swipe rightward
#   "swipe_right"  — fast horizontal swipe leftward
#   "swipe_up"     — fast vertical swipe upward
#   "swipe_down"   — fast vertical swipe downward
#
# Button IDs for touch events use a reserved range above physical buttons:
#   TOUCH_TAP         = 10   payload: (x, y) in .touch_pos
#   TOUCH_LONG_PRESS  = 11   payload: (x, y)
#   TOUCH_SWIPE       = 12   payload: direction string in .touch_gesture
#
# Access last touch coordinates:  touch.pos  → (x, y) or None
# Access last gesture:            touch.gesture → "swipe_left" etc.

import asyncio
from machine import I2C, Pin
import config

# Event ID constants (these extend the button ID space)
TOUCH_TAP        = 10
TOUCH_LONG_PRESS = 11
TOUCH_SWIPE      = 12


# ── FT6336 register map ──────────────────────────────────────────────────────
_FT_TD_STATUS   = 0x02   # number of touch points (0-5)
_FT_TOUCH1_XH   = 0x03   # first touch point MSB X
_FT_GESTURE     = 0x01   # gesture ID register
_FT_GESTURE_MOVE_UP    = 0x10
_FT_GESTURE_MOVE_DOWN  = 0x20
_FT_GESTURE_MOVE_LEFT  = 0x30
_FT_GESTURE_MOVE_RIGHT = 0x40
_FT_THRESHOLD   = 0x80   # touch detection threshold register
_FT_CTRL        = 0x86   # mode register


# ── GT911 register map ───────────────────────────────────────────────────────
_GT_STATUS      = 0x814E
_GT_TOUCH1      = 0x8150
_GT_CFG_START   = 0x8047
_GT_CMD         = 0x8040


class TouchDriver:
    """
    Unified async touch driver for FT6336 and GT911 ICs.

    Runs as a background task, posting events to the shared input queue.
    Game code never calls this directly — use the ButtonManager API.
    """

    def __init__(self, input_queue: asyncio.Queue):
        """
        input_queue: the ButtonManager's internal queue — touch events
        are injected directly so games see them alongside button presses.
        """
        self._queue   = input_queue
        self._i2c     = None
        self._int_pin = None
        self._int_evt = asyncio.Event()
        self._ic      = config.TOUCH_IC   # "FT6336" | "GT911"
        self._addr    = (config.TOUCH_I2C_ADDR_FT6336
                         if self._ic == "FT6336"
                         else config.TOUCH_I2C_ADDR_GT911)

        # Public state — readable by game code
        self.pos     = None    # (x, y) of last touch, or None
        self.gesture = None    # last gesture string

        # Internal tracking for gesture detection
        self._touch_down   = False
        self._down_pos     = (0, 0)
        self._down_time    = 0
        self._long_fired   = False
        self._last_pos     = (0, 0)

    # ── Init ─────────────────────────────────────────────────────

    def init_blocking(self):
        """Set up I²C and configure the touch IC. Call before asyncio."""
        import time
        self._i2c = I2C(
            config.I2C_ID,
            sda=Pin(config.PIN_I2C_SDA),
            scl=Pin(config.PIN_I2C_SCL),
            freq=config.I2C_FREQ,
        )

        # Optional hard reset
        if config.PIN_TOUCH_RST is not None:
            rst = Pin(config.PIN_TOUCH_RST, Pin.OUT)
            rst.value(0); time.sleep_ms(10)
            rst.value(1); time.sleep_ms(50)

        if self._ic == "FT6336":
            self._ft_init()
        else:
            self._gt_init()

        # Interrupt pin — fires when touch data is ready
        self._int_pin = Pin(config.PIN_TOUCH_INT, Pin.IN, Pin.PULL_UP)
        self._int_pin.irq(
            trigger=Pin.IRQ_FALLING,
            handler=self._isr,
        )
        print(f"[touch] {self._ic} initialised at 0x{self._addr:02X}")

    def _isr(self, _pin):
        """Minimal ISR — just sets the asyncio event, no I²C in ISR."""
        self._int_evt.set()

    def _ft_init(self):
        """Configure FT6336 — set threshold and active mode."""
        try:
            self._i2c.writeto_mem(self._addr, _FT_THRESHOLD, bytes([22]))
            self._i2c.writeto_mem(self._addr, _FT_CTRL, bytes([0x00]))
        except OSError as e:
            print(f"[touch] FT6336 init error: {e}")

    def _gt_init(self):
        """GT911 — send config read command to confirm comms."""
        try:
            self._gt_write_cmd(0x02)   # read config
        except OSError as e:
            print(f"[touch] GT911 init error: {e}")

    # ── Background task ──────────────────────────────────────────

    async def run(self):
        """Main touch task — await INT, read IC, classify, post event."""
        import time
        while True:
            # Wait for interrupt or 50 ms timeout (catches long-press tick)
            try:
                await asyncio.wait_for_ms(self._int_evt.wait(), 50)
                self._int_evt.clear()
            except asyncio.TimeoutError:
                pass   # timeout — fall through to check long press

            now = time.ticks_ms()

            if self._ic == "FT6336":
                points = self._ft_read_points()
            else:
                points = self._gt_read_points()

            if points:
                x, y = points[0]
                x, y = self._transform(x, y)
                self.pos = (x, y)
                self._last_pos = (x, y)

                if not self._touch_down:
                    # Finger just landed
                    self._touch_down = True
                    self._down_pos   = (x, y)
                    self._down_time  = now
                    self._long_fired = False
                else:
                    # Finger still down — check for long press
                    held = time.ticks_diff(now, self._down_time)
                    if held >= config.LONG_PRESS_MS and not self._long_fired:
                        self._long_fired = True
                        self.gesture = "long_press"
                        await self._post(TOUCH_LONG_PRESS, "long_press")

            else:
                # No points — finger lifted
                if self._touch_down:
                    self._touch_down = False
                    elapsed  = time.ticks_diff(now, self._down_time)
                    dx = self._last_pos[0] - self._down_pos[0]
                    dy = self._last_pos[1] - self._down_pos[1]
                    travel = (dx*dx + dy*dy) ** 0.5

                    if not self._long_fired:
                        if (travel < config.TAP_MAX_TRAVEL and
                                elapsed < config.LONG_PRESS_MS):
                            # Clean tap
                            self.gesture = "tap"
                            await self._post(TOUCH_TAP, "tap")
                        elif (travel >= config.SWIPE_MIN_PX and
                              elapsed < config.SWIPE_MAX_MS):
                            # Swipe — classify direction
                            direction = self._classify_swipe(dx, dy)
                            self.gesture = direction
                            await self._post(TOUCH_SWIPE, direction)

    # ── Touch IC read helpers ─────────────────────────────────────

    def _ft_read_points(self) -> list:
        """Read up to 5 touch points from FT6336. Returns [(x,y), ...]."""
        try:
            n = self._i2c.readfrom_mem(self._addr, _FT_TD_STATUS, 1)[0] & 0x0F
            if n == 0 or n > 5:
                return []
            points = []
            for i in range(min(n, 2)):   # read up to 2 points
                base = _FT_TOUCH1_XH + i * 6
                data = self._i2c.readfrom_mem(self._addr, base, 4)
                x = ((data[0] & 0x0F) << 8) | data[1]
                y = ((data[2] & 0x0F) << 8) | data[3]
                points.append((x, y))
            return points
        except OSError:
            return []

    def _gt_read_points(self) -> list:
        """Read touch points from GT911."""
        try:
            status = self._gt_read_reg(_GT_STATUS, 1)[0]
            if not (status & 0x80):   # buffer not ready
                return []
            n = status & 0x0F
            points = []
            for i in range(min(n, 2)):
                data = self._gt_read_reg(_GT_TOUCH1 + i * 8, 6)
                x = data[0] | (data[1] << 8)
                y = data[2] | (data[3] << 8)
                points.append((x, y))
            # Clear ready flag
            self._gt_write_reg(_GT_STATUS, bytes([0x00]))
            return points
        except OSError:
            return []

    def _gt_read_reg(self, reg: int, n: int) -> bytes:
        self._i2c.writeto(self._addr, bytes([reg >> 8, reg & 0xFF]))
        return self._i2c.readfrom(self._addr, n)

    def _gt_write_reg(self, reg: int, data: bytes):
        self._i2c.writeto(self._addr, bytes([reg >> 8, reg & 0xFF]) + data)

    def _gt_write_cmd(self, cmd: int):
        self._gt_write_reg(_GT_CMD, bytes([cmd]))

    # ── Coordinate transform ─────────────────────────────────────

    def _transform(self, x: int, y: int):
        """Apply axis swap/flip corrections from config."""
        if config.TOUCH_SWAP_XY:
            x, y = y, x
        if config.TOUCH_FLIP_X:
            x = config.TOUCH_W - 1 - x
        if config.TOUCH_FLIP_Y:
            y = config.TOUCH_H - 1 - y
        x = max(0, min(config.TOUCH_W  - 1, x))
        y = max(0, min(config.TOUCH_H - 1, y))
        return x, y

    # ── Gesture classification ────────────────────────────────────

    @staticmethod
    def _classify_swipe(dx: int, dy: int) -> str:
        if abs(dx) >= abs(dy):
            return "swipe_right" if dx > 0 else "swipe_left"
        else:
            return "swipe_down"  if dy > 0 else "swipe_up"

    # ── Event posting ─────────────────────────────────────────────

    async def _post(self, touch_id: int, event: str):
        if not self._queue.full():
            await self._queue.put((touch_id, event))


touch = TouchDriver(None)   # queue injected by ButtonManager.attach_touch()
