#!/usr/bin/env python3
"""Unit tests for tools/extract_all_inspection_strings.py and translations/room_inspection_ru.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.extract_all_inspection_strings import (
    DEFAULT_OUTPUT_PATH,
    DEFAULT_TRANSLATIONS_PATH,
    classify_string_role,
    extract_inspection_catalog,
)
from tools.patch_inspection import DEFAULT_CHARMAP, encode_string


@pytest.fixture
def catalog() -> dict[str, dict]:
    """Load the generated room inspection translations catalog."""
    assert DEFAULT_OUTPUT_PATH.is_file(), f"Missing {DEFAULT_OUTPUT_PATH}"
    data = json.loads(DEFAULT_OUTPUT_PATH.read_text(encoding="utf-8"))
    return data


def test_catalog_size(catalog: dict[str, dict]):
    """Verify exact count of 734 unique room inspection strings."""
    assert len(catalog) == 734, f"Expected 734 entries, got {len(catalog)}"


def test_catalog_structure(catalog: dict[str, dict]):
    """Verify schema of every entry in the catalog."""
    total_frequency = 0
    all_rooms = set()

    for text, entry in catalog.items():
        assert isinstance(text, str) and len(text) > 0, "Empty string key found"
        assert text != "UNDER\nCONSTRUCTION", "Engine placeholder not filtered"

        assert "russian" in entry, f"Missing 'russian' in {text!r}"
        assert isinstance(entry["russian"], str), f"'russian' not string in {text!r}"

        assert "type" in entry, f"Missing 'type' in {text!r}"
        assert entry["type"] in ("name", "description"), f"Invalid type in {text!r}: {entry['type']}"

        assert "rooms" in entry, f"Missing 'rooms' in {text!r}"
        assert isinstance(entry["rooms"], list), f"'rooms' not list in {text!r}"
        assert len(entry["rooms"]) > 0, f"'rooms' empty in {text!r}"

        for r in entry["rooms"]:
            assert r.startswith("0x"), f"Room {r!r} not formatted as hex"
            r_int = int(r, 16)
            assert 0x059 <= r_int <= 0x0F8, f"Room {r} out of range 0x059..0x0F8"
            all_rooms.add(r)

        assert "frequency" in entry, f"Missing 'frequency' in {text!r}"
        assert isinstance(entry["frequency"], int), f"'frequency' not int in {text!r}"
        assert entry["frequency"] >= len(entry["rooms"]), f"Frequency < len(rooms) in {text!r}"

        total_frequency += entry["frequency"]

    # Exactly 943 total string instances across all rooms
    assert total_frequency == 943
    # 38 rooms contain active non-placeholder inspection text (57 have UNDER CONSTRUCTION, 54 are empty)
    assert len(all_rooms) == 38


def test_hanging_lamp_example(catalog: dict[str, dict]):
    """Verify specific example from Task 1 Brief: 'A hanging lamp.'."""
    target = "A hanging lamp."
    assert target in catalog
    entry = catalog[target]

    assert entry["russian"] == "Подвесная лампа."
    assert entry["type"] == "name"
    assert entry["rooms"] == ["0x05D", "0x098", "0x0C5"]
    assert entry["frequency"] == 3


def test_prepopulated_translations(catalog: dict[str, dict]):
    """Verify pre-population from data/inspection_ru.json."""
    assert DEFAULT_TRANSLATIONS_PATH.is_file()
    doc = json.loads(DEFAULT_TRANSLATIONS_PATH.read_text(encoding="utf-8"))

    # Common strings
    common = doc.get("common", {})
    for eng_k, ru_v in common.items():
        if eng_k in catalog:
            assert catalog[eng_k]["russian"] == ru_v, f"Mismatch for common string {eng_k!r}"

    # Verify at least 38 strings are pre-populated
    prepopulated_count = sum(1 for v in catalog.values() if v["russian"])
    assert prepopulated_count >= 38


def test_classification_logic():
    """Verify string role classification logic."""
    assert classify_string_role("A window.", {"A window.": 6}, {"A window.": 10}) == "name"
    assert classify_string_role("The innkeeper.", {"The innkeeper.": 5}, {"The innkeeper.": 6}) == "name"
    assert classify_string_role("Let's go\nsomewhere else.", {"Let's go\nsomewhere else.": 1}, {"Let's go\nsomewhere else.": 4}) == "description"
    assert classify_string_role("Pure Name.", {"Pure Name.": 2}, {}) == "name"
    assert classify_string_role("Pure Desc.", {}, {"Pure Desc.": 2}) == "description"
