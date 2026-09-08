#!/usr/bin/env python3
"""Unit tests for translations/room_inspection_ru.json and tools/build_inspection_translations.py.

Verifies:
1. 100% completeness: all 734 entries have non-empty Russian translations.
2. PS1 layout constraints:
   - Line width <= 15 Unicode characters.
   - Line count between 1 and 3 lines per string (delimited by \n).
   - NFC Unicode normalization.
3. Character set validity: 100% of characters exist in Cyrillic charmap (DEFAULT_CHARMAP).
4. Schema integrity: JSON keys, type ("name"|"description"), rooms, frequency preserved.
5. Voice and tone consistency: iconic Lina Inverse commentary and object names.
6. Build pipeline idempotence: build_inspection_translations produces deterministic output.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

import pytest

# Ensure repository root and patch_repo are in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))

from tools.build_inspection_translations import (
    DEFAULT_CATALOG_PATH,
    RAW_INSPECTION_TRANSLATIONS,
    build_inspection_translations,
    validate_inspection_string,
    wrap_inspection_string,
)
from tools.patch_inspection import DEFAULT_CHARMAP, load_charmap


@pytest.fixture(scope="module")
def catalog() -> dict[str, dict]:
    """Load the Russian room inspection translations catalog."""
    assert DEFAULT_CATALOG_PATH.is_file(), f"Missing catalog file: {DEFAULT_CATALOG_PATH}"
    data = json.loads(DEFAULT_CATALOG_PATH.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def charmap() -> dict[str, int]:
    """Load canonical Slayers Royal Cyrillic charmap."""
    return load_charmap()


def test_catalog_completeness(catalog: dict[str, dict]):
    """Verify 100% of the 734 unique entries have non-empty Russian translations."""
    assert len(catalog) == 734, f"Expected exactly 734 entries, got {len(catalog)}"

    empty_translations = []
    for eng_text, entry in catalog.items():
        ru = entry.get("russian", "")
        if not ru or not isinstance(ru, str) or not ru.strip():
            empty_translations.append(eng_text)

    assert len(empty_translations) == 0, (
        f"Found {len(empty_translations)} untranslated entries: {empty_translations[:5]}"
    )


def test_line_length_constraints(catalog: dict[str, dict]):
    """Verify that zero lines exceed 15 Unicode characters across all 734 entries."""
    violations = []
    for eng_text, entry in catalog.items():
        ru = entry["russian"]
        lines = ru.split("\n")
        for line_num, line in enumerate(lines, 1):
            if len(line) > 15:
                violations.append(
                    f"{eng_text!r} line {line_num} has {len(line)} chars: {line!r}"
                )

    assert len(violations) == 0, (
        f"Found {len(violations)} line length violations (>15 chars):\n"
        + "\n".join(violations[:10])
    )


def test_line_count_constraints(catalog: dict[str, dict]):
    """Verify that every entry has between 1 and 3 lines (0 lines or >3 lines prohibited)."""
    violations = []
    line_counts = {1: 0, 2: 0, 3: 0}

    for eng_text, entry in catalog.items():
        ru = entry["russian"]
        lines = ru.split("\n")
        count = len(lines)
        if count < 1 or count > 3:
            violations.append(
                f"{eng_text!r} has {count} lines (must be 1..3): {ru!r}"
            )
        else:
            line_counts[count] += 1

    assert len(violations) == 0, (
        f"Found {len(violations)} line count violations:\n"
        + "\n".join(violations[:10])
    )
    # Ensure reasonable distribution across 1, 2, and 3 lines
    assert line_counts[1] > 0, "No 1-line translations found"
    assert line_counts[2] > 0, "No 2-line translations found"
    assert line_counts[3] > 0, "No 3-line translations found"
    assert sum(line_counts.values()) == 734


def test_charmap_validity(catalog: dict[str, dict], charmap: dict[str, int]):
    """Verify that 100% of characters in Russian translations exist in DEFAULT_CHARMAP."""
    invalid_chars = {}
    for eng_text, entry in catalog.items():
        ru = entry["russian"]
        for line in ru.split("\n"):
            for ch in line:
                if ch not in charmap:
                    invalid_chars.setdefault(ch, []).append((eng_text, line))

    assert len(invalid_chars) == 0, (
        f"Found unsupported glyphs not in charmap: "
        f"{[f'{ch!r} ({ord(ch):#06x})' for ch in invalid_chars]}"
    )


def test_unicode_normalization(catalog: dict[str, dict]):
    """Verify that all Russian strings are normalized to NFC Unicode."""
    denormalized = []
    for eng_text, entry in catalog.items():
        ru = entry["russian"]
        if ru != unicodedata.normalize("NFC", ru):
            denormalized.append(eng_text)

    assert len(denormalized) == 0, (
        f"Found {len(denormalized)} non-NFC strings: {denormalized[:5]}"
    )


def test_schema_integrity(catalog: dict[str, dict]):
    """Verify that JSON metadata (type, rooms, frequency) is intact for every entry."""
    total_frequency = 0
    all_rooms = set()

    for eng_text, entry in catalog.items():
        assert "type" in entry, f"Missing 'type' in {eng_text!r}"
        assert entry["type"] in ("name", "description"), f"Invalid type in {eng_text!r}"

        assert "rooms" in entry, f"Missing 'rooms' in {eng_text!r}"
        assert isinstance(entry["rooms"], list) and len(entry["rooms"]) > 0

        for r in entry["rooms"]:
            assert r.startswith("0x")
            room_id = int(r, 16)
            assert 0x059 <= room_id <= 0x0F8
            all_rooms.add(r)

        assert "frequency" in entry, f"Missing 'frequency' in {eng_text!r}"
        assert isinstance(entry["frequency"], int)
        assert entry["frequency"] >= len(entry["rooms"])
        total_frequency += entry["frequency"]

    assert len(all_rooms) == 38, f"Expected 38 active rooms, got {len(all_rooms)}"
    assert total_frequency == 943, f"Expected 943 total instances, got {total_frequency}"


def test_voice_and_character_consistency(catalog: dict[str, dict]):
    """Spot-check iconic translations reflecting Lina Inverse's voice and lore."""
    # 1. Gourry height comparison
    gourry_tree = "It's a tree\nabout twice the\nheight of"
    assert gourry_tree in catalog
    assert "Гаури" in catalog[gourry_tree]["russian"]

    # 2. Zelgadis weight comparison
    zel_table = "If Zelgadis\nstood on it,\nit'd collapse."
    assert zel_table in catalog
    assert "Зелгадис" in catalog[zel_table]["russian"]

    # 3. Mazoku knowledge
    mazoku_line = "I know plenty\nabout Mazoku."
    assert mazoku_line in catalog
    assert "мазоку" in catalog[mazoku_line]["russian"]

    # 4. Bust potion running gag
    bust_potion = "She fell for a\nbust potion,\nthen worked for"
    assert bust_potion in catalog
    assert "груди" in catalog[bust_potion]["russian"]

    # 5. Hanging lamp example
    lamp = "A hanging lamp."
    assert lamp in catalog
    assert catalog[lamp]["russian"] == "Подвесная\nлампа."

    # 6. Coin search between paving stones
    coins = "Coins get stuck\nbetween stones\nlike these..."
    assert coins in catalog
    assert "монет" in catalog[coins]["russian"]


def test_build_pipeline_idempotence(tmp_path: Path, catalog: dict[str, dict]):
    """Verify build_inspection_translations runs idempotently without altering valid output."""
    temp_catalog_file = tmp_path / "test_catalog.json"
    temp_catalog_file.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    rebuilt = build_inspection_translations(
        catalog_path=temp_catalog_file,
        dry_run=False,
        verbose=False,
    )

    assert len(rebuilt) == 734
    for key in catalog:
        assert rebuilt[key]["russian"] == catalog[key]["russian"]
