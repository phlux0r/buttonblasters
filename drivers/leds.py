# drivers/leds.py
# WS2812B LED strip driver using RP2040 PIO state machine.
# CPU overhead: zero — the PIO handles the 800 kHz protocol autonomously.
#
# Provides a small library of effects suitable for a kids' game:
#   idle_rainbow()     — slow rainbow cycle on the menu
#   flash(color, n)    — n quick flashes (correct answer, level up)
#   pulse(color)       — slow breathe effect
#   chase(color)       — running light
#   set_all(color)     — solid colour
#   off()              — all LEDs off
#
# Colors are (r, g, b) tuples, values 0-255.

import asyncio
import array
import rp2
from machine import Pin
import config


# ── PIO program (WS2812B timing) ────────────────────────────────────────────
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


def _scale(color: tuple, brightness: float) -> tuple:
    return tuple(int(c * brightness) for c in color)


def _grb(r, g, b) -> int:
    """WS2812B expects GRB byte order, packed into a 32-bit word."""
    return (g << 16) | (r << 8) | b


class LedStrip:
    """Async WS2812B controller."""

    def __init__(self):
        self._sm = rp2.StateMachine(
            0,
            _ws2812_prog,
            freq=8_000_000,
            sideset_base=Pin(config.PIN_LED_STRIP),
        )
        self._sm.active(1)
        self._n   = config.NUM_LEDS
        self._buf = array.array('I', [0] * self._n)
        self._brightness = config.LED_BRIGHTNESS
        self._effect_task = None

    # ── Direct control ───────────────────────────────────────────

    def set_pixel(self, i: int, r: int, g: int, b: int):
        sr, sg, sb = _scale((r, g, b), self._brightness)
        self._buf[i] = _grb(sr, sg, sb)

    def show(self):
        self._sm.put(self._buf, 8)

    def set_all(self, r: int, g: int, b: int):
        for i in range(self._n):
            self.set_pixel(i, r, g, b)
        self.show()

    def off(self):
        self.set_all(0, 0, 0)

    def set_brightness(self, b: float):
        self._brightness = max(0.0, min(1.0, b))

    # ── Effect launcher ─────────────────────────────────────────

    def start_effect(self, coro):
        """Cancel any running effect and start a new one."""
        if self._effect_task and not self._effect_task.done():
            self._effect_task.cancel()
        self._effect_task = asyncio.create_task(coro)

    # ── Built-in effects (all are async generators / coroutines) ─

    async def idle_rainbow(self):
        """Slow rainbow — use on the menu screen."""
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
        """Quick flashes — correct answer, level up."""
        try:
            for _ in range(count):
                self.set_all(r, g, b)
                await asyncio.sleep_ms(80)
                self.off()
                await asyncio.sleep_ms(60)
        except asyncio.CancelledError:
            pass

    async def pulse(self, r: int, g: int, b: int):
        """Slow breathe effect."""
        import math
        try:
            t = 0
            while True:
                bri = (math.sin(t) + 1) / 2 * self._brightness
                sr, sg, sb = int(r*bri), int(g*bri), int(b*bri)
                for i in range(self._n):
                    self._buf[i] = _grb(sr, sg, sb)
                self.show()
                t += 0.08
                await asyncio.sleep_ms(20)
        except asyncio.CancelledError:
            pass

    async def chase(self, r: int, g: int, b: int):
        """Running light — use during loading / transitions."""
        try:
            pos = 0
            while True:
                for i in range(self._n):
                    fade = 1.0 if i == pos else (0.15 if i == (pos-1) % self._n else 0.0)
                    self.set_pixel(i, int(r*fade), int(g*fade), int(b*fade))
                self.show()
                pos = (pos + 1) % self._n
                await asyncio.sleep_ms(60)
        except asyncio.CancelledError:
            pass

    async def wrong_flash(self):
        """Red flash for wrong answer."""
        await self.flash(255, 0, 0, count=2)

    async def correct_flash(self):
        """Green flash for correct answer."""
        await self.flash(0, 255, 80, count=3)

    async def level_up(self):
        """Rainbow chase for level up / game complete."""
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


# ── Colour helpers ───────────────────────────────────────────────────────────

def _hsv_to_rgb(h: int, s: float, v: float) -> tuple:
    """h: 0-359, s/v: 0.0-1.0 → (r, g, b) 0-255"""
    h = h % 360
    hi = h // 60
    f  = (h / 60) - hi
    p  = v * (1 - s)
    q  = v * (1 - f * s)
    t  = v * (1 - (1 - f) * s)
    lut = [(v,t,p),(q,v,p),(p,v,t),(p,q,v),(t,p,v),(v,p,q)]
    r, g, b = lut[hi]
    return int(r*255), int(g*255), int(b*255)


leds = LedStrip()
