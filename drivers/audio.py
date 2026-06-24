# drivers/audio.py — Button Blasters
# Async audio driver — I2S output via MAX98357A.
#
# ⚠ NOT YET WIRED — PIN_I2S_BCLK/LRC/DIN are None in config.
#    All public methods are safe to call — they no-op silently
#    until the hardware is connected and pins assigned.
#
# When wired: set PIN_I2S_BCLK, PIN_I2S_LRC, PIN_I2S_DIN in config.py
# and the driver will automatically activate on next boot.
#
# Audio files: 16-bit signed PCM WAV, mono, 22050Hz on SD card.
# Convert: ffmpeg -i input.mp3 -ar 22050 -ac 1 -acodec pcm_s16le out.wav

import asyncio
import struct
import config


class AudioManager:
    """
    Two-channel async audio mixer over I2S.
    Safe to import and call when hardware is not yet wired.

    channel 0 = voice clips  (not interrupted by SFX)
    channel 1 = sound effects (interruptible)
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
            print("[audio] I2S ready")
        except Exception as e:
            print(f"[audio] I2S init failed: {e}")

    # ── Public API ───────────────────────────────────────────────

    async def play_voice(self, filename: str, wait: bool = False):
        """Play a voice clip. No-op if hardware not ready."""
        if not self._ready:
            return
        self._cancel(self._voice_task)
        path = "/sd/audio/voice/" + filename
        self._voice_task = asyncio.create_task(self._play(path))
        if wait:
            await self._voice_task

    async def play_sfx(self, filename: str, wait: bool = False):
        """Play a sound effect. No-op if hardware not ready."""
        if not self._ready:
            return
        self._cancel(self._sfx_task)
        path = "/sd/audio/sfx/" + filename
        self._sfx_task = asyncio.create_task(self._play(path))
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
        return (self._ready and
                self._voice_task is not None and
                not self._voice_task.done())

    @property
    def sfx_playing(self) -> bool:
        return (self._ready and
                self._sfx_task is not None and
                not self._sfx_task.done())

    @property
    def ready(self) -> bool:
        return self._ready

    # ── Internal ─────────────────────────────────────────────────

    def _cancel(self, task):
        if task and not task.done():
            task.cancel()

    async def _play(self, path: str):
        try:
            with open(path, 'rb') as f:
                # Parse WAV header
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
        except asyncio.CancelledError:
            pass
        except OSError:
            pass   # file not found — silent fail


audio = AudioManager()
