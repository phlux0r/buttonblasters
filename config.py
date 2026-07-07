# config.py — Button Blasters v3.0
# Hardware-verified pin map — RP2350 Pico 2W
# All values confirmed through hardware bring-up tests 1-11.
# Do not change pin assignments without re-running bring-up tests.

# ── SPI bus (SPI0) ───────────────────────────────────────────────
SPI_ID           = 0
PIN_SCK          = 18    # ✓ verified — only valid SCK for SPI0
PIN_MOSI         = 19    # ✓ verified — only valid MOSI for SPI0
PIN_MISO         = 4     # ✓ verified
SPI_FREQ_DISPLAY = 10_000_000
SPI_FREQ_SD_INIT =    400_000
SPI_FREQ_SD_DATA = 10_000_000

# ── ILI9488 main display (4.0" IPS 320×480) ─────────────────────
PIN_CS_MAIN  = 6
PIN_DC_MAIN  = 12
PIN_RST_MAIN = 17
# LED/backlight wired directly to 3.3V — no GPIO needed
ILI9488_VCOM = 0x4D   # supplier confirmed critical value
MAIN_W       = 480
MAIN_H       = 320
ILI9488_MADCTL = 0x28   # landscape. Rotation options (all BGR):
#   0x48 = portrait (current)      0x28 = landscape
#   0x88 = portrait flipped        0xE8 = landscape flipped (180° of 0x28)

# ── ST7789 button displays (×4, 1.69" 240×300) ──────────────────
PIN_CS_BTN   = (7, 8, 9, 10)
PIN_DC_BTN   = (2, 11, 14, 21)   # GP2 for BTN-0 (GP5 is DEAD)
PIN_RST_BTN  = 15                  # shared reset
PIN_BLK_BTN  = 13                  # MUST be driven HIGH from GPIO
BTN_W        = 240
BTN_H        = 300
NUM_BTN_SCREENS = 4

# ── SD card — DEFERRED ───────────────────────────────────────────
# ILI9488 SDO permanently drives MISO low — built-in slot unusable.
# Separate SPI breakout needed. GP3 reserved for SD_CS.
PIN_CS_SD  = 3
SD_DEFERRED = False

# ── I²C — FT6236 touch + MCP23008 expander ──────────────────────
# Both devices share the same I2C bus.
I2C_ID         = 1
PIN_I2C_SDA    = 26
PIN_I2C_SCL    = 27
I2C_FREQ       = 400_000

# FT6236 touch
PIN_TOUCH_INT  = 28    # TOUCH_INT only — not a button
PIN_TOUCH_RST  = None  # 10kΩ pull-up to 3.3V on board
TOUCH_I2C_ADDR = 0x38
TOUCH_W        = 480
TOUCH_H        = 320
TOUCH_SWAP_XY  = True
TOUCH_FLIP_X   = False
TOUCH_FLIP_Y   = True
SWIPE_MIN_PX   = 40
SWIPE_MAX_MS   = 400
LONG_PRESS_MS  = 600
TAP_MAX_TRAVEL = 12

# MCP23008 GPIO expander
MCP_I2C_ADDR   = 0x20   # A0/A1/A2 all tied to GND

# ── Physical buttons — via MCP23008 ─────────────────────────────
# Buttons wired to MCP23008 GPIO pins (polled over I2C).
# One leg → MCP GPIO pin, other leg → GND.
# Internal pull-ups enabled — no external resistors needed.
# MCP GPIO reads HIGH at rest, LOW when pressed.
MCP_BTN_SCREEN = (0, 1, 2, 3)   # SCREEN-0..3 on MCP GP0-GP3
MCP_BTN_BACK   = 4               # BACK/HOME on MCP GP4
MCP_BTN_MASK   = 0x1F            # bits 0-4

# BTN-0 = PREV ← in menu   BTN-3 = NEXT → in menu
# BTN-1 / BTN-2 = game previews / context actions
BTN_DEBOUNCE_MS = 30
BTN_HOLD_MS     = 600
BTN_POLL_MS     = 10             # MCP23008 poll interval

# ── Audio — MAX98357A I2S ✓ confirmed ────────────────────────────
PIN_I2S_BCLK      = 0    # ✓ confirmed GP0
PIN_I2S_LRC       = 1    # ✓ confirmed GP1
PIN_I2S_DIN       = 16   # ✓ confirmed GP16
AUDIO_SAMPLE_RATE = 22050
AUDIO_BITS        = 16
AUDIO_BUF_BYTES   = 4096

# ── WS2812B LEDs ✓ confirmed ─────────────────────────────────────
# Data via 74AHCT125 level shifter (3.3V → 5V).
# 330Ω series resistor on data line.
# Strip powered from VBUS (5V).
PIN_LED_STRIP  = 20    # ✓ confirmed GP20
NUM_LEDS       = 8     # current strip — may expand later
LED_BRIGHTNESS = 0.35

# ── Haptic motor ✓ confirmed ─────────────────────────────────────
# ERM coin motor via 2N3904 NPN transistor.
# 1kΩ resistor on base, 1N4148 flyback diode across motor.
PIN_HAPTIC     = 22    # ✓ confirmed GP22
HAPTIC_PULSE_MS = 60

# ── Battery ADC — pending ────────────────────────────────────────
# Voltage divider → MCP23008 GP5 (future — not yet wired)
PIN_BAT_ADC    = None
BAT_FULL_V     = 4.2
BAT_EMPTY_V    = 3.3
BAT_WARN_PCT   = 15

# ── Dead / reserved pins ─────────────────────────────────────────
# GP5  — DEAD. Output driver measures -4.2mV when set HIGH. Never use.
# GP23/24/25/29 — WiFi internal. Never connect anything.

# ── UX timing ────────────────────────────────────────────────────
MENU_SCROLL_MS     = 120
GAME_RETURN_IDLE_S = 60
SCREEN_DIM_S       = 120

# ══════════════════════════════════════════════════════════════════
# CONFIRMED GPIO SUMMARY
#  GP0   I2S BCLK → MAX98357A    GP1   I2S LRC → MAX98357A
#  GP2   DC BTN-0                GP3   SD_CS (reserved)
#  GP4   SPI MISO                GP5   DEAD — never use
#  GP6   CS MAIN                 GP7   CS BTN-0
#  GP8   CS BTN-1                GP9   CS BTN-2
#  GP10  CS BTN-3                GP11  DC BTN-1
#  GP12  DC MAIN                 GP13  BLK ST7789
#  GP14  DC BTN-2                GP15  RST ST7789s
#  GP16  I2S DIN → MAX98357A     GP17  RST MAIN
#  GP18  SPI SCK                 GP19  SPI MOSI
#  GP20  WS2812B → 74AHCT125     GP21  DC BTN-3
#  GP22  Haptic → 2N3904         GP26  I2C SDA
#  GP27  I2C SCL                 GP28  TOUCH_INT only
#  GP23/24/25/29 WiFi — NEVER CONNECT
#
# MCP23008 (0x20) GPIO:
#  MCP0  SCREEN-0 button         MCP1  SCREEN-1 button
#  MCP2  SCREEN-2 button         MCP3  SCREEN-3 button
#  MCP4  BACK/HOME button        MCP5  Battery ADC (future)
#  MCP6  spare                   MCP7  spare
# ══════════════════════════════════════════════════════════════════
