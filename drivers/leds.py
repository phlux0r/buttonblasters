# drivers/leds.py — Button Blasters v3.0
# WS2812B LED strip via RP2350 PIO — confirmed GP20.
# Data line via 74AHCT125 level shifter (3.3V → 5V).
# Strip powered from VBUS (5V).
# 330Ω series resistor on data line.
#
# PIO program must be at module level for MicroPython compatibility.

import asyncio
import array
import rp2
from machine import Pin
import config


# ── PIO program — module level (required by MicroPython) ─────────
@rp2.asm_pio(
    sideset_init=rp2.PIO.OUT_LOW,
    out_shiftdir=rp2.PIO.SHIFT_LEFT,
    autopull=True,
    pull_thresh=24,
)
def _ws2812_prog():
    T1, T2, T3 = 2, 5, 3
    wrap_target()
    label("bitloop")
    out(x, 1)           .side(0) [T3-1]
    jmp(not_x, "zero")  .side(1) [T1-1]
    jmp("bitloop")      .side(1) [T2-1]
    label("zero")
    nop()               .side(0) [T2-1]
    wrap()


def _hsv_to_rgb(h: int, s: float, v: float) -> tuple:
    h  = h % 360
    hi = h // 60
    f  = (h / 60) - hi
    p  = v * (1 - s)
    q  = v * (1 - f * s)
    t  = v * (1 - (1 - f) * s)
    lut = [(v,t,p),(q,v,p),(p,v,t),(p,q,v),(t,p,v),(v,p,q)]
    r, g, b = lut[hi]
    return int(r*255), int(g*255), int(b*255)


def _grb(r, g, b) -> int:
    return (g << 16) | (r << 8) | b


class LedStrip:
    """
    Async WS2812B controller via PIO state machine.
    Confirmed working: GP20 via 74AHCT125.
    """

    def __init__(self):
        self._ready       = False
        self._sm          = None
        self._n           = config.NUM_LEDS
        self._buf         = array.array('I', [0] * self._n)
        self._brightness  = config.LED_BRIGHTNESS
        self._effect_task = None
        self._init_hardware()

    def _init_hardware(self):
        if config.PIN_LED_STRIP is None:
            print("[leds] PIN_LED_STRIP not configured — LEDs disabled")
            return
        try:
            self._sm = rp2.StateMachine(
                1, _ws2812_prog,
                freq=8_000_000,
                sideset_base=Pin(config.PIN_LED_STRIP),
            )
            self._sm.active(1)
            self._ready = True
            print(f"[leds] WS2812B ready  GP{config.PIN_LED_STRIP}  "
                  f"{self._n} LEDs  brightness={self._brightness}")
        except Exception as e:
            print(f"[leds] PIO init failed: {e}")

    # ── Direct control ───────────────────────────────────────────

    def set_pixel(self, i: int, r: int, g: int, b: int):
        if not self._ready or i >= self._n:
            return
        bri = self._brightness
        self._buf[i] = _grb(int(r*bri), int(g*bri), int(b*bri))

    def show(self):
        if self._ready:
            self._sm.put(self._buf, 8)

    def set_all(self, r: int, g: int, b: int):
        if not self._ready:
            return
        for i in range(self._n):
            self.set_pixel(i, r, g, b)
        self.show()

    def off(self):
        self.set_all(0, 0, 0)

    def set_brightness(self, b: float):
        self._brightness = max(0.0, min(1.0, b))

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def num_leds(self) -> int:
        return self._n

    # ── Effect launcher ──────────────────────────────────────────

    def start_effect(self, coro):
        if not self._ready:
            return
        if self._effect_task and not self._effect_task.done():
            self._effect_task.cancel()
        self._effect_task = asyncio.create_task(coro)

    def stop_effect(self):
        if self._effect_task and not self._effect_task.done():
            self._effect_task.cancel()
        self._effect_task = None
        self.off()

    # ── Effects ──────────────────────────────────────────────────

    async def idle_rainbow(self):
        hue = 0
        try:
            while True:
                for i in range(self._n):
                    h = (hue + i * (360 // self._n)) % 360
                    self.set_pixel(i, *_hsv_to_rgb(h, 1.0, 1.0))
                self.show()
                hue = (hue + 2) % 360
                await asyncio.sleep_ms(30)
        except asyncio.CancelledError:
            pass

    async def flash(self, r: int, g: int, b: int, count: int = 3):
        try:
            for _ in range(count):
                self.set_all(r, g, b)
                await asyncio.sleep_ms(80)
                self.off()
                await asyncio.sleep_ms(60)
        except asyncio.CancelledError:
            pass

    async def pulse(self, r: int, g: int, b: int):
        import math
        try:
            t = 0
            while True:
                bri = (math.sin(t) + 1) / 2 * self._brightness
                for i in range(self._n):
                    self._buf[i] = _grb(int(r*bri), int(g*bri), int(b*bri))
                self.show()
                t += 0.08
                await asyncio.sleep_ms(20)
        except asyncio.CancelledError:
            pass

    async def chase(self, r: int, g: int, b: int):
        try:
            pos = 0
            while True:
                for i in range(self._n):
                    fade = (1.0 if i == pos else
                            0.15 if i == (pos-1) % self._n else 0.0)
                    self.set_pixel(i,
                                   int(r*fade), int(g*fade), int(b*fade))
                self.show()
                pos = (pos + 1) % self._n
                await asyncio.sleep_ms(60)
        except asyncio.CancelledError:
            pass

    async def wrong_flash(self):
        await self.flash(255, 0, 0, count=2)

    async def correct_flash(self):
        await self.flash(0, 255, 80, count=3)

    async def level_up(self):
        try:
            for _ in range(3):
                for hue in range(0, 360, 15):
                    for i in range(self._n):
                        h = (hue + i * 30) % 360
                        self.set_pixel(i, *_hsv_to_rgb(h, 1.0, 1.0))
                    self.show()
                    await asyncio.sleep_ms(25)
        except asyncio.CancelledError:
            pass


leds = LedStrip()
