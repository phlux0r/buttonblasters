# config.py — Button Blasters v3.0
# Hardware-verified pin map — RP2350 Pico 2W
# All values confirmed through hardware bring-up tests 1-11.
# Do not change pin assignments without re-running bring-up tests.

# ── Core clock ───────────────────────────────────────────────────
# RP2350 default is 150 MHz. Raising it speeds the viper RGB565→666
# conversion AND gives the SPI peripheral higher/finer available bus
# rates (SPI baud is derived by dividing sysclk).
#
# ── HOW TO TUNE ──────────────────────────────────────────────────
#   Default (no overclock):  150_000_000
#   Safe overclock steps:    200_000_000  → 250_000_000  → 300_000_000
#   Applied once at boot in main.py. If the board gets flaky (hangs on
#   boot, USB/REPL drops, random resets), step back down. 200 MHz is a
#   very safe starting overclock for the RP2350. Tune this and
#   SPI_FREQ_DISPLAY independently — change one at a time so you know
#   which one caused any regression.
MACHINE_FREQ     = 250_000_000

# ── SPI bus (SPI0) ───────────────────────────────────────────────
SPI_ID           = 0
PIN_SCK          = 18    # ✓ verified — only valid SCK for SPI0
PIN_MOSI         = 19    # ✓ verified — only valid MOSI for SPI0
PIN_MISO         = 4     # ✓ verified

# Display bus speed. Was 10 MHz (very conservative). The panels can go
# much faster — raising this is the single biggest draw-speed win, since
# every fill/blit funnels through this one bus. The display already ran
# fine at 10 MHz on the current breadboard, so 24 MHz is a safe first step.
#
# ── HOW TO TUNE (on the bench, one step at a time) ───────────────────
#   1. Flash with the current value, then watch ALL FIVE screens during a
#      menu→game transition and a shape blit.
#   2. If everything is clean (no garbled pixels, no flicker, no dropouts),
#      bump to the next step and re-flash:
#         24_000_000  → 32_000_000  → 40_000_000  → 48_000_000
#   3. The FIRST value that shows ANY corruption is too high — drop back to
#      the previous clean step and stop there. That's your ceiling.
#   4. Ceiling depends on wiring quality: this is a breadboard build (see
#      the SD ceiling below), so expect the display to top out lower than a
#      soldered board would. ILI9488 is the limiting panel (~40 MHz on good
#      wiring); the ST7789s tolerate more (~62 MHz).
#   NOTE: actual bus rate is quantised — the RP2350 divides sysclk down, so
#   raising MACHINE_FREQ above gives finer/higher available rates.
SPI_FREQ_DISPLAY = 48_000_000    # starting step — tune upward per notes above

# SD stays slow and decoupled from the display clock — the shared bus
# switches frequency per-device (see drivers/spi_bus.py), so a fast display
# does NOT force a fast SD. Do NOT raise this to match SPI_FREQ_DISPLAY.
SPI_FREQ_SD_INIT =    400_000
SPI_FREQ_SD_DATA =    400_000   # confirmed breadboard ceiling — EIO at
                                 # >=1.32MHz. Target 10MHz on soldered board.

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

# ── ST7789 button displays (×4, 1.69" 300×240 landscape) ─────────
PIN_CS_BTN   = (7, 8, 9, 10)
PIN_DC_BTN   = (2, 11, 14, 21)   # GP2 for BTN-0 (GP5 is DEAD)
PIN_RST_BTN  = 15                  # shared reset
PIN_BLK_BTN  = 13                  # MUST be driven HIGH from GPIO
BTN_W        = 300
BTN_H        = 240
NUM_BTN_SCREENS = 4
# Per-button MADCTL — NOT uniform. Physical mounting is a 2x2 matrix
# (0|2 top row, 1|3 bottom row) with the right column (BTN-2/3) mounted
# physically rotated 180 degrees from the left column (BTN-0/1), for tidy
# cable routing. Same landscape orientation (MV bit set) either way, but
# the 180-degree physical rotation must be compensated in software or
# BTN-2/3 render upside-down/mirrored relative to BTN-0/1.
#   0xA0 = landscape, confirmed via test_15 for BTN-0/1's mounting.
#   0x60 = 0xA0 with MY and MX both toggled (0xA0 ^ 0xC0) — the 180-degree
#          rotation of 0xA0, confirmed via test_15 for BTN-2/3's flipped
#          mounting (both physical positions checked).
# RGB colour order is already correct at bit3=0 in both — do not add
# 0x08/BGR.
ST7789_MADCTL = (0xA0, 0xA0, 0x60, 0x60)   # indexed by BTN-0..3, both
                                            # values bench-confirmed

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

# Physical layout: 2x2 matrix, 0|2 top row, 1|3 bottom row.
# BTN-1 = PREV ← in menu   BTN-3 = NEXT → in menu
# BTN-0 / BTN-2 = game previews / context actions
BTN_DEBOUNCE_MS = 30
BTN_HOLD_MS     = 600
BTN_POLL_MS     = 10             # MCP23008 poll interval

# ── Audio — MAX98357A I2S ✓ confirmed ────────────────────────────
PIN_I2S_BCLK      = 0    # ✓ confirmed GP0
PIN_I2S_LRC       = 1    # ✓ confirmed GP1
PIN_I2S_DIN       = 16   # ✓ confirmed GP16
AUDIO_SAMPLE_RATE = 22050
AUDIO_BITS        = 16
# Was 4096. Confirmed on hardware: machine.I2S(..., ibuf=AUDIO_BUF_BYTES)
# appears to internally double-buffer its DMA ring -- every I2S playback
# allocation fails at exactly 2x this value (8192B at 4096), not the
# configured size itself. I2S is deliberately torn down and rebuilt fresh
# for every single clip (MAX98357A auto-mute behavior, see drivers/audio.py),
# so this allocation happens on EVERY sound, not just once. Halved to 2048
# (this failure's already-documented "next lever" — see HARDWARE_NOTES.md's
# third and eleventh confirmed hardware failures) rather than adding yet
# another permanent boot-time reservation, since several of those already
# stacked up this session and each one shrinks the elastic heap available
# to allocations like this one. No other production consumer of this
# constant besides drivers/audio.py (confirmed via grep — only two test
# scripts also reference it).
AUDIO_BUF_BYTES   = 2048

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

# ── Battery ADC — pending bench confirmation ─────────────────────
# Was planned as a voltage divider into MCP23008 GP5, but the MCP23008
# is a pure digital I/O expander — it has no ADC capability at all, so
# that plan could never have given a real voltage/percentage, only a
# HIGH/LOW flag. Switched to the Pico 2 W's own native VSYS monitor
# instead: GP29/ADC3 reads VSYS (the battery rail) directly, no new
# components needed. GP29 shares its physical pin with the CYW43439
# wireless chip's SPI CLK line, so reading it mid-SPI-transaction would
# give garbage — but this firmware never imports `network`/uses WLAN
# anywhere, so that conflict never actually arises here. GP25 (the
# wireless chip's CS-equivalent line) is still held high before each
# read as cheap insurance, matching the documented technique for this
# board. See tests/test_16_battery_vsys.py and drivers/battery.py.
PIN_BAT_ADC    = 29    # GP29 / ADC3 — VSYS monitor (see note above)
PIN_WIFI_CS    = 25    # held HIGH before each battery read (see note above)
# ✓ BENCH-CONFIRMED — RECALIBRATED after D1 (the reverse-blocking Schottky
# diode added in the battery->VSYS path, to stop USB backfeeding into the
# battery) made VSYS no longer the same node as the battery terminals.
# The original VSYS_ADC_RATIO=2.55 was calibrated with the battery wired
# straight to VSYS, no diode -- once D1 went in, that ratio was still
# internally correct (it converts raw -> the real VSYS voltage), but
# BAT_FULL_V/BAT_EMPTY_V were being compared against VSYS as if VSYS
# still equalled the battery's own terminal voltage, so a fully-charged
# battery could read as empty.
#
# Direct measurement on the as-built board (battery at 4.17V under the
# calibration script's light load): VSYS = 3.80V, diode drop = 0.33V
# (textbook for a 1N5819), remaining ~0.04V from switch/wiring — nothing
# unexpected, no bad connection. VSYS_DROP_V is that whole battery->VSYS
# gap; BAT_FULL_V/BAT_EMPTY_V stay in battery-terminal-voltage units
# (meaning what their names say) and drivers/battery.py subtracts
# VSYS_DROP_V from them before comparing against the VSYS-domain reading.
#
# raw -> VSYS ratio refit against this run's 58 samples (mean raw=25280.2,
# VSYS=3.80V measured directly at the pin): 2.985. See
# tests/battery_calibration_log.py for how to recalibrate further (a
# second point nearer BAT_EMPTY_V would tighten this the same way the
# original 2-point fit wanted a third point).
VSYS_ADC_RATIO = 2.985
VSYS_DROP_V    = 0.37   # battery -> VSYS: D1's forward drop + switch/wiring
BAT_FULL_V     = 4.2    # battery's own terminal voltage, NOT VSYS
BAT_EMPTY_V    = 3.3    # battery's own terminal voltage, NOT VSYS
BAT_WARN_PCT   = 15

# ── Dead / reserved pins ─────────────────────────────────────────
# GP5  — DEAD. Output driver measures -4.2mV when set HIGH. Never use.
# GP23/24 — WiFi internal. Never connect anything.
# GP25/29 — WiFi internal, but DELIBERATELY used for battery monitoring
#           (see Battery ADC section above) — never wired/tested before
#           now, so this note is not itself bench-confirmed either.

# ── UX timing ────────────────────────────────────────────────────
MENU_SCROLL_MS     = 120
GAME_RETURN_IDLE_S = 60
SCREEN_DIM_S       = 120

# ── Countdown text scale ─────────────────────────────────────────
# Was 10 (core/game_base.py's "3-2-1-GO!" countdown). Single source of
# truth shared by core/game_base.py (actual render) and
# core/display_manager.py's warm_text_scratch() (boot-time pre-warm) --
# they used to be two independently hardcoded 10s in different files, an
# easy way to silently desync. Confirmed on hardware: at scale=10, "GO!"'s
# out buffer (dw=240, dh=80 -> 38,400B) was the single biggest text draw
# in the app, and even after seating five other large boot-time
# reservations totaling ~189KB, this one still failed with 150KB nominally
# free (contiguous fragmentation, not a shortage -- see HARDWARE_NOTES.md's
# thirteenth/fourteenth confirmed hardware failures). Dropped to 7
# (out buffer -> 168x56x2 = 18,816B, roughly half) to reduce the single
# largest contiguous ask in the whole boot sequence, rather than continue
# reordering reservations that don't collectively fit regardless of order.
# Still large/dramatic on a 480x320 screen -- just not the biggest
# possible. Raise this again only after confirming real headroom via the
# gc.mem_free() checkpoint prints in core/kernel.py's init().
COUNTDOWN_TEXT_SCALE = 7

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
#  GP23/24 WiFi — NEVER CONNECT
#  GP25  WiFi CS-equiv, held HIGH for battery reads (not bench-confirmed)
#  GP29  VSYS monitor / ADC3 — battery voltage (not bench-confirmed)
#
# MCP23008 (0x20) GPIO:
#  MCP0  SCREEN-0 button         MCP1  SCREEN-1 button
#  MCP2  SCREEN-2 button         MCP3  SCREEN-3 button
#  MCP4  BACK/HOME button        MCP5  spare (battery moved to GP29/ADC3)
#  MCP6  spare                   MCP7  spare
# ══════════════════════════════════════════════════════════════════
