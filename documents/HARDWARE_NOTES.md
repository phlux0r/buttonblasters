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
- **A few physical pixels are cropped on every button screen's left edge**, confirmed on-device via Button Memory's persistent lit-button border (the first UI element ever drawn flush against `x=0` and left on screen long enough to actually look at — Match It!/Star Bonk!'s borders are brief win/lose flashes, easy to miss a clipped edge in). Confirmed uniform across **all 4 buttons regardless of MADCTL** (ruled out as an artifact of BTN-2/3's rotated `0x60` vs BTN-0/1's `0xA0` — see the per-button MADCTL note above), so this isn't a coordinate/rotation bug in `_set_window()`; it presents the same as the panel's own visible glass starting a few columns in from the controller's addressable column 0 (bezel/mounting overlap), same category of quirk as the 240×280→300 row-window fix above, just never noticed until something was drawn flush to the column edge. No `COL_OFFSET` compensation exists in `drivers/display.py`'s `ST7789._set_window()` — worth adding if a future game needs pixel-perfect edge alignment, but the exact crop width needs an on-device measurement (e.g. binary-search an offset until a flush test rectangle stops clipping) rather than a guess. Current workaround: draw edge decoration (Button Memory's lit-button border) flush + thick (24px) rather than inset, so the lost columns are a small fraction of the border instead of most of it.

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

- **BTN-0/1: `MADCTL = 0xA0`** — confirmed (300×240, clean fill, correct top-left corner) via `tests/test_15_button_landscape.py`.
- **BTN-2/3: `MADCTL = 0x60`** — `0xA0` with the MY and MX bits both toggled (`0xA0 ^ 0xC0`), the 180° rotation of the BTN-0/1 value. **Confirmed** via `tests/test_15_button_landscape.py` on both right-column positions (2 and 3) — clean fill, correct top-left corner as viewed on the mounted right-column panels.

`config.py`'s `ST7789_MADCTL` is a 4-tuple indexed by button, `(0xA0, 0xA0, 0x60, 0x60)`; `drivers/display.py`'s `ST7789.__init__` reads `config.ST7789_MADCTL[index]` — there is no single global MADCTL for the button screens anymore.

Working init sequence (current, landscape, BTN-0/1 shown — BTN-2/3 use `0x60` for the MADCTL line, everything else identical):

```python
wc(0x01); time.sleep_ms(150)    # SW reset
wc(0x11); time.sleep_ms(255)    # sleep out
wc(0x3A); wd(0x05)              # RGB565
wc(0x36); wd(0xA0)              # MADCTL — 0xA0 (BTN-0/1) or 0x60 (BTN-2/3)
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

Additional targeted probes (not full bring-up tests, used to diagnose the gotchas above): `test_audio_trace.py`, `test_button_latency.py`, `test_fill_speed.py`, `test_i2s_yield.py`, `test_rgb666_viper.py`, `test_sd_probe.py`, `test_touch_crosshair.py`, `test_15_button_landscape.py` (orientation probe — confirmed `MADCTL=0xA0`/300×240 for BTN-0/1, `MADCTL=0x60` for BTN-2/3's 180°-rotated mounting, on all 4 physical positions).

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
| `bonk/bg_bonk_480x320.bz` | **LE**, kind 0, `strip_h=8` | Main board — can be fully illustrated everywhere now (no flat-colour play-zone constraint) |
| `menu/bgm_menu-bonk_480x320.bz` | BE, kind 1 | Menu card (optional — `core/menu.py` falls back to a procedural card if missing) |

`strip_h` on the board **must** be 8 to match `drivers.strip_renderer.STRIP_H` (the single source of truth — `core/sprite_engine.py` imports it rather than defining its own copy, after those two drifted out of sync once already) — `SpriteEngine.set_background()` raises if it doesn't. History: 32 → 16 → 8, each drop forced by a confirmed on-hardware MemoryError (see the StripBufferPool entry below) — check that entry before baking, in case the number has moved again since this was written. This asset has never successfully been baked at the currently-required value at time of any report so far, so re-baking it isn't throwing away prior work each time, just catching up to a number that kept moving out from under it. `tools/deploy.py` now splits Tier A (`sprb_`/`spr_`, small, permanent littlefs) from Tier B (`bgm_`/`bg_`, large, SD-installed at game load) by filename prefix for any game folder, not just Match's — Bonk needed no deploy.py changes beyond that generalization.

**`tools/bake_assets.py` (added this session — the actual baker, not previously in this repo) had a real colour-key bug:** every `spr_*` sprite showed a visible magenta outline around the character, confirmed by decompressing the shipped `.sz` files directly — each one had a 1-2px ring of near-`0xF81F`-but-not-bit-exact pixels hugging every silhouette edge, which the on-device compositor's exact `!=` colour-key test doesn't treat as transparent. Root cause: `ffmpeg_to_raw()` used ffmpeg's `overlay` filter, which alpha-*blends* the source PNG onto the matte colour — any source pixel with partial alpha (anti-aliased art edges, or a fill/bucket tool that only clears fully-transparent pixels and leaves a low-alpha ring right at the edge) came out as a blended near-matte colour instead of the matte itself. Reproduced and fixed with a synthetic alpha=128 test PNG run through both the old and new filter graphs. Fix: hard-threshold alpha to 0/255 (`alphaextract`+`lut`+`alphamerge`) before compositing, so `overlay` always either keeps the exact source RGB or reveals the exact matte — never a blend. User re-baked the Bonk sprites with the fix and pushed the result; re-checking the re-baked files directly showed blended-fringe pixel counts dropped from 227-599 per sprite to 0-5 (the handful remaining are plausibly genuine near-magenta art content, not fringe, given the order-of-magnitude drop). **Not yet confirmed visually on hardware.**

Missing/invalid assets degrade gracefully: a bad character sprite drops that character from the round's spawn pool (fewer live types, not a crash); a missing/invalid board falls back to an in-memory flat-colour `_FlatBackground` stub (in `games/bonk/game.py`) so the mechanic stays testable before art exists — mirrors Match's per-icon coloured-placeholder fallback.

### What's genuinely new/unverified here

- **First real `StripRenderer` hardware wiring.** `core/sprite_adapter.make_main_strip_renderer()` constructs fresh `Pin` objects for `PIN_CS_MAIN`/`PIN_DC_MAIN` and binds `spi_bus.spi` + `spi_bus.set_freq` — reasoned to be safe (same physical pins ILI9488's own driver already idles high, no concurrent user), but never bench-tested.
- **`StripBufferPool`, held for the whole game via `MainScreenAdapter.open()`/`close()`. Confirmed failing on real hardware three times, at three different pool sizes.**
  1. `MemoryError: ... rgb666[1] did not seat (free=205552, largest~needs 46080 contiguous)` at 150KB (`STRIP_H=32`) — traced to `games/bonk/game.py`'s `load()` allocating the 20KB legend arena *before* `adapter.open()`, violating this codebase's "acquire hardest-first" rule; fixed by reordering.
  2. Same error, same 46080-byte ask, *after* that fix (`free=211376`) — proved the fragmentation predates Bonk's `load()` entirely (menu rendering, boot sequence, or prior session state), not something reorderable within one game's load. Fixed by halving to `STRIP_H=16` (75KB pool, 22.5KB largest block).
  3. `MemoryError: ... rgb666[1] did not seat (free=222752, largest~needs 23040 contiguous)` at 75KB (`STRIP_H=16`) — **on a *later* play within the same power-on session**, not the first attempt (per the user: it worked once, then failed again after unplugging/replugging USB — if the console runs on its LiPo battery, that does NOT power-cycle the device, so this was very likely the same long-running session accumulating fragmentation, not two independent fresh boots). Fixed by halving again to `STRIP_H=8` (37.5KB pool, 11.25KB largest block, ~4x the original strip count).

  **This recurring pattern — the same failure resurfacing after each halving — is a signal the real fix may be structural, not size.** `MainScreenAdapter.open()`/`close()` allocates and frees this pool once per Bonk game *session* (every time the player launches Bonk from the menu, not once per boot), so repeated play within one power-on period repeatedly churns the heap with same-shape alloc/free cycles a non-compacting allocator can't perfectly reclaim — smaller buffers reduce the odds of failure per attempt but don't eliminate the underlying churn. If `STRIP_H=8` also fails, the next lever isn't a smaller buffer — it's making this pool **persistent**: seated once (module-level, like `flash_assets.arena` already is) instead of per-session, trading a permanent heap reservation (whether or not Bonk is ever played) for eliminating the repeated-alloc/free class of failure entirely. Not yet applied to this pool specifically — deserves confirming `STRIP_H=8` is actually insufficient first — but the pattern is now precedented elsewhere in this same file: the button-legend `SpriteArena` (20KB, much smaller but same per-session churn shape) hit exactly this failure mode next and was fixed by making *it* persistent (see the "fourth confirmed hardware failure" entry below). If the strip pool ever needs the same treatment, that's a working template, not a hypothetical.
- **`core/kernel.py`'s `game.load()` had no exception handling** (unlike `game.run()`, which always has) — the MemoryError above propagated all the way out of `AppKernel.run()` and crashed the whole app instead of bouncing back to the menu. Fixed: `load()` failures are now caught, shown as a brief "Couldn't load" splash, and the kernel returns to the carousel — applies to any game's load-time failure, not just this one.
- **Third confirmed hardware failure, this time during `game.run()` not `load()`:** `MemoryError: memory allocation failed, allocating 8192 bytes`, mid-playthrough, after `load()` succeeded (the StripBufferPool fix above held). `core/kernel.py`'s existing try/except around `game.run()` caught it (game aborted back to the menu, app didn't crash), but the game itself wasn't playable. Traced to `drivers/audio.py`'s `_play_wav()`: it allocated a brand-new `bytearray(config.AUDIO_BUF_BYTES)` (4096B) **and** a brand-new `machine.I2S` object on every single call, neither cached — and `games/bonk/game.py`'s `_bonk_feedback()` calls `play_sfx("correct.wav", wait=True)` on every hit (up to 24×/game). This port's GC is non-moving mark-and-sweep, so that per-call churn leaves unreclaimed, unmerged holes until the next `gc.collect()` — the same fragmentation-accumulation story as the StripBufferPool failures above, just triggered by audio instead of the sprite pool. The failing size (8192 = 2× `AUDIO_BUF_BYTES`) is *suggestive* of RP2's `machine.I2S` driver internally double-buffering its DMA ring, but this is **not confirmed** — no MicroPython C source or hardware access to verify the exact mechanism, only the fragmentation story. Fixed two ways: (1) `games/bonk/game.py` now calls `gc.collect()` once per round (a quiet point, no audio/display/sprite work in flight), matching this codebase's existing "collect at a quiet moment" discipline; (2) `drivers/audio.py` now caches and reuses its read buffer (`self._read_buf`) across `_play_wav()` calls instead of allocating fresh every clip — the I2S peripheral itself is still torn down after every clip, unchanged, because that's load-bearing for the MAX98357A auto-mute/noise behavior documented in this same file's module docstring, not something this fix touches. **Not bench-confirmed.** If a full Star Bonk playthrough still hits this same error after these two changes, the next lever is lowering `config.AUDIO_BUF_BYTES` (4096→2048, confirmed via grep to have no other consumers besides `drivers/audio.py` and two test scripts) — deliberately not applied preemptively since (1)+(2) weren't yet tested on hardware when this was written.
- **Fourth confirmed hardware failure, same fragmentation-accumulation class, a different allocation this time:** `MemoryError: memory allocation failed, allocating 20480 bytes` on `game.load()` — caught by the `core/kernel.py` fix above, so it bounced back to the menu ("`[kernel] bonk failed to load: ...`") instead of crashing, but the game couldn't be (re-)entered. 20480 bytes = exactly `games/bonk/game.py`'s 20KB button-legend `SpriteArena`. Occurred on a **second** Bonk session within one power-on run (menu → Bonk → menu → Bonk again), not the first — and notably *after* the (larger, harder) strip buffer pool had already seated fine in that same `load()` call, meaning the leftover free space right after that carve was scattered into fragments all under 20KB. Root cause: `self._legend_arena = flash_assets.SpriteArena(20 * 1024)` allocated a brand-new 20KB `bytearray` on *every* `load()`, then let it become garbage on `unload()`/game-object replacement — the identical per-session alloc/free churn pattern already flagged (but not yet acted on) for the strip buffer pool above, just surfacing through a smaller victim first. Fixed by making the arena **persistent**: a module-level `_legend_arena` in `games/bonk/game.py`, allocated once on the first Bonk `load()` in a power-on session and only `.reset()` (a bump-pointer rewind, not a new allocation) on every load after that — the same pattern `flash_assets.arena` already uses, applied here ahead of doing it for the strip pool since this is the allocation that's actually confirmed failing. **Not bench-confirmed.** If the strip pool itself (not the legend arena) still fails a *second* session's `load()` after this, that's the confirmation the deferred "make the strip pool persistent too" step above needs.
- **Touch target detection reported "misses quite a few targets... intermittent and laggy."** Root cause: `_wait_hit_or_timeout()` relied entirely on the discrete `TOUCH_TAP` queue event, which `drivers/touch.py` only posts on finger-*lift*, and only if the whole touch stayed under `LONG_PRESS_MS` (600ms) *and* under `TAP_MAX_TRAVEL` — a hold slightly too long, or a few px of drag (both easy for a 4-7yo stabbing at a moving target), silently dropped the tap entirely with no event ever posted, not even a "miss". Fixed by adding a `touch_down` property to `drivers/buttons.py`'s `ButtonManager` (exposes `TouchDriver._touch_down`, which is live/continuous, unlike the gesture-classified discrete events) and rewriting `_wait_hit_or_timeout()` to poll `touch_down`/`touch_pos` directly every loop iteration instead of waiting for `TOUCH_TAP` — a hit now registers the instant a finger lands in the target zone, whether or not it's ever lifted cleanly or held past the long-press threshold. **Not bench-confirmed.**
- **Fifth confirmed hardware failure, same fragmentation-accumulation class, this time introduced by the countdown-scale fix below:** `MemoryError: memory allocation failed, allocating 38400 bytes`, mid-`run()` (`"[kernel] running bonk"` then `"game crashed"`, caught by the existing try/except). Traced to `core/display_manager.py`'s shared text-rasteriser scratch buffers (`_TXT_BASE`/`_TXT_OUT`) — module-level, grown lazily the first time a bigger string/scale is requested, never shrunk. `BaseGame.countdown()`'s `"GO!"` at scale 10 needs a `240×80×2 = 38,400`-byte output buffer, the single biggest text draw anywhere in the app — and it was the *first* caller ever to need a buffer that size, which happened well into a Bonk session (after `load()` had already seated the strip pool, the legend arena, and the sprite sheets), not at boot on a fresh heap. Fixed by adding `display_manager.warm_text_scratch()` and calling it once from `core/kernel.py`'s `init()`, immediately after `flash_assets.init()` — the same "seat on the freshest heap, before any subsystem churns it" argument already applied to that arena and to the legend arena above. **Not bench-confirmed.** If some future screen ever needs a bigger text draw than `"GO!"` at scale 10, `warm_text_scratch()`'s pre-grow won't cover it and this class of failure can recur — bump what it renders to match.
- **Sixth confirmed hardware issue — real memory *corruption*, not a `MemoryError`, and the only one of the six that's visual instead of a crash:** playing a full round-set more than once without returning to the menu carousel ("Play Again") corrupted the wizard and goblin main-screen sprites; star and mushroom stayed clean. Root cause: `core/display_manager.py`'s `paint_main_bg()`/`paint_btn_bg()` unconditionally `reset()` + `alloc()` the SHARED `flash_assets.arena` for their per-strip scratch buffer — fine for transient callers (Match It! reloads its icons fresh every match; the menu and boot splash don't keep anything else there), but Star Bonk's `load()` keeps its 4 main-screen sprite sheets (wizard, goblin, star, mushroom, loaded in that order into arena offsets 0, 18432, 36864, 55296) resident in that SAME arena for the whole game session. `_end_screen()` runs once per completed round-set (i.e. on every "Play Again", not just when returning to the menu) and paints `BACK_TILE_PATH`/`REPLAY_TILE_PATH` (300×32×2 = 19,200B) and `RESULT_PATH` (480×32×2 = 30,720B) via those same two methods — each call resets the shared arena's bump pointer to 0 and overwrites whatever sits at the start of it. Wizard (bytes 0–18432) falls entirely inside every one of those strip buffers; goblin (18432–36864) falls partially inside the ~19–30KB range; star and mushroom (36864+) never do — which matches the reported symptom exactly. Confirmed (not just reasoned) with a standalone script that replays `flash_assets.py`'s real `SpriteArena`/`SpriteSheet` logic against the actual shipped `.sz` files: reproduced wizard/goblin corruption with star/mushroom untouched using the shared arena, and showed it disappears using a separate one. Fixed: `paint_main_bg()`/`paint_btn_bg()` now take an optional `arena=` param (default unchanged, so Match It!/menu/boot are unaffected); Bonk's former `_legend_arena` is renamed `_scratch_arena`, bumped from 20KB to 32KB (covers the largest single request across both uses — legend icons and end-screen tiles are never needed at the same time), and passed into every `_end_screen()` paint call, fully isolating those transient paints from the persistent sprite arena. **User-confirmed fixed on real hardware** ("ok that is fixed").
- **Seventh confirmed hardware failure, found immediately after the sixth one shipped:** `[audio] playback error: MemoryError('memory allocation failed, allocating 13230 bytes')` / `11024 bytes`, right after a Bonk round-set ends. Those two sizes match `drivers/audio.py`'s `_synth_tone()` buffer for `new_high_score.wav` (300ms → 13,230B) and `well_done.wav` (250ms → 11,024B) exactly. Neither has a baked audio file for Bonk (or anywhere shared/SD), so `BaseGame.announce_round_complete()` falls through to the synth-tone fallback — which allocated a **brand-new** `bytearray` every single call, unlike `_read_buf` (already fixed earlier this session to be cached). It fires right after `_end_screen()`'s tile/result painting — the most fragmented point in a round-set, made worse by the very fix that had just landed for the sixth issue. Fixed the same way as `_read_buf`: added `AudioManager._synth_buf`, pre-sized at `AudioManager()` construction (an import-time side effect — the freshest heap this app ever sees, even earlier than `flash_assets.init()`) to the largest `_SYNTH_MAP` entry (`game_over.wav`, 400ms → 17,640B), and `_synth_tone()` is now a method that reuses it (grow-and-cache-once for any future `play_tone()` call needing more). Verified standalone (not on hardware) that all 15 `_SYNTH_MAP` entries now serve with zero new allocations. **Not bench-confirmed.**
- **Button-screen legend tiles used `LEGEND_BG = DARK` for a populated target's idle background** — inconsistent with Match It!'s established `ICON_BG = WHITE` convention (icons are baked opaque-on-white, so they only blend cleanly against a white tile). Fixed: `LEGEND_BG = WHITE`; unpopulated tiles are unaffected (still `BLACK`, a separate code path in `_paint_target_buttons()`). **Not bench-confirmed.**
- **Eighth confirmed hardware failure — the sixth issue's `_scratch_arena` (32KB, lazy-seated on first Bonk `load()`) regressed to failing on EVERY load, not just repeat plays:** `[kernel] bonk failed to load: memory allocation failed, allocating 32768 bytes`, reported right after raising `config.SPI_FREQ_DISPLAY` (10→24MHz) and adding a `config.MACHINE_FREQ` core overclock (150→200MHz). Neither change allocates RAM, so the likely mechanism is timing, not size: faster display draws mean fewer/different `asyncio.sleep_ms(0)` yield points during the menu and `game_cache.install()`'s SD→littlefs copy, which shifts *when* other background tasks (LEDs, audio) run and allocate/free their own buffers — enough, on this non-compacting GC, to change where a fresh 32KB claim lands relative to whatever's fragmented by the time `load()` asks for it. That it now failed on the *first* load of a session too (previously only a second-session problem, see the fourth failure above) means the lazy-seed-on-first-load pattern was already living on borrowed time — it just needed a big enough timing nudge to fall over on session one. Fixed by applying the SAME "freshest heap" treatment already used for `flash_assets.arena` and `warm_text_scratch()`: `games/bonk/game.py` now exposes `seat_scratch_arena()`, called once from `core/kernel.py`'s `init()` right after `warm_text_scratch()` — so the arena is carved out before the menu, asset installer, or any other subsystem gets a chance to fragment the heap first. `load()` still calls `seat_scratch_arena()` (now an idempotent no-op in the normal case) as a defensive fallback, then `.reset()`s it same as before. **Not bench-confirmed** — could not be tested on real hardware from this session; needs a full boot + first-load + repeat-load check.
- **Ninth confirmed hardware failure, immediately after the eighth's fix above:** `StripBufferPool: rgb666[1] did not seat (free=142784, largest~needs 11520 contiguous). Heap too fragmented for STRIP_H=8...`. This is exactly the failure `drivers/strip_renderer.py`'s own `STRIP_H` comment predicted as the next step if 8 ever failed too: "the next lever isn't a smaller buffer — it's making this pool persistent... instead of per-session." It did fail, so that lever is now applied. `free=142784` (139KB) vs. needing one contiguous 11,520B (11.25KB) block confirms this is fragmentation, not a total-memory shortage — consistent with the same class of failure as the eighth issue (seating Bonk's scratch arena at boot claimed another 32KB of what used to be free heap by the time Bonk loads, on top of the timing shift from the SPI/overclock change, apparently enough to tip this already-fragile pool over for good). Fixed: `core/sprite_adapter.py` now has a module-level `_shared_pool` + `seat_shared_pool()`, called from `core/kernel.py`'s `init()` as step 1a — *before* `flash_assets.init()` — since this pool does four separate smaller allocations (not one bump carve) and is therefore the most placement-sensitive thing seated at boot, matching the "acquire hardest-first" rule `games/bonk/game.py`'s `load()` already applied internally. `MainScreenAdapter.open()`/`close()` now attach/detach from this shared pool instead of seating/freeing their own — `close()` no longer calls the pool's `__exit__` (which would free the buffers), only restores the display bus frequency. This is a permanent ~37.5KB heap reservation from boot onward, whether or not Bonk is ever played — the trade-off the docs already called out. **Not bench-confirmed** — needs a full boot + first-load + repeat-load Bonk session on real hardware.
- **Tenth confirmed hardware failure, first real boot after the ninth's fix landed:** `[display] main bg paint failed: /assets/sys/bgm_boot_480x320.bz memory allocation failed, allocating 23040 bytes` — the BOOT SPLASH itself, the very first thing every session ever paints, now failing with `free=133824` (130KB) still available. 23,040B is `ILI9488._blit_scratch` (`drivers/display.py`) — the RGB565→RGB666 band scratch used by `blit_rgb565()` for any full-width main-screen paint, previously allocated lazily on first use and cached thereafter. Its first-ever caller has always been the boot splash, and it used to succeed there without issue. Root cause: the eighth and ninth fixes above added ~70KB of NEW permanent boot-time reservations (persistent strip pool + Bonk's scratch arena) ahead of this scratch buffer's first allocation — apparently enough to fragment what's left just enough to make this modest 23KB *contiguous* request fail, despite 130KB total still free. Same fragmentation class as everything else in this file, just a new victim exposed by fixing the previous one — the boot splash isn't Bonk-specific, so this is the first failure in this whole chain that isn't gated behind ever loading Bonk at all. Fixed the same way: `ILI9488.warm_blit_scratch()` pre-allocates `_blit_scratch` to its largest known size (480×16×3), called from `core/kernel.py` as the very FIRST heap reservation of boot — ahead of even the strip pool and `flash_assets.init()` — since it's now the most fragile allocation of the bunch, not because it's the biggest. **Not bench-confirmed** — needs a full boot on real hardware, ideally with `[display] blit scratch alloc` printing once at boot (from `warm_blit_scratch()`) and never again during a session.
- **Eleventh confirmed hardware failure, immediately after the tenth's fix landed:** `[kernel] bonk failed to load: memory allocation failed, allocating 8192 bytes`, with `unload()`'s own cleanup after the failed load raising the SAME error again. 8192 = exactly 2x `config.AUDIO_BUF_BYTES` (4096) — this is a recurrence of the THIRD confirmed hardware failure earlier in this file (`machine.I2S(..., ibuf=AUDIO_BUF_BYTES)` appears to internally double-buffer its DMA ring), just triggered by `load()` itself this time instead of mid-`run()`. `drivers/audio.py` tears down and rebuilds the I2S peripheral fresh for every single clip played (load-bearing for the MAX98357A's auto-mute behavior — see that file's module docstring), so this 8192B allocation happens on every sound, not once. This time it's failing even at `load()`, meaning the elastic (non-permanently-reserved) heap has gotten measurably tighter — worth naming directly: the eighth/ninth/tenth fixes together added ~130KB of NEW permanent boot-time reservations (Bonk's scratch arena 32KB + the persistent strip pool 37.5KB + the blit scratch 23KB, on top of the pre-existing flash_assets arena 96KB + text scratch 38.4KB) in the space of a few hours, and each one shrinks the flexible pool everything else — including this I2S allocation — has to work with. Rather than adding a TWELFTH permanent reservation to this already-growing pile, applied this failure's own already-documented next lever instead (see the third failure's entry above): halved `config.AUDIO_BUF_BYTES` 4096→2048, so the actual failing allocation drops to 4096B instead of 8192B. Confirmed via grep to have no other production consumer besides `drivers/audio.py` (only two test scripts also reference the constant). **Not bench-confirmed.** If Bonk's `load()` still fails here after this, the permanent-reservation total is very likely now the real ceiling, not any one buffer's size — worth measuring `gc.mem_free()` right before `game.load()` runs and comparing against the ~227KB (post this fix) already permanently spoken for, rather than chasing individual allocation sites further.
- **Twelfth confirmed hardware failure — the predicted ceiling from the eleventh entry's closing note, hit almost immediately:** `MemoryError: memory allocation failed, allocating 32768 bytes`, traceback rooted in `core/kernel.py`'s `init()` calling `games/bonk/game.py`'s `seat_scratch_arena()` directly — **boot itself failed**, before the menu, before any game selection, for every game not just Bonk. By this point in the boot sequence roughly 193KB was already permanently committed (blit scratch 23KB + strip pool 38.4KB + flash-asset arena 96KB + text scratch 38.4KB, from the ninth/tenth fixes), and this arena's own 32KB request was the straw that broke it. This is qualitatively worse than every failure before it in this list — those all left the menu usable and only one game broken; this one blocks the whole app. **Reverted the eighth fix's boot-time seating of `_scratch_arena`** — `core/kernel.py` no longer calls `seat_scratch_arena()` during `init()`. `games/bonk/game.py`'s `load()` still calls it as its own first step (unchanged), so the arena is back to the original lazy-seat-on-first-load design, before the eighth fix's "freshest heap" treatment. The strip pool (ninth fix) was deliberately left as-is — boot got past it fine, and it's the more foundational of the two persistent reservations (Bonk can't function at all without it). Also added `gc.mem_free()` diagnostic prints at every boot-time reservation checkpoint AND right before every `game.load()` call, since this session had run out of informed guesses and needs real numbers, not estimates, for whatever the next failure turns out to be. **This is a course-correction, not a new lever** — the underlying lesson from failures eight through twelve together: converting every fragile lazy allocation into a permanent boot reservation doesn't scale on a heap this tight, and each one traded a recoverable single-game bug for a small step closer to an unrecoverable boot failure. Future fixes on this file should check the new checkpoint prints before reaching for "seat it at boot" again. **Not bench-confirmed.**
- **Thirteenth confirmed hardware failure, on the twelfth fix's reverted (lazy) seating, using the new checkpoint prints for the first time:** Match It! played first, then Bonk selected — `[kernel] heap before bonk.load(): free=56208` then `memory allocation failed, allocating 32768 bytes`. Retried loading Bonk two more times without power-cycling: `free=110816` then `free=124528`, **both still failed on the exact same 32768-byte request.** This is the clearest fragmentation signature in this whole file: free heap rose by nearly 70KB across retries (normal session garbage getting collected) while the specific allocation kept failing regardless — proof this was never a shortage, it's *permanent* fragmentation from the OTHER boot-seated blocks (persistent strip pool, `flash_assets.arena`, text scratch — all seated once and never freed, per fixes nine/tenth's design) acting as fixed, non-moving walls that MicroPython's non-compacting GC can never route around, no matter how much unrelated garbage gets collected elsewhere. **Reinstated boot-time seating for `_scratch_arena` (reversing the twelfth fix), but reordered to go FIRST** among the boot-time reservations — before the blit scratch, strip pool, `flash_assets.init()`, and text scratch — instead of last (where it failed the twelfth time). Rationale: at 32KB it's comparatively small, so seating it before the four larger/harder blocks get a chance to carve up the heap gives it the best odds of landing in one contiguous run while the heap is most virgin; the larger blocks (especially `flash_assets.init()`'s 96KB, the single biggest) then get whatever's left. **This is a genuinely different bet than the twelfth failure's ordering**, informed by the checkpoint prints added there — if `flash_assets.init()` fails after this reorder, that's the signal total capacity (not ordering) is the real ceiling, and the next lever has to be shrinking something's size (`SPRITE_BUDGET` or `STRIP_H`), not reordering further. **Not bench-confirmed.**
- **Fourteenth confirmed hardware failure, first boot after the thirteenth's reorder — confirms the reorder alone wasn't enough:** with the checkpoint prints in place, boot got much further this time — `[kernel] heap after bonk scratch arena: free=310816` → `after blit scratch: free=287664` → `after strip pool: free=248976` → `after flash_assets arena: free=150592` — all five reservations that failed last time succeeded, in the new order. Then `warm_text_scratch()`'s 38,400B "GO!" buffer failed anyway, with **150KB nominally free.** This settles the question the thirteenth entry left open: it is NOT ordering. Five large contiguous blocks totaling ~227KB genuinely do not co-exist on this heap regardless of arrangement — reordering just moves which specific allocation is the one left without a large-enough gap, it doesn't create more total contiguous room. Continuing to reorder would be whack-a-mole forever. Fixed by reducing actual demand instead: `config.COUNTDOWN_TEXT_SCALE` (new constant, was two independently hardcoded `10`s — one in `core/game_base.py`'s `_COUNTDOWN_SCALE`, one in `core/display_manager.py`'s `warm_text_scratch()` — now a single shared source of truth so they can't silently desync) dropped from 10 to 7, shrinking the "GO!" out buffer from 38,400B to 18,816B — roughly half the single largest remaining contiguous ask in the boot sequence. Countdown text is still large/dramatic on a 480×320 screen, just not the maximum possible size. **This is the first fix in the eighth-through-fourteenth chain that reduces total footprint rather than relocating or reordering it** — the checkpoint prints made it possible to actually confirm that's what was needed instead of guessing. **Not bench-confirmed.** If this still fails, the next levers in order of likely impact: shrink `SPRITE_BUDGET` (currently 96KB; Bonk's own 4 sprite sheets only need ~74KB of it) toward actual peak usage, or apply the same "reduce, don't relocate" treatment to `STRIP_H`/the persistent strip pool.
- **Fifteenth confirmed hardware failure — boot succeeded fully this time (all five reservations fit, confirming the fourteenth fix worked), but two NEW problems surfaced downstream:** (1) Match It! crashed mid-`run()`: `memory allocation failed, allocating 8192 bytes`. This is a repeat of the third confirmed failure's symptom, but with new evidence that overturns that entry's theory: `AUDIO_BUF_BYTES` was already halved 4096→2048 by the eleventh fix, yet the failure is STILL exactly 8192, not the ~4096 the "I2S internally doubles ibuf" theory would predict. That means `machine.I2S`'s real internal allocation is very likely a FIXED floor (~8192B), not one that scales down with a smaller requested `ibuf` — the eleventh fix's config change never actually addressed the real allocation size. Fixed by adding `gc.collect()` immediately before every `machine.I2S(...)` construction in `drivers/audio.py`'s `_make_i2s()` (both `_play_wav()` and `_play_synth()` route through it) — same "defrag right before the fragile fixed-size ask" pattern already used by `StripBufferPool`. (2) Bonk's score/end screen never appeared after the last round — total console silence, required a manual `Ctrl-C` to recover (interrupt landed in `wait_io_event`, not a printed exception). Traced to `drivers/audio.py`'s `_stream()`: it awaited `evt.wait()` (the I2S DMA-drain IRQ event) with **no timeout at all** — if that IRQ ever doesn't fire (a missed/dropped interrupt), the coroutine hangs forever with zero output, and since `play_sfx(wait=True)`/`play_voice(wait=True)` await that same task, a stuck drain silently freezes the whole game loop. This is a plausible-but-not-certain root cause for the specific symptom (total silence + forced interrupt matches an unbounded-await hang exactly), not a confirmed one. Fixed by wrapping that wait in `asyncio.wait_for(evt.wait(), 1.0)` — a generous bound given a chunk drains in ~46ms under normal playback — and treating a timeout as "cut the clip short, print one diagnostic, keep going" rather than hanging. `_guard()` (already wrapping every playback task) catches and logs whatever this raises, so the fix composes with existing error handling rather than needing new plumbing. **Neither fix is bench-confirmed.**
- **`StripRenderer`'s blocking transmit path does not take `spi_bus`'s lock** — it writes to `spi_bus.spi` directly, bypassing the `device()`/`raw()` serialization every other SPI0 consumer uses. **Originally reasoned safe for Bonk because "audio never touches SPI0" — this was wrong and caused a real bug.** `_bonk_feedback()`'s hit sound was fire-and-forget; `correct.wav` has no Tier B audio baked for this game, so it resolves via the `/sd/audio/sfx/` fallback, and SD *does* share SPI0 with the displays. The fire-and-forget clip's SD file read could run concurrently with the next target's unlocked `render_dirty()` write — two unlocked SPI0 writers racing — and this reproduced on hardware as screen tearing exactly when the next target appeared. Fixed in `games/bonk/game.py`'s `_bonk_feedback()`: the audio call is now `await`ed (not fire-and-forget) so it can't overlap the next render; LED and haptic stay fire-and-forget since neither touches SPI0. The lesson generalizes: "doesn't touch SPI0" needs verifying per-clip against actual resolution path (Tier B/flash vs SD fallback), not assumed from the call site. **Still a real hazard for any future game using `SpriteEngine.start()`'s continuous background tick loop** concurrently with anything else touching SPI0 — that combination hasn't been reasoned through and shouldn't be assumed safe.
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
- **Star Bonk (`games/bonk`) confirmed playable end-to-end on real hardware** — user report: "ok everything works." Five memory/allocation bugs (three StripBufferPool seatings at STRIP_H 32→16→8, one mid-gameplay audio-driven MemoryError, one button-legend-arena MemoryError fixed by making that arena persistent, one text-scratch-buffer MemoryError from the scale-10 countdown fixed by warming it at boot — see entries above) are bench-confirmed fixed, including a repeat play session in the same power-on run. Also confirmed: no more screen tearing on hit sounds, stars/high-score tracking, big countdown numbers/GO!, live touch detection, white legend tiles, and the result-screen score+star overlay (both Match and Bonk). The real board art (`bg_bonk_480x320.bz` at `strip_h=8`) is confirmed in the loop, not just the `_FlatBackground` placeholder. **Regression found immediately after this "everything works" report:** repeat play ("Play Again" without returning to the menu) corrupted the wizard/goblin sprites — the sixth confirmed issue above (shared-arena corruption from the new `RESULT_PATH`/tile paints added in the same round of fixes that produced the "everything works" report). Fixed, but that specific repeat-play path needs re-confirming on hardware — it was passing before the result-screen changes landed, so it's plausible other things this section calls "confirmed" were only exercised on a *first* playthrough.

Outstanding:
- **Internal flash (littlefs) budget, measured with both Match It!'s and Star Bonk's permanent Tier A assets installed:** 843,776 bytes free (~0.80 MB) of the RP2350's 4MB flash, via `tools/free_space.py` (`os.statvfs('/')`). An earlier reading (651,264 bytes / ~0.62 MB) was taken with some stray Tier B (SD-installed-per-load) assets still sitting on littlefs from prior testing — this corrected number is after clearing those leftovers. `core/kernel.py` does call `game_cache.evict(game.GAME_ID)` on every in-app exit path (normal completion, mid-game BACK, and a crashed/failed `load()` or `run()` — all fall through to the same cleanup block), so stray Tier B files aren't a missing-evict-call bug; they only survive a full power loss or firmware reset mid-session, before that cleanup ever runs — plausible given this session's MemoryError history. Worth re-checking after each new game's Tier A assets land — this ~0.80 MB is the ceiling on how much permanent (always-resident) art/audio future games can add before it becomes the binding constraint, separate from the RAM/heap-fragmentation issues documented above.
- Asset pipeline: family photos → stylised art → RGB565 conversion.
- Family voice recording sessions for "My Big Day Out".
- 3D-printed shell design.
- Battery voltage/percentage via GP29/ADC3 (VSYS monitor — see below) — driver written, not yet bench-tested. TP4056 charger wiring still pending separately.
- Remaining games in the library (Button Memory next).

## Battery Monitoring — Design Change (Not Yet Bench-Confirmed)

The original plan ("Battery ADC signal → MCP23008 GP5") was never actually workable: the MCP23008 is a pure digital I/O expander with **no ADC capability at all** — it could only ever have given a HIGH/LOW flag, never a real voltage or percentage. This was caught before any wiring was done, not after a failed attempt.

Replacement: the Pico 2 W's own native VSYS monitor, read via **GP29/ADC3**, needing zero new components. GP29 shares its physical pin with the CYW43439 wireless chip's SPI CLK line — reading it mid-SPI-transaction to the wireless chip would give garbage — but this firmware **never imports `network` or uses `WLAN` anywhere** (confirmed via grep across the whole codebase), so that conflict never actually arises here. **GP25** (the wireless chip's CS-equivalent line) is still held HIGH before every read as cheap insurance, matching the documented technique for this board family.

Important distinction from every other "confirmed" pin in this file: `config.py`'s prior "GP23/24/25/29 — WiFi internal, never connect anything" note was **inherited caution from general Pico W guidance, not an actual observed hardware failure** — user confirmed GP29 was never wired or tested before now. So unlike GP5 (measured -4.2mV, genuinely dead) or the other bench-confirmed pins in this file, this is a deliberate, reasoned departure from a blanket precaution, not a correction of a real prior failure.

Added:
- `tests/test_16_battery_vsys.py` — standalone bring-up test, prints raw ADC + computed voltage + percentage every 2s for 30s. **Run this first**, cross-check the printed voltage against a multimeter reading of the actual battery/VSYS rail.
- `drivers/battery.py` — production `BatteryMonitor` driver (`read_voltage()`, `read_percent()`, `.low` property), following the same style as `drivers/haptic.py`. **Not wired into `core/kernel.py`'s boot sequence or any menu/UI** — deliberately left as a standalone, opt-in driver until the bring-up test confirms real numbers on this board. Given how many boot-time RAM fixes this session already needed, adding an unconfirmed new driver to the boot path wasn't worth the risk before it's actually verified.
- `config.py`: `PIN_BAT_ADC=29`, `PIN_WIFI_CS=25`, `VSYS_ADC_RATIO=3` (the widely-documented Pico-W-family divider ratio — **not yet measured on this specific board**, first thing to adjust if the test's printed voltage is off).

**Next step on the bench:** run `test_16_battery_vsys.py` with the battery connected to VSYS/GND, compare the printed voltage to a multimeter reading. If they match, `drivers/battery.py` is ready to wire into the menu (battery icon/percentage display) as a follow-up. If they don't match, adjust `VSYS_ADC_RATIO` first.

**✓ Bench-confirmed, and the divider ratio was wrong as documented:** first real run printed `raw=27462  voltage=4.15V  ~94%` repeatedly (avg raw ≈27520 across 15 samples), while a multimeter on the battery directly read **3.45V**. The widely-documented Pico-W-family VSYS divider ratio of 3 (used in the initial `VSYS_ADC_RATIO`/`DIVIDER` value) was simply wrong for this board — solving for the real ratio from that data point gives ≈2.49, not 3. This is not a small correction: at the configured `BAT_FULL_V=4.2`/`BAT_EMPTY_V=3.3`, the wrong ratio reported ~94% charge for a battery actually at **~17%** — right next to the `BAT_WARN_PCT=15` low-battery threshold. A kids' device silently reporting "plenty of charge" at what's actually a near-empty battery is exactly the kind of thing this bring-up discipline exists to catch before it ships. Updated `config.VSYS_ADC_RATIO` to `2.49`, and the matching constant in `tests/test_16_battery_vsys.py`, to the bench-confirmed value. **Caveat: calibrated from a single data point** (one voltage level, ~3.45V) — the divider itself should be linear (a passive resistor network), but a second check at a meaningfully different charge level (e.g. after a full charge to ~4.2V) would confirm that holds across the whole range rather than just near where it was measured. `drivers/battery.py` is now ready to wire into the menu/UI as a follow-up, still pending that second confirmation point.

**Second calibration point, after charging — reveals real (not just rounding) disagreement between the two points:** multimeter read 3.71V after charging; `test_16_battery_vsys.py` printed a stable cluster around `raw≈28257` (avg of 15 samples), computing to 3.63-3.71V depending on ratio. Solving each point independently: point 1 (3.45V) implies ratio ≈2.49; point 2 (3.71V) implies ratio ≈2.61 — a ~4.7% spread, not just measurement rounding. Likely cause: LiPo cells commonly show "surface charge" for 10-15 minutes right after charging — a real but transient voltage elevation that settles to the true resting voltage — so if the multimeter reading and the ADC sample weren't taken at exactly the same moment relative to that settling, the two "true" voltages being compared may simply not have matched, independent of anything wrong with the divider math. A proper zero-intercept least-squares fit across both points gives `VSYS_ADC_RATIO ≈ 2.55`, still leaving ~±0.08V residual error at each point — updated `config.py`, the test script, and `drivers/battery.py` to this value. **This is treated as "good enough for a coarse battery indicator," not a precision gauge** — for a kids' console showing roughly-full/roughly-low, ±0.08V (a few percentage points) is an acceptable margin; it would not be acceptable for anything requiring an exact reading. To tighten further: let the battery rest 15+ minutes after any charging before taking a reference reading, take the multimeter and test-script readings as close together in time as possible, and get a third calibration point further from these two (e.g. near `BAT_EMPTY_V` ~3.3V) so there's an actual spread to fit a line against instead of two closely-spaced points.

## Power Architecture — Charging + 5V Rail (PLANNED, NOT YET WIRED)

Two separate problems surfaced during battery bring-up, and the fix for both got combined into one power architecture design:

**Problem 1 — VBUS-fed loads go silent/dim on battery-only power.** User reported audio quality degraded on battery power ("not great"), root-caused to the MAX98357A's VIN being wired directly to **VBUS** — confirmed by the user, not assumed. VBUS is a physical pin fed *only* by USB; it has zero power when running on battery alone, regardless of VSYS/battery state. User also confirmed the WS2812B LED strip has the *identical* symptom (dim/off on battery) — `config.py` already documented "Strip powered from VBUS (5V)" for the LEDs, so this is the same root cause hitting two subsystems, not two separate bugs. The 74AHCT125 level shifter's own VCC is *not* on VBUS (user confirmed) — only the strip's actual power feed and the amp's VIN need to move.

**Problem 2 — raw battery wired directly to VSYS risks backfeed.** Surfaced earlier in this same bring-up session: official Raspberry Pi guidance explicitly warns that connecting a battery straight to VSYS needs its own series diode, because the Pico's onboard VBUS→VSYS Schottky diode only protects USB from backfeed, not the other direction. With USB connected and a bare battery on VSYS, current can push backward into the raw LiPo with no current limiting — not how you want to treat a kids'-device battery repeatedly.

**Combined design** (user has an MT3608 2A boost module — 2-24V in, 5-28V adjustable out — and is fine adding a dedicated USB-C charging port to the shell, with the Pico's own micro-USB tucked behind a removable cover for dev/firmware work only):

```
Battery+/- ──→ TP4056 BAT+/BAT-
TP4056's own USB-C (charging input) ──→ dedicated charging port on the shell
                                         (separate connector from the Pico's own USB)

TP4056 OUT+ (protected, through its DW01) ──→ [master ON/OFF switch] ──┬──→ MT3608 IN+ → 5V_REG
                                                                       │        → MAX98357A VIN (was VBUS)
                                                                       │        → WS2812B strip power (was VBUS)
                                                                       └──→ [new] Schottky diode (1N5819, on hand) ──→ Pico VSYS
All grounds shared common.
```

Reasoning for each piece:
- **The master switch moved here from its original planned spot ("SPDT slide switch on the 3.3V regulated rail").** That original placement was downstream of the Pico's own onboard 3.3V regulator, so it could only ever have power-cycled the Pico itself — the MT3608 branch (audio + LEDs) draws independently from TP4056's output and would have stayed live regardless, meaning "off" wouldn't actually stop the device from drawing on the battery. Moving the switch to before the MT3608/VSYS split makes it a real master off — one switch, whole system, matching what "off" should mean on a battery-powered kids' device.
- **Everything downstream draws from TP4056's protected output, not the raw cell** — DW01's over-discharge/over-current protection now covers the whole system's draw (audio, LEDs, the Pico itself), not just the charge cycle.
- **The new diode between TP4056's output and VSYS is what actually closes Problem 2.** TP4056+DW01's protection MOSFETs pass current through in *normal* operation (protection only cuts off in abnormal conditions) — so even with TP4056 in the loop, VSYS being pushed higher (e.g. by the Pico's own dev-USB port connected at the same time as the battery) could still find a path back through TP4056's normal pass-through into the cell. The diode blocks that specific remaining path. Reduced-but-not-eliminated risk in practice now that the Pico's port is behind a cover and not a normal-use connector, but the diode is the actual fix, not the cover — a kids' device shouldn't rely on "nobody will plug it in wrong."
- **The MT3608 taps TP4056's OUT+ directly**, before the new diode, so the diode's forward-voltage drop doesn't eat into the boost converter's input headroom — the diode's only job is protecting the VSYS/Pico-USB path specifically.
- **MT3608 output MUST be set to a clean 5.0V with a multimeter, with nothing connected to its output yet, before wiring anything to it** — this module ships with output voltage unset via an onboard trimpot, not defaulting to 5V. Skipping this step risks overvoltage damage to the MAX98357A (~5.5V max VIN) and the WS2812Bs.
- **Charge current** on the TP4056 (set by its programming resistor) should suit the 1200mAh cell specifically — many modules default to ~1A, which is a more aggressive rate (~0.83C) for a 1200mAh pack than for whatever capacity the module's default resistor was chosen for. Confirm the module's actual configured current before relying on it.
- **Possible follow-up, not yet observed:** the amp and LEDs now share one switching-regulator supply (the MT3608) — watch for audible whine/buzz synced to LED activity once wired up. Not expected to be severe given the 2A rating, but a known class of issue with shared switching supplies; a second small boost converter just for the LEDs (or an LC filter on the audio supply) would be the fix if it shows up.

**Nothing above is wired yet.** This is a design captured for reference, not a confirmed build — every numbered step needs the physical wiring done and bench-verified (especially the MT3608 output-voltage-before-connecting-anything step, which is a real overvoltage risk if skipped) before any of this can move from "planned" to "confirmed" in this file.
