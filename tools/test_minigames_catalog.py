#!/usr/bin/env python3
"""Test suite verifying translations/minigames_ru.json against all specifications and constraints."""

from __future__ import annotations
import json
from pathlib import Path
import unittest
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from tools.patch_minigames import (
    AMELIA_DIALOGUE_SPECS,
    BANDIT_BONUS_SPEC,
    CHAR_NEWLINE,
    CHAR_PAGE,
    CHAR_TERMINATOR,
    DEFAULT_CHARMAP,
    EATING_STATUS_SPECS,
    MINIGAME_SPECS,
    NAGA_DIALOGUE_SPECS,
    build_minigames_charmap,
    decode_amelia_combo_block,
    encode_amelia_combo_block,
    decode_minigame_dialogue,
    decode_minigame_stream,
    decode_minigame_string,
    encode_minigame_dialogue,
    encode_minigame_stream,
    encode_minigame_string,
)
CATALOG_PATH = REPO_ROOT / "translations" / "minigames_ru.json"
RENPY_QUIZ_PATH = REPO_ROOT / "renpy_extracted" / "game" / "quiz.rpy"


class TestMinigamesCatalog(unittest.TestCase):
    """Validation of translations/minigames_ru.json structure, typography, and constraints."""

    @classmethod
    def setUpClass(cls):
        cls.assertTrue(CATALOG_PATH.is_file(), f"Catalog not found at {CATALOG_PATH}")
        cls.data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    def test_json_structure_and_metadata(self):
        """Verify top-level JSON structure, metadata, and typography instructions."""
        self.assertIn("metadata", self.data)
        self.assertIn("minigames", self.data)
        self.assertIn("quiz", self.data)

        meta = self.data["metadata"]
        self.assertEqual(meta["target_archive"], "PROG.UNT")
        self.assertIn("typography", meta)
        typo = meta["typography"]
        self.assertIn("font_size", typo)
        self.assertIn("minigames_rules_limits", typo)
        self.assertIn("quiz_questions_limits", typo)

        q_limits = typo["quiz_questions_limits"]
        self.assertEqual(q_limits["q_line1_max_chars"], 15)
        self.assertEqual(q_limits["q_line2_max_chars"], 15)
        self.assertEqual(q_limits["option_max_chars"], 15)
        self.assertEqual(q_limits["slot_bytes"], 32)
        self.assertEqual(q_limits["record_bytes"], 164)

    def test_minigames_descriptions_and_budgets(self):
        """Verify all 5 minigames: line count <= 10, line length <= 20 chars, bytes <= budget."""
        expected_minigames = {
            "eating_contest": {"entry": 13, "budget": 328, "offset": 0x07320},
            "amelia_climb": {"entry": 14, "budget": 354, "offset": 0x11318},
            "naga_laugh": {"entry": 15, "budget": 274, "offset": 0x07EB4},
            "slayers_quiz": {"entry": 16, "budget": 252, "offset": 0x08184},
            "bandit_bullying": {"entry": 17, "budget": 346, "offset": 0x082B8},
        }

        minigames = self.data["minigames"]
        self.assertEqual(set(minigames.keys()), set(expected_minigames.keys()))

        for mg_id, exp in expected_minigames.items():
            mg = minigames[mg_id]
            self.assertEqual(mg["id"], mg_id)
            self.assertEqual(mg["prog_entry"], exp["entry"])
            self.assertEqual(mg["allocated_bytes"], exp["budget"])
            self.assertEqual(int(mg["offset_hex"], 16), exp["offset"])
            self.assertIn("rules_ru", mg)
            self.assertIn("description", mg)

            rules_text = mg["rules_ru"]
            lines = rules_text.split("\n")
            self.assertLessEqual(
                len(lines), 10, f"Minigame {mg_id} has {len(lines)} lines > 10"
            )

            for line_idx, line in enumerate(lines):
                self.assertLessEqual(
                    len(line),
                    20,
                    f"Minigame {mg_id} line {line_idx+1} exceeds 20 chars ({len(line)}): {line!r}",
                )
                for ch in line:
                    self.assertIn(
                        ch,
                        DEFAULT_CHARMAP,
                        f"Minigame {mg_id} line {line_idx+1} has unmapped char {ch!r}",
                    )

            # Check byte budget: (len(rules_text) + 1) * 2 bytes <= allocated_bytes
            total_bytes = (len(rules_text) + 1) * 2
            self.assertLessEqual(
                total_bytes,
                exp["budget"],
                f"Minigame {mg_id} exceeds byte budget: {total_bytes} > {exp['budget']}",
            )

    def test_minigames_title_banners(self):
        """Verify all 5 minigames have title banners within byte budget and mapped chars."""
        expected_banners = {
            "eating_contest": {"title": "Обед:", "budget": 328, "offset": 0x07320},
            "amelia_climb": {"title": "Прыжок:", "budget": 354, "offset": 0x11318},
            "naga_laugh": {"title": "Смех Наги:", "budget": 274, "offset": 0x07EB4},
            "slayers_quiz": {"title": "Викторина:", "budget": 252, "offset": 0x08184},
            "bandit_bullying": {"title": "Отстрел:", "budget": 346, "offset": 0x082B8},
        }
        minigames = self.data["minigames"]
        for mg_id, exp in expected_banners.items():
            mg = minigames[mg_id]
            self.assertIn("title_banner", mg, f"Minigame {mg_id} missing 'title_banner'")
            self.assertEqual(mg["title_banner"], exp["title"])
            self.assertIn("title_banner_offset_hex", mg)
            self.assertEqual(int(mg["title_banner_offset_hex"], 16), exp["offset"])
            self.assertIn("title_banner_budget", mg)
            self.assertEqual(mg["title_banner_budget"], exp["budget"])

            tb = mg["title_banner"]
            for ch in tb:
                self.assertIn(ch, DEFAULT_CHARMAP, f"Minigame {mg_id} title banner unmapped char {ch!r}")

            total_bytes = (len(tb) + 1) * 2
            self.assertLessEqual(total_bytes, exp["budget"])
            for ch in tb:
                self.assertNotEqual(
                    DEFAULT_CHARMAP[ch],
                    CHAR_TERMINATOR,
                    f"Minigame {mg_id} title banner contains 0x00FF terminator: {ch!r}",
                )

    def test_unified_rules_stream_encoding_and_budgets(self):
        """Verify unified continuous stream fits within budgets, has no premature 0x00FF, and round-trips."""
        import struct
        minigames = self.data["minigames"]
        for mg_id, exp in MINIGAME_SPECS.items():
            mg = minigames[mg_id]
            title = mg["title_banner"]
            rules = mg["rules_ru"]
            budget = exp["budget"]

            # 1. Combined stream fits within budget
            stream = encode_minigame_stream(title, rules, budget)
            self.assertEqual(len(stream), budget)

            # 2. Verify no 0x00FF occurs between title and rules
            words = [struct.unpack_from("<H", stream, i)[0] for i in range(0, len(stream), 2)]
            self.assertEqual(words[0], 0x0000, f"Minigame {mg_id} missing leading 0x0000 indent")

            # Find double newline separator \n\n (0x00FD, 0x00FD)
            sep_idx = None
            for i in range(1, len(words) - 1):
                if words[i] == CHAR_NEWLINE and words[i + 1] == CHAR_NEWLINE:
                    sep_idx = i
                    break
            self.assertIsNotNone(sep_idx, f"Minigame {mg_id} missing \\n\\n separator")

            # Ensure no 0x00FF anywhere in title banner or separator
            for i in range(sep_idx + 2):
                self.assertNotEqual(
                    words[i],
                    CHAR_TERMINATOR,
                    f"0x00FF found before rules in minigame {mg_id} at word index {i}",
                )

            # 3. Exactly one terminator in non-padding words
            non_pad = [w for w in words if w != 0x0000]
            self.assertEqual(
                non_pad.count(CHAR_TERMINATOR),
                1,
                f"Minigame {mg_id} should have exactly 1 terminator, found {non_pad.count(CHAR_TERMINATOR)}",
            )

            # 4. Verify decoding starting from title_start_offset reads title, advances past \n\n, and reads rules
            dec_title, dec_rules = decode_minigame_stream(stream, budget)
            self.assertEqual(dec_title, title)
            self.assertEqual(dec_rules, rules)

    def test_quiz_contestant_prompt_and_results_screen(self):
        """Verify Quiz contestant prompt and results screen fields, charmap, and budgets."""
        quiz_mg = self.data["minigames"]["slayers_quiz"]
        self.assertIn("contestant_prompt", quiz_mg)
        self.assertEqual(quiz_mg["contestant_prompt"], "Кто играет?")
        self.assertEqual(quiz_mg["contestant_prompt_budget"], 24)
        for ch in quiz_mg["contestant_prompt"]:
            self.assertIn(ch, DEFAULT_CHARMAP, f"Contestant prompt unmapped char {ch!r}")
        self.assertLessEqual((len(quiz_mg["contestant_prompt"]) + 1) * 2, 24)

        self.assertIn("results_screen", quiz_mg)
        rs = quiz_mg["results_screen"]
        expected_rs = {
            "header": {"text": "Итог:", "budget": 16, "offset": 0x0829C},
            "correct_count": {"text": "Верно:     в", "budget": 26, "offset": 0x082AC},
            "avg_speed": {"text": "Ср. время:     с", "budget": 34, "offset": 0x082C6},
        }
        for field, exp in expected_rs.items():
            self.assertIn(field, rs, f"Results screen missing {field}")
            self.assertEqual(rs[field], exp["text"])
            for ch in rs[field]:
                self.assertIn(ch, DEFAULT_CHARMAP, f"Results screen {field} unmapped char {ch!r}")
            self.assertLessEqual((len(rs[field]) + 1) * 2, exp["budget"])

    def test_quiz_description_transferred_from_renpy(self):
        """Verify the quiz description contains the original text from Ren'Py quiz.rpy."""
        quiz_meta = self.data["minigames"]["slayers_quiz"]
        self.assertIn("renpy_help_title", quiz_meta)
        self.assertIn("renpy_help_desc", quiz_meta)

        self.assertIn("100 вопросов", quiz_meta["renpy_help_desc"])
        self.assertIn("Рубак", quiz_meta["renpy_help_desc"])
        self.assertIn("двух ошибок", quiz_meta["renpy_help_desc"])
        self.assertIn("времени", quiz_meta["renpy_help_desc"])

    def test_quiz_questions_count_and_indexing(self):
        """Verify exactly 100 questions with complete ps1_index (0..99) and renpy_id (1..100)."""
        questions = self.data["quiz"]["questions"]
        self.assertEqual(len(questions), 100)

        ps1_indices = [q["ps1_index"] for q in questions]
        renpy_ids = [q["renpy_id"] for q in questions]

        self.assertEqual(ps1_indices, list(range(100)))
        self.assertEqual(sorted(renpy_ids), list(range(1, 101)))

    def test_quiz_questions_character_limits_and_charmap(self):
        """Verify 100% of quiz questions: q_line1, q_line2, opt1, opt2, opt3 strictly <= 15 chars and in DEFAULT_CHARMAP."""
        questions = self.data["quiz"]["questions"]

        for q in questions:
            idx = q["ps1_index"]
            r_id = q["renpy_id"]
            self.assertIn("font_size", q)

            for field in ["q_line1", "q_line2", "opt1", "opt2", "opt3"]:
                val = q[field]
                self.assertIsInstance(val, str)
                self.assertGreater(len(val), 0, f"Q{idx} ({r_id}): {field} is empty")
                self.assertLessEqual(
                    len(val),
                    15,
                    f"Q{idx} ({r_id}): {field} exceeds 15 chars ({len(val)}): {val!r}",
                )

                for ch in val:
                    self.assertIn(
                        ch,
                        DEFAULT_CHARMAP,
                        f"Q{idx} ({r_id}): {field} character {ch!r} not in DEFAULT_CHARMAP: {val!r}",
                    )

    def test_quiz_questions_correct_index_matches_renpy(self):
        """Verify correct answer index strictly in {0, 1, 2} and matches Ren'Py answer."""
        questions = self.data["quiz"]["questions"]

        for q in questions:
            idx = q["ps1_index"]
            r_id = q["renpy_id"]
            corr = q["correct"]
            self.assertIn(corr, (0, 1, 2), f"Q{idx} ({r_id}): correct {corr} not in {0, 1, 2}")

            # Verify against renpy_source
            r_src = q["renpy_source"]
            opts_ru = r_src["opts_ru"]
            corr_ru = r_src["correct_ru"]
            expected_idx = opts_ru.index(corr_ru)
            self.assertEqual(
                corr,
                expected_idx,
                f"Q{idx} ({r_id}): correct index {corr} does not match Ren'Py source index {expected_idx} ({corr_ru})",
            )

    def test_naga_laugh_dialogues_catalog(self):
        """Verify all 6 Naga Laugh dialogues in minigames_ru.json: line limits <= 20, budgets, and charmap."""
        nl = self.data["minigames"]["naga_laugh"]
        self.assertIn("dialogues", nl, "naga_laugh missing 'dialogues' field")
        dlgs = nl["dialogues"]

        expected_ids = {"dialogue_1", "dialogue_2", "dialogue_3", "dialogue_4", "dialogue_5", "dialogue_6"}
        self.assertEqual(set(dlgs.keys()), expected_ids, f"Dialogue keys mismatch: {set(dlgs.keys())} != {expected_ids}")

        for d_id in sorted(expected_ids):
            spec = NAGA_DIALOGUE_SPECS[d_id]
            d_val = dlgs[d_id]
            text = d_val if isinstance(d_val, str) else d_val.get("text", "")
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), 0, f"{d_id} text is empty")

            # Verify each line length <= 20 chars
            pages = text.split("\f")
            if spec.get("is_bubble", True):
                self.assertGreaterEqual(len(pages), 2, f"{d_id} expected at least 2 pages separated by \\f")

            for p_idx, page in enumerate(pages):
                lines = page.split("\n")
                for l_idx, line in enumerate(lines):
                    self.assertLessEqual(
                        len(line),
                        20,
                        f"{d_id} p{p_idx+1} line {l_idx+1} exceeds 20 chars ({len(line)}): {line!r}",
                    )
                    for ch in line:
                        self.assertIn(
                            ch,
                            DEFAULT_CHARMAP,
                            f"{d_id} p{p_idx+1} line {l_idx+1}: character {ch!r} not in DEFAULT_CHARMAP",
                        )

            # Verify byte budget
            txt_budget = spec.get("text_budget", spec["budget"])
            is_bubble = spec.get("is_bubble", True)
            encoded = encode_minigame_dialogue(text, txt_budget, DEFAULT_CHARMAP, is_bubble=is_bubble)
            self.assertLessEqual(
                len(encoded),
                txt_budget,
                f"{d_id} encoded size ({len(encoded)}) exceeds budget ({txt_budget})",
            )

            # Verify round-trip decode
            decoded = decode_minigame_dialogue(encoded, txt_budget, is_bubble=is_bubble)
            self.assertEqual(
                decoded,
                text,
                f"{d_id} round-trip mismatch:\n  Expected: {text!r}\n  Found:    {decoded!r}",
            )


    def test_amelia_climb_dialogues_catalog(self):
        """Verify all 6 Amelia Cliff Climb dialogues (5 justice speeches + justice_up) in minigames_ru.json."""
        ac = self.data["minigames"]["amelia_climb"]
        self.assertIn("dialogues", ac, "amelia_climb missing 'dialogues' field")
        dlgs = ac["dialogues"]

        expected_ids = {"dialogue_1", "dialogue_2", "dialogue_3", "dialogue_4", "dialogue_5", "justice_up"}
        self.assertEqual(set(dlgs.keys()), expected_ids, f"Dialogue keys mismatch: {set(dlgs.keys())} != {expected_ids}")

        for d_id in sorted(expected_ids):
            spec = AMELIA_DIALOGUE_SPECS[d_id]
            d_val = dlgs[d_id]
            text = d_val if isinstance(d_val, str) else d_val.get("text", "")
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), 0, f"{d_id} text is empty")

            # Verify each line length <= 20 chars
            pages = text.split("\f")
            is_bubble = spec.get("is_bubble", True)
            if is_bubble:
                self.assertGreaterEqual(len(pages), 2, f"{d_id} expected at least 2 pages separated by \\f")

            for p_idx, page in enumerate(pages):
                lines = page.split("\n")
                for l_idx, line in enumerate(lines):
                    self.assertLessEqual(
                        len(line),
                        20,
                        f"{d_id} p{p_idx+1} line {l_idx+1} exceeds 20 chars ({len(line)}): {line!r}",
                    )
                    for ch in line:
                        self.assertIn(
                            ch,
                            DEFAULT_CHARMAP,
                            f"{d_id} p{p_idx+1} line {l_idx+1}: character {ch!r} not in DEFAULT_CHARMAP",
                        )

            # Verify byte budget & round-trip
            budget = spec["budget"]
            if is_bubble:
                encoded = encode_minigame_dialogue(text, budget, DEFAULT_CHARMAP, is_bubble=True)
                self.assertEqual(len(encoded), budget)
                decoded = decode_minigame_dialogue(encoded, budget, is_bubble=True)
            else:
                encoded = encode_minigame_string(text, budget, DEFAULT_CHARMAP)
                self.assertEqual(len(encoded), budget)
                decoded = decode_minigame_string(encoded, budget)

            self.assertEqual(
                decoded,
                text,
                f"{d_id} round-trip mismatch:\n  Expected: {text!r}\n  Found:    {decoded!r}",
            )


    def test_amelia_climb_combo_window_catalog(self):
        """Verify amelia_climb combo_window labels, characters, and budgets in minigames_ru.json."""
        ac = self.data["minigames"]["amelia_climb"]
        self.assertIn("combo_window", ac, "amelia_climb missing 'combo_window' field")
        cw = ac["combo_window"]

        self.assertEqual(cw.get("header"), "ОК:")
        self.assertEqual(cw.get("level_a"), "УРА:")
        self.assertEqual(cw.get("level_b"), "УРБ:")
        self.assertEqual(cw.get("level_c"), "УРВ:")
        self.assertEqual(cw.get("level_s"), "УРС:")

        for k, text in cw.items():
            for ch in text:
                self.assertIn(
                    ch,
                    DEFAULT_CHARMAP,
                    f"combo_window '{k}' character {ch!r} not in DEFAULT_CHARMAP",
                )

        # Test encoding all 3 difficulty blocks with catalog labels
        b1 = encode_amelia_combo_block(1, cw)
        b2 = encode_amelia_combo_block(2, cw)
        b3 = encode_amelia_combo_block(3, cw)

        self.assertEqual(len(b1), 92)
        self.assertEqual(len(b2), 100)
        self.assertEqual(len(b3), 100)

        # Test decoding
        dec1 = decode_amelia_combo_block(b1, 92)
        self.assertIn("ОК:", dec1)
        self.assertIn("○", dec1)
    def test_eating_contest_status_messages_catalog(self):
        """Verify all 3 Eating Contest status messages in minigames_ru.json: line limits <= 20, budgets, and charmap."""
        ec = self.data["minigames"]["eating_contest"]
        self.assertIn("status_messages", ec, "eating_contest missing 'status_messages' field")
        msgs = ec["status_messages"]

        expected_ids = {"lina_morale", "gourry_satiated", "combined_status"}
        self.assertEqual(set(msgs.keys()), expected_ids, f"Status message keys mismatch: {set(msgs.keys())} != {expected_ids}")

        for s_id in sorted(expected_ids):
            spec = EATING_STATUS_SPECS[s_id]
            s_val = msgs[s_id]
            text = s_val if isinstance(s_val, str) else s_val.get("text", "")
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), 0, f"{s_id} text is empty")

            lines = text.split("\n")
            for l_idx, line in enumerate(lines):
                self.assertLessEqual(
                    len(line),
                    20,
                    f"{s_id} line {l_idx+1} exceeds 20 chars ({len(line)}): {line!r}",
                )
                for ch in line:
                    self.assertIn(
                        ch,
                        DEFAULT_CHARMAP,
                        f"{s_id} line {l_idx+1}: character {ch!r} not in DEFAULT_CHARMAP",
                    )

            budget = spec["budget"]
            encoded = encode_minigame_dialogue(text, budget, DEFAULT_CHARMAP, is_bubble=False)
            self.assertEqual(len(encoded), budget)
            decoded = decode_minigame_dialogue(encoded, budget, is_bubble=False)
            self.assertEqual(
                decoded,
                text,
                f"{s_id} round-trip mismatch:\n  Expected: {text!r}\n  Found:    {decoded!r}",
            )

    def test_bandit_bullying_time_bonus_catalog(self):
        """Verify Bandit Bullying time bonus in minigames_ru.json: charmap, budget <= 20, and round-trip."""
        bb = self.data["minigames"]["bandit_bullying"]
        self.assertIn("time_bonus", bb, "bandit_bullying missing 'time_bonus' field")
        tb = bb["time_bonus"]
        self.assertIsInstance(tb, str)
        self.assertGreater(len(tb), 0, "time_bonus is empty")
        self.assertLessEqual(len(tb), 20, f"time_bonus exceeds 20 chars: {tb!r}")

        for ch in tb:
            self.assertIn(ch, DEFAULT_CHARMAP, f"time_bonus: character {ch!r} not in DEFAULT_CHARMAP")

        budget = BANDIT_BONUS_SPEC["budget"]
        encoded = encode_minigame_string(tb, budget, DEFAULT_CHARMAP)
        self.assertEqual(len(encoded), budget)
        decoded = decode_minigame_string(encoded, budget)
        self.assertEqual(decoded, tb)

if __name__ == "__main__":
    unittest.main()
