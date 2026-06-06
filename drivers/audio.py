# drivers/audio.py
# Async audio driver — I2S output via MAX98357A.
#
# Supports two simultaneous channels via software mixing:
#   channel 0 = voice clips  (higher priority, not interrupted)
#   channel 1 = sound effects (interruptible)
#
# Audio files live on the SD card under /sd/audio/.
# Supported format: 16-bit signed PCM WAV, mono, 22050 Hz.
# (Convert with: ffmpeg -i input.mp3 -ar 22050 -ac 1 -acodec pcm_s16le out.wav)

import asyncio
import struct
import os
from machine import I2S, Pin
import config


_WAV_HEADER = 44    # standard WAV header size


def _parse_wav_header(f):
    """Return (sample_rate, channels, bits, data_offset) from an open WAV file."""
    f.seek(0)
    header = f.read(44)
    if header[:4] != b'RIFF' or header[8:12] != b'WAVE':
        raise ValueError("Not a WAV file")
    channels    = struct.unpack_from('<H', header, 22)[0]
    sample_rate = struct.unpack_from('<I', header, 24)[0]
    bits        = struct.unpack_from('<H', header, 34)[0]
    return sample_rate, channels, bits, 44


class AudioManager:
    """
    Simple two-channel async audio mixer over I2S.

    Usage:
        await audio.play_voice("correct.wav")
        await audio.play_sfx("ding.wav")
        await audio.play_voice("levelup.wav", wait=True)  # await completion
    """

    def __init__(self):
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
        self._voice_task = None
        self._sfx_task   = None
        self._volume     = 1.0    # 0.0–1.0

    # ── Public API ───────────────────────────────────────────────

    async def play_voice(self, filename: str, wait: bool = False):
        """Play a voice clip (channel 0).  Cancels any current voice."""
        self._cancel(self._voice_task)
        path = "/sd/audio/" + filename
        self._voice_task = asyncio.create_task(self._play(path, priority=0))
        if wait:
            await self._voice_task

    async def play_sfx(self, filename: str, wait: bool = False):
        """Play a sound effect (channel 1).  Cancels any current SFX."""
        self._cancel(self._sfx_task)
        path = "/sd/audio/" + filename
        self._sfx_task = asyncio.create_task(self._play(path, priority=1))
        if wait:
            await self._sfx_task

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
        return self._voice_task is not None and not self._voice_task.done()

    @property
    def sfx_playing(self) -> bool:
        return self._sfx_task is not None and not self._sfx_task.done()

    # ── Internal ─────────────────────────────────────────────────

    def _cancel(self, task):
        if task and not task.done():
            task.cancel()

    async def _play(self, path: str, priority: int):
        try:
            with open(path, 'rb') as f:
                _, _, bits, offset = _parse_wav_header(f)
                f.seek(offset)
                buf = bytearray(config.AUDIO_BUF_BYTES)
                mv  = memoryview(buf)
                while True:
                    n = f.readinto(buf)
                    if n == 0:
                        break
                    # Apply software volume scaling
                    if self._volume < 1.0:
                        for i in range(0, n, 2):
                            sample = struct.unpack_from('<h', buf, i)[0]
                            sample = int(sample * self._volume)
                            struct.pack_into('<h', buf, i, sample)
                    self._i2s.write(mv[:n])
                    await asyncio.sleep_ms(0)   # yield to other tasks
        except asyncio.CancelledError:
            pass
        except OSError:
            pass   # file not found — silent fail


audio = AudioManager()
