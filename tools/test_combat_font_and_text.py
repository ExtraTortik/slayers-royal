#!/usr/bin/env python3
"""Automated tests for Slayers Royal combat font patcher and text extractor."""

from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from localization import unt_lz
from tools.patch_combat_font import (
    unpack_combat_font,
    patch_combat_font,
    compress_combat_font,
    build_combat_charmap,
    build_reverse_charmap,
    render_cyrillic_glyph,
    get_hw_tile_2bpp,
    put_hw_tile_2bpp,
    render_cyrillic_glyph_2bpp,
    build_patched_combat_font,
    find_press_start_font,
    get_tile,
    put_tile,
    COMBAT_FONT_MAX_SIZE,
    TIM_DECOMPRESSED_SIZE,
    TIM_HEADER_SIZE,
    TOTAL_TILES,
    CYRILLIC_UPPER,
    CYRILLIC_LOWER,
    CYRILLIC_UPPER_BASE,
    CYRILLIC_LOWER_BASE,
    CANONICAL_ASCII_GLYPHS,
    import_combat_font_template,
    is_tile_empty,
)
from tools.combat_text import (
    extract_prog_007,
    extract_all_combat_data,
    encode_combat_string,
    encode_text,
    decode_16le_string,
    RAM_BASE,
)
from tools.patch_combat import (
    patch_combat_font_entry,
    patch_combat_overlay_entry,
    patch_combat_disc_image,
    verify_combat_patch,
    check_pointer_tables,
    OFFSET_COMBAT_INIT_EXIT,
    OFFSET_UI_POINTERS,
    OFFSET_CUE_TABLE,
    DESCRIPTOR_TABLE_ORIGINAL,
)
from tools.patch_inspection import parse_iso_dir, read_sector, read_unt_index
from localization.disc import read_extent
import subprocess

SAMPLE_BIN = REPO_ROOT / "downloads" / "sr.bin"
SAMPLE_BIN_RU = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
CATALOG_PATH = REPO_ROOT / "translations" / "combat_ru.json"


@pytest.fixture(scope="module")
def sample_disc():
    if not SAMPLE_BIN.is_file():
        pytest.skip("downloads/sr.bin not found")
    return SAMPLE_BIN


@pytest.fixture(scope="module")
def sample_disc_ru():
    if not SAMPLE_BIN_RU.is_file():
        pytest.skip("slayers_royal_ru.bin not found")
    return SAMPLE_BIN_RU


class TestCombatFont:
    """Verification of combat font 0x142 unpacking, rendering, and compression."""

    def test_unpack_combat_font_structure(self, sample_disc):
        tim_bytes = unpack_combat_font(sample_disc)
        assert len(tim_bytes) == TIM_DECOMPRESSED_SIZE

        # Verify PSX TIM Header: magic 0x10, flags 0x08 (4bpp with CLUT)
        magic, flags = struct.unpack_from("<II", tim_bytes, 0)
        assert magic == 0x10
        assert flags == 0x08

        # Verify CLUT: len=524, x=0, y=480, w=256, h=1
        clut_len, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", tim_bytes, 8)
        assert clut_len == 524
        assert clut_x == 0
        assert clut_y == 480
        assert clut_w == 256
        assert clut_h == 1

        # Verify IMG: w=64 words (128 bytes = 256 pixels)
        img_len, img_x, img_y, img_w, img_h = struct.unpack_from("<IHHHH", tim_bytes, 8 + clut_len)
        assert img_x == 0
        assert img_y == 0
        assert img_w == 64
        assert img_h == 1024

    def test_tile_read_write_roundtrip(self, sample_disc):
        tim_bytes = bytearray(unpack_combat_font(sample_disc))
        # Verify get_tile and put_tile bit-exact roundtrip across tiles
        for tid in range(0, TOTAL_TILES, 32):
            orig = get_tile(tim_bytes, tid)
            assert len(orig) == 128
            put_tile(tim_bytes, tid, orig)
            assert get_tile(tim_bytes, tid) == orig

    def test_cyrillic_glyph_rendering(self):
        font_path = find_press_start_font()
        assert font_path.is_file()

        # Render test characters
        for ch in ("А", "Я", "а", "я", "Ё", "ё", "Ж", "Щ"):
            tile_bytes = render_cyrillic_glyph(ch, font_path)
            assert len(tile_bytes) == 128
            # Non-empty tile
            assert any(b != 0 for b in tile_bytes)
            # Verify only allowed color indices: 0 (trans), 1 (shadow), 3 (white core)
            nibs = []
            for b in tile_bytes:
                nibs.append(b & 0x0F)
                nibs.append(b >> 4)
            assert set(nibs).issubset({0, 1, 3})
            # Must contain both text (3) and shadow (1)
            assert 3 in nibs
            assert 1 in nibs

    def test_combat_font_patch_and_compression_budget(self, sample_disc):
        orig_tim = unpack_combat_font(sample_disc)
        charmap = build_combat_charmap()

        patched_tim, _ = patch_combat_font(orig_tim, charmap)
        assert len(patched_tim) == TIM_DECOMPRESSED_SIZE

        # Header and CLUT must be preserved 100% byte-exact
        assert patched_tim[:TIM_HEADER_SIZE] == orig_tim[:TIM_HEADER_SIZE]

        # Compression with unt_lz mode 1
        compressed = compress_combat_font(patched_tim)
        assert len(compressed) <= COMBAT_FONT_MAX_SIZE  # 23 sectors (47,104 B)

        # Decompression roundtrip
        dec, _ = unt_lz.decompress(compressed)
        assert dec == patched_tim


    def test_hw_tile_read_write_roundtrip(self, sample_disc):
        tim_bytes = bytearray(unpack_combat_font(sample_disc))
        for code in (0x0000, 0x007D, 0x00A8, 0x00BE, 0x0150, 0x0160, 0x0191, 0x03FF):
            orig = get_hw_tile_2bpp(tim_bytes, code)
            assert len(orig) == 64
            put_hw_tile_2bpp(tim_bytes, code, orig)
            assert get_hw_tile_2bpp(tim_bytes, code) == orig

    def test_cyrillic_glyph_2bpp_rendering(self):
        font_path = find_press_start_font()
        assert font_path.is_file()

        for ch in ("А", "П", "Я", "а", "п", "я", "Ё", "ё"):
            tile_bytes = render_cyrillic_glyph_2bpp(ch, font_path)
            assert len(tile_bytes) == 64, f"Tile {ch} must be exactly 64 bytes"
            assert any(b != 0 for b in tile_bytes), f"Tile {ch} must not be all zeros"

            # Verify 2BPP pixel values in {0, 1, 3}
            pixel_vals = []
            for b in tile_bytes:
                for p in range(4):
                    pixel_vals.append((b >> (p * 2)) & 3)

            assert set(pixel_vals).issubset({0, 1, 3})
            assert 3 in pixel_vals, f"Tile {ch} must contain text body (3)"
            assert 1 in pixel_vals, f"Tile {ch} must contain shadow (1)"

    def test_hw_tile_0160_is_cyrillic_p_and_all_66_glyphs(self, sample_disc):
        orig_tim = unpack_combat_font(sample_disc)
        font_path = find_press_start_font()
        patched_tim, compressed = build_patched_combat_font(orig_tim, font_path)

        kanji_tile = get_hw_tile_2bpp(orig_tim, 0x0160)
        p_tile = get_hw_tile_2bpp(patched_tim, 0x0160)

        # When template is present, glyphs come from template
        tpl_path = REPO_ROOT / "data" / "combat_font_template.png"
        if tpl_path.is_file():
            from tools.patch_combat_font import import_combat_font_template
            tpl_tiles = import_combat_font_template(tpl_path)
            expected_p = tpl_tiles["П"]
            assert p_tile == expected_p, "Tile 0x0160 must unpack to hand-drawn Cyrillic 'П'"
            for idx, ch in enumerate(CYRILLIC_UPPER):
                code = CYRILLIC_UPPER_BASE + idx
                assert get_hw_tile_2bpp(patched_tim, code) == tpl_tiles[ch]
            for idx, ch in enumerate(CYRILLIC_LOWER):
                code = CYRILLIC_LOWER_BASE + idx
                assert get_hw_tile_2bpp(patched_tim, code) == tpl_tiles[ch]
        else:
            expected_p = render_cyrillic_glyph_2bpp("П", font_path)
            assert p_tile == expected_p, "Tile 0x0160 must unpack to Cyrillic 'П'"

        assert p_tile != kanji_tile, "Tile 0x0160 must NOT remain Japanese kanji '助'"

        # Verify PressStart2P fallback when template is absent
        patched_fb, _ = build_patched_combat_font(orig_tim, font_path, template_path=Path("/nonexistent"))
        fb_p = render_cyrillic_glyph_2bpp("П", font_path)
        assert get_hw_tile_2bpp(patched_fb, 0x0160) == fb_p

    def test_bank0_tiles_preserved_original(self, sample_disc):
        """Verify Bank 0 tiles are left untouched by combat font patching.

        The in-battle spell selection menu renderer uses Bank 0 with the
        original 8-bit font tile set. Cyrillic injection into Bank 0 was
        removed because it broke spell name display.
        """
        orig_tim = unpack_combat_font(sample_disc)
        font_path = find_press_start_font()
        patched_tim, compressed = build_patched_combat_font(orig_tim, font_path)

        # Bank 0 tiles 0x0000..0x003F should be identical to original
        for tile_id in range(0x40):
            orig_tile = get_hw_tile_2bpp(orig_tim, tile_id)
            patched_tile = get_hw_tile_2bpp(patched_tim, tile_id)
            assert orig_tile == patched_tile, (
                f"Bank 0 tile 0x{tile_id:04X} was modified; "
                f"spell menu renderer requires original tiles"
            )

        # Font compression verification
        assert len(compressed) <= COMBAT_FONT_MAX_SIZE
class TestCombatCharmap:
    """Verification of combat charmap allocation and constraints."""

    def test_charmap_completeness(self):
        charmap = build_combat_charmap()

        # All uppercase Cyrillic in charmap
        for ch in CYRILLIC_UPPER:
            assert ch in charmap

        # All lowercase Cyrillic in charmap
        for ch in CYRILLIC_LOWER:
            assert ch in charmap
        # Basic punctuation and digits
        for ch in (" ", "!", "?", ".", ",", "-", ":", "0", "1", "9"):
            assert ch in charmap

        # Standard English alphabet preserved
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
            assert ch in charmap

    def test_cyrillic_block_lives_in_battle_font(self):
        """Battle text is rendered with font 0x142: Cyrillic occupies 0x0150..0x0191."""
        charmap = build_combat_charmap()
        for ch in CYRILLIC_UPPER + CYRILLIC_LOWER:
            assert 0x0150 <= charmap[ch] <= 0x0191, f"Letter {ch!r} out of range: 0x{charmap[ch]:04X}"
        assert charmap["А"] == 0x0150
        assert charmap["а"] == 0x0171

    def test_encode_text_canonical_charmap(self):
        enc = encode_text("ВЫБЕРИТЕ ЮНИТ")
        charmap = build_combat_charmap()
        expected = b"".join(charmap[c].to_bytes(2, "little") for c in "ВЫБЕРИТЕ ЮНИТ") + b"\xFF\x00"
        assert enc == expected

    def test_no_ascii_overlap_with_cyrillic(self):
        charmap = build_combat_charmap()
        latin = {charmap[c] for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"}
        for ch in CYRILLIC_UPPER + CYRILLIC_LOWER:
            assert charmap[ch] not in latin

class TestCombatTextCatalog:
    """Verification of translations/combat_ru.json dataset."""

    def test_catalog_file_exists_and_valid(self):
        assert CATALOG_PATH.is_file()
        doc = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

        assert "metadata" in doc
        assert "system_strings" in doc
        assert "dialogues" in doc
        assert "charmap" in doc

        assert doc["metadata"]["system_strings_count"] == len(doc["system_strings"])
        assert doc["metadata"]["dialogues_count"] == len(doc["dialogues"])

    def test_system_strings_coverage(self):
        doc = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        sys_strings = doc["system_strings"]
        assert len(sys_strings) == 37

        sys_ids = {s["id"] for s in sys_strings}
        expected_ids = {
            "START", "CONFIG", "ATTACK_SET", "COUNTER_SET", "SPELL_SET",
            "MOVE", "SLIPPER", "LAUGH", "HIT_BACK", "EVADE", "FLEE",
            "GUARD", "WARD", "CAST", "BACK", "MAGIC", "AUTO", "MANUAL",
            "PICK_UNIT", "PICK_ICON", "PICK_SPELL", "MOVE_TO", "TARGET",
            "AREA", "FIGHTING", "WAIT", "PICK_TYPE", "SAVE", "LOAD"
        }
        for eid in expected_ids:
            assert eid in sys_ids, f"Missing system command ID: {eid}"

        # Check PICK_UNIT details
        pick_unit = next(s for s in sys_strings if s["id"] == "PICK_UNIT")
        assert pick_unit["text_en"] == "PICK UNIT"
        assert pick_unit["offset"] == "0x05F398"
        assert "ВЫБЕРИТЕ" in pick_unit["text_ru_full"].upper()
        assert [e["table2_index"] for e in sys_strings] == list(range(37))

        # Check START details
        start_cmd = next(s for s in sys_strings if s["id"] == "START")
        assert start_cmd["text_en"] == "START"
        assert start_cmd["offset"] == "0x05F278"

    def test_dialogue_cues_coverage(self):
        doc = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        dialogues = doc["dialogues"]
        assert len(dialogues) == 101

        # Check indexing 1..101
        indices = [d["index"] for d in dialogues]
        assert indices == list(range(1, 102))

        # Check line #92 (the interfered phrase)
        dlg_92 = dialogues[91]
        assert dlg_92["index"] == 92
        assert dlg_92["offset"] == "0x06241C"
        assert dlg_92["ram_address"] == "0x800B052C"
        assert "interfeer" in dlg_92["text_en"] or "interfer" in dlg_92["text_en"]
        assert dlg_92["speaker"] == "Наёмник"
        assert "Тьфу" in dlg_92["text_ru"] or "пошла с нами" in dlg_92["text_ru"]

        # Check first line
        dlg_1 = dialogues[0]
        assert dlg_1["index"] == 1
        assert dlg_1["offset"] == "0x05F810"
        assert "Нага" in dlg_1["text_ru"]

        # Check last line
        dlg_101 = dialogues[100]
        assert dlg_101["index"] == 101
        assert dlg_101["offset"] == "0x0626CC"
        assert dlg_101["speaker"] == "Лина"

    def test_string_encoding_with_combat_charmap(self):
        doc = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        charmap = build_combat_charmap()

        # All system strings Russian translations encode cleanly
        for s in doc["system_strings"]:
            encoded = encode_combat_string(s["text_ru"], charmap)
            assert encoded.endswith(b"\xFF\x00")
            assert len(encoded) >= 4

        # All 101 dialogue cues Russian translations encode cleanly
        for d in doc["dialogues"]:
            encoded = encode_combat_string(d["text_ru"], charmap)
            assert encoded.endswith(b"\xFF\x00")
            assert len(encoded) >= 4


class TestCombatPatcher:
    """Verification of patch_combat injector and disc verification."""

    def test_verify_combat_patch_ru_bin(self, sample_disc_ru: Path):
        report = verify_combat_patch(sample_disc_ru, catalog_path=CATALOG_PATH)
        assert report["problems"] == []
        assert report["font_decompressed_bytes"] == 66080

    def test_in_memory_overlay_patch(self, sample_disc: Path):
        pvd = read_sector(sample_disc, 16)
        root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
        root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
        root_dir = parse_iso_dir(sample_disc, root_lba, root_size)
        prog_lba, prog_size = root_dir["PROG.UNT"]

        prog_archive = bytearray(read_extent(sample_disc, prog_lba, prog_size))
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        charmap = build_combat_charmap()
        rev_cm = build_reverse_charmap(charmap)
        entries = read_unt_index(prog_archive)
        e007 = entries[7]
        before = bytes(prog_archive[e007.offset : e007.offset + e007.size])

        count = patch_combat_overlay_entry(prog_archive, catalog, charmap)
        assert count == len(catalog["extra_combat_strings"])
        e007_data = bytes(prog_archive[e007.offset : e007.offset + e007.size])

        # Auxiliary strings are written in place with the battle-font charmap
        first = catalog["extra_combat_strings"][0]
        words = decode_16le_string(e007_data, int(first["offset"], 16), stop_at_page=False)
        assert "".join(rev_cm.get(w, "") for w in words) == first["text_ru"]

        # Pointer tables are never touched by this tool
        assert e007_data[0x05F1FC:0x05F258] == DESCRIPTOR_TABLE_ORIGINAL
        assert e007_data[OFFSET_UI_POINTERS:0x05F504] == before[OFFSET_UI_POINTERS:0x05F504]
        assert e007_data[OFFSET_CUE_TABLE:0x062A10] == before[OFFSET_CUE_TABLE:0x062A10]
        assert check_pointer_tables(e007_data) == []

        exit_instr, exit_delay = struct.unpack_from("<II", e007_data, OFFSET_COMBAT_INIT_EXIT)
        assert (exit_instr, exit_delay) == (0x03E00008, 0x00000000)

    test_patch_combat_overlay_entry = test_in_memory_overlay_patch

    def test_cli_verify_mode(self, sample_disc_ru: Path):
        cmd = [
            sys.executable,
            str(REPO_ROOT / "tools" / "patch_combat.py"),
            "--bin",
            str(sample_disc_ru),
            "--verify",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0
        assert "[✓] Combat verification passed" in res.stdout
    def test_combat_reverted_to_english_baseline(self, sample_disc_ru: Path):
        """Verify that slayers_royal_ru.bin preserves clean English combat baseline."""
        pvd_ru = read_sector(sample_disc_ru, 16)
        root_lba_ru = struct.unpack_from("<I", pvd_ru, 156 + 2)[0]
        root_size_ru = struct.unpack_from("<I", pvd_ru, 156 + 10)[0]
        prog_lba_ru, _ = parse_iso_dir(sample_disc_ru, root_lba_ru, root_size_ru)["PROG.UNT"]
        e007_ru = read_unt_index(read_extent(sample_disc_ru, prog_lba_ru, 2048))[0x007]
        prog_007 = read_extent(sample_disc_ru, prog_lba_ru + e007_ru.start_sector, e007_ru.size)

        # 1. Exit instruction at 0x02B78C is original MIPS 'jr $ra; nop' (0x03E00008)
        exit_instr = struct.unpack_from("<I", prog_007, OFFSET_COMBAT_INIT_EXIT)[0]
        assert exit_instr == 0x03E00008, f"Expected clean jr $ra (0x03E00008), got 0x{exit_instr:08X}"

        # 2. The descriptor pointer table is never rewritten
        assert prog_007[0x05F1FC:0x05F258] == DESCRIPTOR_TABLE_ORIGINAL

        # 3. Entry 0x007 matches English base disc bit-for-bit outside dialogue stream if English baseline
        p_en = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
        if p_en.is_file():
            words_start = decode_16le_string(prog_007, 0x05F278, stop_at_page=False)
            is_english = (words_start == [0x0090, 0x008D, 0x00BE, 0x0099, 0x008D, 0x00FF])
            if is_english:
                from tools.patch_combat import get_en_combat_overlay_bytes
                raw_en = get_en_combat_overlay_bytes(p_en)
                assert bytes(prog_007[:0x05F278]) == raw_en[:0x05F278], "Pre-system strings region must be bit-exact with sr_patched.bin!"
                assert bytes(prog_007[0x05F470:0x05F810]) == raw_en[0x05F470:0x05F810], "Table 2 and pre-dialogue region must be bit-exact with sr_patched.bin!"
                assert bytes(prog_007[0x06286C:]) == raw_en[0x06286C:], "Post-dialogue region must be bit-exact with sr_patched.bin!"
    def test_entry_142_patched_in_ru_bin(self, sample_disc: Path, sample_disc_ru: Path):
        pvd_sr = read_sector(sample_disc, 16)
        pvd_ru = read_sector(sample_disc_ru, 16)
        root_lba_sr = struct.unpack_from("<I", pvd_sr, 156 + 2)[0]
        root_size_sr = struct.unpack_from("<I", pvd_sr, 156 + 10)[0]
        root_lba_ru = struct.unpack_from("<I", pvd_ru, 156 + 2)[0]
        root_size_ru = struct.unpack_from("<I", pvd_ru, 156 + 10)[0]

        prog_lba_sr, _ = parse_iso_dir(sample_disc, root_lba_sr, root_size_sr)["PROG.UNT"]
        prog_lba_ru, _ = parse_iso_dir(sample_disc_ru, root_lba_ru, root_size_ru)["PROG.UNT"]

        e142_sr = read_unt_index(read_extent(sample_disc, prog_lba_sr, 2048))[0x142]
        e142_ru = read_unt_index(read_extent(sample_disc_ru, prog_lba_ru, 2048))[0x142]

        raw_sr = read_extent(sample_disc, prog_lba_sr + e142_sr.start_sector, e142_sr.size)
        raw_ru = read_extent(sample_disc_ru, prog_lba_ru + e142_ru.start_sector, e142_ru.size)
        assert raw_ru != raw_sr, "Entry 0x142 in ru.bin must differ from Japanese original!"
        decomp_ru, _ = unt_lz.decompress(raw_ru)
        assert len(decomp_ru) == 66080

        # Verify CLUT: len=524, x=0, y=480, w=256, h=1
        clut_len, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", decomp_ru, 8)
        assert clut_x == 0 and clut_y == 480, f"CLUT must be at (0, 480), got ({clut_x}, {clut_y})"
        assert clut_len == 524

        charmap = build_combat_charmap()
        font_path = find_press_start_font()

        # Verify tile 0x0160 in ru.bin unpacks to Cyrillic 'П' and not kanji '助'
        tile_0160 = get_hw_tile_2bpp(decomp_ru, 0x0160)
        tpl_path = REPO_ROOT / "data" / "combat_font_template.png"
        if tpl_path.is_file():
            from tools.patch_combat_font import import_combat_font_template
            tpl_tiles = import_combat_font_template(tpl_path)
            assert tile_0160 == tpl_tiles["П"], "Tile 0x0160 in ru.bin must unpack to hand-drawn 'П'"
            for idx, ch in enumerate(CYRILLIC_UPPER):
                code = CYRILLIC_UPPER_BASE + idx
                assert get_hw_tile_2bpp(decomp_ru, code) == tpl_tiles[ch], (
                    f"Uppercase glyph '{ch}' at 0x{code:04X} mismatch in ru.bin"
                )
            for idx, ch in enumerate(CYRILLIC_LOWER):
                code = CYRILLIC_LOWER_BASE + idx
                assert get_hw_tile_2bpp(decomp_ru, code) == tpl_tiles[ch], (
                    f"Lowercase glyph '{ch}' at 0x{code:04X} mismatch in ru.bin"
                )
        else:
            expected_p = render_cyrillic_glyph_2bpp("П", font_path)
            assert tile_0160 == expected_p, "Tile 0x0160 in ru.bin must unpack to Cyrillic 'П'"
    def test_ui_labels_resolve_through_pointer_table(self, sample_disc_ru: Path):
        pvd_ru = read_sector(sample_disc_ru, 16)
        root_lba_ru = struct.unpack_from("<I", pvd_ru, 156 + 2)[0]
        root_size_ru = struct.unpack_from("<I", pvd_ru, 156 + 10)[0]
        prog_lba_ru, _ = parse_iso_dir(sample_disc_ru, root_lba_ru, root_size_ru)["PROG.UNT"]
        e007_ru = read_unt_index(read_extent(sample_disc_ru, prog_lba_ru, 2048))[0x007]
        prog_007 = read_extent(sample_disc_ru, prog_lba_ru + e007_ru.start_sector, e007_ru.size)

        # UI pointer 0 (START) must resolve to either English 'START' or Russian 'СТАРТ'
        target = struct.unpack_from("<I", prog_007, OFFSET_UI_POINTERS)[0] - RAM_BASE
        words_start = decode_16le_string(prog_007, target, stop_at_page=False)
        assert words_start in (
            [0x0090, 0x008D, 0x00BE, 0x0099, 0x008D, 0x00FF],  # S T A R T
            [0x0162, 0x0163, 0x0150, 0x0161, 0x0163, 0x00FF],  # С Т А Р Т
        )
        # Every UI pointer must land on a string start and every cue pointer on a speaker opcode
        assert check_pointer_tables(prog_007) == []

    def test_dialogues_baseline_integrity(self, sample_disc_ru: Path):
        """Every dialogue cue pointer in 0x007 must point at a speaker opcode (base 0x8004E5B0)."""
        pvd_ru = read_sector(sample_disc_ru, 16)
        root_lba_ru = struct.unpack_from("<I", pvd_ru, 156 + 2)[0]
        root_size_ru = struct.unpack_from("<I", pvd_ru, 156 + 10)[0]
        prog_lba_ru, _ = parse_iso_dir(sample_disc_ru, root_lba_ru, root_size_ru)["PROG.UNT"]
        e007_ru = read_unt_index(read_extent(sample_disc_ru, prog_lba_ru, 2048))[0x007]
        prog_007 = read_extent(sample_disc_ru, prog_lba_ru + e007_ru.start_sector, e007_ru.size)
        assert RAM_BASE == 0x8004E5B0
        for idx in range(105):
            ram_p = struct.unpack_from("<I", prog_007, OFFSET_CUE_TABLE + idx * 4)[0]
            t = ram_p - RAM_BASE
            assert 0x05F810 <= t < 0x06286A, f"Cue {idx} pointer 0x{ram_p:08X} outside the dialogue stream"
            assert (struct.unpack_from("<H", prog_007, t)[0] >> 8) in (0x91, 0xD1, 0xD2)


class TestCombatScaffolding:
    """Verify combat font templates and spell translation catalog."""

    def test_combat_font_template_structure_and_palette(self):
        tpl_path = REPO_ROOT / "data" / "combat_font_template.png"
        assert tpl_path.is_file(), "data/combat_font_template.png must exist"
        from PIL import Image
        im = Image.open(tpl_path)
        assert im.size == (528, 96), f"Expected 528x96, got {im.size}"
        assert im.mode == "RGBA", f"Expected RGBA mode, got {im.mode}"

    def test_combat_font_template_contains_all_66_hand_drawn_glyphs(self):
        """Verify that Row 3 and Row 5 contain all 66 hand-drawn Cyrillic glyphs."""
        tpl_path = REPO_ROOT / "data" / "combat_font_template.png"
        from tools.patch_combat_font import (
            import_combat_font_template,
            is_tile_empty,
            CYRILLIC_UPPER,
            CYRILLIC_LOWER,
        )
        tiles = import_combat_font_template(tpl_path)
        assert len(tiles) == 66
        for ch in CYRILLIC_UPPER:
            assert ch in tiles, f"Missing upper glyph '{ch}'"
            assert not is_tile_empty(tiles[ch]), f"Upper glyph '{ch}' must not be empty"
        for ch in CYRILLIC_LOWER:
            assert ch in tiles, f"Missing lower glyph '{ch}'"
            assert not is_tile_empty(tiles[ch]), f"Lower glyph '{ch}' must not be empty"

    def test_combat_font_template_labels(self):
        """Verify that Row 2 and Row 4 contain clear text labels directly above drawing tiles."""
        tpl_path = REPO_ROOT / "data" / "combat_font_template.png"
        from PIL import Image
        from tools.patch_combat_font import CYRILLIC_UPPER, CYRILLIC_LOWER
        im = Image.open(tpl_path)

        # Row 2: Uppercase labels
        for col, ch in enumerate(CYRILLIC_UPPER):
            cell = im.crop((col * 16, 2 * 16, (col + 1) * 16, 3 * 16))
            colors = {c[1] for c in (cell.getcolors(256) or [])}
            # Must contain white core text and black outline
            assert (255, 255, 255, 255) in colors, f"Missing white text in label '{ch}'"
            assert (0, 0, 0, 255) in colors, f"Missing black outline in label '{ch}'"

        # Row 4: Lowercase labels
        for col, ch in enumerate(CYRILLIC_LOWER):
            cell = im.crop((col * 16, 4 * 16, (col + 1) * 16, 5 * 16))
            colors = {c[1] for c in (cell.getcolors(256) or [])}
            assert (255, 255, 255, 255) in colors, f"Missing white text in lower label '{ch}'"
            assert (0, 0, 0, 255) in colors, f"Missing black outline in lower label '{ch}'"

        # Row 0 and Row 1: Authentic English reference rows
        for r in (0, 1):
            row_im = im.crop((0, r * 16, 16 * 16, (r + 1) * 16))
            colors = {c[1] for c in (row_im.getcolors(1024) or [])}
            assert (255, 255, 255, 255) in colors, f"Row {r} missing authentic white glyph pixels"

    def test_combat_font_importer_empty_and_painted(self):
        """Verify importer functions: import_combat_font_template and is_tile_empty."""
        tpl_path = REPO_ROOT / "data" / "combat_font_template.png"
        from PIL import Image
        from tools.patch_combat_font import (
            import_combat_font_template,
            is_tile_empty,
            CYRILLIC_UPPER,
            CYRILLIC_LOWER,
        )
        from tools.build_spells_catalog import tile_2bpp_to_image

        # 1. User template imports all 66 non-empty tiles
        tiles = import_combat_font_template(tpl_path)
        assert len(tiles) == 66, f"Expected 66 tiles, got {len(tiles)}"
        for ch, tdata in tiles.items():
            assert not is_tile_empty(tdata), f"Expected tile for '{ch}' to not be empty"

        # 2. Blank image imports as completely empty tiles
        blank_im = Image.new("RGBA", (528, 96), (0, 0, 0, 0))
        blank_tiles = import_combat_font_template(blank_im)
        for ch, tdata in blank_tiles.items():
            assert is_tile_empty(tdata), f"Expected blank tile for '{ch}' to be empty"

        # 3. Painted template recovers user pixels and filters guide borders
        canvas = Image.open(tpl_path).copy()
        canvas.putpixel((5, 3 * 16 + 5), (255, 255, 255, 255))
        canvas.putpixel((6, 3 * 16 + 5), (0, 0, 0, 255))

        painted_tiles = import_combat_font_template(canvas)
        a_tile = painted_tiles["А"]
        assert not is_tile_empty(a_tile), "Tile 'А' should not be empty after painting"

        # Verify recovered pixel art in 2BPP
        a_im = tile_2bpp_to_image(a_tile)
        assert a_im.getpixel((5, 5)) == (255, 255, 255, 255), "White pixel recovered"
        assert a_im.getpixel((6, 5)) == (0, 0, 0, 255), "Black pixel recovered"
        assert a_im.getpixel((0, 0)) == (0, 0, 0, 0), "Guide border filtered to transparent"
    def test_combat_font_reference_grid_exists(self):
        ref_path = REPO_ROOT / "data" / "combat_font_reference_grid.png"
        assert ref_path.is_file(), "data/combat_font_reference_grid.png must exist"
        from PIL import Image
        im = Image.open(ref_path)
        assert im.size[0] >= 1000 and im.size[1] >= 500, "Reference grid must be enlarged visual guide"
        assert im.size == (5724, 960), f"Expected (5724, 960), got {im.size}"
    def test_spells_ru_catalog_119_entries(self):
        spells_path = REPO_ROOT / "translations" / "spells_ru.json"
        assert spells_path.is_file(), "translations/spells_ru.json must exist"
        catalog = json.loads(spells_path.read_text(encoding="utf-8"))
        assert len(catalog) == 119, f"Expected exactly 119 spells, got {len(catalog)}"

        for idx, item in enumerate(catalog):
            expected_idx = 325 + idx
            assert item["entry_index"] == expected_idx
            assert item["entry_hex"] == f"0x{expected_idx:03X}"
            assert "title_en" in item and len(item["title_en"]) > 0
            assert "title_ru" in item and len(item["title_ru"]) > 0
            assert "name_en" in item and "name_ru" in item
            assert "pages_en" in item and isinstance(item["pages_en"], list)
            assert "pages_ru" in item and isinstance(item["pages_ru"], list)
            assert "desc_en" in item and isinstance(item["desc_en"], str)
            assert "desc_ru" in item and isinstance(item["desc_ru"], str)
            assert "title_jp" in item

            # Title before delimiter in authentic spells
            if item["pages_en"]:
                assert len(item["pages_ru"]) == len(item["pages_en"]), (
                    f"Page count mismatch at {expected_idx}: {len(item['pages_ru'])} != {len(item['pages_en'])}"
                )
