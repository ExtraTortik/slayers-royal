#!/usr/bin/env python3
"""Unit tests for tools/patch_inspection.py.

Verifies:
1. 16-bit Cyrillic charmap encoding and decoding for Slayers Royal PS1.
2. Exact encoding and decoding of "Подвесная лампа." and other tavern strings.
3. Pointer table parsing from PROG.UNT room inspection entries.
4. String extraction and round-trip rebuild fidelity.
5. Strict sector boundary and allocation budget constraints.
6. Integrity of data/inspection_ru.json (coverage of 31 strings in 0x05D).
7. UNT archive patching and zero-padding logic.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.patch_inspection import (
    CHAR_NEWLINE,
    CHAR_PAGE_CONTINUE,
    CHAR_STRING_TERMINATOR,
    DEFAULT_CHARMAP,
    HDR_PTR_TABLE_OFFSET,
    HDR_TRAILING_PTR_1,
    HDR_TRAILING_PTR_2,
    RAM_BASE,
    SECTOR_SIZE,
    decode_string,
    encode_string,
    load_charmap,
    parse_inspection_entry,
    patch_unt_entry,
    read_unt_index,
    rebuild_inspection_entry,
    resolve_entry_translations,
)


@pytest.fixture
def charmap() -> dict[str, int]:
    return load_charmap()


@pytest.fixture
def reverse_charmap(charmap: dict[str, int]) -> dict[int, str]:
    return {v: k for k, v in charmap.items()}


@pytest.fixture
def sample_disc_bin() -> Path | None:
    for candidate in [
        REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin",
        REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin",
        REPO_ROOT / "downloads" / "sr.bin",
    ]:
        if candidate.is_file():
            return candidate
    return None


@pytest.fixture
def synthetic_05d_entry(charmap: dict[str, int]) -> bytes:
    """Construct a valid synthetic 4096-byte 0x05D inspection entry."""
    entry = bytearray(4096)
    # Header fields
    # 0x0024: Pointer table start
    pt_off = 0x0A08
    # Pointers (31 pointers)
    num_ptrs = 31
    pt_len = num_ptrs * 4
    pt_end = pt_off + pt_len  # 0x0A84

    struct.pack_into(">I", entry, HDR_PTR_TABLE_OFFSET, RAM_BASE + pt_off)
    struct.pack_into(">I", entry, HDR_TRAILING_PTR_1, RAM_BASE + pt_end + 6)
    struct.pack_into(">I", entry, HDR_TRAILING_PTR_2, RAM_BASE + pt_end)

    # Initial strings starting at 0x0430
    curr = 0x0430
    ptr_offsets = []
    sample_texts = [
        "Потолок таверны.",
        "Потолок таверны.",
        "Второй этаж.",
        "Стена.",
    ] + [f"Объект {i}." for i in range(4, num_ptrs)]

    for idx, text in enumerate(sample_texts):
        if idx == 1:
            ptr_offsets.append(ptr_offsets[0])
            continue
        enc = encode_string(text, charmap)
        entry[curr : curr + len(enc)] = enc
        ptr_offsets.append(curr)
        curr += len(enc)

    # Write pointer table
    for idx, p_off in enumerate(ptr_offsets):
        struct.pack_into(">I", entry, pt_off + idx * 4, RAM_BASE + p_off)

    # Trailing block (16 bytes)
    trailing = b"\x00\x00\x00\x80\xff\xff\x00\x00\x00\x01\x00\x00\x00\x89\xff\xff"
    entry[pt_end : pt_end + len(trailing)] = trailing

    return bytes(entry)


# ---------------------------------------------------------------------------
# 1. 16-bit Russian String Encoding & Decoding Tests
# ---------------------------------------------------------------------------

def test_encode_decode_hanging_lamp(charmap: dict[str, int], reverse_charmap: dict[int, str]):
    """Verify that 'Подвесная лампа.' encodes to 16-bit big-endian words and decodes back."""
    target = "Подвесная лампа."
    encoded = encode_string(target, charmap)

    # 16 characters + 1 terminator = 17 words = 34 bytes
    assert len(encoded) == 34
    assert len(encoded) % 2 == 0

    # Verify terminator is 0x00FF
    last_word = struct.unpack_from(">H", encoded, len(encoded) - 2)[0]
    assert last_word == CHAR_STRING_TERMINATOR

    # Decode back
    words = [struct.unpack_from(">H", encoded, i)[0] for i in range(0, len(encoded), 2)]
    decoded = decode_string(words, reverse_charmap)
    assert decoded == target


def test_encode_control_characters(charmap: dict[str, int], reverse_charmap: dict[int, str]):
    """Verify newline (0x00FE) and page continuation (0x00FD) handling."""
    text = "Строка 1.\nСтрока 2."
    encoded = encode_string(text, charmap)

    words = [struct.unpack_from(">H", encoded, i)[0] for i in range(0, len(encoded), 2)]
    assert CHAR_NEWLINE in words

    decoded = decode_string(words, reverse_charmap)
    assert decoded == text


def test_encode_cyrillic_alphabet(charmap: dict[str, int], reverse_charmap: dict[int, str]):
    """Verify full Russian alphabet (upper and lower case) plus typographic symbols."""
    alphabet = (
        "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
        "«»—…„“ !?,.-:0123456789"
    )
    encoded = encode_string(alphabet, charmap)
    words = [struct.unpack_from(">H", encoded, i)[0] for i in range(0, len(encoded), 2)]
    decoded = decode_string(words, reverse_charmap)
    assert decoded == alphabet


def test_encode_missing_char_raises_error(charmap: dict[str, int]):
    """Characters not in charmap must raise KeyError."""
    with pytest.raises(KeyError, match="not found in charmap"):
        encode_string("Тест \u2603", charmap)


# ---------------------------------------------------------------------------
# 2. Pointer Table Parsing Tests
# ---------------------------------------------------------------------------

def test_parse_synthetic_entry(synthetic_05d_entry: bytes, charmap: dict[str, int]):
    """Test parsing header pointers, pointer table, and strings on synthetic 0x05D."""
    info = parse_inspection_entry(synthetic_05d_entry, entry_index=0x05D, charmap=charmap)

    assert info.entry_index == 0x05D
    assert info.ptr_table_offset == 0x0A08
    assert info.ptr_table_end == 0x0A84
    assert info.num_pointers == 31
    assert len(info.pointers) == 31
    assert info.min_str_offset == 0x0430
    assert len(info.trailing_block) == 16
    assert info.offset_2c_rel == 6
    assert info.offset_30_rel == 0

    # Verify strings extracted
    assert len(info.extracted_strings) == 31
    assert info.extracted_strings[0] == "Потолок таверны."
    assert info.extracted_strings[1] == "Потолок таверны."


def test_parse_real_entry_05d_if_available(sample_disc_bin: Path | None, charmap: dict[str, int]):
    """If disc image is available, parse real 0x05D and verify architecture properties."""
    if sample_disc_bin is None:
        pytest.skip("No disc BIN image available in workspace")

    from tools.patch_inspection import parse_iso_dir, read_extent, read_sector

    pvd = read_sector(sample_disc_bin, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(sample_disc_bin, root_lba, root_size)
    prog_lba, prog_size = root_dir["PROG.UNT"]
    prog_archive = read_extent(sample_disc_bin, prog_lba, prog_size)

    unt_entries = read_unt_index(prog_archive)
    assert len(unt_entries) > 0x05D
    e5d = unt_entries[0x05D]
    data_5d = e5d.extract(prog_archive)

    info = parse_inspection_entry(data_5d, entry_index=0x05D, charmap=charmap)
    assert info.num_pointers == 31
    assert info.min_str_offset == 0x0430
    assert len(info.trailing_block) == 16
    assert len(data_5d) == 4096


# ---------------------------------------------------------------------------
# 3. Round-Trip Rebuild Fidelity Tests
# ---------------------------------------------------------------------------

def test_rebuild_roundtrip(synthetic_05d_entry: bytes, charmap: dict[str, int]):
    """Verify that rebuilding with 31 strings preserves all content and structure."""
    translations_path = REPO_ROOT / "data" / "inspection_ru.json"
    doc = json.loads(translations_path.read_text(encoding="utf-8"))
    ru_strings = doc["entries"]["0x05D"]["strings"]
    assert len(ru_strings) == 31

    rebuilt, result = rebuild_inspection_entry(
        synthetic_05d_entry,
        ru_strings,
        charmap=charmap,
        entry_index=0x05D,
        room_name="БАР",
    )

    # Size checks
    assert len(rebuilt) == 4096
    assert result.allocated_size == 4096
    assert result.used_size <= 4096
    assert result.free_margin >= 0
    assert result.strings_count == 31

    # Re-parse the rebuilt entry
    re_info = parse_inspection_entry(rebuilt, entry_index=0x05D, charmap=charmap)
    assert re_info.num_pointers == 31
    assert re_info.extracted_strings == ru_strings
    assert re_info.extracted_strings[12] == "Подвесная лампа."

    # Verify pointer deduplication between string 0 and 1
    assert re_info.pointer_offsets[0] == re_info.pointer_offsets[1]

    # Verify trailing block intact
    orig_trailing = synthetic_05d_entry[0x0A84 : 0x0A84 + 16]
    assert re_info.trailing_block == orig_trailing


# ---------------------------------------------------------------------------
# 4. Sector Boundary & Budget Constraint Tests
# ---------------------------------------------------------------------------

def test_budget_overflow_raises_error(synthetic_05d_entry: bytes, charmap: dict[str, int]):
    """Rebuilding with massive strings that exceed sector budget must raise ValueError."""
    huge_strings = ["Очень длинная строка текста для проверки переполнения сектора " * 20] * 31

    with pytest.raises(ValueError, match="exceeds allocated capacity"):
        rebuild_inspection_entry(
            synthetic_05d_entry,
            huge_strings,
            charmap=charmap,
            entry_index=0x05D,
        )


def test_free_margin_reporting(synthetic_05d_entry: bytes, charmap: dict[str, int]):
    """Verify free margin calculation."""
    short_strings = ["Кратко."] * 31
    _, result = rebuild_inspection_entry(
        synthetic_05d_entry,
        short_strings,
        charmap=charmap,
        entry_index=0x05D,
    )
    assert result.free_margin > 2000
    assert result.used_size + result.free_margin == 4096


# ---------------------------------------------------------------------------
# 5. data/inspection_ru.json Integrity Tests
# ---------------------------------------------------------------------------

def test_inspection_ru_json_tavern_coverage(charmap: dict[str, int]):
    """Verify data/inspection_ru.json has all 31 strings for Lakewood Tavern (0x05D)."""
    json_path = REPO_ROOT / "data" / "inspection_ru.json"
    assert json_path.is_file(), f"Missing {json_path}"

    doc = json.loads(json_path.read_text(encoding="utf-8"))
    assert "entries" in doc
    assert "0x05D" in doc["entries"]

    entry_5d = doc["entries"]["0x05D"]
    strings = entry_5d["strings"]
    assert len(strings) == 31, f"Expected 31 strings for 0x05D, got {len(strings)}"

    # Specific requirement check: String 12 must be 'Подвесная лампа.'
    assert strings[12] == "Подвесная лампа."

    # Verify every string can be encoded without error
    for idx, s in enumerate(strings):
        try:
            enc = encode_string(s, charmap)
            assert len(enc) > 0
        except KeyError as e:
            pytest.fail(f"String {idx} ({s!r}) failed to encode: {e}")

    # Verify common dictionary
    assert "common" in doc
    assert len(doc["common"]) >= 10
    for key, val in doc["common"].items():
        try:
            enc = encode_string(val, charmap)
            assert len(enc) > 0
        except KeyError as e:
            pytest.fail(f"Common string {val!r} failed to encode: {e}")


# ---------------------------------------------------------------------------
# 6. UNT Archive Patching Tests
# ---------------------------------------------------------------------------

def test_unt_archive_patching():
    """Verify UNT archive parsing, patching, and zero-padding."""
    # Create synthetic 2-entry UNT archive
    # Sector 0: index table
    # Sector 1..2: Entry 0 (2 sectors = 4096 bytes)
    # Sector 3..3: Entry 1 (1 sector = 2048 bytes)
    archive = bytearray(SECTOR_SIZE * 4)

    # Index table in sector 0
    # Entry 0: start=1, count=2
    struct.pack_into("<HH", archive, 0, 1, 2)
    # Entry 1: start=3, count=1
    struct.pack_into("<HH", archive, 4, 3, 1)

    entries = read_unt_index(archive)
    assert len(entries) == 2
    assert entries[0].start_sector == 1
    assert entries[0].sector_count == 2
    assert entries[0].size == 4096
    assert entries[1].start_sector == 3
    assert entries[1].sector_count == 1
    assert entries[1].size == 2048

    # Patch Entry 0 with 100 bytes of data
    payload = b"TEST_PAYLOAD" * 8
    off, alloc, plen = patch_unt_entry(archive, 0, payload)
    assert off == 2048
    assert alloc == 4096
    assert plen == len(payload)

    # Verify data written and padded
    assert archive[2048 : 2048 + len(payload)] == payload
    assert archive[2048 + len(payload) : 2048 + 4096] == b"\x00" * (4096 - len(payload))

    # Patch with payload > allocated must fail
    with pytest.raises(ValueError, match="exceeds allocated budget"):
        patch_unt_entry(archive, 1, b"X" * 3000)


# ---------------------------------------------------------------------------
# 7. Translation Resolution Tests
# ---------------------------------------------------------------------------

def test_resolve_entry_translations_exact_list(synthetic_05d_entry: bytes, charmap: dict[str, int]):
    """Verify resolving translations when exact list is provided."""
    info = parse_inspection_entry(synthetic_05d_entry, entry_index=0x05D, charmap=charmap)
    doc = {
        "entries": {
            "0x05D": {
                "room_name": "БАР",
                "strings": [f"Перевод {i}" for i in range(31)],
            }
        }
    }
    resolved, room_name = resolve_entry_translations(info, doc)
    assert len(resolved) == 31
    assert resolved[0] == "Перевод 0"
    assert room_name == "БАР"


def test_resolve_entry_translations_fallback_common(synthetic_05d_entry: bytes, charmap: dict[str, int]):
    """Verify fallback to common translations for unlisted entries."""
    info = parse_inspection_entry(synthetic_05d_entry, entry_index=0x05E, charmap=charmap)
    doc = {
        "entries": {},
        "common": {
            "Потолок таверны.": "Общий потолок.",
        },
    }
    resolved, room_name = resolve_entry_translations(info, doc)
    assert len(resolved) == 31
    assert resolved[0] == "Общий потолок."
    assert resolved[1] == "Общий потолок."
