"""Unit tests for tools/sync_story_dialogues.py.

Verifies:
- PS1 hardware line length (<= 15 characters)
- PS1 page line limits (1..3 nonempty lines per page)
- Form feed (\\f) page breaks allowed only when allow_page_break is True
- Unicode NFC normalization
- Round-trip integrity between PO and JSON
- Lossless preservation of PO comments and engine controls
- sync-if-newer timestamp logic
- Full integrity of production translations/story_dialogues_ru.json
- Full integrity of translations/translations_index.json
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

import pytest

# Add repo root and patch_repo to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))

from localization.po import PoEntry, read_po, write_po
from tools.sync_story_dialogues import (
    DEFAULT_JSON_PATH,
    DEFAULT_PO_PATH,
    MAX_CHARS_PER_LINE,
    MAX_LINES_PER_PAGE,
    MIN_LINES_PER_PAGE,
    SPEAKERS_GLOSSARY,
    TOTAL_EXPECTED_ENTRIES,
    TOTAL_EXPECTED_SCENES,
    apply_dialogues,
    export_dialogues,
    parse_entry_comments,
    sync_if_newer,
    validate_catalog,
    validate_dialogue_text,
)


class TestValidationRules:
    """Test unit validation rules for individual dialogue lines."""

    def test_valid_single_line(self):
        errors = validate_dialogue_text("Привет, Лина!", allow_page_break=True, context="test/01")
        assert not errors

    def test_valid_three_lines(self):
        text = "Строка один\nСтрока два\nСтрока три"
        errors = validate_dialogue_text(text, allow_page_break=True, context="test/02")
        assert not errors

    def test_valid_multi_page_with_page_break(self):
        text = "Страница 1\nСтрока 2\fСтраница 2\nСтрока 2"
        errors = validate_dialogue_text(text, allow_page_break=True, context="test/03")
        assert not errors

    def test_line_too_long(self):
        # 16 characters -> should fail
        text = "1234567890123456"
        errors = validate_dialogue_text(text, allow_page_break=True, context="test/too_long")
        assert len(errors) == 1
        assert "16 символов" in errors[0]
        assert "максимум 15" in errors[0]

    def test_exactly_fifteen_chars_allowed(self):
        text = "123456789012345"
        errors = validate_dialogue_text(text, allow_page_break=True, context="test/15_chars")
        assert not errors

    def test_too_many_lines_in_page(self):
        text = "Раз\nДва\nТри\nЧетыре"
        errors = validate_dialogue_text(text, allow_page_break=True, context="test/4_lines")
        assert len(errors) == 1
        assert "содержит 4 строк" in errors[0]

    def test_empty_line_forbidden(self):
        text = "Линия 1\n\nЛиния 2"
        errors = validate_dialogue_text(text, allow_page_break=True, context="test/empty_line")
        assert len(errors) == 1
        assert "пустая" in errors[0]

    def test_page_break_forbidden_for_ff(self):
        text = "Стр 1\fСтр 2"
        errors = validate_dialogue_text(text, allow_page_break=False, context="test/no_ff")
        assert len(errors) == 1
        assert "не поддерживает разделение страниц" in errors[0]

    def test_carriage_return_forbidden(self):
        text = "Линия 1\r\nЛиния 2"
        errors = validate_dialogue_text(text, allow_page_break=True, context="test/cr")
        assert any("возврата каретки" in err for err in errors)

    def test_decomposed_unicode_rejected(self):
        # Combining character (NFD) instead of NFC
        decomposed = "е" + "\u0308"  # ё in NFD
        errors = validate_dialogue_text(decomposed, allow_page_break=True, context="test/nfd")
        assert any("NFC" in err for err in errors)

    def test_composed_unicode_accepted(self):
        composed = "ё"
        errors = validate_dialogue_text(composed, allow_page_break=True, context="test/nfc")
        assert not errors


class TestCommentParsing:
    """Test extracting metadata from PO comments."""

    def test_parse_comments_full(self):
        comments = (
            "PROG entry 0x03B; tagged; record E000",
            "Target layout: at most 3 lines per page and 15 characters per line.",
            "Use \\f between additional pages when needed.",
            "Probable speaker: Lina",
            "Preserved engine controls: 9101 D124",
        )
        meta = parse_entry_comments(comments)
        assert meta["family"] == "tagged"
        assert meta["speaker"] == "Lina"
        assert meta["allow_page_break"] is True
        assert meta["controls"] == ["9101", "D124"]

    def test_parse_comments_ff_no_controls(self):
        comments = (
            "PROG entry 0x040; untagged_linear; record U040-S001",
            "Target layout: at most 3 lines per page and 15 characters per line.",
            "This FF segment cannot add another page; shorten to fit.",
        )
        meta = parse_entry_comments(comments)
        assert meta["family"] == "untagged_linear"
        assert meta["speaker"] is None
        assert meta["allow_page_break"] is False
        assert meta["controls"] == []


class TestRoundtripAndApply:
    """Test PO <-> JSON bidirectional conversion."""

    def test_roundtrip_synthetic(self, tmp_path):
        po_file = tmp_path / "test.po"
        json_file = tmp_path / "test.json"

        entries = [
            PoEntry(
                context="dialogue/03B/E000/000",
                source="こんにちは",
                translation="Привет!",
                comments=(
                    "PROG entry 0x03B; tagged; record E000",
                    "Target layout: at most 3 lines per page and 15 characters per line.",
                    "Use \\f between additional pages when needed.",
                    "Probable speaker: Lina",
                    "Preserved engine controls: 9101",
                ),
            ),
            PoEntry(
                context="dialogue/03B/E001/000",
                source="さようなら",
                translation="Пока!",
                comments=(
                    "PROG entry 0x03B; tagged; record E001",
                    "Target layout: at most 3 lines per page and 15 characters per line.",
                    "This FF segment cannot add another page; shorten to fit.",
                    "Probable speaker: Gourry",
                ),
            ),
        ]
        write_po(po_file, entries, "Russian")

        # 1. Export to JSON
        data = export_dialogues(po_file, json_file)
        assert json_file.exists()
        assert data["metadata"]["total_entries"] == 2
        assert len(data["scenes"]) == 1
        assert data["scenes"][0]["scene_id"] == "03B"

        d0 = data["scenes"][0]["dialogues"][0]
        assert d0["speaker"] == "Lina"
        assert d0["speaker_ru"] == "Лина"
        assert d0["allow_page_break"] is True
        assert d0["controls"] == ["9101"]

        d1 = data["scenes"][0]["dialogues"][1]
        assert d1["speaker"] == "Gourry"
        assert d1["speaker_ru"] == "Гаури"
        assert d1["allow_page_break"] is False

        # 2. Modify JSON text and apply back
        with open(json_file, "r", encoding="utf-8") as f:
            j_data = json.load(f)
        j_data["scenes"][0]["dialogues"][0]["text_ru"] = "Привет,\nмир!"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(j_data, f, ensure_ascii=False, indent=2)

        changed = apply_dialogues(json_file, po_file)
        assert changed == 1

        updated_po = read_po(po_file)
        assert updated_po[0].translation == "Привет,\nмир!"
        assert updated_po[0].comments == entries[0].comments
        assert updated_po[1].translation == "Пока!"

    def test_apply_rejects_invalid_json(self, tmp_path):
        po_file = tmp_path / "test.po"
        json_file = tmp_path / "test.json"

        entries = [
            PoEntry(
                context="dialogue/03B/E000/000",
                source="test",
                translation="valid line",
                comments=(
                    "PROG entry 0x03B; tagged; record E000",
                    "Use \\f between additional pages when needed.",
                ),
            )
        ]
        write_po(po_file, entries, "Russian")
        export_dialogues(po_file, json_file)

        # Inject line exceeding 15 chars
        with open(json_file, "r", encoding="utf-8") as f:
            j_data = json.load(f)
        j_data["scenes"][0]["dialogues"][0]["text_ru"] = "Очень длинная строка больше 15"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(j_data, f, ensure_ascii=False, indent=2)

        with pytest.raises(ValueError, match="Cannot apply invalid JSON catalog"):
            apply_dialogues(json_file, po_file)

        # Ensure PO was NOT modified
        po_after = read_po(po_file)
        assert po_after[0].translation == "valid line"


class TestSyncIfNewer:
    """Test timestamp-based automatic synchronization."""

    def test_sync_if_newer(self, tmp_path):
        po_file = tmp_path / "test.po"
        json_file = tmp_path / "test.json"

        entries = [
            PoEntry(
                context="dialogue/03B/E000/000",
                source="test",
                translation="Строка 1",
                comments=(
                    "PROG entry 0x03B; tagged; record E000",
                    "Use \\f between additional pages when needed.",
                ),
            )
        ]
        write_po(po_file, entries, "Russian")
        export_dialogues(po_file, json_file)

        # Immediately after export, PO is not older than JSON (or equal)
        # Touch PO to make it newer
        time.sleep(0.05)
        po_file.touch()
        assert not sync_if_newer(json_file, po_file)

        # Now touch JSON to make it newer
        time.sleep(0.05)
        json_file.touch()
        assert sync_if_newer(json_file, po_file)


class TestProductionCatalogsIntegrity:
    """Verify the actual production catalog files in the repository."""

    def test_story_dialogues_ru_json_exists_and_valid(self):
        assert DEFAULT_JSON_PATH.exists(), f"Missing {DEFAULT_JSON_PATH}"

        is_valid, errors = validate_catalog(DEFAULT_JSON_PATH)
        assert is_valid, f"Validation failed with {len(errors)} errors: {errors[:5]}"

        with open(DEFAULT_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["metadata"]["total_scenes"] == TOTAL_EXPECTED_SCENES
        assert data["metadata"]["total_entries"] == TOTAL_EXPECTED_ENTRIES
        assert len(data["scenes"]) == TOTAL_EXPECTED_SCENES

        total_dialogues = sum(len(s["dialogues"]) for s in data["scenes"])
        assert total_dialogues == TOTAL_EXPECTED_ENTRIES

    def test_translations_index_json_exists_and_valid(self):
        index_path = REPO_ROOT / "translations" / "translations_index.json"
        assert index_path.exists(), f"Missing {index_path}"

        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "catalogs" in data
        assert len(data["catalogs"]) == 14

        catalog_ids = {c["id"] for c in data["catalogs"]}
        expected_ids = {
            "story_dialogues",
            "combat_dialogues",
            "room_inspection",
            "minigames",
            "town_services",
            "shop_dialogues",
            "lore_cards",
            "world_map",
            "location_banners",
            "room_names",
            "minigames_menu",
            "bonus_menu",
            "town_maps",
            "custom_screens",
        }

        # Check all referenced files exist
        for cat in data["catalogs"]:
            cat_file = REPO_ROOT / cat["file"]
            assert cat_file.exists(), f"Catalog file not found: {cat['file']}"
