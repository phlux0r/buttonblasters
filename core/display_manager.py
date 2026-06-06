# core/display_manager.py
# DisplayManager — high-level drawing API.
#
# Wraps the five physical displays (1 main ST7796 + 4 ST7789 buttons)
# and provides:
#   - Bitmap blitting from SD-loaded buffers
#   - Colour fill helpers
#   - Simple text rendering (built-in 8×8 font via framebuf)
#   - Transition effects (fade, slide)
#   - Convenience methods game code actually calls
#
# Games should use this class, not the low-level drivers directly.

import asyncio
import framebuf
from drivers.display import ST7796, ST7789
from drivers.assets import assets
import config


# ── Colour constants (RGB565) ────────────────────────────────────────────────
BLACK   = 0x0000
WHITE   = 0xFFFF
RED     = 0xF800
GREEN   = 0x07E0
BLUE    = 0x001F
YELLOW  = 0xFFE0
CYAN    = 0x07FF
MAGENTA = 0xF81F
ORANGE  = 0xFC60
PURPLE  = 0x781F
DARK    = 0x18C3   # near-black for backgrounds


def rgb(r, g, b) -> int:
    """Convert 0-255 RGB to RGB565."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


class DisplayManager:

    def __init__(self):
        self.main = ST7796()
        self.btns = [ST7789(i) for i in range(config.NUM_BTN_SCREENS)]

    # ── Boot init (blocking) ─────────────────────────────────────

    def init_all(self):
        """Initialise all displays at boot. Blocking — runs before asyncio."""
        self.main.init_blocking()
        for i, d in enumerate(self.btns):
            d.init_blocking()
        print("[display] all displays initialised")

    # ── Fill helpers ─────────────────────────────────────────────

    async def fill_main(self, color=BLACK):
        await self.main.fill(color)

    async def fill_btn(self, idx: int, color=BLACK):
        await self.btns[idx].fill(color)

    async def fill_all_btns(self, color=BLACK):
        for i in range(config.NUM_BTN_SCREENS):
            await self.btns[i].fill(color)

    async def clear_all(self):
        await self.fill_main(BLACK)
        await self.fill_all_btns(BLACK)

    # ── Bitmap blitting ──────────────────────────────────────────

    async def blit_main(self, filename: str, x=0, y=0, w=None, h=None):
        """Load and blit an image to the main screen."""
        buf = await assets.load_image(filename)
        if buf is None:
            return
        fw, fh = assets.image_size(filename)
        await self.main.blit_rgb565(memoryview(buf), x, y, w or fw, h or fh)

    async def blit_btn(self, idx: int, filename: str, x=0, y=0):
        """Load and blit an image to button screen idx."""
        buf = await assets.load_image(filename)
        if buf is None:
            await self.btns[idx].fill(DARK)
            return
        fw, fh = assets.image_size(filename)
        await self.btns[idx].blit_rgb565(memoryview(buf), x, y, fw, fh)

    async def blit_btn_buf(self, idx: int, buf: bytearray, w: int, h: int,
                           x=0, y=0):
        """Blit a pre-loaded buffer to a button screen."""
        await self.btns[idx].blit_rgb565(memoryview(buf), x, y, w, h)

    async def blit_all_btns(self, filenames: list):
        """Blit one image to each button screen. filenames[0..3]."""
        for i, fn in enumerate(filenames[:config.NUM_BTN_SCREENS]):
            if fn:
                await self.blit_btn(i, fn)
            else:
                await self.fill_btn(i, DARK)

    # ── Text rendering ───────────────────────────────────────────
    # Uses MicroPython's built-in 8×8 bitmap font via framebuf.
    # For nicer fonts, replace with a custom font renderer later.

    async def text_main(self, text: str, x: int, y: int,
                        color=WHITE, bg=BLACK, scale=2):
        """Render text on the main screen."""
        char_w = 8 * scale
        char_h = 8 * scale
        bw = len(text) * char_w
        fb_buf = bytearray(bw * char_h * 2)
        fb = framebuf.FrameBuffer(fb_buf, bw, char_h, framebuf.RGB565)
        fb.fill(bg)
        # Draw each character scaled
        for ci, ch in enumerate(text):
            tx = ci * char_w
            if scale == 1:
                fb.text(ch, tx, 0, color)
            else:
                # Manual scale: draw to a 8x8 buffer then scale up
                tmp = bytearray(8 * 8 * 2)
                tfb = framebuf.FrameBuffer(tmp, 8, 8, framebuf.RGB565)
                tfb.fill(bg)
                tfb.text(ch, 0, 0, color)
                for row in range(8):
                    for col in range(8):
                        px = tfb.pixel(col, row)
                        for sr in range(scale):
                            for sc in range(scale):
                                fb.pixel(tx + col*scale + sc,
                                         row*scale + sr, px)
        await self.main.blit_rgb565(memoryview(fb_buf), x, y, bw, char_h)

    async def text_btn(self, idx: int, text: str, x: int, y: int,
                       color=WHITE, bg=BLACK, scale=2):
        """Render text on a button screen."""
        char_w = 8 * scale
        char_h = 8 * scale
        bw = len(text) * char_w
        fb_buf = bytearray(bw * char_h * 2)
        fb = framebuf.FrameBuffer(fb_buf, bw, char_h, framebuf.RGB565)
        fb.fill(bg)
        for ci, ch in enumerate(text):
            fb.text(ch, ci * char_w * (1 if scale == 1 else 1), 0, color)
        await self.btns[idx].blit_rgb565(memoryview(fb_buf), x, y, bw, char_h)

    # ── Transition effects ───────────────────────────────────────

    async def fade_to_black_main(self, steps=8):
        """Fade the main screen to black by blitting darkening overlays."""
        # Simple approach: fill with semi-transparent black in steps
        # (full fade requires framebuf blending — this is a fast approximation)
        for i in range(steps):
            level = int(255 * (i + 1) / steps)
            shade = rgb(0, 0, 0)
            # Darken by drawing progressively larger black strips
            stripe_h = config.MAIN_H // steps
            await self.main.fill(shade, 0, i * stripe_h,
                                 config.MAIN_W, stripe_h)
            await asyncio.sleep_ms(20)

    async def slide_in_main(self, filename: str, direction="left"):
        """Slide a new image in from one edge (simple curtain effect)."""
        buf = await assets.load_image(filename)
        if buf is None:
            return
        fw, fh = assets.image_size(filename)
        steps = 8
        step_w = config.MAIN_W // steps
        for s in range(steps):
            x_dest = config.MAIN_W - (s + 1) * step_w
            await self.main.blit_rgb565(
                memoryview(buf), x_dest, 0,
                (s + 1) * step_w, fh
            )
            await asyncio.sleep_ms(15)

    # ── UI chrome helpers ────────────────────────────────────────

    async def draw_score(self, score: int, lives: int = None):
        """Draw score (and optional lives) in the top-right of main screen."""
        score_str = f"SCORE:{score:04d}"
        x = config.MAIN_W - len(score_str) * 16 - 4
        await self.text_main(score_str, x, 4, color=YELLOW, bg=BLACK, scale=2)
        if lives is not None:
            hearts = "♥" * lives
            await self.text_main(hearts, 4, 4, color=RED, bg=BLACK, scale=2)

    async def draw_progress_bar(self, pct: float, x=0, y=None,
                                w=None, h=8, color=GREEN):
        """Draw a horizontal progress bar on the main screen."""
        y = y if y is not None else config.MAIN_H - 12
        w = w or config.MAIN_W
        filled = int(w * max(0.0, min(1.0, pct)))
        await self.main.fill(DARK,  x, y, w, h)
        if filled:
            await self.main.fill(color, x, y, filled, h)

    async def draw_btn_highlight(self, idx: int, on: bool = True):
        """Draw a coloured border on a button screen to highlight it."""
        border = YELLOW if on else BLACK
        d = self.btns[idx]
        bw, bh = config.BTN_W, config.BTN_H
        thickness = 6
        await d.fill(border, 0, 0, bw, thickness)
        await d.fill(border, 0, bh - thickness, bw, thickness)
        await d.fill(border, 0, 0, thickness, bh)
        await d.fill(border, bw - thickness, 0, thickness, bh)

    # ── Touch UI helpers ─────────────────────────────────────────

    async def draw_touch_target(self, x: int, y: int, w: int, h: int,
                                color=WHITE, label: str = "",
                                active: bool = False):
        """
        Draw a tappable zone on the main screen with a visible border.
        active=True fills the zone (pressed state feedback).
        Minimum recommended size: 57×57 px (~30 mm at 4" display ppi).
        Pair with buttons.hit_test(tx, ty, (x, y, w, h)) in game code.
        """
        border = color
        fill   = color if active else BLACK
        await self.main.fill(border, x,     y,     w, 2)
        await self.main.fill(border, x,     y+h-2, w, 2)
        await self.main.fill(border, x,     y,     2, h)
        await self.main.fill(border, x+w-2, y,     2, h)
        if active:
            await self.main.fill(fill, x+2, y+2, w-4, h-4)
        if label:
            lx = x + w//2 - len(label) * 8
            ly = y + h//2 - 8
            await self.text_main(label, max(x+4, lx), ly,
                                 color=BLACK if active else color,
                                 bg=fill, scale=2)

    async def show_splash(self, title: str, subtitle: str = "",
                          bg_color=DARK):
        """Full-screen splash on main display."""
        await self.main.fill(bg_color)
        cx = config.MAIN_W // 2 - len(title) * 8
        await self.text_main(title,    cx, 120, color=WHITE,  bg=bg_color, scale=2)
        if subtitle:
            cx2 = config.MAIN_W // 2 - len(subtitle) * 6
            await self.text_main(subtitle, cx2, 148, color=YELLOW, bg=bg_color, scale=1)


display = DisplayManager()
