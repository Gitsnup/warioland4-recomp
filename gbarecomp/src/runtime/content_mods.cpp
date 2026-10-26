// content_mods.cpp — see content_mods.h. Line-oriented, dependency-free.
#include "content_mods.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>

namespace gbarecomp::content_mods {
namespace {

constexpr std::uint32_t kRomBase = 0x08000000u;

std::string trim(const std::string& s) {
    size_t a = s.find_first_not_of(" \t\r\n");
    if (a == std::string::npos) return {};
    size_t b = s.find_last_not_of(" \t\r\n");
    return s.substr(a, b - a + 1);
}

std::string strip_comment(const std::string& s) {
    const size_t h = s.find('#');
    return h == std::string::npos ? s : s.substr(0, h);
}

// Accepts bare or quoted values.
std::string parse_value(const std::string& v) {
    std::string t = trim(v);
    if (t.size() >= 2 && (t.front() == '"' || t.front() == '\'') &&
        t.back() == t.front())
        return t.substr(1, t.size() - 2);
    return t;
}

int hex_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

struct PatchLine {
    std::uint32_t offset = 0;
    std::vector<std::uint8_t> bytes;
};

// One `080xxxxx=hexbytes` line. Bare hex addressing only (base 0x08000000);
// a `0x` prefix would silently rebase the target, so it is rejected.
bool parse_patch_line(const std::string& line, PatchLine* out) {
    const size_t eq = line.find('=');
    if (eq == std::string::npos) return false;
    const std::string addr_s = trim(line.substr(0, eq));
    if (addr_s.size() == 8 && (addr_s.rfind("0x", 0) == 0 ||
                               addr_s.rfind("0X", 0) == 0))
        return false;
    if (addr_s.size() != 8) return false;
    std::uint32_t addr = 0;
    for (char c : addr_s) {
        const int n = hex_nibble(c);
        if (n < 0) return false;
        addr = (addr << 4) | static_cast<std::uint32_t>(n);
    }
    if (addr < kRomBase) return false;
    out->offset = addr - kRomBase;
    std::string hex;
    for (char c : trim(line.substr(eq + 1))) {
        if (c == ' ' || c == '\t') continue;  // tolerate spaced byte groups
        if (hex_nibble(c) < 0) return false;
        hex.push_back(c);
    }
    if (hex.empty() || hex.size() % 2 != 0) return false;
    for (size_t i = 0; i + 1 < hex.size(); i += 2) {
        const int hi = hex_nibble(hex[i]);
        const int lo = hex_nibble(hex[i + 1]);
        out->bytes.push_back(static_cast<std::uint8_t>((hi << 4) | lo));
    }
    return true;
}

// patch.binpatch lines: `080xxxxx=hexbytes` (ROM addressing, base 0x08000000).
// Malformed lines are skipped; only an unreadable file fails outright.
bool parse_patch_file(const std::filesystem::path& path,
                      std::vector<PatchLine>* out, std::string* bad_lines) {
    std::ifstream file(path);
    if (!file) return false;
    std::string raw;
    int line_no = 0;
    while (std::getline(file, raw)) {
        ++line_no;
        std::string line = trim(strip_comment(raw));
        if (line.empty()) continue;
        PatchLine pl;
        if (!parse_patch_line(line, &pl)) {
            if (bad_lines) {
                char n[16];
                std::snprintf(n, sizeof(n), "%d", line_no);
                *bad_lines += std::string("patch line ") + n +
                              " is malformed and was skipped\n";
            }
            continue;
        }
        out->push_back(std::move(pl));
    }
    return true;
}

// palette.txt lines: `bg|obj <slot 0-15> <16 BGR555 halfwords, hex>`. Applied
// every frame at the frame boundary, so overrides survive the game's own
// palette reloads (which is the whole point — the ROM's palettes are
// LZ-compressed at rest and rewritten whenever a scene loads).
bool parse_palette_file(const std::filesystem::path& path,
                        std::vector<PaletteOverride>* out, std::string* bad_lines) {
    std::ifstream file(path);
    if (!file) return false;
    std::string raw;
    int line_no = 0;
    while (std::getline(file, raw)) {
        ++line_no;
        std::istringstream iss(trim(strip_comment(raw)));
        std::string kind;
        if (!(iss >> kind)) continue;
        std::string slot_tok;
        if (!(iss >> slot_tok)) {
            if (bad_lines) *bad_lines += "palette line " +
                    std::to_string(line_no) + " is malformed and was skipped\n";
            continue;
        }
        PaletteOverride ov;
        if (kind == "bg") ov.obj = false;
        else if (kind == "obj") ov.obj = true;
        else {
            if (bad_lines) *bad_lines += "palette line " +
                    std::to_string(line_no) + " must start with 'bg' or 'obj'\n";
            continue;
        }
        long slot = 0;
        try { slot = std::stol(slot_tok); }
        catch (...) { slot = -1; }
        if (slot < 0 || slot > 15) {
            if (bad_lines) *bad_lines += "palette line " +
                    std::to_string(line_no) + " slot must be 0..15\n";
            continue;
        }
        ov.slot = static_cast<std::uint8_t>(slot);
        bool ok = true;
        for (int i = 0; i < 16; ++i) {
            std::string tok;
            if (!(iss >> tok)) { ok = false; break; }
            try { ov.colors[i] = static_cast<std::uint16_t>(std::stoul(tok, nullptr, 16) & 0x7FFFu); }
            catch (...) { ok = false; break; }
        }
        if (!ok) {
            if (bad_lines) *bad_lines += "palette line " +
                    std::to_string(line_no) + " needs exactly 16 hex halfwords\n";
            continue;
        }
        out->push_back(ov);
    }
    return true;
}

}  // namespace

std::vector<Mod> scan(const std::filesystem::path& mods_root) {
    std::vector<Mod> mods;
    std::error_code ec;
    if (mods_root.empty() || !std::filesystem::is_directory(mods_root, ec))
        return mods;
    std::vector<std::filesystem::path> dirs;
    for (const auto& entry : std::filesystem::directory_iterator(mods_root, ec)) {
        if (entry.is_directory(ec) && entry.path().filename() != "templates")
            dirs.push_back(entry.path());
    }
    std::sort(dirs.begin(), dirs.end());
    for (const auto& dir : dirs) {
        std::ifstream file(dir / "mod.toml");
        if (!file) continue;
        Mod mod;
        mod.root = dir;
        mod.id = dir.filename().string();
        std::string raw;
        while (std::getline(file, raw)) {
            std::string line = trim(strip_comment(raw));
            if (line.empty() || line.rfind('[', 0) == 0) continue;
            const size_t eq = line.find('=');
            if (eq == std::string::npos) continue;
            const std::string key = trim(line.substr(0, eq));
            const std::string value = parse_value(line.substr(eq + 1));
            if (key == "id") mod.id = value;
            else if (key == "name") mod.name = value;
            else if (key == "kind") mod.kind = value;
            else if (key == "author") mod.author = value;
            else if (key == "description") mod.description = value;
        }
        if (mod.id.empty() || mod.name.empty()) continue;
        if (mod.kind != "soundfont" && mod.kind != "skin" &&
            mod.kind != "patch")
            continue;
        mods.push_back(std::move(mod));
    }
    return mods;
}

std::vector<std::string> load_selections(const std::filesystem::path& mods_root) {
    std::vector<std::string> ids;
    std::ifstream file(mods_root / "selections.toml");
    if (!file) return ids;
    std::string raw;
    while (std::getline(file, raw)) {
        std::string line = trim(strip_comment(raw));
        if (line.empty()) continue;
        // Tolerant reader: each non-comment line is one quoted id. The
        // `enabled = [...]` array form written by save_selections parses as
        // one bracketed line, so also accept bare quoted ids per line.
        if (line.rfind("enabled", 0) == 0) {
            const size_t eq = line.find('=');
            if (eq == std::string::npos) continue;
            line = trim(line.substr(eq + 1));
            // strip surrounding [ ]
            if (!line.empty() && line.front() == '[' && line.back() == ']')
                line = line.substr(1, line.size() - 2);
            size_t start = 0;
            while (start < line.size()) {
                const size_t q1 = line.find('"', start);
                if (q1 == std::string::npos) break;
                const size_t q2 = line.find('"', q1 + 1);
                if (q2 == std::string::npos) break;
                std::string id = line.substr(q1 + 1, q2 - q1 - 1);
                if (!id.empty()) ids.push_back(id);
                start = q2 + 1;
            }
            continue;
        }
        if (line.size() >= 2 && line.front() == '"' && line.back() == '"')
            ids.push_back(line.substr(1, line.size() - 2));
    }
    return ids;
}

bool save_selections(const std::filesystem::path& mods_root,
                     const std::vector<std::string>& ids) {
    std::error_code ec;
    std::filesystem::create_directories(mods_root, ec);
    std::ofstream file(mods_root / "selections.toml");
    if (!file) return false;
    file << "# Content-mod selections. Applied at the next game launch.\n";
    file << "enabled = [";
    for (size_t i = 0; i < ids.size(); ++i) {
        if (i) file << ", ";
        file << '"' << ids[i] << '"';
    }
    file << "]\n";
    return true;
}

int apply_selected(const std::filesystem::path& mods_root,
                   const std::vector<Mod>& mods,
                   const std::vector<std::string>& selected_ids,
                   std::uint8_t* rom, std::size_t rom_size,
                   std::string* log,
                   std::vector<PaletteOverride>* palettes) {
    (void)mods_root;
    int applied = 0;
    auto append_log = [&](const std::string& s) {
        if (log && !s.empty()) {
            log->append(s);
            log->push_back('\n');
        }
    };
    for (const std::string& id : selected_ids) {
        auto it = std::find_if(mods.begin(), mods.end(),
                               [&](const Mod& m) { return m.id == id; });
        if (it == mods.end()) {
            append_log("skipped '" + id + "': not present in the mods folder");
            continue;
        }
        std::vector<PatchLine> lines;
        std::string patch_warn;
        // A missing/bad patch file is not fatal on its own: palette-only
        // mods (runtime skins with no ROM patch) are legitimate, so fall
        // through to palette collection regardless.
        if (!parse_patch_file(it->root / "patch.binpatch", &lines,
                              &patch_warn)) {
            append_log("'" + id +
                       "': patch.binpatch missing or has a bad line" +
                       (patch_warn.empty() ? std::string()
                                           : std::string(" — ") + patch_warn));
        }
        if (!patch_warn.empty())
            append_log("'" + id + "': " + patch_warn);
        int mod_applied = 0;
        for (const PatchLine& pl : lines) {
            if (pl.offset > rom_size || pl.bytes.size() > rom_size - pl.offset) {
                append_log("skipped line in '" + id + "': 0x" + [&] {
                    char buf[16];
                    std::snprintf(buf, sizeof(buf), "%08X", pl.offset + kRomBase);
                    return std::string(buf);
                }() + " is outside the ROM image");
                continue;
            }
            std::memcpy(rom + pl.offset, pl.bytes.data(), pl.bytes.size());
            ++mod_applied;
        }
        applied += mod_applied;
        if (mod_applied > 0)
            append_log("applied " + std::to_string(mod_applied) + " line(s) from '" +
                       id + "' (" + it->name + ")");
        // Runtime palette overrides (skins). These don't touch the ROM at all:
        // they re-apply to palette RAM at every frame boundary.
        if (palettes) {
            std::vector<PaletteOverride> mod_pal;
            std::string pal_warn;
            const auto pal_path = it->root / "palette.txt";
            std::error_code pec;
            if (std::filesystem::exists(pal_path, pec)) {
                if (parse_palette_file(pal_path, &mod_pal, &pal_warn)) {
                    if (!mod_pal.empty()) {
                        palettes->insert(palettes->end(), mod_pal.begin(),
                                         mod_pal.end());
                        append_log("queued " + std::to_string(mod_pal.size()) +
                                   " palette override(s) from '" + id + "'");
                    }
                    if (!pal_warn.empty()) append_log("'" + id + "': " + pal_warn);
                } else {
                    append_log("skipped '" + id +
                               "': palette.txt could not be read");
                }
            }
        }
    }
    return applied;
}

bool export_templates(const std::filesystem::path& mods_root,
                      std::string* log) {
    std::error_code ec;
    const std::filesystem::path tpl = mods_root / "templates";
    std::filesystem::create_directories(tpl, ec);
    bool wrote = false;

    {
        const std::filesystem::path dir = tpl / "soundfont-template";
        std::filesystem::create_directories(dir, ec);
        std::ofstream f(dir / "mod.toml");
        f << "# Soundfont starter template: copy this whole folder next to\n"
             "# this one, rename the folder, then edit these fields.\n"
             "[mod]\n"
             "id = \"soundfont-template\"\n"
             "name = \"My soundfont\"\n"
             "kind = \"soundfont\"\n"
             "author = \"you\"\n"
             "description = \"Replaces sequenced-instrument sample data at \"\n"
             "    \"fixed ROM offsets (the dump itself stays untouched).\"\n";
        f.close();
        wrote |= static_cast<bool>(f);
        std::ofstream p(dir / "patch.binpatch");
        p << "# Soundfont patch lines: ROM-address = hex bytes.\n"
             "#   08098028        song table (566 songs, 8-byte entries)\n"
             "#   08097FC8        player table (8 players, 0x98 bytes each)\n"
             "# Players 0-5 = music (BGM), players 6-7 = sound effects.\n"
             "# Song headers -> voicegroups -> instruments -> sample records\n"
             "# (rate/loop/length + PCM8 data). Tools/wl4_mod_tools.py\n"
             "# `find-samples` prints every sample record with its offset.\n"
             "# Example (commented out):\n"
             "# 08000010=0001020304050607\n";
        p.close();
        wrote |= static_cast<bool>(p);
        std::ofstream r(dir / "README.md");
        r << "# Soundfont template\n\n"
             "GBA music is *sequenced*: the ROM stores note data plus\n"
             "instrument sample records (rate, loop points, PCM8 data).\n"
             "A soundfont mod overwrites those records in memory at boot,\n"
             "leaving the ROM dump untouched.\n\n"
             "1. Run `python tools/wl4_mod_tools.py find-samples` against\n"
             "   the dump to list every instrument record and sample region.\n"
             "2. Craft replacement bytes and write `patch.binpatch` lines:\n"
             "   `ROM-address = hex bytes` (one line per replacement).\n"
             "3. Rename this folder, set its `mod.toml` fields, then enable\n"
             "   it in the in-game Mods screen (applies on next launch).\n";
        r.close();
        wrote |= static_cast<bool>(r);
    }

    {
        const std::filesystem::path dir = tpl / "wario-skin-template";
        std::filesystem::create_directories(dir, ec);
        std::ofstream f(dir / "mod.toml");
        f << "# Skin starter template: copy this whole folder next to this\n"
             "# one, rename the folder, then edit these fields.\n"
             "[mod]\n"
             "id = \"wario-skin-template\"\n"
             "name = \"My Wario skin\"\n"
             "kind = \"skin\"\n"
             "author = \"you\"\n"
             "description = \"Recolors Wario via per-frame palette overrides\"\n"
             "    \"(palette.txt) and/or re-tiles sprite data at fixed ROM\"\n"
             "    \"offsets (patch.binpatch). The dump itself stays untouched.\"\n";
        f.close();
        wrote |= static_cast<bool>(f);
        std::ofstream p(dir / "patch.binpatch");
        p << "# Skin patch lines: ROM-address = hex bytes (re-tiles / sprite\n"
             "# data swaps). Example (commented out):\n"
             "# 08000010=7fff03e07c1f0000\n";
        p.close();
        wrote |= static_cast<bool>(p);
        std::ofstream q(dir / "palette.txt");
        q << "# Skin palette overrides — the RECOMMENDED way to recolor.\n"
             "# WL4's palettes are LZ-compressed in the ROM, so patching\n"
             "# palette bytes at rest is impractical. Override the live\n"
             "# palette RAM every frame instead. Workflow:\n"
             "#   1. Play until the sprite/scene you want to recolor is on\n"
             "#      screen, then dump palette RAM:\n"
             "#        ./WarioLand4Recomp --no-window --frames 600 \\\n"
             "#            --dump-palette /tmp/pal.bin\n"
             "#   2. Find the live subpalette and its slot:\n"
             "#        python tools/wl4_mod_tools.py scan-palette-ram /tmp/pal.bin\n"
             "#   3. Write one line here per 16-color subpalette:\n"
             "#      bg <slot 0-15> <16 BGR555 halfwords>\n"
             "#      obj <slot 0-15> <16 BGR555 halfwords>\n"
             "# Example (commented out) — paint BG slot 0 solid red:\n"
             "# bg 0 0000 7c00 7c00 7c00 7c00 7c00 7c00 7c00 7c00 7c00 7c00 7c00 7c00 7c00 7c00 7c00 7c00\n";
        q.close();
        wrote |= static_cast<bool>(q);
        std::ofstream r(dir / "README.md");
        r << "# Wario skin template\n\n"
             "Two layers, pick what you need:\n\n"
             "**Recolor (recommended): `palette.txt`.** WL4's palettes are\n"
             "LZ-compressed at rest in the ROM, so recoloring overrides the\n"
             "live palette RAM every frame instead. See the comments inside\n"
             "`palette.txt` for the dump -> scan -> override workflow.\n"
             "Overrides survive the game's own palette reloads and fades,\n"
             "and the ROM dump stays untouched.\n\n"
             "**Re-tile: `patch.binpatch`.** Byte patches rewrite sprite/\n"
             "tile data in memory at boot. Tile graphics are also\n"
             "compressed at rest, so tile patches target decompressed\n"
             "caches (advanced).\n\n"
             "After editing: rename this folder, set its `mod.toml` fields,\n"
             "then enable it in the in-game Mods screen (applies on next\n"
             "launch).\n";
        r.close();
        wrote |= static_cast<bool>(r);
    }

    if (wrote && log)
        *log = "templates written under " + (mods_root / "templates").string();
    return wrote;
}

}  // namespace gbarecomp::content_mods