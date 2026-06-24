# core/menu.py — Button Blasters
# Animated game carousel menu.
#
# Layout:
#   Main screen  → selected game card (icon + title + description + stars)
#   BTN-0        → PREV ← indicator
#   BTN-1        → adjacent game preview (idx-1)
#   BTN-2        → adjacent game preview (idx+1)
#   BTN-3        → NEXT → indicator
#
# Navigation:
#   BTN-0 press  → scroll left (PREV)
#   BTN-3 press  → scroll right (NEXT)
#   BTN-1 press  → launch preview game (idx-1 … wraps)
#   BTN-2 press  → launch preview game (idx+1 … wraps)
#   BACK press   → (reserved — no-op in menu, returns to top of carousel)
#   Touch tap on lower half of main screen → launch selected game
#   Swipe left/right → scroll carousel

import asyncio
from core.display_manager import display, WHITE, YELLOW, BLACK, GREEN, rgb
from drivers.audio import audio
from drivers.leds import leds
from drivers.buttons import buttons, BTN_PREV, BTN_NEXT, BTN_BACK
from drivers.assets import assets
import config

_CARD_COLORS = [
    rgb(60,  30, 120),
    rgb(20,  90, 160),
    rgb(160, 60,  20),
    rgb(20, 130,  70),
    rgb(130, 20,  80),
    rgb(80, 130,  20),
]


class Menu:

    def __init__(self, registry: list):
        self._registry = registry
        self._idx      = 0
        self._n        = len(registry)
        self._scores   = {}
        self._stars    = {}

    # ── Entry point ──────────────────────────────────────────────

    async def run(self) -> type:
        """Display the menu. Returns the selected game CLASS."""
        buttons.clear()
        if leds.ready:
            leds.start_effect(leds.idle_rainbow())
        await self._render_full()

        while True:
            action, data = await buttons.get_menu_event()

            if action == "prev":
                self._idx = (self._idx - 1) % self._n
                await self._render_full()
                await audio.play_sfx("menu_move.wav")

            elif action == "next":
                self._idx = (self._idx + 1) % self._n
                await self._render_full()
                await audio.play_sfx("menu_move.wav")

            elif action == "select":
                # BTN-1 → launch idx-1 preview, BTN-2 → launch idx+1 preview
                btn = data
                if btn == 1:
                    self._idx = (self._idx - 1) % self._n
                elif btn == 2:
                    self._idx = (self._idx + 1) % self._n
                await audio.play_sfx("menu_select.wav")
                return self._registry[self._idx]

            elif action == "back":
                # BACK in menu resets to first game
                self._idx = 0
                await self._render_full()

            elif action == "tap":
                tx, ty = data
                # Lower half of main screen = launch selected game
                if ty > config.MAIN_H // 2:
                    await audio.play_sfx("menu_select.wav")
                    return self._registry[self._idx]

            elif action == "swipe":
                direction = data
                if direction == "swipe_left":
                    self._idx = (self._idx + 1) % self._n
                elif direction == "swipe_right":
                    self._idx = (self._idx - 1) % self._n
                await self._render_full()
                await audio.play_sfx("menu_move.wav")

    # ── Rendering ────────────────────────────────────────────────

    async def _render_full(self):
        await self._render_main_card()
        await self._render_btn_screens()

    async def _render_main_card(self):
        game_cls = self._registry[self._idx]
        bg       = _CARD_COLORS[self._idx % len(_CARD_COLORS)]

        await display.fill_main(bg)

        # Icon
        if game_cls.ICON_FILE and assets.sd_available:
            ix = config.MAIN_W // 2 - 32
            await display.blit_main(game_cls.ICON_FILE, ix, 40)

        # Title
        title = game_cls.TITLE[:20]
        tx = config.MAIN_W // 2 - len(title) * 8
        await display.text_main(title, tx, 124, WHITE, bg, scale=2)

        # Description
        desc = game_cls.DESCRIPTION[:38]
        dx = max(4, config.MAIN_W // 2 - len(desc) * 4)
        await display.text_main(desc, dx, 148,
                                rgb(200, 200, 200), bg, scale=1)

        # Stars
        game_id  = game_cls.GAME_ID
        stars    = self._stars.get(game_id, 0)
        star_str = ("*" * stars) + ("-" * (3 - stars))
        sx = config.MAIN_W // 2 - len(star_str) * 8
        await display.text_main(star_str, sx, 168, YELLOW, bg, scale=2)

        # Tap hint
        await display.text_main("TAP HERE TO PLAY",
                                config.MAIN_W // 2 - 16 * 6,
                                config.MAIN_H // 2 + 40,
                                WHITE, bg, scale=1)

        # Carousel dots
        dot_total_w = self._n * 12
        dot_x0 = config.MAIN_W // 2 - dot_total_w // 2
        dot_y  = config.MAIN_H - 20
        for i in range(self._n):
            col   = WHITE if i == self._idx else rgb(80, 80, 80)
            dot_x = dot_x0 + i * 12
            await display.main.fill(col, dot_x, dot_y, 8, 8)

        # Battery (optional)
        await self._render_battery(bg)

    async def _render_btn_screens(self):
        """BTN-0 = PREV, BTN-1 = prev game preview,
           BTN-2 = next game preview, BTN-3 = NEXT."""
        # BTN-0: PREV indicator
        await display.show_prev_indicator(active=False)

        # BTN-1: game at idx-1
        prev_idx = (self._idx - 1) % self._n
        await self._render_btn_game(1, prev_idx)

        # BTN-2: game at idx+1
        next_idx = (self._idx + 1) % self._n
        await self._render_btn_game(2, next_idx)

        # BTN-3: NEXT indicator
        await display.show_next_indicator(active=False)

    async def _render_btn_game(self, slot: int, game_idx: int):
        game_cls = self._registry[game_idx]
        bg       = _CARD_COLORS[game_idx % len(_CARD_COLORS)]
        r        = (bg >> 11) << 3
        g        = ((bg >> 5) & 0x3F) << 2
        b        = (bg & 0x1F) << 3

        await display.btns[slot].fill_rgb(r//3, g//3, b//3)

        if game_cls.ICON_FILE and assets.sd_available:
            ix = config.BTN_W // 2 - 32
            iy = config.BTN_H // 2 - 48
            await display.blit_btn(slot, game_cls.ICON_FILE, ix, iy)

        short = game_cls.TITLE[:12]
        tx = max(0, config.BTN_W // 2 - len(short) * 4)
        await display.text_btn(slot, short, tx,
                               config.BTN_H // 2 + 28,
                               WHITE, 0x0000, scale=1)

        stars = self._stars.get(game_cls.GAME_ID, 0)
        if stars:
            sstr = "*" * stars
            sx = max(0, config.BTN_W // 2 - len(sstr) * 6)
            await display.text_btn(slot, sstr, sx,
                                   config.BTN_H // 2 + 44,
                                   YELLOW, 0x0000, scale=1)

    async def _render_battery(self, bg):
        if config.PIN_BAT_ADC is None:
            return
        try:
            from machine import ADC
            adc = ADC(config.PIN_BAT_ADC)
            raw = adc.read_u16()
            v   = (raw / 65535 * 3.3) * 2
            pct = int((v - config.BAT_EMPTY_V) /
                      (config.BAT_FULL_V - config.BAT_EMPTY_V) * 100)
            pct = max(0, min(100, pct))
            col = (GREEN if pct > 30 else
                   YELLOW if pct > 15 else rgb(255, 60, 0))
            bw = 28; filled = bw * pct // 100
            bx = config.MAIN_W - 38; by = 6
            await display.main.fill(rgb(60, 60, 60), bx, by, bw, 10)
            if filled:
                await display.main.fill(col, bx, by, filled, 10)
            await display.main.fill(rgb(120, 120, 120),
                                    bx + bw, by + 2, 4, 6)
        except Exception:
            pass

    # ── Score tracking ───────────────────────────────────────────

    def update_result(self, game_id: str, score: int, stars: int):
        if score > self._scores.get(game_id, 0):
            self._scores[game_id] = score
        if stars > self._stars.get(game_id, 0):
            self._stars[game_id] = stars
