# core/menu.py — Button Blasters
# Animated game carousel menu.
#
# Physical layout is a 2x2 matrix (0|2 top row, 1|3 bottom row); left
# column {0,1} is "previous", right column {2,3} is "next".
#
# Layout:
#   Main screen  → selected game card (icon + title + description + stars)
#   BTN-0        → adjacent game preview (idx-1), top-left
#   BTN-1        → PREV ← indicator, bottom-left
#   BTN-2        → adjacent game preview (idx+1), top-right
#   BTN-3        → NEXT → indicator, bottom-right
#
# Navigation:
#   BTN-1 press  → scroll left (PREV)
#   BTN-3 press  → scroll right (NEXT)
#   BTN-0 press  → launch preview game (idx-1 … wraps)
#   BTN-2 press  → launch preview game (idx+1 … wraps)
#   BACK press   → (reserved — no-op in menu, returns to top of carousel)
#   Touch tap on lower half of main screen → launch selected game
#   Swipe left/right → scroll carousel

import asyncio
from core.display_manager import display, WHITE, YELLOW, BLACK, GREEN, DARK, rgb
from drivers.audio import audio
from drivers.leds import leds
from drivers.buttons import buttons, BTN_PREV, BTN_NEXT, BTN_BACK
from drivers.assets import assets
from core.settings import settings as settings_screen
import config

# Top-left gear/settings tap target on the main card. 48x48 is a little
# under the project's own 57x57 min-touch-target guidance (see
# display_manager.draw_touch_target's docstring) to limit how much of a
# baked menu card it covers — worth revisiting if it proves fiddly to
# actually tap.
_SETTINGS_ICON = (4, 4, 48, 48)

_CARD_COLORS = [
    rgb(60,  30, 120),
    rgb(20,  90, 160),
    rgb(160, 60,  20),
    rgb(20, 130,  70),
    rgb(130, 20,  80),
    rgb(80, 130,  20),
]

_MENU_CARD = "/assets/menu/bgm_menu-%s_480x320.bz"   # % GAME_ID
_MENU_TILE = "/assets/menu/btn_menu-%s_300x240.bz"   # % GAME_ID — landscape
BTN_PREV_PATH = "/assets/menu/btn_prev_300x240.bz"
BTN_NEXT_PATH = "/assets/menu/btn_next_300x240.bz"

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
        await self._render_prev_next()
        await self._render_full()

        while True:
            action, data = await buttons.get_menu_event()

            if action == "prev":
                self._idx = (self._idx - 1) % self._n
                # Sound BEFORE the render, and AWAITED (wait=True) — same
                # rule as games/bonk/game.py's _bonk_feedback() and
                # games/match/game.py's _reveal_correct(): menu_move.wav can
                # resolve via an SD-backed path, and SD shares the SPI0 bus
                # with the displays. Without wait=True here, that fire-and-
                # forget file read raced _render_full()'s own SPI0 writes —
                # confirmed on hardware as screen tearing. wait=True still
                # starts the click instantly; it just makes the render wait
                # for the read to finish first, so the two never overlap.
                await audio.play_sfx("menu_move.wav", wait=True)
                await self._render_full()

            elif action == "next":
                self._idx = (self._idx + 1) % self._n
                await audio.play_sfx("menu_move.wav", wait=True)
                await self._render_full()

            elif action == "select":
                # BTN-0 → launch idx-1 preview, BTN-2 → launch idx+1 preview
                btn = data
                if btn == 0:
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
                if buttons.hit_test(tx, ty, _SETTINGS_ICON):
                    await audio.play_sfx("menu_select.wav")
                    await settings_screen.run()
                    buttons.clear()
                    # SettingsScreen overwrites BTN-1/BTN-3 with its -/+
                    # graphics — _render_full() deliberately never touches
                    # those two (see _render_prev_next()'s docstring), so
                    # without this they'd be stuck showing -/+ forever.
                    await self._render_prev_next()
                    await self._render_full()
                # Lower half of main screen = launch selected game
                elif ty > config.MAIN_H // 2:
                    await audio.play_sfx("menu_select.wav")
                    return self._registry[self._idx]

            elif action == "swipe":
                direction = data
                if direction == "swipe_left":
                    self._idx = (self._idx + 1) % self._n
                elif direction == "swipe_right":
                    self._idx = (self._idx - 1) % self._n
                await audio.play_sfx("menu_move.wav", wait=True)
                await self._render_full()

    # ── Rendering ────────────────────────────────────────────────

    async def _render_prev_next(self):
        """Paint BTN-1/BTN-3's static PREV/NEXT arrow cards. Called once on
        entering the menu, and again on returning from anything (e.g. the
        settings screen) that overwrites those two screens with its own
        content — _render_full() deliberately does NOT repaint these on
        every scroll (only the two dynamic preview screens), so any caller
        that puts something else on BTN-1/3 must restore them explicitly."""
        if not await display.paint_btn_bg(1, BTN_PREV_PATH):
            await display.show_prev_indicator()
        if not await display.paint_btn_bg(3, BTN_NEXT_PATH):
            await display.show_next_indicator()

    async def _render_full(self):
        await self._render_main_card()
        await self._render_settings_icon()
        await self._render_btn_screens()

    async def _render_settings_icon(self):
        # Drawn AFTER the main card (baked or procedural) so it isn't
        # painted over — see _render_full()'s ordering.
        x, y, w, h = _SETTINGS_ICON
        await display.draw_touch_target(x, y, w, h, color=WHITE, label="SET")

    # Procedural fallback card (landscape 480×320) — used when a game has
    # no baked menu card asset. Draws title/description/stars/hint from the
    # game class attributes on a flat colour.

    async def _render_main_card_procedural(self, game_cls):
        bg     = _CARD_COLORS[self._idx % len(_CARD_COLORS)]
        header = getattr(game_cls, "MENU_HEADER", None)

        await display.fill_main(bg)
        cx = config.MAIN_W // 2

        # Title — white, bold. On a full-width header band if the game defines
        # MENU_HEADER (e.g. Match It!'s hot pink), else on the card colour.
        title  = game_cls.TITLE[:22]
        tscale = 3 if len(title) * 24 <= config.MAIN_W else 2
        thalf  = 8 * tscale // 2
        tx     = max(4, cx - len(title) * thalf)
        if header is not None:
            await display.main.fill(header, 0, 0, config.MAIN_W, 56)
            ty = (56 - 8 * tscale) // 2
            await display.text_main(title, tx, ty, WHITE, header,
                                    scale=tscale, bold=True)
            body_y = 84
        else:
            body_y = 60
            await display.text_main(title, tx, body_y, WHITE, bg,
                                    scale=tscale, bold=True)
            body_y += 8 * tscale + 12

        # Icon (optional, if present on SD) — below the title
        if game_cls.ICON_FILE and assets.sd_available:
            await display.blit_main(game_cls.ICON_FILE, cx - 32, body_y)
            body_y += 76

        # Description — one line
        desc = game_cls.DESCRIPTION[:44]
        dx   = max(4, cx - len(desc) * 4)
        await display.text_main(desc, dx, body_y, rgb(200, 200, 200), bg, scale=1)

        # Stars — BIGGER (scale 3), gold, centred
        stars    = self._stars.get(game_cls.GAME_ID, 0)
        star_str = ("*" * stars) + ("-" * (3 - stars))
        ssx = cx - len(star_str) * 12          # scale 3 -> char 24, half 12
        await display.text_main(star_str, ssx, 272, YELLOW, bg, scale=3)

        # Tap hint — lower third
        hint = "TAP HERE TO PLAY"
        hx   = cx - len(hint) * 8
        await display.text_main(hint, max(4, hx), config.MAIN_H - 96,
                                WHITE, bg, scale=2)

        # Carousel dots — bottom edge
        dot_total_w = self._n * 12
        dot_x0 = cx - dot_total_w // 2
        dot_y  = config.MAIN_H - 16
        for i in range(self._n):
            col = WHITE if i == self._idx else rgb(80, 80, 80)
            await display.main.fill(col, dot_x0 + i * 12, dot_y, 8, 8)

        await self._render_battery(bg)

    async def _render_main_card(self):
        game_cls = self._registry[self._idx]
        gid      = game_cls.GAME_ID
        cx       = config.MAIN_W // 2

        # Baked per-game card (title / description / decoration all baked in).
        if not await display.paint_main_bg(_MENU_CARD % gid):
            await self._render_main_card_procedural(game_cls)
            return

        # Dynamic overlays on the card's flat zones:
        # Stars — card's stars zone; colours per game (Match It! = pink on
        # white), default gold-on-dark. 4px higher than before.
        stars    = self._stars.get(gid, 0)
        star_str = ("*" * stars) + ("-" * (3 - stars))
        sfg = getattr(game_cls, "MENU_STARS_FG", YELLOW)
        sbg = getattr(game_cls, "MENU_STARS_BG", DARK)
        ssx = cx - len(star_str) * 12
        await display.text_main(star_str, ssx, 268, sfg, sbg, scale=3)

        # Carousel dots — footer.
        dot_total_w = self._n * 12
        dot_x0 = cx - dot_total_w // 2
        dot_y  = config.MAIN_H - 16
        for i in range(self._n):
            col = WHITE if i == self._idx else rgb(80, 80, 80)
            await display.main.fill(col, dot_x0 + i * 12, dot_y, 8, 8)

        # Battery — header flat zone.
        await self._render_battery(BLACK)

    async def _render_btn_screens(self):
        """BTN-0 = prev game preview, BTN-2 = next game preview.
           BTN-1 (PREV) and BTN-3 (NEXT) are static — painted once in run()."""
        prev_idx = (self._idx - 1) % self._n
        await self._render_btn_game(0, prev_idx)
        next_idx = (self._idx + 1) % self._n
        await self._render_btn_game(2, next_idx)

    async def _render_btn_game_procedural(self, slot: int, game_idx: int):
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

    async def _render_btn_game(self, slot: int, game_idx: int):
        gid = self._registry[game_idx].GAME_ID
        if not await display.paint_btn_bg(slot, _MENU_TILE % gid):
            await self._render_btn_game_procedural(slot, game_idx)

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

    async def show_loading(self):
        """Overwrite the stars zone with a LOADING banner while
        game_cache installs this game's assets."""
        cx = config.MAIN_W // 2
        label = "WAIT..."
        lx = cx - len(label) * 8
        await display.text_main(label, lx, 270, 0xe681, 0xffff, scale=2)