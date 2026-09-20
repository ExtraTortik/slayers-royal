#!/usr/bin/env python3
"""Unit tests for tools/patch_spells.py.

Covers:
1. Encoding format per entry (title + delimiter 0x00A3 0x00A3 + pages + 0x00FF).
2. Budget validation (<= 2048 bytes per entry) for all 119 entries.
3. 100% round-trip decoding for all 119 spells and combat options.
4. Handling of empty pages (e.g., entry 325 'СПРАВКА ПО МАГИИ').
5. Proper encoding of special characters ('★' -> 0x0256).
6. Overflow validation (> 2048 bytes raises ValueError).
7. In-place disc patching and Mode 2 Form 1 EDC/ECC recalculation and verification.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from localization.disc import (
    CdChecksums,
    RAW_SECTOR_SIZE,
    USER_DATA_OFFSET,
    USER_DATA_SIZE,
    read_extent,
)
from tools.combat_dialogue_charmap import (
    build_combat_dialogue_charmap,
    build_reverse_charmap,
    encode_combat_dialogue_string,
    decode_combat_dialogue_string,
    COMBAT_CHARMAP,
    REVERSE_COMBAT_CHARMAP,
)
from tools.patch_spells import (
    DELIMITER_QUOTE,
    DELIMITER_COLON,
    ENTRY_SECTOR_SIZE,
    OPCODE_NEWLINE,
    OPCODE_PAGE_BREAK,
    OPCODE_TERMINATOR,
    SPELLS_COUNT,
    SPELLS_FIRST_ENTRY,
    SPELLS_LAST_ENTRY,
    ENTRY_COMBAT_DATA,
    ENTRY_007_SECTORS,
    ENTRY_007_SPELL_MENU_START,
    ENTRY_007_SPELL_MENU_END,
    ENTRY_007_SPELL_MENU_SIZE,
    ENTRY_007_CLEAN_SPELL_MENU_BYTES,
    ENTRY_007_RU_SPELL_MENU_BYTES,
    ENTRY_007_RU_POINTER_BYTES,
    ENTRY_007_POINTER_TABLE_START,
    OFFSET_MIPS_INIT_EXIT,
    OFFSET_SYSTEM_BUTTONS_START,
    OFFSET_SYSTEM_BUTTONS_END,
    OFFSET_TABLE2_START,
    OFFSET_DIALOGUES_START,
    OFFSET_DIALOGUES_END,
    OFFSET_TABLE3_START,
    SECTION_SPELL_IDS,
    SECTION_BUDGETS,
    SECTION_OFFSETS,
    get_prog_unt_entry_extent,
    patch_spell_menu_in_entry_007,
    decode_spell,
    encode_spell,
    get_prog_unt_spells_extent,
    patch_spells,
    verify_spells_on_disc,
)

CATALOG_PATH = REPO_ROOT / "translations" / "spells_ru.json"
SAMPLE_BIN_PATHS = [
    REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin",
    REPO_ROOT / "build" / "en_patched" / "sr_patched.bin",
    REPO_ROOT / "downloads" / "sr.bin",
]


@pytest.fixture
def spells_catalog() -> list[dict]:
    assert CATALOG_PATH.is_file(), f"Catalog not found at {CATALOG_PATH}"
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    assert len(data) == SPELLS_COUNT, f"Expected {SPELLS_COUNT} entries, got {len(data)}"
    return data


@pytest.fixture
def available_disc() -> Path:
    for p in SAMPLE_BIN_PATHS:
        if p.is_file():
            return p
    pytest.skip("No sample PS1 BIN image found for disc tests")


class TestSpellEncoding:
    """Tests for individual spell binary encoding and structure."""

    def test_encode_spell_basic_structure(self):
        """Test encoding of a standard spell entry with pages."""
        entry = {
            "entry_index": 326,
            "title_ru": "Холи Блесс",
            "pages_ru": [
                "Очищает нежить,\nвключая призраков.",
                "Действует на всю нежить\nна карте боя.",
            ],
        }
        raw = encode_spell(entry)
        assert len(raw) == ENTRY_SECTOR_SIZE, f"Sector size must be {ENTRY_SECTOR_SIZE}"

        words = list(struct.unpack(f"<{ENTRY_SECTOR_SIZE // 2}H", raw))
        assert OPCODE_TERMINATOR in words, "Must contain 0x00FF terminator"
        term_idx = words.index(OPCODE_TERMINATOR)

        # Everything after 0x00FF must be zero padding
        assert all(w == 0 for w in words[term_idx + 1:]), "Trailing bytes must be 0x00"

        # Check delimiter [0x00BC, 0x00FE] (colon + newline)
        delim_indices = [
            i for i in range(term_idx - 1)
            if words[i] == DELIMITER_COLON and words[i + 1] == OPCODE_NEWLINE
        ]
        assert len(delim_indices) == 1, "Must contain exactly one delimiter [0x00BC, 0x00FE]"
        d = delim_indices[0]

        # Before delimiter is title
        title_words = words[:d]
        rev = build_reverse_charmap()
        title_text = decode_combat_dialogue_string(struct.pack(f"<{len(title_words)}H", *title_words), rev)
        assert title_text == "Холи Блесс"

        # After delimiter are pages separated by 0x00FD
        body_words = words[d + 2:term_idx]
        assert OPCODE_PAGE_BREAK in body_words, "Must contain 0x00FD between pages"

    def test_encode_spell_empty_pages(self):
        """Test encoding of entry with empty pages (entry 325 'СПРАВКА ПО МАГИИ')."""
        entry = {
            "entry_index": 325,
            "title_ru": "СПРАВКА ПО МАГИИ",
            "pages_ru": [],
        }
        raw = encode_spell(entry)
        assert len(raw) == ENTRY_SECTOR_SIZE

        words = list(struct.unpack(f"<{ENTRY_SECTOR_SIZE // 2}H", raw))
        assert OPCODE_TERMINATOR in words
        term_idx = words.index(OPCODE_TERMINATOR)

        # Check delimiter is present (colon + newline)
        assert words[term_idx - 2] == DELIMITER_COLON
        assert words[term_idx - 1] == OPCODE_NEWLINE

        title, pages = decode_spell(raw)
        assert title == "СПРАВКА ПО МАГИИ"
        assert pages == []

    def test_decode_spell_legacy_delimiter(self):
        """Verify that decode_spell continues to support legacy quote delimiter [0x00A3, 0x00A3]."""
        entry = {
            "entry_index": 326,
            "title_ru": "Холи Блесс",
            "pages_ru": ["Очищает нежить,\nвключая призраков."],
        }
        cm = build_combat_dialogue_charmap()
        title_bytes = encode_combat_dialogue_string(entry["title_ru"], cm)
        page_bytes = encode_combat_dialogue_string(entry["pages_ru"][0], cm)
        words = list(struct.unpack(f"<{len(title_bytes)//2}H", title_bytes))
        words.extend([DELIMITER_QUOTE, DELIMITER_QUOTE])
        words.extend(struct.unpack(f"<{len(page_bytes)//2}H", page_bytes))
        words.append(OPCODE_TERMINATOR)
        raw = struct.pack(f"<{len(words)}H", *words).ljust(ENTRY_SECTOR_SIZE, b"\x00")
        dec_title, dec_pages = decode_spell(raw)
        assert dec_title == "Холи Блесс"
        assert dec_pages == ["Очищает нежить,\nвключая призраков."]

    def test_special_star_character_encoding(self):
        """Verify that '★' is encoded as 0x0256 and round-trips cleanly."""
        entry = {
            "entry_index": 420,
            "title_ru": "★★ АНИМАЦИЯ ★★",
            "pages_ru": ["АНИМАЦИЯ БОЯ: ВКЛ"],
        }
        raw = encode_spell(entry)
        words = list(struct.unpack(f"<{ENTRY_SECTOR_SIZE // 2}H", raw))
        # First two words should be 0x0256 (for '★★')
        assert words[0] == 0x0256
        assert words[1] == 0x0256

        dec_title, dec_pages = decode_spell(raw)
        assert dec_title == "★★ АНИМАЦИЯ ★★"
        assert dec_pages == ["АНИМАЦИЯ БОЯ: ВКЛ"]

    def test_overflow_raises_value_error(self):
        """Verify that attempting to encode > 2048 bytes raises ValueError."""
        entry = {
            "entry_index": 999,
            "title_ru": "ДЛИННОЕ ЗАКЛИНАНИЕ",
            "pages_ru": ["Очень длинный текст страницы " * 100 for _ in range(5)],
        }
        with pytest.raises(ValueError, match="exceeds sector budget"):
            encode_spell(entry)


class TestCatalogRoundTrip:
    """Tests round-trip encoding and decoding of all 119 spells in the catalog."""

    def test_all_119_spells_round_trip(self, spells_catalog):
        """Every spell in spells_ru.json must decode identically after encoding."""
        rev = build_reverse_charmap()
        cm = build_combat_dialogue_charmap()

        for item in spells_catalog:
            idx = item["entry_index"]
            raw = encode_spell(item, cm)
            dec_title, dec_pages = decode_spell(raw, rev)

            exp_title = item.get("title_ru") or item.get("name_ru") or item.get("title_en") or ""
            exp_pages = item.get("pages_ru") or []

            assert dec_title == exp_title, f"Title mismatch in entry {idx}: {dec_title!r} != {exp_title!r}"
            assert dec_pages == exp_pages, f"Pages mismatch in entry {idx}: {dec_pages!r} != {exp_pages!r}"

    def test_all_119_spells_sector_budget(self, spells_catalog):
        """Every spell must fit well within 2048 bytes (max observed ~318 bytes)."""
        cm = build_combat_dialogue_charmap()
        max_bytes = 0

        for item in spells_catalog:
            raw = encode_spell(item, cm)
            words = list(struct.unpack(f"<{len(raw)//2}H", raw))
            term_pos = words.index(OPCODE_TERMINATOR) + 1
            used_bytes = term_pos * 2
            if used_bytes > max_bytes:
                max_bytes = used_bytes

            assert used_bytes <= ENTRY_SECTOR_SIZE, (
                f"Entry {item['entry_index']} used {used_bytes} bytes > {ENTRY_SECTOR_SIZE}"
            )

        # Generous safety margin check
        assert max_bytes < 512, f"Maximum spell size ({max_bytes} bytes) exceeds expected ceiling of 512 bytes"


class TestDiscPatching:
    """Tests in-place disc image patching and Mode 2 Form 1 EDC/ECC recalculation."""

    def test_dry_run_mode(self, available_disc):
        """Dry-run must validate all 119 spells without altering the disc image."""
        res = patch_spells(available_disc, CATALOG_PATH, dry_run=True)
        assert res["spells_patched"] == SPELLS_COUNT
        assert res["dry_run"] is True
        assert res["max_payload_size"] <= ENTRY_SECTOR_SIZE

    def test_patch_spells_and_verify_edc_ecc(self, available_disc, tmp_path):
        """Patch a disc copy and verify 100% valid EDC/ECC and content across all 119 sectors."""
        work_bin = tmp_path / "test_spells.bin"
        shutil.copyfile(available_disc, work_bin)

        # 1. Apply patch
        res = patch_spells(work_bin, CATALOG_PATH, dry_run=False)
        assert res["spells_patched"] == SPELLS_COUNT

        # 2. Run verification on the patched disc
        v_res = verify_spells_on_disc(work_bin, CATALOG_PATH)
        assert v_res["entries_total"] == SPELLS_COUNT
        assert v_res["edc_ecc_valid"] == SPELLS_COUNT, f"EDC/ECC failures: {v_res['errors']}"
        assert v_res["content_valid"] == SPELLS_COUNT, f"Content mismatches: {v_res['errors']}"
        assert len(v_res["errors"]) == 0

        # 3. Direct independent EDC/ECC verification on sector bytes
        prog_lba, first_offset, offsets = get_prog_unt_spells_extent(work_bin)
        checksums = CdChecksums()

        with work_bin.open("rb") as f:
            for i, offset in enumerate(offsets):
                lba = prog_lba + offset
                f.seek(lba * RAW_SECTOR_SIZE)
                sec = f.read(RAW_SECTOR_SIZE)
                assert len(sec) == RAW_SECTOR_SIZE

                # Mode 2 Form 1 check
                assert sec[15] == 2, f"LBA {lba} is not Mode 2"
                assert not (sec[18] & 0x20), f"LBA {lba} is not Form 1"

                # Checksums
                edc = checksums.compute_edc(sec[0x10:0x818])
                assert edc == sec[0x818:0x81C], f"EDC failed at LBA {lba}"
                ecc_p = checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86)
                assert ecc_p == sec[0x81C:0x8C8], f"ECC P failed at LBA {lba}"
                ecc_q = checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88)
                assert ecc_q == sec[0x8C8:0x930], f"ECC Q failed at LBA {lba}"

class TestSpellMenuEncoding:
    """Tests for in-battle spell selection menu bytes in Entry 0x007."""

    def test_clean_spell_menu_bytes_size(self):
        """Clean spell menu constant has exactly 524 bytes."""
        assert len(ENTRY_007_CLEAN_SPELL_MENU_BYTES) == ENTRY_007_SPELL_MENU_SIZE

    def test_ru_spell_menu_bytes_size(self):
        """Russian spell menu constant has exactly 524 bytes."""
        assert len(ENTRY_007_RU_SPELL_MENU_BYTES) == ENTRY_007_SPELL_MENU_SIZE
    def test_clean_spell_menu_bytes_match_en_patched(self):
        """Clean spell menu bytes match the verified en_patched baseline."""
        en_path = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
        if not en_path.is_file():
            pytest.skip("en_patched disc image not available")
        prog_lba, e7_start, e7_count = get_prog_unt_entry_extent(en_path, ENTRY_COMBAT_DATA)
        e7_data = read_extent(en_path, prog_lba + e7_start, e7_count * 2048)
        en_menu = e7_data[ENTRY_007_SPELL_MENU_START:ENTRY_007_SPELL_MENU_END]
        assert en_menu == ENTRY_007_CLEAN_SPELL_MENU_BYTES, (
            "ENTRY_007_CLEAN_SPELL_MENU_BYTES does not match en_patched disc"
        )

    def test_all_57_spells_present_in_catalog(self, spells_catalog):
        """Verify that spells_ru.json contains all 57 spells with menu_ru names."""
        spells_map = {item["entry_index"]: item for item in spells_catalog}
        total_ids = sum(len(ids) for ids in SECTION_SPELL_IDS)
        assert total_ids == 57, f"Expected 57 spell IDs in sections, got {total_ids}"

        for sec_idx, ids in enumerate(SECTION_SPELL_IDS):
            for spell_id in ids:
                assert spell_id in spells_map, f"Spell {spell_id} missing from catalog"
                item = spells_map[spell_id]
                menu_name = item.get("menu_ru") or item.get("name_ru")
                assert menu_name, f"Spell {spell_id} missing menu_ru name in catalog"

    def test_section_offsets_and_budgets_cover_full_region(self):
        """Verify section offsets and budgets cover the full 524-byte region."""
        total_budget = sum(SECTION_BUDGETS)
        assert total_budget == ENTRY_007_SPELL_MENU_SIZE
        for i, (off, bud) in enumerate(zip(SECTION_OFFSETS, SECTION_BUDGETS)):
            if i + 1 < len(SECTION_OFFSETS):
                assert off + bud == SECTION_OFFSETS[i + 1], (
                    f"Section {i} end {off + bud:#x} != section {i+1} start {SECTION_OFFSETS[i+1]:#x}"
                )

class TestEntry007Invariants:
    """Tests preservation of all critical Entry 0x007 structures during spell menu patching."""

    def test_patch_spell_menu_in_entry_007_preserves_invariants(self):
        """Patch spell menu into simulated Entry 0x007 and verify invariants."""
        dummy_size = ENTRY_007_SECTORS * 2048
        e7 = bytearray(b"\xAA" * dummy_size)

        # Setup MIPS exit instruction at 0x02B78C
        struct.pack_into("<II", e7, OFFSET_MIPS_INIT_EXIT, 0x03E00008, 0x00000000)

        # Setup dummy UI buttons, prompts, dialogue cues, and tables
        e7[OFFSET_SYSTEM_BUTTONS_START:OFFSET_SYSTEM_BUTTONS_END] = b"\x11" * (OFFSET_SYSTEM_BUTTONS_END - OFFSET_SYSTEM_BUTTONS_START)
        e7[OFFSET_DIALOGUES_START:OFFSET_DIALOGUES_END] = b"\x22" * (OFFSET_DIALOGUES_END - OFFSET_DIALOGUES_START)
        e7[OFFSET_TABLE2_START:OFFSET_TABLE2_START + 148] = b"\x33" * 148
        e7[OFFSET_TABLE3_START:OFFSET_TABLE3_START + 200] = b"\x44" * 200

        # Apply spell menu patch (writes Russian spell menu by default)
        patched = patch_spell_menu_in_entry_007(e7)

        # 1. MIPS exit instruction intact
        mips = struct.unpack_from("<II", patched, OFFSET_MIPS_INIT_EXIT)
        assert mips == (0x03E00008, 0x00000000)

        # 2. System buttons intact
        assert patched[OFFSET_SYSTEM_BUTTONS_START:OFFSET_SYSTEM_BUTTONS_END] == b"\x11" * (OFFSET_SYSTEM_BUTTONS_END - OFFSET_SYSTEM_BUTTONS_START)

        # 3. Dialogues intact
        assert patched[OFFSET_DIALOGUES_START:OFFSET_DIALOGUES_END] == b"\x22" * (OFFSET_DIALOGUES_END - OFFSET_DIALOGUES_START)

        # 4. Table 2 and Table 3 intact
        assert patched[OFFSET_TABLE2_START:OFFSET_TABLE2_START + 148] == b"\x33" * 148
        assert patched[OFFSET_TABLE3_START:OFFSET_TABLE3_START + 200] == b"\x44" * 200

        # 5. Spell menu region is patched and exactly 524 bytes matching Russian translation
        menu_bytes = patched[ENTRY_007_SPELL_MENU_START:ENTRY_007_SPELL_MENU_END]
        assert len(menu_bytes) == ENTRY_007_SPELL_MENU_SIZE
        assert menu_bytes == ENTRY_007_RU_SPELL_MENU_BYTES

        # 6. Pointer table region is patched matching Russian pointer table
        ptr_bytes = patched[ENTRY_007_POINTER_TABLE_START:ENTRY_007_POINTER_TABLE_START + len(ENTRY_007_RU_POINTER_BYTES)]
        assert ptr_bytes == ENTRY_007_RU_POINTER_BYTES

        # 7. Explicit clean English patch works as well
        patched_en = patch_spell_menu_in_entry_007(e7, clean_bytes=ENTRY_007_CLEAN_SPELL_MENU_BYTES)
        assert patched_en[ENTRY_007_SPELL_MENU_START:ENTRY_007_SPELL_MENU_END] == ENTRY_007_CLEAN_SPELL_MENU_BYTES

    def test_clean_spell_menu_avoids_default_charmap_mojibake(self):
        """Verify that Entry 0x007 menus avoid DEFAULT_CHARMAP (preventing 'RO L ON' mojibake)."""
        from tools.patch_inspection import DEFAULT_CHARMAP
        mojibake_rondo = bytes([DEFAULT_CHARMAP["Р"], DEFAULT_CHARMAP["о"], DEFAULT_CHARMAP["н"], DEFAULT_CHARMAP["д"], DEFAULT_CHARMAP["о"]])
        assert mojibake_rondo not in ENTRY_007_CLEAN_SPELL_MENU_BYTES
        assert mojibake_rondo not in ENTRY_007_RU_SPELL_MENU_BYTES
