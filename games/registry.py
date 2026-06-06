# games/registry.py
# Game registry — the single place to list all available games.
#
# To add a new game:
#   1. Create games/<game_id>/game.py with a class subclassing BaseGame
#   2. Import it here and add it to REGISTRY
#
# The kernel reads REGISTRY to build the menu and instantiate games.
# Order in the list = order in the menu carousel.

# ── Import games as they are created ────────────────────────────
# Each import is wrapped in a try/except so a broken game doesn't
# prevent the rest of the console from booting.

REGISTRY = []   # populated below

def _register(module_path, class_name):
    try:
        parts = module_path.split(".")
        mod = __import__(module_path, fromlist=[class_name])
        cls = getattr(mod, class_name)
        REGISTRY.append(cls)
        print(f"[registry] registered: {cls.GAME_ID} — {cls.TITLE}")
    except Exception as e:
        print(f"[registry] failed to load {module_path}.{class_name}: {e}")

# ── Register games here ──────────────────────────────────────────
# Uncomment each line as you implement the game.
# Format: _register("games.<folder>.game", "<ClassName>")

# _register("games.match.game",    "ShapeMatchGame")
# _register("games.memory.game",   "ButtonMemoryGame")
# _register("games.bonk.game",     "StarBonkGame")
# _register("games.count.game",    "CountItGame")
# _register("games.colour.game",   "ColourQuestGame")
# _register("games.rhythm.game",   "BeatAlongGame")
# Add your new games here …


# ── Fallback: if no games registered, add a placeholder ─────────
if not REGISTRY:
    from core.game_base import BaseGame, GameResult

    class PlaceholderGame(BaseGame):
        GAME_ID     = "placeholder"
        TITLE       = "Coming Soon!"
        DESCRIPTION = "New games are being added."
        ICON_FILE   = "shared/placeholder_64x64.raw"

        async def load(self):
            await self.display.fill_main(0x18C3)
            await self.display.fill_all_btns(0x18C3)

        async def run(self) -> GameResult:
            await self.display.show_splash("COMING", "SOON!")
            await self.wait_any_button()
            return self._make_result()

        async def unload(self):
            await self.display.clear_all()

    REGISTRY.append(PlaceholderGame)
    print("[registry] no games found — using placeholder")
