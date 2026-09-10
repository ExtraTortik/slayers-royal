#!/usr/bin/env python3
"""Test suite verifying translations/combat_dialogues_ru.json against all requirements."""

from __future__ import annotations
import json
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from tools.combat_dialogue_charmap import build_combat_dialogue_charmap
from tools.patch_combat_dialogues import encode_conversation_block

CATALOG_PATH = REPO_ROOT / "translations" / "combat_dialogues_ru.json"
CHARMAP = build_combat_dialogue_charmap()


class TestCombatDialoguesCatalog(unittest.TestCase):
    """Validation of translations/combat_dialogues_ru.json structure and constraints."""

    @classmethod
    def setUpClass(cls):
        cls.assertTrue(CATALOG_PATH.is_file(), f"Catalog not found at {CATALOG_PATH}")
        cls.data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    def test_json_structure_and_metadata(self):
        """Verify top-level JSON structure and metadata fields."""
        self.assertIn("metadata", self.data)
        self.assertIn("blocks", self.data)
        meta = self.data["metadata"]
        self.assertEqual(meta["version"], "1.0")
        self.assertEqual(meta["source_archive"], "PROG.UNT")
        self.assertEqual(meta["entry_index"], "0x007")
        self.assertEqual(meta["dialogue_stream_offset"], "0x05F810")
        self.assertEqual(meta["total_blocks"], 114)
        self.assertEqual(meta["max_chars_per_line"], 21)
        self.assertEqual(meta["max_lines_per_bubble"], 3)

    def test_blocks_count_and_indexing(self):
        """Verify exactly 114 blocks indexed block_001..block_114."""
        blocks = self.data["blocks"]
        self.assertEqual(len(blocks), 114)
        for i, b in enumerate(blocks):
            expected_id = f"block_{i+1:03d}"
            self.assertEqual(b["id"], expected_id)
            self.assertEqual(b["block_index"], i + 1)
            self.assertTrue(b["offset"].startswith("0x"))
            self.assertTrue(b["ram_address"].startswith("0x80"))
            self.assertGreater(b["allocated_budget_bytes"], 0)
            self.assertGreater(len(b["bubbles"]), 0)

    def test_bubble_formatting_constraints(self):
        """Verify max 21 chars per line and max 3 lines per bubble."""
        for b in self.data["blocks"]:
            for bub in b["bubbles"]:
                text_ru = bub["text_ru"]
                self.assertTrue(text_ru, f"Empty text_ru in {b['id']}")
                lines = text_ru.split("\n")
                self.assertLessEqual(
                    len(lines),
                    3,
                    f"Bubble {bub['bubble_index']} in {b['id']} exceeds 3 lines: {text_ru!r}"
                )
                for l in lines:
                    self.assertLessEqual(
                        len(l),
                        21,
                        f"Line {l!r} in {b['id']} exceeds 21 chars (len={len(l)})"
                    )

    def test_english_reference_text_no_corrupted_kanji(self):
        """Verify that English text contains 0 corrupted kanji or unmapped digraphs."""
        for b in self.data["blocks"]:
            for bub in b["bubbles"]:
                text_en = bub["text_en"]
                for ch in text_en:
                    # Character code >= 0x4E00 indicates a CJK ideograph (kanji fallback)
                    self.assertLess(
                        ord(ch),
                        0x4E00,
                        f"Corrupted kanji {ch!r} (U+{ord(ch):04X}) in {b['id']} English text: {text_en!r}"
                    )

    def test_encoded_block_budgets(self):
        """Verify every block's binary encoded size fits inside allocated_budget_bytes."""
        for b in self.data["blocks"]:
            encoded = encode_conversation_block(b, CHARMAP)
            budget = b["allocated_budget_bytes"]
            self.assertLessEqual(
                len(encoded),
                budget,
                f"Block {b['id']} at {b['offset']} exceeds budget: {len(encoded)} > {budget}"
            )

    def test_screenshot_dialogue_block_0x06241C(self):
        """Verify block at offset 0x06241C specifically (the interfered phrase)."""
        b_target = next(b for b in self.data["blocks"] if b["offset"] == "0x06241C")
        self.assertIsNotNone(b_target)
        self.assertEqual(len(b_target["bubbles"]), 3)
        self.assertEqual(b_target["allocated_budget_bytes"], 196)

        # Bubble 1: Mercenary 0xD26A
        bub1 = b_target["bubbles"][0]
        self.assertEqual(bub1["speaker_opcode"], "0xD26A")
        self.assertEqual(bub1["speaker"], "Наёмник")
        self.assertTrue("interfeer" in bub1["text_en"] or "interfer" in bub1["text_en"])
        self.assertTrue("Пошла б" in bub1["text_ru"] or "Шла бы" in bub1["text_ru"] or "ногами" in bub1["text_ru"] or "нос" in bub1["text_ru"])

        # Bubble 2: Sylphiel 0x91C4
        bub2 = b_target["bubbles"][1]
        self.assertEqual(bub2["speaker_opcode"], "0x91C4")
        self.assertEqual(bub2["speaker"], "Сильфиль")
        self.assertTrue("Shut up" in bub2["text_en"])
        self.assertTrue("Заткнись" in bub2["text_ru"])

        # Bubble 3: Mercenary 0xD263
        bub3 = b_target["bubbles"][2]
        self.assertEqual(bub3["speaker_opcode"], "0xD263")
        self.assertEqual(bub3["speaker"], "Наёмник")
        self.assertTrue("Scary" in bub3["text_en"])
        self.assertTrue("страшно" in bub3["text_ru"] or "спеси" in bub3["text_ru"])

        # Check encoded size
        enc = encode_conversation_block(b_target, CHARMAP)
        self.assertLessEqual(len(enc), 196)


if __name__ == "__main__":
    unittest.main()
