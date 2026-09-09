#!/usr/bin/env python3
"""Patch world map location names in PROG.UNT for Slayers Royal (PS1).

This tool:
1. Reads Russian translations from translations/world_map_ru.json (20 location names).
2. Encodes Russian strings as 16-bit little-endian words (uint16_le) delimited by
   0x00FF (FF 00) using DEFAULT_CHARMAP.
3. Injects the encoded string table into PROG.UNT Sector 89 (LBA 229109) at offset 0x05FA.
4. Updates 20 32-bit pointers in Sector 93 (LBA 229113) at offset 0x0120..0x016C
   using the formula: 0x8004E4C0 + rel_offset.
5. Validates that the total table length <= 518 bytes (does not overflow Sector 89).
6. Recalculates Mode 2 Form 1 EDC/ECC checksums via replace_extent_in_place.
7. Supports --verify mode.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from patch_repo.localization.disc import (
    RAW_SECTOR_SIZE,
    USER_DATA_SIZE,
    CdChecksums,
    read_extent,
    replace_extent_in_place,
)
from PIL import Image, ImageDraw, ImageFont
from patch_repo.localization.glyphs import (
    FONT_PIXEL_OFFSET,
    FONT_PIXEL_SIZE,
    FONT_TIM_OFFSET,
    FONT_TIM_SIZE,
    RAW_FONT_PIXEL_OFFSET,
    glyph_xy,
)
from tools.patch_inspection import DEFAULT_CHARMAP

# Default paths
DEFAULT_TRANSLATIONS = REPO_ROOT / "translations" / "world_map_ru.json"
DEFAULT_TARGET_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"

# Disc and PROG.UNT layout constants
PROG_LBA = 229020
PROG_SECTOR_MAP_DATA = 89
PROG_SECTOR_MAP_PTRS = 93

SECTOR_89_LBA = PROG_LBA + PROG_SECTOR_MAP_DATA  # 229109
SECTOR_93_LBA = PROG_LBA + PROG_SECTOR_MAP_PTRS  # 229113

SECTOR_89_TABLE_OFFSET = 0x05FC
SECTOR_89_SAFE_END = 0x07C6  # Crucial system jump table starts at 0x07C6 and must be preserved!
MAX_TABLE_BYTES = SECTOR_89_SAFE_END - SECTOR_89_TABLE_OFFSET  # 458 bytes
SECTOR_93_PTR_OFFSET = 0x0120
NUM_LOCATIONS = 20

# PS1 RAM address calculation constants:
# Sector 89 is loaded in RAM such that byte offset in sector 89 maps to RAM:
# RAM_address = RAM_BASE + offset_in_sector_89
# For offset 0x05FC, RAM address is 0x8005BDB0 + 0x05FC = 0x8005C3AC.
RAM_BASE = 0x8005BDB0
TABLE_START_IN_ENTRY = SECTOR_89_TABLE_OFFSET  # 0x05FC

DELIMITER = 0x00FF
# Canonical system jump table and SPU/loader pointers at 0x07C6..0x0800 (58 bytes).
# Present in both JP and EN retail images; must be strictly preserved for CD-ROM interrupts to function!
SYSTEM_JUMP_TABLE = bytes.fromhex(
    "7f83fe867d8efd917c99fba07d98779472906c8c0080e0838ead95ce9cf374c5058000301380"
    "e03e138000001080004010800080108000c01080"
)

# 16x16 stacked location glyphs in font TIM (PROG.UNT Entry 0x03A)
# Displayed on the World Map location card (e.g. LAKEWOOD -> ЛЕЙК/ВУД, BARKLAND -> БАРК/ЛЕНД, AREA -> РЕГ/ИОН)
STACKED_GLYPHS: dict[int, tuple[str, str]] = {
    0x02BC: ("ЛЕЙК", "ВУД"),       # was LAKE/WOOD
    0x0296: ("БАРК", "ЛЕНД"),      # was BARK/LAND
    0x028B: ("РЕГ", ""),           # was AR
    0x029C: ("ИОН", ""),           # was EA (together "РЕГИОН" instead of "AR EA")
    0x02A5: ("ФРИ", "ГРАНТ"),      # was FREE/GROUND
    0x0289: ("ГРАМ", "СТОК"),      # was GRAM/STOCK
    0x02B6: ("ТУР", "СИТИ"),       # was TOUL/CITY
    0x02B7: ("САМ", "БУРГ"),       # was SUN/BURG
    0x02C0: ("СЕЙ", "РУН"),        # was SEY/RUUN
    0x02C1: ("КЬЮ", "ЗАК"),        # was KUZ/ACK
    0x02C7: ("МАРК", "УЭЛЛС"),     # was MARK/WELLS
    0x02D3: ("ЛЕЗА", "РИАМ"),      # was LEZ/ARIAM
}
FONT_TTF_PATH = REPO_ROOT / "fonts" / "PressStart2P.ttf"


def get_reverse_charmap(charmap: dict[str, int] | None = None) -> dict[int, str]:
    """Return inverted mapping from glyph ID to character."""
    cm = charmap if charmap is not None else DEFAULT_CHARMAP
    return {v: k for k, v in cm.items()}


def load_world_map_translations(path: Path | str | None = None) -> list[str]:
    """Load the 20 Russian location names from JSON catalog.

    Supports multiple JSON structures:
    - {"locations": [{"text_ru": "..."}, ...]}
    - {"locations": ["...", ...]}
    - ["...", ...]
    - {"0": "...", "1": "...", ...}
    """
    target = Path(path) if path is not None else DEFAULT_TRANSLATIONS
    if not target.is_file():
        raise FileNotFoundError(f"Translation catalog not found: {target}")

    data = json.loads(target.read_text(encoding="utf-8"))
    strings: list[str] = []

    if isinstance(data, dict):
        if "locations" in data:
            locs = data["locations"]
            if isinstance(locs, list):
                for item in locs:
                    if isinstance(item, dict):
                        text = item.get("text_ru") or item.get("ru") or item.get("text")
                        if text is not None:
                            strings.append(str(text))
                    elif isinstance(item, str):
                        strings.append(item)
            elif isinstance(locs, dict):
                for i in range(NUM_LOCATIONS):
                    key = str(i)
                    if key in locs:
                        val = locs[key]
                        strings.append(val.get("text_ru", val) if isinstance(val, dict) else str(val))
        else:
            # Maybe indexed dict {"0": "...", ...}
            for i in range(NUM_LOCATIONS):
                key = str(i)
                if key in data:
                    val = data[key]
                    strings.append(val.get("text_ru", val) if isinstance(val, dict) else str(val))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                text = item.get("text_ru") or item.get("ru") or item.get("text")
                if text is not None:
                    strings.append(str(text))
            elif isinstance(item, str):
                strings.append(item)

    if len(strings) != NUM_LOCATIONS:
        raise ValueError(
            f"Expected exactly {NUM_LOCATIONS} locations in {target}, found {len(strings)}"
        )

    return strings


def encode_location_strings(
    strings: list[str],
    charmap: dict[str, int] | None = None,
) -> tuple[bytes, list[int]]:
    """Encode Russian location strings into 16-bit little-endian word table.

    Each character is encoded as a uint16_le word via charmap.
    Each string is terminated by 0x00FF (b'\\xff\\x00').

    Returns:
        (table_bytes, offsets) where offsets are byte offsets within table_bytes.
    """
    if len(strings) != NUM_LOCATIONS:
        raise ValueError(f"Expected {NUM_LOCATIONS} strings, got {len(strings)}")

    cm = charmap if charmap is not None else DEFAULT_CHARMAP
    table = bytearray()
    offsets: list[int] = []

    for idx, text in enumerate(strings):
        offsets.append(len(table))
        for char in text:
            if char not in cm:
                raise ValueError(
                    f"Character '{char}' (U+{ord(char):04X}) in location [{idx}] '{text}' "
                    f"is missing from charmap"
                )
            code = cm[char]
            table.extend(struct.pack("<H", code))
        # Delimiter 0x00FF
        table.extend(struct.pack("<H", DELIMITER))

    if len(table) > MAX_TABLE_BYTES:
        raise ValueError(
            f"Encoded table length ({len(table)} bytes) exceeds maximum budget "
            f"of {MAX_TABLE_BYTES} bytes by {len(table) - MAX_TABLE_BYTES} bytes"
        )

    return bytes(table), offsets


def calculate_pointers(
    offsets: list[int],
    ram_base: int = RAM_BASE,
    table_entry_offset: int = TABLE_START_IN_ENTRY,
) -> list[int]:
    """Calculate 32-bit RAM pointer addresses for each string in the table.

    Formula: RAM_address = ram_base + rel_offset
    where rel_offset = table_entry_offset + offset_in_table.
    """
    if len(offsets) != NUM_LOCATIONS:
        raise ValueError(f"Expected {NUM_LOCATIONS} offsets, got {len(offsets)}")

    pointers: list[int] = []
    for off in offsets:
        rel_offset = table_entry_offset + off
        ptr = ram_base + rel_offset
        if ptr % 2 != 0:
            raise ValueError(f"Pointer 0x{ptr:08X} is not 16-bit aligned")
        pointers.append(ptr)

    return pointers


def decode_location_strings(
    table_bytes: bytes,
    count: int = NUM_LOCATIONS,
    charmap: dict[str, int] | None = None,
) -> list[str]:
    """Decode location strings from a raw 16-bit little-endian byte table."""
    rev_cm = get_reverse_charmap(charmap)
    strings: list[str] = []
    pos = 0

    while pos + 1 < len(table_bytes) and len(strings) < count:
        chars: list[str] = []
        while pos + 1 < len(table_bytes):
            code = struct.unpack_from("<H", table_bytes, pos)[0]
            pos += 2
            if code == DELIMITER:
                break
            chars.append(rev_cm.get(code, f"\\u{code:04x}"))
        strings.append("".join(chars))

    return strings


def patch_world_map_sectors(
    sec89: bytes,
    sec93: bytes,
    strings: list[str],
    charmap: dict[str, int] | None = None,
) -> tuple[bytes, bytes, list[int]]:
    """Patch Sector 89 (table) and Sector 93 (pointers) in memory.

    Returns:
        (new_sec89, new_sec93, pointers)
    """
    if len(sec89) != USER_DATA_SIZE:
        raise ValueError(f"Sector 89 must be {USER_DATA_SIZE} bytes, got {len(sec89)}")
    if len(sec93) != USER_DATA_SIZE:
        raise ValueError(f"Sector 93 must be {USER_DATA_SIZE} bytes, got {len(sec93)}")

    table_bytes, offsets = encode_location_strings(strings, charmap)
    pointers = calculate_pointers(offsets)

    # Patch Sector 89: preserve header up to 0x05FC, insert table, pad zeroes ONLY up to 0x07C6
    # Note: 0x07C6..0x0800 contains critical system jump table / loader code and must NOT be overwritten!
    new_sec89 = bytearray(sec89)
    new_sec89[SECTOR_89_TABLE_OFFSET : SECTOR_89_TABLE_OFFSET + len(table_bytes)] = table_bytes
    padding_len = SECTOR_89_SAFE_END - (SECTOR_89_TABLE_OFFSET + len(table_bytes))
    if padding_len < 0:
        raise ValueError(
            f"Sector 89 overflow: table length ({len(table_bytes)}) exceeds safe budget of "
            f"{MAX_TABLE_BYTES} bytes by {-padding_len} bytes"
        )
    new_sec89[SECTOR_89_TABLE_OFFSET + len(table_bytes) : SECTOR_89_SAFE_END] = b"\x00" * padding_len
    # Self-healing: if 0x07C6..0x0800 was zeroed out by a previous buggy build, restore it!
    if new_sec89[SECTOR_89_SAFE_END:] == b"\x00" * len(SYSTEM_JUMP_TABLE):
        new_sec89[SECTOR_89_SAFE_END:] = SYSTEM_JUMP_TABLE

    # Patch Sector 93: update 20 32-bit pointers at 0x0120..0x016C
    new_sec93 = bytearray(sec93)
    for idx, ptr in enumerate(pointers):
        ptr_offset = SECTOR_93_PTR_OFFSET + idx * 4
        struct.pack_into("<I", new_sec93, ptr_offset, ptr)

    return bytes(new_sec89), bytes(new_sec93), pointers

def render_stacked_glyph(top_text: str, bot_text: str, ttf_path: Path | None = None) -> Image.Image:
    """Render a 16x16 1-bit mask with stacked text (e.g. ЛЕЙК on top, ВУД on bottom)."""
    font_file = ttf_path or FONT_TTF_PATH
    font_5 = ImageFont.truetype(str(font_file), 5)
    font_6 = ImageFont.truetype(str(font_file), 6)

    im = Image.new("L", (16, 16), 0)
    draw = ImageDraw.Draw(im)

    if top_text and not bot_text:
        # Centered horizontally and vertically
        bb = draw.textbbox((0, 0), top_text, font=font_6)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        x = max(0, (16 - w) // 2)
        y = max(0, (16 - h) // 2)
        draw.text((x, y), top_text, font=font_6, fill=255)
    else:
        if top_text:
            f = font_5 if len(top_text) > 3 else font_6
            bb = draw.textbbox((0, 0), top_text, font=f)
            w = bb[2] - bb[0]
            x = max(0, (16 - w) // 2)
            draw.text((x, 0), top_text, font=f, fill=255)
        if bot_text:
            f = font_5 if len(bot_text) > 3 else font_6
            bb = draw.textbbox((0, 0), bot_text, font=f)
            w = bb[2] - bb[0]
            x = max(0, (16 - w) // 2)
            draw.text((x, 8), bot_text, font=f, fill=255)

    return im


def patch_world_map_font_glyphs(bin_path: Path | str, ttf_path: Path | None = None) -> int:
    """Patch stacked location glyphs (ЛЕЙК/ВУД, БАРК/ЛЕНД, etc.) into PROG.UNT runtime font TIM.

    Updates both FONT_TIM_OFFSET and RAW_FONT_PIXEL_OFFSET with EDC/ECC recalculation.
    Returns the number of patched glyph cells.
    """
    p = Path(bin_path)
    if not p.is_file():
        raise FileNotFoundError(f"BIN image not found: {p}")

    # 1. Read Font TIM from PROG.UNT
    sec_num = FONT_TIM_OFFSET // USER_DATA_SIZE
    sec_off = FONT_TIM_OFFSET % USER_DATA_SIZE
    num_secs = (sec_off + FONT_TIM_SIZE + USER_DATA_SIZE - 1) // USER_DATA_SIZE

    extent = bytearray(read_extent(p, PROG_LBA + sec_num, num_secs * USER_DATA_SIZE))
    tim = bytearray(extent[sec_off : sec_off + FONT_TIM_SIZE])

    def _set_pixel(buf: bytearray, x: int, y: int, val: int):
        bo = FONT_PIXEL_OFFSET + y * 512 + x // 2
        if x & 1:
            buf[bo] = (buf[bo] & 0x0F) | ((val & 0x0F) << 4)
        else:
            buf[bo] = (buf[bo] & 0xF0) | (val & 0x0F)

    changed_offsets: list[int] = []

    for gid, (top, bot) in STACKED_GLYPHS.items():
        gx, gy = glyph_xy(gid)
        mask = render_stacked_glyph(top, bot, ttf_path)
        pixels = mask.load()
        for py in range(16):
            for px in range(16):
                val = 3 if pixels[px, py] > 80 else 0
                bo = FONT_PIXEL_OFFSET + (gy + py) * 512 + (gx + px) // 2
                changed_offsets.append(bo)
                _set_pixel(tim, gx + px, gy + py, val)

    extent[sec_off : sec_off + FONT_TIM_SIZE] = tim
    replace_extent_in_place(p, PROG_LBA + sec_num, bytes(extent))

    # 2. Update raw font pixel copy at RAW_FONT_PIXEL_OFFSET
    raw_sec_num = RAW_FONT_PIXEL_OFFSET // USER_DATA_SIZE
    raw_sec_off = RAW_FONT_PIXEL_OFFSET % USER_DATA_SIZE
    raw_num_secs = (raw_sec_off + FONT_PIXEL_SIZE + USER_DATA_SIZE - 1) // USER_DATA_SIZE
    raw_extent = bytearray(read_extent(p, PROG_LBA + raw_sec_num, raw_num_secs * USER_DATA_SIZE))

    for bo in set(changed_offsets):
        target = raw_sec_off + (bo - FONT_PIXEL_OFFSET)
        raw_extent[target] = tim[bo]

    replace_extent_in_place(p, PROG_LBA + raw_sec_num, bytes(raw_extent))
    return len(STACKED_GLYPHS)

def patch_world_map_sector_1606(bin_path: Path | str) -> int:
    """Patch Sector 1606 (LBA 230626) in PROG.UNT to write full Russian names for world map banners.

    - Slot 0 (0x150, Table 1) and Table 2 (0x6C4): ЛЕЙКВУД (full-size 16x16 chars across the top ribbon banner!)
    - Slot 1 (0x160, Table 1) and Table 2 (0x6D4): БАРКЛЕНД (full-size 16x16 chars with НД ligature!)
    - Slot 2 (0x170): ФРИГРАНТ (with НТ ligature!)
    - Slot 3 (0x180): ГРАМСТОК (with ОК ligature!)
    - Slot 4 (0x190): СЕЙРУН
    - Offset 0x368: РЕГИОН (0x028B, 0x029C)
    """
    p = Path(bin_path)
    sec1606_lba = PROG_LBA + 1606
    sec1606 = bytearray(read_extent(p, sec1606_lba, USER_DATA_SIZE))

    def make_slot(words: list[int]) -> bytes:
        b = bytearray()
        for w in words:
            b.extend(struct.pack("<H", w))
        b.extend(struct.pack("<H", DELIMITER))
        pad = 16 - len(b)
        if pad > 0:
            b.extend(b"\x00" * pad)
        return bytes(b[:16])

    CM = DEFAULT_CHARMAP
    slot_lakewood = make_slot([CM["Л"], CM["Е"], CM["Й"], CM["К"], CM["В"], CM["У"], CM["Д"]])
    slot_barkland = make_slot([CM["Б"], CM["А"], CM["Р"], CM["К"], CM["Л"], CM["Е"], 0x028A])
    slot_freeground = make_slot([CM["Ф"], CM["Р"], CM["И"], CM["Г"], CM["Р"], CM["А"], 0x028C])
    slot_grumstock = make_slot([CM["Г"], CM["Р"], CM["А"], CM["М"], CM["С"], CM["Т"], 0x028D])
    slot_saillune = make_slot([CM["С"], CM["Е"], CM["Й"], CM["Р"], CM["У"], CM["Н"]])

    sec1606[0x150 : 0x150 + 16] = slot_lakewood
    sec1606[0x160 : 0x160 + 16] = slot_barkland
    sec1606[0x170 : 0x170 + 16] = slot_freeground
    sec1606[0x180 : 0x180 + 16] = slot_grumstock
    sec1606[0x190 : 0x190 + 16] = slot_saillune

    sec1606[0x6C4 : 0x6C4 + 16] = slot_lakewood
    sec1606[0x6D4 : 0x6D4 + 16] = slot_barkland

    # At 0x368: РЕГИОН
    reg_bytes = struct.pack("<HHHH", 0x028B, 0x029C, DELIMITER, 0x0000)
    sec1606[0x368 : 0x368 + 8] = reg_bytes

    replace_extent_in_place(p, sec1606_lba, bytes(sec1606))
    return 5


def verify_world_map_bin(
    bin_path: Path | str,
    translations_path: Path | str | None = None,
    charmap: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Verify binary integrity, pointers, strings, and EDC/ECC for world map.

    Returns verification report dict or raises AssertionError/ValueError.
    """
    p = Path(bin_path)
    if not p.is_file():
        raise FileNotFoundError(f"BIN image not found: {p}")

    expected_strings = load_world_map_translations(translations_path)
    expected_table, expected_offsets = encode_location_strings(expected_strings, charmap)
    expected_pointers = calculate_pointers(expected_offsets)

    # 1. Read Sector 89 and Sector 93
    sec89 = read_extent(p, SECTOR_89_LBA, USER_DATA_SIZE)
    sec93 = read_extent(p, SECTOR_93_LBA, USER_DATA_SIZE)

    # 2. Check EDC/ECC checksums for both sectors on disc
    checksums = CdChecksums()
    verified_sectors = 0
    with p.open("rb") as handle:
        for lba in (SECTOR_89_LBA, SECTOR_93_LBA):
            handle.seek(lba * RAW_SECTOR_SIZE)
            raw_sec = handle.read(RAW_SECTOR_SIZE)
            if len(raw_sec) != RAW_SECTOR_SIZE:
                raise ValueError(f"Failed to read complete raw sector at LBA {lba}")
            assert raw_sec[0x818:0x81C] == checksums.compute_edc(raw_sec[0x10:0x818]), (
                f"Mode 2 Form 1 EDC checksum mismatch at LBA {lba}"
            )
            assert raw_sec[0x81C:0x8C8] == checksums.compute_ecc(raw_sec[0x10:], 86, 24, 2, 86), (
                f"Mode 2 Form 1 ECC P-parity mismatch at LBA {lba}"
            )
            assert raw_sec[0x8C8:0x930] == checksums.compute_ecc(raw_sec[0x10:], 52, 43, 86, 88), (
                f"Mode 2 Form 1 ECC Q-parity mismatch at LBA {lba}"
            )
            verified_sectors += 1

    # 3. Verify Sector 93 pointers
    actual_pointers: list[int] = []
    for idx in range(NUM_LOCATIONS):
        ptr_offset = SECTOR_93_PTR_OFFSET + idx * 4
        ptr = struct.unpack_from("<I", sec93, ptr_offset)[0]
        actual_pointers.append(ptr)
        expected_ptr = expected_pointers[idx]
        assert ptr == expected_ptr, (
            f"Pointer [{idx:02d}] mismatch at Sector 93 offset 0x{ptr_offset:04X}: "
            f"expected 0x{expected_ptr:08X}, found 0x{ptr:08X}"
        )

    # 4. Verify Sector 89 table contents
    table_slice = sec89[SECTOR_89_TABLE_OFFSET : SECTOR_89_TABLE_OFFSET + len(expected_table)]
    assert table_slice == expected_table, (
        f"Sector 89 table data mismatch at offset 0x{SECTOR_89_TABLE_OFFSET:04X}"
    )

    # 5. Verify decoding of location strings
    decoded = decode_location_strings(table_slice, NUM_LOCATIONS, charmap)
    assert decoded == expected_strings, (
        f"Decoded strings mismatch:\nExpected: {expected_strings}\nActual:   {decoded}"
    )

    # 6. Verify remaining padding in Sector 89 is all zeros
    padding_start = SECTOR_89_TABLE_OFFSET + len(expected_table)
    padding_slice = sec89[padding_start:SECTOR_89_SAFE_END]
    assert all(b == 0 for b in padding_slice), (
        f"Sector 89 contains non-zero data in padding zone at offset 0x{padding_start:04X}"
    )
    # Verify critical system jump table at 0x07C6..0x0800 is intact
    assert sec89[SECTOR_89_SAFE_END:] != b"\x00" * (USER_DATA_SIZE - SECTOR_89_SAFE_END), (
        "Sector 89 system jump table at 0x07C6 was corrupted with zeroes!"
    )

    return {
        "verified": True,
        "bin_path": str(p),
        "locations_count": NUM_LOCATIONS,
        "table_bytes": len(expected_table),
        "max_table_bytes": MAX_TABLE_BYTES,
        "margin_bytes": MAX_TABLE_BYTES - len(expected_table),
        "sector_89_lba": SECTOR_89_LBA,
        "sector_93_lba": SECTOR_93_LBA,
        "edc_ecc_verified_sectors": verified_sectors,
        "first_location": decoded[0],
        "second_location": decoded[1],
        "pointers_sample": [f"0x{ptr:08X}" for ptr in actual_pointers[:4]],
    }


def patch_world_map_bin(
    bin_path: Path | str,
    translations_path: Path | str | None = None,
    verify_after: bool = True,
    charmap: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Patch world map location names in a PS1 CD-ROM BIN image.

    Recalculates Mode 2 Form 1 EDC/ECC checksums using replace_extent_in_place.
    """
    p = Path(bin_path)
    if not p.is_file():
        raise FileNotFoundError(f"BIN image not found: {p}")

    strings = load_world_map_translations(translations_path)

    # Read current sectors
    sec89 = read_extent(p, SECTOR_89_LBA, USER_DATA_SIZE)
    sec93 = read_extent(p, SECTOR_93_LBA, USER_DATA_SIZE)

    # Patch sectors in memory
    new_sec89, new_sec93, pointers = patch_world_map_sectors(sec89, sec93, strings, charmap)

    # Write back to disc image with EDC/ECC recalculation
    replace_extent_in_place(p, SECTOR_89_LBA, new_sec89)
    replace_extent_in_place(p, SECTOR_93_LBA, new_sec93)


    # 3. Patch stacked location glyphs (ЛЕЙК/ВУД, БАРК/ЛЕНД, РЕГИОН) in font TIM
    patched_glyphs_count = patch_world_map_font_glyphs(p)
    # 4. Patch Sector 1606 banner strings (full-size ЛЕЙКВУД, БАРКЛЕНД, etc.)
    patch_world_map_sector_1606(p)

    result = {
        "patched": True,
        "bin_path": str(p),
        "locations_count": len(strings),
        "table_bytes": len(strings) * 2 + 2,
        "pointers_count": len(pointers),
        "stacked_glyphs_count": patched_glyphs_count,
    }

    if verify_after:
        verify_report = verify_world_map_bin(p, translations_path, charmap)
        result["verify_report"] = verify_report

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch Russian world map location names in Slayers Royal (PS1)."
    )
    parser.add_argument(
        "--bin",
        type=Path,
        default=DEFAULT_TARGET_BIN if DEFAULT_TARGET_BIN.is_file() else None,
        help="Path to PS1 CD-ROM BIN image to patch (e.g. slayers_royal_ru.bin)",
    )
    parser.add_argument(
        "--translations",
        "--catalog",
        dest="translations",
        type=Path,
        default=DEFAULT_TRANSLATIONS,
        help="Path to translations/world_map_ru.json",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing patch without modifying disc",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform encoding and sector patching in memory without writing to disc",
    )

    args = parser.parse_args()

    if not args.bin:
        print("Error: --bin must be specified or default target BIN must exist.", file=sys.stderr)
        return 1

    if args.verify:
        print(f"Verifying world map patch in {args.bin}...")
        try:
            report = verify_world_map_bin(args.bin, args.translations)
            print("[PASS] World map patch verification successful!")
            print(f"  Locations count:  {report['locations_count']}")
            print(f"  Table size:       {report['table_bytes']} / {report['max_table_bytes']} bytes (margin: {report['margin_bytes']} bytes)")
            print(f"  Verified sectors: LBA {report['sector_89_lba']}, {report['sector_93_lba']} (EDC/ECC clean)")
            print(f"  Sample pointers:  {', '.join(report['pointers_sample'])}")
            print(f"  Sample locations: 0: '{report['first_location']}', 1: '{report['second_location']}'")
            return 0
        except Exception as exc:
            print(f"[FAIL] Verification failed: {exc}", file=sys.stderr)
            return 1

    if args.dry_run:
        print(f"Dry-run patch check on {args.bin}...")
        strings = load_world_map_translations(args.translations)
        sec89 = read_extent(args.bin, SECTOR_89_LBA, USER_DATA_SIZE)
        sec93 = read_extent(args.bin, SECTOR_93_LBA, USER_DATA_SIZE)
        new_sec89, new_sec93, ptrs = patch_world_map_sectors(sec89, sec93, strings)
        table_bytes, _ = encode_location_strings(strings)
        print(f"[OK] Dry run successful. Table size: {len(table_bytes)} / {MAX_TABLE_BYTES} bytes.")
        print(f"  Pointers: {len(ptrs)} pointers calculated (sample: 0x{ptrs[0]:08X}, 0x{ptrs[1]:08X})")
        return 0

    print(f"Patching world map location names in {args.bin}...")
    try:
        patch_result = patch_world_map_bin(args.bin, args.translations, verify_after=True)
        report = patch_result["verify_report"]
        print("[OK] World map successfully patched and verified!")
        print(f"  Table size:       {report['table_bytes']} / {report['max_table_bytes']} bytes (margin: {report['margin_bytes']} bytes)")
        print(f"  Pointers:         20 pointers updated in Sector 93 (0x{SECTOR_93_PTR_OFFSET:04X}..0x{SECTOR_93_PTR_OFFSET+76:04X})")
        print(f"  EDC/ECC:          Regenerated and verified for LBA {SECTOR_89_LBA} and {SECTOR_93_LBA}")
        return 0
    except Exception as exc:
        print(f"[ERROR] Patch failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
