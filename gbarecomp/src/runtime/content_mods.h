// content_mods.h — player-owned content mods (soundfonts / skins / patches).
//
// A mod is a folder under the content-mods root (RunOptions::content_mods_dir):
//
//   <mods_root>/<mod-id>/mod.toml       [mod] id/name/kind/author/description
//   <mods_root>/<mod-id>/patch.binpatch  optional offset=hexbytes patch lines
//   <mods_root>/<mod-id>/palette.txt     optional runtime palette overrides
//
// Patches apply to the in-memory ROM copy after the on-disk dump's SHA-1 is
// verified, before any guest instruction runs. The dump file itself stays
// pristine; diagnostics and save identity key off the verified dump. A mod
// that fails to parse is skipped with a log line — never a boot failure.
#pragma once

#include <array>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace gbarecomp::content_mods {

// A per-frame palette override (applied to palette RAM at VBlank, so it
// works even though the ROM's palette data is compressed at rest).
struct PaletteOverride {
    bool obj = false;                 // false: BG palette RAM, true: OBJ
    std::uint8_t slot = 0;            // 0..15
    std::array<std::uint16_t, 16> colors{};
};

struct Mod {
    std::string id;
    std::string name;
    std::string kind;  // "soundfont" | "skin" | "patch"
    std::string author;
    std::string description;
    std::filesystem::path root;
};

// Enumerate valid mod folders. Invalid folders are skipped silently; the
// result contains only parseable mods.
std::vector<Mod> scan(const std::filesystem::path& mods_root);

// Selected mod ids, persisted by save_selections in <mods_root>/selections.toml.
std::vector<std::string> load_selections(const std::filesystem::path& mods_root);
bool save_selections(const std::filesystem::path& mods_root,
                     const std::vector<std::string>& ids);

// Apply every selected mod's patch.binpatch to `rom`. Returns the number of
// applied patch lines. Per-line problems append to *log and are skipped.
int apply_selected(const std::filesystem::path& mods_root,
                   const std::vector<Mod>& mods,
                   const std::vector<std::string>& selected_ids,
                   std::uint8_t* rom, std::size_t rom_size,
                   std::string* log,
                   std::vector<PaletteOverride>* palettes = nullptr);
// Palette overrides from selected mods' palette.txt are collected into
// *palettes (BG slots first, then OBJ slots override BG on conflict).

// Write starter template folders (soundfont + skin) under
// <mods_root>/templates/. Returns false (with *log) when nothing was written.
bool export_templates(const std::filesystem::path& mods_root,
                      std::string* log);

}  // namespace gbarecomp::content_mods