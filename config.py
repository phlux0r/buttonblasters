# config.py
# Button Blasters — hardware-verified pin map
# RP2350 Pico 2W
#
# ── SPI bus ──────────────────────────────────────────────────────
SPI_ID           = 0
PIN_SCK          = 18    # ✓ verified
PIN_MOSI         = 19    # ✓ verified
PIN_MISO         = 4     # ✓ verified
SPI_FREQ_DISPLAY = 10_000_000
SPI_FREQ_SD_INIT =    400_000
SPI_FREQ_SD_DATA = 10_000_000

# ── ILI9488 main display ─────────────────────────────────────────
PIN_CS_MAIN  = 6     # ✓ verified
PIN_DC_MAIN  = 12    # ✓ verified
PIN_RST_MAIN = 17    # ✓ verified
# LED wired directly to 3.3V — no GPIO needed

# IPS panel — confirmed critical settings
ILI9488_PIXEL_FORMAT = 0x66   # 18-bit RGB666
ILI9488_VCOM         = 0x4D   # supplier confirmed
ILI9488_IPS          = True   # 0x21 inversion required

# ── ST7789 button displays (×4) ──────────────────────────────────
PIN_CS_BTN   = (7, 8, 9, 10)
PIN_DC_BTN   = (5, 11, 13, 14)
PIN_RST_BTN  = 15

# ── SD card (built into main display module) ─────────────────────
PIN_CS_SD    = 16    # SD_CS on display module — free from DC conflict

# ── Display geometry ─────────────────────────────────────────────
MAIN_W, MAIN_H = 320, 480    # native portrait
BTN_W,  BTN_H  = 240, 280    # ST7789 1.69"
NUM_BTN_SCREENS = 4

# ── I²C — FT6236 touch ───────────────────────────────────────────
I2C_ID         = 1
PIN_I2C_SDA    = 26
PIN_I2C_SCL    = 27
PIN_TOUCH_INT  = 28
PIN_TOUCH_RST  = None    # 10kΩ pull-up to 3.3V on breadboard
I2C_FREQ       = 400_000
TOUCH_IC       = "FT6236"
TOUCH_I2C_ADDR = 0x38
TOUCH_W        = 320
TOUCH_H        = 480
TOUCH_SWAP_XY  = False   # verify in Test 3
TOUCH_FLIP_X   = False
TOUCH_FLIP_Y   = False
SWIPE_MIN_PX   = 40
SWIPE_MAX_MS   = 400
LONG_PRESS_MS  = 600
TAP_MAX_TRAVEL = 12

# ── Buttons ───────────────────────────────────────────────────────
# ⚠ GPIO expander (MCP23008) needed for full button set
# Temporary proto assignments using remaining free pins:
PIN_BTN_SCREEN = (19, 20, 21, 22)   # placeholder — conflicts likely
PIN_BTN_NAV    = (0, 1)
BTN_DEBOUNCE_MS = 30

# ── Audio / LEDs / Haptic ─────────────────────────────────────────
# Pending GPIO expander — placeholders only
PIN_I2S_BCLK   = None
PIN_I2S_LRC    = None
PIN_I2S_DIN    = None
PIN_LED_STRIP  = None
PIN_HAPTIC     = None
PIN_BAT_ADC    = None
AUDIO_SAMPLE_RATE = 22050
AUDIO_BITS     = 16
AUDIO_BUF_BYTES = 4096
NUM_LEDS       = 10
LED_BRIGHTNESS = 0.35
HAPTIC_PULSE_MS = 60
BAT_FULL_V     = 4.2
BAT_EMPTY_V    = 3.3
BAT_WARN_PCT   = 15

# ── UX ────────────────────────────────────────────────────────────
MENU_SCROLL_MS      = 120
GAME_RETURN_IDLE_S  = 60
SCREEN_DIM_S        = 120

# ══════════════════════════════════════════════════════════════════
# GPIO SUMMARY
#  GP0   NAV BACK          GP1   NAV NEXT
#  GP4   SPI MISO          GP5   DC BTN-0
#  GP6   CS MAIN ✓         GP7   CS BTN-0
#  GP8   CS BTN-1          GP9   CS BTN-2
#  GP10  CS BTN-3          GP11  DC BTN-1
#  GP12  DC MAIN ✓         GP13  DC BTN-2
#  GP14  DC BTN-3          GP15  RST BTN
#  GP16  CS SD             GP17  RST MAIN ✓
#  GP18  SPI SCK ✓         GP19  SPI MOSI ✓
#  GP26  I2C SDA           GP27  I2C SCL
#  GP28  TOUCH INT
#  GP2,3,20,21,22 free
#  GP23,24,25,29 WiFi — DO NOT USE
# ══════════════════════════════════════════════════════════════════