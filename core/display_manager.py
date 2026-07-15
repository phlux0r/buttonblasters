# core/display_manager.py — Button Blasters
# High-level drawing API wrapping all 5 displays.
#
# Display layout:
#   main      ILI9488 4.0" 320×480  — game/menu primary screen
#   btns[0]   ST7789  1.69" 240×300 — PREV ← in menu / game context
#   btns[1]   ST7789  1.69" 240×300 — game preview / context action
#   btns[2]   ST7789  1.69" 240×300 — game preview / context action
#   btns[3]   ST7789  1.69" 240×300 — NEXT → in menu / game context
#
# Games use this class — never the low-level drivers directly.

import asyncio
import framebuf
import micropython
from drivers.display import ILI9488, ST7789
from drivers.assets import assets
from drivers import flash_assets
from core import game_cache
import config

# ── Colour constants (RGB565) ────────────────────────────────────
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
DARK    = 0x18C3

# Menu nav colours for BTN-0 (PREV) and BTN-3 (NEXT)
PREV_COLOR = 0x4810   # dark purple tint
NEXT_COLOR = 0x0B60   # dark green tint


def rgb(r: int, g: int, b: int) -> int:
    """Convert 0-255 RGB to RGB565."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

@micropython.viper
def _fb_le_to_be(buf: ptr8, n_bytes: int):
    # framebuf.RGB565 is little-endian on RP2350; both blit paths (the ILI9488
    # rgb565_to_666 viper and the ST7789 direct stream) read big-endian, so
    # swap the byte pairs before blitting or colours come out byte-swapped
    # (0xEA16 pink -> green). Baked assets are already BE, so they never hit this.
    i = 0
    while i < n_bytes:
        t = buf[i]
        buf[i] = buf[i + 1]
        buf[i + 1] = t
        i += 2

class DisplayManager:

    def __init__(self):
        self.main = ILI9488()
        self.btns = [ST7789(i) for i in range(config.NUM_BTN_SCREENS)]

    # ── Boot init (blocking) ─────────────────────────────────────

    def init_all(self):
        """Initialise all 5 displays at boot. Must run before asyncio."""
        self.main.init_blocking()
        print("[display] main ILI9488 ready")
        # All ST7789s share a reset — BTN-0 owns the reset pin
        for i, d in enumerate(self.btns):
            d.init_blocking()
            print(f"[display] BTN-{i} ST7789 ready")

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

    async def blit_main(self, filename: str, x=0, y=0,
                        w=None, h=None):
        buf = await assets.load_image(filename)
        if buf is None:
            return
        fw, fh = assets.image_size(filename)
        await self.main.blit_rgb565(memoryview(buf), x, y,
                                    w or fw, h or fh)

    async def blit_btn(self, idx: int, filename: str, x=0, y=0):
        buf = await assets.load_image(filename)
        if buf is None:
            await self.btns[idx].fill(DARK)
            return
        fw, fh = assets.image_size(filename)
        await self.btns[idx].blit_rgb565(memoryview(buf), x, y, fw, fh)

    async def blit_btn_buf(self, idx: int, buf: bytearray,
                           w: int, h: int, x=0, y=0):
        await self.btns[idx].blit_rgb565(memoryview(buf), x, y, w, h)

    async def paint_main_bg(self, path):
        """Stream a BE (kind 1) 480x320 background from flash to the main
        display, one strip at a time via an arena-borrowed buffer. Returns
        True if painted, False on any error (caller supplies the fallback)."""
        bg = None
        try:
            bg = game_cache.open_background(path)
            if not bg.big_endian:
                raise ValueError("main bg must be BE (kind 1); got LE: " + path)
            flash_assets.arena.reset()
            buf = flash_assets.arena.alloc(bg.w * bg.strip_h * 2)
            for i in range(bg.n_strips):
                rows = bg.read_strip(i, buf)
                await self.main.blit_rgb565(
                    buf[:bg.w * rows * 2], 0, i * bg.strip_h, bg.w, rows)
                await asyncio.sleep_ms(0)
            return True
        except Exception as e:
            print("[display] main bg paint failed:", path, e)
            return False
        finally:
            if bg is not None:
                bg.close()
            flash_assets.arena.reset()

    async def paint_btn_bg(self, idx, path):
        """Stream a BE (kind 1) 240x300 background from flash to button screen
        idx, one strip at a time via an arena-borrowed buffer. Returns True if
        painted, False on any error (caller supplies the fallback)."""
        bg = None
        try:
            bg = game_cache.open_background(path)
            if not bg.big_endian:
                raise ValueError("btn bg must be BE (kind 1); got LE: " + path)
            flash_assets.arena.reset()
            buf = flash_assets.arena.alloc(bg.w * bg.strip_h * 2)
            for i in range(bg.n_strips):
                rows = bg.read_strip(i, buf)
                await self.blit_btn_buf(
                    idx, buf[:bg.w * rows * 2], bg.w, rows, x=0, y=i * bg.strip_h)
                await asyncio.sleep_ms(0)
            return True
        except Exception as e:
            print("[display] btn bg paint failed:", path, e)
            return False
        finally:
            if bg is not None:
                bg.close()
            flash_assets.arena.reset()

    # ── Text rendering (8×8 framebuf font) ──────────────────────

    async def text_main(self, text: str, x: int, y: int,
                        color=WHITE, bg=BLACK, scale=2, bold=False):
        char_w = 8 * scale
        char_h = 8 * scale
        bw     = len(text) * char_w + (1 if bold else 0)
        fb_buf = bytearray(bw * char_h * 2)
        fb     = framebuf.FrameBuffer(fb_buf, bw, char_h, framebuf.RGB565)
        fb.fill(bg)
        for ci, ch in enumerate(text):
            tx = ci * char_w
            if scale == 1:
                fb.text(ch, tx, 0, color)
                if bold:
                    fb.text(ch, tx + 1, 0, color)
            else:
                tmp = bytearray(8 * 8 * 2)
                tfb = framebuf.FrameBuffer(tmp, 8, 8, framebuf.RGB565)
                tfb.fill(bg)
                tfb.text(ch, 0, 0, color)
                for row in range(8):
                    for col in range(8):
                        px = tfb.pixel(col, row)
                        if px == bg:
                            continue
                        for sr in range(scale):
                            for sc in range(scale):
                                fb.pixel(tx + col*scale + sc, row*scale + sr, px)
                                if bold:
                                    fb.pixel(tx + col*scale + sc + 1,
                                             row*scale + sr, px)
        _fb_le_to_be(fb_buf, len(fb_buf))
        await self.main.blit_rgb565(memoryview(fb_buf), x, y, bw, char_h)

    async def text_btn(self, idx: int, text: str, x: int, y: int,
                       color=WHITE, bg=BLACK, scale=1):
        char_w = 8 * scale
        char_h = 8 * scale
        bw     = len(text) * char_w
        fb_buf = bytearray(bw * char_h * 2)
        fb     = framebuf.FrameBuffer(fb_buf, bw, char_h, framebuf.RGB565)
        fb.fill(bg)
        for ci, ch in enumerate(text):
            fb.text(ch, ci * char_w, 0, color)
        _fb_le_to_be(fb_buf, len(fb_buf))
        await self.btns[idx].blit_rgb565(memoryview(fb_buf), x, y, bw, char_h)

    # ── Menu nav indicators ──────────────────────────────────────

    async def show_prev_indicator(self, active: bool = False):
        """Draw PREV ← on BTN-0. active=True when pressed."""
        bg = rgb(92, 50, 200) if active else rgb(23, 12, 50)
        await self.btns[0].fill_rgb(*((92, 50, 200) if active
                                       else (23, 12, 50)))
        await self.draw_btn_border(0, rgb(92, 50, 200))
        label = "<  PREV"
        lx = config.BTN_W // 2 - len(label) * 4
        await self.text_btn(0, label, max(4, lx),
                            config.BTN_H // 2 - 4, WHITE, bg, scale=1)

    async def show_next_indicator(self, active: bool = False):
        """Draw NEXT → on BTN-3. active=True when pressed."""
        bg = rgb(30, 180, 60) if active else rgb(7, 45, 15)
        await self.btns[3].fill_rgb(*((30, 180, 60) if active
                                       else (7, 45, 15)))
        await self.draw_btn_border(3, rgb(30, 180, 60))
        label = "NEXT  >"
        lx = config.BTN_W // 2 - len(label) * 4
        await self.text_btn(3, label, max(4, lx),
                            config.BTN_H // 2 - 4, WHITE, bg, scale=1)

    # ── UI helpers ───────────────────────────────────────────────

    async def draw_btn_border(self, idx: int,
                               color=WHITE, thickness=6):
        """Draw a coloured border on a button screen."""
        d  = self.btns[idx]
        bw = config.BTN_W
        bh = config.BTN_H
        t  = thickness
        await d.fill(color, 0,    0,    bw, t)
        await d.fill(color, 0,    bh-t, bw, t)
        await d.fill(color, 0,    0,    t,  bh)
        await d.fill(color, bw-t, 0,    t,  bh)

    async def draw_btn_highlight(self, idx: int, on: bool = True):
        """Yellow border = selected, black = deselected."""
        await self.draw_btn_border(idx, YELLOW if on else BLACK)

    async def draw_score(self, score: int, lives: int = None,
                         color=YELLOW, bg=BLACK):
        """Score + optional lives in top-right of main screen."""
        score_str = f"SCORE:{score:04d}"
        x = config.MAIN_W - len(score_str) * 16 - 4
        await self.text_main(score_str, x, 4,
                             color=color, bg=bg, scale=2)
        if lives is not None:
            hearts = "v" * lives   # ♥ not in 8×8 font — use 'v'
            await self.text_main(hearts, 4, 4,
                                 color=RED, bg=bg, scale=2)

    async def draw_progress_bar(self, pct: float,
                                x=0, y=None, w=None,
                                h=8, color=GREEN):
        y = y if y is not None else config.MAIN_H - 12
        w = w or config.MAIN_W
        filled = int(w * max(0.0, min(1.0, pct)))
        await self.main.fill(DARK,  x, y, w, h)
        if filled:
            await self.main.fill(color, x, y, filled, h)

    async def draw_touch_target(self, x: int, y: int,
                                w: int, h: int,
                                color=WHITE, label: str = "",
                                active: bool = False):
        """
        Draw a tappable zone with visible border.
        Minimum recommended size: 57×57 px (~30mm at 4" ppi).
        Pair with buttons.hit_test(tx, ty, (x, y, w, h)).
        """
        fill = color if active else BLACK
        await self.main.fill(color, x,     y,     w, 2)
        await self.main.fill(color, x,     y+h-2, w, 2)
        await self.main.fill(color, x,     y,     2, h)
        await self.main.fill(color, x+w-2, y,     2, h)
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
        await self.text_main(title, cx, 120,
                             color=WHITE, bg=bg_color, scale=2)
        if subtitle:
            cx2 = config.MAIN_W // 2 - len(subtitle) * 6
            await self.text_main(subtitle, cx2, 148,
                                 color=YELLOW, bg=bg_color, scale=1)

    async def show_no_sd_warning(self):
        """Shown at boot if SD card is not available."""
        await self.main.fill_rgb(60, 10, 10)
        await self.text_main("NO SD CARD", 40, 100,
                             color=RED, bg=rgb(60, 10, 10), scale=2)
        await self.text_main("Separate SD breakout",
                             8, 130,
                             color=WHITE, bg=rgb(60, 10, 10), scale=1)
        await self.text_main("module needed",
                             28, 142,
                             color=WHITE, bg=rgb(60, 10, 10), scale=1)


display = DisplayManager()
