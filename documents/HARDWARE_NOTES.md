# Hardware Notes — Confirmed Facts & Bring-Up Gotchas

This document is the ground truth for Button Blasters hardware: confirmed pin assignments, driver-level facts learned the hard way during bring-up, and firmware gotchas that aren't obvious from the datasheets or MicroPython docs. `config.py` and the drivers in `drivers/`/`core/` already implement everything below — treat this as the "why" behind those files, and the reference to check before changing pin assignments or display/touch init code.

All facts here are bench-confirmed, not assumptions. Where two "obvious" configurations exist and only one worked, that's called out explicitly.

---

## Development Environment

| Item | Value |
|---|---|
| MCU | Raspberry Pi Pico 2 W (RP2350, 4 MB flash) |
| MicroPython | v1.28.0, RPI_PICO2_W firmware |
| Dev OS | macOS Big Sur 11.7.11 |
| IDE | VS Code + MicroPico extension v4.3.4 |
| VS Code version | v1.90 or v1.106 only — **v1.91 crashes on Big Sur** |

---

## Display Orientation — Landscape (confirmed)

The console is mounted in landscape. Both display and touch are configured for it; these values are confirmed working on the bench.

- Main display: `MAIN_W = 480`, `MAIN_H = 320`
- ILI9488 rotation: `ILI9488_MADCTL = 0x28` (landscape). The 180° variant is `0xE8`. Portrait was `0x48`.
- Touch (must match the rotated display — confirmed via crosshair test, `tests/test_touch_crosshair.py`):
  - `TOUCH_W = 480`, `TOUCH_H = 320`
  - `TOUCH_SWAP_XY = True`
  - `TOUCH_FLIP_X = False`
  - `TOUCH_FLIP_Y = True`

**Display↔touch handedness is not predictable from the datasheet** on these cheap panels — after any rotation change, reconfirm the touch flip flags on the bench with a crosshair test (tap all 4 corners). The flags above are *not* the "obvious" pairing for `MADCTL 0x28`.

Transform order in the touch driver: `SWAP_XY` first, *then* flips against `TOUCH_W`/`TOUCH_H` — so `TOUCH_W`/`TOUCH_H` must hold the landscape (already-swapped) dimensions.

---

## ILI9488 Main Display

- IPS panel — requires specific init sequence, not a standard TN init.
- **Two different CS framing rules, easy to conflate:**
  - Command/parameter bytes (init sequence, window-setting) use **per-byte CS framing** — CS goes low then high around each individual byte. Skipping this fails init.
  - Pixel data streams under **one continuous CS-low**. The RAMWR command (`0x2C`) and every pixel byte that follows are a single transaction: CS goes low at `0x2C`, stays low through every pixel, and rises once at the end. Raising CS after the `0x2C` command byte makes the panel ignore the entire pixel stream (blank/white screen). This was the v3.0 blank-screen bug — `_set_window` had ended RAMWR via the per-byte helper, raising CS before pixels were sent.
- Pixel format: 18-bit RGB666 (`0x66`), not 16-bit.
- `VCOM = 0x4D` — supplier-confirmed as critical; wrong value produces no image.
- Command `0x21` (display inversion ON) is required for IPS panels — omitting it gives a blank screen.
- Sleep-out (`0x11`) must come first, with a 120 ms delay before any other command.
- Backlight is wired directly to 3.3V — no GPIO needed.
- Fill speed: ~552 ms per full frame at 10 MHz SPI (18-bit/pixel). Consistent with streamed pixel data — per-byte CS toggling on pixels would take seconds, which is itself a signal that pixels must stream under one CS-low.
- SPI frequency: 10 MHz confirmed stable.

Minimal working init sequence:

```python
write_cmd(0x11); time.sleep_ms(120)          # sleep out
write_cmd(0x3A); write_data(0x66)            # 18-bit RGB666
write_cmd(0xC5)                               # VCOM
write_data(0x00); write_data(0x4D); write_data(0x80)
write_cmd(0x21)                               # inversion ON (IPS)
write_cmd(0x36); write_data(ILI9488_MADCTL)  # 0x28 landscape BGR
write_cmd(0x29)                               # display ON
```

RAMWR → pixel streaming (the pattern that must hold):

```python
# inside a CS-LOW transaction:
wc(0x2A); wd(...)        # column window  (per-byte CS ok here)
wc(0x2B); wd(...)        # row window
# RAMWR: CS stays LOW from here through all pixels
dc=0; cs=0; write(0x2C); dc=1   # do NOT raise CS
write(pixel_stream...)          # CS still LOW
cs=1                            # raised once, at the very end
```

---

## ST7789 Button Displays

- `BLK` (backlight) must be driven **HIGH from GPIO** (GP13) — tying it to 3.3V does not work on this module.
- Requires the full LovyanGFX-derived power-up init; a minimal 6-command init does not activate the frame buffer.
- Native working window is **240×300** (portrait), not the datasheet's 240×280 — 300 rows fills the full physical screen. **Landscape (current, for the 2×2 shell layout): 300×240** — bench-confirmed clean (no dead/garbage strip, same total pixel budget as portrait just rotated) via `tests/test_15_button_landscape.py`. RGB colour order was already correct at MADCTL bit3=0 in portrait — the landscape values keep that bit, don't add BGR when experimenting further. **MADCTL is per-button, not a single value** — see the dedicated subsection below (2×2 mounting rotates BTN-2/3 180° from BTN-0/1).
- GP5 is dead on this board, so DC for BTN-0 uses GP2 instead of the "expected" pin.
- SPI at 10 MHz confirmed stable. No MISO connection needed — displays are write-only.
- Same RAMWR/CS rule as the ILI9488: CS stays low from the `0x2C` command through all pixel data, rising once at the end. ST7789 doesn't need per-byte CS framing on command bytes, but the RAMWR→pixel transition must hold CS low or fills produce noise.
- Fill speed: ~177 ms per full frame in portrait (RGB565 native — faster than the main display's RGB666); not yet re-measured in landscape (same pixel count, should be ~equal).
- **Switching orientation invalidates every full-screen button asset baked at the old dimensions** — the 96×96 icon sprites (Match's `sprb_*`, Bonk's `spr_*`/`sprb_*`) are unaffected since they're centered by a formula that recomputes from `config.BTN_W`/`BTN_H`, but anything baked at the whole button canvas (menu tiles, prev/next/back tiles) needs re-baking at 300×240 and its filename updated accordingly (`_240x300.bz` → `_300x240.bz`).

### Physical mounting: 2×2 matrix, button roles remapped

The shell mounts the four button screens as a 2×2 matrix, not a linear row:

```
0 | 2
1 | 3
```

Left column {0,1} = "previous", right column {2,3} = "next". Button roles (was a linear-row assumption of BTN-0=PREV, BTN-1/2=preview, BTN-3=NEXT):

| Position | Old role (linear) | New role (2×2) |
|---|---|---|
| BTN-0 (top-left) | PREV ← nav | game preview (idx-1) |
| BTN-1 (bottom-left) | game preview | PREV ← nav |
| BTN-2 (top-right) | game preview | game preview (idx+1) — unchanged |
| BTN-3 (bottom-right) | NEXT → nav | NEXT → nav — unchanged |

Only BTN-0 and BTN-1 swapped roles; BTN-2/BTN-3 were already correct for the new layout. `drivers/buttons.py`'s `BTN_PREV`/`BTN_NEXT` aliases are the single source of truth for the nav roles — `core/menu.py`'s "select" handling (which button launches which preview) was updated to match by hand, since it isn't derived from those aliases.

End-of-game screens (Match It!, Star Bonk) also moved BACK from BTN-0 to **BTN-3** (bottom-right), with "Play Again" now on BTN-0,1,2 — a deliberate choice by the project owner, not a semantic-consistency inference (BTN-3 now doubles as "NEXT" in the menu and "BACK to menu" in an end screen — different meaning, same physical button, intentional).

#### MADCTL is per-button, not uniform

The right column (BTN-2/3) is mounted physically rotated 180° from the left column (BTN-0/1), for tidy cable routing — same part number, same landscape orientation, but the panel itself is flipped in its mounting. That has to be compensated in software or BTN-2/3 render upside-down/mirrored relative to BTN-0/1.

- **BTN-0/1: `MADCTL = 0x60`** — confirmed (300×240, clean fill, correct top-left corner) via `tests/test_15_button_landscape.py` on an unmounted panel.
- **BTN-2/3: `MADCTL = 0xA0`** — `0x60` with the MY and MX bits both toggled (`0x60 ^ 0xC0`), the 180° rotation of the confirmed value. **Reasoned correct, not yet bench-confirmed** on an actual mounted right-column panel — it's the same value the test already tried and rejected for an *unrotated* panel, which is consistent with it being the flipped variant, but "consistent with" isn't "confirmed on." Point `CS_IDX` at position 2 or 3 and re-run the test before trusting this.

`config.py`'s `ST7789_MADCTL` is a 4-tuple indexed by button, `(0x60, 0x60, 0xA0, 0xA0)`; `drivers/display.py`'s `ST7789.__init__` reads `config.ST7789_MADCTL[index]` — there is no single global MADCTL for the button screens anymore.

Working init sequence (current, landscape, BTN-0/1 shown — BTN-2/3 use `0xA0` for the MADCTL line, everything else identical):

```python
wc(0x01); time.sleep_ms(150)    # SW reset
wc(0x11); time.sleep_ms(255)    # sleep out
wc(0x3A); wd(0x05)              # RGB565
wc(0x36); wd(0x60)              # MADCTL — 0x60 (BTN-0/1) or 0xA0 (BTN-2/3)
wc(0xB2); wd(0x0C,0x0C,0x00,0x33,0x33)
wc(0xB7); wd(0x35)
wc(0xBB); wd(0x19)
wc(0xC0); wd(0x2C)
wc(0xC2); wd(0x01)
wc(0xC3); wd(0x12)
wc(0xC4); wd(0x20)
wc(0xC6); wd(0x0F)
wc(0xD0); wd(0xA4,0xA1)
wc(0xE0); wd(0xD0,0x04,0x0D,0x11,0x13,0x2B,0x3F,0x54,0x4C,0x18,0x0D,0x0B,0x1F,0x23)
wc(0xE1); wd(0xD0,0x04,0x0C,0x11,0x13,0x2C,0x3F,0x44,0x51,0x2F,0x1F,0x1F,0x20,0x23)
wc(0x21); wc(0x13); time.sleep_ms(10)
wc(0x29); time.sleep_ms(255)    # display ON
```

---

## FT6236 Touch (landscape, confirmed)

- I2C bus 1: SDA=GP26, SCL=GP27, INT=GP28
- Address: `0x38`
- `CTP_RST`: 10kΩ pull-up to 3.3V (per module supplier's own recommendation)
- Landscape axis mapping — see [Display Orientation](#display-orientation--landscape-confirmed) above for the confirmed flags.

---

## SD Card

The SD slot built into the ILI9488 display module **cannot be used** alongside the display controller: once the ILI9488 is initialized and active, its SDO pin drives the shared MISO line low even while its own CS is high, blocking all SD communication.

**Fix:** physically disconnect the ILI9488 module's SDO pin from GP4. The displays are write-only (no readback ever needed), so removing SDO costs nothing — but leaving it connected lets the active display controller stomp MISO. Only the separate SD breakout may drive GP4/MISO.

Symptom if reconnected: standalone SD tests pass (because the display isn't initialized yet in that test), but SD fails with `timeout waiting for v2 card` the moment firmware initializes the main display.

Confirmed working configuration:
- Separate SPI SD breakout on the shared SPI0 bus, `SD_CS = GP3`.
- 10kΩ pull-up on MISO (GP4) is mandatory — and physically fragile on breadboard. A loose leg produces the same `timeout waiting for v2 card` as the SDO-contention bug above; reseat it first when SD fails after any board handling.
- SD data transfers run at **400kHz**, not the 10MHz in `config.SPI_FREQ_SD_DATA` (that value is aspirational, for a future soldered board). At 1.32MHz+ the breadboard throws `EIO` on block reads.
- All other CS pins (GP6–GP10) must be held HIGH before SD init to avoid bus contention.

---

## SPI Bus

- SPI0: SCK=GP18, MOSI=GP19, MISO=GP4.
- GP2/GP3 do **not** work as SCK/MOSI, despite the SPI constructor accepting them without error.
- GP4 does not work as MOSI.
- GP18/GP19 are the only confirmed-valid SCK/MOSI for SPI0 on this board/firmware.
- All CS pins must be held HIGH before SD card init.

---

## Firmware / MicroPython Gotchas

- `random` has `choice()` but **not** `shuffle()` — hand-roll Fisher–Yates with `randint` (inclusive of both ends).
- **Buffer allocation:** allocate all four render buffers once, at renderer/game init, immediately after `gc.collect()` — never per-frame, never per-round. Allocate the two 45KB RGB666 buffers first (largest, hardest to place), then the two 30KB source buffers, at a quiet game-load moment. Heap fragmentation only grows once menus, audio, and LED effects have churned it — 47% fragmentation at boot vs. ~352KB free / 187KB largest-contiguous post-boot, on a 446KB MicroPython heap.
- **`spi_bus._set_freq()` cache desync — and the trap in "fixing" it:** the bus wrapper caches `_current_freq` and skips the re-init when the requested frequency already matches, which is correct and necessary — `spi.init()` is a real hardware reconfigure, and paying it on every SPI transaction is audible as stutter on audio playback (measured: every ~4KB chunk read wrapped in an unconditionally-reiniting `set_freq` turned smooth playback into a stutter within one commit). The actual bug is narrower: SD mount constructs its own `machine.SPI(config.SPI_ID, ...)` instance and `SDCard.init_spi()` calls `.init()` on *that* object — same physical SPI0 peripheral, invisible to `spi_bus`'s cache — so the cache goes stale exactly once, right after mount. Fix: keep the skip-if-unchanged cache; route every direct `spi.init()` call in the codebase through `spi_bus.set_freq()` instead of touching `spi_bus.spi`/a raw `machine.SPI` directly; and call the new `spi_bus.invalidate()` right after SD mount (before restoring display speed) since that's the one point a foreign SPI object is known to have moved the real clock behind the cache's back. Do **not** "fix" a future occurrence of this by making `_set_freq` unconditional again — find the new out-of-band `spi.init()` caller and route it through `set_freq()`/`invalidate()` instead.
- **`__import__` is native** — no kwargs, and it returns the top-level package, not the leaf module. For dynamic game loading (`games/registry.py`), walk the dotted path manually (`for part in path.split('.')[1:]: mod = getattr(mod, part)`) instead of using `fromlist=`.
- **`wait_screen_button()` ignores BACK (id 4)** — games needing BACK-to-quit must poll `buttons._queue` directly (see `games/example/game.py` / `games/match/game.py`).
- **LED effects run as asyncio tasks** — `leds.off()` only clears pixels, it does not stop a running effect task (which keeps rewriting the strip). Use `leds.stop_effect()` / `strip_renderer` to actually halt an effect.
- **Audio I2S must be non-blocking.** A blocking `i2s.write()` freezes the event loop for the whole chunk, starving the display mid-fill and producing white/coloured stripe tearing during playback. Use IRQ-callback mode (`i2s.irq(cb)`, `mode=I2S.TX`): `write()` returns immediately and the callback fires on drain — await an `asyncio.Event` set by the callback. `asyncio.StreamWriter`/`drain()` does **not** yield on this RP2350/v1.28 build (measured with `tests/test_i2s_yield.py` — the loop froze), so IRQ-callback is required, not `StreamWriter`.
- **Main-display RGB565→RGB666 conversion must use `@micropython.viper` AND stream in bands** (`graphics_speed/rgb666_viper.py`). The per-pixel Python conversion loop was ~31x slower (476ms vs 15ms for a 160×160 buffer) and starved the event loop, causing audio tearing and button lag. Converting the whole buffer at once needs a 76KB RGB666 output buffer, which throws `MemoryError` on the fragmented heap even when total free memory looks sufficient. Convert/stream in ~16-row bands with a small (~7.5KB) reused scratch buffer (`gc.collect()` before the one-time allocation). The viper function takes a source pixel offset so each band starts at the correct row.
- **Button debounce:** fire "press" on the *first* edge, and only debounce the *release*. The old approach (detect press → sleep 30ms → re-read → discard if released) threw away quick child taps entirely ("I press but nothing happens"). Fire press immediately (never dropped), debounce release time-based with no blocking sleep — a blocking sleep here also stalled the scan of other buttons.

---

## Hardware Bring-Up Test Results

| Test | File | Status |
|---|---|---|
| Pico 2 W health | `tests/test_01_pico_health.py` | ✓ Passed |
| ILI9488 main display | `tests/test_02_main_display.py` | ✓ Passed |
| FT6236 touch | `tests/test_03_touch.py` | ✓ Passed |
| ST7789 button displays | `tests/test_04_button_displays.py` | ✓ Passed |
| All 5 displays + touch | `tests/test_05_all_displays.py` | ✓ Passed |
| Push buttons | `tests/test_05_buttons.py` | ✓ Passed |
| Full integration | `tests/test_06_integration.py` | ✓ Passed |
| MCP23008 expander | `tests/test_07_mcp23008.py` | ✓ Passed |
| MAX98357A audio | `tests/test_08_audio.py` | ✓ Passed |
| WS2812B LEDs | `tests/test_09_leds.py` | ✓ Passed |
| Buttons via MCP23008 | `tests/test_10_buttons_mcp.py` | ✓ Passed |
| Haptic motor | `tests/test_11_haptic.py` | ✓ Passed |
| Boot RAM/heap | `tests/test_12_boot_ram.py` | ✓ Passed |
| LED strip scene | `tests/test_13_strip_scene.py` | ✓ Passed |
| Sprite engine | `tests/test_14_sprite_engine.py` | ✓ Passed |
| SD card | `tests/test_sd_card.py` | ✓ Passed |

Additional targeted probes (not full bring-up tests, used to diagnose the gotchas above): `test_audio_trace.py`, `test_button_latency.py`, `test_fill_speed.py`, `test_i2s_yield.py`, `test_rgb666_viper.py`, `test_sd_probe.py`, `test_touch_crosshair.py`, `test_15_button_landscape.py` (orientation probe — confirmed `MADCTL=0x60`/300×240 for BTN-0/1's mounting; `MADCTL=0xA0` for BTN-2/3's 180°-rotated mounting is reasoned but not yet bench-confirmed).

---

## Star Bonk! — sprite_engine Integration (first real use, NOT bench-verified)

Star Bonk (`games/bonk/`) is the first game to actually wire up
`core/sprite_engine.py` + `drivers/strip_renderer.py` + `core/sprite_adapter.py`
— everything below is new as of this game and needs a real hardware pass
before trusting it, same as anything else in this doc marked unverified.

### Why sprite_engine instead of the simple direct-blit path Match It! uses

A target pops up at a genuinely random position every spawn and must
cleanly reveal the real board underneath when it disappears — the simple
`blit_rgb565` path Match uses (same fixed slot every time, opaque icon,
no erase needed) can't do that without either a full-screen repaint per
hit (too slow for a reaction game) or constraining the board to a flat
erase-colour play zone (visually limiting). `sprite_engine`'s dirty-strip
compositing against a real LE background solves this properly — moving/
removing a sprite naturally re-reveals the actual board pixels.

### Asset spec (endianness/colour-key mistakes here fail loudly, not silently)

Each of the 4 characters (wizard, goblin, star, mushroom) needs **two**
baked sprites — one per rendering path:

| Asset | Format | Purpose |
|---|---|---|
| `bonk/spr_<name>_96x96x1.sz` | **LE**, kind 2, magenta-keyed (`0xF81F`) | Main-screen target — sprite_engine reads this |
| `bonk/sprb_<name>_96x96x1.sz` | **BE**, kind 3, opaque | Button-screen legend icon — plain `blit_btn_buf`, same convention as Match's icons |
| `bonk/bg_bonk_480x320.bz` | **LE**, kind 0, `strip_h=32` | Main board — can be fully illustrated everywhere now (no flat-colour play-zone constraint) |
| `menu/bgm_menu-bonk_480x320.bz` | BE, kind 1 | Menu card (optional — `core/menu.py` falls back to a procedural card if missing) |

`strip_h` on the board **must** be 32 to match `sprite_engine.STRIP_H` — `SpriteEngine.set_background()` raises if it doesn't. `tools/deploy.py` now splits Tier A (`sprb_`/`spr_`, small, permanent littlefs) from Tier B (`bgm_`/`bg_`, large, SD-installed at game load) by filename prefix for any game folder, not just Match's — Bonk needed no deploy.py changes beyond that generalization.

Missing/invalid assets degrade gracefully: a bad character sprite drops that character from the round's spawn pool (fewer live types, not a crash); a missing/invalid board falls back to an in-memory flat-colour `_FlatBackground` stub (in `games/bonk/game.py`) so the mechanic stays testable before art exists — mirrors Match's per-icon coloured-placeholder fallback.

### What's genuinely new/unverified here

- **First real `StripRenderer` hardware wiring.** `core/sprite_adapter.make_main_strip_renderer()` constructs fresh `Pin` objects for `PIN_CS_MAIN`/`PIN_DC_MAIN` and binds `spi_bus.spi` + `spi_bus.set_freq` — reasoned to be safe (same physical pins ILI9488's own driver already idles high, no concurrent user), but never bench-tested.
- **150KB `StripBufferPool`, held for the whole game via `MainScreenAdapter.open()`/`close()`.** On top of the 96KB flash_assets arena (always seated) and Bonk's own small ~20KB legend arena, this needs a real free-heap check at game load — `StripBufferPool` hard-fails with a diagnostic `MemoryError` if it can't seat (by design, not a bug to paper over), but if it doesn't fit, `core/kernel.py`'s `game.load()` call has no exception handling around it, so a failed seat currently crashes the whole app rather than gracefully declining to launch. Worth a bench check before relying on this in front of a kid.
- **`StripRenderer`'s blocking transmit path does not take `spi_bus`'s lock** — it writes to `spi_bus.spi` directly, bypassing the `device()`/`raw()` serialization every other SPI0 consumer uses. Reasoned to be safe for Bonk specifically because everything in its `run()` loop is awaited sequentially and the only concurrent background activity (LED/haptic/audio bonk-feedback) never touches SPI0. **This becomes a real hazard if a future game uses `SpriteEngine.start()`'s continuous background tick loop** (an independent asyncio task redrawing on a timer) concurrently with anything else touching SPI0 (another display draw, an SD read) — that combination has not been reasoned through and should not be assumed safe.
- **The DMA transmit seam is unused here** — Bonk runs the blocking `_start_transmit`/`_wait_transmit` implementation, matching the "not yet verified" status the seam already carried in the Soldered-Board Follow-Ups section below.

### Gameplay assumptions (tunable, not hardware facts — flagged since the design synopsis didn't pin these down)

- `ROUND_HITS = 8` bonks per round (24 total across 3 rounds) — arbitrary, easy to retune.
- `TARGET_POINTS`: wizard=1, goblin=2, star=3, mushroom=4 — ordering matches the fixed button legend order (BTN-0..3), no gameplay difference in spawn odds by value.
- Speed curve: 2000ms reaction window at the start, -200ms every 10 hits (running total, not reset per round), floored at 700ms.
- A missed/timed-out target is never penalised — it just despawns and a new one spawns, matching this console's low-pressure design for ages 4-7.
- "Tap anywhere near" is implemented as a 24px hit-pad on all sides of the 96×96 sprite (144×144 effective hit zone).

---

## Soldered-Board Follow-Ups (performance headroom, bench-gated)

Deliberately not attempted on the breadboard — each needs a bench pass on
the soldered board before trusting it:

- **Display SPI at 20MHz.** The ILI9488 write clock is rated to 20MHz;
  10MHz is the confirmed breadboard ceiling. Doubling it halves the
  ~552ms full-frame cost on the main display and ~177ms on the ST7789s.
  Re-run `tests/test_fill_speed.py` and the touch crosshair after changing
  `SPI_FREQ_DISPLAY`.
- **SD data rate.** `SPI_FREQ_SD_DATA` is 400kHz because the breadboard
  EIOs at ≥1.32MHz. On a soldered board, retest at 10MHz — that makes
  direct SD audio streaming viable (4KB chunk in ~3ms instead of ~82ms)
  and menu-card streaming from SD plausible.
- **DMA pixel transmit.** `drivers/strip_renderer.py` has the transmit
  seam (`_start_transmit`/`_wait_transmit`) designed so an rp2.DMA channel
  into the PL022 TX FIFO can replace the blocking write without touching
  window setup, CS framing, or the converter. The RP2350/v1.28 DMA↔PL022
  wiring is unverified — bench-confirm before trusting it.

---

## Status Snapshot

Confirmed done:
- All hardware bring-up tests passing (1–14 plus SD).
- MCP23008 GPIO expander at `0x20`; all physical buttons + BACK routed through it.
- MAX98357A audio, WS2812B LEDs, haptic motor all confirmed on their pins.
- SD card working with breakout module (ILI9488 SDO physically disconnected from GP4).
- Landscape rotation confirmed end-to-end — display (`MADCTL 0x28`) + touch mapping.
- Graphics speed pass done — viper-banded RGB565→666 conversion, big-chunk fills, reusable blit scratch buffer.
- Shape Match playable end-to-end (`games/match`).

In progress, needs a bench pass (see Star Bonk section above for detail):
- Star Bonk (`games/bonk`) — code complete, registered, but genuinely untested on hardware. Blocking before it's trustworthy: bake the 10 required assets (see asset spec table above), confirm the 150KB StripBufferPool actually seats alongside everything else at game load, and confirm the first-ever StripRenderer hardware wiring (CS/DC pins, blocking transmit) actually paints correctly.

Outstanding:
- Asset pipeline: family photos → stylised art → RGB565 conversion.
- Family voice recording sessions for "My Big Day Out".
- 3D-printed shell design.
- Battery ADC wiring (MCP23008 GP5) and TP4056 charger wiring.
- Remaining games in the library (Button Memory next).
