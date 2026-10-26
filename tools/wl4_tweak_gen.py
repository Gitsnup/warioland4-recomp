#!/usr/bin/env python3
"""Generate gbarecomp/src/runtime/tweaks_patches.h for the built-in gameplay tweaks.

Sources of truth:
  tools/tweaks/gp_slope_roll.s  - thumb replacement body for the ground-pound
      landing pose handler (func_8011898). Assembled with arm-none-eabi-as and
      placed at ROM 0x08354440 — an all-zero gap between the sprite pose
      graphics tables (0x354409..0x355200 verified all 0x00 in the USA ROM;
      nothing references that span — see the placement contract below).

Hook design (byte-exact against the USA dump):
  func_8011898 starts with `ldr r2, [pc, #8]` (0x4A02) loading gWarioData from
  its first pool word at 0x080118A4. That pool word is DEAD for the GP-landing
  path: pose 29 selects kPrimGp via the *second* pool word (0x080118A8), pose
  != 29 loads kPrimSuperGp from a third pool word (0x080118E0). So the entry
  is rewritten as `ldr r3, [pc, #8]` (0x4B02 — Thumb literal base is
  insn+4, so [pc,#8] = 0x080118A4, the repurposed pool word) followed by
  `bx r3` (0x4718), and the pool word itself becomes the helper VA. The
  original `ldr r2`/`ldrb` pair re-executes inside the helper (pushing lr
  first, so the caller's flow is preserved).

Run from the repo root:  python3 tools/wl4_tweak_gen.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tools" / "tweaks" / "gp_slope_roll.s"
OUT = ROOT / "gbarecomp" / "src" / "runtime" / "tweaks_patches.h"

# All-zero gap inside the sprite pose graphics tables (verified below).
HELPER_ROM_ADDR = 0x08354440
GP_HANDLER_ROM_ADDR = 0x08011898
GP_HANDLER_POOL_ADDR = 0x080118A4      # gWarioData pool word (dead in this path)
GP_HANDLER_ORIG_PAIR = bytes.fromhex("024a5078")      # ldr r2,[pc,#8]; ldrb r0,[r2,#1]
GP_HANDLER_NEW_PAIR = bytes.fromhex("024b1847")       # ldr r3,[pc,#8]; bx r3
POOL_ORIG = bytes.fromhex("98180003")                 # 0x03001898 (gWarioData)
POOL_NEW = bytes.fromhex("40443508")                  # helper VA 0x08354440

# func_8010554 (walking pose handler) velocity constants.
# Each entry: (rom_addr, original halfword, replacement halfword, note)
# All inside func_8010554 (walking pose handler). r1/r0 hold the raw velocity
# halfword at every site; LSLS x2 doubles the step magnitude. The decel sites
# (4-6) double the stop/turn step too, which is what makes turning snappier.
TURBO_SITES = [
    (0x08010636, 0x1D88, 0x0048, "shoulder-run accel: adds r0,r1,#6 -> lsls r0,r1,#1"),
    (0x08010640, 0x1C88, 0x0048, "shoulder-run near-max: adds r0,r1,#2 -> lsls r0,r1,#1"),
    (0x0801065E, 0x3006, 0x0040, "walk accel: adds r0,#6 -> lsls r0,r0,#1"),
    (0x080106B6, 0x1F88, 0x0048, "leftward shoulder-run accel: subs r0,r1,#6 -> lsls r0,r1,#1"),
    (0x080106C0, 0x1E88, 0x0048, "leftward near-max: subs r0,r1,#2 -> lsls r0,r1,#1"),
    (0x080106E4, 0x3806, 0x380C, "left accel/stop: subs r0,#6 -> subs r0,#12"),
]


def assemble() -> bytes:
    # Assemble AND link at the helper's true VA. Assembling alone would place
    # the section at address 0, so the `bl 0x806DAC1` encodes as a
    # self-referencing placeholder (-4) — correct only at address 0, which is
    # not where the helper lives. Linking with -Ttext fixes every
    # PC-relative encoding in one step; the literal pools are absolute words
    # and unaffected.
    subprocess.run(
        ["arm-none-eabi-as", "-mthumb", "-mcpu=arm7tdmi", "-o", "/tmp/wl4_tweak_gen.o", str(SRC)],
        check=True,
    )
    subprocess.run(
        ["arm-none-eabi-ld", f"-Ttext={HELPER_ROM_ADDR:#x}",
         "-o", "/tmp/wl4_tweak_gen.elf", "/tmp/wl4_tweak_gen.o"],
        check=True,
    )
    subprocess.run(
        ["arm-none-eabi-objcopy", "-O", "binary", "/tmp/wl4_tweak_gen.elf",
         "/tmp/wl4_tweak_gen.bin"],
        check=True,
    )
    data = Path("/tmp/wl4_tweak_gen.bin").read_bytes()
    if not 0 < len(data) <= 0x110:
        raise SystemExit(f"helper size {len(data)} out of expected range")
    # The helper is fully position-independent except for literal pools:
    # the func_806DAC0 call goes through a local `bl .Lcall_r3; bx r3`
    # trampoline (see gp_slope_roll.s), so the only BL must target a point
    # inside the helper itself, and the probe VA must appear as a pool word.
    def bl_target(i: int) -> int:
        hw1 = data[i] | (data[i + 1] << 8)
        hw2 = data[i + 2] | (data[i + 3] << 8)
        if (hw1 & 0xF800) != 0xF000 or (hw2 & 0xF800) != 0xF800:
            return 0
        hi = hw1 & 0x7FF
        lo = hw2 & 0x7FF
        off = (hi << 12) | (lo << 1)
        if hi & 0x400:
            off -= 1 << 24
        return HELPER_ROM_ADDR + i + 4 + off

    found = []
    for i in range(0, len(data) - 3, 2):
        t = bl_target(i)
        if t:
            found.append((HELPER_ROM_ADDR + i, t))
    if not found:
        raise SystemExit("helper contains no BL at all")
    for addr, t in found:
        if not HELPER_ROM_ADDR <= t < HELPER_ROM_ADDR + len(data):
            raise SystemExit(
                f"helper BL at {addr:#010X} escapes the blob (target {t:#010X}) "
                "— cross-section relocation leaked in")
    probe = int.from_bytes(bytes.fromhex("0106d608"), "little")  # 0x0806DAC1 LE
    count = 0
    for i in range(0, len(data) - 3, 4):
        if data[i : i + 4] == bytes.fromhex("c1da0608"):
            count += 1
    if count != 1:
        raise SystemExit(f"probe VA 0x0806DAC1 appears {count} times in helper pool (want 1)")
    return data


def c_array(name: str, data: bytes) -> str:
    lines = []
    for i in range(0, len(data), 12):
        lines.append("    " + " ".join(f"0x{b:02x}," for b in data[i : i + 12]))
    return f"inline constexpr unsigned char {name}[] = {{\n" + "\n".join(lines) + "\n};\n"


def encode_b(addr: int, target: int) -> int:
    """Thumb-1 unconditional B (0xE000 mask)."""
    off = (target - (addr + 4)) >> 1
    assert -(1 << 11) <= off < (1 << 11), f"branch out of range 0x{addr:08X}->0x{target:08X}"
    return 0xE000 | (off & 0x7FF)


def main() -> None:
    helper = assemble()

    if helper[:2] != b"\x00\xb5":
        raise SystemExit("helper does not start with push {lr}")

    # Placement contract check against the actual USA dump.
    rom = (ROOT / "decomp" / "baserom_us.gba").read_bytes()
    base = HELPER_ROM_ADDR - 0x08000000
    span = rom[base : base + len(helper)]
    if len(span) != len(helper):
        raise SystemExit(f"helper span at {HELPER_ROM_ADDR:#x} falls outside the ROM — address bug")
    if any(b != 0 for b in span):
        raise SystemExit(f"helper span at {HELPER_ROM_ADDR:#x} is not all-zero — placement invalid")
    # Guard the neighborhood: the gap must still be zero-padded for a margin.
    if any(b != 0 for b in rom[base + len(helper) : base + len(helper) + 0x10]):
        raise SystemExit("no zero margin after helper — placement unsafe")
    # Entry bytes must match the USA dump exactly.
    entry = rom[GP_HANDLER_ROM_ADDR - 0x08000000 : GP_HANDLER_ROM_ADDR - 0x08000000 + 4]
    if entry != GP_HANDLER_ORIG_PAIR:
        raise SystemExit(f"unexpected entry bytes {entry.hex()} at {GP_HANDLER_ROM_ADDR:#x}")
    pool = rom[GP_HANDLER_POOL_ADDR - 0x08000000 : GP_HANDLER_POOL_ADDR - 0x08000000 + 4]
    if pool != POOL_ORIG:
        raise SystemExit(f"unexpected pool bytes {pool.hex()} at {GP_HANDLER_POOL_ADDR:#x}")
    # Turbo sites must match the USA dump too — a mismatch means an address
    # or encoding assumption is wrong and the runtime would silently skip
    # the whole tweak.
    for addr, orig, _repl, note in TURBO_SITES:
        got = int.from_bytes(rom[addr - 0x08000000 : addr - 0x08000000 + 2], "little")
        if got != orig:
            raise SystemExit(f"turbo site {addr:#010X} ({note}): expected {orig:#06X}, ROM has {got:#06X}")

    hdr = []
    hdr.append("// Auto-generated by tools/wl4_tweak_gen.py — do not edit by hand.")
    hdr.append("// Source of truth: tools/tweaks/gp_slope_roll.s (thumb assembly).")
    hdr.append("#pragma once")
    hdr.append("")
    hdr.append("namespace gbarecomp {")
    hdr.append("namespace runtime_tweaks {")
    hdr.append("")
    hdr.append(f"// Assembled helper body, installed at ROM {HELPER_ROM_ADDR:#010X}")
    hdr.append("// (all-zero gap inside the sprite pose graphics tables).")
    hdr.append(c_array("kGpSlopeRollHelper", helper))
    hdr.append(f"inline constexpr unsigned kGpSlopeRollHelperAddr = {HELPER_ROM_ADDR:#010X};")
    hdr.append(f"inline constexpr unsigned kGpSlopeRollEntryAddr = {GP_HANDLER_ROM_ADDR:#010X};")
    hdr.append(f"inline constexpr unsigned kGpSlopeRollPoolAddr = {GP_HANDLER_POOL_ADDR:#010X};")
    hdr.append(f"inline constexpr unsigned short kGpSlopeRollEntryOrig0 = {int.from_bytes(GP_HANDLER_ORIG_PAIR[0:2], 'little'):#06X};")
    hdr.append(f"inline constexpr unsigned short kGpSlopeRollEntryOrig1 = {int.from_bytes(GP_HANDLER_ORIG_PAIR[2:4], 'little'):#06X};")
    hdr.append(f"inline constexpr unsigned short kGpSlopeRollEntryNew0 = {int.from_bytes(GP_HANDLER_NEW_PAIR[0:2], 'little'):#06X};")
    hdr.append(f"inline constexpr unsigned short kGpSlopeRollEntryNew1 = {int.from_bytes(GP_HANDLER_NEW_PAIR[2:4], 'little'):#06X};")
    hdr.append("")
    hdr.append("struct PatchSite { unsigned addr; unsigned short orig; unsigned short repl; };")
    hdr.append("")
    hdr.append("// Entry hook (2 halfwords) + repurposed pool word (2 halfwords). The")
    hdr.append("// pool word's only reader is the patched entry, so rewriting it is safe.")
    hdr.append("inline constexpr PatchSite kGpSlopeRollSites[] = {")
    for addr, orig, repl in (
        (GP_HANDLER_ROM_ADDR, int.from_bytes(GP_HANDLER_ORIG_PAIR[0:2], "little"),
         int.from_bytes(GP_HANDLER_NEW_PAIR[0:2], "little")),
        (GP_HANDLER_ROM_ADDR + 2, int.from_bytes(GP_HANDLER_ORIG_PAIR[2:4], "little"),
         int.from_bytes(GP_HANDLER_NEW_PAIR[2:4], "little")),
        (GP_HANDLER_POOL_ADDR, int.from_bytes(POOL_ORIG[0:2], "little"),
         int.from_bytes(POOL_NEW[0:2], "little")),
        (GP_HANDLER_POOL_ADDR + 2, int.from_bytes(POOL_ORIG[2:4], "little"),
         int.from_bytes(POOL_NEW[2:4], "little")),
    ):
        hdr.append(f"    {{{addr:#010X}, {orig:#06X}, {repl:#06X}}},")
    hdr.append("};")
    hdr.append("")
    hdr.append("inline constexpr PatchSite kTurboMovementSites[] = {")
    for addr, orig, repl, note in TURBO_SITES:
        hdr.append(f"    {{{addr:#010X}, {orig:#06X}, {repl:#06X}}},  // {note}")
    hdr.append("};")
    hdr.append("")
    hdr.append("}  // namespace runtime_tweaks")
    hdr.append("}  // namespace gbarecomp")
    OUT.write_text("\n".join(hdr) + "\n")
    print(f"wrote {OUT} ({len(helper)} helper bytes, {len(TURBO_SITES)} turbo sites)")


if __name__ == "__main__":
    sys.exit(main())
