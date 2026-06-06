# 🎮 Button Blasters

A DIY  handheld kids' game console built around the **RP2040 Pico**, featuring a 4" capacitive touchscreen, four button-mounted LCD screens, ambient LED lighting, and quality I2S audio. Designed for ages 4–7. Fully 3D-printed shell.

![MicroPython](https://img.shields.io/badge/MicroPython-1.23%2B-green.svg)
![Platform: RP2040](https://img.shields.io/badge/Platform-RP2040-red.svg)
![Status: In Development](https://img.shields.io/badge/Status-In%20Development-yellow.svg)

---

## ✨ What Is This?

Button Blasters is a handheld game console with a twist: **four of the six input buttons have their own small LCD screens**. Games can show images, numbers, colours, or symbols on the button screens and ask players to match, tap, or react to what they see — creating an input experience unique to this device.

The project is fully open-source: firmware, hardware design notes, and 3D print files (coming soon).

---

## 📸 Hardware Overview

| Component | Spec |
|---|---|
| MCU | RP2040 Pico (8 MB flash variant) |
| Main display | ST7796 4.0" 480×320 capacitive touch (FT6336 / GT911) |
| Button LCDs | 4× ST7789 1.69" 240×280 TFT |
| Storage | microSD card (bitmaps + audio) |
| Audio | MAX98357A I2S DAC + amp → 40mm 3W 4Ω speaker |
| LEDs | WS2812B strip (8–12 LEDs, shell edge) |
| Haptic | ERM coin vibration motor |
| Power | LiPo 3.7V 2000mAh + TP4056 USB-C charger |
| Shell | 3D-printed PLA+ or PETG |

**Estimated battery life:** ~7–8 hours typical play.

---

## 🗂 Firmware Structure

```
buttonblasters/
├── main.py                  # Entry point — boots kernel
├── config.py                # All pin assignments & constants (edit this)
│
├── drivers/
│   ├── spi_bus.py           # Shared SPI0 bus with asyncio locking
│   ├── display.py           # ST7796 (main) + ST7789 (buttons) drivers
│   ├── touch.py             # FT6336 / GT911 capacitive touch driver
│   ├── buttons.py           # Physical buttons + touch unified event queue
│   ├── audio.py             # I2S streaming, 2-channel voice/SFX mixer
│   ├── leds.py              # WS2812B via RP2040 PIO (zero CPU overhead)
│   ├── haptic.py            # ERM motor pulse patterns
│   └── assets.py            # SD card mount, image index, async loader
│
├── core/
│   ├── kernel.py            # Boot sequence, task tree, game↔menu cycle
│   ├── menu.py              # Animated game carousel with swipe navigation
│   ├── display_manager.py   # High-level drawing API for games
│   └── game_base.py         # BaseGame abstract class
│
└── games/
    ├── registry.py          # Register games here (one line each)
    └── example/
        └── game.py          # Fully working game template — copy to start
```

The firmware uses **MicroPython asyncio** for cooperative multitasking. All five displays share a single SPI bus via a lock; touch, buttons, LEDs, and audio each run as independent background tasks.

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

Both physical buttons and touch events arrive from the same queue:

```python
# Physical buttons
btn = await self.wait_screen_button()       # blocks until btn 0-3 pressed
btn = await self.wait_any_button()          # any button including nav

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

---

## 🖼 Asset Pipeline

All bitmaps and audio are stored on the microSD card.

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

### Audio Format

16-bit signed PCM WAV, mono, 22050 Hz:
```bash
ffmpeg -i input.mp3 -ar 22050 -ac 1 -acodec pcm_s16le output.wav
```

---

## ⚡ GPIO Pin Map

| GPIO | Function |
|---|---|
| GP0 | I²C SDA (touch IC) |
| GP1 | I²C SCL (touch IC) |
| GP2 | TOUCH_INT (interrupt) |
| GP3 | SPI SCK |
| GP4 | SPI MOSI |
| GP5 | SPI MISO |
| GP6 | CS — ST7796 main display |
| GP7–10 | CS — ST7789 button LCDs 0–3 |
| GP11 | CS — SD card |
| GP12 | DC — ST7796 |
| GP13–16 | DC — ST7789 0–3 |
| GP17 | RST — ST7796 |
| GP18 | RST — ST7789 (shared) |
| GP19–22 | Screen buttons 0–3 |
| GP23 | I2S BCLK |
| GP24 | I2S LRC |
| GP25 | I2S DIN |
| GP26 | Battery ADC (100kΩ + 100kΩ divider) |
| GP27 | NAV BACK button |
| GP28 | WS2812B data (via 74AHCT1G125) |
| GP29 | Haptic motor (via NPN transistor) |

> **Note:** WS2812B LEDs need 5V data logic. Use a 74AHCT1G125 single-gate buffer between GP28 and the LED strip DIN pin.

---

## 🔧 Getting Started

### Flash MicroPython

1. Hold BOOTSEL on the Pico and plug into USB — it mounts as a drive
2. Download the latest MicroPython `.uf2` from [micropython.org](https://micropython.org/download/rp2-pico/)
3. Drag the `.uf2` onto the Pico drive — it reboots automatically

### Install the Firmware

Using [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html):
```bash
pip install mpremote
mpremote connect auto cp -r buttonblasters/ :
```

Or use **VS Code + MicroPico extension** for a GUI workflow (see IDE section below).

### Prepare the SD Card

Format as FAT32 and create the directory structure shown above. Copy your bitmap and audio assets into the appropriate folders.

### Configuration

All hardware pin assignments and tunable constants live in **`config.py`**. This is the only file you need to edit when adapting to a different PCB layout or module variant.

Key settings to check for your specific touch module:
```python
TOUCH_IC      = "FT6336"    # or "GT911"
TOUCH_SWAP_XY = False       # True if axes are transposed
TOUCH_FLIP_X  = False       # True if X is mirrored
TOUCH_FLIP_Y  = False       # True if Y is mirrored
```

---

## 💻 Recommended IDE

**VS Code + [MicroPico extension](https://marketplace.visualstudio.com/items?itemName=paulober.pico-w-go)**

- Syncs your project folder to the Pico in one click
- Integrated MicroPython REPL in the terminal panel
- Full Python syntax highlighting and autocomplete

> **macOS Big Sur (11.x) users:** VS Code 1.91 crashes on Big Sur. Download **v1.90** or **v1.106** directly from [code.visualstudio.com/updates](https://code.visualstudio.com/updates) and disable auto-updates after installing.

**Thonny** is a simpler alternative if you prefer a dedicated MicroPython IDE — works on all macOS versions and requires no configuration.

---

## 🎮 Planned Games

| Game | Type | Uses touch? |
|---|---|---|
| Shape Match | Matching | Partial |
| Button Memory | Memory sequence | No |
| Star Bonk | Reaction | No |
| Count It! | Counting | Yes — tap to count |
| Colour Quest | Exploration | Yes |
| Beat Along | Rhythm | Yes — drum pads |
| *(your game here)* | | |

---

## 🔌 Power & Charging

- **Battery:** LiPo 3.7V 2000mAh (503759 or similar flat cell)
- **Charger:** TP4056 module **with DW01 protection IC** — essential for a kids' device
- **Charging:** USB-C, ~2 hours to full
- **Switch:** SPDT slide switch on the 3.3V regulated rail
- **Battery indicator:** Shown on main screen via ADC voltage divider

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
