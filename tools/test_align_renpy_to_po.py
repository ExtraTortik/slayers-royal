#!/usr/bin/env python3
"""Test suite verifying story dialogue Ren'Py alignment and polished overrides."""

from __future__ import annotations
import sys
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from localization.po import read_po
from localization.script import parse_target
from tools.story_dialogue_overrides import POLISHED_OVERRIDES
from tools.align_renpy_to_po import parse_renpy_script, align_and_update


class TestStoryDialogueAlignment(unittest.TestCase):
    """Validation of dialogue.po and story_dialogue_overrides against PS1 constraints."""

    @classmethod
    def setUpClass(cls):
        cls.po_path = PATCH_REPO / "localization-work" / "ru" / "dialogue.po"
        cls.assertTrue(cls.po_path.is_file(), f"dialogue.po not found at {cls.po_path}")
        cls.catalog = read_po(cls.po_path)
        cls.catalog_by_ctx = {e.context: e for e in cls.catalog}

    def test_catalog_size_and_completeness(self):
        """Verify exactly 4,514 entries in dialogue.po and 100% translated."""
        self.assertEqual(len(self.catalog), 4514)
        for entry in self.catalog:
            self.assertTrue(bool(entry.translation), f"Empty translation for {entry.context}")

    def test_polished_overrides_exist_in_catalog(self):
        """Verify all curated override contexts exist in dialogue.po."""
        self.assertGreaterEqual(len(POLISHED_OVERRIDES), 216)
        for ctx, text in POLISHED_OVERRIDES.items():
            self.assertIn(ctx, self.catalog_by_ctx, f"Context {ctx} missing in catalog")
            entry = self.catalog_by_ctx[ctx]
            self.assertEqual(
                entry.translation, text, f"Override text differs in catalog for {ctx}"
            )

    def test_polished_overrides_formatting_constraints(self):
        """Verify each polished entry satisfies <= 15 chars/line, <= 3 lines, no dangling dots."""
        for ctx, text in POLISHED_OVERRIDES.items():
            entry = self.catalog_by_ctx[ctx]
            allow_cont = not any("cannot add another page" in c for c in entry.comments)
            delim = 0x00FD if allow_cont else 0x00FF
            # parse_target must succeed
            pages = parse_target(text, delim, ctx)
            if not allow_cont:
                self.assertEqual(len(pages), 1, f"{ctx}: 0x00FF record cannot have multiple pages")
                lines = pages[0]
                self.assertLessEqual(len(lines), 3, f"{ctx}: exceeds 3 lines")
                for line in lines:
                    self.assertLessEqual(len(line), 15, f"{ctx}: line exceeds 15 chars: {line!r}")

    def test_menu_choices_not_truncated(self):
        """Verify choice menus are multi-line options rather than chopped text."""
        # Lakewood main street choice menu
        e126 = self.catalog_by_ctx.get("dialogue/03C/E079/126")
        self.assertIsNotNone(e126)
        self.assertIn("Осмотреть город\nВыйти из города", e126.translation)

        # Explain or stop choice menu
        e316 = self.catalog_by_ctx.get("dialogue/041/U041-S316/000")
        self.assertIsNotNone(e316)
        self.assertIn("Всё объяснить\nНе рассказывать", e316.translation)


if __name__ == "__main__":
    unittest.main()
