# WarioLand4Recomp — native static recompilation of Wario Land 4 (GBA)

[![build](https://github.com/Gitsnup/warioland4-recomp/actions/workflows/build.yml/badge.svg)](https://github.com/Gitsnup/warioland4-recomp/actions/workflows/build.yml)

A native Linux / Android port of **Wario Land 4 (USA)** built with
[mstan's gbarecomp](https://github.com/mstan/gbarecomp) static recompilation
toolkit and the [lilDavid/warioland4](https://github.com/lilDavid/warioland4)
decompilation.

The guest code is **not emulated**: all 4,086 ARM7TDMI functions of the
commercial ROM are translated once into native C++ by `gba_recompile`
(4,080 THUMB + 6 ARM), compiled into the host binary, and dispatched through
generated jump tables. The decompilation supplies verified function names and
boundaries for the 588 symbols it covers so the recompiled source reads like
the game's real source. The original 8 MiB ROM is never shipped or emulated.

```
┌─────────────┐   md5/SHA-1/CRC32    ┌──────────────────────────────────────┐
│ user's ROM  ├─────────────────────►│ tools/regen.sh                       │
│ (8 MiB)     │   identity gate      │  1. verify ROM identity              │
└─────────────┘                      │  2. stamp SHA-1/CRC32 into configs   │
┌─────────────┐                      │  3. build wl4-decomp with agbcc      │
│ wl4-decomp  ├──┐                   │     (md5 must match retail: byte-    │
│ (decomp)    │  │  4,086 verified   │     perfect ELF → .gba → .md5 OK)    │
└─────────────┘  │  symbols          │  4. import symbols + boundaries      │
                 └──────────────────►│  5. gba_recompile → generated/*.cpp  │
                                     └──────────────┬───────────────────────┘
┌─────────────┐   engine (C++)                     │ native C++
│ gbarecomp   ├◄───────────────────────────────────┤
│ + recomp-ui │  runtime, PPU, APU, save, input    ▼
└─────────────┘                        WarioLand4Recomp (desktop exe)
                                       libmain.so + APK (Android)
```

## What is in this repo

| Path | Contents |
| --- | --- |
| `gbarecomp/` | mstan's gbarecomp engine (recompiler, runtime, Android shell) |
| `recomp-ui/` | shared Dear ImGui pre-boot launcher |
| `decomp/` | lilDavid's Wario Land 4 decompilation (agbcc submodule) |
| `variants/warioland4/game.toml` | desktop runtime + recompiler config |
| `variants/warioland4/generated/` | recompiled guest code (built by regen) |
| `variants/warioland4/symbols/` | decomp symbol overlays (built by regen) |
| `android/` | Gradle project for the Android APK |
| `tools/regen.sh` | full Linux pipeline (the only button) |
| `roms/`, `bios/`, `saves/` | user-supplied content — never committed |

## Requirements

- Linux with 3+ GB free RAM (build compiles ~12 MB C++ TUs), 20 GB disk
- `gcc`, `cmake`, `python3`, `java` (17), `git`
- `binutils-arm-none-eabi` (decomp linking)
- `libsdl2-dev` (desktop window/launcher)
- Android: SDK platform 35, build-tools 34, NDK 27.1, CMake 3.22.1

## Legal note

This repo contains **no copyrighted data**. You must provide:

1. Your own legally dumped **Wario Land 4 (USA)** cartridge image
   (md5 `5fe47355a33e3fabec2a1607af88a404`), placed at
   `roms/warioland4_usa.gba`
2. *(optional)* A GBA BIOS dump (sha1
   `300c20df6731a33952ded8c436f7f186d25d3492`), placed at
   `bios/gba_bios.bin`. Without one the runtime boots from an embedded
   synthetic BIOS stub (mGBA's hle-bios.s, MPL-2.0): vector table, an
   SWI dispatcher, and an IRQ wrapper. Intro logo playback is skipped
   and `bios_hle` boots the game directly.

Every stage hash-verifies identity before proceeding. The APK build refuses
to embed a ROM/BIOS whose SHA-1 doesn't match, and a public build made
without `-PprivateRom`/`-PprivateBios` embeds neither.

## Build (Linux desktop)

```bash
tools/regen.sh --jobs 3
cmake -S . -B build-desktop -DCMAKE_BUILD_TYPE=Release
cmake --build build-desktop -j3            # guest shards compile serially
./build-desktop/WarioLand4Recomp
```

Headless verification without a window:

```bash
./build-desktop/WarioLand4Recomp --no-window --frames 600 --tcp 0
```

## Build (Android arm64 APK)

```bash
export ANDROID_HOME=/opt/android-sdk
cd android
sh gradlew assembleRelease \
    -PprivateRom=$PWD/../roms/warioland4_usa.gba \
    -PprivateBios=$PWD/../bios/gba_bios.bin
# → android/app/build/outputs/apk/release/app-release.apk
```

Landscape-locked, touch + gamepad input, SRAM saves in app-private storage.

## Building without a ROM dump (CI-friendly)

Both CI jobs and plain local builds work with **no ROM and no BIOS** on disk:

- Desktop: `cmake -S . -B build && cmake --build build` — the binary boots
  from an embedded synthetic-BIOS stub and asks for the game dump on first
  run (SHA-1 verified, dump stays pristine).
- Android: `cd android && ./gradlew assembleDebug` — the debug APK ships no
  copyrighted data; the first-run setup screen collects the dump (and
  optionally the BIOS).

Private/personal APKs that embed your own dump build with `-PprivateRom=` /
`-PprivateBios=` as shown above — never distribute the result.

`tools/wl4_tweak_gen.py` regenerates the gameplay-tweak patch table
(`gbarecomp/src/runtime/tweaks_patches.h`) from `tools/tweaks/*.s`; CI runs
it as an idempotence check, so regenerate + commit when changing a tweak.

## GitHub Actions

Every push builds two artifacts (no ROM data involved):

- **warioland4-recomp-linux-x64** — desktop binary + config shims
- **warioland4-recomp-debug-apk** — debug-signed Android arm64 APK

The desktop job also re-runs the tweak generator and fails on drift between
the assembly sources and the committed header.

## License

MIT for this project's own code — see `LICENSE` and
`THIRD_PARTY_ATTRIBUTION.md` for the vendored engines' licenses. The Wario
Land 4 ROM, its BIOS, and all Nintendo assets remain the property of
Nintendo; this repository ships none of them.

## Why static recompilation (vs. emulation)

- Native execution speed on phones (no interpreter/JIT in the hot path)
- No ROM dependency at runtime beyond the identity gate
- The decomp's symbols name the recompiled functions, making enhancements
  (widescreen, HUD work) patchable at source level later
- Deterministic: the decomp's rebuilt ROM matches the retail cartridge
  byte-for-byte, so the recompilation target is provably the same game
