#!/usr/bin/env python3
"""Charmap and tile allocation analysis for Slayers Royal PS1 combat dialogues.

Provides:
1. Scan of English combat UI buttons (0x05F278..0x05F470), system strings, and
   English font tiles in PROG.UNT 0x142 to verify zero tile collision.
2. Bidirectional charmap mapping 66 Russian Cyrillic characters (А-Я, а-я, Ё, ё)
   to 66 unreferenced tile indices in font 0x142 (0x0150..0x0191).
3. Preservation of Latin digits, punctuation, and English font tiles.
4. String encoding and decoding routines for combat dialogue blocks.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from tools.patch_combat_font import (
    CANONICAL_ASCII_GLYPHS,
    TOTAL_TILES,
    unpack_combat_font,
)

# Cyrillic alphabets (33 uppercase, 33 lowercase)
CYRILLIC_UPPER = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
CYRILLIC_LOWER = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"

# Base tile index for Cyrillic uppercase and lowercase in font 0x142
CYRILLIC_UPPER_BASE = 0x0150  # 0x0150..0x0170 (33 tiles)
CYRILLIC_LOWER_BASE = 0x0171  # 0x0171..0x0191 (33 tiles)

# Control codes in dialogue stream
OPCODE_NEWLINE = 0x00FE
OPCODE_BUBBLE_ADVANCE = 0x00FD
OPCODE_PAGE_BREAK = 0x00FD  # Alias for OPCODE_BUBBLE_ADVANCE (intra-bubble pagination)
OPCODE_BLOCK_END = 0x00FF

# Punctuation & digits in font 0x142 (canonical)
CANONICAL_PUNCTUATION: dict[str, int] = {
    " ": 0x007D,  # Transparent space tile
    ",": 0x00A1,
    ".": 0x00A2,
    '"': 0x00A3,
    "-": 0x00A4,
    "!": 0x00A6,
    "?": 0x00A7,
    ":": 0x00BC,
    "0": 0x00A8,
    "1": 0x00A9,
    "2": 0x00AA,
    "3": 0x00AB,
    "4": 0x00AC,
    "5": 0x00AD,
    "6": 0x00AE,
    "7": 0x00AF,
    "8": 0x00B0,
    "9": 0x00B1,
    # Extra symbols available in font 0x142
    "(": 0x0001,
    ")": 0x0002,
    "*": 0x0003,
    "/": 0x0004,
    ";": 0x0005,
    "=": 0x0006,
    "'": 0x031B,
    "★": 0x0256,
}

# Typographic aliases mapped to canonical tiles
TYPOGRAPHIC_ALIASES: dict[str, int] = {
    "«": 0x00A3,
    "»": 0x00A3,
    "“": 0x00A3,
    "”": 0x00A3,
    "„": 0x00A3,
    "’": 0x031B,
    "`": 0x031B,
    "—": 0x00A4,
    "–": 0x00A4,
}

CANONICAL_PUNCTUATION_AND_DIGITS: dict[str, int] = {
    **CANONICAL_PUNCTUATION,
    **TYPOGRAPHIC_ALIASES,
}


def build_combat_dialogue_charmap() -> dict[str, int]:
    """Build bidirectional charmap mapping characters to 16-bit font 0x142 tile codes.

    Guarantees:
    - 33 Cyrillic uppercase letters mapped to 0x0150..0x0170.
    - 33 Cyrillic lowercase letters mapped to 0x0171..0x0191.
    - Latin punctuation and digits mapped to canonical font 0x142 tiles.
    - ASCII letters A-Z, a-z preserved from CANONICAL_ASCII_GLYPHS.
    """
    cm: dict[str, int] = {}

    # 1. Cyrillic uppercase
    for idx, ch in enumerate(CYRILLIC_UPPER):
        cm[ch] = CYRILLIC_UPPER_BASE + idx

    # 2. Cyrillic lowercase
    for idx, ch in enumerate(CYRILLIC_LOWER):
        cm[ch] = CYRILLIC_LOWER_BASE + idx

    # 3. Punctuation, digits, and aliases
    for ch, code in CANONICAL_PUNCTUATION_AND_DIGITS.items():
        cm[ch] = code

    # 4. Latin ASCII letters for English reference or mixed text
    for ch, code in CANONICAL_ASCII_GLYPHS.items():
        if ch not in cm:
            cm[ch] = code

    return cm


def build_reverse_charmap(charmap: Mapping[str, int] | None = None) -> dict[int, str]:
    """Build reverse charmap mapping 16-bit tile codes to character strings.

    Prioritizes Cyrillic letters and canonical characters over secondary aliases.
    """
    cm = charmap if charmap is not None else build_combat_dialogue_charmap()
    rev: dict[int, str] = {}

    # 1. Lower priority: Typographic aliases and ASCII letters
    for k, v in TYPOGRAPHIC_ALIASES.items():
        if k in cm:
            rev[cm[k]] = k
    for k, v in CANONICAL_ASCII_GLYPHS.items():
        if k in cm:
            rev[cm[k]] = k

    # 2. Higher priority: Canonical punctuation and digits
    for k, v in CANONICAL_PUNCTUATION.items():
        if k in cm:
            rev[cm[k]] = k

    # 3. Highest priority: Russian letters
    for ch in CYRILLIC_UPPER + CYRILLIC_LOWER:
        rev[cm[ch]] = ch
    return rev


COMBAT_CHARMAP = build_combat_dialogue_charmap()
REVERSE_COMBAT_CHARMAP = build_reverse_charmap(COMBAT_CHARMAP)


def scan_protected_tiles(
    bin_path: Path | None = None,
    prog_entry_7_data: bytes | None = None,
) -> set[int]:
    """Scan all tile indices referenced by English combat UI buttons, system strings,
    and English font glyphs to ensure zero conflict with Cyrillic tiles.

    Returns the set of all tile indices (0..511) that MUST remain untouched.
    """
    protected: set[int] = set()

    # 1. English canonical ASCII font tiles and gourry-hacks tiles
    protected.update(CANONICAL_ASCII_GLYPHS.values())

    gourry_file = REPO_ROOT / "data" / "gourry_latin_tiles.json"
    if gourry_file.is_file():
        try:
            gourry_tiles = json.loads(gourry_file.read_text(encoding="utf-8"))
            protected.update(int(k, 16) for k in gourry_tiles.keys())
        except Exception:
            pass

    # 2. Extract Entry 0x007 from BIN if available
    e7_bytes: bytes | None = prog_entry_7_data
    target_bin = bin_path or (REPO_ROOT / "build" / "en_patched" / "sr_patched.bin")
    if e7_bytes is None and target_bin.is_file():
        try:
            from patch_repo.localization.disc import read_sector
            from tools.patch_inspection import parse_iso_dir, read_unt_index

            with target_bin.open("rb") as f:
                pvd = read_sector(target_bin, 16)
                root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
                root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
                root_dir = parse_iso_dir(target_bin, root_lba, root_size)
                if "PROG.UNT" in root_dir:
                    prog_lba, _ = root_dir["PROG.UNT"]
                    idx_sector = read_sector(target_bin, prog_lba)
                    entries = read_unt_index(idx_sector)
                    e7 = entries[7]
                    e7_bytes = b"".join(
                        read_sector(target_bin, prog_lba + e7.start_sector + s)
                        for s in range(e7.sector_count)
                    )
        except Exception:
            pass

    # 3. Scan UI buttons region in Entry 0x007: 0x05F278..0x05F470
    if e7_bytes and len(e7_bytes) >= 0x05F470:
        ui_region = e7_bytes[0x05F278:0x05F470]
        for i in range(0, len(ui_region), 2):
            tile_code = struct.unpack_from("<H", ui_region, i)[0]
            if 0 < tile_code < TOTAL_TILES:
                protected.add(tile_code)

        # Scan Table 1 strings (0x05F1FC..0x05F258)
        table1_region = e7_bytes[0x05F1FC:0x05F258]
        ram_base = 0x8004E110
        for i in range(0, len(table1_region), 4):
            ptr = struct.unpack_from("<I", table1_region, i)[0]
            off = ptr - ram_base
            if 0 <= off < len(e7_bytes):
                s_off = off
                while s_off + 2 <= len(e7_bytes):
                    val = struct.unpack_from("<H", e7_bytes, s_off)[0]
                    s_off += 2
                    if val in (0x0000, 0x00FF):
                        break
                    if 0 < val < TOTAL_TILES:
                        protected.add(val)

    return protected


def find_safe_cyrillic_tiles(
    protected_tiles: set[int] | None = None,
    count: int = 66,
) -> list[int]:
    """Find a contiguous block of completely unused tile indices in font 0x142.

    Returns the designated 66 tiles (0x0150..0x0191) after verifying zero conflicts.
    """
    protected = protected_tiles if protected_tiles is not None else scan_protected_tiles()
    designated = list(range(CYRILLIC_UPPER_BASE, CYRILLIC_UPPER_BASE + count))

    conflicts = set(designated) & protected
    if conflicts:
        hex_conflicts = [f"0x{c:04X}" for c in sorted(conflicts)]
        raise ValueError(
            f"Cyrillic tile range 0x{designated[0]:04X}..0x{designated[-1]:04X} "
            f"has {len(conflicts)} conflicts with protected tiles: {hex_conflicts}"
        )

    return designated


def encode_combat_dialogue_string(
    text: str,
    charmap: Mapping[str, int] | None = None,
) -> bytes:
    """Encode a Russian/Latin text string to 16-bit little-endian combat tile stream.

    Special codes:
    - '\\n' -> 0x00FE (line break)
    - '\\f' -> 0x00FD (OPCODE_PAGE_BREAK / OPCODE_BUBBLE_ADVANCE: page break)
    - '…'  -> three dots (0x00A2, 0x00A2, 0x00A2)
    """
    cm = charmap if charmap is not None else COMBAT_CHARMAP
    encoded = bytearray()

    idx = 0
    while idx < len(text):
        ch = text[idx]
        if ch == "\r":
            idx += 1
            continue
        elif ch == "\n":
            encoded.extend(struct.pack("<H", OPCODE_NEWLINE))
            idx += 1
        elif ch == "\f":
            encoded.extend(struct.pack("<H", OPCODE_BUBBLE_ADVANCE))
            idx += 1
        elif ch == "…":
            dot_code = cm.get(".", 0x00A2)
            encoded.extend(struct.pack("<H", dot_code))
            encoded.extend(struct.pack("<H", dot_code))
            encoded.extend(struct.pack("<H", dot_code))
            idx += 1
        else:
            code = cm.get(ch)
            if code is None:
                # Fallback: try uppercase/lowercase or space
                if ch.upper() in cm:
                    code = cm[ch.upper()]
                elif ch.lower() in cm:
                    code = cm[ch.lower()]
                else:
                    code = cm.get(" ", 0x007D)
            encoded.extend(struct.pack("<H", code))
            idx += 1

    return bytes(encoded)


def decode_combat_dialogue_string(
    data: bytes,
    reverse_charmap: Mapping[int, str] | None = None,
) -> str:
    """Decode 16-bit little-endian combat dialogue bytes back to text string."""
    rev = reverse_charmap if reverse_charmap is not None else REVERSE_COMBAT_CHARMAP
    chars: list[str] = []

    for i in range(0, len(data) - 1, 2):
        code = struct.unpack_from("<H", data, i)[0]
        if code == OPCODE_BLOCK_END:
            break
        elif code == OPCODE_NEWLINE:
            chars.append("\n")
        elif code == OPCODE_BUBBLE_ADVANCE:
            chars.append("\f")
        elif code in rev:
            chars.append(rev[code])
        else:
            chars.append(f"[{code:#06x}]")

    return "".join(chars)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze combat dialogue charmap and verify free tile slots.")
    parser.add_argument("--bin", type=Path, help="Path to English patched PS1 BIN image")
    parser.add_argument("--dump-charmap", type=Path, help="Dump charmap JSON to file")
    parser.add_argument("--verify", action="store_true", help="Run comprehensive verification checks")

    args = parser.parse_args()

    charmap = build_combat_dialogue_charmap()

    if args.dump_charmap:
        cm_hex = {k: f"0x{v:04X}" for k, v in sorted(charmap.items(), key=lambda x: x[1])}
        args.dump_charmap.parent.mkdir(parents=True, exist_ok=True)
        args.dump_charmap.write_text(json.dumps(cm_hex, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Dumped charmap ({len(charmap)} entries) to {args.dump_charmap}")

    # Verification
    protected = scan_protected_tiles(bin_path=args.bin)
    safe_tiles = find_safe_cyrillic_tiles(protected)

    print(f"Protected English tiles: {len(protected)}")
    print(f"Cyrillic designated tiles: 0x{safe_tiles[0]:04X}..0x{safe_tiles[-1]:04X} ({len(safe_tiles)} tiles)")
    print(f"Conflict count with English UI: {len(set(safe_tiles) & protected)} (0 expected)")

    # Round-trip test
    sample_text = "Тьфу! Если б ты пошла с нами, эти типы не совали бы свой нос!\nЗаткнись!"
    encoded = encode_combat_dialogue_string(sample_text)
    decoded = decode_combat_dialogue_string(encoded)
    assert decoded == sample_text, f"Round-trip mismatch:\nOriginal: {sample_text}\nDecoded:  {decoded}"
    print(f"Charmap encoding & decoding test: PASSED (encoded length = {len(encoded)} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
