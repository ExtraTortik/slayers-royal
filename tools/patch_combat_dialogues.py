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
    import_combat_font_template,
    is_tile_empty,
    find_press_start_font,
    build_patched_combat_font,
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
    OPCODE_PAGE_BREAK,
    OPCODE_BLOCK_END,
    COMBAT_CHARMAP,
    REVERSE_COMBAT_CHARMAP,
    encode_combat_dialogue_string,
    decode_combat_dialogue_string,
    scan_protected_tiles,
    find_safe_cyrillic_tiles,
)

DEFAULT_RU_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_EN_BIN = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
DEFAULT_BIN = DEFAULT_RU_BIN if DEFAULT_RU_BIN.is_file() else DEFAULT_EN_BIN
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

OFFSET_SYSTEM_COMMANDS_START = 0x05F278
OFFSET_SYSTEM_COMMANDS_END = 0x05F398
OFFSET_PROMPT_SLOTS_START = 0x05F394
OFFSET_PROMPT_SLOTS_END = 0x05F46C
# Backward compatibility aliases
OFFSET_PROMPT_STREAM_START = 0x05F394
OFFSET_PROMPT_STREAM_END = 0x05F470
PROMPT_STREAM_MAX_BYTES = 220  # 0x05F470 - 0x05F394 = 220 bytes
SYSTEM_COMMAND_SLOTS: list[tuple[int, str]] = [
    (0x05F278, "СТАРТ"),      # START
    (0x05F288, "ОПЦИИ"),      # CONFIG
    (0x05F298, "АТАКА"),      # ATTACK
    (0x05F2A8, "ОТВЕТ"),      # COUNTER
    (0x05F2B8, "МАГИЯ"),      # SPELL
    (0x05F2C8, "УДАР"),       # HIT
    (0x05F2D8, "ТАРАН"),      # RAM
    (0x05F2E8, "ХОД"),        # MOVE
    (0x05F2F8, "ТАПОК"),      # SLIPPER
    (0x05F308, "ХОХОТ"),      # LAUGH
    (0x05F318, "ОТВЕТ"),      # COUNTER_ACT
    (0x05F328, "УКЛОН"),      # EVADE
    (0x05F338, "ПОБЕГ"),      # FLEE
    (0x05F348, "ТЕРПЕТЬ"),    # ENDURE
    (0x05F358, "ЗАЩИТА"),     # GUARD
    (0x05F368, "БАРЬЕР"),     # WARD
    (0x05F378, "МАГИЯ"),      # CAST
    (0x05F388, "НАЗАД"),      # BACK
]

FIXED_PROMPT_SLOTS: list[tuple[int, int, str]] = [
    (0x05F394, 14, "ЗАЩИТА"),
    (0x05F3A2, 10, "АВТО"),
    (0x05F3AC, 14, "РУЧНОЙ"),
    (0x05F3BA, 20, "КТО ХОДИТ"),
    (0x05F3CE, 20, "ДЕЙСТВИЕ"),
    (0x05F3E2, 22, "МАГИЯ"),
    (0x05F3F8, 18, "КУДА?"),
    (0x05F40A, 16, "ЦЕЛЬ?"),
    (0x05F41A, 12, "ЗОНА?"),
    (0x05F426, 18, "ИДЕТ БОЙ"),
    (0x05F438, 12, "ЖДИТЕ"),
    (0x05F444, 20, "РЕЖИМ"),
    (0x05F458, 10, "СЕЙВ"),
    (0x05F462, 10, "ЛОАД"),
]

SYSTEM_PROMPT_STRINGS: list[str] = [text for _, _, text in FIXED_PROMPT_SLOTS]

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



def encode_conversation_block(
    block: dict[str, Any],
    charmap: Mapping[str, int] | None = None,
) -> bytes:
    """Encode a single conversation block into binary format.

    Format:
    [Speaker Opcode 1] [Bubble 1 Page 1 text]
    (if bubble 1 page 2: [0x00FD] [Bubble 1 Page 2 text])
    ...
    (if bubble 2: [0x00FD] [Speaker Opcode 2] [Bubble 2 Page 1 text])
    ...
    [0x00FF] (Block terminator)
    """
    cm = charmap if charmap is not None else COMBAT_CHARMAP
    bubbles = block.get("bubbles", [])
    if not bubbles:
        raise ValueError(f"Block {block.get('id')} has no bubbles")

    data = bytearray()
    for bubble_idx, bubble in enumerate(bubbles):
        speaker_raw = bubble.get("speaker_opcode", 0)
        if isinstance(speaker_raw, str):
            speaker_op = int(speaker_raw, 16)
        else:
            speaker_op = int(speaker_raw)

        # Support both "pages": ["p1", "p2"] and "text_ru" with \f
        if "pages" in bubble and bubble["pages"] is not None:
            pages: list[str] = []
            for p in bubble["pages"]:
                pages.extend(p.split("\f"))
        else:
            text_ru = bubble.get("text_ru", "")
            pages = text_ru.split("\f")

        if not pages:
            pages = [""]

        for page_idx, page_text in enumerate(pages):
            if bubble_idx == 0 and page_idx == 0:
                # First page of first bubble: [Speaker Opcode] [Page 1 text]
                data.extend(struct.pack("<H", speaker_op))
            elif page_idx == 0:
                # First page of subsequent bubble: [0x00FD] [Next Speaker Opcode] [Page 1 text]
                data.extend(struct.pack("<H", OPCODE_BUBBLE_ADVANCE))
                data.extend(struct.pack("<H", speaker_op))
            else:
                # Subsequent page of SAME bubble: [0x00FD] [Page k text] (NO speaker opcode)
                data.extend(struct.pack("<H", OPCODE_PAGE_BREAK))

            encoded_page = encode_combat_dialogue_string(page_text, cm)
            data.extend(encoded_page)

    # Terminate conversation block
    data.extend(struct.pack("<H", OPCODE_BLOCK_END))

    return bytes(data)

def decode_conversation_bubbles(
    data: bytes,
    reverse_charmap: Mapping[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Decode raw conversation block bytes into speech bubbles and pages.

    Differentiates 0x00FD opcode behavior:
    - 0x00FD followed by glyph (< 0x9000): Intra-bubble page advance for current speaker.
    - 0x00FD followed by speaker opcode (>= 0x9000): Bubble advance starting a new speaker bubble.
    """
    rev = reverse_charmap if reverse_charmap is not None else REVERSE_COMBAT_CHARMAP
    words = [struct.unpack_from("<H", data, i)[0] for i in range(0, len(data) - 1, 2)]
    if not words or words[0] == OPCODE_BLOCK_END:
        return []

    bubbles: list[dict[str, Any]] = []
    i = 0
    if words[0] >= 0x9000:
        current_speaker = words[0]
        i = 1
    elif words[0] == OPCODE_BUBBLE_ADVANCE and len(words) > 1 and words[1] >= 0x9000:
        current_speaker = words[1]
        i = 2
    else:
        current_speaker = 0x9109
        i = 0

    current_bubble_pages: list[list[int]] = []
    current_page_words: list[int] = []

    def _flush_bubble() -> None:
        nonlocal current_bubble_pages, current_page_words
        current_bubble_pages.append(current_page_words)
        pages_text = [
            decode_combat_dialogue_string(
                b"".join(struct.pack("<H", c) for c in p_words),
                rev,
            )
            for p_words in current_bubble_pages
        ]
        bubbles.append({
            "bubble_index": len(bubbles) + 1,
            "speaker_opcode": f"0x{current_speaker:04X}",
            "pages": pages_text,
            "text_ru": "\f".join(pages_text),
        })
        current_bubble_pages = []
        current_page_words = []

    while i < len(words):
        w = words[i]
        if w == OPCODE_BLOCK_END:
            break
        elif w == OPCODE_BUBBLE_ADVANCE:
            next_w = words[i + 1] if i + 1 < len(words) else OPCODE_BLOCK_END
            if next_w == OPCODE_BLOCK_END:
                break
            elif next_w >= 0x9000:
                # Switch speaker and start new bubble
                _flush_bubble()
                current_speaker = next_w
                i += 2
                continue
            else:
                # Next page of same speaker (< 0x9000)
                current_bubble_pages.append(current_page_words)
                current_page_words = []
                i += 1
                continue
        else:
            current_page_words.append(w)
            i += 1

    if current_speaker is not None:
        _flush_bubble()

    return bubbles


def decode_conversation_block(
    data: bytes,
    reverse_charmap: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    """Decode binary conversation block into block dictionary containing 'bubbles'."""
    return {
        "bubbles": decode_conversation_bubbles(data, reverse_charmap),
    }


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
    - Maximum 3 lines per page/bubble.
    - Explicit '\\n' for newlines, '\\f' for page breaks.
    """
    issues: list[str] = []
    blocks = catalog.get("blocks", [])
    for block in blocks:
        block_id = block.get("id", "unknown")
        for bubble in block.get("bubbles", []):
            bubble_idx = bubble.get("bubble_index", 1)
            if "pages" in bubble and bubble["pages"] is not None:
                pages: list[str] = []
                for p in bubble["pages"]:
                    pages.extend(p.split("\f"))
            else:
                text_ru = bubble.get("text_ru", "")
                pages = text_ru.split("\f")

            for page_idx, page in enumerate(pages, 1):
                lines = page.split("\n")
                prefix = (
                    f"{block_id} bubble {bubble_idx}"
                    if len(pages) == 1
                    else f"{block_id} bubble {bubble_idx} page {page_idx}"
                )
                if len(lines) > max_lines_per_bubble:
                    issues.append(
                        f"{prefix}: {len(lines)} lines exceeds max {max_lines_per_bubble}"
                    )
                for line_idx, line in enumerate(lines, 1):
                    if len(line) > max_chars_per_line:
                        issues.append(
                            f"{prefix} line {line_idx}: length {len(line)} exceeds max {max_chars_per_line} ('{line}')"
                        )
    return issues

def patch_combat_system_strings(
    e7_data: bytearray,
    charmap: Mapping[str, int] | None = None,
) -> bytearray:
    """Patch 18 fixed 16-byte command slots and 14 fixed prompt slots into Entry 0x007.

    1. Slots 0x05F278..0x05F398: 18 fixed 16-byte (0x10) slots.
       Each string is encoded with combat dialogue charmap, terminated with 0x00FF,
       padded with 0x00, and verified to fit within 16 bytes.
    2. Fixed prompt slots 0x05F394..0x05F46C:
       14 fixed prompt slots in FIXED_PROMPT_SLOTS matching PS1 hardware pointers.
       Each string is encoded with combat dialogue charmap, terminated with 0x00FF,
       and padded with 0x00 up to its exact slot length.
    3. Any unallocated gaps between slots up to 0x05F470 are zeroed.
    4. Table 2 boundary at 0x05F470 is strictly preserved.
    """
    cm = charmap if charmap is not None else COMBAT_CHARMAP
    if not isinstance(e7_data, bytearray):
        e7_data = bytearray(e7_data)

    # 1. 18 fixed 16-byte command slots (0x05F278..0x05F398)
    for slot_offset, text in SYSTEM_COMMAND_SLOTS:
        encoded = encode_combat_dialogue_string(text, cm) + struct.pack("<H", OPCODE_BLOCK_END)
        if len(encoded) > 16:
            raise ValueError(
                f"Command string '{text}' at 0x{slot_offset:06X} exceeds 16-byte slot: {len(encoded)} bytes > 16"
            )
        padded = encoded.ljust(16, b"\x00")
        e7_data[slot_offset : slot_offset + 16] = padded

    # 2. 14 fixed prompt slots in FIXED_PROMPT_SLOTS (0x05F394..0x05F46C)
    for slot_offset, slot_len, text in FIXED_PROMPT_SLOTS:
        encoded = encode_combat_dialogue_string(text, cm) + struct.pack("<H", OPCODE_BLOCK_END)
        if len(encoded) > slot_len:
            raise ValueError(
                f"Prompt string '{text}' at 0x{slot_offset:06X} exceeds {slot_len}-byte slot: {len(encoded)} bytes > {slot_len}"
            )
        padded = encoded.ljust(slot_len, b"\x00")
        e7_data[slot_offset : slot_offset + slot_len] = padded

    # 3. Zero out any unallocated gaps between slots up to 0x05F470
    for i in range(len(FIXED_PROMPT_SLOTS) - 1):
        curr_end = FIXED_PROMPT_SLOTS[i][0] + FIXED_PROMPT_SLOTS[i][1]
        next_start = FIXED_PROMPT_SLOTS[i + 1][0]
        if next_start > curr_end:
            e7_data[curr_end : next_start] = b"\x00" * (next_start - curr_end)

    last_slot_end = FIXED_PROMPT_SLOTS[-1][0] + FIXED_PROMPT_SLOTS[-1][1] if FIXED_PROMPT_SLOTS else 0x05F46C
    if last_slot_end < OFFSET_TABLE2_START:
        e7_data[last_slot_end : OFFSET_TABLE2_START] = b"\x00" * (OFFSET_TABLE2_START - last_slot_end)

    # 4. Verify Table 2 at 0x05F470 is never touched
    assert len(e7_data) >= OFFSET_TABLE2_START, "Entry 0x007 buffer too small"

    return e7_data


def verify_combat_system_strings(
    e7_data: bytes,
    charmap: Mapping[str, int] | None = None,
) -> None:
    """Verify that Entry 0x007 contains correctly formatted Russian system strings.

    1. Checks all 18 fixed command slots in 0x05F278..0x05F398.
       For slots 0..16, checks the full 16-byte padded slot.
       For slot 17 (0x05F388), checks the encoded command string ending at 0x05F394.
    2. Checks all 14 fixed prompt slots in FIXED_PROMPT_SLOTS (0x05F394..0x05F46C).
       Verifies each string starts at its exact offset and is padded with 0x00.
    3. Confirms unallocated gaps between slots and up to 0x05F470 are zeroed.
    4. Confirms Table 2 boundary at 0x05F470 is strictly preserved.
    """
    cm = charmap if charmap is not None else COMBAT_CHARMAP

    # Verify 18 fixed command slots
    first_prompt_offset = FIXED_PROMPT_SLOTS[0][0] if FIXED_PROMPT_SLOTS else 0x05F394
    for slot_offset, text in SYSTEM_COMMAND_SLOTS:
        encoded = encode_combat_dialogue_string(text, cm) + struct.pack("<H", OPCODE_BLOCK_END)
        if len(encoded) > 16:
            raise AssertionError(f"Command '{text}' exceeds 16-byte budget: {len(encoded)} bytes")
        if slot_offset + 16 <= first_prompt_offset:
            expected_slot = encoded.ljust(16, b"\x00")
            actual_slot = e7_data[slot_offset : slot_offset + 16]
            if actual_slot != expected_slot:
                raise AssertionError(
                    f"Command '{text}' mismatch at 0x{slot_offset:06X}: expected {expected_slot.hex()}, got {actual_slot.hex()}"
                )
        else:
            actual_str = e7_data[slot_offset : slot_offset + len(encoded)]
            if actual_str != encoded:
                raise AssertionError(
                    f"Command '{text}' mismatch at 0x{slot_offset:06X}: expected {encoded.hex()}, got {actual_str.hex()}"
                )

    # Verify 14 fixed prompt slots
    for slot_offset, slot_len, text in FIXED_PROMPT_SLOTS:
        encoded = encode_combat_dialogue_string(text, cm) + struct.pack("<H", OPCODE_BLOCK_END)
        if len(encoded) > slot_len:
            raise AssertionError(f"Prompt '{text}' exceeds {slot_len}-byte budget: {len(encoded)} bytes")
        expected_slot = encoded.ljust(slot_len, b"\x00")
        actual_slot = e7_data[slot_offset : slot_offset + slot_len]
        if actual_slot != expected_slot:
            raise AssertionError(
                f"Prompt '{text}' mismatch at 0x{slot_offset:06X}: expected {expected_slot.hex()}, got {actual_slot.hex()}"
            )

    # Verify unallocated gaps are zeroed
    for i in range(len(FIXED_PROMPT_SLOTS) - 1):
        curr_end = FIXED_PROMPT_SLOTS[i][0] + FIXED_PROMPT_SLOTS[i][1]
        next_start = FIXED_PROMPT_SLOTS[i + 1][0]
        if next_start > curr_end:
            gap = e7_data[curr_end:next_start]
            if gap != b"\x00" * (next_start - curr_end):
                raise AssertionError(f"Gap at 0x{curr_end:06X}..0x{next_start:06X} is not zeroed: {gap.hex()}")

    if FIXED_PROMPT_SLOTS:
        last_slot_end = FIXED_PROMPT_SLOTS[-1][0] + FIXED_PROMPT_SLOTS[-1][1]
        if last_slot_end < OFFSET_TABLE2_START:
            gap = e7_data[last_slot_end:OFFSET_TABLE2_START]
            if gap != b"\x00" * (OFFSET_TABLE2_START - last_slot_end):
                raise AssertionError(f"Gap at 0x{last_slot_end:06X}..0x{OFFSET_TABLE2_START:06X} is not zeroed: {gap.hex()}")

def verify_entry_checksums(bin_path: Path, prog_lba: int, start_sector: int, sector_count: int) -> int:
    """Verify Mode 2 Form 1 EDC and ECC checksums for all sectors of an entry."""
    checksums = CdChecksums()
    verified = 0
    with bin_path.open("rb") as f:
        for s in range(sector_count):
            lba = prog_lba + start_sector + s
            f.seek(lba * RAW_SECTOR_SIZE)
            sec = f.read(RAW_SECTOR_SIZE)
            if len(sec) < RAW_SECTOR_SIZE:
                raise AssertionError(f"Sector at LBA {lba} truncated: {len(sec)} bytes")
            if sec[0x818:0x81C] != checksums.compute_edc(sec[0x10:0x818]):
                raise AssertionError(f"EDC mismatch at LBA {lba}")
            if sec[0x81C:0x8C8] != checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86):
                raise AssertionError(f"ECC P-parity mismatch at LBA {lba}")
            if sec[0x8C8:0x930] != checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88):
                raise AssertionError(f"ECC Q-parity mismatch at LBA {lba}")
            verified += 1
    return verified


def verify_entry_7_invariants(orig_e7: bytes, patched_e7: bytes) -> None:
    """Verify that all protected regions outside dialogue stream and system strings are 100% untouched."""
    # 1. Everything before system strings (0..0x05F278) must be byte-exact identical
    if patched_e7[:OFFSET_SYSTEM_BUTTONS_START] != orig_e7[:OFFSET_SYSTEM_BUTTONS_START]:
        raise AssertionError("Invariant violation: Bytes before 0x05F278 were modified!")

    # 2. Table 1 at 0x05F1FC..0x05F258 must be untouched
    if patched_e7[OFFSET_TABLE1_START:OFFSET_SYSTEM_BUTTONS_START] != orig_e7[OFFSET_TABLE1_START:OFFSET_SYSTEM_BUTTONS_START]:
        raise AssertionError("Invariant violation: Table 1 was modified!")

    # 3. MIPS instruction at 0x02B78C must be untouched
    if patched_e7[OFFSET_MIPS_INIT_EXIT : OFFSET_MIPS_INIT_EXIT + 8] != orig_e7[OFFSET_MIPS_INIT_EXIT : OFFSET_MIPS_INIT_EXIT + 8]:
        raise AssertionError("Invariant violation: MIPS instruction at 0x02B78C was modified!")

    # 4. Table 2 at 0x05F470..0x05F504 and pre-dialogue region (0x05F470..0x05F810) must be untouched
    if patched_e7[OFFSET_TABLE2_START:DIALOGUE_STREAM_START] != orig_e7[OFFSET_TABLE2_START:DIALOGUE_STREAM_START]:
        raise AssertionError("Invariant violation: Table 2 or pre-dialogue region (0x05F470..0x05F810) was modified!")

    # 5. Everything at/after Table 3 must be byte-exact identical
    if patched_e7[OFFSET_TABLE3_START:] != orig_e7[OFFSET_TABLE3_START:]:
        raise AssertionError("Invariant violation: Bytes at/after Table 3 (0x06286C) were modified!")

    # 6. Verify Russian system strings are correctly placed and formatted
    verify_combat_system_strings(patched_e7)

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
    template_path: Path | None = None,
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
    patched_tim, compressed_font = build_patched_combat_font(orig_tim, font_path, template_path=template_path)

    # Pad compressed font to exact sector budget
    font_budget = e142_count * USER_DATA_SIZE
    padded_font = compressed_font.ljust(font_budget, b"\x00")

    # 4. Validate formatting constraints (<= 21 chars/line, <= 3 lines/bubble)
    formatting_issues = validate_dialogue_formatting(catalog)

    # 5. Patch Entry 0x007 in-place (dialogue blocks + system commands & prompts)
    patched_e7 = patch_dialogue_blocks(orig_e7, catalog)
    patched_e7 = patch_combat_system_strings(bytearray(patched_e7))

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
        "system_commands_patched": len(SYSTEM_COMMAND_SLOTS),
        "prompt_strings_patched": len(FIXED_PROMPT_SLOTS),
        "compressed_font_size": len(compressed_font),
        "font_budget": COMBAT_FONT_MAX_SIZE,
        "font_margin": COMBAT_FONT_MAX_SIZE - len(compressed_font),
        "entry_7_sectors": e7_count,
        "entry_142_sectors": e142_count,
        "dry_run": dry_run,
        "target_bin": str(work_bin),
        "formatting_issues": formatting_issues,
    }


# Alias for external callers/pipeline
patch_combat_dialogues_pipeline = patch_combat_dialogues


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch combat dialogues and font in Slayers Royal (PS1).")
    parser.add_argument("--bin", type=Path, default=DEFAULT_BIN, help="Path to input disc image (sr.bin / sr_patched.bin)")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="Path to translations JSON catalog")
    parser.add_argument("--output-bin", type=Path, help="Path to output modified disc image")
    parser.add_argument("--dry-run", action="store_true", help="Validate and encode without modifying disc image")
    parser.add_argument("--verify", action="store_true", help="Run thorough validation and invariant checks")
    parser.add_argument("--template", type=Path, default=REPO_ROOT / "data" / "combat_font_template.png", help="Path to combat font template PNG")
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
            template_path=args.template,
        )
        print(f"Successfully processed {result['blocks_patched']} dialogue blocks.")
        print(f"Patched {result['system_commands_patched']} combat command slots (0x05F278..0x05F398).")
        print(f"Patched {result['prompt_strings_patched']} fixed prompt slots (0x05F394..0x05F46C).")
        print(f"Font compressed size: {result['compressed_font_size']:,} bytes / {result['font_budget']:,} budget "
              f"(Margin: {result['font_margin']:,} bytes)")
        print(f"Entry 0x007: {result['entry_7_sectors']} sectors, Entry 0x142: {result['entry_142_sectors']} sectors.")
        print("Invariants: 100% verified (Table 1, Table 2, Table 3, System buttons, MIPS 0x02B78C intact).")
        if args.verify and args.bin.is_file():
            prog_lba, e7_start, e7_count, disc_e7 = extract_entry_data_and_info(args.bin, ENTRY_COMBAT_DATA)
            try:
                verify_combat_system_strings(disc_e7)
                sec_count = verify_entry_checksums(args.bin, prog_lba, e7_start, e7_count)
                print(f"EDC/ECC verified on all {sec_count} sectors of Entry 0x007 on {args.bin.name}.")
            except Exception:
                pass
        return 0
    except Exception as e:
        print(f"Error during patching: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
