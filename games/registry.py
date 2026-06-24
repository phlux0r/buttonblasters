# games/registry.py — Button Blasters
# Single place to register all available games.
#
# To add a game:
#   1. Create games/<game_id>/game.py subclassing BaseGame
#   2. Uncomment (or add) the matching _register() line below
#
# Order = menu carousel order.

REGISTRY = []


def _register(module_path, class_name):
    try:
        mod = __import__(module_path, fromlist=[class_name])
        cls = getattr(mod, class_name)
        REGISTRY.append(cls)
        print(f"[registry] registered: {cls.GAME_ID} — {cls.TITLE}")
    except Exception as e:
        print(f"[registry] failed to load {module_path}: {e}")


# ── Uncomment as games are implemented ───────────────────────────
# _register("games.match.game",    "ShapeMatchGame")
# _register("games.memory.game",   "ButtonMemoryGame")
# _register("games.bonk.game",     "StarBonkGame")
# _register("games.count.game",    "CountItGame")
# _register("games.sort.game",     "MagicSortGame")
# _register("games.feed.game",     "FeedTheAnimalGame")
# _register("games.bakery.game",   "MagicBakeryGame")
# _register("games.shadow.game",   "ShadowMatchGame")
# _register("games.garden.game",   "GardenGrowGame")
# _register("games.adventure.game","MyBigDayOutGame")


# ── Fallback placeholder ─────────────────────────────────────────
if not REGISTRY:
    from core.game_base import BaseGame, GameResult

    class PlaceholderGame(BaseGame):
        GAME_ID     = "placeholder"
        TITLE       = "Coming Soon!"
        DESCRIPTION = "Games are being added."
        ICON_FILE   = None

        async def load(self):
            from core.display_manager import rgb
            await self.display.fill_main(rgb(20, 10, 60))
            await self.display.fill_all_btns(rgb(20, 10, 60))

        async def run(self) -> GameResult:
            await self.display.show_splash("COMING", "SOON!")
            await self.wait_any_button()
            return self._make_result()

        async def unload(self):
            await self.display.clear_all()

    REGISTRY.append(PlaceholderGame)
    print("[registry] no games found — using placeholder")
