#!/usr/bin/env python3
"""Wario Land 4 content-mod toolkit.

Companion to the engine's content-mods system (mods/<id>/mod.toml +
patch.binpatch). Everything here reads the ROM dump only; nothing writes it.

Commands
--------
scan-palettes <rom> [--out DIR]   Find candidate 16-color BGR555 sprite
                                  subpalettes, print offsets + swatch PNGs.
find-samples  <rom> [--out FILE]  Walk the MP2K song table -> song headers ->
                                  voicegroups -> instruments -> sample
                                  records; print a map of every patchable
                                  region.
wav2patch     <wav> --offset 0x08XXXXXX [--format pcm8|pcm16]
                                  [--rate 18157] [--out FILE]
                                  Convert a WAV into a ready patch.binpatch
                                  line set (sample data + WaveData header).
dump-region   <rom> --offset N --len N [-o FILE]
                                  Hexdump or extract a region.

Addressing: GBA ROM is mapped at 0x08000000; every offset a tool prints is a
ROM address usable directly in a `patch.binpatch` line.
"""
import argparse
import math
import os
import zlib
import struct
import sys
import wave

ROM_BASE = 0x08000000
SONG_TABLE = 0x08098028   # gSongTable: 566 entries x 8 bytes {u32 header,u16 ms,u16 me}
PLAYER_TABLE = 0x08097FC8 # gMPlayTable
SONG_COUNT = 566


def read_rom(path):
    with open(path, "rb") as f:
        rom = f.read()
    if len(rom) < 0xC0:
        sys.exit("not a GBA ROM")
    return rom


def rom_at(rom, addr, length):
    off = addr - ROM_BASE
    if off < 0 or off + length > len(rom):
        raise ValueError(f"address 0x{addr:08X} outside ROM")
    return rom[off:off + length]


def u32(rom, addr):
    return struct.unpack_from("<I", rom_at(rom, addr, 4), 0)[0]


def u16(rom, addr):
    return struct.unpack_from("<H", rom_at(rom, addr, 2), 0)[0]


# ── PNG swatch writer (stdlib only) ────────────────────────────────────
def write_palette_png(path, bgr555):
    px = []
    for v in bgr555:
        r = ((v >> 10) & 31) * 255 // 31
        g = ((v >> 5) & 31) * 255 // 31
        b = (v & 31) * 255 // 31
        px.append(bytes((r, g, b)))
    w = h = 16
    scale = 16
    W = H = w * scale
    raw = bytearray()
    for y in range(H):
        raw.append(0)
        row = px[(y // scale) * 1]  # one row of 16 swatches each 16px tall
        line = bytearray()
        for x in range(0, W, scale):
            line += px[x // scale] * scale
        raw += line
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def bgr555_to_hex(v):
    return f"{v:04x}"

# ── Wario subpalette signature (shared by ROM + palette-RAM scans) ─────
def wario_sig_block(colors):
    """Score a 16-color BGR555 block for Wario's sprite subpalette:
    yellow cap/shirt, violet overalls, white gloves, pink nose/ears,
    skin tone, dark outline, transparent slot 0. Returns a score or None.
    """
    yellow = violet = skin = white = pink = dark = 0
    for v in colors:
        r, g, b = (v >> 10) & 31, (v >> 5) & 31, v & 31
        if r >= 29 and g >= 27 and b <= 6:
            yellow += 1
        if 12 <= r <= 24 and g <= 14 and b >= 22:
            violet += 1
        if r >= 27 and 18 <= g <= 26 and 12 <= b <= 22:
            skin += 1
        if r >= 28 and g >= 28 and b >= 26:
            white += 1
        if r >= 29 and 10 <= g <= 20 and 14 <= b <= 24 and not (
                r >= 27 and g >= 22):
            pink += 1
        if (r <= 5 and g <= 5 and b <= 8) or v <= 0x2000:
            dark += 1
    if colors[0] != 0:
        return None
    if yellow < 2 or violet < 2 or skin < 1 or pink < 1 or dark < 1:
        return None
    if white < 1:
        return None
    nonzero = sum(1 for c in colors if c != 0)
    if nonzero < 11:
        return None
    return yellow * 2 + violet * 2 + skin + pink * 2 + white + dark


def cmd_scan_palettes(args):
    rom = read_rom(args.rom)
    outdir = args.out or "palette-scan"
    os.makedirs(outdir, exist_ok=True)

    # Signature colors for a Wario-like subpalette (BGR555).
    # Wario: yellow cap/shirt, violet overalls/cap brim, white gloves,
    # pink nose/ears, skin tone.
    # Wario's player subpalette: yellow cap/shirt, violet overalls,
    # white gloves, pink nose/ears, skin tone, dark outline, transparent
    # slot 0. Pink-vs-skin and the outline are what separate him from
    # generic scene palettes.
    sig_block = wario_sig_block

    hits = []
    step = 32
    for off in range(0, len(rom) - step, step):
        block = struct.unpack_from("<16H", rom, off)
        if block[0] != 0:
            continue
        score = sig_block(block)
        if score:
            hits.append((score, ROM_BASE + off, block))
    hits.sort(key=lambda h: -h[0])
    print(f"{len(hits)} candidate palette block(s), best-first:\n")
    for score, addr, colors in hits[:60]:
        print(f"0x{addr:08X} score={score}: "
              + " ".join(f"{c:04x}" for c in colors))
        write_palette_png(f"{outdir}/pal_{addr - ROM_BASE:08x}.png", colors)
    if len(hits) > 60:
        print(f"... and {len(hits) - 60} more (raise the filter or lower "
              "the thresholds in sig_block).")
    print(f"\nSwatch PNGs for the top {min(len(hits), 60)}: {outdir}/ "
          "(16 slots, index 0..15 left to right)")


# ── MP2K sample walk ──────────────────────────────────────────────────
def tone_walk(rom, vg_addr, depth, seen, rows, owner):
    if depth > 3 or vg_addr in seen:
        return
    seen.add(vg_addr)
    # ToneData is 12 bytes: {u8 type, u8 key, u8 length, u8 pan_sweep,
    # u32 wav, u8 attack, u8 decay, u8 sustain, u8 release}
    for i in range(128):
        taddr = vg_addr + 12 * i
        if taddr - ROM_BASE + 12 > len(rom):
            return
        type_, key, length, pan = struct.unpack_from("<4B", rom, taddr - ROM_BASE)
        if type_ == 0:
            continue
        raw = u32(rom, taddr + 4)
        wav = raw - ROM_BASE  # normalized to a ROM-relative offset
        kind = type_ & 0xC0
        if not (0 <= wav <= len(rom)):
            continue
        if kind in (0x80, 0x40) and (type_ & 0x07) == 0:
            # rhythm/drum set (count in `length`) / key split (below `key`):
            # the wav pointer is a table of ToneData records.
            tone_walk(rom, ROM_BASE + wav, depth + 1, seen, rows,
                      owner + (f"/drum@t{i}" if kind == 0x80 else f"/split@t{i}"))
            continue
        if (type_ & 0x07) or kind in (0x80, 0x40):
            continue  # CGB hardware channels (types 1-7) have no DirectSound wav
        if wav + 16 > len(rom):
            continue
        wtype, wflags, wfreq, wloop, wsize = struct.unpack_from(
            "<HHIII", rom, wav)
        depth_bytes = 1  # MP2K DirectSound samples are PCM8 or DPCM-compressed
        # WaveData.freq stores the base sample rate as rate_hz << 10
        # (e.g. 0x00D10C00 >> 10 = 13379 Hz). Halfword 2 is a flags field
        # (0x4000 = looped), which is what the engine's shadow mixer reads.
        rate = wfreq >> 10
        data_addr = ROM_BASE + wav + 16
        rows.append(dict(
            tone=taddr, wav=ROM_BASE + wav, data=data_addr,
            type=type_, flags=wflags,
            kind=("drum" if kind == 0x80 else
                  "split" if kind == 0x40 else "direct"),
            rate_hz=rate, loop_start=wloop, size=wsize,
            bytes_=wsize * depth_bytes, owner=owner,
            instrument_index=i))
        if wsize * depth_bytes > 0x400000 or wsize == 0:
            rows[-1]["suspect"] = True


def cmd_find_samples(args):
    rom = read_rom(args.rom)
    rows = []
    seen_headers = set()
    for s in range(SONG_COUNT):
        entry = SONG_TABLE + 8 * s
        hdr = u32(rom, entry)
        if hdr < ROM_BASE or hdr - ROM_BASE + 8 > len(rom):
            continue
        if hdr in seen_headers:
            continue
        seen_headers.add(hdr)
        track_count = rom[hdr - ROM_BASE]
        if not (1 <= track_count <= 16):
            continue
        tone = u32(rom, hdr + 4)
        if tone < ROM_BASE or tone - ROM_BASE + 16 > len(rom):
            continue
        tone_walk(rom, tone, 0, set(), rows, f"song{s}")
    lines = []
    lines.append("# MP2K sample map — every patchable instrument record")
    lines.append("# (generated by tools/wl4_mod_tools.py find-samples)")
    lines.append(f"# song table 0x{SONG_TABLE:08X} ({SONG_COUNT} entries)")
    lines.append("# players 0-5 = music, players 6-7 = sound effects")
    lines.append("#")
    lines.append("# A sample record: WaveData header (16 bytes) then PCM data.")
    lines.append("# WaveData: {u16 type, u16 flags(0x4000=loop), u32 freq(rateHz<<10),")
    lines.append("#            u32 loopStart, u32 size}")
    lines.append("# rate_hz shown = freq>>10 (root pitch; MidiKeyToFreq scales per note)")
    seen_keys = set()
    uniq = []
    for r in rows:
        k = (r["wav"], r["rate_hz"], r["size"])
        if k in seen_keys:
            continue
        seen_keys.add(k)
        uniq.append(r)
    for r in sorted(uniq, key=lambda r: r["data"]):
        flag = " SUSPECT" if r.get("suspect") else ""
        lines.append(
            f"tone 0x{r['tone']:08X} [{r['kind']:6s} inst {r['instrument_index']:<3d}]"
            f" wav 0x{r['wav']:08X} data 0x{r['data']:08X}..+0x{r['bytes_']:06X}"
            f" rate {r['rate_hz']:>6d}Hz loop {r['loop_start']}{flag}"
            f"  ({r['owner']})")
    lines.append("# Patching a sample: keep the tone entry's wav pointer, rewrite the")
    # WaveData header + PCM payload in place (same size), or point the tone at
    # new bytes appended in free ROM space (update size/rate accordingly).
    text = "\n".join(lines) + "\n"
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"wrote {args.out} ({len(uniq)} unique sample records)")
    else:
        print(text)


def cmd_wav2patch(args):
    with wave.open(args.wav, "rb") as w:
        if w.getcomptype() != "NONE":
            sys.exit("compressed WAV")
        ch = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        frames = w.getnframes()
        data = w.readframes(frames)
    if ch > 1:
        sys.exit("mono only (mix down yourself)")
    if width not in (1, 2):
        sys.exit("8-bit or 16-bit WAV only")
    # Convert to the engine's sample depth.
    if args.format == "pcm8":
        if width == 1:
            samples = [b - 128 for b in data]  # wav 8-bit is unsigned
        else:
            samples = [s >> 8 for s in struct.unpack(f"<{len(data)//2}h", data)]
        payload = bytes((s & 0xFF) for s in samples)
        depth = 1
    else:
        if width == 2:
            payload = data
        else:
            samples = [(b - 128) << 8 for b in data]
            payload = struct.pack(f"<{len(samples)}h", *samples)
        depth = 2
    n = len(payload) // depth
    # MP2K DMA timer for the sample rate: rate = 16777216 / (2048 - status).
    status = 2048 - round(16777216 / args.rate)
    if not (0 <= status <= 0xFFFF):
        sys.exit("rate out of range for the MP2K DMA timer")
    wave_type = (1 if depth == 2 else 0)  # bit0 = 16-bit; no loop unless asked
    header = struct.pack("<HHIII", wave_type, status, args.rate, 0, n)
    lines = []
    lines.append(f"# {args.wav}: {n} samples, {depth * 8}-bit, {args.rate} Hz")
    lines.append(f"# WaveData header at 0x{args.offset:08X} (16 bytes)")
    lines.append(f"0x{args.offset:08X}={header.hex()}")
    lines.append(f"# sample data at 0x{args.offset + 16:08X}")
    for i in range(0, len(payload), 64):
        chunk = payload[i:i + 64]
        lines.append(f"0x{args.offset + 16 + i:08X}={chunk.hex()}")
    text = "\n".join(lines) + "\n"
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"wrote {args.out}")
    else:
        print(text)


def cmd_scan_palette_ram(args):
    """Scan a palette-RAM dump (1 KB, from `--dump-palette`) for Wario's
    player subpalette and print ready patch.binbinpatch lines.

    WL4 stores its palettes compressed in ROM, so the ROM scan can't see
    them; the authoritative view is palette RAM at 0x05000000 (BG first,
    OBJ at +0x200). Run the game to where the skin you want to mod is on
    screen, dump palette RAM, then scan it here.
    """
    with open(args.dump, "rb") as f:
        data = f.read()
    if len(data) != 1024:
        sys.exit(f"expected 1024 bytes, got {len(data)} (use --dump-palette)")
    hits = []
    for slot in range(16):
        off = 512 + slot * 32  # OBJ palette area
        colors = struct.unpack_from("<16H", data, off)
        score = wario_sig_block(colors)
        if score:
            hits.append((score, slot, colors))
    hits.sort(key=lambda h: -h[0])
    if not hits:
        print("No Wario subpalette found. Get in-game (a level, not the "
              "title screen), then dump again:")
        print("  ./build-desktop/WarioLand4Recomp --no-window --frames 400 "
              "--tcp 0 --dump-palette /tmp/palette.bin")
        return
    for score, slot, colors in hits:
        print(f"OBJ slot {slot} score={score}: "
              + " ".join(f"{c:04x}" for c in colors))
        write_palette_png(f"{args.out}/obj_slot{slot}.png" if args.out
                          else f"obj_slot{slot}.png", colors)
    print("\nPatch line template (replace values with your recolor, "
          "keep slot 0 transparent):")
    for score, slot, colors in hits:
        base = 0x05000000 + 512 + slot * 32
        print(f"0x{base:08X}=" + b"".join(struct.pack("<H", c)
                                          for c in colors).hex())
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        print(f"\nSwatch PNGs in {args.out}/")


def cmd_dump_region(args):
    rom = read_rom(args.rom)
    off = args.offset - ROM_BASE if args.offset >= ROM_BASE else args.offset
    data = rom[off:off + args.len]
    if args.o:
        with open(args.o, "wb") as f:
            f.write(data)
        print(f"wrote {args.o} ({len(data)} bytes @0x{ROM_BASE + off:08X})")
        return
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        print(f"{ROM_BASE + off + i:08X}  " +
              chunk.hex(" ") + "  " +
              "".join(chr(c) if 32 <= c < 127 else "." for c in chunk))


def cmd_scan_palette_ram(args):
    # WL4 stores palettes compressed in ROM; the real 1 KB palette RAM is
    # what the PPU reads. Dump it from a running game with:
    #   WarioLand4Recomp --no-window --frames 400 --tcp 0 \
    #       --dump-palette /tmp/palette.bin   (run until the target screen)
    # Slots 0-15 here are the BG palettes; slots 16-31 are OBJ (sprites).
    # Wario's player sprite palette lives in OBJ space.
    with open(args.dump, "rb") as f:
        ram = f.read()
    if len(ram) < 1024:
        sys.exit("palette dump must be 1024 bytes")
    outdir = args.out
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    hits = []
    for slot in range(32):
        block = struct.unpack_from("<16H", ram, slot * 32)
        score = wario_sig_block(block)
        label = ("OBJ" if slot >= 16 else "BG ") + f" slot{slot % 16:2d}"
        if score:
            hits.append((score, label, block))
        if any(block):
            print(f"{label}: " + " ".join(f"{c:04x}" for c in block))
    print()
    if not hits:
        print("No Wario subpalette found on this screen. Play until Wario is "
              "on screen, then dump again (mod the sig thresholds in "
              "wario_sig_block for other characters).")
        return
    hits.sort(key=lambda h: -h[0])
    print("Wario subpalette candidates, best-first:")
    for score, label, colors in hits:
        print(f"{label} score={score}: " + " ".join(f"{c:04x}" for c in colors))
        if outdir:
            write_palette_png(f"{outdir}/palscan_{label.replace(' ', '_')}.png",
                              colors)
    print("\nPatch addressing: BG palettes start at 0x05000000, OBJ at "
          "0x05000200; slot N begins at +N*32 bytes.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("scan-palettes", help="find sprite subpalette candidates")
    sp.add_argument("rom")
    sp.add_argument("--out", default=None)
    sp.set_defaults(fn=cmd_scan_palettes)

    sp = sub.add_parser("find-samples", help="map MP2K instruments and samples")
    sp.add_argument("rom")
    sp.add_argument("--out", default=None)
    sp.set_defaults(fn=cmd_find_samples)

    sp = sub.add_parser("wav2patch", help="WAV -> patch.binpatch lines")
    sp.add_argument("wav")
    sp.add_argument("--offset", type=lambda s: int(s, 0), required=True)
    sp.add_argument("--format", choices=("pcm8", "pcm16"), default="pcm8")
    sp.add_argument("--rate", type=int, default=18157)
    sp.add_argument("--out", default=None)
    sp.set_defaults(fn=cmd_wav2patch)

    sp = sub.add_parser("dump-region", help="hexdump / extract ROM region")
    sp.add_argument("rom")
    sp.add_argument("--offset", type=lambda s: int(s, 0), required=True)
    sp.add_argument("--len", type=lambda s: int(s, 0), required=True)
    sp.add_argument("-o", default=None)
    sp.set_defaults(fn=cmd_dump_region)

    sp = sub.add_parser("scan-palette-ram",
                        help="find Wario's subpalette in a --dump-palette dump")
    sp.add_argument("dump")
    sp.add_argument("--out", default=None)
    sp.set_defaults(fn=cmd_scan_palette_ram)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()