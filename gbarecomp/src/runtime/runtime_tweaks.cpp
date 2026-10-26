// runtime_tweaks.cpp — built-in gameplay tweaks implementation.
//
// Patch sets come from the generated tweaks_patches.h; this file only
// validates + applies them and persists selections. Patches write to the
// in-memory ROM copy at boot (after SHA-1 verification, before any guest
// instruction runs), so the on-disk dump stays pristine and save identity
// is unaffected.
#include "runtime_tweaks.h"

#include "content_mods.h"
#include "tweaks_patches.h"

#include <algorithm>
#include <cstdio>
#include <cstring>

namespace gbarecomp::runtime_tweaks {

namespace {

// ROM-space VA -> file offset (GBA carts map 0x08000000.. to offset 0).
bool rom_offset(unsigned addr, std::size_t rom_size, std::size_t* out) {
    if (addr < 0x08000000 || addr - 0x08000000 >= rom_size) return false;
    *out = addr - 0x08000000;
    return true;
}

// One halfword site. Returns false (with *log) on out-of-range or
// original-byte mismatch; never writes a partial patch.
bool patch_halfword(std::uint8_t* rom, std::size_t rom_size, unsigned addr,
                    unsigned short orig, unsigned short repl,
                    const char* tweak_id, std::string* log) {
    std::size_t off;
    if (!rom_offset(addr, rom_size, &off)) {
        char buf[128];
        std::snprintf(buf, sizeof(buf),
                      "[gbarecomp:tweaks] %s: site 0x%08X out of range, skipped\n",
                      tweak_id, addr);
        log->append(buf);
        return false;
    }
    const unsigned short current =
        static_cast<unsigned short>(rom[off] | (rom[off + 1] << 8));
    if (current != orig) {
        char buf[160];
        std::snprintf(buf, sizeof(buf),
                      "[gbarecomp:tweaks] %s: site 0x%08X expected %04X got %04X, skipped\n",
                      tweak_id, addr, orig, current);
        log->append(buf);
        return false;
    }
    rom[off] = static_cast<std::uint8_t>(repl & 0xFF);
    rom[off + 1] = static_cast<std::uint8_t>(repl >> 8);
    return true;
}

// Helper-body install: verifies the whole span is the original zero padding
// (0x354409..0x355200 is an all-zero gap between data tables) before
// overwriting, so we never stomp real code.
bool install_helper(std::uint8_t* rom, std::size_t rom_size,
                    const char* tweak_id, std::string* log) {
    std::size_t off;
    if (!rom_offset(runtime_tweaks::kGpSlopeRollHelperAddr, rom_size, &off)) {
        log->append("[gbarecomp:tweaks] gp-slope-roll: helper site out of range\n");
        return false;
    }
    for (std::size_t i = 0; i < sizeof(runtime_tweaks::kGpSlopeRollHelper); ++i) {
        if (rom[off + i] != 0x00) {
            char buf[128];
            std::snprintf(buf, sizeof(buf),
                          "[gbarecomp:tweaks] gp-slope-roll: helper span not free at +0x%zX\n",
                          i);
            log->append(buf);
            return false;
        }
    }
    std::memcpy(rom + off, runtime_tweaks::kGpSlopeRollHelper,
                sizeof(runtime_tweaks::kGpSlopeRollHelper));
    return true;
}

bool apply_gp_slope_roll(std::uint8_t* rom, std::size_t rom_size,
                         std::string* log) {
    if (!install_helper(rom, rom_size, "gp-slope-roll", log)) return false;
    // Entry hook (ldr r3,[pc,#8]; bx r3) + repurposed pool word -> helper VA.
    // Every site is checked against its original bytes first (patch_halfword),
    // so a foreign dump fails loudly instead of branching into garbage.
    int ok = 0;
    for (const auto& site : runtime_tweaks::kGpSlopeRollSites) {
        ok += patch_halfword(rom, rom_size, site.addr, site.orig, site.repl,
                             "gp-slope-roll", log);
    }
    return ok == static_cast<int>(std::size(runtime_tweaks::kGpSlopeRollSites));
}

bool apply_turbo_movement(std::uint8_t* rom, std::size_t rom_size,
                          std::string* log) {
    int ok = 0;
    for (const auto& site : runtime_tweaks::kTurboMovementSites) {
        ok += patch_halfword(rom, rom_size, site.addr, site.orig, site.repl,
                             "turbo-movement", log);
    }
    return ok == static_cast<int>(std::size(runtime_tweaks::kTurboMovementSites));
}

}  // namespace

const std::vector<Tweak> kTweaks = {
    {"tweak-gp-slope-roll",
     "Slope roll (ground pound)",
     "Ground-pounding onto a slope flows straight into a roll."},
    {"tweak-turbo-movement",
     "Faster turning",
     "Walking and shoulder-run acceleration build speed twice as fast."},
};

std::vector<std::string> load_selections(const std::filesystem::path& mods_root) {
    // Same tolerant reader as content mods; the shared selections.toml is
    // one flat quoted-id list and tweak ids never collide with mod ids.
    return content_mods::load_selections(mods_root);
}

bool save_selections(const std::filesystem::path& mods_root,
                     const std::vector<std::string>& ids) {
    return content_mods::save_selections(mods_root, ids);
}

bool selected(const std::filesystem::path& mods_root, const std::string& id) {
    for (const std::string& sel : load_selections(mods_root))
        if (sel == id) return true;
    return false;
}

int apply_enabled(std::uint8_t* rom, std::size_t rom_size,
                  const std::vector<std::string>& ids, std::string* log) {
    int applied = 0;
    for (const Tweak& t : kTweaks) {
        const std::string id = t.id;
        if (std::find(ids.begin(), ids.end(), id) == ids.end()) continue;
        bool ok = false;
        if (id == "tweak-gp-slope-roll")
            ok = apply_gp_slope_roll(rom, rom_size, log);
        else if (id == "tweak-turbo-movement")
            ok = apply_turbo_movement(rom, rom_size, log);
        if (ok) {
            char buf[96];
            std::snprintf(buf, sizeof(buf), "[gbarecomp:tweaks] applied %s\n", t.id);
            log->append(buf);
            ++applied;
        }
    }
    return applied;
}

}  // namespace gbarecomp::runtime_tweaks