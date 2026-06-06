# config.py
# Button Blasters — hardware pin map & tunable constants
# Edit this file when adapting to a different PCB layout.
# All other modules import from here — never hardcode pins elsewhere.
#
# CHANGE LOG:
#   Rev 1.1 — replaced ILI9488 3.5" with ST7796 4.0" capacitive touch display
#             GP0/GP1 reallocated from UART to I²C for FT6336/GT911 touch IC
#             GP2 reallocated to TOUCH_INT; SCK shifted to GP3 etc.
#             SPI_FREQ_DISPLAY raised to 62 MHz (ST7796 supports it)
#             Debug UART → USB CDC (Thonny / mpremote via USB)

# ── I²C bus — touch controller (FT6336 / GT911) ─────────────────
I2C_ID        = 0
PIN_I2C_SDA   = 0           # GP0 — was UART TX, now I²C SDA
PIN_I2C_SCL   = 1           # GP1 — was UART RX, now I²C SCL
PIN_TOUCH_INT = 2           # GP2 — interrupt line from touch IC (active LOW)
PIN_TOUCH_RST = None        # set to a GPIO if your module exposes RST; else None
I2C_FREQ      = 400_000     # 400 kHz fast-mode

# Touch IC selection — set to whichever IC is on your module
TOUCH_IC      = "FT6336"    # "FT6336" | "GT911"
TOUCH_I2C_ADDR_FT6336 = 0x38
TOUCH_I2C_ADDR_GT911  = 0x14   # or 0x5D depending on INT pin at power-up

# Touch geometry (matches main display, landscape)
TOUCH_W       = 480
TOUCH_H       = 320
TOUCH_SWAP_XY  = False      # set True if axes are transposed on your module
TOUCH_FLIP_X   = False      # set True if X axis is mirrored
TOUCH_FLIP_Y   = False      # set True if Y axis is mirrored

# Gesture detection thresholds
SWIPE_MIN_PX   = 40         # minimum travel distance to register a swipe
SWIPE_MAX_MS   = 400        # maximum time for a swipe gesture
LONG_PRESS_MS  = 600        # hold duration before "long_press" fires
TAP_MAX_TRAVEL = 12         # px — finger must stay this close to tap origin

# ── SPI bus (shared by all displays + SD card) ───────────────────
SPI_ID   = 0
PIN_SCK  = 3                # GP3 (shifted up by 1 to free GP2 for TOUCH_INT)
PIN_MOSI = 4                # GP4
PIN_MISO = 5                # GP5
SPI_FREQ_DISPLAY = 62_000_000   # 62 MHz — ST7796 handles this reliably
SPI_FREQ_SD_INIT =    400_000   # 400 kHz SD card initialisation
SPI_FREQ_SD_DATA = 25_000_000   # 25 MHz SD card data transfer

# ── Display chip-selects ─────────────────────────────────────────
PIN_CS_MAIN   = 6           # ST7796 4.0" main screen
PIN_CS_BTN    = (7, 8, 9, 10)  # ST7789 1.69" button screens 0-3
PIN_CS_SD     = 11          # microSD card

# ── Display DC (data/command) lines ─────────────────────────────
PIN_DC_MAIN   = 12
PIN_DC_BTN    = (13, 14, 15, 16)

# ── Display reset lines ──────────────────────────────────────────
PIN_RST_MAIN  = 17
PIN_RST_BTN   = 18          # single pin — all 4 ST7789s reset together

# ── Display geometry ─────────────────────────────────────────────
MAIN_W, MAIN_H   = 480, 320    # ST7796 4.0" (landscape)
BTN_W,  BTN_H    = 240, 280    # ST7789 (portrait)
NUM_BTN_SCREENS  = 4

# ── Buttons (active LOW, internal pull-up) ───────────────────────
PIN_BTN_SCREEN = (19, 20, 21, 22)   # under the 4 LCD buttons
PIN_BTN_NAV    = (26, 27)            # BACK, NEXT (nav buttons)
BTN_DEBOUNCE_MS = 30

# ── Audio (I2S → MAX98357A) ──────────────────────────────────────
PIN_I2S_BCLK = 23
PIN_I2S_LRC  = 24
PIN_I2S_DIN  = 25
AUDIO_SAMPLE_RATE = 22050   # 22 kHz — good quality, SD-friendly file sizes
AUDIO_BITS        = 16
AUDIO_BUF_BYTES   = 4096    # streaming buffer size

# ── WS2812B LED strip ────────────────────────────────────────────
PIN_LED_STRIP = 28
NUM_LEDS      = 10
LED_BRIGHTNESS = 0.35        # 0.0–1.0 — keep low for battery life

# ── Haptic motor ─────────────────────────────────────────────────
PIN_HAPTIC    = 29
HAPTIC_PULSE_MS = 60         # single short buzz duration

# ── Battery ADC ──────────────────────────────────────────────────
# NOTE: GP29 is used for haptic above, so battery ADC moves to the
# internal Pico VSYS sense pin (ADC input 3 = GP29 on Pico, but the
# Pico also has an internal ADC channel for VSYS/3 on ADC channel 3).
# Alternatively wire the voltage divider to GP26 (ADC0) and set here:
PIN_BAT_ADC    = 26          # ADC0 — wire 100k+100k divider from VBAT here
BAT_FULL_V     = 4.2
BAT_EMPTY_V    = 3.3
BAT_WARN_PCT   = 15          # show warning below this %

# ── Menu / UX ────────────────────────────────────────────────────
MENU_SCROLL_MS      = 120    # ms between menu cursor moves
GAME_RETURN_IDLE_S  = 60     # return to menu after this many idle seconds
SCREEN_DIM_S        = 120    # dim backlight after this many seconds
