#!/usr/bin/env python3
"""Tests for the in-battle spell menu Russian patcher."""

from __future__ import annotations

import json
from pathlib import Path
import struct
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from tools.patch_spells import (
    ENTRY_007_SPELL_MENU_END,
    ENTRY_007_SPELL_MENU_START,
    ENTRY_007_POINTER_TABLE_START,
)
from tools.patch_spell_menu_ru import (
    BIGRAM_CODES,
    BIGRAM_ORDER,
    MAX_NAME_GLYPHS,
    SINGLE_CODES,
    SINGLE_ORDER,
    SPELL_NAME_COUNT,
    SPELL_POINTER_COUNT,
    build_font_cells,
    build_name_region,
    build_pointer_table,
    decode_name,
    encode_name,
    load_menu_names,
    parse_tim,
    patch_entry_007_names,
    ram_base_for_entry_007,
    read_tim_cell,
    write_tim_cell,
)

CATALOG = REPO_ROOT / "translations" / "spells_ru.json"


def _synthetic_tim(width: int = 128, height: int = 256) -> bytes:
    clut_len = 12 + 256 * 2
    clut = struct.pack("<IHHHH", clut_len, 0, 480, 256, 1) + b"\x00\x00" * 256
    pixel_data = bytes(width * height // 2)
    img_len = 12 + len(pixel_data)
    image = struct.pack("<IHHHH", img_len, 0, 0, width // 4, height) + pixel_data
    return b"\x10\x00\x00\x00" + struct.pack("<I", 0x08) + clut + image


def _synthetic_e7() -> bytearray:
    e7 = bytearray(745 * 2048)
    base = 0x8004E5B0
    struct.pack_into("<I", e7, ENTRY_007_POINTER_TABLE_START + 4, base + ENTRY_007_SPELL_MENU_START)
    return e7


class TestNameEncoding:
    def test_all_catalog_names_round_trip(self):
        names = load_menu_names(CATALOG)
        assert len(names) == SPELL_NAME_COUNT
        for name in names:
            encoded = encode_name(name)
            assert 1 <= len(encoded) <= MAX_NAME_GLYPHS
            assert decode_name(encoded) == name

    def test_pool_fits_original_region(self):
        names = load_menu_names(CATALOG)
        pool, _ = build_name_region(names)
        assert len(pool) == ENTRY_007_SPELL_MENU_END - ENTRY_007_SPELL_MENU_START
        assert len(b"".join(encode_name(name) for name in names)) <= len(pool)

    def test_every_encoded_byte_has_a_glyph(self):
        cells = build_font_cells()
        names = load_menu_names(CATALOG)
        for name in names:
            for value in encode_name(name):
                if value == 0x5F:  # blank space tile
                    continue
                assert value + 0x60 in cells, f"byte {value:#04x} from {name!r} has no glyph"

    def test_unknown_character_is_rejected(self):
        with pytest.raises(ValueError):
            encode_name("ЦАРЬ")


class TestPointerTable:
    def test_pointer_table_is_monotonic_and_ends_at_pool_end(self):
        names = load_menu_names(CATALOG)
        base = 0x8004E5B0
        raw = build_pointer_table(names, base)
        pointers = list(struct.unpack(f"<{SPELL_POINTER_COUNT}I", raw))
        assert pointers[0] == 0
        assert all(pointers[i] <= pointers[i + 1] for i in range(1, len(pointers) - 1))
        assert pointers[1] == base + ENTRY_007_SPELL_MENU_START
        assert pointers[-1] == base + ENTRY_007_SPELL_MENU_START + sum(
            len(encode_name(name)) for name in names
        )

    def test_patch_entry_007_names_preserves_unrelated_regions(self):
        e7 = _synthetic_e7()
        e7[0x1000:0x2000] = b"\xAA" * 0x1000
        e7[0x60000:0x61000] = b"\xBB" * 0x1000
        names = load_menu_names(CATALOG)
        patched = patch_entry_007_names(e7, names)
        assert bytes(patched[0x1000:0x2000]) == b"\xAA" * 0x1000
        assert bytes(patched[0x60000:0x61000]) == b"\xBB" * 0x1000
        base = ram_base_for_entry_007(patched)
        pointers = list(
            struct.unpack_from(
                f"<{SPELL_POINTER_COUNT}I", patched, ENTRY_007_POINTER_TABLE_START
            )
        )
        for index, name in enumerate(names, start=1):
            start = pointers[index] - base
            end = pointers[index + 1] - base
            assert decode_name(bytes(patched[start:end])) == name


class TestFontCells:
    def test_every_catalog_character_has_a_cell(self):
        cells = build_font_cells()
        assert set(SINGLE_CODES.values()) <= set(cells)
        assert set(BIGRAM_CODES.values()) <= set(cells)
        for bigram in BIGRAM_ORDER:
            bitmap = cells[BIGRAM_CODES[bigram]]
            assert len(bitmap) == 10 and all(len(row) == 8 for row in bitmap)

    def test_tim_cell_write_read_round_trip(self):
        tim = bytearray(_synthetic_tim())
        info = parse_tim(bytes(tim))
        bitmap = build_font_cells()[SINGLE_CODES["Ё"]]
        u, v = 0x80 + (SINGLE_CODES["Ё"] - 0x60) % 16 * 8, 0x70 + (SINGLE_CODES["Ё"] - 0x60) // 16 * 10
        write_tim_cell(tim, info, u, v, bitmap)
        assert read_tim_cell(bytes(tim), info, u, v) == bitmap
        # Neighbouring cells stay empty.
        assert read_tim_cell(bytes(tim), info, (u + 8) % 128, v) == [
            [0] * 8 for _ in range(10)
        ]

    def test_cell_write_is_idempotent(self):
        tim = bytearray(_synthetic_tim())
        info = parse_tim(bytes(tim))
        bitmap = build_font_cells()[SINGLE_CODES["Ш"]]
        write_tim_cell(tim, info, 0x98, 0x84, bitmap)
        once = bytes(tim)
        write_tim_cell(tim, info, 0x98, 0x84, bitmap)
        assert bytes(tim) == once
