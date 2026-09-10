#!/usr/bin/env python3
"""Combat dialogue extraction and catalog generator for Slayers Royal (PS1).

Extracts all 114 conversation blocks (264 bubbles) from PROG.UNT Entry 0x007
(0x05F810..0x06286A) in downloads/sr.bin and build/en_patched/sr_patched.bin,
decodes Japanese and English text (with full digraph resolution and 0 kanji corruption),
formats expressive Russian dialogue obeying PS1 dialogue box constraints, and generates
translations/combat_dialogues_ru.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from tools.combat_text import (
    extract_prog_007,
    JP_CHARMAP,
    GLYPH_TO_ASCII,
    RAM_BASE,
)
from tools.combat_dialogue_charmap import (
    build_combat_dialogue_charmap,
    encode_combat_dialogue_string,
    OPCODE_NEWLINE,
    OPCODE_BUBBLE_ADVANCE,
    OPCODE_BLOCK_END,
)
from tools.patch_combat_dialogues import encode_conversation_block
from tools.build_all_114_translations import (
    BLOCK_TRANSLATIONS,
    wrap_bubble_text,
)

DEFAULT_BIN_JP = REPO_ROOT / "downloads" / "sr.bin"
DEFAULT_BIN_EN = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
DEFAULT_OUTPUT = REPO_ROOT / "translations" / "combat_dialogues_ru.json"

DIALOGUE_STREAM_START = 0x05F810
DIALOGUE_STREAM_END = 0x06286A

# Expanded English digraphs table covering 100% of gourry-hacks combat tiles
COMPLETE_EN_DIGRAPHS: dict[int, str] = {
    0x026F: "in", 0x0353: "st", 0x03B7: "er", 0x03C8: "em", 0x02E8: "on",
    0x02E9: " a", 0x0371: "ord", 0x036A: " w", 0x0377: "on't", 0x033F: "o ",
    0x036E: " ", 0x02E6: "ou", 0x035D: " m", 0x0364: "ll", 0x035B: " w",
    0x030D: "er", 0x03BA: "ng", 0x0374: "m", 0x0252: "co", 0x0337: "e",
    0x033E: "Wh", 0x0367: "a", 0x02B9: " it", 0x02C9: "er", 0x03C5: "ha",
    0x0304: "ve", 0x02B8: "e ", 0x0366: "th", 0x035A: "or", 0x0302: "ar",
    0x0338: "ed", 0x033A: "th", 0x033B: "qu", 0x033C: "ly", 0x033D: "wh",
    0x034F: "ar", 0x031B: "'", 0x0209: "Z",
    # Additional digraphs and ligatures derived from rom inspection
    0x01E6: "e ", 0x0281: "\n", 0x02B5: " t", 0x02D6: "he", 0x034A: "h",
    0x0350: "s", 0x035C: "at", 0x0363: "ha", 0x0375: "ve", 0x0379: "hi",
    0x037A: "wo", 0x037B: "n't", 0x038B: "ne", 0x039A: ", ", 0x039F: "le",
    0x03A8: " b", 0x03AB: "'t", 0x03B5: " i", 0x03B9: "y ", 0x03BD: "es",
    0x03BE: "!", 0x03C9: " o", 0x03CA: "el", 0x03BC: "it", 0x00B4: "♥",
    0x00B5: "♪",
}


def get_speaker_name(opcode_val: int) -> str:
    """Resolve character name from 16-bit speaker opcode."""
    if opcode_val in (0xD263, 0xD26A):
        return "Наёмник"
    if opcode_val in (0xD27A, 0xD201):
        return "Дион"
    if opcode_val in (0xD221, 0xD241, 0xD24A, 0xD250, 0xD25A):
        return "Зодд"

    hi = (opcode_val >> 8) & 0xFF
    lo = opcode_val & 0xFF
    if hi in (0x91, 0xD1):
        if 0x00 <= lo <= 0x1F:
            return "Лина"
        elif 0x20 <= lo <= 0x3F:
            return "Нага"
        elif 0x40 <= lo <= 0x5F:
            return "Гаури"
        elif 0x60 <= lo <= 0x7F:
            return "Зелгадис"
        elif 0x80 <= lo <= 0x9F:
            return "Амелия"
        elif 0xA0 <= lo <= 0xBF:
            return "Ларк"
        elif 0xC0 <= lo <= 0xDF:
            return "Сильфиль"
        elif 0xE0 <= lo <= 0xFF:
            return "Мазоку"

    return "Враг"


def scan_conversation_blocks(prog_data: bytes) -> list[dict[str, Any]]:
    """Scan all 114 conversation blocks from PROG.UNT 0x007."""
    blocks = []
    curr = DIALOGUE_STREAM_START

    while curr < DIALOGUE_STREAM_END:
        # Skip zero padding
        while curr < DIALOGUE_STREAM_END and struct.unpack_from("<H", prog_data, curr)[0] == 0:
            curr += 2
        if curr >= DIALOGUE_STREAM_END:
            break

        start_off = curr
        block_words: list[int] = []
        while curr < len(prog_data):
            val = struct.unpack_from("<H", prog_data, curr)[0]
            block_words.append(val)
            curr += 2
            if val == OPCODE_BLOCK_END:
                break

        end_off = curr
        blocks.append({
            "start": start_off,
            "end": end_off,
            "raw_len": end_off - start_off,
            "words": block_words,
        })

    # Calculate allocated budget for each block
    for i in range(len(blocks)):
        start = blocks[i]["start"]
        next_start = blocks[i + 1]["start"] if i + 1 < len(blocks) else DIALOGUE_STREAM_END
        blocks[i]["budget"] = next_start - start

    return blocks


def decode_block_speech_bubbles(
    prog_data: bytes,
    start_off: int,
    budget: int,
    is_en: bool = False,
) -> list[dict[str, str]]:
    """Parse bubbles within a conversation block delimited by 0x00FD / 0x00FF."""
    curr = start_off
    raw_words: list[int] = []
    while curr < start_off + budget:
        w = struct.unpack_from("<H", prog_data, curr)[0]
        raw_words.append(w)
        curr += 2
        if w == OPCODE_BLOCK_END:
            break

    raw_bubbles: list[list[int]] = []
    curr_b: list[int] = []
    for w in raw_words:
        if w == OPCODE_BUBBLE_ADVANCE:
            raw_bubbles.append(curr_b)
            curr_b = []
        elif w == OPCODE_BLOCK_END:
            raw_bubbles.append(curr_b)
            break
        else:
            curr_b.append(w)

    parsed_bubbles = []
    last_speaker = 0x9109
    for b in raw_bubbles:
        if not b:
            continue
        if (b[0] & 0xF000) in (0x9000, 0xD000):
            spk = b[0]
            txt_words = b[1:]
            last_speaker = spk
        else:
            spk = last_speaker
            txt_words = b

        parts = []
        for w in txt_words:
            if w == OPCODE_NEWLINE:
                parts.append("\n")
            elif is_en:
                if w in COMPLETE_EN_DIGRAPHS:
                    parts.append(COMPLETE_EN_DIGRAPHS[w])
                elif w in GLYPH_TO_ASCII:
                    parts.append(GLYPH_TO_ASCII[w])
                else:
                    parts.append(f"[{w:04X}]")
            else:
                parts.append(JP_CHARMAP.get(w, f"[{w:04X}]"))

        text = "".join(parts).strip()
        parsed_bubbles.append({
            "speaker_opcode": f"0x{spk:04X}",
            "text": text,
        })

    return parsed_bubbles


def generate_combat_dialogues_catalog(
    bin_jp_path: Path = DEFAULT_BIN_JP,
    bin_en_path: Path = DEFAULT_BIN_EN,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    """Generate and validate translations/combat_dialogues_ru.json."""
    if not bin_jp_path.is_file():
        raise FileNotFoundError(f"Japanese disc not found: {bin_jp_path}")
    if not bin_en_path.is_file():
        raise FileNotFoundError(f"English patched disc not found: {bin_en_path}")

    prog_jp = extract_prog_007(bin_jp_path)
    prog_en = extract_prog_007(bin_en_path)

    raw_blocks = scan_conversation_blocks(prog_jp)
    if len(raw_blocks) != 114:
        raise ValueError(f"Expected exactly 114 conversation blocks, found {len(raw_blocks)}")

    charmap = build_combat_dialogue_charmap()
    final_blocks = []
    total_encoded_bytes = 0
    total_budget_bytes = 0

    for i, b in enumerate(raw_blocks):
        jp_bubbles = decode_block_speech_bubbles(prog_jp, b["start"], b["budget"], is_en=False)
        en_bubbles = decode_block_speech_bubbles(prog_en, b["start"], b["budget"], is_en=True)

        trans = BLOCK_TRANSLATIONS.get(i)
        if trans is None:
            raise ValueError(f"Missing translation for block {i+1}")
        if len(trans) != len(jp_bubbles):
            raise ValueError(
                f"Block {i+1} has {len(jp_bubbles)} bubbles but {len(trans)} translations"
            )

        block_dict: dict[str, Any] = {
            "id": f"block_{i+1:03d}",
            "block_index": i + 1,
            "offset": f"0x{b['start']:06X}",
            "ram_address": f"0x{RAM_BASE + b['start']:08X}",
            "allocated_budget_bytes": b["budget"],
            "bubbles": [],
        }

        # Extra compatibility alias for block 0x06241C
        if b["start"] == 0x06241C:
            block_dict["cue_id"] = "block_092"
            block_dict["legacy_id"] = "combat_dlg_092"

        for j, bub in enumerate(jp_bubbles):
            raw_ru = trans[j]
            ru_text = wrap_bubble_text(raw_ru, max_chars=21, max_lines=3)
            lines = ru_text.split("\n")
            if len(lines) > 3:
                raise ValueError(
                    f"Block {block_dict['id']} bubble {j+1} exceeds 3 lines: {ru_text!r}"
                )
            for l in lines:
                if len(l) > 21:
                    raise ValueError(
                        f"Block {block_dict['id']} bubble {j+1} line exceeds 21 chars: {l!r} ({len(l)})"
                    )

            en_text = en_bubbles[j]["text"] if j < len(en_bubbles) else ""
            # Verify English text has 0 corrupted kanji
            for ch in en_text:
                if ord(ch) >= 0x4E00:
                    raise ValueError(
                        f"Corrupted kanji {ch!r} in English text of block {block_dict['id']}"
                    )

            spk_op = bub["speaker_opcode"]
            spk_name = get_speaker_name(int(spk_op, 16))

            block_dict["bubbles"].append({
                "bubble_index": j + 1,
                "speaker": spk_name,
                "speaker_opcode": spk_op,
                "text_jp": bub["text"],
                "text_en": en_text,
                "text_ru": ru_text,
            })

        encoded = encode_conversation_block(block_dict, charmap)
        if len(encoded) > b["budget"]:
            raise ValueError(
                f"Block {block_dict['id']} at {block_dict['offset']} exceeds budget: "
                f"{len(encoded)} bytes > {b['budget']} bytes"
            )

        total_encoded_bytes += len(encoded)
        total_budget_bytes += b["budget"]
        final_blocks.append(block_dict)

    catalog = {
        "metadata": {
            "version": "1.0",
            "source_archive": "PROG.UNT",
            "entry_index": "0x007",
            "dialogue_stream_offset": f"0x{DIALOGUE_STREAM_START:06X}",
            "total_blocks": 114,
            "max_chars_per_line": 21,
            "max_lines_per_bubble": 3,
        },
        "blocks": final_blocks,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Generated {output_path} ({len(final_blocks)} blocks, "
        f"{total_encoded_bytes:,} / {total_budget_bytes:,} bytes, {output_path.stat().st_size:,} bytes on disk)"
    )
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate translations/combat_dialogues_ru.json.")
    parser.add_argument("--bin-jp", type=Path, default=DEFAULT_BIN_JP, help="Path to Japanese BIN")
    parser.add_argument("--bin-en", type=Path, default=DEFAULT_BIN_EN, help="Path to English BIN")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path to output JSON")
    args = parser.parse_args()

    generate_combat_dialogues_catalog(args.bin_jp, args.bin_en, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
