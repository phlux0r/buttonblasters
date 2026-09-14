# 🎮 Button Blasters

A DIY handheld kids' game console built around the **Raspberry Pi Pico 2 W (RP2350)**, featuring a 4" capacitive touchscreen, four button-mounted LCD screens, ambient LED lighting, and I2S audio. Designed for ages 4–7. Fully 3D-printed shell (in progress).

![MicroPython](https://img.shields.io/badge/MicroPython-1.28.0-green.svg)
![Platform: RP2350](https://img.shields.io/badge/Platform-RP2350-red.svg)
![Status: In Development](https://img.shields.io/badge/Status-In%20Development-yellow.svg)

---

## ✨ What Is This?

Button Blasters is a handheld game console with a twist: **four of the six input buttons have their own small LCD screens**. Games can show images, numbers, colours, or symbols on the button screens and ask players to match, tap, or react to what they see — an input experience unique to this device.

The project is fully open-source: firmware, hardware design notes, asset tooling, and (soon) 3D print files.

> **Hardware bring-up is complete and four games are playable on the real device.** All confirmed pin assignments, driver-level gotchas, bench results and the full memory-fragmentation history live in [`documents/HARDWARE_NOTES.md`](documents/HARDWARE_NOTES.md) — read that before touching `config.py`, the display/touch drivers, or the boot-time heap reservations in `core/kernel.py`.

---

## 📸 Hardware Overview

| Component | Spec |
|---|---|
| MCU | Raspberry Pi Pico 2 W (RP2350, 4 MB flash), overclocked to 250 MHz |
| Main display | ILI9488 4.0" IPS 480×320 landscape, FT6236 capacitive touch, 18-bit RGB666 |
| Button LCDs | 4× ST7789 1.69" 280×240 landscape (visible glass), RGB565 |
| Storage | microSD card via separate SPI breakout (Tier B assets + audio) |
| Audio | MAX98357A I2S DAC + amp → 40mm 3W 4Ω speaker |
| LEDs | WS2812B strip (8 LEDs, shell edge) via 74AHCT125 level shifter |
| Haptic | ERM coin vibration motor via 2N3904 NPN transistor |
| GPIO expander | MCP23008 I²C DIP-8 (0x20) — all physical buttons |
| Battery monitor | VSYS via GP29/ADC3, bench-calibrated (`drivers/battery.py`) |
| Power | LiPo 3.7V 1200mAh + TP4056 USB-C charger (wiring in progress) |
| Shell | 3D-printed PLA+ or PETG |

**Dev environment:** MicroPython v1.28.0 (RPI_PICO2_W build), VS Code + MicroPico extension, `mpremote` for deployment.

---

## 🗂 Firmware Structure

```
buttonblasters/
├── main.py                  # Entry point — sets core clock, boots AppKernel
├── config.py                # Hardware-verified pin map & tunables (single source of truth)
├── sdcard.py                # SD card block driver (FAT filesystem)
├── rgb666_viper.py          # @micropython.viper RGB565(BE)→RGB666 band converter
│
├── drivers/                 # One module per peripheral; module-level singletons
│   ├── spi_bus.py           # Shared SPI0 bus: asyncio lock + cache-aware freq switching
│   ├── display.py           # ILI9488 (main) + ST7789 (buttons) low-level drivers
│   ├── touch.py             # FT6236 touch: tap / long-press / swipe classification
│   ├── buttons.py           # MCP23008 polling + touch events → one shared event queue
│   ├── audio.py             # I2S WAV/synth playback (IRQ-driven, non-blocking)
│   ├── leds.py              # WS2812B via PIO + asyncio effects
│   ├── strip_renderer.py    # Band-streamed ILI9488 painter (LE source) + strip buffer pool
│   ├── haptic.py            # ERM motor pulse patterns
│   ├── battery.py           # VSYS ADC read, averaged + EMA-smoothed
│   ├── assets.py            # SD mount + legacy .raw image loader
│   └── flash_assets.py      # .bz/.sz asset loader, 96KB bump-allocated sprite arena
│
├── core/
│   ├── kernel.py            # Boot sequence, heap reservations, menu↔game cycle, idle dim
│   ├── menu.py              # Game carousel (buttons + touch + swipe), battery icon, settings
│   ├── settings.py          # Volume screen; persisted to /sd/settings.json
│   ├── display_manager.py   # High-level drawing API used by games (fills, text, bg paint)
│   ├── game_base.py         # BaseGame + GameResult, shared feedback helpers
│   ├── game_cache.py        # Tier B: install a game's SD assets to littlefs at load, evict at unload
│   ├── sprite_engine.py     # Dirty-strip sprite compositor (colour-keyed, viper blits)
│   └── sprite_adapter.py    # Glue: SpriteEngine ↔ StripRenderer, persistent strip pool
│
├── games/
│   ├── registry.py          # Register games here (one line each) — order = carousel order
│   ├── example/             # Minimal template — copy to start a new game
│   ├── match/               # Match It!      — shapes / fruit / animals matching
│   ├── memory/              # Button Memory  — Simon-style sequence
│   ├── bonk/                # Star Bonk!     — tap the target before it vanishes
│   └── bakery/              # Magic Bakery   — pick recipe ingredients off a conveyor belt
│
├── assets/                  # Baked .bz/.sz assets checked into the repo
│   ├── sys/                 # Boot splash, "no SD" card            (Tier A, littlefs)
│   ├── menu/                # Shared nav tiles → littlefs; per-game cards/tiles → SD (streamed)
│   ├── static/<game>/       # Per-game sprites, always resident    (Tier A, littlefs)
│   └── <game>/              # Per-game backgrounds                 (Tier B, SD → littlefs at load)
├── audio/                   # Shared WAV clips (sfx/, voice/) — copied to the SD card by hand
├── art_src/                 # Source PNGs for a few sprites
├── documents/               # HARDWARE_NOTES.md, narrator script, family recording guide
├── tools/                   # Desktop + on-device helper scripts (see Tooling)
└── tests/                   # Hardware bring-up and performance test scripts (run via mpremote)
```

### How it runs

The firmware is a single **MicroPython asyncio** application. `AppKernel.init()` brings up hardware in a fixed order, then `AppKernel.run()` loops: menu → `game.load()` → `game.run()` → save result → `game.unload()`.

Background tasks that run for the life of the app: MCP23008 button polling, touch polling, the idle watchdog (dims LEDs and turns off the button-screen backlight after `SCREEN_DIM_S`), plus short-lived audio/LED effect tasks.

All five displays and the SD card share **SPI0**. `drivers/spi_bus.py` serialises access with an asyncio lock and switches the bus clock per device (48 MHz displays, 10 MHz SD) without redundant re-inits.

### Memory model (important)

The RP2350 heap is ~450 KB and MicroPython's GC does not compact. The codebase has hit heap fragmentation many times, so **every large buffer is reserved once at boot, in a deliberate order, and never freed**:

| Reservation | Size | Owner |
|---|---|---|
| Display scratch arena (bg paints, transient icon decodes) | 32 KB | `core/display_manager.py` |
| ILI9488 blit scratch (one 16-row RGB666 band) | 23 KB | `drivers/display.py` |
| Text raster scratch | ~19 KB | `core/display_manager.py` |
| Strip buffer pool (2× RGB666 + 2× RGB565 strips, `STRIP_H=8`) | ~37 KB | `core/sprite_adapter.py` |
| Sprite arena (bump allocator) | 96 KB | `drivers/flash_assets.py` |

Games borrow from these arenas with `arena.reset()` + `arena.alloc()` and must never allocate large buffers themselves. The kernel prints one line at boot with the free heap after each reservation (`heap free after scratch/blit/text/pool/arena: …`) — watch those numbers when adding anything.

---

## 🕹 Adding a Game

Every game is a self-contained package under `games/`.

**1. Copy the template**
```
cp -r games/example games/my_game
```

**2. Edit `games/my_game/game.py`** — subclass `BaseGame`:

```python
from core.game_base import BaseGame, GameResult

class MyGame(BaseGame):
    GAME_ID        = "my_game"
    TITLE          = "My Game"
    DESCRIPTION    = "Shown on the procedural menu card if no baked card exists."
    MAX_SCORE      = 12          # natural ceiling → 1/2/3 stars scale to it
    USES_COUNTDOWN = True        # 3-2-1-GO! before run(); False to skip

    async def load(self):        # decode assets, paint initial screens
        await self.display.fill_all_btns(0x0000)

    async def run(self) -> GameResult:
        if self.USES_COUNTDOWN:
            await self.countdown(3)
        btn = await self.wait_screen_button()   # 0-3
        self.score += 1
        return self._make_result()

    async def unload(self):
        await super().unload()   # stops audio, evicts caches, clears screens
```

For a standard "result card + Again/Back tiles" ending, set the `RESULT_*` class attributes and call `await self.show_end_screen(score_str)` — it paints the card, stars, tiles, plays the cheer, and returns `"again"` or `"back"` (with an idle timeout). See `games/memory/game.py` for the shortest example.

**3. Register it** in `games/registry.py`:
```python
_register("games.my_game.game", "MyGame")
```

**4. Add assets** (optional): a menu card `assets/menu/bgm_menu-my_game_480x320.bz` and tile `assets/menu/btn_menu-my_game_280x240.bz`; sprites under `assets/static/my_game/`; backgrounds under `assets/my_game/`. Missing assets fall back to procedural drawing, so a game is testable before any art exists.

The kernel handles the menu card, loading banner, score/star/best-time persistence (`/sd/scores.json`), crash recovery back to the menu, and Tier B install/evict.

### Input API

Physical buttons (via MCP23008) and touch events arrive on one queue as `(id, event)` tuples. Button ids 0–3 are the screen buttons (2×2 layout: 0|2 top row, 1|3 bottom row), 4 is BACK/HOME; touch ids are 10 (tap), 11 (long press), 12 (swipe).

```python
btn = await self.wait_screen_button()       # blocks until btn 0-3 pressed
btn = await self.wait_any_button()          # any button including BACK (4)
x, y = await self.wait_tap()                # blocks until screen tap
btn, evt = await self.wait_tap_or_button()  # either
self.check_back()                           # non-blocking: was BACK pressed? (quits if so)
self.tap_hit(x, y, (rx, ry, rw, rh))         # rectangle hit test

# Non-blocking, for games that run their own loop (reaction games, belt ticks):
ev = self.buttons.poll()                    # next (id, event) or None
self.buttons.take_back_press()              # True if BACK is queued; removes only that event
self.buttons.pressed_at(btn)                # ticks_ms of the press edge (timestamp gating)
self.buttons.touch_down / self.buttons.touch_pos   # live finger state

await self.show_correct()     # green LEDs + ding + haptic
await self.show_wrong()       # red LEDs + buzz
await self.announce_round_complete()   # "well done" / "new high score" voice line
await self.wait_or_timeout_back(coro)  # end-screen wait with idle auto-return
```

> `check_back()` only ever removes a BACK press from the queue, so it is safe to call alongside your own `poll()` loop. See `games/match/game.py` `_wait_answer()` for timestamp gating with `pressed_at()`.

### Drawing API

`self.display` is the `DisplayManager` singleton:

```python
await display.fill_main(color) / fill_btn(i, color) / fill_all_btns(color)
await display.text_main(text, x, y, color, bg, scale, bold) / text_btn(i, ...)
await display.paint_main_bg("/assets/x/bgm_..._480x320.bz", arena=None, x=0, y=0)
await display.paint_btn_bg(i, "/assets/x/btn_..._280x240.bz", arena=None)
await display.blit_btn_buf(i, be_rgb565_buf, w, h, x, y)
await display.draw_btn_border(i, color, thickness) / draw_score(score) / draw_progress_bar(pct)
```

`paint_*_bg()` streams through the display scratch arena by default (never the shared `flash_assets.arena`), so a game's resident sprites are safe. Games can borrow that same arena for short-lived decodes with `seat_bg_scratch()`.

For animated main-screen scenes, use `SpriteEngine` + `MainScreenAdapter` (see `games/bonk` for one-shot repaints and `games/bakery` for a continuous tick loop). The renderer holds the SPI0 bus lock for every strip it pushes, so other display draws simply queue behind it. The one exception is SD-backed audio, which reads the card without the lock by design: stop the engine before playing a clip that may resolve from `/sd/audio/`, or bake the clip as Tier B audio for the game.

---

## 🖼 Asset Pipeline

Art is baked on the desktop by `tools/bake_assets.py` into a chunked, zlib-compressed RGB565 container (`BBA1` header). Filename prefixes select the pipeline:

| Prefix | Output | Byte order | Used for |
|---|---|---|---|
| `bg_<name>_480x320.png` | `.bz` kind 0, 8-row strips | LE | SpriteEngine backgrounds (boards sprites animate over) |
| `bgraw_…` | as above, uncompressed | LE | Hot backgrounds (10× faster strip loads, more flash) |
| `bgm_<name>_WxH.png` | `.bz` kind 1, 32-row strips | BE | Main-screen static images (cards, result screens) |
| `btn_<name>_280x240.png` | `.bz` kind 1 | BE | Button-screen backgrounds / tiles |
| `spr_<name>_WxHxN.png` | `.sz` kind 2, magenta key | LE | Main-screen sprites (SpriteEngine) |
| `sprb_<name>_WxHxN.png` | `.sz` kind 3 | BE | Button-screen sprites/icons (opaque) |

Sprite frames are at most 96×96 with at most 8 frames per sheet, laid out in one horizontal row. Every loader checks the kind byte, so an LE/BE mix-up fails loudly at load time rather than as colour corruption.

```bash
python3 tools/bake_assets.py art/ assets/         # bakes changed PNGs (needs ffmpeg)
python3 tools/inspect_asset.py assets/menu/*.bz   # header sanity check
python3 tools/verify_bake.py art/spr_x.png assets/static/x/spr_x.sz   # colour-key check
```

### Tiers

- **Tier A** (`assets/sys`, the shared Again/Back/Next/Prev tiles in `assets/menu`, `assets/static/<game>`): permanent residents on littlefs. Small sprites and system art.
- **Per-game menu art** (`assets/menu/bgm_menu-*`, `btn_menu-*`): pushed to `/sd/assets/menu/` by `deploy.py --sd` and streamed from the card strip by strip whenever the carousel shows them. `deploy.py` converts them to uncompressed chunks while staging (one multi-sector read per strip, no inflate), since card space is free and the RP2350's time is not. They compress only ~2:1 and were half of all flash in use; each new game adds about 220 KB, so they never go on flash.
- **Tier B** (`assets/<game>/`): large backgrounds. Deployed to the SD card at `/sd/assets/<game>/` and copied to littlefs `/assets/<game>/` by `core/game_cache.py` when the game loads, then deleted at unload. Files that don't fit are streamed strip-by-strip from SD instead.

### SD Card Layout

```
/sd/
  assets/menu/             ← per-game menu cards and tiles (pushed by deploy.py --sd)
  assets/<game_id>/        ← Tier B backgrounds (pushed by deploy.py --sd)
  assets/<game_id>/audio/  ← optional per-game clips (installed with Tier B)
  audio/sfx/               ← shared sound effects  (copy from repo audio/sfx/)
  audio/voice/             ← shared voice clips    (copy from repo audio/voice/)
  scores.json              ← auto-generated high scores / stars / best times
  settings.json            ← auto-generated (volume)
```

### Audio

16-bit signed PCM WAV, mono, 22050 Hz. Clips resolve in order: per-game Tier B dir → littlefs `/assets/audio/` → `/sd/audio/` → a built-in synth tone fallback, so the console still beeps with no files at all.

```bash
ffmpeg -i input.mp3 -ar 22050 -ac 1 -acodec pcm_s16le output.wav
```

---

## 🔧 Getting Started

### Flash MicroPython

1. Hold BOOTSEL on the Pico 2 W and plug into USB — it mounts as a drive
2. Download the RPI_PICO2_W MicroPython `.uf2` (v1.28.0+) from [micropython.org](https://micropython.org/download/rpi_pico2_w/)
3. Drag the `.uf2` onto the Pico drive — it reboots automatically

### Install the Firmware

```bash
pip install -r tools/requirements.txt   # mpremote + mpy-cross (pinned to the firmware's .mpy version)
python3 tools/check_compile.py          # optional: catch syntax errors before flashing
python3 tools/deploy.py                 # stage into build/ and copy to the Pico
python3 tools/deploy.py --mpy           # cross-compile to .mpy (smaller, faster import)
python3 tools/deploy.py --sd            # also mirror Tier B assets onto the mounted SD card
python3 tools/deploy.py --dry-run       # stage only, inspect build/
```

`deploy.py` never copies `tests/`, `tools/`, `documents/` or the `audio/` folder. Copy `audio/sfx` and `audio/voice` to the SD card by hand (or push them to littlefs `/assets/audio/` for bus-free playback).

### Prepare the SD Card

Format as FAT32. Use a **separate SPI SD breakout**, not the slot on the ILI9488 module — that slot's SDO line drives MISO low and blocks every other device on the bus (see the hardware notes).

### Tooling

| Script | Runs on | Purpose |
|---|---|---|
| `tools/deploy.py` | desktop | Stage + install firmware; `--sd` pushes Tier B assets |
| `tools/bake_assets.py` | desktop | PNG → `.bz`/`.sz` baker |
| `tools/inspect_asset.py` | desktop | Read a baked asset's header, validate against loader rules |
| `tools/verify_bake.py` | desktop | Compare a baked sprite against its PNG for colour-key fringes |
| `tools/check_compile.py` | desktop | Cross-compile every module with `mpy-cross` (what CI runs) |
| `tools/mount_sd.py` | Pico | Force a real SD mount before pushing (used by `deploy.py --sd`) |
| `tools/device_du.py` | Pico | Per-folder usage on littlefs and SD |
| `tools/free_space.py` | Pico | Free littlefs space |

### Configuration

All pin assignments and tunables live in `config.py`, set to the confirmed-working values. Don't change pins without re-running the relevant bring-up test in `tests/`. Tuning knobs with bench notes inline: `MACHINE_FREQ`, `SPI_FREQ_DISPLAY`, `SPI_FREQ_SD_DATA`, `COUNTDOWN_TEXT_SCALE`, `SCREEN_DIM_S`, and the touch orientation flags:

```python
TOUCH_SWAP_XY = True   # confirmed for landscape (MADCTL 0x28)
TOUCH_FLIP_X  = False
TOUCH_FLIP_Y  = True
```

---

## ⚡ GPIO Pin Map

Confirmed via hardware bring-up tests 1–16 (see `tests/`). Rationale for each choice is in [`documents/HARDWARE_NOTES.md`](documents/HARDWARE_NOTES.md).

| GPIO | Function |
|---|---|
| GP0 | I2S BCLK → MAX98357A |
| GP1 | I2S LRC → MAX98357A |
| GP2 | DC — ST7789 BTN-0 |
| GP3 | SD_CS (SD breakout) |
| GP4 | SPI MISO |
| GP5 | **DEAD — do not use** (reads 0V regardless of `Pin.OUT` value) |
| GP6 | CS — ILI9488 main display |
| GP7–10 | CS — ST7789 button LCDs 0–3 |
| GP11 | DC — ST7789 BTN-1 |
| GP12 | DC — ILI9488 main |
| GP13 | BLK — ST7789 shared backlight (GPIO-driven; off until the menu has content, off when idle) |
| GP14 | DC — ST7789 BTN-2 |
| GP15 | RST — ST7789 (shared) |
| GP16 | I2S DIN → MAX98357A |
| GP17 | RST — ILI9488 main |
| GP18 | SPI SCK |
| GP19 | SPI MOSI |
| GP20 | WS2812B data → 74AHCT125 level shifter |
| GP21 | DC — ST7789 BTN-3 |
| GP22 | Haptic motor → 2N3904 |
| GP26 | I²C SDA (FT6236 touch + MCP23008 expander, shared bus) |
| GP27 | I²C SCL |
| GP28 | TOUCH_INT only — not a nav button |
| GP23/24 | WiFi internal — **never connect anything** |
| GP25 | WiFi CS-equivalent — held HIGH during battery reads |
| GP29 | VSYS monitor / ADC3 — battery voltage (bench-calibrated, ratio 2.983) |
| MCP23008 GP0–3 | Screen buttons 0–3 |
| MCP23008 GP4 | BACK/HOME button |
| MCP23008 GP5–7 | Spare |

> The ST7789 panels' visible glass is native columns 20–299, so `config.BTN_COL_OFFSET = 20` is applied once inside the driver's window setup; all game code uses logical 0–279 coordinates. BTN-2/3 are mounted rotated 180° and get a different MADCTL.

---

## 🎮 Game Library

**Playable on hardware:**

| Game | Type | Input | Notes |
|---|---|---|---|
| Match It! (`games/match`) | Matching — shapes, fruit, animals; 3 rounds × 6 | Buttons | Times perfect runs; best time persisted |
| Button Memory (`games/memory`) | Simon-style sequence | Buttons | Synth tones per button, reuses Bonk's icons |
| Star Bonk! (`games/bonk`) | Reaction — tap the target before it vanishes | Touch | First SpriteEngine game; live touch polling |
| Magic Bakery (`games/bakery`) | Collect recipe ingredients from a conveyor belt | Touch + buttons | First continuous-tick SpriteEngine game |

Every game shares the same end-screen convention: result card on main, **Again** tiles on BTN-0/1/2, **Back** on BTN-3, tap-anywhere replays, and an idle timeout returns to the menu. The menu also has a volume screen (tap the top-left gear).

**Planned** (not yet registered):

| Game | Type | Uses touch? |
|---|---|---|
| Count It! | Counting | Yes — tap to count |
| Magic Sort | Drag and drop sorting | Yes |
| Feed the Animal | Swipe gestures | Yes |
| Shadow Match | Silhouette identification | Yes |
| Garden Grow | Swipe to water/sun | Yes |
| My Big Day Out | Personalised branching adventure (flagship) | Yes |

**My Big Day Out** is the flagship: the child picks an avatar, family photos are converted to a cartoon style, family members record their own voice lines plus a main narrator (see `documents/`), and the branching story is driven by JSON on the SD card. Art direction is a soft rounded Bluey/Hey Duggee aesthetic.

---

## 🔌 Power & Charging

**⚠️ IN PROGRESS.** Battery monitoring is bench-confirmed; the charger/switch/boost wiring below is the design being built. See `documents/HARDWARE_NOTES.md` for the reasoning behind each decision.

- **Battery:** LiPo 3.7V 1200mAh flat cell
- **Charger:** TP4056 module **with DW01 protection IC** — essential for a kids' device. Confirm the module's actual charge current suits a 1200mAh cell before wiring
- **Charging port:** a dedicated USB-C port on the shell, wired to the TP4056's own USB input — separate from the Pico's micro-USB
- **Dev/firmware port:** the Pico's onboard micro-USB behind a removable cover, for `mpremote`/flashing only
- **Power topology:**
  ```
  Battery+/- ──→ TP4056 BAT+/BAT-
  TP4056 OUT+ (protected) ──→ [master ON/OFF switch] ──┬──→ MT3608 boost → 5V → MAX98357A VIN + WS2812B
                                                       └──→ 1N5819 Schottky (D1) ──→ Pico VSYS
  All grounds common.
  ```
  Everything downstream draws from the TP4056's *protected* output, so DW01 over-discharge protection covers the whole system. D1 stops the Pico's dev USB port back-feeding the battery when both are connected. D1 is already fitted: it drops ~0.37 V, which is why `config.VSYS_DROP_V` exists and the battery thresholds are expressed in battery-terminal volts.
- **5V rail:** MT3608 boost converter for audio + LEDs (VBUS is only live on USB). **Set its output to 5.0 V with a multimeter, unloaded, before connecting anything.**
- **Switch:** SPDT slide switch *before* the boost/VSYS split, so "off" really cuts the LED/audio branch too.
- **Battery indicator:** GP29/ADC3, bench-calibrated across two cells and three operating points (`tests/battery_calibration_log.py`). Shown in the menu header.

---

## 📄 License

MIT (see [`LICENSE`](LICENSE)) — do whatever you like with it. If you build one, share a photo!

---

## 🙏 Acknowledgements

- [MicroPython](https://micropython.org) — the firmware runtime
- [LovyanGFX](https://github.com/lovyan03/LovyanGFX) — display init sequence inspiration
- [pico-micropython-examples](https://github.com/raspberrypi/pico-micropython-examples) — PIO WS2812 example

---

*Button Blasters is a personal/hobby project. Not a commercial product.*
