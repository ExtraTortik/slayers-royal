#!/usr/bin/env python3
"""Comprehensive Combat Dialogue Budget & Repacking Analyzer for PROG.UNT 0x007.

Features:
1. Calculates encoded binary byte sizes vs allocated budgets for all 114 blocks
   in translations/combat_dialogues_ru.json.
2. Computes budget statistics: total allocated bytes, total used bytes, total free bytes,
   min/max/average slack, and pagination metrics.
3. Maps battle condition trigger offsets (0x05F5F0..0x05F808), Table 2 pointers
   (0x05F470..0x05F504), and Table 3 pointers (0x06286C..0x062A0C) to dialogue blocks.
4. Implements dynamic repacking feasibility simulation demonstrating contiguous headroom
   and pointer adjustments.
5. Provides CLI interface with `--check` returning 0 when all blocks fit budgets.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import struct
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from tools.combat_dialogue_charmap import (
    COMBAT_CHARMAP,
    OPCODE_PAGE_BREAK,
    build_combat_dialogue_charmap,
)
from tools.patch_combat import TABLE2_CANONICAL_BYTES, TABLE3_CUE_OFFSETS
from tools.patch_combat_dialogues import (
    DIALOGUE_STREAM_START,
    OFFSET_TABLE2_START,
    OFFSET_TABLE3_START,
    encode_conversation_block,
    extract_entry_data_and_info,
)

RAM_BASE = 0x8004E110  # PROG.UNT Entry 0x007 RAM base address

DEFAULT_CATALOG_PATH = REPO_ROOT / "translations" / "combat_dialogues_ru.json"
DEFAULT_DISC_PATH = REPO_ROOT / "downloads" / "sr.bin"

# Address Constants in PROG.UNT Entry 0x007
OFFSET_TRIGGER_TABLE_START = 0x05F5F0
OFFSET_TRIGGER_TABLE_END = 0x05F808  # 536 bytes
OFFSET_TABLE2_END = 0x05F504  # 37 pointers (148 bytes)
OFFSET_TABLE3_END = 0x062A0C  # 105 pointers (420 bytes)
DIALOGUE_STREAM_END = OFFSET_TABLE3_START  # 0x06286C

# Canonical 536 bytes of trigger conditions (0x05F5F0..0x05F808)
CANONICAL_TRIGGERS_536 = bytes.fromhex(
    "ff1309ff920103045e0a0105ffffff150a0204ffffff160a0301ffffff170a04"
    "01ffffff180b01010710ff190b020510ffff1a0b0301ffffff1b0b0810ffffff"
    "1c0bff90010406600bff900306ff610c0009ffffff1d0c010102ffff650c0201"
    "02ffff1e0c030102ffff1f0c050709ffff200c060902ffff660c070207ffff67"
    "0d010107ffff210d090107ffff220d100107ffff6a0e00ffffffff230e020508"
    "ffff240e030408ffff270e040708ffff280e050208ffff260e060108ffff250f"
    "00010304072a10000107ffff2b11000107ffff2c12000107ffff2d13000107ff"
    "ff2e14000107ffff2f15000107ffff3016030107ffff3117020102ffff321802"
    "0102ffff3319020102ffff341a030113ffff351a050312ffff361a060713ffff"
    "371aff9213ffff591aff92ffffff5a1aff93ffffff5b1c0003ffffff381d020407"
    "ffff3925000103ffff3a25010107ffff3b260003ffffff6e26040103ffff3c27"
    "010107ffff3e28010103ffff3f2900ffffffff4029050104ffff632a000105ff"
    "ff412a010105ffff722b010407ffff422b040407ffff622b060407ffff432b0b"
    "0407ffff442c00ffffffff452d000103ffff472d010107ffff482d0305ffffff"
    "462d0404ffffff492e0003ffffff4a2e0101ffffff4b2e0205ffffff4c38000103"
    "ffff4e380204ffffff4f38060103ffff50390004ffffff51390101ffffff523a"
    "0003ffffff533a0101ffffff543b010103ffff683d01"
)


@dataclass
class BlockBudgetReport:
    """Budget metrics for a single conversation block."""

    id: str
    block_index: int
    offset: int
    offset_hex: str
    ram_address: int
    ram_address_hex: str
    allocated_budget: int
    encoded_size: int
    slack: int
    fits: bool
    bubble_count: int
    page_count: int
    has_pagination: bool


@dataclass
class BudgetSummary:
    """Overall statistics and collection of block budget reports."""

    total_blocks: int
    total_allocated_bytes: int
    total_used_bytes: int
    total_free_bytes: int
    min_slack: int
    min_slack_block_id: str
    max_slack: int
    max_slack_block_id: str
    avg_slack: float
    overflow_count: int
    paginated_blocks_count: int
    blocks: list[BlockBudgetReport] = field(default_factory=list)

    @property
    def all_fit(self) -> bool:
        return self.overflow_count == 0


@dataclass
class TriggerMapping:
    """Mapping of a 7-byte condition trigger to its targeted dialogue block."""

    trigger_offset: int
    trigger_offset_hex: str
    block_index: int
    block_id: str
    battle_id: int
    raw_bytes_hex: str
    target_block_offset: int
    target_block_offset_hex: str


@dataclass
class Table2PointerMapping:
    """Mapping of Table 2 pointers (0x05F470..0x05F504) to targets."""

    pointer_index: int
    pointer_offset: int
    pointer_offset_hex: str
    ram_address: int
    ram_address_hex: str
    target_offset: int
    target_offset_hex: str
    target_type: str  # 'trigger', 'dialogue', 'pre_dialogue'
    target_block_id: str | None = None
    speaker_opcode_hex: str | None = None


@dataclass
class Table3CueMapping:
    """Mapping of Table 3 cue pointers (0x06286C..0x062A0C) to dialogue targets."""

    cue_index: int
    pointer_offset: int
    pointer_offset_hex: str
    ram_address: int
    ram_address_hex: str
    target_offset: int
    target_offset_hex: str
    target_block_id: str
    offset_within_block: int
    bubble_index: int | None = None
    speaker: str | None = None
    speaker_opcode_hex: str | None = None


@dataclass
class RepackedBlock:
    """Result of repacking a single dialogue block."""

    id: str
    block_index: int
    old_offset: int
    new_offset: int
    encoded_size: int
    delta: int  # new_offset - old_offset


@dataclass
class RepackSimulationResult:
    """Simulation analysis of dynamic dialogue block repacking."""

    total_original_budget: int
    total_repacked_bytes: int
    contiguous_headroom_bytes: int
    dialogue_start: int
    dialogue_end_repacked: int
    dialogue_end_original: int
    blocks: list[RepackedBlock] = field(default_factory=list)
    repacked_table2_pointers: list[dict[str, Any]] = field(default_factory=list)
    repacked_table3_cues: list[dict[str, Any]] = field(default_factory=list)


def parse_catalog_file(catalog_path: Path | str) -> dict[str, Any]:
    """Load and parse combat dialogues catalog JSON."""
    path = Path(catalog_path)
    if not path.is_file():
        raise FileNotFoundError(f"Catalog file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_entry_007_bytes(
    disc_path: Path | str | None = None,
    entry_file_path: Path | str | None = None,
) -> bytes | None:
    """Load Entry 0x007 bytes from disc image or raw binary file."""
    if entry_file_path:
        p = Path(entry_file_path)
        if p.is_file():
            return p.read_bytes()

    if disc_path:
        p = Path(disc_path)
        if p.is_file():
            try:
                _, _, _, e7 = extract_entry_data_and_info(p, 7)
                return e7
            except Exception:
                pass
    return None


def analyze_budgets(
    catalog: dict[str, Any],
    charmap: Mapping[str, int] | None = None,
) -> BudgetSummary:
    """Calculate encoded size vs allocated budget for all dialogue blocks."""
    cm = charmap if charmap is not None else build_combat_dialogue_charmap()
    blocks_data = catalog.get("blocks", [])

    reports: list[BlockBudgetReport] = []
    total_allocated = 0
    total_used = 0
    paginated_count = 0

    for block in blocks_data:
        block_id = block.get("id", "")
        block_idx = block.get("block_index", 0)
        off_str = block.get("offset", "0x000000")
        offset = int(off_str, 16) if isinstance(off_str, str) else int(off_str)
        ram_str = block.get("ram_address", "0x00000000")
        ram_addr = int(ram_str, 16) if isinstance(ram_str, str) else int(ram_str)
        budget = int(block.get("allocated_budget_bytes", 0))

        encoded = encode_conversation_block(block, cm)
        encoded_size = len(encoded)
        slack = budget - encoded_size
        fits = encoded_size <= budget

        bubbles = block.get("bubbles", [])
        bubble_count = len(bubbles)
        page_count = 0
        has_pagination = False

        for bub in bubbles:
            pages = bub.get("pages")
            text_ru = bub.get("text_ru", "")
            if pages and len(pages) > 1:
                has_pagination = True
                page_count += len(pages)
            elif "\f" in text_ru:
                has_pagination = True
                page_count += len(text_ru.split("\f"))
            else:
                page_count += 1

        if has_pagination:
            paginated_count += 1

        total_allocated += budget
        total_used += encoded_size

        reports.append(
            BlockBudgetReport(
                id=block_id,
                block_index=block_idx,
                offset=offset,
                offset_hex=f"0x{offset:06X}",
                ram_address=ram_addr,
                ram_address_hex=f"0x{ram_addr:08X}",
                allocated_budget=budget,
                encoded_size=encoded_size,
                slack=slack,
                fits=fits,
                bubble_count=bubble_count,
                page_count=page_count,
                has_pagination=has_pagination,
            )
        )

    slacks = [r.slack for r in reports]
    min_s = min(slacks) if slacks else 0
    max_s = max(slacks) if slacks else 0
    avg_s = (sum(slacks) / len(slacks)) if slacks else 0.0
    min_block_id = reports[slacks.index(min_s)].id if slacks else ""
    max_block_id = reports[slacks.index(max_s)].id if slacks else ""
    overflow_count = sum(1 for r in reports if not r.fits)

    return BudgetSummary(
        total_blocks=len(reports),
        total_allocated_bytes=total_allocated,
        total_used_bytes=total_used,
        total_free_bytes=total_allocated - total_used,
        min_slack=min_s,
        min_slack_block_id=min_block_id,
        max_slack=max_s,
        max_slack_block_id=max_block_id,
        avg_slack=avg_s,
        overflow_count=overflow_count,
        paginated_blocks_count=paginated_count,
        blocks=reports,
    )


def map_table2_pointers(
    catalog: dict[str, Any],
    e7_bytes: bytes | None = None,
) -> list[Table2PointerMapping]:
    """Map the 37 pointers in Table 2 (0x05F470..0x05F504) to targets."""
    table2_bytes = (
        e7_bytes[OFFSET_TABLE2_START:OFFSET_TABLE2_END]
        if e7_bytes and len(e7_bytes) >= OFFSET_TABLE2_END
        else TABLE2_CANONICAL_BYTES
    )

    blocks = catalog.get("blocks", [])
    mappings: list[Table2PointerMapping] = []

    for idx in range(37):
        pos = idx * 4
        ram_ptr = struct.unpack_from("<I", table2_bytes, pos)[0]
        file_offset = ram_ptr - RAM_BASE
        ptr_offset = OFFSET_TABLE2_START + pos

        # Determine target type
        if file_offset < DIALOGUE_STREAM_START:
            target_type = "trigger" if file_offset >= OFFSET_TRIGGER_TABLE_START else "pre_dialogue"
            target_block = None
            speaker_op = None
        else:
            target_type = "dialogue"
            # Find matching block
            matching = [
                b for b in blocks
                if int(b["offset"], 16) <= file_offset < int(b["offset"], 16) + b["allocated_budget_bytes"]
            ]
            target_block = matching[0]["id"] if matching else None
            speaker_op = None
            if e7_bytes and file_offset < len(e7_bytes) - 1:
                spk = struct.unpack_from("<H", e7_bytes, file_offset)[0]
                speaker_op = f"0x{spk:04X}"

        mappings.append(
            Table2PointerMapping(
                pointer_index=idx,
                pointer_offset=ptr_offset,
                pointer_offset_hex=f"0x{ptr_offset:06X}",
                ram_address=ram_ptr,
                ram_address_hex=f"0x{ram_ptr:08X}",
                target_offset=file_offset,
                target_offset_hex=f"0x{file_offset:06X}",
                target_type=target_type,
                target_block_id=target_block,
                speaker_opcode_hex=speaker_op,
            )
        )

    return mappings


def map_table3_cues(
    catalog: dict[str, Any],
    e7_bytes: bytes | None = None,
) -> list[Table3CueMapping]:
    """Map the 105 pointers in Table 3 (0x06286C..0x062A0C) to dialogue cues."""
    blocks = catalog.get("blocks", [])
    mappings: list[Table3CueMapping] = []

    for idx, cue_off in enumerate(TABLE3_CUE_OFFSETS):
        ptr_offset = OFFSET_TABLE3_START + idx * 4
        ram_ptr = RAM_BASE + cue_off

        # Locate containing block
        containing = [
            b for b in blocks
            if int(b["offset"], 16) <= cue_off < int(b["offset"], 16) + b["allocated_budget_bytes"]
        ]
        target_block = containing[0]["id"] if containing else "unknown"
        delta = cue_off - int(containing[0]["offset"], 16) if containing else 0

        speaker = None
        speaker_op = None
        bubble_idx = None

        if containing:
            b = containing[0]
            # Try to identify which bubble this cue matches
            if delta == 0:
                bubble_idx = 1
                if b.get("bubbles"):
                    speaker = b["bubbles"][0].get("speaker")
                    speaker_op = b["bubbles"][0].get("speaker_opcode")
            elif e7_bytes and cue_off < len(e7_bytes) - 1:
                spk = struct.unpack_from("<H", e7_bytes, cue_off)[0]
                speaker_op = f"0x{spk:04X}"
                for bub in b.get("bubbles", []):
                    if bub.get("speaker_opcode") == speaker_op:
                        speaker = bub.get("speaker")
                        bubble_idx = bub.get("bubble_index")
                        break

        mappings.append(
            Table3CueMapping(
                cue_index=idx,
                pointer_offset=ptr_offset,
                pointer_offset_hex=f"0x{ptr_offset:06X}",
                ram_address=ram_ptr,
                ram_address_hex=f"0x{ram_ptr:08X}",
                target_offset=cue_off,
                target_offset_hex=f"0x{cue_off:06X}",
                target_block_id=target_block,
                offset_within_block=delta,
                bubble_index=bubble_idx,
                speaker=speaker,
                speaker_opcode_hex=speaker_op,
            )
        )

    return mappings


def map_battle_condition_triggers(
    catalog: dict[str, Any],
    e7_bytes: bytes | None = None,
) -> list[TriggerMapping]:
    """Map battle condition trigger records in 0x05F5F0..0x05F808 to dialogue blocks."""
    trig_data = (
        e7_bytes[OFFSET_TRIGGER_TABLE_START:OFFSET_TRIGGER_TABLE_END]
        if e7_bytes and len(e7_bytes) >= OFFSET_TRIGGER_TABLE_END
        else CANONICAL_TRIGGERS_536
    )

    blocks = catalog.get("blocks", [])
    block_map = {b["block_index"]: b for b in blocks}

    mappings: list[TriggerMapping] = []
    stride = 7
    for i in range(0, len(trig_data) - stride + 1, stride):
        rec = trig_data[i : i + stride]
        if len(rec) != stride:
            break
        cue_idx = rec[1]
        battle_id = rec[2]
        trig_offset = OFFSET_TRIGGER_TABLE_START + i

        b_match = block_map.get(cue_idx)
        block_id = b_match["id"] if b_match else f"block_{cue_idx:03d}"
        target_off = int(b_match["offset"], 16) if b_match else 0

        mappings.append(
            TriggerMapping(
                trigger_offset=trig_offset,
                trigger_offset_hex=f"0x{trig_offset:06X}",
                block_index=cue_idx,
                block_id=block_id,
                battle_id=battle_id,
                raw_bytes_hex=rec.hex(),
                target_block_offset=target_off,
                target_block_offset_hex=f"0x{target_off:06X}",
            )
        )

    return mappings


def simulate_repacking(
    catalog: dict[str, Any],
    charmap: Mapping[str, int] | None = None,
    align: int = 2,
) -> RepackSimulationResult:
    """Simulate dynamic sequential repacking of all conversation blocks.

    Demonstrates:
    - How blocks are packed tightly starting at 0x05F810.
    - Contiguous headroom freed up before Table 3 (0x06286C).
    - New offsets for all Table 3 and Table 2 pointers.
    """
    cm = charmap if charmap is not None else build_combat_dialogue_charmap()
    blocks = catalog.get("blocks", [])

    repacked_blocks: list[RepackedBlock] = []
    current_offset = DIALOGUE_STREAM_START
    total_original_budget = 0
    total_repacked_bytes = 0

    old_to_new_block_offset: dict[int, int] = {}

    for b in blocks:
        old_off = int(b["offset"], 16)
        budget = int(b["allocated_budget_bytes"])
        encoded = encode_conversation_block(b, cm)
        enc_size = len(encoded)

        # Align if necessary
        if align > 1 and current_offset % align != 0:
            current_offset += align - (current_offset % align)

        new_off = current_offset
        delta = new_off - old_off

        repacked_blocks.append(
            RepackedBlock(
                id=b["id"],
                block_index=b["block_index"],
                old_offset=old_off,
                new_offset=new_off,
                encoded_size=enc_size,
                delta=delta,
            )
        )

        old_to_new_block_offset[old_off] = new_off
        current_offset += enc_size
        total_original_budget += budget
        total_repacked_bytes += enc_size

    headroom = DIALOGUE_STREAM_END - current_offset

    # Simulate remapped Table 3 cue pointers
    repacked_table3: list[dict[str, Any]] = []
    for idx, old_cue in enumerate(TABLE3_CUE_OFFSETS):
        containing = [
            b for b in repacked_blocks
            if b.old_offset <= old_cue < b.old_offset + int(catalog["blocks"][b.block_index - 1]["allocated_budget_bytes"])
        ]
        if containing:
            b_match = containing[0]
            offset_inside = old_cue - b_match.old_offset
            new_cue = b_match.new_offset + offset_inside
        else:
            new_cue = old_cue

        repacked_table3.append(
            {
                "cue_index": idx,
                "pointer_offset": f"0x{OFFSET_TABLE3_START + idx * 4:06X}",
                "old_target": f"0x{old_cue:06X}",
                "new_target": f"0x{new_cue:06X}",
                "new_ram_address": f"0x{RAM_BASE + new_cue:08X}",
            }
        )

    # Simulate remapped Table 2 pointers
    repacked_table2: list[dict[str, Any]] = []
    for idx in range(37):
        ptr_off = OFFSET_TABLE2_START + idx * 4
        ram_p = struct.unpack_from("<I", TABLE2_CANONICAL_BYTES, idx * 4)[0]
        old_target = ram_p - RAM_BASE

        if old_target >= DIALOGUE_STREAM_START:
            containing = [
                b for b in repacked_blocks
                if b.old_offset <= old_target < b.old_offset + int(catalog["blocks"][b.block_index - 1]["allocated_budget_bytes"])
            ]
            if containing:
                b_match = containing[0]
                offset_inside = old_target - b_match.old_offset
                new_target = b_match.new_offset + offset_inside
            else:
                new_target = old_target
        else:
            new_target = old_target

        repacked_table2.append(
            {
                "pointer_index": idx,
                "pointer_offset": f"0x{ptr_off:06X}",
                "old_target": f"0x{old_target:06X}",
                "new_target": f"0x{new_target:06X}",
                "new_ram_address": f"0x{RAM_BASE + new_target:08X}",
            }
        )

    return RepackSimulationResult(
        total_original_budget=total_original_budget,
        total_repacked_bytes=total_repacked_bytes,
        contiguous_headroom_bytes=headroom,
        dialogue_start=DIALOGUE_STREAM_START,
        dialogue_end_repacked=current_offset,
        dialogue_end_original=DIALOGUE_STREAM_END,
        blocks=repacked_blocks,
        repacked_table2_pointers=repacked_table2,
        repacked_table3_cues=repacked_table3,
    )


def format_budget_table(summary: BudgetSummary, max_rows: int | None = None) -> str:
    """Format budget reports into an aligned text table."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("               COMBAT DIALOGUE BUDGET ANALYSIS (114 BLOCKS)               ")
    lines.append("=" * 78)
    lines.append(
        f"{'Block ID':<10} {'Offset':<10} {'RAM Addr':<12} {'Budget':<8} {'Used':<6} {'Slack':<7} {'Pages':<6} {'Status':<6}"
    )
    lines.append("-" * 78)

    rows = summary.blocks if max_rows is None else summary.blocks[:max_rows]
    for b in rows:
        status = "OK" if b.fits else "OVER!"
        pag_flag = f"{b.page_count}p" if b.has_pagination else "1p"
        lines.append(
            f"{b.id:<10} {b.offset_hex:<10} {b.ram_address_hex:<12} {b.allocated_budget:<8} "
            f"{b.encoded_size:<6} {b.slack:<7} {pag_flag:<6} {status:<6}"
        )

    if max_rows is not None and len(summary.blocks) > max_rows:
        lines.append(f"... [{len(summary.blocks) - max_rows} additional blocks elided] ...")

    lines.append("-" * 78)
    lines.append(f"Total Blocks:      {summary.total_blocks:>6d}")
    lines.append(f"Total Allocated:   {summary.total_allocated_bytes:>6d} bytes")
    lines.append(f"Total Used:        {summary.total_used_bytes:>6d} bytes")
    lines.append(f"Total Slack (Free):{summary.total_free_bytes:>6d} bytes")
    lines.append(f"Average Slack:     {summary.avg_slack:>9.2f} bytes / block")
    lines.append(f"Min Slack:         {summary.min_slack:>6d} bytes ({summary.min_slack_block_id})")
    lines.append(f"Max Slack:         {summary.max_slack:>6d} bytes ({summary.max_slack_block_id})")
    lines.append(f"Paginated Blocks:  {summary.paginated_blocks_count:>6d} blocks (0x00FD)")
    lines.append(f"Overflow Count:    {summary.overflow_count:>6d} blocks")
    lines.append("=" * 78)
    return "\n".join(lines)


def format_repack_report(sim: RepackSimulationResult) -> str:
    """Format repacking simulation results into a readable text report."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("             DYNAMIC REPACKING FEASIBILITY SIMULATION REPORT              ")
    lines.append("=" * 78)
    lines.append(f"Dialogue Stream Start:        0x{sim.dialogue_start:06X} (RAM 0x{RAM_BASE + sim.dialogue_start:08X})")
    lines.append(f"Original End (Table 3):       0x{sim.dialogue_end_original:06X} (RAM 0x{RAM_BASE + sim.dialogue_end_original:08X})")
    lines.append(f"Repacked End:                 0x{sim.dialogue_end_repacked:06X} (RAM 0x{RAM_BASE + sim.dialogue_end_repacked:08X})")
    lines.append(f"Original Total Budget:        {sim.total_original_budget:,} bytes")
    lines.append(f"Repacked Stream Bytes:        {sim.total_repacked_bytes:,} bytes")
    lines.append(f"Contiguous Free Headroom:     {sim.contiguous_headroom_bytes:,} bytes")
    lines.append("-" * 78)
    lines.append("Table 2 Pointers Dynamically Remapped:  37 pointers")
    lines.append("Table 3 Cues Dynamically Remapped:     105 cue pointers")
    lines.append("Battle Trigger Conditions Retained:     77 records (0x05F5F0..0x05F808)")
    lines.append("=" * 78)
    return "\n".join(lines)


def format_trigger_mapping_report(
    triggers: list[TriggerMapping],
    t2_ptrs: list[Table2PointerMapping],
    t3_cues: list[Table3CueMapping],
) -> str:
    """Format pointer and trigger mapping summary."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("            POINTER & TRIGGER TABLE OFFSET MAPPING ANALYSIS               ")
    lines.append("=" * 78)
    lines.append(f"1. Battle Condition Triggers (0x05F5F0..0x05F808): {len(triggers)} records")
    for t in triggers[:5]:
        lines.append(
            f"   Offset {t.trigger_offset_hex}: Block #{t.block_index:03d} ({t.block_id}) -> Target {t.target_block_offset_hex} (Battle {t.battle_id})"
        )
    lines.append(f"   ... [{len(triggers) - 5} records omitted]")
    lines.append("")
    lines.append(f"2. Table 2 Pointers (0x05F470..0x05F504): {len(t2_ptrs)} pointers")
    for p in t2_ptrs[:5]:
        lines.append(
            f"   T2[{p.pointer_index:02d}] @ {p.pointer_offset_hex} -> RAM {p.ram_address_hex} ({p.target_offset_hex}) [{p.target_type}]"
        )
    lines.append(f"   ... [{len(t2_ptrs) - 5} pointers omitted]")
    lines.append("")
    lines.append(f"3. Table 3 Cue Pointers (0x06286C..0x062A0C): {len(t3_cues)} cue pointers")
    for c in t3_cues[:5]:
        lines.append(
            f"   T3[{c.cue_index:03d}] @ {c.pointer_offset_hex} -> Target {c.target_offset_hex} ({c.target_block_id} +{c.offset_within_block}B)"
        )
    lines.append(f"   ... [{len(t3_cues) - 5} cue pointers omitted]")
    lines.append("=" * 78)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Comprehensive Combat Dialogue Budget & Repacking Analyzer for PROG.UNT 0x007."
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG_PATH,
        help=f"Path to combat_dialogues_ru.json (default: {DEFAULT_CATALOG_PATH})",
    )
    parser.add_argument(
        "--disc",
        type=Path,
        default=DEFAULT_DISC_PATH,
        help=f"Path to clean or patched PS1 CD image sr.bin (default: {DEFAULT_DISC_PATH})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check budgets only: output clean summary table and return 0 if all 114 blocks fit.",
    )
    parser.add_argument(
        "--repack-sim",
        action="store_true",
        help="Run and display dynamic dialogue repacking simulation.",
    )
    parser.add_argument(
        "--triggers",
        action="store_true",
        help="Display trigger condition and pointer mapping analysis.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Display full 114-row table without eliding rows.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full analysis result as structured JSON.",
    )

    args = parser.parse_args(argv)

    try:
        catalog = parse_catalog_file(args.catalog)
    except Exception as e:
        print(f"Error loading catalog: {e}", file=sys.stderr)
        return 2

    # Load charmap
    charmap = build_combat_dialogue_charmap()

    # Load Entry 7 binary data if available
    e7_bytes = load_entry_007_bytes(disc_path=args.disc)

    # 1. Budget analysis
    summary = analyze_budgets(catalog, charmap=charmap)

    # 2. Trigger and pointer mapping
    t2_ptrs = map_table2_pointers(catalog, e7_bytes)
    t3_cues = map_table3_cues(catalog, e7_bytes)
    triggers = map_battle_condition_triggers(catalog, e7_bytes)

    # 3. Repacking simulation
    repack_sim = simulate_repacking(catalog, charmap=charmap)

    if args.json:
        payload = {
            "summary": asdict(summary),
            "repack_simulation": asdict(repack_sim),
            "table2_pointers": [asdict(p) for p in t2_ptrs],
            "table3_cues": [asdict(c) for c in t3_cues],
            "triggers": [asdict(t) for t in triggers],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if summary.all_fit else 1

    max_rows = None if args.verbose else 25
    table_str = format_budget_table(summary, max_rows=max_rows)
    print(table_str)

    if args.triggers or (not args.check and not args.repack_sim):
        print("\n" + format_trigger_mapping_report(triggers, t2_ptrs, t3_cues))

    if args.repack_sim or (not args.check and not args.triggers):
        print("\n" + format_repack_report(repack_sim))

    if summary.all_fit:
        print("\n[SUCCESS] All 114 conversation blocks fit strictly within allocated budgets.")
        return 0
    else:
        print(
            f"\n[FAILURE] {summary.overflow_count} conversation block(s) exceed allocated budgets!",
            file=sys.stderr,
        )
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.stderr.close()
        sys.exit(0)
