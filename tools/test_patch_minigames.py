"""Unit and integration tests for tools/patch_minigames.py.

Covers:
1. In-memory patching of PROG.UNT entries 13, 14, 15, 16, 17.
2. Quiz question table encoding (offsets, 32B padding, 164B struct, correct indices).
3. Binary verification and round-trip decoding of rules and questions.
4. Budget overflow protection and typography limit enforcement.
5. Verification against target disc image and Mode 2 Form 1 EDC/ECC checks.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import struct
import sys
import unittest

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.patch_minigames import (
    AMELIA_COMBO_POINTERS,
    AMELIA_COMBO_POINTERS_OFFSET,
    AMELIA_COMBO_POINTERS_RAW,
    AMELIA_COMBO_SPECS,
    AMELIA_DIALOGUE_POINTERS,
    AMELIA_DIALOGUE_POINTERS_RAW,
    AMELIA_DIALOGUE_SPECS,
    AMELIA_POINTER_TABLE_OFFSET,
    BANDIT_BONUS_SPEC,
    CHAR_NEWLINE,
    CHAR_PAGE,
    CHAR_TERMINATOR,
    DEFAULT_CATALOG,
    DEFAULT_CHARMAP,
    DEFAULT_TARGET_BIN,
    EATING_STATUS_SPECS,
    MINIGAME_CHARMAP,
    MINIGAME_FONT_GLYPH_IDS,
    MINIGAME_SPECS,
    NAGA_DIALOGUE_POINTERS,
    NAGA_DIALOGUE_POINTERS_RAW,
    NAGA_DIALOGUE_SPECS,
    PROG_FONT_ENTRY,
    PROG_FONT_PIXEL_OFFSET,
    QUIZ_SPEC,
    GLYPH_CIRCLE,
    GLYPH_DOWN,
    GLYPH_LEFT,
    GLYPH_RIGHT,
    GLYPH_UP,
    PRISTINE_BUTTON_TILES,
    QUIZ_UI_SPECS,
    REVERSE_CHARMAP,
    SMINI_DEFAULT_LBA,
    SMINI_FONT_SPECS,
    SMINI_PROTECTED_GLYPHS,
    build_minigames_charmap,
    check_font_size,
    decode_minigame_dialogue,
    decode_amelia_combo_block,
    decode_minigame_rules,
    decode_minigame_stream,
    decode_minigame_string,
    decode_quiz_question,
    decode_quiz_slot,
    encode_minigame_dialogue,
    encode_amelia_combo_block,
    encode_minigame_rules,
    encode_minigame_stream,
    encode_minigame_string,
    encode_quiz_question,
    encode_quiz_slot,
    encode_quiz_table,
    extract_03a_bank0_tile,
    extract_prog_font_tiles,
    extract_smini_tile,
    get_reverse_charmap,
    inject_smini_tile,
    load_prog_entries_data,
    load_smini_entries_data,
    locate_smini_unt,
    patch_minigames_memory,
    patch_smini_fonts_memory,
    verify_minigames,
)


class TestMinigamesPatching(unittest.TestCase):
    """Test suite covering minigames and quiz encoding, patching, and verification."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))
        cls.minigames = cls.catalog["minigames"]
        cls.quiz = cls.catalog["quiz"]
        cls.questions = cls.quiz["questions"]

    # ==========================================================================
    # 1. In-memory patching tests for entries 13, 14, 15, 16, 17
    # ==========================================================================

    def test_in_memory_patching_entry_13_eating_contest(self):
        """Test in-memory patching of Entry 13: unified continuous stream at 0x07320 (328B)."""
        mg = self.minigames["eating_contest"]
        spec = MINIGAME_SPECS["eating_contest"]
        start_off = spec["offset"]
        budget = spec["budget"]
        end_off = spec["rules_end_offset"]

        entry_size = 167936  # 82 sectors
        mock_entry = bytearray(b"\xAA" * entry_size)

        entries = {13: mock_entry, 14: bytearray(2048), 15: bytearray(2048), 16: bytearray(65536), 17: bytearray(2048)}
        stats = patch_minigames_memory(entries, self.catalog)

        self.assertIn("eating_contest", stats)
        self.assertIn("eating_contest_title", stats)
        self.assertEqual(stats["eating_contest"]["entry"], 13)
        self.assertEqual(stats["eating_contest"]["offset"], start_off)
        self.assertEqual(stats["eating_contest"]["bytes"], budget)

        # Before title_start_offset: untouched \xAA
        self.assertEqual(mock_entry[:start_off], b"\xAA" * start_off)

        # Decoded continuous stream matches catalog title banner and rules
        dec_title, dec_rules = decode_minigame_stream(mock_entry[start_off : start_off + budget], budget)
        self.assertEqual(dec_title, mg["title_banner"])
        self.assertEqual(dec_rules, mg["rules_ru"])

        # Verify no 0x00FF in title section
        words = [struct.unpack_from("<H", mock_entry[start_off : start_off + budget], i)[0] for i in range(0, budget, 2)]
        self.assertEqual(words[0], 0x0000)
        title_len = len(mg["title_banner"])
        for i in range(1, 1 + title_len + 2):
            self.assertNotEqual(words[i], CHAR_TERMINATOR)

        # Untouched region between rules end (0x07468) and status messages start (0x0746C)
        self.assertEqual(mock_entry[end_off : 0x0746C], b"\xAA" * (0x0746C - end_off))

        # Verify status messages in stats and decoded values
        self.assertIn("eating_contest_status_messages", stats)
        for s_id, s_spec in EATING_STATUS_SPECS.items():
            self.assertIn(f"eating_contest_{s_id}", stats)
            s_stat = stats[f"eating_contest_{s_id}"]
            self.assertEqual(s_stat["entry"], 13)
            self.assertEqual(s_stat["offset"], s_spec["offset"])
            self.assertEqual(s_stat["budget"], s_spec["budget"])

            exp_text = mg["status_messages"][s_id]
            dec_text = decode_minigame_dialogue(
                mock_entry[s_spec["offset"] : s_spec["offset"] + s_spec["budget"]],
                s_spec["budget"],
                is_bubble=False,
            )
            self.assertEqual(dec_text, exp_text, f"Entry 13 {s_id} decoded mismatch")

        # After status messages at 0x07532: untouched \xAA
        self.assertEqual(mock_entry[0x07532 : 0x07532 + 64], b"\xAA" * 64)
    def test_in_memory_patching_entry_14_amelia_climb(self):
        """Test in-memory patching of Entry 14: unified continuous stream at 0x11318 (354B)."""
        mg = self.minigames["amelia_climb"]
        spec = MINIGAME_SPECS["amelia_climb"]
        start_off = spec["offset"]
        budget = spec["budget"]
        end_off = spec["rules_end_offset"]

        entry_size = 157696
        mock_entry = bytearray(b"\xBB" * entry_size)

        entries = {13: bytearray(2048), 14: mock_entry, 15: bytearray(2048), 16: bytearray(65536), 17: bytearray(2048)}
        stats = patch_minigames_memory(entries, self.catalog)

        self.assertIn("amelia_climb", stats)
        self.assertIn("amelia_climb_title", stats)
        self.assertEqual(mock_entry[:start_off], b"\xBB" * start_off)

        dec_title, dec_rules = decode_minigame_stream(mock_entry[start_off : start_off + budget], budget)
        self.assertEqual(dec_title, mg["title_banner"])
        self.assertEqual(dec_rules, mg["rules_ru"])

        words = [struct.unpack_from("<H", mock_entry[start_off : start_off + budget], i)[0] for i in range(0, budget, 2)]
        self.assertEqual(words[0], 0x0000)
        title_len = len(mg["title_banner"])
        for i in range(1, 1 + title_len + 2):
            self.assertNotEqual(words[i], CHAR_TERMINATOR)

        # Untouched region between rules end (0x1147A) and speech 1 start (0x1147C)
        self.assertEqual(mock_entry[end_off : 0x1147C], b"\xBB" * (0x1147C - end_off))

        # Verify Amelia dialogues in stats and decoded values
        self.assertIn("amelia_climb_dialogues", stats)
        for d_id, d_spec in AMELIA_DIALOGUE_SPECS.items():
            self.assertIn(f"amelia_climb_{d_id}", stats)
            d_stat = stats[f"amelia_climb_{d_id}"]
            self.assertEqual(d_stat["entry"], 14)
            self.assertEqual(d_stat["offset"], d_spec["offset"])
            self.assertEqual(d_stat["budget"], d_spec["budget"])

            exp_text = mg["dialogues"][d_id]
            is_bubble = d_spec.get("is_bubble", True)
            if is_bubble:
                dec_text = decode_minigame_dialogue(
                    mock_entry[d_spec["offset"] : d_spec["offset"] + d_spec["budget"]],
                    d_spec["budget"],
                    is_bubble=True,
                )
            else:
                dec_text = decode_minigame_string(
                    mock_entry[d_spec["offset"] : d_spec["offset"] + d_spec["budget"]],
                    d_spec["budget"],
                )
            self.assertEqual(dec_text, exp_text, f"Entry 14 {d_id} decoded mismatch")

        # Verify 5-pointer table at 0x11854..0x11868
        ptrs = struct.unpack_from("<5I", mock_entry, AMELIA_POINTER_TABLE_OFFSET)
        self.assertEqual(ptrs, AMELIA_DIALOGUE_POINTERS)

        # Verify Amelia combo window in stats and decoded values
        self.assertIn("amelia_climb_combo_window", stats)
        for diff_level, spec_key in ((1, "difficulty_1"), (2, "difficulty_2"), (3, "difficulty_3")):
            self.assertIn(f"amelia_climb_combo_{spec_key}", stats)
            c_stat = stats[f"amelia_climb_combo_{spec_key}"]
            spec = AMELIA_COMBO_SPECS[spec_key]
            self.assertEqual(c_stat["entry"], 14)
            self.assertEqual(c_stat["offset"], spec["offset"])
            self.assertEqual(c_stat["budget"], spec["budget"])

            dec_combo = decode_amelia_combo_block(
                mock_entry[spec["offset"] : spec["offset"] + spec["budget"]],
                spec["budget"],
            )
            self.assertIn("ОК:", dec_combo)
            self.assertIn("○", dec_combo)

        # Verify 3-pointer table at 0x1198C..0x11998
        combo_ptrs = struct.unpack_from("<3I", mock_entry, AMELIA_COMBO_POINTERS_OFFSET)
        self.assertEqual(combo_ptrs, AMELIA_COMBO_POINTERS)

        # Untouched region between 3-pointer table end (0x11998) and justice_up (0x12318)
        self.assertEqual(mock_entry[0x11998 : 0x11998 + 64], b"\xBB" * 64)
        # Untouched region after justice_up end (0x12338)
        self.assertEqual(mock_entry[0x12338 : 0x12338 + 64], b"\xBB" * 64)
    def test_in_memory_patching_entry_15_naga_laugh(self):
        """Test in-memory patching of Entry 15: unified continuous stream at 0x07EB4 and dialogues 1..6 at 0x07FC8..0x0833A."""
        mg = self.minigames["naga_laugh"]
        spec = MINIGAME_SPECS["naga_laugh"]
        start_off = spec["offset"]
        budget = spec["budget"]
        end_off = spec["rules_end_offset"]

        entry_size = 114688
        mock_entry = bytearray(b"\xCC" * entry_size)

        entries = {13: bytearray(2048), 14: bytearray(2048), 15: mock_entry, 16: bytearray(65536), 17: bytearray(2048)}
        stats = patch_minigames_memory(entries, self.catalog)

        self.assertIn("naga_laugh", stats)
        self.assertIn("naga_laugh_title", stats)
        self.assertEqual(mock_entry[:start_off], b"\xCC" * start_off)

        dec_title, dec_rules = decode_minigame_stream(mock_entry[start_off : start_off + budget], budget)
        self.assertEqual(dec_title, mg["title_banner"])
        self.assertEqual(dec_rules, mg["rules_ru"])

        words = [struct.unpack_from("<H", mock_entry[start_off : start_off + budget], i)[0] for i in range(0, budget, 2)]
        self.assertEqual(words[0], 0x0000)
        title_len = len(mg["title_banner"])
        for i in range(1, 1 + title_len + 2):
            self.assertNotEqual(words[i], CHAR_TERMINATOR)

        # Padding bytes between rules and Dialogue 1: 0x07FC6..0x07FC8 (2 bytes)
        self.assertEqual(mock_entry[end_off : end_off + 2], b"\xCC\xCC")

        # Verify all 6 dialogues patched in memory and reported in stats
        self.assertIn("naga_laugh_dialogues", stats)
        self.assertEqual(stats["naga_laugh_dialogues"]["dialogues"], 6)

        dlgs = mg["dialogues"]
        for d_id, d_spec in NAGA_DIALOGUE_SPECS.items():
            self.assertIn(f"naga_laugh_{d_id}", stats)
            exp_text = dlgs[d_id]
            txt_off = d_spec.get("text_offset", d_spec["offset"])
            txt_bud = d_spec.get("text_budget", d_spec["budget"])
            is_bubble = d_spec.get("is_bubble", True)

            dec_dlg = decode_minigame_dialogue(mock_entry[txt_off : txt_off + txt_bud], txt_bud, is_bubble=is_bubble)
            self.assertEqual(dec_dlg, exp_text, f"{d_id} text mismatch")

        # Verify Dialogue 2 also decodes when offset 0x0806A with 00 00 padding is passed
        d2_from_pad = decode_minigame_dialogue(mock_entry[0x0806A : 0x08114], 170, is_bubble=True)
        self.assertEqual(d2_from_pad, dlgs["dialogue_2"])

        # Verify Dialogue 6 pointer table integrity at 0x08308..0x0831C
        ptrs = struct.unpack_from("<5I", mock_entry, 0x08308)
        self.assertEqual(ptrs, NAGA_DIALOGUE_POINTERS)

        # After Dialogue 6 at 0x0833A: untouched 0xCC
        self.assertEqual(mock_entry[0x0833A : 0x0833A + 64], b"\xCC" * 64)
    def test_in_memory_patching_entry_16_quiz_rules_and_questions(self):
        """Test in-memory patching of Entry 16: unified stream at 0x08184 (252B), UI, and questions."""
        mg = self.minigames["slayers_quiz"]
        spec = MINIGAME_SPECS["slayers_quiz"]
        start_off = spec["offset"]
        budget = spec["budget"]
        end_off = spec["rules_end_offset"]

        cp_off = QUIZ_UI_SPECS["contestant_prompt"]["offset"]
        cp_bud = QUIZ_UI_SPECS["contestant_prompt"]["budget"]
        hdr_off = QUIZ_UI_SPECS["results_header"]["offset"]
        hdr_bud = QUIZ_UI_SPECS["results_header"]["budget"]
        cnt_off = QUIZ_UI_SPECS["results_correct_count"]["offset"]
        cnt_bud = QUIZ_UI_SPECS["results_correct_count"]["budget"]
        spd_off = QUIZ_UI_SPECS["results_avg_speed"]["offset"]
        spd_bud = QUIZ_UI_SPECS["results_avg_speed"]["budget"]
        quiz_off = int(self.quiz["metadata"]["questions_offset_hex"], 16)
        quiz_len = 16400

        entry_size = 118784
        mock_entry = bytearray(b"\xDD" * entry_size)

        entries = {13: bytearray(2048), 14: bytearray(2048), 15: bytearray(2048), 16: mock_entry, 17: bytearray(2048)}
        stats = patch_minigames_memory(entries, self.catalog)

        self.assertIn("slayers_quiz_title", stats)
        self.assertIn("slayers_quiz_rules", stats)
        self.assertIn("slayers_quiz_prompt", stats)
        self.assertIn("slayers_quiz_results_header", stats)
        self.assertIn("slayers_quiz_results_correct_count", stats)
        self.assertIn("slayers_quiz_results_avg_speed", stats)
        self.assertIn("quiz_questions", stats)

        # Region before start_off untouched
        self.assertEqual(mock_entry[:start_off], b"\xDD" * start_off)

        # Verify decoded unified stream
        dec_title, dec_rules = decode_minigame_stream(mock_entry[start_off : start_off + budget], budget)
        self.assertEqual(dec_title, mg["title_banner"])
        self.assertEqual(dec_rules, mg["rules_ru"])

        words = [struct.unpack_from("<H", mock_entry[start_off : start_off + budget], i)[0] for i in range(0, budget, 2)]
        self.assertEqual(words[0], 0x0000)
        title_len = len(mg["title_banner"])
        for i in range(1, 1 + title_len + 2):
            self.assertNotEqual(words[i], CHAR_TERMINATOR)

        # Gap between rules stream and contestant prompt (0x08280 .. 0x08284, 4 bytes) untouched
        self.assertEqual(mock_entry[end_off:cp_off], b"\xDD" * (cp_off - end_off))

        # Verify contestant prompt
        dec_cp = decode_minigame_string(mock_entry[cp_off : cp_off + cp_bud], cp_bud)
        self.assertEqual(dec_cp, mg["contestant_prompt"])

        # Verify results screen
        rs = mg["results_screen"]
        dec_h = decode_minigame_string(mock_entry[hdr_off : hdr_off + hdr_bud], hdr_bud)
        self.assertEqual(dec_h, rs["header"])
        dec_cnt = decode_minigame_string(mock_entry[cnt_off : cnt_off + cnt_bud], cnt_bud)
        self.assertEqual(dec_cnt, rs["correct_count"])
        dec_spd = decode_minigame_string(mock_entry[spd_off : spd_off + spd_bud], spd_bud)
        self.assertEqual(dec_spd, rs["avg_speed"])

        # Region after questions untouched
        end_quiz = quiz_off + quiz_len
        self.assertEqual(mock_entry[end_quiz : end_quiz + 64], b"\xDD" * 64)

        # Verify all 100 decoded questions
        for i, q in enumerate(self.questions):
            q_slice = mock_entry[quiz_off + i * 164 : quiz_off + (i + 1) * 164]
            dec_q = decode_quiz_question(q_slice)
            self.assertEqual(dec_q["q_line1"], q["q_line1"])
            self.assertEqual(dec_q["q_line2"], q["q_line2"])
            self.assertEqual(dec_q["opt1"], q["opt1"])
            self.assertEqual(dec_q["opt2"], q["opt2"])
            self.assertEqual(dec_q["opt3"], q["opt3"])
            self.assertEqual(dec_q["correct"], q["correct"])
    def test_in_memory_patching_entry_17_bandit_bullying(self):
        """Test in-memory patching of Entry 17: unified continuous stream at 0x082B8 (346B)."""
        mg = self.minigames["bandit_bullying"]
        spec = MINIGAME_SPECS["bandit_bullying"]
        start_off = spec["offset"]
        budget = spec["budget"]
        end_off = spec["rules_end_offset"]

        entry_size = 217088
        mock_entry = bytearray(b"\xEE" * entry_size)

        entries = {13: bytearray(2048), 14: bytearray(2048), 15: bytearray(2048), 16: bytearray(65536), 17: mock_entry}
        stats = patch_minigames_memory(entries, self.catalog)

        self.assertIn("bandit_bullying", stats)
        self.assertIn("bandit_bullying_title", stats)
        self.assertEqual(mock_entry[:start_off], b"\xEE" * start_off)

        dec_title, dec_rules = decode_minigame_stream(mock_entry[start_off : start_off + budget], budget)
        self.assertEqual(dec_title, mg["title_banner"])
        self.assertEqual(dec_rules, mg["rules_ru"])

        words = [struct.unpack_from("<H", mock_entry[start_off : start_off + budget], i)[0] for i in range(0, budget, 2)]
        self.assertEqual(words[0], 0x0000)
        title_len = len(mg["title_banner"])
        for i in range(1, 1 + title_len + 2):
            self.assertNotEqual(words[i], CHAR_TERMINATOR)

        # Untouched region between rules end (0x08412) and time bonus start (0x08414)
        self.assertEqual(mock_entry[end_off : BANDIT_BONUS_SPEC["offset"]], b"\xEE" * (BANDIT_BONUS_SPEC["offset"] - end_off))

        # Verify time bonus in stats and decoded value
        self.assertIn("bandit_bullying_time_bonus", stats)
        tb_stat = stats["bandit_bullying_time_bonus"]
        self.assertEqual(tb_stat["entry"], 17)
        self.assertEqual(tb_stat["offset"], BANDIT_BONUS_SPEC["offset"])
        self.assertEqual(tb_stat["budget"], BANDIT_BONUS_SPEC["budget"])

        exp_tb = mg["time_bonus"]
        dec_tb = decode_minigame_string(
            mock_entry[BANDIT_BONUS_SPEC["offset"] : BANDIT_BONUS_SPEC["offset"] + BANDIT_BONUS_SPEC["budget"]],
            BANDIT_BONUS_SPEC["budget"],
        )
        self.assertEqual(dec_tb, exp_tb, "Entry 17 time_bonus decoded mismatch")

        # Untouched region after time bonus end (0x08428)
        self.assertEqual(mock_entry[0x08428 : 0x08428 + 64], b"\xEE" * 64)
    # ==========================================================================
    # 2. Quiz question table encoding tests (offsets, padding, correct answer)
    # ==========================================================================

    def test_quiz_slot_encoding_and_padding(self):
        """Test encoding a slot: 16-bit LE words, 0x00FF terminator, zero padding to 32 bytes."""
        text = "Меч Света?"
        slot_bytes = encode_quiz_slot(text, 32)
        self.assertEqual(len(slot_bytes), 32)

        words = [struct.unpack_from("<H", slot_bytes, i)[0] for i in range(0, 32, 2)]
        # Check characters
        for idx, ch in enumerate(text):
            self.assertEqual(words[idx], DEFAULT_CHARMAP[ch])
        # Terminator
        self.assertEqual(words[len(text)], CHAR_TERMINATOR)
        # Padding zeros
        for i in range(len(text) + 1, 16):
            self.assertEqual(words[i], 0x0000)

        # Roundtrip decode
        self.assertEqual(decode_quiz_slot(slot_bytes), text)

    def test_quiz_slot_exact_15_char_boundary(self):
        """Test maximum allowed slot text length: exactly 15 characters (30B + 2B term = 32B)."""
        max_text = "А" * 15
        slot_bytes = encode_quiz_slot(max_text, 32)
        self.assertEqual(len(slot_bytes), 32)
        words = [struct.unpack_from("<H", slot_bytes, i)[0] for i in range(0, 32, 2)]
        self.assertEqual(words[15], CHAR_TERMINATOR)
        self.assertEqual(decode_quiz_slot(slot_bytes), max_text)

    def test_quiz_slot_overflow_raises_error(self):
        """Test that slot text > 15 characters (> 32 bytes) raises ValueError."""
        overflow_text = "А" * 16  # 16 chars * 2B + 2B terminator = 34B > 32B
        with self.assertRaises(ValueError):
            encode_quiz_slot(overflow_text, 32)

    def test_quiz_question_struct_layout(self):
        """Test 164-byte struct layout: 5 slots * 32 bytes + uint32_le correct index."""
        q_sample = {
            "ps1_index": 0,
            "q_line1": "Кого одолел",
            "q_line2": "Меч Света?",
            "opt1": "Занаффар",
            "opt2": "Граушерра",
            "opt3": "Милгазия",
            "correct": 0,
        }
        raw = encode_quiz_question(q_sample)
        self.assertEqual(len(raw), 164)

        # Verify slots positions
        self.assertEqual(decode_quiz_slot(raw[0:32]), "Кого одолел")
        self.assertEqual(decode_quiz_slot(raw[32:64]), "Меч Света?")
        self.assertEqual(decode_quiz_slot(raw[64:96]), "Занаффар")
        self.assertEqual(decode_quiz_slot(raw[96:128]), "Граушерра")
        self.assertEqual(decode_quiz_slot(raw[128:160]), "Милгазия")

        corr_val = struct.unpack_from("<I", raw, 160)[0]
        self.assertEqual(corr_val, 0)

    def test_quiz_question_invalid_correct_index(self):
        """Test that correct answer index not in (0, 1, 2) raises ValueError."""
        bad_q = copy.deepcopy(self.questions[0])
        bad_q["correct"] = 3
        with self.assertRaises(ValueError):
            encode_quiz_question(bad_q)

        bad_q["correct"] = -1
        with self.assertRaises(ValueError):
            encode_quiz_question(bad_q)

    def test_encode_full_quiz_table(self):
        """Test encoding all 100 questions produces exactly 16,400 bytes with accurate offsets."""
        table = encode_quiz_table(self.questions)
        self.assertEqual(len(table), 16400)

        for i, exp_q in enumerate(self.questions):
            offset = i * 164
            q_rec = table[offset : offset + 164]
            dec = decode_quiz_question(q_rec)
            self.assertEqual(dec["q_line1"], exp_q["q_line1"])
            self.assertEqual(dec["q_line2"], exp_q["q_line2"])
            self.assertEqual(dec["opt1"], exp_q["opt1"])
            self.assertEqual(dec["opt2"], exp_q["opt2"])
            self.assertEqual(dec["opt3"], exp_q["opt3"])
            self.assertEqual(dec["correct"], exp_q["correct"])

    # ==========================================================================
    # 3. Binary verification and round-trip decode tests
    # ==========================================================================

    def test_minigames_rules_roundtrip_all_5_games(self):
        """Verify strict round-trip encode/decode of continuous stream for all 5 minigames."""
        for mg_id, exp in MINIGAME_SPECS.items():
            mg = self.minigames[mg_id]
            budget = exp["budget"]
            encoded = encode_minigame_stream(mg["title_banner"], mg["rules_ru"], budget)
            self.assertEqual(len(encoded), budget)
            dec_title, dec_rules = decode_minigame_stream(encoded, budget)
            self.assertEqual(dec_title, mg["title_banner"])
            self.assertEqual(dec_rules, mg["rules_ru"])

    def test_unified_stream_no_premature_terminator(self):
        """Verify that no 0x00FF terminator appears between title banner and rules in any minigame."""
        for mg_id, exp in MINIGAME_SPECS.items():
            mg = self.minigames[mg_id]
            budget = exp["budget"]
            stream = encode_minigame_stream(mg["title_banner"], mg["rules_ru"], budget)
            words = [struct.unpack_from("<H", stream, i)[0] for i in range(0, budget, 2)]

            # Indent 0x0000
            self.assertEqual(words[0], 0x0000, f"{mg_id} missing 0x0000 indent")

            # Locate \n\n (0x00FD, 0x00FD)
            sep_idx = None
            for i in range(1, len(words) - 1):
                if words[i] == CHAR_NEWLINE and words[i + 1] == CHAR_NEWLINE:
                    sep_idx = i
                    break
            self.assertIsNotNone(sep_idx, f"{mg_id} missing \\n\\n separator")

            # Ensure no 0x00FF before rules
            for i in range(sep_idx + 2):
                self.assertNotEqual(
                    words[i],
                    CHAR_TERMINATOR,
                    f"0x00FF found in title section of {mg_id} at index {i}",
                )

            # Single terminator in non-padding words
            non_pad = [w for w in words if w != 0x0000]
            self.assertEqual(non_pad.count(CHAR_TERMINATOR), 1)

    def test_encode_decode_minigame_string_all_title_banners(self):
        """Verify encode_minigame_string and decode_minigame_string roundtrip for all 5 title banners."""
        for mg_id, spec in MINIGAME_SPECS.items():
            mg = self.minigames[mg_id]
            self.assertIn("title_banner", mg)
            tb = mg["title_banner"]
            budget = spec["title_budget"]
            encoded = encode_minigame_string(tb, budget)
            self.assertEqual(len(encoded), budget)
            decoded = decode_minigame_string(encoded, budget)
            self.assertEqual(decoded, tb)

    def test_encode_decode_quiz_ui_strings(self):
        """Verify encode_minigame_string and decode_minigame_string roundtrip for contestant prompt and results."""
        mg16 = self.minigames["slayers_quiz"]
        cp = mg16["contestant_prompt"]
        cp_bud = QUIZ_UI_SPECS["contestant_prompt"]["budget"]
        cp_enc = encode_minigame_string(cp, cp_bud)
        self.assertEqual(len(cp_enc), cp_bud)
        self.assertEqual(decode_minigame_string(cp_enc, cp_bud), cp)

        rs = mg16["results_screen"]
        for field, spec_key in [("header", "results_header"), ("correct_count", "results_correct_count"), ("avg_speed", "results_avg_speed")]:
            text = rs[field]
            bud = QUIZ_UI_SPECS[spec_key]["budget"]
            enc = encode_minigame_string(text, bud)
            self.assertEqual(len(enc), bud)
            self.assertEqual(decode_minigame_string(enc, bud), text)
    def test_minigames_rules_newline_encoding(self):
        """Verify newline character translates to 0x00FD and terminates with 0x00FF."""
        text = "Строка 1\nСтрока 2"
        encoded = encode_minigame_rules(text, 64)
        words = [struct.unpack_from("<H", encoded, i)[0] for i in range(0, len(encoded), 2)]

        # Find 0x00FD and 0x00FF
        self.assertIn(CHAR_NEWLINE, words)
        self.assertIn(CHAR_TERMINATOR, words)
        nl_pos = words.index(CHAR_NEWLINE)
        term_pos = words.index(CHAR_TERMINATOR)
        self.assertEqual(nl_pos, len("Строка 1"))
        self.assertEqual(term_pos, len(text))

        decoded = decode_minigame_rules(encoded, 64)
        self.assertEqual(decoded, text)

    def test_verify_minigames_against_target_bin(self):
        """Test verify_minigames on localization-output/ru/slayers_royal_ru.bin if present."""
        if not DEFAULT_TARGET_BIN.is_file():
            self.skipTest(f"Target disc image not found: {DEFAULT_TARGET_BIN}")

        res = verify_minigames(DEFAULT_TARGET_BIN, DEFAULT_CATALOG)
        self.assertEqual(res["status"], "valid")
        self.assertEqual(res["verified_minigames"], 5)
        self.assertEqual(res["verified_questions"], 100)
        self.assertEqual(res["verified_font_entries"], 5)
        self.assertGreaterEqual(res["verified_font_tiles"], 79)
        self.assertGreaterEqual(res["verified_sectors"], 1800)
        self.assertEqual(res.get("verified_amelia_dialogues"), 6)
        self.assertEqual(res.get("verified_eating_status"), 3)
        self.assertEqual(res.get("verified_bandit_bonus"), 1)
        self.assertEqual(res.get("verified_amelia_combo_blocks"), 3)
        self.assertEqual(res.get("verified_button_icons"), 5)
    # ==========================================================================
    # 4. Budget overflow protection tests
    # ==========================================================================

    def test_rules_budget_overflow_protection(self):
        """Test that rules text exceeding allocated budget raises ValueError."""
        # Budget for quiz rules is 228 bytes (113 chars + 1 term = 114 words = 228B)
        overflow_text = "А" * 114  # 114 chars + 1 term = 115 words = 230 bytes > 228B
        with self.assertRaises(ValueError):
            encode_minigame_rules(overflow_text, 228)

    def test_unmapped_character_raises_value_error(self):
        """Test that unmapped characters in rules or quiz raise ValueError."""
        with self.assertRaises(ValueError):
            encode_minigame_rules("Текст с японским иероглифом 漢", 100)

        with self.assertRaises(ValueError):
            encode_quiz_slot("Слово с 漢", 32)

    def test_typography_validation_detects_overflow(self):
        """Test check_font_size catches line length > 20, lines > 10, option > 15."""
        bad_catalog = copy.deepcopy(self.catalog)

        # 1. Line > 20 chars in minigame
        bad_catalog["minigames"]["eating_contest"]["rules_ru"] = "Слишком длинная строка правил которая превышает двадцать знаков"
        errors = check_font_size(bad_catalog)
        self.assertTrue(any("exceeds 20 chars" in e for e in errors))

        # 2. Line count > 10 in minigame
        bad_catalog["minigames"]["eating_contest"]["rules_ru"] = "\n".join(f"Строка {i}" for i in range(12))
        errors = check_font_size(bad_catalog)
        self.assertTrue(any("lines > 10" in e for e in errors))

        # 3. Question line > 15 chars in quiz
        bad_catalog = copy.deepcopy(self.catalog)
        bad_catalog["quiz"]["questions"][0]["q_line1"] = "Длинный вопрос более 15"
        errors = check_font_size(bad_catalog)
        self.assertTrue(any("exceeds 15 chars" in e for e in errors))

        # 4. Option > 15 chars in quiz
        bad_catalog = copy.deepcopy(self.catalog)
        bad_catalog["quiz"]["questions"][0]["opt1"] = "Очень длинный ответ"
        errors = check_font_size(bad_catalog)
        self.assertTrue(any("exceeds 15 chars" in e for e in errors))

        # 5. Invalid correct answer index
        bad_catalog = copy.deepcopy(self.catalog)
        bad_catalog["quiz"]["questions"][0]["correct"] = 5
        errors = check_font_size(bad_catalog)
        self.assertTrue(any("correct index 5 not in (0, 1, 2)" in e for e in errors))

    def test_canonical_catalog_passes_all_typography_checks(self):
        """Verify that the official translations/minigames_ru.json passes 100% of typography checks."""
        errors = check_font_size(self.catalog)
        self.assertEqual(errors, [], f"Catalog has typography errors: {errors}")

    # ==========================================================================
    # 5. SMINI.UNT Font Extraction & Injection Tests
    # ==========================================================================

    def test_font_tile_extraction_from_03a(self):
        """Test extraction of 16x16 4bpp tiles from synthetic decompressed 0x03A."""
        # Create synthetic decompressed buffer of size 131,616 bytes
        decomp = bytearray(131616)
        gid = 0x0009  # 'А': col = 9, row = 0
        tile_col = gid % 16
        tile_row = gid // 16

        # Populate distinct rows for this tile
        for r in range(16):
            src_off = PROG_FONT_PIXEL_OFFSET + (tile_row * 16 + r) * 512 + (tile_col * 8)
            decomp[src_off : src_off + 8] = bytes([r * 16 + i for i in range(8)])

        tile = extract_03a_bank0_tile(bytes(decomp), gid)
        self.assertEqual(len(tile), 128)
        for r in range(16):
            expected_row = bytes([r * 16 + i for i in range(8)])
            self.assertEqual(tile[r * 8 : (r + 1) * 8], expected_row)

        # Invalid glyph IDs (outside Bank 0)
        with self.assertRaises(ValueError):
            extract_03a_bank0_tile(bytes(decomp), 256)
        with self.assertRaises(ValueError):
            extract_03a_bank0_tile(bytes(decomp), -1)

    def test_extract_prog_font_tiles_dictionary(self):
        """Test extract_prog_font_tiles extracts all requested glyphs into dictionary."""
        decomp = bytearray(131616)
        test_gids = [0x0008, 0x0009, 0x002A, 0x007D]
        tiles = extract_prog_font_tiles(bytes(decomp), test_gids)
        self.assertEqual(len(tiles), len(test_gids))
        for gid in test_gids:
            self.assertIn(gid, tiles)
            self.assertEqual(len(tiles[gid]), 128)

    def test_smini_tile_injection_and_roundtrip(self):
        """Test inject_smini_tile and extract_smini_tile roundtrip."""
        buffer = bytearray(673792)
        base_pixel_off = 0x082BB8
        gid = 0x0009  # 'А' (col 9, row 0)

        # Create known 128-byte test tile
        test_tile = bytes([i % 256 for i in range(128)])
        inject_smini_tile(buffer, base_pixel_off, gid, test_tile)

        # Extract back and verify
        extracted = extract_smini_tile(buffer, base_pixel_off, gid)
        self.assertEqual(extracted, test_tile)

        # Verify that an adjacent tile in the buffer remains untouched (all zeroes)
        adjacent_tile = extract_smini_tile(buffer, base_pixel_off, 0x000A)
        self.assertEqual(adjacent_tile, bytes(128))

        # Invalid tile size raises ValueError
        with self.assertRaises(ValueError):
            inject_smini_tile(buffer, base_pixel_off, gid, b"short")

        # Buffer too small raises IndexError
        small_buffer = bytearray(100)
        with self.assertRaises(IndexError):
            inject_smini_tile(small_buffer, base_pixel_off, gid, test_tile)
        with self.assertRaises(IndexError):
            extract_smini_tile(small_buffer, base_pixel_off, gid)
    def test_patch_smini_fonts_memory_all_entries(self):
        """Test patch_smini_fonts_memory injects into all 5 minigame buffers."""
        entries_data = {
            3: bytearray(673792),
            0: bytearray(655360),
            1: bytearray(694272),
            2: bytearray(671744),
            4: bytearray(393216),
        }
        test_tile = bytes([0x77] * 128)
        font_tiles = {0x0009: test_tile, 0x002A: test_tile}

        stats = patch_smini_fonts_memory(entries_data, font_tiles, [3, 0, 1, 2, 4])
        self.assertEqual(len(stats), 5)
        for e_idx in (3, 0, 1, 2, 4):
            self.assertIn(e_idx, stats)
            self.assertEqual(stats[e_idx]["tiles_injected"], 2)
            spec = SMINI_FONT_SPECS[e_idx]
            extracted = extract_smini_tile(entries_data[e_idx], spec["pixel_offset"], 0x0009)
            self.assertEqual(extracted, test_tile)

    def test_smini_font_specs_integrity(self):
        """Verify SMINI_FONT_SPECS offsets: pixel_offset == file_offset + 0x40."""
        expected_files = {3: 9, 0: 30, 1: 11, 2: 11, 4: 7}
        for e_idx, expected_file in expected_files.items():
            self.assertIn(e_idx, SMINI_FONT_SPECS)
            spec = SMINI_FONT_SPECS[e_idx]
            self.assertEqual(spec["file_index"], expected_file)
            self.assertEqual(
                spec["pixel_offset"],
                spec["file_offset"] + 0x40,
                f"Entry {e_idx} pixel offset must equal file_offset + 0x40 (got 0x{spec['pixel_offset']:X})",
            )

    def test_minigame_font_glyph_ids_coverage(self):
        """Verify MINIGAME_FONT_GLYPH_IDS covers all Russian letters and punctuation."""
        # 1. Cyrillic upper А..Я and Ё
        for ch in "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯЁ":
            self.assertIn(ch, DEFAULT_CHARMAP)
            gid = DEFAULT_CHARMAP[ch]
            self.assertIn(
                gid,
                MINIGAME_FONT_GLYPH_IDS,
                f"Character {ch!r} (0x{gid:04X}) missing from MINIGAME_FONT_GLYPH_IDS",
            )

        # 2. Cyrillic lower а..я and ё
        for ch in "абвгдежзийклмнопрстуфхцчшщъыьэюяё":
            self.assertIn(ch, DEFAULT_CHARMAP)
            gid = DEFAULT_CHARMAP[ch]
            self.assertIn(
                gid,
                MINIGAME_FONT_GLYPH_IDS,
                f"Character {ch!r} (0x{gid:04X}) missing from MINIGAME_FONT_GLYPH_IDS",
            )

        # 3. Space and minigame punctuation
        for ch in (" ", "«", "»", "—", ",", ".", "!", "?", ":", "-", "0", "1", "2", "3", "5"):
            self.assertIn(ch, DEFAULT_CHARMAP)
            gid = DEFAULT_CHARMAP[ch]
            self.assertIn(
                gid,
                MINIGAME_FONT_GLYPH_IDS,
                f"Punctuation {ch!r} (0x{gid:04X}) missing from MINIGAME_FONT_GLYPH_IDS",
            )

        # 4. Total count of glyphs in MINIGAME_FONT_GLYPH_IDS
        self.assertGreaterEqual(len(MINIGAME_FONT_GLYPH_IDS), 79)

        # 5. Latin collision range 0x0057..0x0076 strictly excluded
        for gid in range(0x0057, 0x0077):
            self.assertNotIn(
                gid,
                MINIGAME_FONT_GLYPH_IDS,
                f"Collision glyph 0x{gid:04X} must be excluded from MINIGAME_FONT_GLYPH_IDS",
            )

    def test_smini_entry_1_protected_glyphs_and_buttons(self):
        """Verify SMINI_PROTECTED_GLYPHS and authentic PlayStation button tiles in Entry 1."""
        expected_protected = {0x006B, 0x0074, 0x0075, 0x0076, 0x0077}
        self.assertEqual(SMINI_PROTECTED_GLYPHS, expected_protected)

        # Verify all 5 pristine button tiles are 128 bytes
        for gid in expected_protected:
            self.assertIn(gid, PRISTINE_BUTTON_TILES)
            self.assertEqual(len(PRISTINE_BUTTON_TILES[gid]), 128)

        # Test patch_smini_fonts_memory protects button tiles in Entry 1
        fake_entries = {1: bytearray(694272)}
        dummy_tile = bytes([0x99] * 128)
        font_tiles = {0x006B: dummy_tile, 0x0074: dummy_tile, 0x0008: dummy_tile}
        stats = patch_smini_fonts_memory(fake_entries, font_tiles, [1])
        self.assertIn(1, stats)

        pixel_off = SMINI_FONT_SPECS[1]["pixel_offset"]
        # Button tiles 0x006B and 0x0074 must NOT be dummy_tile, must be PRISTINE_BUTTON_TILES
        tile_circle = extract_smini_tile(fake_entries[1], pixel_off, 0x006B)
        tile_up = extract_smini_tile(fake_entries[1], pixel_off, 0x0074)
        tile_a = extract_smini_tile(fake_entries[1], pixel_off, 0x0008)

        self.assertEqual(tile_circle, PRISTINE_BUTTON_TILES[0x006B])
        self.assertEqual(tile_up, PRISTINE_BUTTON_TILES[0x0074])
        self.assertEqual(tile_a, dummy_tile)

    def test_authoritative_charmap_exact_mappings(self):
        """The minigame charmap must equal the toolkit glyph map, never a literal table.

        Glyph IDs are allocated dynamically per story build (tools/vram_charmap.py),
        so this test checks structure and agreement with the snapshot rather than
        fixed numbers.
        """
        from tools.vram_charmap import load_glyph_map
        cm = build_minigames_charmap()
        glyph_map = load_glyph_map()
        for ch, glyph in glyph_map.items():
            self.assertEqual(cm[ch], glyph, ch)
        # Toolkit allocation order: ascending by code point (cells owned by the
        # English release are skipped, so IDs are increasing but not consecutive)
        upper = "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
        for prev, cur in zip(upper, upper[1:]):
            self.assertLess(cm[prev], cm[cur], cur)
        self.assertLess(cm["Ё"], cm["А"])
        self.assertLess(cm["«"], cm["Ё"])
        self.assertLess(cm["»"], cm["Ё"])
        self.assertLessEqual(max(cm[c] for c in upper + upper.lower() + "ё«»—…"), 0x0056)

        # English base cells are static
        self.assertEqual(cm[" "], 0x007D)
        self.assertEqual(cm["."], 0x00A2)
        self.assertEqual(cm[","], 0x00A1)
        self.assertEqual(cm["!"], 0x00A6)
        self.assertEqual(cm["?"], 0x00A7)
        self.assertEqual(cm[":"], 0x00BC)
        self.assertEqual(cm["-"], 0x00A4)
        for i, d in enumerate("0123456789"):
            self.assertEqual(cm[d], 0x00A8 + i)

        # Reverse charmap priority
        rev = get_reverse_charmap(cm)
        self.assertEqual(rev[cm["«"]], "«")
        self.assertEqual(rev[cm["»"]], "»")
        for ch in "ЁАБЯаяё":
            self.assertEqual(rev[cm[ch]], ch)

    def test_quiz_rules_exact_text_roundtrip(self):
        """Verify Quiz rules decode cleanly without shift, including «Рубак» quotes."""
        expected_text = self.minigames["slayers_quiz"]["rules_ru"]
        self.assertIn("«Рубак»", expected_text)
        budget = self.minigames["slayers_quiz"]["allocated_bytes"]
        encoded = encode_minigame_rules(expected_text, budget)
        decoded = decode_minigame_rules(encoded, budget)
        self.assertEqual(decoded, expected_text)

    def test_naga_dialogues_encoding_and_roundtrip(self):
        """Verify all 6 Naga Laugh dialogues encode with proper control codes and decode bit-exact."""
        dlgs = self.minigames["naga_laugh"]["dialogues"]
        for d_id, d_spec in NAGA_DIALOGUE_SPECS.items():
            text = dlgs[d_id]
            txt_bud = d_spec.get("text_budget", d_spec["budget"])
            is_bubble = d_spec.get("is_bubble", True)

            encoded = encode_minigame_dialogue(text, txt_bud, DEFAULT_CHARMAP, is_bubble=is_bubble)
            self.assertEqual(len(encoded), txt_bud)

            words = [struct.unpack_from("<H", encoded, i)[0] for i in range(0, txt_bud, 2)]

            # Check terminator
            self.assertIn(CHAR_TERMINATOR, words)

            # If speech bubble, check page break 0x00FE before terminator
            if is_bubble:
                term_idx = words.index(CHAR_TERMINATOR)
                self.assertGreater(term_idx, 0)
                self.assertEqual(words[term_idx - 1], CHAR_PAGE)
                # Check intra-bubble page break
                self.assertIn(CHAR_PAGE, words[: term_idx - 1])

            decoded = decode_minigame_dialogue(encoded, txt_bud, is_bubble=is_bubble)
            self.assertEqual(decoded, text, f"{d_id} round-trip mismatch")

    def test_naga_dialogues_budget_overflow_protection(self):
        """Verify that dialogues exceeding their byte budgets raise ValueError."""
        spec = NAGA_DIALOGUE_SPECS["dialogue_1"]
        overflow_text = "А" * 100
        with self.assertRaises(ValueError):
            encode_minigame_dialogue(overflow_text, spec["budget"], DEFAULT_CHARMAP)

    def test_naga_dialogues_pointer_table_integrity(self):
        """Verify 20-byte RAM pointer header in Dialogue 6 matches authoritative values."""
        self.assertEqual(len(NAGA_DIALOGUE_POINTERS), 5)
        self.assertEqual(len(NAGA_DIALOGUE_POINTERS_RAW), 20)
        expected_ptrs = (0x80056578, 0x8005661C, 0x800566C4, 0x8005676C, 0x80056810)
        self.assertEqual(NAGA_DIALOGUE_POINTERS, expected_ptrs)

    def test_naga_dialogues_zero_fill_in_memory(self):
        """Verify that every dialogue buffer in Entry 15 is zero-filled before writing."""
        entry_size = 114688
        mock_entry = bytearray(b"\xFF" * entry_size)
        entries = {13: bytearray(2048), 14: bytearray(2048), 15: mock_entry, 16: bytearray(65536), 17: bytearray(2048)}
        patch_minigames_memory(entries, self.catalog)

        # Verify Dialogue 1 buffer tail has zeroes, not 0xFF
        d1_spec = NAGA_DIALOGUE_SPECS["dialogue_1"]
        d1_end = d1_spec["offset"] + d1_spec["budget"]
        self.assertEqual(mock_entry[d1_end - 4 : d1_end], b"\x00\x00\x00\x00")

        # Verify Dialogue 2 buffer at 0x0806A has 00 00 padding, not 0xFF
        self.assertEqual(mock_entry[0x0806A : 0x0806C], b"\x00\x00")

    def test_amelia_dialogues_pointer_table_integrity(self):
        """Verify 20-byte RAM pointer table for Amelia Cliff Climb matches authoritative values."""
        self.assertEqual(len(AMELIA_DIALOGUE_POINTERS), 5)
        self.assertEqual(len(AMELIA_DIALOGUE_POINTERS_RAW), 20)
        expected_ptrs = (0x8005FA2C, 0x8005FAF4, 0x8005FB9C, 0x8005FC80, 0x8005FD64)
        self.assertEqual(AMELIA_DIALOGUE_POINTERS, expected_ptrs)
        self.assertEqual(AMELIA_POINTER_TABLE_OFFSET, 0x11854)

    def test_amelia_dialogues_zero_fill_in_memory(self):
        """Verify that every dialogue buffer in Entry 14 is zero-filled before writing."""
        entry_size = 157696
        mock_entry = bytearray(b"\xFF" * entry_size)
        entries = {13: bytearray(2048), 14: mock_entry, 15: bytearray(2048), 16: bytearray(65536), 17: bytearray(2048)}
        patch_minigames_memory(entries, self.catalog)

        for d_id in ("dialogue_1", "dialogue_2", "dialogue_3", "dialogue_4", "dialogue_5"):
            d_spec = AMELIA_DIALOGUE_SPECS[d_id]
            off = d_spec["offset"]
            bud = d_spec["budget"]
            self.assertEqual(mock_entry[off + bud - 2 : off + bud], b"\x00\x00", f"{d_id} tail not zero-filled")

        # justice_up exactly fits 32 bytes and ends with 0x00FF terminator
        ju_spec = AMELIA_DIALOGUE_SPECS["justice_up"]
        ju_end = ju_spec["offset"] + ju_spec["budget"]
        self.assertEqual(mock_entry[ju_end - 2 : ju_end], b"\xff\x00", "justice_up ends with 0x00FF terminator")

        # Verify alignment padding for dialogue_3 (0x116CE..0x116D0) and dialogue_4 (0x117B2..0x117B4)
        self.assertEqual(mock_entry[0x116CE:0x116D0], b"\x00\x00")
        self.assertEqual(mock_entry[0x117B2:0x117B4], b"\x00\x00")

    def test_eating_contest_zero_fill_in_memory(self):
        """Verify that every status message buffer in Entry 13 is zero-filled before writing."""
        entry_size = 167936
        mock_entry = bytearray(b"\xFF" * entry_size)
        entries = {13: mock_entry, 14: bytearray(2048), 15: bytearray(2048), 16: bytearray(65536), 17: bytearray(2048)}
        patch_minigames_memory(entries, self.catalog)

        for s_id in ("gourry_satiated", "combined_status"):
            s_spec = EATING_STATUS_SPECS[s_id]
            off = s_spec["offset"]
            bud = s_spec["budget"]
            self.assertEqual(mock_entry[off + bud - 2 : off + bud], b"\x00\x00", f"{s_id} tail not zero-filled")

        # lina_morale exactly fits 72 bytes and ends with 0x00FF terminator
        lm_spec = EATING_STATUS_SPECS["lina_morale"]
        lm_end = lm_spec["offset"] + lm_spec["budget"]
        self.assertEqual(mock_entry[lm_end - 2 : lm_end], b"\xff\x00", "lina_morale ends with 0x00FF terminator")

    def test_bandit_bullying_time_bonus_zero_fill_in_memory(self):
        """Verify that time bonus buffer in Entry 17 is zero-filled before writing."""
        entry_size = 217088
        mock_entry = bytearray(b"\xFF" * entry_size)
        entries = {13: bytearray(2048), 14: bytearray(2048), 15: bytearray(2048), 16: bytearray(65536), 17: mock_entry}
        patch_minigames_memory(entries, self.catalog)

        off = BANDIT_BONUS_SPEC["offset"]
        bud = BANDIT_BONUS_SPEC["budget"]
        self.assertEqual(mock_entry[off + bud - 2 : off + bud], b"\x00\x00")

    def test_amelia_dialogues_budget_overflow_protection(self):
        """Verify that Amelia dialogues exceeding their byte budgets raise ValueError."""
        for d_id, d_spec in AMELIA_DIALOGUE_SPECS.items():
            budget = d_spec["budget"]
            is_bubble = d_spec.get("is_bubble", True)
            overflow_text = "А" * (budget // 2 + 1)
            with self.assertRaises(ValueError):
                if is_bubble:
                    encode_minigame_dialogue(overflow_text, budget, DEFAULT_CHARMAP, is_bubble=True)
                else:
                    encode_minigame_string(overflow_text, budget, DEFAULT_CHARMAP)

    def test_eating_status_budget_overflow_protection(self):
        """Verify that Eating Contest messages exceeding their byte budgets raise ValueError."""
        for s_id, s_spec in EATING_STATUS_SPECS.items():
            budget = s_spec["budget"]
            overflow_text = "А" * (budget // 2 + 1)
            with self.assertRaises(ValueError):
                encode_minigame_dialogue(overflow_text, budget, DEFAULT_CHARMAP, is_bubble=False)

    def test_bandit_bonus_budget_overflow_protection(self):
        """Verify that Bandit Bullying time bonus exceeding budget raises ValueError."""
        budget = BANDIT_BONUS_SPEC["budget"]
        overflow_text = "А" * (budget // 2 + 1)
        with self.assertRaises(ValueError):
            encode_minigame_string(overflow_text, budget, DEFAULT_CHARMAP)


    def test_amelia_combo_blocks_encoding_and_roundtrip(self):
        """Verify Amelia combo window blocks encode to exact byte budgets and decode bit-exact."""
        labels = {"header": "ОК:", "level_a": "УРА:", "level_b": "УРБ:", "level_c": "УРВ:", "level_s": "УРС:"}
        expected_budgets = {1: 92, 2: 100, 3: 100}

        for diff, exp_budget in expected_budgets.items():
            encoded = encode_amelia_combo_block(diff, labels)
            self.assertEqual(len(encoded), exp_budget)

            decoded = decode_amelia_combo_block(encoded, exp_budget)
            self.assertIn("ОК:", decoded)
            self.assertIn("УРА:", decoded)
            self.assertIn("УРБ:", decoded)
            self.assertIn("УРВ:", decoded)
            self.assertIn("УРС:", decoded)
            self.assertIn("○", decoded)
            self.assertIn("?", decoded)

    def test_amelia_combo_pointer_table_integrity(self):
        """Verify Amelia combo pointer table matches authoritative RAM addresses."""
        self.assertEqual(len(AMELIA_COMBO_POINTERS), 3)
        self.assertEqual(len(AMELIA_COMBO_POINTERS_RAW), 12)
        self.assertEqual(AMELIA_COMBO_POINTERS, (0x8005FE18, 0x8005FE74, 0x8005FED8))

    def test_amelia_combo_budget_overflow_protection(self):
        """Verify Amelia combo block raises ValueError when label exceeds budget."""
        bad_labels = {"header": "О" * 50}
        with self.assertRaises(ValueError):
            encode_amelia_combo_block(1, bad_labels)

if __name__ == "__main__":
    unittest.main()
