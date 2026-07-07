# games/match/shapes_draw.py — Button Blasters
# Renders shapes AND glyphs (letters/numbers) into a CALLER-PROVIDED
# framebuf.FrameBuffer. Does NOT allocate — the buffer is created once at
# game load and reused for every item on every screen (avoids per-round
# 144KB allocations that caused MemoryError from heap fragmentation).
#
# The game fills the screen background solid first (fast streamed fill),
# then blits this small centered buffer on top; filling the buffer with
# the same bg makes the blit seamless.

import math
import framebuf

# Shape name groups
BASE_SHAPES  = ("circle", "square", "triangle", "star")
EXTRA_SHAPES = ("diamond", "pentagon", "hexagon")
SHAPES       = BASE_SHAPES          # backward-compatible export


def render(fb, box, shape, size, color, bg):
    """Draw a SHAPE into pre-allocated FrameBuffer fb (box x box, RGB565)."""
    fb.fill(bg)
    c = box // 2
    if shape == "circle":
        _circle(fb, c, c, size // 2, color)
    elif shape == "square":
        _square(fb, c, c, size, color)
    elif shape == "triangle":
        _triangle(fb, c, c, size, color)
    elif shape == "star":
        _star(fb, c, c, size, color)
    elif shape == "diamond":
        _regular_polygon(fb, c, c, size // 2, 4, color)
    elif shape == "pentagon":
        _regular_polygon(fb, c, c, size // 2, 5, color)
    elif shape == "hexagon":
        _regular_polygon(fb, c, c, size // 2, 6, color)
    else:
        raise ValueError("unknown shape: " + str(shape))


def render_glyph(fb, box, char, scale, color, bg, tmp_fb):
    """
    Draw a single CHARACTER (letter/number) scaled up into fb, centered.
    tmp_fb is a pre-allocated 8x8 RGB565 FrameBuffer (drawn once, scaled
    into fb) — passed in so this allocates nothing.
    """
    fb.fill(bg)
    tmp_fb.fill(bg)
    tmp_fb.text(char, 0, 0, color)         # built-in 8x8 font
    gw = 8 * scale
    ox = (box - gw) // 2
    oy = (box - gw) // 2
    for row in range(8):
        for col in range(8):
            if tmp_fb.pixel(col, row) == color:
                fb.fill_rect(ox + col * scale, oy + row * scale,
                             scale, scale, color)


# ── Shape primitives ─────────────────────────────────────────────

def _circle(fb, cx, cy, r, color):
    for dy in range(-r, r + 1):
        dx = int(math.sqrt(max(0, r * r - dy * dy)))
        if dx > 0:
            fb.fill_rect(cx - dx, cy + dy, dx * 2, 1, color)


def _square(fb, cx, cy, size, color):
    half = size // 2
    fb.fill_rect(cx - half, cy - half, size, size, color)


def _triangle(fb, cx, cy, size, color):
    half = size // 2
    top_y = cy - half
    height = size
    for row in range(height + 1):
        y = top_y + row
        frac = row / height
        half_width = int(half * frac)
        if half_width > 0:
            fb.fill_rect(cx - half_width, y, half_width * 2, 1, color)


def _fill_polygon(fb, pts, color):
    ys = [p[1] for p in pts]
    top, bottom = int(min(ys)), int(max(ys))
    n = len(pts)
    for y in range(top, bottom + 1):
        xs = []
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if (y1 <= y < y2) or (y2 <= y < y1):
                t = (y - y1) / (y2 - y1)
                xs.append(x1 + t * (x2 - x1))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            x_start = int(xs[i])
            width = int(xs[i + 1]) - x_start
            if width > 0:
                fb.fill_rect(x_start, y, width, 1, color)


def _regular_polygon(fb, cx, cy, r, sides, color, rot=-math.pi / 2):
    pts = [(cx + r * math.cos(rot + 2 * math.pi * i / sides),
            cy + r * math.sin(rot + 2 * math.pi * i / sides))
           for i in range(sides)]
    _fill_polygon(fb, pts, color)


def _star(fb, cx, cy, size, color):
    outer_r = size // 2
    inner_r = outer_r * 0.4
    pts = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        r = outer_r if i % 2 == 0 else inner_r
        pts.append((cx + r * math.cos(angle), cy - r * math.sin(angle)))
    _fill_polygon(fb, pts, color)
