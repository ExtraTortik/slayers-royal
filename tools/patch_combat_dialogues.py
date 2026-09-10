#!/usr/bin/env python3
"""Combat dialogue patcher for Slayers Royal (PS1).

Features:
1. Injects Russian Cyrillic glyphs into completely unreferenced tiles (0x0150..0x0191)
   in font 0x142 (PROG.UNT entry 0x142), leaving English letters, digits, punctuation,
   and UI buttons 100% intact.
2. Compresses font with unt_lz mode 1 within 23 sectors (47,104 bytes).
3. Performs clean in-place block replacement in PROG.UNT Entry 0x007
   (0x05F810..0x06286A, 114 conversation blocks) from translations/combat_dialogues_ru.json.
4. Preserves Table 1, Table 2, Table 3, system buttons (0x05F278..0x05F470), and
   MIPS instruction at 0x02B78C completely untouched.
5. Injects modified Entry 0x142 (23 sectors) and Entry 0x007 (745 sectors) into the
   target PS1 BIN image with Mode 2 Form 1 EDC/ECC recalculation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import struct
import sys
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from localization import unt_lz
from localization.disc import (
    read_extent,
    replace_extent_in_place,
    CdChecksums,
    RAW_SECTOR_SIZE,
    USER_DATA_SIZE,
    USER_DATA_OFFSET,
)
from tools.patch_inspection import (
    parse_iso_dir,
    read_sector,
    read_unt_index,
)
from tools.patch_combat_font import (
    unpack_combat_font,
    put_tile,
    get_tile,
    get_hw_tile_2bpp,
    put_hw_tile_2bpp,
    render_cyrillic_glyph_2bpp,
    TOTAL_TILES,
    COMBAT_FONT_ENTRY,
    COMBAT_FONT_SECTORS,
    COMBAT_FONT_MAX_SIZE,
    TIM_DECOMPRESSED_SIZE,
)
from tools.combat_dialogue_charmap import (
    CYRILLIC_UPPER,
    CYRILLIC_LOWER,
    CYRILLIC_UPPER_BASE,
    CYRILLIC_LOWER_BASE,
    OPCODE_NEWLINE,
    OPCODE_BUBBLE_ADVANCE,
    OPCODE_BLOCK_END,
    COMBAT_CHARMAP,
    REVERSE_COMBAT_CHARMAP,
    encode_combat_dialogue_string,
    decode_combat_dialogue_string,
    scan_protected_tiles,
    find_safe_cyrillic_tiles,
)

DEFAULT_BIN = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
DEFAULT_CATALOG = REPO_ROOT / "translations" / "combat_dialogues_ru.json"
DEFAULT_TIM_CACHE = REPO_ROOT / "data" / "prog_entry_142_en.tim"
DEFAULT_FONT = REPO_ROOT / "fonts" / "PressStart2P.ttf"

ENTRY_COMBAT_DATA = 0x007
ENTRY_COMBAT_FONT = 0x142

EXPECTED_E7_SECTORS = 745
EXPECTED_E142_SECTORS = 23

DIALOGUE_STREAM_START = 0x05F810
DIALOGUE_STREAM_END = 0x06286A

# Invariant offsets in Entry 0x007
OFFSET_MIPS_INIT_EXIT = 0x02B78C
OFFSET_TABLE1_START = 0x05F1FC
OFFSET_SYSTEM_BUTTONS_START = 0x05F278
OFFSET_SYSTEM_BUTTONS_END = 0x05F470
OFFSET_TABLE2_START = 0x05F470
OFFSET_TABLE3_START = 0x06286C


def render_cyrillic_glyph(char: str, font_path: Path) -> bytes:
    """Render a single character into a 16x16 4bpp tile using PressStart2P (size 11).

    Palette 0 colors:
    - 0x0: Transparent
    - 0x1: Dark shadow / outline
    - 0x3: Text core body (white)
    """
    canvas_core = Image.new("L", (16, 16), 0)
    canvas_shadow = Image.new("L", (16, 16), 0)
    draw_core = ImageDraw.Draw(canvas_core)
    draw_shadow = ImageDraw.Draw(canvas_shadow)

    font = ImageFont.truetype(str(font_path), 11)
    bbox = draw_core.textbbox((0, 0), char, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]

    # Center horizontally and vertically within 16x16 tile, leaving margin for shadow
    x = max(0, min(14, (15 - w) // 2))
    y = max(0, min(14, (15 - h) // 2))

    draw_core.text((x - bbox[0], y - bbox[1]), char, font=font, fill=255)
    draw_shadow.text((x - bbox[0] + 1, y - bbox[1] + 1), char, font=font, fill=255)

    pix_c = canvas_core.load()
    pix_s = canvas_shadow.load()

    tile_bytes = bytearray()
    for py in range(16):
        row_nibs = []
        for px in range(16):
            if pix_c[px, py] >= 80:
                row_nibs.append(3)   # Core text (Color 3)
            elif pix_s[px, py] >= 80:
                row_nibs.append(1)   # Shadow / outline (Color 1)
            else:
                row_nibs.append(0)   # Transparent (Color 0)
        for i in range(0, 16, 2):
            b = (row_nibs[i] & 0x0F) | ((row_nibs[i + 1] & 0x0F) << 4)
            tile_bytes.append(b)

    return bytes(tile_bytes)


def build_patched_combat_font(
    tim_decompressed: bytes,
    font_path: Path | None = None,
) -> tuple[bytes, bytes]:
    """Render Cyrillic glyphs into font 0x142 in 2BPP and compress with unt_lz mode 1.

    Renders all 66 characters in CYRILLIC_UPPER (0x0150..0x0170) and
    CYRILLIC_LOWER (0x0171..0x0191) using put_hw_tile_2bpp.

    Returns:
        (patched_tim_decompressed, compressed_bytes)

    Raises:
        ValueError if compressed font exceeds 23 sectors (47,104 bytes).
    """
    if len(tim_decompressed) != TIM_DECOMPRESSED_SIZE:
        raise ValueError(f"Invalid TIM size: {len(tim_decompressed)} bytes (expected {TIM_DECOMPRESSED_SIZE})")

    fp = font_path or DEFAULT_FONT
    if not fp.is_file():
        raise FileNotFoundError(f"Font file not found: {fp}")

    patched_tim = bytearray(tim_decompressed)

    # Render 33 uppercase Russian glyphs into 0x0150..0x0170
    for idx, ch in enumerate(CYRILLIC_UPPER):
        tile_id = CYRILLIC_UPPER_BASE + idx
        tile_bytes = render_cyrillic_glyph_2bpp(ch, fp)
        put_hw_tile_2bpp(patched_tim, tile_id, tile_bytes)

    # Render 33 lowercase Russian glyphs into 0x0171..0x0191
    for idx, ch in enumerate(CYRILLIC_LOWER):
        tile_id = CYRILLIC_LOWER_BASE + idx
        tile_bytes = render_cyrillic_glyph_2bpp(ch, fp)
        put_hw_tile_2bpp(patched_tim, tile_id, tile_bytes)

    patched_bytes = bytes(patched_tim)

    # Compress with unt_lz mode 1
    compressed = unt_lz.compress(patched_bytes)
    if len(compressed) > COMBAT_FONT_MAX_SIZE:
        raise ValueError(
            f"Compressed font size ({len(compressed)} bytes) exceeds budget of "
            f"{COMBAT_FONT_MAX_SIZE} bytes ({COMBAT_FONT_SECTORS} sectors)"
        )

    return patched_bytes, compressed


def encode_conversation_block(
    block: dict[str, Any],
    charmap: Mapping[str, int] | None = None,
) -> bytes:
    """Encode a single conversation block into binary format.

    Format:
    [Speaker Opcode 1] [Bubble 1 text]
    (if bubble 2: [0x00FD] [Speaker Opcode 2] [Bubble 2 text])
    ...
    [0x00FF] (Block terminator)
    """
    cm = charmap if charmap is not None else COMBAT_CHARMAP
    bubbles = block.get("bubbles", [])
    if not bubbles:
        raise ValueError(f"Block {block.get('id')} has no bubbles")

    data = bytearray()
    for idx, bubble in enumerate(bubbles):
        speaker_raw = bubble.get("speaker_opcode", 0)
        if isinstance(speaker_raw, str):
            speaker_op = int(speaker_raw, 16)
        else:
            speaker_op = int(speaker_raw)

        if idx > 0:
            # Advance delimiter
            data.extend(struct.pack("<H", OPCODE_BUBBLE_ADVANCE))

        # Append speaker opcode
        data.extend(struct.pack("<H", speaker_op))

        # Append Russian dialogue text
        text_ru = bubble.get("text_ru", "")
        encoded_text = encode_combat_dialogue_string(text_ru, cm)
        data.extend(encoded_text)

    # Terminate conversation block
    data.extend(struct.pack("<H", OPCODE_BLOCK_END))

    return bytes(data)


def patch_dialogue_blocks(
    entry_7_data: bytes,
    catalog: dict[str, Any],
    charmap: Mapping[str, int] | None = None,
) -> bytes:
    """Patch all dialogue blocks in-place into Entry 0x007.

    Verifies budgets and pads trailing bytes in each block with 0x0000.
    Ensures zero modification outside dialogue block allocations.
    """
    cm = charmap if charmap is not None else COMBAT_CHARMAP
    patched_e7 = bytearray(entry_7_data)
    blocks = catalog.get("blocks", [])

    for block in blocks:
        block_id = block.get("id", "unknown")
        raw_offset = block.get("offset")
        offset = int(raw_offset, 16) if isinstance(raw_offset, str) else int(raw_offset)
        budget = int(block.get("allocated_budget_bytes", 0))

        if not (DIALOGUE_STREAM_START <= offset < DIALOGUE_STREAM_END):
            raise ValueError(
                f"Block {block_id} offset 0x{offset:06X} outside dialogue range "
                f"0x{DIALOGUE_STREAM_START:06X}..0x{DIALOGUE_STREAM_END:06X}"
            )

        encoded = encode_conversation_block(block, cm)
        if len(encoded) > budget:
            raise ValueError(
                f"Block {block_id} at 0x{offset:06X} exceeds allocated budget: "
                f"{len(encoded)} bytes > {budget} bytes"
            )

        # Pad with 0x00 up to budget
        padded_block = encoded + (b"\x00" * (budget - len(encoded)))

        # Overwrite in-place
        patched_e7[offset : offset + budget] = padded_block

    return bytes(patched_e7)

def validate_dialogue_formatting(
    catalog: dict[str, Any],
    max_chars_per_line: int = 21,
    max_lines_per_bubble: int = 3,
) -> list[str]:
    """Validate dialogue box constraints:
    - Maximum 18-21 characters per line.
    - Maximum 3 lines per bubble.
    - Explicit '\\n' for newlines.
    """
    issues: list[str] = []
    blocks = catalog.get("blocks", [])
    for block in blocks:
        block_id = block.get("id", "unknown")
        for bubble in block.get("bubbles", []):
            bubble_idx = bubble.get("bubble_index", 1)
            text_ru = bubble.get("text_ru", "")
            lines = text_ru.split("\n")
            if len(lines) > max_lines_per_bubble:
                issues.append(
                    f"{block_id} bubble {bubble_idx}: {len(lines)} lines exceeds max {max_lines_per_bubble}"
                )
            for line_idx, line in enumerate(lines, 1):
                if len(line) > max_chars_per_line:
                    issues.append(
                        f"{block_id} bubble {bubble_idx} line {line_idx}: length {len(line)} exceeds max {max_chars_per_line} ('{line}')"
                    )
    return issues


def verify_entry_7_invariants(orig_e7: bytes, patched_e7: bytes) -> None:
    """Verify that all protected regions outside dialogue stream are 100% untouched."""
    # 1. Everything before dialogue stream must be byte-exact identical
    if patched_e7[:DIALOGUE_STREAM_START] != orig_e7[:DIALOGUE_STREAM_START]:
        raise AssertionError("Invariant violation: Bytes before 0x05F810 were modified!")

    # 2. Everything at/after Table 3 must be byte-exact identical
    if patched_e7[OFFSET_TABLE3_START:] != orig_e7[OFFSET_TABLE3_START:]:
        raise AssertionError("Invariant violation: Bytes at/after Table 3 (0x06286C) were modified!")

    # 3. System buttons at 0x05F278..0x05F470 must be untouched
    if patched_e7[OFFSET_SYSTEM_BUTTONS_START:OFFSET_SYSTEM_BUTTONS_END] != orig_e7[OFFSET_SYSTEM_BUTTONS_START:OFFSET_SYSTEM_BUTTONS_END]:
        raise AssertionError("Invariant violation: System buttons region was modified!")

    # 4. Table 1 at 0x05F1FC..0x05F258 must be untouched
    if patched_e7[OFFSET_TABLE1_START:OFFSET_SYSTEM_BUTTONS_START] != orig_e7[OFFSET_TABLE1_START:OFFSET_SYSTEM_BUTTONS_START]:
        raise AssertionError("Invariant violation: Table 1 was modified!")

    # 5. Table 2 at 0x05F470..0x05F504 must be untouched
    if patched_e7[OFFSET_TABLE2_START:OFFSET_TABLE2_START + 148] != orig_e7[OFFSET_TABLE2_START:OFFSET_TABLE2_START + 148]:
        raise AssertionError("Invariant violation: Table 2 was modified!")

    # 6. MIPS instruction at 0x02B78C must be untouched
    if patched_e7[OFFSET_MIPS_INIT_EXIT : OFFSET_MIPS_INIT_EXIT + 8] != orig_e7[OFFSET_MIPS_INIT_EXIT : OFFSET_MIPS_INIT_EXIT + 8]:
        raise AssertionError("Invariant violation: MIPS instruction at 0x02B78C was modified!")


def extract_entry_data_and_info(
    bin_path: Path,
    entry_index: int,
) -> tuple[int, int, int, bytes]:
    """Extract entry from target BIN image.

    Returns:
        (prog_lba, start_sector, sector_count, data_bytes)
    """
    with bin_path.open("rb") as f:
        pvd = read_sector(bin_path, 16)
        root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
        root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
        root_dir = parse_iso_dir(bin_path, root_lba, root_size)
        if "PROG.UNT" not in root_dir:
            raise ValueError("PROG.UNT not found in ISO directory")
        prog_lba, _ = root_dir["PROG.UNT"]
        idx_sector = read_sector(bin_path, prog_lba)
        entries = read_unt_index(idx_sector)
        if entry_index >= len(entries):
            raise IndexError(f"Entry index {entry_index} out of range in PROG.UNT")
        e = entries[entry_index]
        data = b"".join(
            read_sector(bin_path, prog_lba + e.start_sector + s)
            for s in range(e.sector_count)
        )
        return prog_lba, e.start_sector, e.sector_count, data


def patch_combat_dialogues(
    bin_path: Path,
    catalog_path: Path | None = None,
    output_bin: Path | None = None,
    dry_run: bool = False,
    tim_source: Path | None = None,
    font_path: Path | None = None,
) -> dict[str, Any]:
    """Execute complete combat dialogue patching pipeline.

    1. Load translations catalog.
    2. Extract Entry 0x007 and Entry 0x142 from disc image.
    3. Patch font 0x142 with Cyrillic glyphs and compress with unt_lz mode 1.
    4. Patch Entry 0x007 in-place with Russian dialogues.
    5. Verify zero-touch invariants.
    6. If dry_run is False, write modified sectors to disc image with EDC/ECC recalculation.
    """
    cat_path = catalog_path or DEFAULT_CATALOG
    if not cat_path.is_file():
        raise FileNotFoundError(f"Translations catalog not found at {cat_path}")

    catalog = json.loads(cat_path.read_text(encoding="utf-8"))
    blocks = catalog.get("blocks", [])

    if not bin_path.is_file():
        raise FileNotFoundError(f"Target disc image not found at {bin_path}")

    # Determine working BIN path
    work_bin = bin_path
    if output_bin is not None and output_bin != bin_path and not dry_run:
        output_bin.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bin_path, output_bin)
        work_bin = output_bin

    # 1. Read Entry 0x007
    prog_lba, e7_start, e7_count, orig_e7 = extract_entry_data_and_info(work_bin, ENTRY_COMBAT_DATA)
    if e7_count != EXPECTED_E7_SECTORS:
        raise ValueError(f"Entry 0x007 sector count mismatch: {e7_count} (expected {EXPECTED_E7_SECTORS})")

    # 2. Read Entry 0x142
    _, e142_start, e142_count, _ = extract_entry_data_and_info(work_bin, ENTRY_COMBAT_FONT)
    if e142_count != EXPECTED_E142_SECTORS:
        raise ValueError(f"Entry 0x142 sector count mismatch: {e142_count} (expected {EXPECTED_E142_SECTORS})")

    # 3. Build patched combat font
    orig_tim = unpack_combat_font(tim_source or work_bin)
    patched_tim, compressed_font = build_patched_combat_font(orig_tim, font_path)

    # Pad compressed font to exact sector budget
    font_budget = e142_count * USER_DATA_SIZE
    padded_font = compressed_font.ljust(font_budget, b"\x00")

    # 4. Validate formatting constraints (<= 21 chars/line, <= 3 lines/bubble)
    formatting_issues = validate_dialogue_formatting(catalog)

    # 5. Patch Entry 0x007 in-place
    patched_e7 = patch_dialogue_blocks(orig_e7, catalog)

    # 6. Verify invariants
    verify_entry_7_invariants(orig_e7, patched_e7)

    # 6. Disc sector injection
    if not dry_run:
        # Write Entry 0x142 (23 sectors)
        replace_extent_in_place(work_bin, prog_lba + e142_start, padded_font)

        # Write Entry 0x007 (745 sectors)
        replace_extent_in_place(work_bin, prog_lba + e7_start, patched_e7)

    return {
        "blocks_patched": len(blocks),
        "compressed_font_size": len(compressed_font),
        "font_budget": COMBAT_FONT_MAX_SIZE,
        "font_margin": COMBAT_FONT_MAX_SIZE - len(compressed_font),
        "entry_7_sectors": e7_count,
        "entry_142_sectors": e142_count,
        "dry_run": dry_run,
        "target_bin": str(work_bin),
        "formatting_issues": formatting_issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch combat dialogues and font in Slayers Royal (PS1).")
    parser.add_argument("--bin", type=Path, default=DEFAULT_BIN, help="Path to input disc image (sr.bin / sr_patched.bin)")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="Path to translations JSON catalog")
    parser.add_argument("--output-bin", type=Path, help="Path to output modified disc image")
    parser.add_argument("--dry-run", action="store_true", help="Validate and encode without modifying disc image")
    parser.add_argument("--verify", action="store_true", help="Run thorough validation and invariant checks")
    args = parser.parse_args()
    is_dry = args.dry_run or args.verify
    print(f"Target BIN: {args.bin}")
    print(f"Translations: {args.catalog}")
    print(f"Mode: {'DRY RUN' if is_dry else 'APPLY PATCH'}")
    try:
        result = patch_combat_dialogues(
            bin_path=args.bin,
            catalog_path=args.catalog,
            output_bin=args.output_bin,
            dry_run=args.dry_run or args.verify,
        )
        print(f"Successfully processed {result['blocks_patched']} dialogue blocks.")
        print(f"Font compressed size: {result['compressed_font_size']:,} bytes / {result['font_budget']:,} budget "
              f"(Margin: {result['font_margin']:,} bytes)")
        print(f"Entry 0x007: {result['entry_7_sectors']} sectors, Entry 0x142: {result['entry_142_sectors']} sectors.")
        print("Invariants: 100% verified (Table 1, Table 2, Table 3, System buttons, MIPS 0x02B78C intact).")
        return 0
    except Exception as e:
        print(f"Error during patching: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
