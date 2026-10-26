// main.cpp — WarioLand4Recomp entry point.
//
// Structure mirrors WarioWareTwistedRecomp (the Android-proven game shell):
// mobile_prepare_process() handles the Android private-storage layout, staged
// game TOML, and log file; desktop keeps the recomp-ui pre-boot launcher.
//
// ROM identity is baked in by tools/regen.sh (src/wl4e_rom_identity.h).

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "mobile_platform.h"
#include "runtime.h"
#include "wl4e_rom_identity.h"
#include "wl4e_song_classes.h"

#if defined(GBAGAME_RECOMP_UI)
#include "game_launcher_boot.h"
#endif

#ifndef GBARECOMP_DEFAULT_GAME_CONFIG
#define GBARECOMP_DEFAULT_GAME_CONFIG "variants/warioland4/game.toml"
#endif

namespace {

void print_usage() {
    std::printf(
        "WarioLand4Recomp [--bios <path>] [--rom <path>] [game.toml]\n"
        "The BIOS and ROM must match the SHA-1 identities in game.toml.\n"
        "Windowed play opens the recomp-ui launcher first; --no-launcher "
        "skips it once.\n"
        "Static recompilation is the default; set GBARECOMP_FORCE_INTERP=1 "
        "for the reference interpreter diagnostic backend.\n");
}

}  // namespace

int warioland4_main(int argc, char** argv) {
    std::vector<std::string> args(argv, argv + argc);
    // Android: private-storage layout, log file, staged game TOML and no
    // pre-boot launcher (shared gbarecomp mobile setup). No-op on desktop.
    gbarecomp::MobileProcessOptions mobile;
    mobile.game_config = GBARECOMP_DEFAULT_GAME_CONFIG;
    mobile.program_name = "./WarioLand4Recomp";
    gbarecomp::mobile_prepare_process(args, mobile);

    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--help") == 0 ||
            std::strcmp(argv[i], "-h") == 0) {
            print_usage();
            return 0;
        }
    }

    gbarecomp::RunOptions opts;
    opts.builtin_game_name = "Wario Land 4";
    opts.builtin_rom_sha1 = WL4E_ROM_SHA1;
    opts.builtin_rom_crc32 = WL4E_ROM_CRC32;
    opts.launcher_region = "USA";
    opts.launcher_game_config = GBARECOMP_DEFAULT_GAME_CONFIG;
    opts.launcher_save_path = "saves/warioland4_usa.sav";
#if defined(__ANDROID__)
    opts.ui_touch_friendly = true;
#endif
    // Native-fill widescreen headroom: the resize-driven view may widen the
    // guest up to 480 logical px (height stays at the authentic 160), which
    // reveals more world on the horizontal sides — a la Sonic Origins.
    opts.max_resize_view_width = 480;
    opts.max_view_width = 480;

    // Widescreen margins: serve the TRUE off-screen room tiles from the
    // game's own BG map arrays (gBackgroundInfo) — the entry animation and
    // MP2K split mute (Music / Sound effects): the game's own song table
    // classifies every song as BGM (players 0-5) or SFX (players 6-7);
    // see wl4e_song_classes.h, generated from decomp/include/sound.h.
    static const gbarecomp::RunOptions::Mp2kSplitMuteConfig mp2k_cfg{
        wl4e::kMPlayTableAddr, wl4e::kSongTableAddr,
        wl4e::kSongCount, wl4e::kPlayerCount, wl4e::kSongIsMusic};
    opts.mp2k_split_mute = &mp2k_cfg;

    // Player content mods (custom soundfonts / Wario skins / patches): the
    // mods folder sits beside the game.toml on desktop and inside the app's
    // files dir on Android (staged from the APK payload).
    opts.content_mods_dir = "mods";

#if defined(GBAGAME_RECOMP_UI)
    if (game_launcher_preboot(args, opts)) return 0;
#endif
    std::vector<char*> av;
    av.reserve(args.size());
    for (auto& arg : args) av.push_back(arg.data());
    return gbarecomp::run_game(static_cast<int>(av.size()), av.data(), opts);
}

#if defined(__ANDROID__)
extern "C" int SDL_main(int argc, char** argv) {
    // Desktop-sized host stack for recompiled code (see mobile_platform.h).
    return gbarecomp::mobile_run_with_stack(warioland4_main, argc, argv);
}
#else
int main(int argc, char** argv) {
    return warioland4_main(argc, argv);
}
#endif
