# drivers/audio.py — Button Blasters v3.0
# MAX98357A I2S audio driver — confirmed GP0/GP1/GP16.
#
# NON-BLOCKING via IRQ-callback I2S (mode=I2S.TX, i2s.irq(cb)). In this
# mode i2s.write() returns immediately and the driver fires the callback
# when the buffer has drained; we await an asyncio.Event set by that
# callback, so the event loop runs freely during playback.
#
# WHY NOT StreamWriter: on this RP2350 / MicroPython v1.28 build,
# StreamWriter.drain() did NOT actually yield — audio still blocked the
# loop and the display tore into stripes. IRQ-callback mode was measured
# (test_i2s_yield.py) to keep the loop at ~92% speed during playback.
#
# Two channels:
#   channel 0 = voice clips  (not interrupted by SFX)
#   channel 1 = sound effects (interruptible)
#
# Synth fallback: if SD unavailable, named SFX become sine tones.
#
# Audio files on SD: 16-bit signed PCM WAV, mono, 22050Hz
# Convert: ffmpeg -i input.mp3 -ar 22050 -ac 1 -acodec pcm_s16le out.wav

import asyncio
import struct
import math
import config


_SYNTH_MAP = {
    "correct.wav":       (659, 150, 0.4),
    "wrong.wav":         (220, 200, 0.4),
    "menu_move.wav":     (880,  60, 0.25),
    "menu_select.wav":   (523, 120, 0.4),
    "game_start.wav":    (784, 200, 0.4),
    "go.wav":            (880, 300, 0.5),
    "count_1.wav":       (440, 100, 0.4),
    "count_2.wav":       (440, 100, 0.4),
    "count_3.wav":       (440, 100, 0.4),
    "ping.wav":          (660,  80, 0.3),
    "startup.wav":       (523, 200, 0.35),
    "level_up.wav":      (784, 300, 0.45),
    "game_over.wav":     (220, 400, 0.4),
    "well_done.wav":     (659, 250, 0.4),
    "new_high_score.wav":(880, 300, 0.5),
}


def _synth_tone(freq, duration_ms, volume=0.4, sample_rate=22050):
    n   = int(sample_rate * duration_ms / 1000)
    buf = bytearray(n * 2)
    for i in range(n):
        s = int(32767 * volume * math.sin(2 * math.pi * freq * i / sample_rate))
        struct.pack_into('<h', buf, i * 2, s)
    return buf


class AudioManager:
    """Two-channel non-blocking I2S audio (IRQ-callback) with synth fallback."""

    def __init__(self):
        self._ready       = False
        self._i2s         = None
        self._voice_task  = None
        self._sfx_task    = None
        self._volume      = 1.0
        # IRQ isolation: the callback sets whichever Event is "current".
        # Each playback installs its own Event before writing a chunk, so
        # a cancelled/superseded playback can't have a stale callback set
        # the wrong Event.
        self._drain_evt   = None
        self._init_hardware()

    def _init_hardware(self):
        if (config.PIN_I2S_BCLK is None or
                config.PIN_I2S_LRC is None or
                config.PIN_I2S_DIN is None):
            print("[audio] I2S pins not configured — audio disabled")
            return
        try:
            from machine import I2S, Pin
            self._i2s = I2S(
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
            # Single IRQ handler for the lifetime of the driver; it sets
            # the Event that the currently-playing coroutine is awaiting.
            self._i2s.irq(self._on_drain)
            self._ready = True
            print(f"[audio] MAX98357A ready  "
                  f"BCLK=GP{config.PIN_I2S_BCLK}  "
                  f"LRC=GP{config.PIN_I2S_LRC}  "
                  f"DIN=GP{config.PIN_I2S_DIN}")
        except Exception as e:
            print(f"[audio] I2S init failed: {e}")

    def _on_drain(self, _arg):
        # IRQ context — keep it trivial: flag the current drain Event.
        evt = self._drain_evt
        if evt is not None:
            evt.set()

    # ── Public API ───────────────────────────────────────────────

    async def play_voice(self, filename: str, wait: bool = False):
        if not self._ready:
            return
        self._cancel(self._voice_task)
        path = "/sd/audio/voice/" + filename
        self._voice_task = asyncio.create_task(
            self._play_file_or_synth(path, filename))
        if wait:
            try:
                await self._voice_task
            except asyncio.CancelledError:
                pass

    async def play_sfx(self, filename: str, wait: bool = False):
        if not self._ready:
            return
        self._cancel(self._sfx_task)
        path = "/sd/audio/sfx/" + filename
        self._sfx_task = asyncio.create_task(
            self._play_file_or_synth(path, filename))
        if wait:
            try:
                await self._sfx_task
            except asyncio.CancelledError:
                pass

    async def play_tone(self, freq: int, duration_ms: int, volume: float = 0.4):
        if not self._ready:
            return
        self._cancel(self._sfx_task)
        self._sfx_task = asyncio.create_task(
            self._play_synth(freq, duration_ms, volume))

    def stop_sfx(self):
        self._cancel(self._sfx_task)
        self._sfx_task = None

    def stop_all(self):
        self._cancel(self._voice_task)
        self._cancel(self._sfx_task)
        self._voice_task = self._sfx_task = None

    def set_volume(self, vol: float):
        self._volume = max(0.0, min(1.0, vol))

    @property
    def voice_playing(self) -> bool:
        return (self._ready and self._voice_task is not None
                and not self._voice_task.done())

    @property
    def sfx_playing(self) -> bool:
        return (self._ready and self._sfx_task is not None
                and not self._sfx_task.done())

    @property
    def ready(self) -> bool:
        return self._ready

    # ── Internal ─────────────────────────────────────────────────

    def _cancel(self, task):
        if task and not task.done():
            task.cancel()

    async def _stream(self, mv, n_bytes):
        """
        Write mv[:n_bytes] to I2S in non-blocking chunks, awaiting the
        drain IRQ between chunks so the event loop stays free.
        Uses a per-call Event installed as self._drain_evt.
        """
        evt = asyncio.Event()
        CHUNK = config.AUDIO_BUF_BYTES
        offset = 0
        try:
            while offset < n_bytes:
                end = min(offset + CHUNK, n_bytes)
                evt.clear()
                self._drain_evt = evt          # this playback owns the IRQ now
                self._i2s.write(mv[offset:end])  # returns immediately (IRQ mode)
                await evt.wait()               # loop free until DMA drains
                offset = end
        finally:
            # Only relinquish the IRQ Event if it's still ours (a newer
            # playback may have already taken it).
            if self._drain_evt is evt:
                self._drain_evt = None

    async def _play_file_or_synth(self, path: str, filename: str):
        try:
            await self._play_wav(path)
        except asyncio.CancelledError:
            return
        except OSError:
            basename = filename.split("/")[-1]
            if basename in _SYNTH_MAP:
                freq, dur, vol = _SYNTH_MAP[basename]
                await self._play_synth(freq, dur, vol * self._volume)

    async def _play_wav(self, path: str):
        with open(path, 'rb') as f:
            header = f.read(44)                     # consume RIFF/WAVE header
            if header[:4] != b'RIFF' or header[8:12] != b'WAVE':
                return
            buf = bytearray(config.AUDIO_BUF_BYTES)
            mv  = memoryview(buf)
            while True:
                n = f.readinto(buf)
                if n == 0:
                    break
                if self._volume < 1.0:
                    for i in range(0, n, 2):
                        s = struct.unpack_from('<h', buf, i)[0]
                        struct.pack_into('<h', buf, i, int(s * self._volume))
                await self._stream(mv, n)

    async def _play_synth(self, freq: int, duration_ms: int, volume: float = 0.4):
        try:
            buf = _synth_tone(freq, duration_ms,
                              volume * self._volume, config.AUDIO_SAMPLE_RATE)
            await self._stream(memoryview(buf), len(buf))
        except asyncio.CancelledError:
            pass


audio = AudioManager()
