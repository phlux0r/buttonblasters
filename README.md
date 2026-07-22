# 🎮 Button Blasters

A DIY handheld kids' game console built around the **Raspberry Pi Pico 2 W (RP2350)**, featuring a 4" capacitive touchscreen, four button-mounted LCD screens, ambient LED lighting, and quality I2S audio. Designed for ages 4–7. Fully 3D-printed shell.

![MicroPython](https://img.shields.io/badge/MicroPython-1.28.0-green.svg)
![Platform: RP2350](https://img.shields.io/badge/Platform-RP2350-red.svg)
![Status: In Development](https://img.shields.io/badge/Status-In%20Development-yellow.svg)

---

## ✨ What Is This?

Button Blasters is a handheld game console with a twist: **four of the six input buttons have their own small LCD screens**. Games can show images, numbers, colours, or symbols on the button screens and ask players to match, tap, or react to what they see — creating an input experience unique to this device.

The project is fully open-source: firmware, hardware design notes, and 3D print files (coming soon).

> **Hardware bring-up is complete.** All confirmed pin assignments, driver-level gotchas, and bench-test results live in [`documents/HARDWARE_NOTES.md`](documents/HARDWARE_NOTES.md) — read that before touching `config.py` or the display/touch drivers.

---

## 📸 Hardware Overview

| Component | Spec |
|---|---|
| MCU | Raspberry Pi Pico 2 W (RP2350, 4 MB flash) |
| Main display | ILI9488 4.0" IPS 480×320, FT6236 capacitive touch, 18-bit RGB666 |
| Button LCDs | 4× ST7789 1.69" 300×240 landscape (effective), RGB565 |
| Storage | microSD card via separate SPI breakout (bitmaps + audio) |
| Audio | MAX98357A I2S DAC + amp → 40mm 3W 4Ω speaker |
| LEDs | WS2812B strip (8 LEDs, shell edge) via 74AHCT125 level shifter |
| Haptic | ERM coin vibration motor via 2N3904 NPN transistor |
| GPIO expander | MCP23008 I²C DIP-8 (0x20) — all physical buttons |
| Power | LiPo 3.7V 1200mAh + TP4056 USB-C charger (wiring pending) |
| Shell | 3D-printed PLA+ or PETG |

**Dev environment:** MicroPython v1.28.0 (RPI_PICO2_W build), VS Code + MicroPico extension.

---

## 🗂 Firmware Structure

```
buttonblasters/
├── main.py                  # Entry point — boots kernel
├── config.py                # Hardware-verified pin map & constants (edit this)
├── sdcard.py                # SD card block driver (FAT filesystem)
├── rgb666_viper.py          # @micropython.viper RGB565→RGB666 band converter (31x speedup)
│
├── drivers/
│   ├── spi_bus.py           # Shared SPI0 bus, asyncio-locked, cache-aware freq switching
│   ├── display.py           # ILI9488 (main) + ST7789 (buttons) drivers
│   ├── touch.py             # FT6236 capacitive touch driver
│   ├── buttons.py           # MCP23008-polled buttons + touch, unified event queue
│   ├── audio.py             # I2S streaming via IRQ callback (non-blocking)
│   ├── leds.py               # WS2812B via RP2040 PIO
│   ├── strip_renderer.py    # LED effect sequencing (asyncio tasks)
│   ├── haptic.py             # ERM motor pulse patterns
│   ├── assets.py             # SD card mount, image index, async loader
│   └── flash_assets.py      # On-flash fallback asset loading
│
├── core/
│   ├── kernel.py             # Boot sequence, task tree, game↔menu cycle
│   ├── menu.py                # Animated game carousel with swipe navigation
│   ├── display_manager.py    # High-level drawing API for games
│   ├── game_base.py          # BaseGame abstract class
│   ├── game_cache.py         # Per-game asset caching
│   ├── sprite_engine.py      # Sprite compositing/animation
│   └── sprite_adapter.py     # Bridges sprite engine to display_manager
│
├── games/
│   ├── registry.py           # Register games here (one line each)
│   ├── example/              # Working game template — copy to start a new game
│   └── match/                # Shape Match — first playable game (shapes/letters/numbers)
│
├── assets/                   # Bitmaps checked into the repo (menu, sys, per-game)
├── documents/                 # Hardware notes, narrator script, family recording guide
├── tools/                     # deploy.py — stages & installs firmware to the Pico
└── tests/                     # Hardware bring-up + performance test scripts (see below)
```

The firmware uses **MicroPython asyncio** for cooperative multitasking. All five displays share a single SPI bus via a lock; touch, buttons (via MCP23008), LEDs, and audio each run as independent background tasks.

---

## 🕹 Adding a Game

Every game is a self-contained folder under `games/`. To add one:

**1. Copy the example template**
```
cp -r games/example games/my_game
```

**2. Edit `games/my_game/game.py`** — subclass `BaseGame` and implement three methods:

```python
class MyGame(BaseGame):
    GAME_ID     = "my_game"
    TITLE       = "My Game"
    DESCRIPTION = "A short description shown in the menu."
    ICON_FILE   = "my_game/icon_64x64.raw"   # image on SD card

    async def load(self):
        # Preload bitmaps, clear displays, set up state
        await self.display.clear_all()

    async def run(self) -> GameResult:
        # Main game loop — return GameResult when done
        await self.countdown(3)
        btn = await self.wait_screen_button()   # 0-3
        # ... your game logic ...
        return self._make_result()

    async def unload(self):
        await super().unload()   # stops audio, clears screens
```

**3. Register it** in `games/registry.py`:
```python
_register("games.my_game.game", "MyGame")
```

That's it. The kernel handles the menu card, transitions, score saving, back button, and LED effects automatically.

### Input API

Physical buttons (via MCP23008) and touch events arrive from the same queue:

```python
# Physical buttons
btn = await self.wait_screen_button()       # blocks until btn 0-3 pressed
btn = await self.wait_any_button()          # any button including BACK

# Touch
x, y = await self.wait_tap()               # blocks until screen tap
btn, evt = await self.wait_tap_or_button() # accepts either input type

# Check if a tap landed on a zone
if self.tap_hit(x, y, (rect_x, rect_y, rect_w, rect_h)):
    ...

# Shared feedback helpers
await self.show_correct()    # green LED flash + ding sound
await self.show_wrong()      # red LED flash + wrong sound
await self.show_level_up()   # rainbow LEDs + voice clip
await self.countdown(3)      # 3-2-1-GO! with audio
```

> `wait_screen_button()` does not return the BACK button (id 4) — games that need BACK-to-quit must poll `buttons._queue` directly. See `games/example/game.py` or `games/match/game.py`.

---

## 🖼 Asset Pipeline

All bitmaps and audio are stored on the microSD card (with an on-flash fallback via `drivers/flash_assets.py`).

### SD Card Layout

```
/sd/
  images/
    shared/          ← icons used by multiple games
    <game_id>/       ← per-game bitmaps
  audio/
    sfx/             ← short sound effects  (ding.wav, wrong.wav …)
    voice/           ← voice clips          (correct.wav, well_done.wav …)
    music/           ← background loops     (menu.wav …)
  adventure/
    stories/         ← JSON story data for "My Big Day Out"
  scores.json        ← auto-generated, do not edit
```

### Bitmap Format

Raw RGB565, little-endian, no header. Filename must encode dimensions:

```
cat_64x64.raw        ← 64×64 pixels
background_480x320.raw
```

Convert from PNG using ffmpeg:
```bash
ffmpeg -i input.png -vf scale=64:64 -pix_fmt rgb565le output_64x64.raw
```

The main display consumes 18-bit RGB666, not RGB565 — bitmaps stay RGB565 on disk and are converted band-by-band at draw time by `graphics_speed/rgb666_viper.py` (see hardware notes for why this can't be a full-buffer conversion).

### Audio Format

16-bit signed PCM WAV, mono, 22050 Hz:
```bash
ffmpeg -i input.mp3 -ar 22050 -ac 1 -acodec pcm_s16le output.wav
```

---

## ⚡ GPIO Pin Map

Confirmed via hardware bring-up tests 1–14 (see `tests/`). Full context and rationale for each pin choice is in [`documents/HARDWARE_NOTES.md`](documents/HARDWARE_NOTES.md).

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
| GP13 | BLK — ST7789 backlight (driven HIGH from GPIO, not tied to 3.3V) |
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
| GP25 | WiFi CS-equivalent — held HIGH during battery reads (not bench-confirmed) |
| GP29 | VSYS monitor / ADC3 — battery voltage (not bench-confirmed) |
| MCP23008 GP0–3 | Screen buttons 0–3 |
| MCP23008 GP4 | BACK/HOME button |
| MCP23008 GP5 | Spare — battery monitoring moved to GP29/ADC3 (MCP23008 has no ADC) |

> **Note:** WS2812B LEDs need 5V data logic. A 74AHCT125 level shifter sits between GP20 and the LED strip DIN pin.

---

## 🔧 Getting Started

### Flash MicroPython

1. Hold BOOTSEL on the Pico 2 W and plug into USB — it mounts as a drive
2. Download the RPI_PICO2_W MicroPython `.uf2` (v1.28.0+) from [micropython.org](https://micropython.org/download/rpi_pico2_w/)
3. Drag the `.uf2` onto the Pico drive — it reboots automatically

### Install the Firmware

Use the deploy script — it maps the repo layout to the device layout
(sprites to `/assets/static/`, SD payload staged separately) and skips
tests/docs that would waste flash:

```bash
pip install mpremote
python3 tools/deploy.py                 # stage + install to the Pico
python3 tools/deploy.py --mpy           # smaller: cross-compile to .mpy
python3 tools/deploy.py --dry-run       # stage into build/ to inspect
```

Anything staged under `build/sd/` belongs on the SD card (copy with a card
reader, or `--sd` to push through the mounted card).

**VS Code + MicroPico** (see IDE section below) remains handy for the REPL
and quick single-file iteration, but the script is the reproducible path.

### Prepare the SD Card

Format as FAT32 and create the directory structure shown above. Copy your bitmap and audio assets into the appropriate folders. Use a **separate SPI SD breakout**, not the slot built into the ILI9488 display module — see `documents/HARDWARE_NOTES.md` for why the built-in slot can't be used alongside the display.

### Configuration

All hardware pin assignments and tunable constants live in **`config.py`**, and are already set to the confirmed-working values for this build. Don't change pin assignments without re-running the relevant bring-up test in `tests/`.

Touch orientation must match your display rotation — see the Display Orientation section of `documents/HARDWARE_NOTES.md` before changing any of these:
```python
TOUCH_SWAP_XY = True   # confirmed for landscape (MADCTL 0x28)
TOUCH_FLIP_X  = False
TOUCH_FLIP_Y  = True
```

---

## 💻 Recommended IDE

**VS Code + [MicroPico extension](https://marketplace.visualstudio.com/items?itemName=paulober.pico-w-go)** (tested with v4.3.4)

- Syncs your project folder to the Pico in one click
- Integrated MicroPython REPL in the terminal panel
- Full Python syntax highlighting and autocomplete

> **macOS Big Sur (11.x) users:** VS Code 1.91 crashes on Big Sur. Download **v1.90** or **v1.106** directly from [code.visualstudio.com/updates](https://code.visualstudio.com/updates) and disable auto-updates after installing.

**Thonny** is a simpler alternative if you prefer a dedicated MicroPython IDE — works on all macOS versions and requires no configuration.

---

## 🎮 Game Library

**Playable now:**

| Game | Type | Uses touch? |
|---|---|---|
| Shape Match (`games/match`) | Matching — shapes, letters, numbers, expanding pool | Partial |
| Star Bonk! (`games/bonk`) | Reaction — tap the target before it disappears | Yes — primary input |

Star Bonk! is the first game to use `core/sprite_engine.py` + `drivers/strip_renderer.py` for real (targets pop up at genuinely random positions and need clean erase-and-reveal against the illustrated board — see `documents/HARDWARE_NOTES.md`'s Star Bonk section for the full asset spec and the bench checks still needed before trusting it on hardware).

**Planned** (registered but commented out in `games/registry.py` until implemented):

| Game | Type | Uses touch? |
|---|---|---|
| Button Memory | Simon-style sequence | No |
| Count It! | Counting | Yes — tap to count |
| Magic Sort | Drag and drop sorting | Yes |
| Feed the Animal | Swipe gestures | Yes |
| Magic Bakery | Collect ingredients | Yes |
| Shadow Match | Silhouette identification | Yes |
| Garden Grow | Swipe to water/sun | Yes |
| My Big Day Out | Personalised branching adventure (flagship) | Yes |

**My Big Day Out** is the flagship game: child picks an avatar, family photos get converted to a cartoon style, family members record their own voice lines plus a main narrator, and the branching story is driven by JSON on the SD card (`/sd/adventure/stories/`). Art direction is a soft rounded Bluey/Hey Duggee aesthetic.

---

## 🔌 Power & Charging

**⚠️ PLANNED, NOT YET WIRED — everything in this section is a design, not a confirmed build.** See `documents/HARDWARE_NOTES.md` for the full reasoning behind each decision below.

- **Battery:** LiPo 3.7V 1200mAh flat cell
- **Charger:** TP4056 module **with DW01 protection IC** — essential for a kids' device. Charge current (set by the module's programming resistor) should be chosen to suit this cell's 1200mAh capacity, not assumed from a generic default — confirm the module's actual charge current before wiring it in
- **Charging port:** a **dedicated USB-C port exposed on the shell**, wired to the TP4056 module's own USB input — deliberately separate from the Pico's own micro-USB port
- **Dev/firmware port:** the Pico's onboard micro-USB, tucked behind a removable shell cover — accessible for `mpremote`/flashing, but not a normal-use port. Kept separate from charging so the two never compete for the same connector
- **Power topology:**
  ```
  Battery+/- ──→ TP4056 BAT+/BAT-
  TP4056 OUT+ (protected, through DW01) ──→ [master ON/OFF switch] ──┬──→ MT3608 buck-boost IN+ → 5V_REG
                                                                     │        → MAX98357A VIN + WS2812B strip power
                                                                     └──→ [new] Schottky diode (1N5819, on hand) ──→ Pico VSYS
  All grounds shared common.
  ```
  Everything downstream (VSYS, the boost converter, audio, LEDs) draws from TP4056's *protected* output, not the raw cell — so DW01's over-discharge/over-current protection covers the whole system, not just charging. The added diode between TP4056's output and VSYS specifically prevents the Pico's own dev-USB port from ever pushing current back into the battery if both it and the battery happen to be connected at once — a real risk that came up during bring-up (see HARDWARE_NOTES.md), not just a theoretical one.
- **5V rail (audio + LEDs):** an MT3608 boost converter (2A, 2–24V in → 5–28V adjustable out) steps the battery-derived voltage up to a stable 5V, replacing the MAX98357A's and WS2812B strip's original direct-to-VBUS wiring — VBUS is only powered when USB is connected, so both were previously silent/dim on battery-only power. **The MT3608's output must be set to a clean 5.0V with a multimeter, with nothing connected to its output, before wiring anything to it** — it ships with output voltage unset.
- **Switch:** SPDT slide switch moved to **before the MT3608/VSYS split** (right after TP4056's protected output, per the topology above) — NOT on the Pico's 3.3V regulated rail as originally planned. That original placement was downstream of the Pico's own onboard regulator, so it would only ever have powered the Pico itself down; the MT3608 branch (audio + LEDs) draws independently and would have stayed live, defeating the point of an "off" switch and leaving something drawing on the battery whenever the device is supposedly off
- **Battery indicator:** Reads VSYS directly via the Pico 2 W's native GP29/ADC3 — no extra components. MCP23008 has no ADC capability, so the original GP5 plan was replaced. See `tests/test_16_battery_vsys.py` for the bring-up test and `drivers/battery.py` for the driver. **Bench-confirmed** — the divider ratio needed real calibration (the commonly-documented value was wrong for this board); see `documents/HARDWARE_NOTES.md` for the full story. Not yet wired into the menu/UI

---

## 📄 License

MIT — do whatever you like with it. If you build one, share a photo!

---

## 🙏 Acknowledgements

- [MicroPython](https://micropython.org) — the firmware runtime
- [LovyanGFX](https://github.com/lovyan03/LovyanGFX) — display driver inspiration
- [rp2040-pio-ws2812](https://github.com/raspberrypi/pico-micropython-examples) — PIO LED example

---

*Button Blasters is a personal/hobby project. Not a commercial product.*
