# config.py
# Button Blasters — hardware-verified pin map
# RP2350 Pico 2W  |  All pins confirmed via hardware bring-up tests
#
# ── SPI bus (SPI0) ───────────────────────────────────────────────
SPI_ID           = 0
PIN_SCK          = 18    # ✓ verified — only valid SCK for SPI0
PIN_MOSI         = 19    # ✓ verified — only valid MOSI for SPI0
PIN_MISO         = 4     # ✓ verified
SPI_FREQ_DISPLAY = 10_000_000
SPI_FREQ_SD_INIT =    400_000
SPI_FREQ_SD_DATA = 10_000_000

# ── ILI9488 main display (4.0" IPS 320×480) ─────────────────────
PIN_CS_MAIN  = 6     # ✓ verified
PIN_DC_MAIN  = 12    # ✓ verified
PIN_RST_MAIN = 17    # ✓ verified
# LED/backlight wired directly to 3.3V — no GPIO needed

# IPS panel — confirmed critical init values
ILI9488_VCOM = 0x4D   # supplier confirmed "important!!!"
MAIN_W       = 320
MAIN_H       = 480

# ── ST7789 button displays (×4, 1.69" 240×300) ──────────────────
PIN_CS_BTN   = (7, 8, 9, 10)       # BTN-0 … BTN-3
PIN_DC_BTN   = (2, 11, 14, 21)     # BTN-0 uses GP2 (GP5 is DEAD)
PIN_RST_BTN  = 15                   # shared reset for all four
PIN_BLK_BTN  = 13                   # MUST be driven HIGH from GPIO
                                     # (tying to 3.3V does not work)
BTN_W        = 240
BTN_H        = 300    # 300 rows fills the full physical screen
NUM_BTN_SCREENS = 4

# ── SD card — DEFERRED ───────────────────────────────────────────
# Built-in SD slot on ILI9488 module is unusable:
#   ILI9488 SDO pin permanently drives MISO low (confirmed 0V on GP4).
# Solution: separate SPI SD card breakout module with dedicated MISO.
# GP3 reserved for SD_CS when breakout is sourced.
PIN_CS_SD    = 3     # reserved — do not use for anything else
SD_DEFERRED  = True

# ── I²C — FT6236 capacitive touch ───────────────────────────────
I2C_ID         = 1
PIN_I2C_SDA    = 26
PIN_I2C_SCL    = 27
PIN_TOUCH_INT  = 28   # TOUCH_INT only — NOT a nav button
PIN_TOUCH_RST  = None # 10kΩ pull-up to 3.3V on board
I2C_FREQ       = 400_000
TOUCH_I2C_ADDR = 0x38
TOUCH_W        = 320
TOUCH_H        = 480
TOUCH_SWAP_XY  = False
TOUCH_FLIP_X   = False
TOUCH_FLIP_Y   = False
SWIPE_MIN_PX   = 40
SWIPE_MAX_MS   = 400
LONG_PRESS_MS  = 600
TAP_MAX_TRAVEL = 12

# ── Physical buttons ─────────────────────────────────────────────
# Screen buttons — one under each ST7789 display
# Press triggers the action shown on that display
PIN_BTN_SCREEN   = (20, 22, 0, 1)  # SCREEN-0 … SCREEN-3
                                     # maps to BTN display index 0-3

# Navigation — single BACK/HOME button
PIN_BTN_BACK     = 16

# NAV-NEXT removed — BTN-0 and BTN-3 screen buttons serve as
# PREV/NEXT in menu context (shown with ← → arrow icons)
# BTN-0 = PREV ←   BTN-3 = NEXT →
# BTN-1, BTN-2 = game previews / context actions

BTN_DEBOUNCE_MS  = 30
BTN_HOLD_MS      = 600

# ── Dead / reserved pins ─────────────────────────────────────────
# GP5  — DEAD/SHORTED on this board. Output driver measures -4.2mV
#         when set HIGH. Never use for any purpose.
# GP23, GP24, GP25, GP29 — WiFi internal. Never connect anything.

# ── Audio — MAX98357A I2S DAC ────────────────────────────────────
# Not yet wired — pins are None until audio hardware is connected.
PIN_I2S_BCLK      = None  # pending
PIN_I2S_LRC       = None  # pending
PIN_I2S_DIN       = None  # pending
AUDIO_SAMPLE_RATE = 22050
AUDIO_BITS        = 16
AUDIO_BUF_BYTES   = 4096

# ── WS2812B LEDs — via 74AHCT125 level shifter ──────────────────
# Not yet wired.
PIN_LED_STRIP  = None  # pending
NUM_LEDS       = 10
LED_BRIGHTNESS = 0.35

# ── Haptic motor ─────────────────────────────────────────────────
# Not yet wired.
PIN_HAPTIC     = None  # pending
HAPTIC_PULSE_MS = 60

# ── Battery ADC ──────────────────────────────────────────────────
PIN_BAT_ADC    = None  # pending
BAT_FULL_V     = 4.2
BAT_EMPTY_V    = 3.3
BAT_WARN_PCT   = 15

# ── UX timing ────────────────────────────────────────────────────
MENU_SCROLL_MS     = 120
GAME_RETURN_IDLE_S = 60
SCREEN_DIM_S       = 120

# ══════════════════════════════════════════════════════════════════
# CONFIRMED GPIO SUMMARY (hardware-tested)
#
#  GP0   SCREEN-2 button    GP1   SCREEN-3 button
#  GP2   DC BTN-0           GP3   SD_CS (reserved, breakout pending)
#  GP4   SPI MISO ✓         GP5   DEAD — never use
#  GP6   CS MAIN ✓          GP7   CS BTN-0
#  GP8   CS BTN-1            GP9   CS BTN-2
#  GP10  CS BTN-3            GP11  DC BTN-1
#  GP12  DC MAIN ✓           GP13  BLK ST7789 (GPIO HIGH)
#  GP14  DC BTN-2            GP15  RST all ST7789s
#  GP16  BACK/HOME button    GP17  RST MAIN ✓
#  GP18  SPI SCK ✓           GP19  SPI MOSI ✓
#  GP20  SCREEN-0 button     GP21  DC BTN-3
#  GP22  SCREEN-1 button     GP26  I2C SDA
#  GP27  I2C SCL             GP28  TOUCH_INT (not a button)
#  GP23/24/25/29  WiFi internal — NEVER CONNECT
# ══════════════════════════════════════════════════════════════════
