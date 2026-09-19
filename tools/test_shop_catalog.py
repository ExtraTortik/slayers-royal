#!/usr/bin/env python3
"""Validation test suite for translations/shop_dialogues_ru.json."""

import json
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.patch_minigames import build_minigames_charmap

CATALOG_PATH = REPO_ROOT / "translations" / "shop_dialogues_ru.json"


class TestShopCatalog(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CATALOG_PATH.is_file(), f"Catalog file not found: {CATALOG_PATH}")
        self.data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.charmap = build_minigames_charmap()

    def test_metadata_structure(self):
        meta = self.data.get("meta", {})
        self.assertEqual(meta.get("entry_index"), 3)
        self.assertEqual(meta.get("entry_lba"), 229219)
        self.assertEqual(meta.get("ram_base"), "0x8004E5B0")
        self.assertEqual(meta.get("total_dialogues"), 98)
        self.assertEqual(meta.get("total_pointers"), 100)
        self.assertEqual(meta.get("total_items"), 91)

    def test_all_100_pointers_mapped(self):
        dialogues = self.data.get("dialogues", {})
        all_ptrs = []
        for d_id, d in dialogues.items():
            for p in d["pointer_offsets_hex"]:
                all_ptrs.append(int(p, 16))

        self.assertEqual(len(all_ptrs), 100, f"Expected 100 pointers, got {len(all_ptrs)}")

        # Table 1: 84 pointers (0x031F14..0x032060, step 4)
        t1_expected = [0x031F14 + i * 4 for i in range(84)]
        # Table 2: 16 pointers (0x0322B0..0x0322EC, step 4)
        t2_expected = [0x0322B0 + i * 4 for i in range(16)]

        expected_all = sorted(t1_expected + t2_expected)
        actual_all = sorted(all_ptrs)
        self.assertEqual(actual_all, expected_all, "Pointer table coverage mismatch")

    def test_dialogue_formatting_and_constraints(self):
        dialogues = self.data.get("dialogues", {})
        for d_id, d in dialogues.items():
            text_ru = d.get("text_ru", "")
            self.assertTrue(text_ru, f"Empty text_ru in {d_id}")

            # Ensure no Japanese characters
            jp_match = re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", text_ru)
            self.assertIsNone(
                jp_match,
                f"Untranslated Japanese characters in {d_id}: '{text_ru}'",
            )

            # Check pages and lines
            pages = text_ru.split("\f")
            for p_idx, page in enumerate(pages):
                lines = page.split("\n")
                self.assertLessEqual(
                    len(lines),
                    3,
                    f"Too many lines ({len(lines)} > 3) in {d_id} page {p_idx}: {lines}",
                )
                for l_idx, line in enumerate(lines):
                    # Strip <XXXX> escape tags for length check
                    clean_line = re.sub(r"<[0-9A-Fa-f]{4}>", "", line)
                    self.assertLessEqual(
                        len(clean_line),
                        15,
                        f"Line too long ({len(clean_line)} > 15) in {d_id}: '{line}'",
                    )

    def test_cyrillic_charmap_validity(self):
        dialogues = self.data.get("dialogues", {})
        for d_id, d in dialogues.items():
            text_ru = d.get("text_ru", "")
            clean_text = re.sub(r"<[0-9A-Fa-f]{4}>", "", text_ru)
            for ch in clean_text:
                if ch in ("\n", "\f", "\r"):
                    continue
                self.assertIn(
                    ch,
                    self.charmap,
                    f"Character {ch!r} (U+{ord(ch):04X}) in {d_id} not in authoritative charmap!",
                )

    def test_shop_items_table(self):
        items = self.data.get("shop_items", [])
        self.assertEqual(len(items), 91, f"Expected 91 shop items, got {len(items)}")

        for idx, item in enumerate(items):
            self.assertEqual(item["index"], idx)
            expected_ptr = f"0x{0x030A20 + idx * 4:06X}"
            self.assertEqual(item["pointer_offset_hex"], expected_ptr)
            self.assertTrue(item["offset_hex"].startswith("0x030"))
            self.assertTrue(item["text_jp"])
            self.assertTrue(item["text_ru"])

            # Check Cyrillic encoding of text_ru
            for ch in item["text_ru"]:
                self.assertIn(
                    ch,
                    self.charmap,
                    f"Character {ch!r} in shop item {idx} ('{item['text_ru']}') not in charmap!",
                )

            # Ensure no Japanese characters in text_ru
            jp_match = re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", item["text_ru"])
            self.assertIsNone(
                jp_match,
                f"Untranslated Japanese characters in shop item {idx}: '{item['text_ru']}'",
            )

        for idx, item in enumerate(items):
            self.assertLessEqual(
                len(item["text_ru"]),
                8,
                f"Shop item {idx} ('{item['text_ru']}') exceeds 8 chars limit for inventory display!",
            )
    def test_stat_column_widths_and_overlay_positioning(self):
        items = self.data.get("shop_items", [])
        expected_compact_stats = {
            7: "Ф.Атк",
            8: "Ф.Защ",
            9: "М.Атк",
            10: "М.Защ",
            11: "Точн.",
            12: "Уклон",
        }
        for idx, exp_label in expected_compact_stats.items():
            actual = items[idx]["text_ru"]
            self.assertEqual(
                actual,
                exp_label,
                f"Stat {idx} must be compact label {exp_label}, got {actual}",
            )
            self.assertLessEqual(len(actual), 5, f"Stat {idx} label exceeds 5 chars: {actual}")

        dialogues = self.data.get("dialogues", {})
        # Check buy_suggest_weapon
        sugg_lines = dialogues["buy_suggest_weapon"]["text_ru"].split("\n")
        self.assertTrue(
            sugg_lines[1].startswith("<00BF>"),
            f"buy_suggest_weapon Line 2 must start with <00BF>: {sugg_lines}",
        )

        # Check buy_material_weapon
        mat_lines = dialogues["buy_material_weapon"]["text_ru"].split("\n")
        self.assertTrue(
            mat_lines[0].startswith("<00BF>"),
            f"buy_material_weapon Line 1 must start with <00BF>: {mat_lines}",
        )
        self.assertTrue(
            mat_lines[1].startswith("<00BF>"),
            f"buy_material_weapon Line 2 must start with <00BF>: {mat_lines}",
        )

        # Check all <00BF> lines in all dialogues
        for d_id, d in dialogues.items():
            text = d["text_ru"]
            for page in text.split("\f"):
                for line in page.split("\n"):
                    if "<00BF>" in line:
                        self.assertTrue(
                            line.startswith("<00BF>"),
                            f"In {d_id}, line '{line}' contains <00BF> but does not start with it!",
                        )



if __name__ == "__main__":
    unittest.main()
