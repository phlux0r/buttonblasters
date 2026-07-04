# drivers/audio.py — Button Blasters v3.0
# MAX98357A I2S audio driver — confirmed GP0/GP1/GP16.
#
# Two channels:
#   channel 0 = voice clips  (not interrupted by SFX)
#   channel 1 = sound effects (interruptible)
#
# Synth fallback: if SD card unavailable, named sound effects
# are generated as simple sine-wave tones so the game always
# has audio feedback even without asset files.
#
# Audio files on SD: 16-bit signed PCM WAV, mono, 22050Hz
# Convert: ffmpeg -i input.mp3 -ar 22050 -ac 1 -acodec pcm_s16le out.wav

import asyncio
import struct
import math
import config


# ── Synth fallback tone map ───────────────────────────────────────
# Maps sound effect filenames to (frequency_hz, duration_ms, volume)
_SYNTH_MAP = {
    "correct.wav":      (659, 150, 0.4),
    "wrong.wav":        (220, 200, 0.4),
    "menu_move.wav":    (880,  60, 0.25),
    "menu_select.wav":  (523, 120, 0.4),
    "game_start.wav":   (784, 200, 0.4),
    "go.wav":           (880, 300, 0.5),
    "count_1.wav":      (440, 100, 0.4),
    "count_2.wav":      (440, 100, 0.4),
    "count_3.wav":      (440, 100, 0.4),
    "ping.wav":         (660,  80, 0.3),
    "startup.wav":      (523, 200, 0.35),
    "level_up.wav":     (784, 300, 0.45),
    "game_over.wav":    (220, 400, 0.4),
    "well_done.wav":    (659, 250, 0.4),
    "new_high_score.wav":(880, 300, 0.5),
}


def _synth_tone(freq, duration_ms, volume=0.4, sample_rate=22050):
    """Generate a sine wave tone as bytes."""
    n   = int(sample_rate * duration_ms / 1000)
    buf = bytearray(n * 2)
    for i in range(n):
        s = int(32767 * volume * math.sin(2 * math.pi * freq * i / sample_rate))
        struct.pack_into('<h', buf, i * 2, s)
    return buf


class AudioManager:
    """
    Two-channel async I2S audio with synth fallback.
    Confirmed working: BCLK=GP0, LRC=GP1, DIN=GP16.
    """

    def __init__(self):
        self._ready      = False
        self._i2s        = None
        self._voice_task = None
        self._sfx_task   = None
        self._volume     = 1.0
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
            self._ready = True
            print(f"[audio] MAX98357A ready  "
                  f"BCLK=GP{config.PIN_I2S_BCLK}  "
                  f"LRC=GP{config.PIN_I2S_LRC}  "
                  f"DIN=GP{config.PIN_I2S_DIN}")
        except Exception as e:
            print(f"[audio] I2S init failed: {e}")

    # ── Public API ───────────────────────────────────────────────

    async def play_voice(self, filename: str, wait: bool = False):
        """Play a voice clip (channel 0)."""
        if not self._ready:
            return
        self._cancel(self._voice_task)
        path = "/sd/audio/voice/" + filename
        self._voice_task = asyncio.create_task(
            self._play_file_or_synth(path, filename, is_sfx=False))
        if wait:
            await self._voice_task

    async def play_sfx(self, filename: str, wait: bool = False):
        """Play a sound effect (channel 1)."""
        if not self._ready:
            return
        self._cancel(self._sfx_task)
        path = "/sd/audio/sfx/" + filename
        self._sfx_task = asyncio.create_task(
            self._play_file_or_synth(path, filename, is_sfx=True))
        if wait:
            await self._sfx_task

    async def play_tone(self, freq: int, duration_ms: int,
                        volume: float = 0.4):
        """Play a synthesised tone directly — no SD needed."""
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

    async def _play_file_or_synth(self, path: str,
                                   filename: str, is_sfx: bool):
        """Try to play WAV file, fall back to synth tone."""
        try:
            await self._play_wav(path)
        except (OSError, asyncio.CancelledError) as e:
            if isinstance(e, asyncio.CancelledError):
                return
            # File not found — try synth fallback
            basename = filename.split("/")[-1]
            if basename in _SYNTH_MAP:
                freq, dur, vol = _SYNTH_MAP[basename]
                await self._play_synth(freq, dur, vol * self._volume)

    async def _play_wav(self, path: str):
        with open(path, 'rb') as f:
            header = f.read(44)
            if header[:4] != b'RIFF' or header[8:12] != b'WAVE':
                return
            f.seek(44)
            buf = bytearray(config.AUDIO_BUF_BYTES)
            mv  = memoryview(buf)
            while True:
                n = f.readinto(buf)
                if n == 0:
                    break
                if self._volume < 1.0:
                    for i in range(0, n, 2):
                        s = struct.unpack_from('<h', buf, i)[0]
                        struct.pack_into('<h', buf, i,
                                        int(s * self._volume))
                self._i2s.write(mv[:n])
                await asyncio.sleep_ms(0)

    async def _play_synth(self, freq: int, duration_ms: int,
                          volume: float = 0.4):
        try:
            buf = _synth_tone(freq, duration_ms,
                              volume * self._volume,
                              config.AUDIO_SAMPLE_RATE)
            self._i2s.write(memoryview(buf))
            await asyncio.sleep_ms(0)
        except asyncio.CancelledError:
            pass


audio = AudioManager()
