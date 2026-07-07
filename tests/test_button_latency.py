# test_button_latency.py — measure button press → recognition latency
#
# Run standalone. It runs the REAL button manager + a simulated "draw
# load" so we can measure how long after a physical press the event is
# actually seen by game-style polling — and how much a concurrent screen
# draw delays it.
#
# Press any screen button (0-3) when prompted. It prints, per press:
#   - latency from the MCP press-edge timestamp to when polling saw it
#   - whether a draw was running at the time
# Ctrl-C to stop.

import asyncio
import time
from drivers.buttons import buttons
from core.display_manager import display, DARK

_draw_running = False


async def _fake_draw_loop():
    # Simulates the per-round draw load: clear main + 4 button screens,
    # repeatedly, so we can see if a press during a draw is delayed.
    global _draw_running
    while True:
        _draw_running = True
        await display.fill_main(DARK)
        for i in range(4):
            await display.fill_btn(i, DARK)
        _draw_running = False
        await asyncio.sleep_ms(400)   # gap between draws to press in


async def _latency_probe():
    print("=" * 52)
    print("BUTTON LATENCY TEST")
    print("Press screen buttons 0-3 repeatedly (during AND between draws)")
    print("=" * 52)
    buttons.clear()
    last_seen = [0, 0, 0, 0, 0]
    while True:
        try:
            btn, evt = buttons._queue.get_nowait()
        except Exception:
            await asyncio.sleep_ms(5)
            continue
        if evt != "press" or btn > 3:
            continue
        now = time.ticks_ms()
        edge = buttons._pressed_at[btn]
        latency = time.ticks_diff(now, edge)
        during = "DURING draw" if _draw_running else "between draws"
        print(f"  btn {btn}: latency {latency:4d} ms   ({during})")


async def main():
    display.init_all()
    buttons.init_queue()
    # Buttons need I2C (shared with touch). Init touch to get the bus.
    from drivers.touch import touch
    i2c = touch.init_blocking()
    buttons.init_mcp(i2c)
    asyncio.create_task(buttons.run())
    asyncio.create_task(_fake_draw_loop())
    await _latency_probe()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\nstopped.")
