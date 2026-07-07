# test_touch_crosshair.py — Button Blasters touch rotation diagnostic
#
# Run standalone. Tap the screen (especially the 4 CORNERS and CENTER).
# For each tap it prints the transformed (x, y) and draws a crosshair on
# the main display where it thinks you tapped.
#
# HOW TO READ THE RESULT (landscape 480x320, origin top-left):
#   Tap TOP-LEFT corner    -> expect x~0,   y~0
#   Tap TOP-RIGHT corner   -> expect x~479, y~0
#   Tap BOTTOM-LEFT        -> expect x~0,   y~319
#   Tap BOTTOM-RIGHT       -> expect x~479, y~319
#
# If X is inverted (tap left reads high x): toggle TOUCH_FLIP_X.
# If Y is inverted (tap top reads high y):  toggle TOUCH_FLIP_Y.
# If X and Y are SWAPPED (tap right moves the crosshair down): the
#   SWAP_XY setting is wrong for this rotation.
# Change ONE flag at a time in config.py, reflash this test, retry.

import asyncio
import config
from core.display_manager import display, rgb, WHITE, BLACK
from drivers.touch import touch
from drivers.buttons import buttons


def _print_header():
    print("=" * 48)
    print("TOUCH CROSSHAIR TEST — landscape", config.MAIN_W, "x", config.MAIN_H)
    print("Current config:")
    print("  TOUCH_W =", config.TOUCH_W, " TOUCH_H =", config.TOUCH_H)
    print("  TOUCH_SWAP_XY =", config.TOUCH_SWAP_XY)
    print("  TOUCH_FLIP_X  =", config.TOUCH_FLIP_X)
    print("  TOUCH_FLIP_Y  =", config.TOUCH_FLIP_Y)
    print("Tap the 4 corners + center. Ctrl-C to stop.")
    print("=" * 48)


async def _draw_crosshair(x, y):
    # Clamp so the crosshair stays fully on-screen
    x = max(10, min(config.MAIN_W - 10, x))
    y = max(10, min(config.MAIN_H - 10, y))
    # Horizontal + vertical white bars through (x, y) on a dark field
    await display.fill_main(rgb(10, 10, 30))
    await display.main.fill(WHITE, 0, y, config.MAIN_W, 2)      # horizontal line
    await display.main.fill(WHITE, x, 0, 2, config.MAIN_H)      # vertical line
    # A small box at the exact point
    await display.main.fill(rgb(255, 80, 0), x - 6, y - 6, 12, 12)
    # Print coordinates as text near top-left
    await display.text_main(f"x={x} y={y}", 8, 8, WHITE, rgb(10, 10, 30), scale=2)


async def main():
    display.init_all()
    await display.fill_main(rgb(10, 10, 30))
    await display.text_main("TAP CORNERS", 8, 8, WHITE, rgb(10, 10, 30), scale=2)

    # Touch needs I2C + its polling task
    touch.init_blocking()
    buttons.init_queue()
    buttons.attach_touch(touch)
    asyncio.create_task(buttons.run_touch())

    _print_header()

    while True:
        # buttons.get_tap() returns the (x, y) tuple directly (it blocks
        # until a TOUCH_TAP arrives and returns touch.pos).
        x, y = await buttons.get_tap()
        print(f"TAP  x={x:4d}  y={y:4d}")
        await _draw_crosshair(x, y)


try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\nstopped.")
