#!/usr/bin/env python3
"""Test suite verifying tools/analyze_combat_budgets.py and budget metrics."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from tools.analyze_combat_budgets import (
    DEFAULT_CATALOG_PATH,
    analyze_budgets,
    format_budget_table,
    format_repack_report,
    format_trigger_mapping_report,
    main,
    map_battle_condition_triggers,
    map_table2_pointers,
    map_table3_cues,
    parse_catalog_file,
    simulate_repacking,
)
from tools.combat_dialogue_charmap import build_combat_dialogue_charmap


class TestAnalyzeCombatBudgets(unittest.TestCase):
    """Test suite for combat dialogue budget analyzer."""

    @classmethod
    def setUpClass(cls):
        cls.charmap = build_combat_dialogue_charmap()
        cls.catalog = parse_catalog_file(DEFAULT_CATALOG_PATH)

    def test_analyze_budgets_all_114_blocks(self):
        """Verify that analyze_budgets processes all 114 blocks and all fit."""
        summary = analyze_budgets(self.catalog, self.charmap)
        self.assertEqual(summary.total_blocks, 114)
        self.assertTrue(summary.all_fit, f"Found {summary.overflow_count} overflowing blocks")
        self.assertEqual(summary.overflow_count, 0)
        self.assertGreater(summary.total_allocated_bytes, summary.total_used_bytes)
        self.assertGreater(summary.total_free_bytes, 0)
        self.assertGreaterEqual(summary.min_slack, 0)
        self.assertGreater(summary.max_slack, summary.min_slack)
        self.assertGreater(summary.avg_slack, 0.0)
        self.assertGreaterEqual(summary.paginated_blocks_count, 2)

    def test_paginated_blocks_001_and_106(self):
        """Verify that Block 001 and Block 106 are flagged as paginated and fit budgets."""
        summary = analyze_budgets(self.catalog, self.charmap)
        block_map = {b.id: b for b in summary.blocks}

        # Block 001: Lina's bubble with 2 pages
        b001 = block_map.get("block_001")
        self.assertIsNotNone(b001)
        self.assertTrue(b001.has_pagination)
        self.assertTrue(b001.fits)
        self.assertLessEqual(b001.encoded_size, 176)
        self.assertGreaterEqual(b001.page_count, 2)

        # Block 106: Mossman's bubble with 2 pages
        b106 = block_map.get("block_106")
        self.assertIsNotNone(b106)
        self.assertTrue(b106.has_pagination)
        self.assertTrue(b106.fits)
        self.assertLessEqual(b106.encoded_size, 196)
        self.assertGreaterEqual(b106.page_count, 2)

    def test_overflow_detection_on_oversized_block(self):
        """Verify that analyze_budgets correctly catches and reports budget overflow."""
        mock_catalog = copy.deepcopy(self.catalog)
        # Artificially bloat block 002 with excessive text
        mock_catalog["blocks"][1]["bubbles"][0]["text_ru"] = (
            "Это очень длинный текст, который гарантированно превысит "
            "выделенный бюджет в 96 байт для блока 002."
        )

        summary = analyze_budgets(mock_catalog, self.charmap)
        self.assertFalse(summary.all_fit)
        self.assertGreaterEqual(summary.overflow_count, 1)
        b002_report = next(b for b in summary.blocks if b.id == "block_002")
        self.assertFalse(b002_report.fits)
        self.assertLess(b002_report.slack, 0)

    def test_table2_pointer_mapping(self):
        """Verify Table 2 mapping produces exactly 37 valid pointer entries."""
        t2 = map_table2_pointers(self.catalog)
        self.assertEqual(len(t2), 37)

        trigger_count = sum(1 for p in t2 if p.target_type == "trigger")
        dialogue_count = sum(1 for p in t2 if p.target_type == "dialogue")
        self.assertGreater(trigger_count, 0)
        self.assertGreater(dialogue_count, 0)

        # Check offsets are monotonic in Table 2
        for idx in range(len(t2) - 1):
            self.assertEqual(t2[idx + 1].pointer_offset, t2[idx].pointer_offset + 4)

    def test_table3_cue_mapping(self):
        """Verify Table 3 mapping produces exactly 105 valid cue pointers."""
        t3 = map_table3_cues(self.catalog)
        self.assertEqual(len(t3), 105)

        for cue in t3:
            self.assertTrue(cue.target_block_id.startswith("block_"))
            self.assertGreaterEqual(cue.offset_within_block, 0)

    def test_battle_condition_trigger_mapping(self):
        """Verify battle condition triggers map to valid dialogue blocks."""
        triggers = map_battle_condition_triggers(self.catalog)
        self.assertGreaterEqual(len(triggers), 70)

        for trig in triggers:
            self.assertTrue(trig.block_id.startswith("block_"))
            self.assertGreaterEqual(trig.block_index, 1)
            self.assertLessEqual(trig.block_index, 114)
            self.assertTrue(trig.target_block_offset_hex.startswith("0x"))

    def test_simulate_repacking(self):
        """Verify dynamic repacking simulation produces contiguous headroom."""
        sim = simulate_repacking(self.catalog, self.charmap)
        self.assertEqual(len(sim.blocks), 114)
        self.assertGreater(sim.contiguous_headroom_bytes, 500)
        self.assertLess(sim.dialogue_end_repacked, sim.dialogue_end_original)
        self.assertEqual(sim.dialogue_start, 0x05F810)

        # Verify blocks are sequentially packed without overlap
        for i in range(len(sim.blocks) - 1):
            curr_b = sim.blocks[i]
            next_b = sim.blocks[i + 1]
            self.assertGreaterEqual(
                next_b.new_offset,
                curr_b.new_offset + curr_b.encoded_size,
                f"Overlap detected between {curr_b.id} and {next_b.id}",
            )

        # Verify Table 2 and Table 3 remapping in simulation
        self.assertEqual(len(sim.repacked_table2_pointers), 37)
        self.assertEqual(len(sim.repacked_table3_cues), 105)

    def test_table_formatters(self):
        """Verify output string formatters run without exceptions."""
        summary = analyze_budgets(self.catalog, self.charmap)
        table_str = format_budget_table(summary, max_rows=10)
        self.assertIn("COMBAT DIALOGUE BUDGET ANALYSIS", table_str)
        self.assertIn("block_001", table_str)
        self.assertIn("Total Blocks", table_str)

        sim = simulate_repacking(self.catalog, self.charmap)
        repack_str = format_repack_report(sim)
        self.assertIn("DYNAMIC REPACKING FEASIBILITY", repack_str)
        self.assertIn("Contiguous Free Headroom", repack_str)

        t2 = map_table2_pointers(self.catalog)
        t3 = map_table3_cues(self.catalog)
        triggers = map_battle_condition_triggers(self.catalog)
        trig_str = format_trigger_mapping_report(triggers, t2, t3)
        self.assertIn("POINTER & TRIGGER TABLE", trig_str)

    def test_cli_flags_execution(self):
        """Verify main() CLI handles --check, --repack-sim, --triggers, and --json."""
        exit_code_check = main(["--check"])
        self.assertEqual(exit_code_check, 0)

        exit_code_repack = main(["--repack-sim"])
        self.assertEqual(exit_code_repack, 0)

        exit_code_triggers = main(["--triggers"])
        self.assertEqual(exit_code_triggers, 0)

        exit_code_json = main(["--json"])
        self.assertEqual(exit_code_json, 0)


if __name__ == "__main__":
    unittest.main()
