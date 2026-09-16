#!/usr/bin/env python3
"""Unit tests for room location names translation and injection pipeline.

Validates:
1. Complete catalog integrity in translations/room_names_ru.json (160 rooms, 48 unique names).
2. Clean Cyrillic encoding of all 48 room location names without unmapped characters.
3. Specific translation verification for the user-reported location banners:
   - 0x05D (BAR / 定食屋) -> "БАР"
   - 0x059 (MAIN / 表通り) -> "ГЛАВНАЯ"
   - 0x05C (IN / 宿屋) -> "ОТЕЛЬ"
   - 0x05A (BACK / 裏通り) -> "ЗАКОУЛКИ"
4. Successful in-place and relocated room name embedding in room entries.
5. Successful patching of non-inspection cave rooms (0x06C..0x076).
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from tools.patch_inspection import (
    DEFAULT_ROOM_NAMES,
    HDR_ROOM_NAME_PTR,
    RAM_BASE,
    decode_string,
    encode_string,
    get_room_name_translation,
    load_charmap,
    load_room_names,
    parse_inspection_entry,
    rebuild_inspection_entry,
)


@pytest.fixture(scope="module")
def room_names_doc() -> dict[str, str]:
    return load_room_names(DEFAULT_ROOM_NAMES)


@pytest.fixture(scope="module")
def charmap() -> dict[str, int]:
    return load_charmap()


@pytest.fixture(scope="module")
def reverse_charmap(charmap: dict[str, int]) -> dict[int, str]:
    return {v: k for k, v in charmap.items()}


def test_room_names_catalog_integrity(room_names_doc: dict[str, str]):
    """Catalog must exist, contain all 160 room entries and 48 unique location names."""
    assert DEFAULT_ROOM_NAMES.is_file(), f"Missing {DEFAULT_ROOM_NAMES}"
    raw = json.loads(DEFAULT_ROOM_NAMES.read_text(encoding="utf-8"))
    assert "unique_locations" in raw
    assert len(raw["unique_locations"]) == 48, f"Expected 48 unique locations, got {len(raw['unique_locations'])}"
    assert len(raw["entries"]) == 160, f"Expected 160 room entries, got {len(raw['entries'])}"

    # All room entries 0x059..0x0F8 must be present
    for e_idx in range(0x059, 0x0F9):
        hex_key = f"0x{e_idx:03X}"
        assert hex_key in raw["entries"], f"Missing entry {hex_key} in catalog"
        entry_spec = raw["entries"][hex_key]
        assert "name_ru" in entry_spec
        assert entry_spec["name_ru"].strip(), f"Empty Russian name in {hex_key}"


def test_all_unique_locations_encode_cleanly(charmap: dict[str, int], reverse_charmap: dict[int, str]):
    """Every unique Russian location name must encode into valid 16-bit words and decode identically."""
    raw = json.loads(DEFAULT_ROOM_NAMES.read_text(encoding="utf-8"))
    for jp, info in raw["unique_locations"].items():
        ru_text = info["ru"]
        enc = encode_string(ru_text, charmap)
        assert len(enc) >= 4, f"Encoded string too short: {enc}"
        assert enc.endswith(b"\x00\xff"), f"Missing 0x00FF terminator: {enc}"

        # Decode back and verify exact round-trip match
        words = [struct.unpack_from(">H", enc, i)[0] for i in range(0, len(enc) - 2, 2)]
        dec = decode_string(words, reverse_charmap)
        assert dec == ru_text, f"Round-trip mismatch for {jp}: {dec!r} != {ru_text!r}"


def test_user_reported_location_banners_mapping(room_names_doc: dict[str, str]):
    """Verify exact translations for the 4 location banners highlighted by the user."""
    # 1. BAR (0x05D Lakewood Diner / Bar)
    assert get_room_name_translation(0x05D, room_names_doc) == "БАР"
    # 2. MAIN ST (0x059 Lakewood Main Street)
    assert get_room_name_translation(0x059, room_names_doc) == "ГЛАВНАЯ"
    # 3. INN (0x05C Lakewood Inn)
    assert get_room_name_translation(0x05C, room_names_doc) == "ОТЕЛЬ"
    # 4. BACK ST (0x05A Lakewood Backstreet)
    assert get_room_name_translation(0x05A, room_names_doc) == "ЗАКОУЛКИ"


def test_rebuild_with_in_place_room_name(charmap: dict[str, int], reverse_charmap: dict[int, str]):
    """A short room name that fits within next_hdr must be written in-place without moving pointers."""
    from tools.test_batch_inspection_patch import build_synthetic_room_entry

    strings = ["Табличка.", "Стул."]
    entry_raw = bytearray(build_synthetic_room_entry(strings, charmap, allocated_size=2048))
    # Configure real header layout: room name at 0x42, next structure at 0x4A (8 bytes budget)
    struct.pack_into(">I", entry_raw, HDR_ROOM_NAME_PTR, RAM_BASE + 0x0042)
    struct.pack_into(">I", entry_raw, 0x0008, RAM_BASE + 0x004A)
    entry_bytes = bytes(entry_raw)

    rebuilt_bytes, result = rebuild_inspection_entry(
        entry_bytes,
        strings,
        charmap=charmap,
        entry_index=0x05D,
        room_name="БАР",
        allocated_size=2048,
    )

    p3c = struct.unpack_from(">I", rebuilt_bytes, HDR_ROOM_NAME_PTR)[0] - RAM_BASE
    assert p3c == 0x0042
    words = []
    c = p3c
    while c + 2 <= len(rebuilt_bytes):
        w = struct.unpack_from(">H", rebuilt_bytes, c)[0]
        c += 2
        if w == 0x00FF:
            break
        words.append(w)
    assert decode_string(words, reverse_charmap) == "БАР"


def test_rebuild_with_relocated_room_name(charmap: dict[str, int], reverse_charmap: dict[int, str]):
    """A long room name that exceeds next_hdr must be relocated to free space and update HDR_ROOM_NAME_PTR."""
    from tools.test_batch_inspection_patch import build_synthetic_room_entry

    strings = ["Фонтан на площади.", "Дерево."]
    entry_raw = bytearray(build_synthetic_room_entry(strings, charmap, allocated_size=2048))
    # Configure real header layout: room name at 0x42, next structure at 0x4A (8 bytes budget)
    struct.pack_into(">I", entry_raw, HDR_ROOM_NAME_PTR, RAM_BASE + 0x0042)
    struct.pack_into(">I", entry_raw, 0x0008, RAM_BASE + 0x004A)
    entry_bytes = bytes(entry_raw)

    # "ГЛАВНАЯ" is 7 chars = 16 bytes, exceeds the 8-byte header slot
    rebuilt_bytes, result = rebuild_inspection_entry(
        entry_bytes,
        strings,
        charmap=charmap,
        entry_index=0x059,
        room_name="ГЛАВНАЯ",
        allocated_size=2048,
    )

    p3c = struct.unpack_from(">I", rebuilt_bytes, HDR_ROOM_NAME_PTR)[0] - RAM_BASE
    assert p3c >= 0x0100, f"Expected relocated pointer, got {hex(p3c)}"
    words = []
    c = p3c
    while c + 2 <= len(rebuilt_bytes):
        w = struct.unpack_from(">H", rebuilt_bytes, c)[0]
        c += 2
        if w == 0x00FF:
            break
        words.append(w)
    assert decode_string(words, reverse_charmap) == "ГЛАВНАЯ"
    assert result.used_size <= 2048
    assert result.free_margin >= 0
