# Button Blasters — Hardware Bring-Up Tests

Run these scripts **in order**, one at a time, directly from VS Code
using MicroPico: "Run current file on Pico".

Do NOT upload main.py until Test 6 passes.

---

## Test sequence

| Script | Tests | Wire before running |
|---|---|---|
| `test_01_pico_health.py` | Pico 2W, RAM, flash, LED blink | USB only |
| `test_02_main_display.py` | ILI9488 colour fills, speed | Main display (9 pins) |
| `test_03_touch.py` | FT6236 I2C, coordinates, axis check | + CTP_SDA/SCL/INT |
| `test_04_button_displays.py` | ST7789 ×4, CS isolation, checkerboard | + 4× button displays |
| `test_05_buttons.py` | All 6 buttons, debounce, hold | + 6 buttons |
| `test_06_integration.py` | Everything together, FPS, SD card | Full wiring |

---

## Before Test 6 — get sdcard.py

Test 6 mounts the SD card. You need `sdcard.py` on the Pico root.

Download it from:
https://github.com/micropython/micropython-lib/blob/master/micropython/drivers/storage/sdcard/sdcard.py

Upload it to the Pico root alongside main.py.

---

## Troubleshooting quick reference

| Symptom | Likely cause |
|---|---|
| Display blank/white | Check RST, DC, CS wiring |
| Display wrong colours | Check MOSI and SCK |
| Touch not found | Check CTP_SDA→GP26, CTP_SCL→GP27 |
| Touch axes wrong | Set TOUCH_FLIP_X/Y in config.py |
| SD not mounting | Insert card, check sdcard.py on Pico |
| Button not detected | Check GND leg, internal pull-up active |
| ImportError | Upload missing file to Pico |
| MemoryError | Run gc.collect() in REPL |

---

## GPIO quick reference (Pico 2W)

```
GP2   TOUCH_INT          GP3   SPI SCK
GP4   SPI MOSI           GP5   SPI MISO
GP6   CS main display    GP7   CS BTN-0
GP8   CS BTN-1           GP9   CS BTN-2
GP10  CS BTN-3           GP11  CS SD card
GP12  DC main            GP13  DC BTN-0
GP14  DC BTN-1           GP15  DC BTN-2
GP16  DC BTN-3           GP17  RST main
GP18  RST all BTNs       GP19  Screen button 0
GP20  Screen button 1    GP21  Screen button 2
GP22  Screen button 3    GP26  I2C SDA (touch)
GP27  I2C SCL (touch)    GP28  NAV BACK

⚠ DO NOT USE: GP23, GP24, GP25, GP29 — WiFi chip internal
```
