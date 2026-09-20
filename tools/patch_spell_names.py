#!/usr/bin/env python3
"""Spell name list patcher for Slayers Royal (PS1) Russian translation.

Replaces the 57 spell/action catalog names displayed in the in-battle
spell selection list with Russian translations.  Generates 8×10 pixel
Cyrillic glyph tiles, writes them into the combat font TIM (Entry 0x142),
and encodes Russian name strings into Entry 0x007.

Architecture:
  The spell list renderer uses a dedicated 8-bit tile engine:
    - lbu $a3, 0($v1)        ; load tile index (0x00-0x5F)
    - addiu $a3, $a3, 0x60   ; tile descriptor code = index + 0x60
  Tile descriptors at Entry 0x007 offset 0x0673AC define 8×10 px tiles
  sourced from the combat font TIM at texture page (832, 256), UV offset
  (128, 112).  Each tile occupies 4 bytes/row × 10 rows = 40 bytes in
  the 4bpp TIM pixel data.

  Name strings are packed byte arrays at Entry 0x007 offset 0x06F2CC,
  referenced by a pointer table at offset 0x06F4D8 (58 entries, index 0
  is NULL).

Changes:
  1. Replaces the first 26 glyph tiles (indices 0x00-0x19) in the TIM
     with Cyrillic letter bitmaps rendered from NotoSans at 11px.
  2. Packs all 57 Russian spell names from translations/spells_ru.json
     (field ``name_ru``) into the 524-byte string region, updating all
     58 pointer-table entries.
  3. Recompresses Entry 0x142 with unt_lz mode 1 and writes both
     modified entries to disc with Mode 2 Form 1 EDC/ECC recalculation.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from localization import unt_lz
from localization.disc import (
    CdChecksums,
    RAW_SECTOR_SIZE,
    USER_DATA_OFFSET,
    USER_DATA_SIZE,
    read_extent,
    replace_extent_in_place,
)
from tools.patch_inspection import parse_iso_dir, read_sector, read_unt_index

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RAM_BASE = 0x8004E5B0           # RAM load address for PROG.UNT Entry 0x007
STRING_REGION_OFF = 0x06F2CC    # Entry-0x007 offset: packed spell name bytes
POINTER_TABLE_OFF = 0x06F4D8   # Entry-0x007 offset: 58-entry pointer table
STRING_REGION_SIZE = POINTER_TABLE_OFF - STRING_REGION_OFF   # 524 bytes
POINTER_COUNT = 58              # Entries 0 (NULL) .. 57

ENTRY_007 = 0x007
ENTRY_142 = 0x142

SECTION_SPELL_IDS = [
    # Section 1 (Lina): 9 spells
    [347, 354, 338, 372, 371, 373, 332, 333, 364],
    # Section 2 (Naga): 21 spells
    [331, 334, 335, 329, 330, 336, 339, 340, 341, 344, 346, 349, 350, 355, 356, 357, 358, 360, 361, 365, 379],
    # Section 3 (Other): 22 spells
    [326, 327, 328, 337, 342, 343, 345, 348, 351, 352, 353, 359, 362, 363, 366, 367, 368, 369, 370, 378, 380, 381],
    # Section 4 (Remaining): 5 spells
    [374, 375, 376, 377, 382],
]
SECTION_BUDGETS = [104, 212, 164, 44]
SECTION_OFFSETS = [0x06F2CC, 0x06F334, 0x06F408, 0x06F4AC]
POINTER_COUNT = 59              # Entries 0 (NULL) .. 58 (end boundary)
# TIM layout for spell-name tiles (4bpp)
TIM_PIXEL_DATA_OFF = 544        # Offset of pixel data within decompressed TIM
TIM_ROW_BYTES = 128             # 64 16-bit words = 256 4bpp pixels
TILE_WIDTH = 8                  # pixels
TILE_HEIGHT = 10                # pixels
TILE_UV_BASE_U = 128            # U coordinate of tile index 0
TILE_UV_BASE_V = 112            # V coordinate of tile index 0
TILE_UV_PAGE_Y = 256            # Texture page Y offset
TILES_PER_ROW = 16
SPACE_TILE = 0x5F

# Characters needed for Russian spell names
CYRILLIC_CHARS = sorted({
    '-', 'Ё', 'А', 'Б', 'В', 'Г', 'Д', 'Е', 'З', 'И', 'Й', 'К',
    'Л', 'М', 'Н', 'О', 'П', 'Р', 'С', 'Т', 'У', 'Ф', 'Х', 'Ш',
    'Ь', 'Э',
})

# Tile index charmap: character -> tile index (0x00-0x19)
SPELL_NAME_CHARMAP: dict[str, int] = {ch: i for i, ch in enumerate(CYRILLIC_CHARS)}
SPELL_NAME_CHARMAP[' '] = SPACE_TILE

REVERSE_SPELL_NAME_CHARMAP: dict[int, str] = {v: k for k, v in SPELL_NAME_CHARMAP.items()}

# Font search paths
FONT_SEARCH = [
    REPO_ROOT / "fonts" / "NotoSans-Regular.ttf",
    Path("/usr/share/fonts/noto/NotoSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
    Path("/usr/share/fonts/TTF/NotoSans-Regular.ttf"),
    Path("/usr/share/fonts/noto/NotoSans-Bold.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]

FONT_SIZE = 11

# ---------------------------------------------------------------------------
# Font handling
# ---------------------------------------------------------------------------

def find_font() -> Path:
    """Locate a TrueType font with Cyrillic support."""
    for p in FONT_SEARCH:
        if p.is_file():
            return p
    raise FileNotFoundError(
        "No suitable font found. Place NotoSans-Regular.ttf in fonts/"
    )


def render_glyph_4bpp(char: str, font: ImageFont.FreeTypeFont) -> list[list[int]]:
    """Render a character as 8×10 pixels with 4-bit depth (0-15)."""
    img = Image.new('L', (TILE_WIDTH, TILE_HEIGHT), 0)
    draw = ImageDraw.Draw(img)

    bbox = draw.textbbox((0, 0), char, font=font)
    char_w = bbox[2] - bbox[0]
    char_h = bbox[3] - bbox[1]

    x = (TILE_WIDTH - char_w) // 2 - bbox[0]
    y = (TILE_HEIGHT - char_h) // 2 - bbox[1] - 1
    y = max(-bbox[1], y)

    draw.text((x, y), char, fill=255, font=font)

    rows: list[list[int]] = []
    for py in range(TILE_HEIGHT):
        row: list[int] = []
        for px in range(TILE_WIDTH):
            val = img.getpixel((px, py))
            row.append(val * 15 // 255)
        rows.append(row)
    return rows


def generate_cyrillic_tiles(font_path: Path | None = None) -> dict[str, list[list[int]]]:
    """Generate 4bpp glyph bitmaps for all needed Cyrillic characters."""
    fp = font_path or find_font()
    font = ImageFont.truetype(str(fp), FONT_SIZE)
    return {ch: render_glyph_4bpp(ch, font) for ch in CYRILLIC_CHARS}


# ---------------------------------------------------------------------------
# TIM manipulation
# ---------------------------------------------------------------------------

def tile_uv(tile_index: int) -> tuple[int, int]:
    """Return (U, V) coordinates for a spell-name tile index."""
    col = tile_index % TILES_PER_ROW
    row = tile_index // TILES_PER_ROW
    return (TILE_UV_BASE_U + col * TILE_WIDTH,
            TILE_UV_BASE_V + row * TILE_HEIGHT)


def write_tile_to_tim(
    tim: bytearray,
    tile_index: int,
    pixels: list[list[int]],
) -> None:
    """Write an 8×10 4bpp tile into the TIM pixel data."""
    u, v = tile_uv(tile_index)
    tim_row_base = TILE_UV_PAGE_Y + v
    tim_byte_col = u // 2

    for py in range(TILE_HEIGHT):
        row_offset = TIM_PIXEL_DATA_OFF + (tim_row_base + py) * TIM_ROW_BYTES
        for px in range(TILE_WIDTH):
            byte_off = row_offset + tim_byte_col + px // 2
            val = pixels[py][px] & 0x0F
            if px % 2 == 0:
                tim[byte_off] = (tim[byte_off] & 0xF0) | val
            else:
                tim[byte_off] = (tim[byte_off] & 0x0F) | (val << 4)


def patch_tim_with_cyrillic(
    tim_data: bytes,
    font_path: Path | None = None,
) -> bytearray:
    """Inject Cyrillic glyph tiles into the combat font TIM."""
    tim = bytearray(tim_data)
    tiles = generate_cyrillic_tiles(font_path)

    for ch, tile_idx in SPELL_NAME_CHARMAP.items():
        if ch == ' ' or tile_idx == SPACE_TILE:
            continue
        write_tile_to_tim(tim, tile_idx, tiles[ch])

    return tim


# ---------------------------------------------------------------------------
# Spell name encoding
# ---------------------------------------------------------------------------

def encode_spell_name(name: str) -> bytes:
    """Encode a Russian spell name as a byte string of tile indices."""
    result = []
    for ch in name:
        if ch not in SPELL_NAME_CHARMAP:
            raise ValueError(f"Character '{ch}' not in spell name charmap")
        result.append(SPELL_NAME_CHARMAP[ch])
    return bytes(result)


def decode_spell_name(data: bytes) -> str:
    """Decode a tile-index byte string back to a Russian spell name."""
    chars = []
    for b in data:
        if b in REVERSE_SPELL_NAME_CHARMAP:
            chars.append(REVERSE_SPELL_NAME_CHARMAP[b])
        elif b == SPACE_TILE:
            chars.append(' ')
        else:
            chars.append(f'[{b:#04x}]')
    return ''.join(chars)


def build_spell_name_region(
    names: Sequence[str],
) -> tuple[bytes, bytes]:
    """Pack 57 spell names into sections and build the 59-entry pointer table (0..58).

    Returns:
        (string_region_bytes, pointer_table_bytes)
    """
    assert len(names) == 57, f"Expected 57 names, got {len(names)}"

    all_packed = bytearray()
    pointers = [0]  # Index 0 is NULL
    name_idx = 0

    for sec_i, sec in enumerate(SECTION_SPELL_IDS):
        sec_offset = SECTION_OFFSETS[sec_i]
        sec_budget = SECTION_BUDGETS[sec_i]
        sec_bytes = bytearray()

        for _ in sec:
            name = names[name_idx]
            name_idx += 1
            ptr = RAM_BASE + sec_offset + len(sec_bytes)
            pointers.append(ptr)
            sec_bytes.extend(encode_spell_name(name))

        if len(sec_bytes) > sec_budget:
            raise ValueError(
                f"Section {sec_i + 1} ({len(sec_bytes)} bytes) exceeds budget ({sec_budget} bytes)"
            )

        sec_bytes.extend(b"\x5f" * (sec_budget - len(sec_bytes)))
        all_packed.extend(sec_bytes)

    assert len(all_packed) == STRING_REGION_SIZE

    # Boundary pointer for spell 57 (index 58)
    pointers.append(RAM_BASE + POINTER_TABLE_OFF)

    ptr_bytes = bytearray()
    for ptr in pointers:
        ptr_bytes.extend(struct.pack("<I", ptr))

    return bytes(all_packed), bytes(ptr_bytes)


# ---------------------------------------------------------------------------
# Disc patching
# ---------------------------------------------------------------------------

def load_spells_catalog(catalog_path: Path | None = None) -> list[dict]:
    """Load spells_ru.json and return the 57 spell entries in SECTION_SPELL_IDS order."""
    path = catalog_path or (REPO_ROOT / "translations" / "spells_ru.json")
    with open(path, encoding="utf-8") as f:
        spells = json.load(f)
    by_id = {s["entry_index"]: s for s in spells}
    flat_ids = [sid for sec in SECTION_SPELL_IDS for sid in sec]
    return [by_id[sid] for sid in flat_ids]

def patch_spell_names(
    disc_path: Path,
    catalog_path: Path | None = None,
    font_path: Path | None = None,
    dry_run: bool = False,
    verify: bool = False,
) -> dict:
    """Patch spell names in the disc image.

    Steps:
        1. Load spell catalog and extract name_ru values.
        2. Generate Cyrillic glyph tiles and inject into Entry 0x142 TIM.
        3. Encode Russian names and build pointer table for Entry 0x007.
        4. Recompress Entry 0x142 with unt_lz.
        5. Write both entries to disc with EDC/ECC recalculation.
    """
    # 1. Load catalog
    spells = load_spells_catalog(catalog_path)
    names = [s['name_ru'] for s in spells]

    report: dict = {
        'spells_count': len(names),
        'unique_chars': len(set(ch for n in names for ch in n if ch != ' ')),
    }

    # Validate all characters are in charmap
    for i, name in enumerate(names):
        for ch in name:
            if ch not in SPELL_NAME_CHARMAP:
                raise ValueError(
                    f"Spell {i+1} '{name}': character '{ch}' not in charmap"
                )

    # 2. Build packed name data
    string_data, ptr_data = build_spell_name_region(names)
    report['string_bytes'] = len(string_data)
    report['pointer_entries'] = len(ptr_data) // 4

    # 3. Read disc structure
    pvd = read_sector(disc_path, 16)
    root_lba = struct.unpack_from('<I', pvd, 156 + 2)[0]
    root_size = struct.unpack_from('<I', pvd, 156 + 10)[0]
    iso_entries = parse_iso_dir(disc_path, root_lba, root_size)
    prog_lba = iso_entries['PROG.UNT'][0]

    sector0 = read_extent(disc_path, prog_lba, 2048)
    entries = read_unt_index(sector0)

    e007 = entries[ENTRY_007]
    e142 = entries[ENTRY_142]

    # 4. Read and patch Entry 0x142 (combat font TIM)
    e142_raw = read_extent(disc_path, prog_lba + e142.start_sector, e142.size)
    tim_dec, _ = unt_lz.decompress(e142_raw)

    patched_tim = patch_tim_with_cyrillic(tim_dec, font_path)
    compressed_tim = unt_lz.compress(bytes(patched_tim))

    font_budget = e142.size
    if len(compressed_tim) > font_budget:
        raise ValueError(
            f"Compressed font ({len(compressed_tim)}) exceeds "
            f"budget ({font_budget})"
        )

    padded_tim = compressed_tim.ljust(font_budget, b'\x00')
    report['font_compressed'] = len(compressed_tim)
    report['font_budget'] = font_budget

    # 5. Read and patch Entry 0x007
    e007_data = bytearray(read_extent(
        disc_path, prog_lba + e007.start_sector, e007.size
    ))

    # Write string region
    e007_data[STRING_REGION_OFF:STRING_REGION_OFF + STRING_REGION_SIZE] = string_data

    # Write pointer table (only entries 0-57, preserve entry 58+)
    ptr_table_size = POINTER_COUNT * 4  # 232 bytes
    e007_data[POINTER_TABLE_OFF:POINTER_TABLE_OFF + ptr_table_size] = ptr_data

    if verify:
        # Verify round-trip
        for i, name in enumerate(names):
            ptr_start = struct.unpack_from("<I", e007_data, POINTER_TABLE_OFF + (i + 1) * 4)[0]
            ptr_end = struct.unpack_from("<I", e007_data, POINTER_TABLE_OFF + (i + 2) * 4)[0]
            offset = ptr_start - RAM_BASE
            encoded = e007_data[offset : offset + len(name)]
            decoded = decode_spell_name(encoded)
            if decoded != name:
                raise AssertionError(
                    f"Spell {i+1} round-trip failed: '{name}' -> '{decoded}'"
                )
        print(f"  ✓ All {len(names)} spell names verified (round-trip)")

    if dry_run:
        report['dry_run'] = True
        return report

    # 6. Write Entry 0x142 to disc
    replace_extent_in_place(
        disc_path, prog_lba + e142.start_sector, padded_tim
    )
    report['e142_sectors'] = e142.size // USER_DATA_SIZE

    # 7. Write Entry 0x007 to disc
    replace_extent_in_place(
        disc_path, prog_lba + e007.start_sector, bytes(e007_data)
    )
    report['e007_sectors'] = e007.size // USER_DATA_SIZE

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch spell names with Russian translations"
    )
    parser.add_argument(
        "--bin", type=Path, required=True,
        help="Path to the PS1 BIN disc image",
    )
    parser.add_argument(
        "--catalog", type=Path, default=None,
        help="Path to spells_ru.json (default: translations/spells_ru.json)",
    )
    parser.add_argument(
        "--font", type=Path, default=None,
        help="Path to TrueType font with Cyrillic support",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate without writing to disc",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Verify patched data after writing",
    )

    args = parser.parse_args()

    if not args.bin.is_file():
        print(f"Error: disc image not found: {args.bin}", file=sys.stderr)
        return 1

    print("Patching spell names with Russian translations...")
    report = patch_spell_names(
        disc_path=args.bin,
        catalog_path=args.catalog,
        font_path=args.font,
        dry_run=args.dry_run,
        verify=args.verify,
    )

    print(f"  Spells: {report['spells_count']}")
    print(f"  Unique characters: {report['unique_chars']}")
    print(f"  String data: {report['string_bytes']} / {STRING_REGION_SIZE} bytes")
    print(f"  Font compressed: {report['font_compressed']} / {report['font_budget']} bytes")

    if report.get('dry_run'):
        print("  (dry run — no changes written)")
    else:
        print(f"  Entry 0x142: {report['e142_sectors']} sectors written")
        print(f"  Entry 0x007: {report['e007_sectors']} sectors written")
        print("  ✓ Spell names patched successfully")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
