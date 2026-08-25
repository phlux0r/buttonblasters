# core/kernel.py — Button Blasters v3.0
# AppKernel — central coordinator.
#
# Boot sequence:
#   1. Displays (SPI bus, ILI9488 + 4× ST7789)
#   2. Touch + I2C bus init — returns shared I2C instance
#   3. MCP23008 button init (shares I2C with touch)
#   4. Audio (I2S)
#   5. LEDs (PIO)
#   6. Haptic (GPIO — init LOW immediately to prevent float)
#   7. SD card mount (deferred — non-fatal)
#   8. Asset index + score load
#   9. Startup effects + menu

import asyncio
import gc
import json
import time

from core.display_manager import display, rgb, warm_text_scratch
from core.menu import Menu
from core.game_base import GameResult
from core.settings import load_volume
from core import game_cache
from games.registry import REGISTRY
from drivers.buttons import buttons
from drivers.touch import touch
from drivers.audio import audio
from drivers.leds import leds
from drivers.haptic import haptic
from drivers.assets import assets
from drivers.spi_bus import spi_bus
from drivers import flash_assets
import config

_SCORES_PATH = "/sd/scores.json"
_BOOT_BG = "/assets/sys/bgm_boot_480x320.bz"
_NOSD_BG = "/assets/sys/bgm_nosd_480x320.bz"

class AppKernel:

    def __init__(self):
        self._menu   = None
        self._scores = {}
        self._dimmed = False

    async def init(self):
        print("[kernel] boot start")

        # 0. Init asyncio queue (must be inside async context)
        buttons.init_queue()

        # 1. Displays
        display.init_all()

        # 1a-pre0. Seat Bonk's scratch arena FIRST of everything, before
        # even the blit scratch below. History: this WAS boot-seated, but
        # positioned LAST among five boot reservations — failed there
        # ("blew the boot budget", see games.bonk.game._scratch_arena's
        # comment), so it got reverted to lazy seating at load() time
        # instead. Lazy seating then ALSO failed, repeatedly, on real
        # hardware after playing Match first: three retries showed free
        # heap RISING each time (56208 -> 110816 -> 124528) while the exact
        # same 32768-byte request kept failing regardless — proof this
        # isn't a shortage, it's permanent fragmentation from the OTHER
        # boot-seated blocks (persistent strip pool, flash_assets.arena,
        # text scratch) acting as fixed, non-moving walls (MicroPython's GC
        # doesn't compact) that happen to leave no single gap >= 32KB, no
        # matter how much unrelated garbage gets collected. So: back to
        # boot-time seating, but FIRST this time instead of last, so it
        # claims its 32KB while the heap is most virgin, before the larger
        # reservations below get a chance to wall it in. If flash_assets.init()
        # (96KB, the single biggest block) fails after this reorder, that's
        # the checkpoint print to watch — it would mean total capacity, not
        # ordering, is the real ceiling, and the next lever would be
        # shrinking something's SIZE (SPRITE_BUDGET or STRIP_H), not
        # reordering further.
        from games.bonk.game import seat_scratch_arena
        seat_scratch_arena()
        print(f"[kernel] heap after bonk scratch arena: free={gc.mem_free()}")

        # 1a-pre. Pre-warm the ILI9488's own full-width blit scratch buffer
        # (23,040B) BEFORE anything else claims heap. Confirmed on hardware
        # to be the most fragile allocation of all: it's used by the boot
        # splash paint below (the very first main-screen draw of every
        # session), and once the strip pool + Bonk scratch arena reservations
        # (added for a DIFFERENT fix) landed ahead of it, this one started
        # failing despite 130KB+ still free — pure fragmentation. See
        # ILI9488.warm_blit_scratch() in drivers/display.py for the full
        # story. Goes first because it's now the most fragile, not because
        # it's the biggest.
        display.main.warm_blit_scratch()
        print(f"[kernel] heap after blit scratch: free={gc.mem_free()}")

        # 1a. Seat the main-screen strip buffer pool FIRST, on the freshest
        # heap of all — before even flash_assets.init() below. Confirmed on
        # hardware: this pool's per-game-session seat/free cycle (via
        # MainScreenAdapter.open()/close()) fragmented the heap badly enough
        # that STRIP_H shrank 32→16→8 across three separate confirmed
        # failures, and STILL failed at 8 ("did not seat... Heap too
        # fragmented") after the menu + game_cache.install() had run first.
        # This pool does FOUR separate smaller allocations (not one bump
        # carve like flash_assets.arena), so it's the most placement-
        # sensitive of everything seated at boot — same "acquire hardest-
        # first" rule already applied inside games/bonk/game.py's load(),
        # just extended to the whole boot sequence. Persistent for the
        # whole power-on session now (see core/sprite_adapter.py's
        # seat_shared_pool() / _shared_pool) — never freed until reset.
        from core.sprite_adapter import seat_shared_pool
        seat_shared_pool()
        print(f"[kernel] heap after strip pool: free={gc.mem_free()}")

        # 1b. Seat the flash-asset sprite arena on the FRESHEST heap — before
        # any subsystem (touch/audio/LEDs/SD) churns it, and before the boot
        # card paints (paint_main_bg borrows the arena). One 96KB alloc.
        flash_assets.init()
        print(f"[kernel] heap after flash_assets arena: free={gc.mem_free()}")

        # 1c. Same argument, same freshest-heap moment: pre-grow the shared
        # text-scratch buffers to the largest size any game will ever ask
        # for (currently Bonk's scale-10 "GO!", 38.4KB), instead of letting
        # that grow happen lazily mid-game on a fragmented heap — confirmed
        # on hardware to MemoryError there otherwise.
        warm_text_scratch()
        print(f"[kernel] heap after text scratch: free={gc.mem_free()}")

        # Boot splash — baked card if present, else the text splash.
        if not await display.paint_main_bg(_BOOT_BG):
            await display.show_splash("BUTTON", "BLASTERS",
                                      bg_color=rgb(20, 10, 60))

        # 2. Touch + shared I2C bus
        try:
            i2c = touch.init_blocking()   # returns I2C instance
            buttons.attach_touch(touch)
            print("[kernel] touch ready")
        except Exception as e:
            print(f"[kernel] touch init failed: {e}")
            i2c = None

        # 3. MCP23008 buttons (share same I2C bus)
        if i2c is not None:
            try:
                buttons.init_mcp(i2c)
                print("[kernel] buttons ready via MCP23008")
            except Exception as e:
                print(f"[kernel] MCP23008 init failed: {e}")
        else:
            print("[kernel] skipping MCP23008 — no I2C bus")

        # 4. Audio (already initialised at import — just confirm)
        if audio.ready:
            print("[kernel] audio ready")
        else:
            print("[kernel] audio not ready — check I2S wiring")

        # 5. LEDs
        if leds.ready:
            leds.start_effect(leds.chase(80, 40, 255))
            await asyncio.sleep_ms(600)
            leds.off()
        else:
            print("[kernel] LEDs not ready")
            await asyncio.sleep_ms(200)

        # 6. Haptic — already initialised LOW at import
        if haptic.ready:
            print("[kernel] haptic ready")

        # 7. SD card (deferred — non-fatal)
        sd_ok = assets.mount_sd()
        if sd_ok:
            assets.build_index()
            await self._load_scores()
        else:
            if not await display.paint_main_bg(_NOSD_BG):
                await display.show_no_sd_warning()
            await asyncio.sleep_ms(1500)

        # 7b. Restore saved volume (no-op / defaults to 1.0 without SD) —
        # before the startup sound so it's audible at the right level too.
        audio.set_volume(await load_volume())

        # 8. Startup sound
        await audio.play_sfx("startup.wav")

        # 9. Build menu
        self._menu = Menu(REGISTRY)
        self._menu._scores = {
            gid: d.get("score", 0) for gid, d in self._scores.items()}
        self._menu._stars = {
            gid: d.get("stars", 0) for gid, d in self._scores.items()}

        print(f"[kernel] boot complete — {len(REGISTRY)} games registered")

    async def run(self):
        asyncio.create_task(buttons.run())
        asyncio.create_task(buttons.run_touch())
        asyncio.create_task(self._idle_watchdog())

        while True:
            game_cls = await self._menu.run()

            saved      = self._scores.get(game_cls.GAME_ID, {})
            best_score = saved.get("score", 0)
            best_time  = saved.get("best_time_s")
            game = game_cls(display, audio, leds, buttons, assets,
                            best_score=best_score, best_time_s=best_time)
            await self._transition_to_game(game)
            await self._menu.show_loading()
            audio.stop_all()             # NEW — clean silence during install, not a stall

            print(f"[kernel] loading {game.GAME_ID}")
            if leds.ready:
                leds.start_effect(leds.chase(100, 200, 100))
            await game_cache.install(game.GAME_ID)      # Tier B — SD → littlefs
            audio.set_game(game.GAME_ID)                # game's Tier B audio dir
            print(f"[kernel] heap before {game.GAME_ID}.load(): "
                  f"free={gc.mem_free()}")
            try:
                await game.load()
            except Exception as e:
                # game.run() has always had this net; load() didn't, so a
                # load-time failure (e.g. Star Bonk's StripBufferPool
                # MemoryError on a fragmented heap) used to propagate all
                # the way out of AppKernel.run() and crash the whole app
                # instead of bouncing back to the menu.
                print(f"[kernel] {game.GAME_ID} failed to load: {e}")
                leds.stop_effect()
                await display.show_splash("Couldn't load", game.TITLE,
                                          bg_color=rgb(60, 15, 15))
                await asyncio.sleep_ms(2000)
                try:
                    await game.unload()
                except Exception as e2:
                    print(f"[kernel] {game.GAME_ID} unload after failed "
                         f"load also raised: {e2}")
                audio.set_game(None)
                game_cache.evict(game.GAME_ID)
                continue   # back to the menu — skip run()/save/unload below
            leds.stop_effect()          # not off() — off() clears pixels but
                                        # leaves the effect task rewriting them

            print(f"[kernel] running {game.GAME_ID}")
            try:
                result = await game.run()
            except Exception as e:
                print(f"[kernel] game crashed: {e}")
                result = GameResult(score=0, completed=False)

            await self._save_result(game.GAME_ID, result)
            self._menu.update_result(game.GAME_ID,
                                     result.score, result.stars)

            # The game owns its own end screen, BACK handling, and the
            # end-of-round cheer (BaseGame.announce_round_complete()) —
            # the kernel just cleans up and returns to the carousel.
            leds.stop_effect()

            await game.unload()
            audio.set_game(None)
            game_cache.evict(game.GAME_ID)        # Tier B evict
            print(f"[kernel] unloaded {game.GAME_ID}")

    async def _transition_to_game(self, game):
        # Each game owns its own intro (e.g. Match It!'s category card) — no
        # generic GET READY splash or game_start.wav here. The LED flash is a
        # non-blocking effect with no SPI contention, so it's safe to start.
        if leds.ready:
            leds.start_effect(leds.flash(80, 80, 255, count=2))

    async def _idle_watchdog(self):
        # Polls buttons.last_input_ms -- the shared queue's own timestamp,
        # updated on EVERY physical button press or touch event regardless
        # of which loop consumes it (menu navigation, in-game play, an end
        # screen's wait) -- rather than relying on call sites to each
        # remember to report activity back to the kernel. That used to be
        # self._last_input, reset only from two spots (a game just
        # selected, a game just finished): confirmed on hardware that
        # meant menu navigation and in-game play never reset the idle
        # timer at all, so the button screens dimmed and then nothing
        # short of actually launching a game brought them back.
        while True:
            await asyncio.sleep_ms(5000)
            idle_s = time.ticks_diff(
                time.ticks_ms(), buttons.last_input_ms) // 1000
            if idle_s >= config.SCREEN_DIM_S and not self._dimmed:
                if leds.ready:
                    leds.set_brightness(config.LED_IDLE_BRIGHTNESS)
                # The 4 button screens' shared backlight (GP13) is a real
                # power lever, unlike the main ILI9488's backlight (wired
                # straight to 3.3V, no GPIO, can never be switched off
                # regardless of what firmware does).
                display.set_btn_backlight(False)
                self._dimmed = True
                print("[kernel] idle — dimmed")
            elif idle_s < config.SCREEN_DIM_S and self._dimmed:
                if leds.ready:
                    leds.set_brightness(config.LED_BRIGHTNESS)
                display.set_btn_backlight(True)
                self._dimmed = False
                print("[kernel] input resumed — undimmed")

    # scores.json lives on the SD card, which shares SPI0 with the displays.
    # Every read/write must run inside spi_bus.raw() at the SD-safe clock —
    # a bare open() runs at whatever speed the bus was left at (usually the
    # display's 10MHz, which EIOs on this board) and can collide with a
    # concurrent display transaction. JSON encode/decode happens OUTSIDE the
    # locked window so the bus is held only for the actual transfer.

    async def _load_scores(self):
        try:
            async with spi_bus.raw(config.SPI_FREQ_SD_DATA):
                with open(_SCORES_PATH, "r") as f:
                    data = f.read()
            self._scores = json.loads(data)
            print(f"[kernel] loaded scores for {len(self._scores)} games")
        except OSError:
            self._scores = {}
        except ValueError:
            print("[kernel] scores.json corrupt — starting fresh")
            self._scores = {}

    async def _save_scores(self):
        if not assets.sd_available:
            return
        data = json.dumps(self._scores)
        try:
            async with spi_bus.raw(config.SPI_FREQ_SD_DATA):
                with open(_SCORES_PATH, "w") as f:
                    f.write(data)
        except OSError as e:
            print("[kernel] score save failed:", e)

    async def _save_result(self, game_id: str, result: GameResult):
        entry   = self._scores.get(game_id, {"score": 0, "stars": 0})
        changed = False
        if result.score > entry.get("score", 0):
            entry["score"]    = result.score
            result.high_score = True
            changed           = True
        if result.stars > entry.get("stars", 0):
            entry["stars"] = result.stars
            changed        = True
        if result.time_s is not None:
            best = entry.get("best_time_s")
            if best is None or result.time_s < best:
                entry["best_time_s"]  = result.time_s
                result.new_best_time  = True
                changed                = True
        self._scores[game_id] = entry
        if changed:
            await self._save_scores()
