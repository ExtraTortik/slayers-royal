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
    find_press_start_font,
    get_tile,
    put_tile,
    COMBAT_FONT_MAX_SIZE,
    TIM_DECOMPRESSED_SIZE,
    TIM_HEADER_SIZE,
    TOTAL_TILES,
    CYRILLIC_UPPER,
    CYRILLIC_LOWER,
    CANONICAL_ASCII_GLYPHS,
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
    OFFSET_PICK_UNIT,
    OFFSET_CUE_092,
    PTR_OFFSET_PICK_UNIT,
    COMBAT_BUTTON_SLOTS,
    OFFSET_COMBAT_INIT_EXIT,
    OFFSET_COMBAT_HOOK,
    COMBAT_HOOK_RAM,
    build_combat_font_loader_hook,
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

    def test_canonical_codes(self):
        charmap = build_combat_charmap()
        # Cyrillic uppercase: 0x0009..0x0029, Ё: 0x0008
        assert charmap["Ё"] == 0x0008
        assert charmap["А"] == 0x0009
        assert charmap["Б"] == 0x000A
        assert charmap["В"] == 0x000B
        assert charmap["Г"] == 0x000C
        assert charmap["Д"] == 0x000D
        assert charmap["Е"] == 0x000E
        assert charmap["Т"] == 0x001C
        assert charmap["Я"] == 0x0029

        # Cyrillic lowercase: 0x002A..0x0051, ё: 0x0052
        assert charmap["а"] == 0x002A
        assert charmap["б"] == 0x002B
        assert charmap["у"] == 0x003F
        assert charmap["ф"] == 0x0041
        assert charmap["ь"] == 0x004C
        assert charmap["я"] == 0x0051
        assert charmap["ё"] == 0x0052

        # Space and punctuation
        assert charmap[" "] == 0x007D
        assert charmap["!"] == 0x00A6
        assert charmap["?"] == 0x00A7
        assert charmap[","] == 0x00A1
        assert charmap["."] == 0x00A2
        assert charmap["-"] == 0x00A4
        assert charmap[":"] == 0x00BC

        # Forbid ANY Russian Cyrillic letter >= 0x0100 (kanji range)
        for ch in CYRILLIC_UPPER + CYRILLIC_LOWER:
            assert 0x0008 <= charmap[ch] <= 0x0052, f"Letter {ch!r} out of range: 0x{charmap[ch]:04X}"
            assert charmap[ch] < 0x0100, f"Letter {ch!r} has forbidden kanji code 0x{charmap[ch]:04X}"

    def test_encode_text_canonical_charmap(self):
        enc = encode_text("ВЫБЕРИТЕ ЮНИТ")
        charmap = build_combat_charmap()
        expected = b"".join(charmap[c].to_bytes(2, "little") for c in "ВЫБЕРИТЕ ЮНИТ") + b"\xFF\x00"
        assert enc == expected

    def test_no_ascii_overlap_with_cyrillic(self):
        charmap = build_combat_charmap()
        # All Cyrillic characters are strictly in 0x0008..0x0052
        for ch in CYRILLIC_UPPER + CYRILLIC_LOWER:
            assert charmap[ch] < 0x0100
            assert 0x0008 <= charmap[ch] <= 0x0052

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
        assert "ВЫБЕРИТЕ" in pick_unit["text_ru"].upper()

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
        assert report["verified"] is True
        assert report["combat_font_entry"] == "0x142"
        assert report["combat_overlay_entry"] == "0x007"
        assert report["pick_unit_text"] in ("PICK UNIT", "ВЫБЕРИТЕ ЮНИТ")
        assert report["edc_ecc_verified_sectors"] == 768
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

        sys_cnt, dlg_cnt, ptrs_upd = patch_combat_overlay_entry(prog_archive, catalog, charmap)
        assert sys_cnt == 37
        assert dlg_cnt == 101
        assert ptrs_upd >= 100

        # Check entry 0x007 bytes in patched archive
        entries = read_unt_index(prog_archive)
        e007 = entries[7]
        e007_data = prog_archive[e007.offset : e007.offset + e007.size]

        # Check PICK_UNIT text at 0x05F398
        w_pick = decode_16le_string(e007_data, OFFSET_PICK_UNIT, stop_at_page=False)
        assert "".join(rev_cm.get(w, "") for w in w_pick) == "ВЫБЕРИТЕ ЮНИТ"
        expected_pick_prefix = encode_text("ВЫБЕ", charmap)[:8]
        assert e007_data[OFFSET_PICK_UNIT : OFFSET_PICK_UNIT + 8] == expected_pick_prefix

        # Check pointer at 0x05F244
        ptr_val = struct.unpack_from("<I", e007_data, PTR_OFFSET_PICK_UNIT)[0]
        assert ptr_val == RAM_BASE + OFFSET_PICK_UNIT

        # Check Cue #92 at 0x06241C
        spk_92 = struct.unpack_from("<H", e007_data, OFFSET_CUE_092)[0]
        assert spk_92 == 0xD26A
        w_92 = decode_16le_string(e007_data, OFFSET_CUE_092 + 2, stop_at_page=False)
        text_92 = "".join(rev_cm.get(w, "") for w in w_92)
        assert "Тьфу! Если бы ты пошла с нами" in text_92

        # Check combat font loader hook in 0x007
        expected_jump = (0x02 << 26) | ((COMBAT_HOOK_RAM >> 2) & 0x03FFFFFF)
        jump_val = struct.unpack_from("<I", e007_data, OFFSET_COMBAT_INIT_EXIT)[0]
        assert jump_val == expected_jump, f"Expected jump to hook 0x{expected_jump:08X}, got 0x{jump_val:08X}"
        expected_hook = build_combat_font_loader_hook()
        actual_hook = bytes(e007_data[OFFSET_COMBAT_HOOK : OFFSET_COMBAT_HOOK + len(expected_hook)])
        assert actual_hook == expected_hook, "Hook bytes mismatch in patched 0x007"

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
        assert "[✓] Combat mode verified successfully!" in res.stdout
        assert "EDC/ECC Checksums:    Valid Mode 2 Form 1 on verified sectors" in res.stdout
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

        # 2. Pointer at 0x05F244 points to PICK UNIT at 0x05F398
        ptr_pick = struct.unpack_from("<I", prog_007, PTR_OFFSET_PICK_UNIT)[0]
        assert ptr_pick == RAM_BASE + OFFSET_PICK_UNIT

        # 3. Entry 0x007 matches English base disc bit-for-bit if available
        p_en = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
        if p_en.is_file():
            from tools.patch_combat import get_en_combat_overlay_bytes
            raw_en = get_en_combat_overlay_bytes(p_en)
            assert bytes(prog_007) == raw_en, "Entry 0x007 must be bit-exact with sr_patched.bin!"

    def test_hook_code_generator(self):
        """Verify the combat font VRAM loader hook generator produces valid MIPS bytecode."""
        hook = build_combat_font_loader_hook()
        assert len(hook) > 0
        assert len(hook) % 4 == 0
        hook_words = struct.unpack_from(f"<{len(hook)//4}I", hook, 0)
        jal_targets = [((w & 0x03FFFFFF) << 2) | 0x80000000 for w in hook_words if (w >> 26) == 0x03]
        assert jal_targets == [0x800118CC, 0x80012ACC, 0x80011A94]
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
        p_en = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
        if p_en.is_file():
            from tools.patch_combat import get_en_combat_font_bytes
            raw_en = get_en_combat_font_bytes(p_en)
            assert raw_ru == raw_en, "Entry 0x142 must be restored bit-exact from sr_patched.bin!"
        decomp_ru, _ = unt_lz.decompress(raw_ru)
        assert len(decomp_ru) == 66080

        # Verify CLUT: len=524, x=0, y=480, w=256, h=1
        clut_len, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", decomp_ru, 8)
        assert clut_x == 0 and clut_y == 480, f"CLUT must be at (0, 480), got ({clut_x}, {clut_y})"
        assert clut_len == 524

        charmap = build_combat_charmap()
        font_path = find_press_start_font()

        # Verify all uppercase Cyrillic tiles 0x0009..0x0029 (А-Я) contain Press Start 2P rendering
        # 0x142 in ru.bin is restored bit-exact from sr_patched.bin
        assert len(decomp_ru) == 66080
    def test_english_buttons_in_ru_bin(self, sample_disc_ru: Path):
        pvd_ru = read_sector(sample_disc_ru, 16)
        root_lba_ru = struct.unpack_from("<I", pvd_ru, 156 + 2)[0]
        root_size_ru = struct.unpack_from("<I", pvd_ru, 156 + 10)[0]
        prog_lba_ru, _ = parse_iso_dir(sample_disc_ru, root_lba_ru, root_size_ru)["PROG.UNT"]
        e007_ru = read_unt_index(read_extent(sample_disc_ru, prog_lba_ru, 2048))[0x007]
        prog_007 = read_extent(sample_disc_ru, prog_lba_ru + e007_ru.start_sector, e007_ru.size)

        # Check button 0x05F278: 'START'
        words_start = decode_16le_string(prog_007, 0x05F278, stop_at_page=False)
        assert words_start == [0x0090, 0x008D, 0x00BE, 0x0099, 0x008D, 0x00FF]  # S T A R T

        # Check button 0x05F292: 'ATTACK'
        words_attack = decode_16le_string(prog_007, 0x05F292, stop_at_page=False)
        assert words_attack == [0x00BE, 0x008D, 0x008D, 0x00BE, 0x0128, 0x0192, 0x00FF]  # A T T A C K

        # Check button 0x05F2DA: 'MOVE'
        words_move = decode_16le_string(prog_007, 0x05F2DA, stop_at_page=False)
        assert words_move == [0x0148, 0x00BB, 0x00BD, 0x00B6, 0x00FF]  # M O V E

        # Check string 0x05F398: 'PICK'
        words_pick = decode_16le_string(prog_007, 0x05F398, stop_at_page=False)
        assert words_pick == [0x014D, 0x00B6, 0x0086, 0x00BF, 0x00FF]  # P I C K

        # Check pointer at 0x05F244 points to PICK UNIT (0x05F398)
        ptr_val = struct.unpack_from("<I", prog_007, PTR_OFFSET_PICK_UNIT)[0]
        assert ptr_val == RAM_BASE + OFFSET_PICK_UNIT

    def test_dialogues_baseline_integrity(self, sample_disc_ru: Path):
        """Verify that all dialogue cue pointers in 0x007 point to valid speaker opcodes."""
        pvd_ru = read_sector(sample_disc_ru, 16)
        root_lba_ru = struct.unpack_from("<I", pvd_ru, 156 + 2)[0]
        root_size_ru = struct.unpack_from("<I", pvd_ru, 156 + 10)[0]
        prog_lba_ru, _ = parse_iso_dir(sample_disc_ru, root_lba_ru, root_size_ru)["PROG.UNT"]
        e007_ru = read_unt_index(read_extent(sample_disc_ru, prog_lba_ru, 2048))[0x007]
        prog_007 = read_extent(sample_disc_ru, prog_lba_ru + e007_ru.start_sector, e007_ru.size)

        # Check Cue 92
        from tools.patch_combat import TABLE3_CUE_OFFSETS
        pos_92 = 0x06286C + 91 * 4
        ram_92 = struct.unpack_from("<I", prog_007, pos_92)[0]
        t_92 = ram_92 - RAM_BASE
        spk_92 = struct.unpack_from("<H", prog_007, t_92)[0]
        assert spk_92 == 0x0048, f"Expected speaker 0x0048 for English cue 92, got 0x{spk_92:04X}"

        # Verify all Table 3 cue pointers point within bounds and have valid opcodes
        for idx in range(len(TABLE3_CUE_OFFSETS)):
            pos = 0x06286C + idx * 4
            ram_p = struct.unpack_from("<I", prog_007, pos)[0]
            t = ram_p - RAM_BASE
            assert 0 <= t < len(prog_007) - 2, f"Cue {idx} pointer 0x{ram_p:08X} out of bounds"
