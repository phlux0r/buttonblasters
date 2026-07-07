# test_audio_trace.py — trace the IRQ handshake in the audio.py _stream path
#
# Reproduces audio.py's structure (init-time irq registration + shared
# _drain_evt) with step-by-step prints, then compares against the
# per-playback registration that WORKED in test_i2s_yield.py.
#
# Run standalone. Watch which variant prints "callback fired" and plays.

import asyncio
import time
import math
import struct
from machine import I2S, Pin
import config


def _tone(freq, ms, rate, vol=0.3):
    n = int(rate * ms / 1000)
    buf = bytearray(n * 2)
    for i in range(n):
        s = int(32767 * vol * math.sin(2 * math.pi * freq * i / rate))
        struct.pack_into('<h', buf, i * 2, s)
    return buf


def _make_i2s():
    return I2S(0,
               sck=Pin(config.PIN_I2S_BCLK),
               ws=Pin(config.PIN_I2S_LRC),
               sd=Pin(config.PIN_I2S_DIN),
               mode=I2S.TX, bits=config.AUDIO_BITS,
               format=I2S.MONO, rate=config.AUDIO_SAMPLE_RATE,
               ibuf=config.AUDIO_BUF_BYTES)


# ── Variant A: audio.py's approach (init-time irq + shared event) ──
class SharedEvtAudio:
    def __init__(self, i2s):
        self._i2s = i2s
        self._drain_evt = None
        self._cb_count = 0
        self._i2s.irq(self._on_drain)   # registered ONCE

    def _on_drain(self, _):
        self._cb_count += 1
        evt = self._drain_evt
        if evt is not None:
            evt.set()

    async def play(self, data):
        mv = memoryview(data)
        CHUNK = config.AUDIO_BUF_BYTES
        offset = 0
        chunk_i = 0
        while offset < len(mv):
            end = min(offset + CHUNK, len(mv))
            evt = asyncio.Event()
            evt.clear()
            self._drain_evt = evt
            print(f"  [A] chunk {chunk_i}: write {end-offset}B ...", end="")
            self._i2s.write(mv[offset:end])
            print(" written, awaiting drain ...", end="")
            try:
                await asyncio.wait_for_ms(evt.wait(), 3000)
                print(f" DRAINED (cb_count={self._cb_count})")
            except asyncio.TimeoutError:
                print(f" !! TIMEOUT waiting for callback (cb_count={self._cb_count})")
                return False
            offset = end
            chunk_i += 1
        return True


# ── Variant B: test_i2s_yield.py's approach (per-playback irq) ──────
class PerPlayAudio:
    def __init__(self, i2s):
        self._i2s = i2s

    async def play(self, data):
        evt = asyncio.Event()
        cb_count = [0]
        def _cb(_):
            cb_count[0] += 1
            evt.set()
        self._i2s.irq(_cb)              # registered PER PLAYBACK
        mv = memoryview(data)
        CHUNK = config.AUDIO_BUF_BYTES
        offset = 0
        chunk_i = 0
        while offset < len(mv):
            end = min(offset + CHUNK, len(mv))
            evt.clear()
            print(f"  [B] chunk {chunk_i}: write {end-offset}B ...", end="")
            self._i2s.write(mv[offset:end])
            print(" written, awaiting drain ...", end="")
            try:
                await asyncio.wait_for_ms(evt.wait(), 3000)
                print(f" DRAINED (cb_count={cb_count[0]})")
            except asyncio.TimeoutError:
                print(f" !! TIMEOUT (cb_count={cb_count[0]})")
                return False
            offset = end
            chunk_i += 1
        return True


async def main():
    print("=" * 52)
    print("AUDIO IRQ HANDSHAKE TRACE")
    print("=" * 52)
    tone = _tone(523, 400, config.AUDIO_SAMPLE_RATE)
    print(f"tone: {len(tone)} bytes, chunk size {config.AUDIO_BUF_BYTES}\n")

    print("VARIANT A — audio.py style (init-time irq + shared event):")
    i2s = _make_i2s()
    a = SharedEvtAudio(i2s)
    ok_a = await a.play(tone)
    i2s.deinit()
    print(f"  Variant A result: {'PLAYED' if ok_a else 'STALLED'}\n")

    await asyncio.sleep_ms(300)

    print("VARIANT B — test_i2s_yield.py style (per-playback irq):")
    i2s = _make_i2s()
    b = PerPlayAudio(i2s)
    ok_b = await b.play(tone)
    i2s.deinit()
    print(f"  Variant B result: {'PLAYED' if ok_b else 'STALLED'}\n")

    print("=" * 52)
    print("VERDICT:")
    if ok_b and not ok_a:
        print("  Shared-event init-time irq (audio.py) STALLS;")
        print("  per-playback irq (test) WORKS. Fix = register irq")
        print("  per-playback in audio.py. (You should have heard B only.)")
    elif ok_a and ok_b:
        print("  Both worked here — the no-audio bug is elsewhere in")
        print("  audio.py (e.g. task cancel, or play_* not being awaited).")
    elif not ok_a and not ok_b:
        print("  Both stalled — deeper issue; report full output.")
    print("=" * 52)


try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("stopped.")
