# test_i2s_yield.py — Button Blasters audio yield diagnostic
#
# Proves whether IRQ-callback I2S actually yields to the asyncio event
# loop during playback (the property StreamWriter FAILED to provide on
# this build — audio blocked and the display tore).
#
# HOW IT WORKS:
#   - A "display heartbeat" coroutine bumps a counter every ~1ms.
#   - We play ~1s of audio via IRQ-callback non-blocking I2S.
#   - If audio YIELDS, the counter climbs by hundreds during playback.
#   - If audio BLOCKS, the counter barely moves (frozen for ~1s).
#
# Run standalone. No display needed — pure timing measurement.

import asyncio
import time
import math
import struct
from machine import I2S, Pin
import config

# ── Shared state ─────────────────────────────────────────────────
_tick = 0
_done = asyncio.Event()


def _make_tone(freq, ms, rate, vol=0.3):
    n = int(rate * ms / 1000)
    buf = bytearray(n * 2)
    for i in range(n):
        s = int(32767 * vol * math.sin(2 * math.pi * freq * i / rate))
        struct.pack_into('<h', buf, i * 2, s)
    return buf


async def _heartbeat():
    # Stand-in for display work: bump a counter as fast as the loop allows.
    global _tick
    while not _done.is_set():
        _tick += 1
        await asyncio.sleep_ms(1)


async def _play_irq(i2s, data):
    # IRQ-callback non-blocking playback. i2s.write() returns immediately;
    # the IRQ fires when the buffer drains, setting an asyncio Event we
    # await — so the loop is free the whole time.
    evt = asyncio.Event()

    def _cb(arg):
        # IRQ context: just flag the event (scheduled via set()).
        evt.set()

    i2s.irq(_cb)

    mv = memoryview(data)
    CHUNK = config.AUDIO_BUF_BYTES
    offset = 0
    while offset < len(mv):
        end = min(offset + CHUNK, len(mv))
        evt.clear()
        n = i2s.write(mv[offset:end])   # returns immediately in IRQ mode
        # Wait for this chunk to finish draining (loop stays free).
        await evt.wait()
        offset = end


async def main():
    global _tick
    print("=" * 50)
    print("I2S YIELD TEST — IRQ-callback mode")
    print("rate:", config.AUDIO_SAMPLE_RATE, " bits:", config.AUDIO_BITS)
    print("=" * 50)

    i2s = I2S(
        0,
        sck=Pin(config.PIN_I2S_BCLK),
        ws=Pin(config.PIN_I2S_LRC),
        sd=Pin(config.PIN_I2S_DIN),
        mode=I2S.TX,
        bits=config.AUDIO_BITS,
        format=I2S.MONO,
        rate=config.AUDIO_SAMPLE_RATE,
        ibuf=config.AUDIO_BUF_BYTES,
    )

    tone = _make_tone(523, 1000, config.AUDIO_SAMPLE_RATE)  # ~1s of C5
    print("tone bytes:", len(tone), " (~1s playback)")

    # Baseline: how many ticks in 1s with NO audio?
    _tick = 0
    hb = asyncio.create_task(_heartbeat())
    await asyncio.sleep_ms(1000)
    baseline = _tick
    print(f"\nBaseline ticks in 1s (no audio): {baseline}")

    # Now play ~1s of audio and count ticks DURING it.
    _tick = 0
    t0 = time.ticks_ms()
    await _play_irq(i2s, tone)
    elapsed = time.ticks_diff(time.ticks_ms(), t0)
    during = _tick

    _done.set()
    await asyncio.sleep_ms(10)

    print(f"Playback wall time: {elapsed} ms")
    print(f"Ticks DURING playback: {during}")
    print("=" * 50)

    # Verdict: if audio yields, ticks-during should be a large fraction
    # of baseline (loop kept running). If it blocked, ticks ~0.
    if during > baseline * 0.5:
        print("=> PASS: IRQ mode YIELDS. Loop ran freely during audio.")
        print("   Safe to rewrite audio.py around this pattern.")
    elif during > baseline * 0.1:
        print("=> PARTIAL: some yielding but choppy. Report numbers to Claude.")
    else:
        print("=> FAIL: audio BLOCKED the loop (ticks ~frozen).")
        print("   IRQ mode isn't yielding either — report to Claude.")

    i2s.deinit()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("stopped.")
