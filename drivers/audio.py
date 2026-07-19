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
# Audio files: 16-bit signed PCM WAV, mono, 22050Hz
# Convert: ffmpeg -i input.mp3 -ar 22050 -ac 1 -acodec pcm_s16le out.wav
#
# CLIP RESOLUTION ORDER (first hit wins):
#   1. /assets/<game_id>/audio/<kind>/   Tier B — installed from SD by
#      game_cache at game load (littlefs; no SPI0 traffic to play)
#   2. /assets/audio/<kind>/             littlefs, deployed shared clips
#   3. /sd/audio/<kind>/                 SD directly, UNMANAGED (see below)
#   4. _SYNTH_MAP tone                   fallback when no file exists
#
# SD reads here do NOT bracket the shared SPI0 bus at the SD-safe clock
# (unlike every other SD consumer — read_file(), game_cache, kernel score
# I/O). That's a deliberate, known trade: bracketing every ~4KB chunk read
# in spi_bus.raw() fixes a theoretical concurrent-access hazard but costs
# a lock acquire + frequency check every ~93ms of audio, and measured on
# hardware that was audible as stutter even after the frequency-cache
# regression it exposed was separately fixed. The accepted hazard (see
# assets.py's SHARED-BUS RULE note) is that no current game draws to a
# display while a background (non-awaited) clip is still streaming from
# SD — every game explicitly sequences draw-then-play or awaits playback
# before its next draw. If a future game needs true background SD audio
# concurrent with SD/display traffic, that game's own audio should live
# in /assets/<game_id>/audio/ (Tier B, no SPI0 contention) rather than
# reintroducing bus-locking here.

import asyncio
import struct
import math
import micropython
import config

_FLASH_AUDIO_ROOT = "/assets/audio"
_SD_AUDIO_ROOT    = "/sd/audio"

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


@micropython.viper
def _scale_volume(buf: ptr8, n_bytes: int, vol_q8: int):
    # In-place volume scale of 16-bit LE samples, vol_q8 = volume * 256.
    # Native code — the per-sample struct.unpack/pack loop this replaces
    # took longer than the audio it processed and starved the I2S buffer.
    i = 0
    while i < n_bytes:
        s = int(buf[i]) | (int(buf[i + 1]) << 8)
        if s & 0x8000:
            s -= 0x10000
        s = (s * vol_q8) >> 8
        buf[i]     = s & 0xFF
        buf[i + 1] = (s >> 8) & 0xFF
        i += 2


# Largest buffer any _SYNTH_MAP entry can ever need (game_over.wav, 400ms
# @ 22050Hz) -- see AudioManager._synth_buf below for why this is
# pre-sized rather than left to grow lazily.
_MAX_SYNTH_MS = max(dur for _, dur, _ in _SYNTH_MAP.values())


class AudioManager:
    """Two-channel non-blocking I2S audio (IRQ-callback) with synth fallback."""

    def __init__(self):
        self._ready      = False
        self._i2s        = None
        self._voice_task = None
        self._sfx_task   = None
        self._volume     = 1.0
        self._drain_evt  = None      # Event the IRQ sets (per-playback owner)
        self._game_root  = None      # /assets/<game_id>/audio while a game runs
        self._read_buf   = None      # lazy WAV read buffer, reused across
                                      # _play_wav() calls (see there — was a
                                      # fresh bytearray(AUDIO_BUF_BYTES) every
                                      # call, a repeating uncached allocation
                                      # that contributed to a confirmed
                                      # on-hardware MemoryError)
        # Synth-tone scratch buffer, pre-sized to the biggest _SYNTH_MAP
        # entry and allocated NOW (AudioManager() is constructed as an
        # import-time side effect, on the freshest heap this app ever
        # sees) instead of lazily inside _synth_tone() -- that used to
        # bytearray() a fresh buffer every call (never cached, unlike
        # _read_buf above), and confirmed on hardware to MemoryError right
        # after Star Bonk's end screen: announce_round_complete() plays
        # "well_done.wav"/"new_high_score.wav" via this synth fallback
        # (neither has a baked audio file), landing exactly when the heap
        # is most fragmented from that screen's tile/result paints.
        self._synth_buf = bytearray(
            int(config.AUDIO_SAMPLE_RATE * _MAX_SYNTH_MS / 1000) * 2)
        self._init_hardware()

    def _synth_tone(self, freq, duration_ms, volume=0.4, sample_rate=22050):
        n    = int(sample_rate * duration_ms / 1000)
        need = n * 2
        if len(self._synth_buf) < need:
            self._synth_buf = bytearray(need)   # play_tone() with a longer
                                                  # duration than any _SYNTH_MAP
                                                  # entry — not pre-warmed, but
                                                  # still cached from here on
        buf = self._synth_buf
        for i in range(n):
            s = int(32767 * volume * math.sin(2 * math.pi * freq * i / sample_rate))
            struct.pack_into('<h', buf, i * 2, s)
        return memoryview(buf)[:need]

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

    def set_game(self, game_id):
        """Point clip resolution at a game's Tier B audio dir (installed to
        littlefs by game_cache). Kernel calls this at game load; pass None
        at unload to fall back to shared clips only."""
        self._game_root = ("/assets/%s/audio" % game_id) if game_id else None

    def _candidates(self, kind, filename):
        paths = []
        if self._game_root:
            paths.append(self._game_root + "/" + kind + "/" + filename)
        paths.append(_FLASH_AUDIO_ROOT + "/" + kind + "/" + filename)
        paths.append(_SD_AUDIO_ROOT + "/" + kind + "/" + filename)
        return paths

    async def play_voice(self, filename: str, wait: bool = False):
        if not self._ready:
            return
        self._cancel(self._voice_task)
        self._voice_task = asyncio.create_task(
            self._guard(self._play_file_or_synth(
                self._candidates("voice", filename), filename)))
        if wait:
            try:
                await self._voice_task
            except asyncio.CancelledError:
                pass

    async def play_sfx(self, filename: str, wait: bool = False):
        if not self._ready:
            return
        self._cancel(self._sfx_task)
        self._sfx_task = asyncio.create_task(
            self._guard(self._play_file_or_synth(
                self._candidates("sfx", filename), filename)))
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

    async def _play_file_or_synth(self, paths, filename: str):
        for path in paths:
            try:
                await self._play_wav(path)
                return
            except asyncio.CancelledError:
                raise
            except OSError:
                continue      # not at this root — try the next
        basename = filename.split("/")[-1]
        if basename in _SYNTH_MAP:
            freq, dur, vol = _SYNTH_MAP[basename]
            await self._play_synth(freq, dur, vol * self._volume)

    async def _play_wav(self, path: str):
        # No spi_bus locking/frequency management here — see the module
        # docstring's CLIP RESOLUTION note for why that trade was reverted.
        f = open(path, 'rb')
        try:
            header = f.read(44)
            if header[:4] != b'RIFF' or header[8:12] != b'WAVE':
                return
            # Reused across calls (grow-if-needed) instead of a fresh
            # bytearray every clip — this port's GC doesn't move/compact,
            # so repeated allocate-and-abandon here fragments the heap.
            if self._read_buf is None or len(self._read_buf) < config.AUDIO_BUF_BYTES:
                self._read_buf = bytearray(config.AUDIO_BUF_BYTES)
            buf = self._read_buf
            mv  = memoryview(buf)
            self._i2s = self._make_i2s()   # one session for the whole clip
            try:
                while True:
                    n = f.readinto(buf)
                    if not n:
                        break
                    if self._volume < 1.0:
                        _scale_volume(mv, n, int(self._volume * 256))
                    await self._stream(mv, n)
            finally:
                self._i2s.deinit()
                self._i2s = None
        finally:
            f.close()

    async def _play_synth(self, freq: int, duration_ms: int, volume: float = 0.4):
        mv = self._synth_tone(freq, duration_ms,
                              volume * self._volume, config.AUDIO_SAMPLE_RATE)
        self._i2s = self._make_i2s()
        try:
            await self._stream(mv, len(mv))
        finally:
            self._i2s.deinit()
            self._i2s = None

audio = AudioManager()
