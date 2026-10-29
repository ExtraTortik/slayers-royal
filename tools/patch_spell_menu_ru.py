#!/usr/bin/env python3
"""Russian translation of the in-battle spell selection menu.

Two resources are patched in PROG.UNT:

1. Entry 0x13F - the compact 4bpp battle font (128x256 TIM, LZ-compressed).
   The Latin/ligature tiles used by the English spell list are replaced with
   Russian uppercase letters and a small set of frequent bigrams.  The tiles
   are addressed by the same descriptors the engine already uses, so no code
   or descriptor changes are required.

2. Entry 0x007 - the 57-name battle spell table (0x06F2CC) and its 59-entry
   pointer table (0x06F4D8).  Names are re-encoded with the new compact-font
   codes.  The encoded pool is packed into the original 524-byte region; the
   pointer table is rewritten to match.

The renderer draws one 8x10 glyph per 8-bit code with a fixed 9-pixel pitch,
so a name must be at most 10 glyphs long to stay inside the list box.  Bigram
tiles are used for the seven names that are 11 characters long.

Run after patch_spells.py: it must not be followed by the old
"restore English spell menu" step that used to live in patch_spells.py.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from localization import unt_lz
from localization.disc import (
    CdChecksums,
    RAW_SECTOR_SIZE,
    USER_DATA_SIZE,
    read_extent,
    replace_extent_in_place,
)
from tools.patch_spells import (
    ENTRY_007_POINTER_TABLE_START,
    ENTRY_007_SPELL_MENU_END,
    ENTRY_007_SPELL_MENU_START,
    get_prog_unt_entry_extent,
)

DEFAULT_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_CATALOG = REPO_ROOT / "translations" / "spells_ru.json"

ENTRY_BATTLE_FONT = 0x13F
ENTRY_COMBAT_DATA = 0x007
FONT_TIM_MAGIC = b"\x10\x00\x00\x00"
GLYPH_PIXEL_INDEX = 0x0C

# Descriptor table inside Entry 0x007: 20 bytes per glyph code, starting at code 0x60.
GLYPH_DESCRIPTOR_OFFSET = 0x0673AC
GLYPH_DESCRIPTOR_SIZE = 20

# The menu renderer advances 9 pixels per glyph and has a ten-slot x table.
MAX_NAME_GLYPHS = 10

SPELL_NAME_COUNT = 57
SPELL_POINTER_COUNT = 59  # NULL + 57 names + end pointer

# ---------------------------------------------------------------------------
# Compact-font glyphs
# ---------------------------------------------------------------------------

# 5x5 uppercase Cyrillic.  The battle font stores five unique rows twice, so
# every pattern below is expanded to 8x10 by duplicating its rows.
SINGLE_GLYPHS: dict[str, list[str]] = {
    "А": [".###.", "#...#", "#####", "#...#", "#...#"],
    "Б": ["####.", "#....", "####.", "#...#", "####."],
    "В": ["####.", "#...#", "####.", "#...#", "####."],
    "Г": ["#####", "#....", "#....", "#....", "#...."],
    "Д": [".###.", ".#.#.", ".#.#.", "#####", "#...#"],
    "Е": ["#####", "#....", "####.", "#....", "#####"],
    # Six rows: the dots occupy the first row.
    "Ё": ["#.#.#", "#####", "#....", "####.", "#....", "#####"],
    "З": ["####.", "....#", ".###.", "....#", "####."],
    "И": ["#...#", "#..##", "#.#.#", "##..#", "#...#"],
    # Six rows: breve above the letter.
    "Й": [".#.#.", "#...#", "#..##", "#.#.#", "##..#", "#...#"],
    "К": ["#...#", "#..#.", "###..", "#..#.", "#...#"],
    "Л": ["..###", ".#..#", ".#..#", "#...#", "#...#"],
    "М": ["#...#", "##.##", "#.#.#", "#...#", "#...#"],
    "Н": ["#...#", "#...#", "#####", "#...#", "#...#"],
    "О": [".###.", "#...#", "#...#", "#...#", ".###."],
    "П": ["#####", "#...#", "#...#", "#...#", "#...#"],
    "Р": ["####.", "#...#", "####.", "#....", "#...."],
    "С": [".####", "#....", "#....", "#....", ".####"],
    "Т": ["#####", "..#..", "..#..", "..#..", "..#.."],
    "У": ["#...#", "#...#", ".####", "....#", "###.."],
    "Ф": [".###.", "#.#.#", "#.#.#", "#.#.#", ".###."],
    "Х": ["#...#", "#...#", ".#.#.", "#...#", "#...#"],
    "Ш": ["#.#.#", "#.#.#", "#.#.#", "#.#.#", "#####"],
    "Ь": ["#....", "#....", "####.", "#...#", "####."],
    "Э": ["####.", "....#", "..###", "....#", "####."],
    "-": [".....", ".....", ".###.", ".....", "....."],
}

# 4x5 letter halves used inside the 8-pixel-wide bigram tiles.
BIGRAM_LETTER_GLYPHS: dict[str, list[str]] = {
    "А": [".##.", "#..#", "####", "#..#", "#..#"],
    "Б": ["####", "#...", "###.", "#..#", "###."],
    "Г": ["####", "#...", "#...", "#...", "#..."],
    "Д": [".##.", ".#.#", ".#.#", "####", "#..#"],
    "Е": ["####", "#...", "###.", "#...", "####"],
    "И": ["#..#", "#.##", "##.#", "#..#", "#..#"],
    "Й": [".##.", "#..#", "#.##", "##.#", "#..#"],
    "Л": [".###", ".#.#", ".#.#", "#..#", "#..#"],
    "О": [".##.", "#..#", "#..#", "#..#", ".##."],
    "Р": ["###.", "#..#", "###.", "#...", "#..."],
    "С": [".###", "#...", "#...", "#...", ".###"],
    "Т": ["####", "..#.", "..#.", "..#.", "..#."],
    " ": ["....", "....", "....", "....", "...."],
    "-": ["....", "....", "####", "....", "...."],
}

SINGLE_ORDER = "АБВГДЕЁЗИЙКЛМНОПРСТУФХШЬЭ-"
BIGRAM_ORDER = [
    "РА", " Б", "ЛЕ", "ЕЙ", "АС", "СТ", "БР", "БО", "ДИ", "ДА",
    "РИ", "АЙ", "-Б", "АГ", "ЛА",
]

SINGLE_CODES = {ch: 0x60 + i for i, ch in enumerate(SINGLE_ORDER)}
BIGRAM_CODES = {
    bg: 0x60 + len(SINGLE_ORDER) + i for i, bg in enumerate(BIGRAM_ORDER)
}
SPACE_BYTE = 0x5F  # Existing blank tile (code 0xBF).  The renderer still
                   # advances one 9-pixel slot because x positions are fixed.
SPACE_CODE = SPACE_BYTE + 0x60

assert len(set(SINGLE_CODES.values()) | set(BIGRAM_CODES.values())) == (
    len(SINGLE_CODES) + len(BIGRAM_CODES)
)
for _bg in BIGRAM_ORDER:
    assert _bg[0] in BIGRAM_LETTER_GLYPHS and _bg[1] in BIGRAM_LETTER_GLYPHS


def expand_pattern(rows: list[str]) -> list[str]:
    """Expand a 5- or 6-row pattern to the 10-row cell used by the battle font."""
    if len(rows) == 5:
        return [rows[0], rows[0], rows[1], rows[1], rows[2], rows[2], rows[3], rows[3], rows[4], rows[4]]
    if len(rows) == 6:
        return [rows[0], rows[1], rows[1], rows[2], rows[2], rows[3], rows[3], rows[4], rows[4], rows[5]]
    raise ValueError(f"Unsupported glyph height: {len(rows)}")


def single_bitmap(char: str) -> list[list[int]]:
    rows = expand_pattern(SINGLE_GLYPHS[char])
    # Existing single-letter tiles keep a one-pixel left margin.
    return [[1 if (0 <= x - 1 < len(rows[y]) and rows[y][x - 1] == "#") else 0 for x in range(8)] for y in range(10)]


def bigram_bitmap(bigram: str) -> list[list[int]]:
    left = BIGRAM_LETTER_GLYPHS[bigram[0]]
    right = BIGRAM_LETTER_GLYPHS[bigram[1]]
    rows = [left[y] + right[y] for y in range(5)]
    rows = expand_pattern(rows)
    return [[1 if rows[y][x] == "#" else 0 for x in range(8)] for y in range(10)]


def build_font_cells() -> dict[int, list[list[int]]]:
    cells = {SINGLE_CODES[ch]: single_bitmap(ch) for ch in SINGLE_ORDER}
    cells.update({BIGRAM_CODES[bg]: bigram_bitmap(bg) for bg in BIGRAM_ORDER})
    return cells


# ---------------------------------------------------------------------------
# Name encoding
# ---------------------------------------------------------------------------

def encode_name(name: str) -> bytes:
    """Encode one spell name into compact-font bytes (greedy bigrams first)."""
    out = bytearray()
    index = 0
    while index < len(name):
        pair = name[index : index + 2]
        if len(pair) == 2 and pair in BIGRAM_CODES:
            out.append(BIGRAM_CODES[pair] - 0x60)
            index += 2
            continue
        char = name[index]
        if char == " ":
            out.append(SPACE_BYTE)
        elif char in SINGLE_CODES:
            out.append(SINGLE_CODES[char] - 0x60)
        else:
            raise ValueError(f"Character {char!r} has no compact-font glyph (name {name!r})")
        index += 1
    if len(out) > MAX_NAME_GLYPHS:
        raise ValueError(
            f"Encoded name {name!r} needs {len(out)} glyphs (max {MAX_NAME_GLYPHS})"
        )
    return bytes(out)


def decode_name(data: bytes) -> str:
    """Decode compact-font bytes back to a Russian string."""
    reverse_single = {code - 0x60: ch for ch, code in SINGLE_CODES.items()}
    reverse_bigram = {code - 0x60: bg for bg, code in BIGRAM_CODES.items()}
    out: list[str] = []
    for value in data:
        if value == SPACE_BYTE:
            out.append(" ")
        elif value in reverse_bigram:
            out.append(reverse_bigram[value])
        elif value in reverse_single:
            out.append(reverse_single[value])
        else:
            out.append(f"<{value:02X}>")
    return "".join(out)


def load_menu_names(catalog_path: Path) -> list[str]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(catalog, list) or len(catalog) < SPELL_NAME_COUNT + 1:
        raise ValueError(f"Unexpected spell catalog structure: {catalog_path}")
    names: list[str] = []
    for item in catalog[1 : SPELL_NAME_COUNT + 1]:
        name = item.get("menu_ru") or item.get("name_ru") or item.get("title_ru")
        if not name:
            raise ValueError(f"Missing Russian menu name in catalog entry: {item!r}")
        names.append(name)
    if len(names) != SPELL_NAME_COUNT:
        raise ValueError(f"Expected {SPELL_NAME_COUNT} spell names, got {len(names)}")
    return names


# ---------------------------------------------------------------------------
# TIM helpers
# ---------------------------------------------------------------------------

def parse_tim(tim: bytes) -> dict[str, int]:
    if len(tim) < 8 or tim[:4] != FONT_TIM_MAGIC:
        raise ValueError("Entry 0x13F is not a TIM resource")
    flags = struct.unpack_from("<I", tim, 4)[0]
    pmode = flags & 7
    pos = 8
    if flags & 8:
        clut_len = struct.unpack_from("<I", tim, pos)[0]
        pos += clut_len
    img_len, img_x, img_y, img_w, img_h = struct.unpack_from("<IHHHH", tim, pos)
    if pmode != 0:
        raise ValueError(f"Expected a 4bpp font TIM, got pmode {pmode}")
    pixel_offset = pos + 12
    pixel_width = img_w * 4
    pixel_height = img_h
    expected = pixel_width * pixel_height // 2
    if img_len - 12 != expected:
        raise ValueError(
            f"Unexpected TIM image size: {img_len - 12} != {expected}"
        )
    return {
        "pmode": pmode,
        "pixel_offset": pixel_offset,
        "width": pixel_width,
        "height": pixel_height,
        "img_x": img_x,
        "img_y": img_y,
    }


def descriptor_uv(e7_data: bytes, code: int) -> tuple[int, int]:
    off = GLYPH_DESCRIPTOR_OFFSET + code * GLYPH_DESCRIPTOR_SIZE
    u = e7_data[off + 12]
    v = e7_data[off + 13]
    return u, v


def write_tim_cell(
    tim: bytearray,
    tim_info: dict[str, int],
    u: int,
    v: int,
    bitmap: list[list[int]],
) -> None:
    width = tim_info["width"]
    pixel_offset = tim_info["pixel_offset"]
    # 4bpp texture coordinates wrap within the 128-pixel-wide TIM.
    x0 = u % width
    y0 = v
    if y0 + 10 > tim_info["height"]:
        raise ValueError(f"Glyph cell outside font TIM: u={u} v={v}")
    for y in range(10):
        for x in range(8):
            px = x0 + x
            if px >= width:
                raise ValueError(f"Glyph cell crosses TIM width: u={u} v={v}")
            byte_index = pixel_offset + (y0 + y) * (width // 2) + px // 2
            shift = 4 * (px % 2)
            value = tim[byte_index]
            value &= ~(0xF << shift)
            if bitmap[y][x]:
                value |= GLYPH_PIXEL_INDEX << shift
            tim[byte_index] = value


def read_tim_cell(tim: bytes, tim_info: dict[str, int], u: int, v: int) -> list[list[int]]:
    width = tim_info["width"]
    pixel_offset = tim_info["pixel_offset"]
    x0 = u % width
    y0 = v
    bitmap = []
    for y in range(10):
        row = []
        for x in range(8):
            byte_index = pixel_offset + (y0 + y) * (width // 2) + (x0 + x) // 2
            value = tim[byte_index]
            row.append(1 if (value >> (4 * ((x0 + x) % 2))) & 0xF else 0)
        bitmap.append(row)
    return bitmap


# ---------------------------------------------------------------------------
# Disc patching
# ---------------------------------------------------------------------------

def read_entry_007(bin_path: Path) -> tuple[int, int, int, bytes]:
    prog_lba, start, count = get_prog_unt_entry_extent(bin_path, ENTRY_COMBAT_DATA)
    data = read_extent(bin_path, prog_lba + start, count * 2048)
    return prog_lba, start, count, data


def build_name_region(names: list[str]) -> tuple[bytes, bytes]:
    """Pack encoded names into the original 524-byte region and build pointers."""
    pool = bytearray()
    starts: list[int] = []
    for name in names:
        starts.append(len(pool))
        pool.extend(encode_name(name))
    if len(pool) > ENTRY_007_SPELL_MENU_END - ENTRY_007_SPELL_MENU_START:
        raise ValueError(
            f"Encoded spell names use {len(pool)} bytes, "
            f"budget is {ENTRY_007_SPELL_MENU_END - ENTRY_007_SPELL_MENU_START}"
        )
    payload = bytes(pool).ljust(ENTRY_007_SPELL_MENU_END - ENTRY_007_SPELL_MENU_START, b"\x00")
    return payload, b""


def build_pointer_table(names: list[str], ram_base: int) -> bytes:
    pool_start = ENTRY_007_SPELL_MENU_START
    offsets: list[int] = []
    cursor = pool_start
    for name in names:
        offsets.append(cursor)
        cursor += len(encode_name(name))
    pointers = [0] + [ram_base + offset for offset in offsets] + [ram_base + cursor]
    if len(pointers) != SPELL_POINTER_COUNT:
        raise ValueError(f"Expected {SPELL_POINTER_COUNT} pointers, built {len(pointers)}")
    return b"".join(struct.pack("<I", value) for value in pointers)


def ram_base_for_entry_007(e7_data: bytes) -> int:
    """Derive the RAM load address from the first name pointer in Entry 0x007."""
    first_pointer = struct.unpack_from("<I", e7_data, ENTRY_007_POINTER_TABLE_START + 4)[0]
    if first_pointer <= ENTRY_007_SPELL_MENU_START:
        raise ValueError("Entry 0x007 spell pointer table is corrupted")
    return first_pointer - ENTRY_007_SPELL_MENU_START


def patch_entry_007_names(e7_data: bytearray, names: list[str]) -> bytearray:
    ram_base = ram_base_for_entry_007(e7_data)
    pool, _ = build_name_region(names)
    pointers = build_pointer_table(names, ram_base)
    e7_data[
        ENTRY_007_SPELL_MENU_START : ENTRY_007_SPELL_MENU_START + len(pool)
    ] = pool
    e7_data[
        ENTRY_007_POINTER_TABLE_START : ENTRY_007_POINTER_TABLE_START + len(pointers)
    ] = pointers
    return e7_data


def patch_battle_font(bin_path: Path, dry_run: bool = False) -> dict[str, Any]:
    prog_lba, start, count = get_prog_unt_entry_extent(bin_path, ENTRY_BATTLE_FONT)
    lba = prog_lba + start
    raw = read_extent(bin_path, lba, count * 2048)
    tim, _ = unt_lz.decompress(raw)
    tim_info = parse_tim(tim)
    _prog_lba, _e7_start, _e7_count, e7_data = read_entry_007(bin_path)

    cells = build_font_cells()
    patched_tim = bytearray(tim)
    for code, bitmap in cells.items():
        u, v = descriptor_uv(e7_data, code)
        write_tim_cell(patched_tim, tim_info, u, v, bitmap)

    compressed = unt_lz.compress(bytes(patched_tim))
    if len(compressed) > count * 2048:
        raise ValueError(
            f"Patched font TIM compresses to {len(compressed)} bytes, "
            f"budget is {count * 2048}"
        )
    if not dry_run:
        replace_extent_in_place(bin_path, lba, compressed.ljust(count * 2048, b"\x00"))
        verify_font_entry(bin_path, cells)
    return {
        "lba": lba,
        "sectors": count,
        "compressed_size": len(compressed),
        "budget": count * 2048,
        "glyphs": len(cells),
    }


def verify_font_entry(bin_path: Path, cells: dict[int, list[list[int]]] | None = None) -> dict[str, Any]:
    prog_lba, start, count = get_prog_unt_entry_extent(bin_path, ENTRY_BATTLE_FONT)
    raw = read_extent(bin_path, prog_lba + start, count * 2048)
    tim, _ = unt_lz.decompress(raw)
    tim_info = parse_tim(tim)
    _prog_lba, _e7_start, _e7_count, e7_data = read_entry_007(bin_path)
    expected = cells if cells is not None else build_font_cells()
    errors: list[str] = []
    for code, bitmap in expected.items():
        u, v = descriptor_uv(e7_data, code)
        actual = read_tim_cell(tim, tim_info, u, v)
        if actual != bitmap:
            errors.append(f"Glyph 0x{code:02X} at u=0x{u:02X} v=0x{v:02X} does not match")
    return {
        "glyphs": len(expected),
        "errors": errors,
    }


def patch_spell_menu(
    bin_path: Path,
    catalog_path: Path = DEFAULT_CATALOG,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not bin_path.is_file():
        raise FileNotFoundError(f"Disc image not found: {bin_path}")
    names = load_menu_names(catalog_path)

    prog_lba, start, count, e7_data = read_entry_007(bin_path)
    patched_e7 = patch_entry_007_names(bytearray(e7_data), names)
    if not dry_run:
        replace_extent_in_place(bin_path, prog_lba + start, bytes(patched_e7))

    font_report = patch_battle_font(bin_path, dry_run=dry_run)

    # Verify names on disc (unless dry-run, where the image is untouched).
    if not dry_run:
        verify = verify_spell_menu(bin_path, catalog_path)
        if verify["errors"]:
            raise AssertionError("Spell menu verification failed: " + "; ".join(verify["errors"][:5]))

    return {
        "names": len(names),
        "encoded_pool_bytes": sum(len(encode_name(name)) for name in names),
        "max_name_glyphs": max(len(encode_name(name)) for name in names),
        "font": font_report,
        "e7_lba": prog_lba + start,
    }


def verify_spell_menu(
    bin_path: Path,
    catalog_path: Path = DEFAULT_CATALOG,
) -> dict[str, Any]:
    names = load_menu_names(catalog_path)
    _prog_lba, _start, _count, e7_data = read_entry_007(bin_path)
    errors: list[str] = []
    ram_base = ram_base_for_entry_007(e7_data)
    pointers = [struct.unpack_from("<I", e7_data, ENTRY_007_POINTER_TABLE_START + i * 4)[0] for i in range(SPELL_POINTER_COUNT)]
    if pointers[0] != 0:
        errors.append("Pointer 0 (NULL) is not zero")
    decoded: list[str] = []
    for index, expected_name in enumerate(names, start=1):
        start_ptr = pointers[index] - ram_base
        end_ptr = pointers[index + 1] - ram_base
        if not (ENTRY_007_SPELL_MENU_START <= start_ptr <= end_ptr <= ENTRY_007_SPELL_MENU_END):
            errors.append(f"Pointer {index} out of range: {start_ptr:#x}..{end_ptr:#x}")
            continue
        data = e7_data[start_ptr:end_ptr]
        decoded_name = decode_name(data)
        decoded.append(decoded_name)
        if decoded_name != expected_name:
            errors.append(f"Name {index} round-trip mismatch: {decoded_name!r} != {expected_name!r}")
    font_verify = verify_font_entry(bin_path)
    errors.extend(font_verify["errors"])
    return {
        "names": len(names),
        "max_name_glyphs": max(len(encode_name(name)) for name in names),
        "encoded_pool_bytes": sum(len(encode_name(name)) for name in names),
        "font_glyphs": font_verify["glyphs"],
        "errors": errors,
    }


def verify_edc_ecc(bin_path: Path) -> list[str]:
    checksums = CdChecksums()
    errors: list[str] = []
    prog_lba, e7_start, e7_count = get_prog_unt_entry_extent(bin_path, ENTRY_COMBAT_DATA)
    font_lba, font_start, font_count = get_prog_unt_entry_extent(bin_path, ENTRY_BATTLE_FONT)
    for lba, count, label in (
        (prog_lba + e7_start, e7_count, "Entry 0x007"),
        (font_lba + font_start, font_count, "Entry 0x13F"),
    ):
        with bin_path.open("rb") as handle:
            for index in range(count):
                handle.seek((lba + index) * RAW_SECTOR_SIZE)
                sector = handle.read(RAW_SECTOR_SIZE)
                if len(sector) != RAW_SECTOR_SIZE:
                    errors.append(f"{label}: truncated sector {index}")
                    break
                if (
                    checksums.compute_edc(sector[0x10:0x818]) != sector[0x818:0x81C]
                    or checksums.compute_ecc(sector[0x10:], 86, 24, 2, 86) != sector[0x81C:0x8C8]
                    or checksums.compute_ecc(sector[0x10:], 52, 43, 86, 88) != sector[0x8C8:0x930]
                ):
                    errors.append(f"{label}: EDC/ECC failure at LBA {lba + index}")
                    break
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", type=Path, default=DEFAULT_BIN, help="disc image to patch")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="spells_ru.json")
    parser.add_argument("--dry-run", action="store_true", help="validate without writing")
    parser.add_argument("--verify", action="store_true", help="verify an already patched image")
    args = parser.parse_args()

    if args.verify:
        report = verify_spell_menu(args.bin, args.catalog)
        errors = list(report["errors"]) + verify_edc_ecc(args.bin)
        print(f"Spell menu names: {report['names']}")
        print(f"Max glyphs per name: {report['max_name_glyphs']}/{MAX_NAME_GLYPHS}")
        print(f"Encoded pool: {report['encoded_pool_bytes']} bytes")
        print(f"Font glyphs verified: {report['font_glyphs']}")
        if errors:
            print(f"Verification FAILED with {len(errors)} error(s):")
            for error in errors[:20]:
                print(f"  - {error}")
            return 1
        print("Verification OK")
        return 0

    report = patch_spell_menu(args.bin, args.catalog, dry_run=args.dry_run)
    print(f"Patched {report['names']} spell names "
          f"({report['encoded_pool_bytes']} bytes, max {report['max_name_glyphs']} glyphs)")
    font = report["font"]
    print(f"Patched battle font: {font['glyphs']} glyph cells, "
          f"{font['compressed_size']}/{font['budget']} compressed bytes")
    if args.dry_run:
        print("Dry run: disc image was not modified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
