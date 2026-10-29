from __future__ import annotations

import os
import unittest
from dataclasses import replace
from pathlib import Path

from localization.disc import SOURCE_PROG_SHA256, read_prog
from localization.glyphs import BASE_CHAR_TO_GLYPH
from localization.script import (
    RUNTIME_BASE,
    catalog_entries,
    parse_all,
    parse_scene,
    read_entries,
    rebuild_dialogue,
    source_inventory,
    validate_catalog,
)


SOURCE_BIN = os.environ.get("SLAYERS_ROYAL_BIN")


@unittest.skipUnless(SOURCE_BIN, "set SLAYERS_ROYAL_BIN for source-disc integration tests")
class SourceDiscIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prog = read_prog(Path(str(SOURCE_BIN)), SOURCE_PROG_SHA256)

    def test_complete_source_inventory(self) -> None:
        inventory = source_inventory(self.prog)
        self.assertEqual(inventory["scene_count"], 29)
        self.assertEqual(inventory["special_bank_count"], 1)
        self.assertEqual(inventory["record_count"], 2784)
        self.assertEqual(inventory["segment_count"], 4552)
        self.assertEqual(inventory["translatable_segment_count"], 4514)

    def test_every_pointer_rebuilds_with_short_cyrillic_text(self) -> None:
        catalog = [
            replace(entry, translation="Тест") for entry in catalog_entries(self.prog)
        ]
        translations = validate_catalog(self.prog, catalog)
        charmap = {
            **BASE_CHAR_TO_GLYPH,
            "Т": 0x001,
            "е": 0x002,
            "с": 0x003,
            "т": 0x004,
        }
        rebuilt = rebuild_dialogue(
            self.prog,
            translations,
            charmap,
            {"Те": 0x005, "ес": 0x006, "ст": 0x007},
        )
        self.assertEqual(len(rebuilt), len(self.prog))
        self.assertEqual(len(parse_all(rebuilt)), 30)
    def test_entry_03e_pointers_and_record_c5(self) -> None:
        entries = read_entries(self.prog)
        scene_03e = parse_scene(entries[0x03E], self.prog)
        self.assertEqual(scene_03e.family, "tagged")
        self.assertLess(0x00C5, len(scene_03e.pointers))
        ptr_c5 = scene_03e.pointers[0x00C5]
        self.assertEqual(ptr_c5 % 2, 0, "Pointer 0x00C5 must be 2-byte aligned")
        saturn_ptr = RUNTIME_BASE + ptr_c5
        self.assertTrue(0x00230000 <= saturn_ptr < 0x00240000, "Must be Saturn pointer 0x0023XXXX")
        for idx, ptr in enumerate(scene_03e.pointers):
            self.assertEqual(ptr % 2, 0, f"Pointer {idx} must be 2-byte aligned")
            s_ptr = RUNTIME_BASE + ptr
            self.assertTrue(0x00230000 <= s_ptr < 0x00240000, f"Pointer {idx} must be 0x0023XXXX")



if __name__ == "__main__":
    unittest.main()
