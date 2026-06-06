# core/menu.py
# Menu system — animated carousel of game cards.
#
# Layout:
#   Main screen  → game card (icon + title + description + stars)
#   Button LCDs  → 4 adjacent game icons for quick-pick
#   NAV BACK/NEXT → scroll carousel left/right
#   Any screen button → launch that game
#
# The menu also shows battery level and handles the idle/dim timeout.

import asyncio
from core.display_manager import display, WHITE, YELLOW, BLACK, GREEN, rgb
from drivers.audio import audio
from drivers.leds import leds
from drivers.buttons import buttons, BTN_BACK, BTN_NEXT
from drivers.touch import TOUCH_TAP, TOUCH_SWIPE
from drivers.assets import assets
import config


# Colour palette for menu cards — cycles per game slot
_CARD_COLORS = [
    rgb(60,  30, 120),   # purple
    rgb(20,  90, 160),   # blue
    rgb(160, 60,  20),   # orange
    rgb(20, 130,  70),   # green
    rgb(130, 20,  80),   # pink
    rgb(80, 130,  20),   # lime
]


class Menu:

    def __init__(self, registry: list):
        self._registry = registry
        self._idx      = 0          # currently selected game index
        self._n        = len(registry)
        self._scores   = {}         # game_id → best score
        self._stars    = {}         # game_id → stars earned (0-3)

    # ── Entry point ──────────────────────────────────────────────

    async def run(self) -> type:
        """
        Display the menu and wait for the player to pick a game.
        Returns the selected game CLASS (not instance).
        """
        buttons.clear()
        leds.start_effect(leds.idle_rainbow())
        await self._render_full()

        while True:
            await self._render_full()
            btn, evt = await buttons.get()
            if evt != "press":
                continue

            if btn == BTN_NEXT or evt == "swipe_left":
                self._idx = (self._idx + 1) % self._n
                await self._render_full()
                await audio.play_sfx("menu_move.wav")

            elif btn == BTN_BACK or evt == "swipe_right":
                self._idx = (self._idx - 1) % self._n
                await self._render_full()
                await audio.play_sfx("menu_move.wav")

            elif btn == TOUCH_TAP:
                # Tap on screen — check if it landed on a touch target zone
                pos = buttons.touch_pos
                if pos:
                    tx, ty = pos
                    # Bottom half of screen = launch current game
                    if ty > 180:
                        await audio.play_sfx("menu_select.wav")
                        return self._registry[self._idx]

            elif btn <= 3:
                # Quick-pick: physical button n selects the adjacent game
                pick_idx = (self._idx + btn) % self._n
                self._idx = pick_idx
                await audio.play_sfx("menu_select.wav")
                await self._render_full()
                await asyncio.sleep_ms(200)
                return self._registry[self._idx]

    # ── Rendering ────────────────────────────────────────────────

    async def _render_full(self):
        await self._render_main_card()
        await self._render_btn_icons()

    async def _render_main_card(self):
        """Draw the selected game's card on the main screen."""
        game_cls = self._registry[self._idx]
        bg = _CARD_COLORS[self._idx % len(_CARD_COLORS)]

        await display.fill_main(bg)

        # Game icon (centred, upper half)
        if game_cls.ICON_FILE:
            icon_x = config.MAIN_W // 2 - 32
            icon_y = 40
            await display.blit_main(game_cls.ICON_FILE, icon_x, icon_y)
        else:
            # placeholder block
            await display.main.fill(WHITE, config.MAIN_W//2-32,
                                    40, 64, 64)

        # Title
        title = game_cls.TITLE[:20]
        tx = config.MAIN_W // 2 - len(title) * 8
        await display.text_main(title, tx, 124, WHITE, bg, scale=2)

        # Description (single line, truncated)
        desc = game_cls.DESCRIPTION[:38]
        dx = config.MAIN_W // 2 - len(desc) * 4
        await display.text_main(desc, max(4, dx), 148,
                                 rgb(200, 200, 200), bg, scale=1)

        # Stars earned
        game_id = game_cls.GAME_ID
        stars   = self._stars.get(game_id, 0)
        star_str = ("★" * stars) + ("☆" * (3 - stars))
        sx = config.MAIN_W // 2 - len(star_str) * 8
        await display.text_main(star_str, sx, 168, YELLOW, bg, scale=2)

        # Navigation hints
        await display.text_main("◀ BACK", 8, config.MAIN_H - 18,
                                 rgb(160, 160, 160), bg, scale=1)
        await display.text_main("NEXT ▶",
                                 config.MAIN_W - 56, config.MAIN_H - 18,
                                 rgb(160, 160, 160), bg, scale=1)

        # Carousel position dots
        dot_y = config.MAIN_H - 18
        dot_total_w = self._n * 12
        dot_x0 = config.MAIN_W // 2 - dot_total_w // 2
        for i in range(self._n):
            col = WHITE if i == self._idx else rgb(80, 80, 80)
            dot_x = dot_x0 + i * 12
            await display.main.fill(col, dot_x, dot_y, 8, 8)

        # Battery indicator (top right)
        await self._render_battery()

    async def _render_btn_icons(self):
        """Show the 4 games adjacent to current selection on button screens."""
        for slot in range(4):
            game_idx = (self._idx + slot) % self._n
            game_cls = self._registry[game_idx]
            bg = _CARD_COLORS[game_idx % len(_CARD_COLORS)]

            await display.fill_btn(slot, bg)

            if game_cls.ICON_FILE:
                # Centre icon on the button screen
                ix = config.BTN_W // 2 - 32
                iy = config.BTN_H // 2 - 48
                await display.blit_btn(slot, game_cls.ICON_FILE, ix, iy)

            # Game title (small, below icon)
            short = game_cls.TITLE[:10]
            tx = config.BTN_W // 2 - len(short) * 4
            await display.text_btn(slot, short, max(0, tx),
                                   config.BTN_H // 2 + 28,
                                   WHITE, bg, scale=1)

            # Stars
            stars = self._stars.get(game_cls.GAME_ID, 0)
            sstr = "★" * stars
            if sstr:
                sx = config.BTN_W // 2 - len(sstr) * 6
                await display.text_btn(slot, sstr, max(0, sx),
                                       config.BTN_H // 2 + 44,
                                       YELLOW, bg, scale=1)

            # Highlight selected game
            if slot == 0:
                await display.draw_btn_highlight(slot, on=True)

    async def _render_battery(self):
        """Draw a tiny battery gauge in the top-right of the main screen."""
        try:
            from machine import ADC
            adc = ADC(config.PIN_BAT_ADC)
            raw = adc.read_u16()
            v_adc = raw / 65535 * 3.3
            v_bat = v_adc * 2   # voltage divider halves it
            pct = int((v_bat - config.BAT_EMPTY_V) /
                      (config.BAT_FULL_V - config.BAT_EMPTY_V) * 100)
            pct = max(0, min(100, pct))
            col = GREEN if pct > 30 else YELLOW if pct > 15 else rgb(255, 60, 0)
            bar_w = 28
            filled = bar_w * pct // 100
            bx = config.MAIN_W - 38
            by = 6
            await display.main.fill(rgb(60, 60, 60), bx, by, bar_w, 10)
            if filled:
                await display.main.fill(col, bx, by, filled, 10)
            # terminal pip
            await display.main.fill(rgb(120, 120, 120),
                                    bx + bar_w, by + 2, 4, 6)
        except Exception:
            pass   # ADC not available in emulation — skip silently

    # ── Score tracking (called by kernel after each game) ────────

    def update_result(self, game_id: str, score: int, stars: int):
        if score > self._scores.get(game_id, 0):
            self._scores[game_id] = score
        if stars > self._stars.get(game_id, 0):
            self._stars[game_id] = stars
