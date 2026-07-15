# drivers/audio.py — Button Blasters v3.0
# MAX98357A I2S audio driver — confirmed GP0/GP1/GP16.
#
# NON-BLOCKING via IRQ-callback I2S (mode=I2S.TX, i2s.irq(cb)). write()
# returns immediately; the callback fires on drain and sets an
# asyncio.Event the playback loop awaits, so the event loop runs freely
# during playback. (StreamWriter/drain() does NOT yield on this
# RP2350/v1.28 build — measured — so IRQ-callback is required.)
#
# IMPORTANT: playback runs as fire-and-forget tasks. Their bodies are
# wrapped in _guard() so an exception inside a task is caught rather than
# silently swallowed by the scheduler — an earlier version lost ALL audio
# because a task exception vanished with no traceback and no sound.
#
# Audio files on SD: 16-bit signed PCM WAV, mono, 22050Hz
# Convert: ffmpeg -i input.mp3 -ar 22050 -ac 1 -acodec pcm_s16le out.wav

import asyncio
import struct
import math
import config

_SD_DATA_BAUD = 400_000   # keep in sync with drivers/assets.py / game_cache.py

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
        self._ready      = False
        self._i2s        = None
        self._voice_task = None
        self._sfx_task   = None
        self._volume     = 1.0
        self._drain_evt  = None      # Event the IRQ sets (per-playback owner)
        self._init_hardware()

    def _init_hardware(self):
        if (config.PIN_I2S_BCLK is None or
                config.PIN_I2S_LRC is None or
                config.PIN_I2S_DIN is None):
            print("[audio] I2S pins not configured — audio disabled")
            return
        try:
            # Confirm the peripheral can init, then release it immediately.
            # MAX98357A auto-mutes with no valid clock present -- leaving I2S
            # live for the whole runtime defeats that protection and lets any
            # rail/DIN noise through at all times, not just during playback
            # (confirmed: unplugging BCLK silenced file-transfer noise). From
            # here on, I2S exists only for the duration of an actual _stream().
            i2s = self._make_i2s()
            i2s.deinit()
            self._ready = True
            print(f"[audio] MAX98357A ready  "
                f"BCLK=GP{config.PIN_I2S_BCLK}  "
                f"LRC=GP{config.PIN_I2S_LRC}  "
                f"DIN=GP{config.PIN_I2S_DIN}")
        except Exception as e:
            print(f"[audio] I2S init failed: {e}")

    def _make_i2s(self):
        from machine import I2S, Pin
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
        i2s.irq(self._on_drain)
        return i2s

    def _on_drain(self, _arg):
        # IRQ context — keep trivial: flag the current drain Event.
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
            self._guard(self._play_file_or_synth(path, filename)))
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
            self._guard(self._play_file_or_synth(path, filename)))
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
            self._guard(self._play_synth(freq, duration_ms, volume)))

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

    async def _guard(self, coro):
        # Fire-and-forget tasks swallow exceptions silently (no traceback,
        # no sound). Catch them here so one bad clip can't kill all audio.
        try:
            await coro
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[audio] playback error: {repr(e)}")

    async def _stream(self, mv, n_bytes):
        evt = asyncio.Event()
        CHUNK = config.AUDIO_BUF_BYTES
        offset = 0
        try:
            while offset < n_bytes:
                end = min(offset + CHUNK, n_bytes)
                evt.clear()
                self._drain_evt = evt
                self._i2s.write(mv[offset:end])
                await evt.wait()
                offset = end
        finally:
            if self._drain_evt is evt:
                self._drain_evt = None

    async def _play_file_or_synth(self, path: str, filename: str):
        try:
            await self._play_wav(path)
        except asyncio.CancelledError:
            raise
        except OSError:
            basename = filename.split("/")[-1]
            if basename in _SYNTH_MAP:
                freq, dur, vol = _SYNTH_MAP[basename]
                await self._play_synth(freq, dur, vol * self._volume)

    async def _play_wav(self, path: str):
        f = open(path, 'rb')
        header = f.read(44)
        if header[:4] != b'RIFF' or header[8:12] != b'WAVE':
            f.close()
            return
        buf = bytearray(config.AUDIO_BUF_BYTES)
        mv  = memoryview(buf)
        self._i2s = self._make_i2s()   # one session for the whole clip
        try:
            while True:
                n = f.readinto(buf)
                if n == 0:
                    break
                if self._volume < 1.0:
                    for i in range(0, n, 2):
                        s = struct.unpack_from('<h', buf, i)[0]
                        struct.pack_into('<h', buf, i, int(s * self._volume))
                await self._stream(mv, n)
        finally:
            f.close()
            self._i2s.deinit()
            self._i2s = None

    async def _play_synth(self, freq: int, duration_ms: int, volume: float = 0.4):
        buf = _synth_tone(freq, duration_ms,
                        volume * self._volume, config.AUDIO_SAMPLE_RATE)
        self._i2s = self._make_i2s()
        try:
            await self._stream(memoryview(buf), len(buf))
        finally:
            self._i2s.deinit()
            self._i2s = None

audio = AudioManager()
