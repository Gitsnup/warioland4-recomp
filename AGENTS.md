# WarioLand4Recomp — project notes

Native static recompilation of Wario Land 4 (USA) for Linux desktop and
Android arm64. Built on mstan's gbarecomp engine. Run `README.md` for the
full architecture; this file records decisions and machine-specific facts.

## Current state (v0.1.0 — public repo: github.com/Gitsnup/warioland4-recomp)

- **v0.1.0 — GitHub public repo + CI.** Repo ships NO ROM, NO BIOS dump,
  NO compiled artifacts (see .gitignore). Vendored forks (their .git
  parked out of tree): gbarecomp (mstan) with our runtime integration,
  recomp-ui (mstan), decomp (lilDavid/warioland4). decomp/tools/agbcc
  and decomp/build are gitignored (clone agbcc separately to rebuild
  the decomp; not needed for the recomp build). GitHub Actions
  (.github/workflows/build.yml): desktop Linux build + generated-header
  idempotence check + Android arm64 debug APK (ROM-less; first-run
  setup asks for the dump). versionCode 10.
- **v0.1.0 — built-in gameplay Tweaks section (in-game settings).**
  Binary patch sets applied to the in-memory ROM copy at boot (same
  path as content mods; dump stays pristine, applies next launch,
  selections shared in selections.toml). Registry:
  gbarecomp/src/runtime/runtime_tweaks.{h,cpp} + generated
  tweaks_patches.h. Two tweaks: (1) tweak-gp-slope-roll — ground-pound
  onto a slope tile flows into a roll: helper thumb body
  (tools/tweaks/gp_slope_roll.s, linked AT 0x08354408 via ld -Ttext —
  assembling without linking mis-encodes the BL) installed in the
  all-zero gap at ROM 0x354408..0x355200, entry hook 0x08011898
  rewritten to ldr r3,[pc,#8]; bx r3 with the pool word repurposed;
  helper reloads gWarioData after func_806DAC0 (clobbers r2) and
  branches on the HIGH halfword of the return ((overridden<<16)|type —
  matches every in-game caller). (2) tweak-turbo-movement —
  func_8010554 accel/decel steps doubled (6 halfword sites, orig bytes
  verified). Generator: tools/wl4_tweak_gen.py verifies every site's
  original bytes + helper-span zeroness (non-vacuous: length-checked)
  + BL target == 0x0806DAC0 + probe VA pool word before emitting the
  header; run it after editing the .s. Headless verify: both tweaks
  apply, boot clean (unmapped=0, render stats identical to baseline).
- **v0.0.9 — Android mods dir is root-accessible.** Internal storage
  (/data/data/<pkg>/files) is opaque without root, so on Android a relative
  `content_mods_dir` is redirected to the app's EXTERNAL files dir
  (Android/data/<pkg>/files/mods — readable over USB/MTP and by most file
  managers). mobile_platform.cpp advertises it as GBARECOMP_EXTERNAL_DIR
  when read+write are granted; runtime.cpp redirects only relative paths and
  create_directories() the target, so desktop behavior is unchanged. The
  setup screen shows the exact mods path under the privacy line, and the
  Mods section's "Export starter templates" description embeds the real
  root. `modsDirPath()` in GbaSetupActivity mirrors the same path. The
  extractReleaseNativeSymbolTables task is disabled (app/build.gradle):
  multi-GB RAM spike, useless for side-loaded APKs.

- **v0.0.8 — content mods (soundfonts / Wario skins), desktop-verified.**
  Player-owned mods live in `mods/` beside the binary (`opts.content_mods_dir
  = "mods"` in src/main.cpp). Each mod = folder with `mod.toml` (id/name/
  kind: soundfont|skin|patch), optional `patch.binpatch` (lines
  `ROM-address=hexbytes`, applied to the in-memory ROM copy after SHA-1
  verification — the dump stays pristine), optional `palette.txt` (lines
  `bg|obj <slot> <16 BGR555 halfwords>`; re-applied EVERY frame at the frame
  boundary so they survive the game's LZ-decompressed palette reloads and
  fades — WL4 palettes are compressed at rest, so ROM patching is not viable
  for recolors). Engine: `gbarecomp/src/runtime/content_mods.{h,cpp}`
  (scan/load_selections/apply_selected/export_templates; selections persist
  in `mods/selections.toml`, apply at next launch). In-game Mods settings
  section lists one toggle per mod + "Export starter templates" action that
  writes `mods/templates/{soundfont-template,wario-skin-template}` (each:
  mod.toml + patch.binpatch + README explaining the workflow). Tooling:
  `tools/wl4_mod_tools.py` — `find-samples` (MP2K song-table walk → every
  instrument/sample record with ROM offsets), `wav2patch` (WAV → patch line,
  PCM8/16 + rate), `scan-palettes` (ROM static scan — mostly fruitless
  because palettes are compressed), `scan-palette-ram <dump>` (the working
  path: run with `--dump-palette`, scan the live dump for the subpalette +
  slot, write a palette.txt override). Verified: test skin with red BG slot
  0 override landed in palette RAM (dump diff) and changed 2,586 px of the
  title render vs base run; find-samples maps 15 song-1 tones. Headless
  palette application is gated on PPU frame-count change (NOT per dispatch —
  an earlier draft applied per step_once() = millions of memcpys/frame).

- **Headless input injection (`--press`):** frame-indexed synthetic
  KEYINPUT for verification scripts (`--press 100:start` skips the boot
  intro and lands on the title screen; see the recipe at the bottom).
  Reference screenshot `docs/screenshot-title-no-bios.png` is the true
  title screen now — the old one was the *intro* (crescent moon + night
  sky), which looks similar but is not skippable-by-waiting.
- **v0.0.7 — in-level widescreen (the "black margins" fix).** v0.0.6 widened
  the guest but margins rendered black inside levels: with no tilemap provider
  the PPU margin path memsets black, and the level-select rooms (entry/death
  scenes) only looked wide because their full-map draws filled the ring. Root
  mechanism, for the record: with no provider, margin rows fail closed
  (`render_scanline_wide` early-out); WL4's window setup (func_806B3E8) sets
  WINOUT=0x3F + WIN1=HUD(0x20), so once the *true* margin tiles are supplied
  they render everywhere except the HUD strip. Fix: new WL4-specific margin
  provider `gbarecomp/src/debug/ws_wl4_margins.cpp` — reads each BG layer's
  FULL room map (gBackgroundInfo @0x03000054: per layer {u16* data; u16 w;
  u16 h}, indexed [y*w+x]) + per-layer world camera (u16 subpixels, px=>>2;
  gBg1XPosition @0x0300187A and friends — see file header for the address
  map from decomp func_806C828/func_806F4BC) and returns the true world tile
  entry for columns outside the native 240. Installed via
  `opts.extended_view_init` in src/main.cpp (fires once when the view first
  expands). Off-room margins stay black (backdrop), not ring-seam garbage.
  Screen shake shifts margins ≤shake/8 px transiently (world cams exclude
  shake; registers include it).
- **v0.0.6 — Native fill = Sonic-Origins-style widescreen.** Picking fit mode
  2 widens the *guest itself*: `runtime_ui_set(SCREEN_FIT)` maps fit 2 →
  `RECOMP_RUNTIME_UI_VIEW_ADAPTIVE` (+ `view_mode_dirty`), and any other fit
  maps back to `VIEW_NATIVE`. The engine's resize-driven path then computes
  `resize_driven_view_geometry` — height locked at the authentic 160 lines,
  width = display aspect (capped by `opts.max_resize_view_width = 480`, set
  in src/main.cpp; WL4 does NOT use Density sizing, so tablets don't grow
  vertically). No ROM change — same hash, pure runtime. The pre-existing
  host-side crop-fill branch in host_window.cpp only runs as a fallback for
  non-opted-in games now.

- **v0.0.3 crash fix (Android 15+):** all packaged .so files were 4KB page
  aligned; Android 15 devices require 16KB alignment or the loader kills the
  process instantly (also matched the 0.0.1 symptom). Fix:
  `cmakeArguments: ["-DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,max-page-size=16384"]`
  in android/app/build.gradle. Verified: readelf LOAD segments = 0x4000 on
  libmain/libSDL2/libc++_shared. NOTE: the SDL2 CMake builds it as SHARED
  with the same linker flags, so the flag covers it too.
- **v0.0.3 also fixed** android/game_android.toml asset paths: it now uses
  `../../bios/gba_bios.bin` / `../../roms/warioland4_usa.gba` (staged under
  files/variants/warioland4/ at runtime; previously pointed one level short,
  so ROM resolution would fail even without the loader crash).

- **App icon (v0.0.5):** adaptive launcher icon built from the Wario Land 4
  box art lives in `android/app/src/main/res` (mipmap-anydpi-v26 + legacy
  PNGs at all densities + `values/ic_launcher_background.xml`). The engine
  res dir (`gbarecomp/platform/android/res`) never had an icon; the game
  res dir is the sole source. minSdk is 28, so adaptive icons always apply.
- **ROMs are NOT kept in `roms/`** (freed 16 MB). The only copy is
  `decomp/baserom_us.gba` (needed by the decomp build anyway). Root
  `game.toml` points there; `[save].path` explicitly targets
  `roms/warioland4_usa.sav` so desktop saves survive. Variant TOML uses
  `../../decomp/baserom_us.gba`. For APK builds pass
  `-PprivateRom=$PWD/../decomp/baserom_us.gba`. `roms/` now only holds the
  desktop save file.
- **BIOS is optional.** The runtime boots from an embedded synthetic BIOS
  stub when no dump is supplied. Stub source: mGBA `src/gba/hle-bios.s`
  (MPL-2.0), assembled to `gbarecomp/src/gba/hlebios_bytes.h`
  (`xxd -i`). The only edit vs upstream: the `swieq 0xF00000` mGBA-internal
  call was replaced with `moveq r11, r11` (engine has no stall-count hook).
- BIOS-less boot forces `bios_hle` + skips the Nintendo-logo intro check
  (the logo compare reads BIOS bytes that aren't there). See
  `runtime.cpp` around `no BIOS dump available`.
- `args.bios_stub` flag (runtime.cpp) drives `GbaBios::install_synthetic_stub()`.
- Desktop binary runs from repo root with no args: root `game.toml` is a
  shim with repo-relative paths pointing at `roms/` + `bios/`. The variant
  TOML (`variants/warioland4/game.toml`) uses `../..`-relative paths because
  the Android build stages it deeper. Keep both in sync when editing.
- Android: `biosRequired: false` (app/build.gradle) — setup screen treats
  the BIOS as optional. v0.1.0 = versionCode 10.
- v0.0.4 added the settings features: screen-fit modes (0=None,
  1=Stretch, 2=Native full-res, 3=Custom ×N) under Display, Color screen
  (0-4), and MP2K split mute — Music/SFX toggles enforced at the engine
  level via the song table (`src/wl4e_song_classes.h`, generated from
  `decomp/include/sound.h`; 566 songs, 8 players). Graphics tab merged
  into Display in the launcher UI.
- ROM SHA-1 (USA): `b9fe05a8080e124b67bce6a623234ee3b518a2c1`
  (md5 `5fe47355a33e3fabec2a1607af88a404`).

## Building on this machine (Debian 12, 4 GB RAM, 3 cores)

- **Desktop:** needs `libsdl2-dev`. Build:
  `cmake --build build-desktop --target WarioLand4Recomp -j 2`.
  First-time configure was already done (build-desktop/ exists).
- **Android:** SDK lives in `/home/workspace/.cache/android-sdk`
  (cmdline-tools + platform-35 + build-tools 34 + NDK 27.1 + cmake 3.22.1),
  Gradle caches in `/home/workspace/.cache/gradle`. Container resets (apt
  packages, /opt, /tmp) are wiped on restart — the .cache dir persists.
  Rebuild:
  ```bash
  export ANDROID_HOME=/home/workspace/.cache/android-sdk
  export GRADLE_USER_HOME=/home/workspace/.cache/gradle
  cd android && sh gradlew assembleRelease -PgbaNativeJobs=2 \
      -PprivateRom=$PWD/../roms/warioland4_usa.gba
  ```
- **Memory is tight:** gradle.properties is capped at `-Xmx1400m` +
  `parallel=false` for a reason. Default `gbaNativeJobs` is 8 → instant
  OOM-kill on this box. Keep `-PgbaNativeJobs=2` (or 1).
- Output: `android/app/build/outputs/apk/release/warioland4-<ver>-release-PRIVATE-rom-included.apk`,
  copied to repo root as `WarioLand4-Recomp-v<ver>-arm64.apk`.
- Another Zo conversation compiles Rust (touchHLE) concurrently sometimes;
  it eats 1.5-2 GB. If the gradle link step OOM-dies, wait for it to finish
  and rerun — compiled objects stay cached in android/app/.cxx.

## Known quirks

- Self-heal native recompile of the three BIOS-stub PCs
  (0x40, 0x184, 0x194) fails: generated C references `g_runtime_resume_pc`
  without an extern decl. Harmless — the interpreter bridge covers those
  PCs and the game runs fine. Fix would go into the shard generator
  (`arm-recomp-core`), not the runtime.
- The 9p filesystem here can serve stale file contents after host
  restarts. If a build "doesn't see" an edit, re-check the file with
  grep, then `touch` it (fresh inode) and rebuild.

## Verification recipe (headless, no display)

```bash
./build-desktop/WarioLand4Recomp --no-window --frames 260 --tcp 0 \
    --press 100:start --dump-png /tmp/verify.png
```
Expected: `boot` line, no `unmapped`, and a PNG of the Wario Land 4 title
screen ("PUSH START" over the car/night-sky scene). Reference:
`docs/screenshot-title-no-bios.png`.

NOTE: without the press the dump shows the *intro* (crescent moon + night
sky), not the title — the intro must be skipped with one START press. Use
`--press <frame>:<buttons>[:<hold>]` for frame-indexed headless input
(button names a,b,select,start,up,down,left,right,l,r, comma-separated;
frames counted from runner start, hold defaults to 3 frames).
