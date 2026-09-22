#!/usr/bin/env python3
"""Unit tests for combat dialogue patcher and Cyrillic charmap.

Tests:
1. Charmap encoding & bidirectional mapping, safe Cyrillic tile allocation (0x0150..0x0191),
   and zero conflict with English UI buttons, system strings, digits, and punctuation.
2. Font 0x142 rendering, unt_lz mode 1 compression within 23 sectors (47,104 bytes),
   and round-trip bit-exact decompression.
3. In-place conversation block encoding, opcode insertion (0x00FE, 0x00FD, 0x00FF),
   zero-padding, and budget overflow detection.
4. Invariant protection: Table 1, Table 2, Table 3, system buttons (0x05F278..0x05F470),
   and MIPS instruction at 0x02B78C must remain 100% untouched.
5. Dry-run execution of patch_combat_dialogues pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
import struct
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))
from localization import unt_lz
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
    build_combat_dialogue_charmap,
    build_reverse_charmap,
    encode_combat_dialogue_string,
    decode_combat_dialogue_string,
    scan_protected_tiles,
    find_safe_cyrillic_tiles,
)
from tools.patch_combat_dialogues import (
    DEFAULT_BIN,
    DEFAULT_CATALOG,
    DEFAULT_TIM_CACHE,
    DEFAULT_FONT,
    ENTRY_COMBAT_DATA,
    ENTRY_COMBAT_FONT,
    COMBAT_FONT_MAX_SIZE,
    DIALOGUE_STREAM_START,
    DIALOGUE_STREAM_END,
    OFFSET_MIPS_INIT_EXIT,
    OFFSET_TABLE1_START,
    OFFSET_SYSTEM_BUTTONS_START,
    OFFSET_SYSTEM_BUTTONS_END,
    OFFSET_TABLE2_START,
    OFFSET_TABLE3_START,
    build_patched_combat_font,
    get_hw_tile_2bpp,
    put_hw_tile_2bpp,
    render_cyrillic_glyph_2bpp,
    encode_conversation_block,
    decode_conversation_block,
    decode_conversation_bubbles,
    validate_dialogue_formatting,
    patch_dialogue_blocks,
    verify_entry_7_invariants,
    patch_combat_dialogues,
    extract_entry_data_and_info,
    UI_POINTER_COUNT,
    UI_POINTER_BASE,
    load_system_strings,
    pack_ui_strings,
    patch_combat_system_strings,
    verify_combat_system_strings,
    verify_entry_checksums,
    patch_combat_dialogues_pipeline,
)
from tools.patch_combat_font import import_combat_font_template


class TestCombatDialogueCharmap(unittest.TestCase):
    """Test Cyrillic charmap, safe tile allocation, and bidirectional translation."""

    def test_cyrillic_alphabet_counts(self):
        """Test that Cyrillic alphabet contains 33 uppercase and 33 lowercase letters."""
        self.assertEqual(len(CYRILLIC_UPPER), 33)
        self.assertEqual(len(CYRILLIC_LOWER), 33)
        self.assertIn("Ё", CYRILLIC_UPPER)
        self.assertIn("ё", CYRILLIC_LOWER)

    def test_designated_tile_range(self):
        """Test designated Cyrillic tile slots are 0x0150..0x0191."""
        tiles = find_safe_cyrillic_tiles()
        self.assertEqual(len(tiles), 66)
        self.assertEqual(tiles[0], 0x0150)
        self.assertEqual(tiles[-1], 0x0191)
        self.assertEqual(tiles[32], 0x0170)
        self.assertEqual(tiles[33], 0x0171)

    def test_zero_conflicts_with_protected_tiles(self):
        """Verify zero conflict between Cyrillic tiles and English UI/buttons/digits."""
        protected = scan_protected_tiles()
        designated = set(range(CYRILLIC_UPPER_BASE, CYRILLIC_UPPER_BASE + 66))
        conflicts = designated & protected
        self.assertEqual(len(conflicts), 0, f"Found conflicts: {[hex(c) for c in conflicts]}")

    def test_bidirectional_roundtrip(self):
        """Test round-trip encoding and decoding of Russian dialogue text."""
        test_strings = [
            "Тьфу! Если б ты пошла с нами, эти типы не совали бы свой нос!",
            "Заткнись!\nНи за что я к вам\nне присоединюсь!",
            "Ой, как страшно!\nПоглядим, надолго ли\nхватит этой спеси.",
            "Нага! Учти, город совсем рядом! Драгу-Слейв применять нельзя!",
            "Гаури, кажется, он мазоку!",
            "Эй! 12345... Что это было?!",
        ]
        for s in test_strings:
            encoded = encode_combat_dialogue_string(s)
            decoded = decode_combat_dialogue_string(encoded)
            self.assertEqual(decoded, s, f"Mismatch for '{s}'")

    def test_control_codes_encoding(self):
        """Test newline (0x00FE) and bubble advance (0x00FD) encoding."""
        encoded = encode_combat_dialogue_string("Привет\nМир\fДа")
        words = [struct.unpack_from("<H", encoded, i)[0] for i in range(0, len(encoded), 2)]
        self.assertIn(OPCODE_NEWLINE, words)
        self.assertIn(OPCODE_BUBBLE_ADVANCE, words)


    def test_opcode_page_break_constant(self):
        """Test OPCODE_PAGE_BREAK constant and alias to OPCODE_BUBBLE_ADVANCE (0x00FD)."""
        self.assertEqual(OPCODE_PAGE_BREAK, 0x00FD)
        self.assertEqual(OPCODE_PAGE_BREAK, OPCODE_BUBBLE_ADVANCE)

    def test_form_feed_page_break_roundtrip(self):
        """Test encoding and decoding of \\f (form-feed) as page break delimiter."""
        sample = "Лина:\nПервая страница!\fВторая страница!\fТретья страница!"
        encoded = encode_combat_dialogue_string(sample)
        words = [struct.unpack_from("<H", encoded, i)[0] for i in range(0, len(encoded), 2)]

        # Must contain OPCODE_PAGE_BREAK (0x00FD) exactly twice
        self.assertEqual(words.count(OPCODE_PAGE_BREAK), 2)
        # Must decode back cleanly to original string
        decoded = decode_combat_dialogue_string(encoded)
        self.assertEqual(decoded, sample)

class TestCombatFontGeneration(unittest.TestCase):
    """Test combat font TIM modification and compression within 23-sector budget."""

    def test_font_compression_within_budget(self):
        """Verify that font 0x142 with 66 Cyrillic glyphs compresses <= 47,104 bytes."""
        self.assertTrue(DEFAULT_TIM_CACHE.is_file(), "Cached English TIM not found")
        orig_tim = DEFAULT_TIM_CACHE.read_bytes()
        patched_tim, compressed = build_patched_combat_font(orig_tim, DEFAULT_FONT)

        self.assertEqual(len(patched_tim), 66080)
        self.assertLessEqual(
            len(compressed),
            COMBAT_FONT_MAX_SIZE,
            f"Compressed font size {len(compressed)} exceeds {COMBAT_FONT_MAX_SIZE} bytes",
        )
        # Verify decompression bit-exact round-trip
        decompressed, _ = unt_lz.decompress(compressed)
        self.assertEqual(decompressed, patched_tim)

    def test_latin_tiles_preserved_in_font(self):
        """Verify that existing English tiles are not modified by Cyrillic font patching."""
        orig_tim = DEFAULT_TIM_CACHE.read_bytes()
        patched_tim, _ = build_patched_combat_font(orig_tim, DEFAULT_FONT)

        # Tile 0x00BE is 'A' in English combat UI
        self.assertEqual(get_hw_tile_2bpp(orig_tim, 0x00BE), get_hw_tile_2bpp(patched_tim, 0x00BE))
        # Tile 0x007D is transparent space
        self.assertEqual(get_hw_tile_2bpp(orig_tim, 0x007D), get_hw_tile_2bpp(patched_tim, 0x007D))
        # Tile 0x00A8 is digit '0'
        self.assertEqual(get_hw_tile_2bpp(orig_tim, 0x00A8), get_hw_tile_2bpp(patched_tim, 0x00A8))

    def test_cyrillic_glyph_2bpp_encoding(self):
        """Verify 2BPP encoding format and constraints for Cyrillic glyphs."""
        self.assertTrue(DEFAULT_FONT.is_file(), "Default font not found")
        for ch in ("А", "П", "Я", "а", "п", "я", "Ё", "ё"):
            tile_bytes = render_cyrillic_glyph_2bpp(ch, DEFAULT_FONT)
            self.assertEqual(len(tile_bytes), 64, f"Tile {ch} must be exactly 64 bytes (16x16 in 2BPP)")
            self.assertTrue(any(b != 0 for b in tile_bytes), f"Tile {ch} must not be all zeros")

            # Extract 2-bit pixel values (4 pixels per byte)
            pixel_vals = []
            for b in tile_bytes:
                for p in range(4):
                    pixel_vals.append((b >> (p * 2)) & 3)

            # In 2BPP: 0=transparent, 1=shadow, 3=white text body
            self.assertTrue(set(pixel_vals).issubset({0, 1, 3}))
            self.assertIn(3, pixel_vals, f"Tile {ch} must contain text body (3)")
            self.assertIn(1, pixel_vals, f"Tile {ch} must contain shadow (1)")

    def test_hw_tile_0160_is_cyrillic_p_not_kanji(self):
        """Verify that tile 0x0160 unpacks to Cyrillic 'П' and NOT original kanji '助'."""
        orig_tim = DEFAULT_TIM_CACHE.read_bytes()
        patched_tim, _ = build_patched_combat_font(orig_tim, DEFAULT_FONT)

        kanji_tile = get_hw_tile_2bpp(orig_tim, 0x0160)
        p_tile = get_hw_tile_2bpp(patched_tim, 0x0160)

        tpl_path = REPO_ROOT / "data" / "combat_font_template.png"
        if tpl_path.is_file():
            tpl_tiles = import_combat_font_template(tpl_path)
            expected_p = tpl_tiles["П"]
        else:
            expected_p = render_cyrillic_glyph_2bpp("П", DEFAULT_FONT)

        self.assertEqual(p_tile, expected_p)
        self.assertNotEqual(p_tile, kanji_tile, "Tile 0x0160 must not remain Japanese kanji '助'")

        # Verify PressStart2P fallback when template is absent
        patched_fb, _ = build_patched_combat_font(orig_tim, DEFAULT_FONT, template_path=Path("/nonexistent"))
        fb_p = render_cyrillic_glyph_2bpp("П", DEFAULT_FONT)
        self.assertEqual(get_hw_tile_2bpp(patched_fb, 0x0160), fb_p)

    def test_all_66_cyrillic_glyphs_unpack_correctly(self):
        """Verify all 66 Cyrillic glyphs unpack correctly from patched Entry 0x142."""
        orig_tim = DEFAULT_TIM_CACHE.read_bytes()
        patched_tim, _ = build_patched_combat_font(orig_tim, DEFAULT_FONT)

        tpl_path = REPO_ROOT / "data" / "combat_font_template.png"
        if tpl_path.is_file():
            tpl_tiles = import_combat_font_template(tpl_path)
            for idx, ch in enumerate(CYRILLIC_UPPER):
                code = CYRILLIC_UPPER_BASE + idx
                expected = tpl_tiles[ch]
                actual = get_hw_tile_2bpp(patched_tim, code)
                self.assertEqual(actual, expected, f"Uppercase glyph '{ch}' at 0x{code:04X} mismatch")

            for idx, ch in enumerate(CYRILLIC_LOWER):
                code = CYRILLIC_LOWER_BASE + idx
                expected = tpl_tiles[ch]
                actual = get_hw_tile_2bpp(patched_tim, code)
                self.assertEqual(actual, expected, f"Lowercase glyph '{ch}' at 0x{code:04X} mismatch")
        else:
            for idx, ch in enumerate(CYRILLIC_UPPER):
                code = CYRILLIC_UPPER_BASE + idx
                expected = render_cyrillic_glyph_2bpp(ch, DEFAULT_FONT)
                actual = get_hw_tile_2bpp(patched_tim, code)
                self.assertEqual(actual, expected, f"Uppercase glyph '{ch}' at 0x{code:04X} mismatch")

            for idx, ch in enumerate(CYRILLIC_LOWER):
                code = CYRILLIC_LOWER_BASE + idx
                expected = render_cyrillic_glyph_2bpp(ch, DEFAULT_FONT)
                actual = get_hw_tile_2bpp(patched_tim, code)
                self.assertEqual(actual, expected, f"Lowercase glyph '{ch}' at 0x{code:04X} mismatch")
class TestInPlaceDialoguePatching(unittest.TestCase):
    """Test in-place dialogue block encoding, formatting, and invariant preservation."""

    def test_encode_single_block(self):
        """Test encoding of a multi-bubble conversation block."""
        block = {
            "id": "block_test",
            "offset": "0x05F810",
            "allocated_budget_bytes": 176,
            "bubbles": [
                {
                    "bubble_index": 1,
                    "speaker": "Лина",
                    "speaker_opcode": "0x9109",
                    "text_ru": "Нага! Город рядом!",
                },
                {
                    "bubble_index": 2,
                    "speaker": "Нага",
                    "speaker_opcode": "0xD123",
                    "text_ru": "О-хо-хо-хо!",
                },
            ],
        }
        encoded = encode_conversation_block(block)
        # Check first word is 0x9109
        first_word = struct.unpack_from("<H", encoded, 0)[0]
        self.assertEqual(first_word, 0x9109)

        # Check last word is 0x00FF
        last_word = struct.unpack_from("<H", encoded, len(encoded) - 2)[0]
        self.assertEqual(last_word, OPCODE_BLOCK_END)

        # Check 0x00FD is present and followed by 0xD123
        words = [struct.unpack_from("<H", encoded, i)[0] for i in range(0, len(encoded), 2)]
        fd_idx = words.index(OPCODE_BUBBLE_ADVANCE)
        self.assertEqual(words[fd_idx + 1], 0xD123)

        self.assertLessEqual(len(encoded), 176)

    def test_intra_bubble_pagination_encoding(self):
        """Test intra-bubble pagination: bubble with 2 pages encodes as [Speaker] [P1] [0x00FD] [P2] [0x00FF]."""
        # Format a: "pages" list
        block_pages = {
            "id": "block_pages",
            "offset": "0x05F810",
            "allocated_budget_bytes": 176,
            "bubbles": [
                {
                    "bubble_index": 1,
                    "speaker": "Лина",
                    "speaker_opcode": "0x9109",
                    "pages": ["Первая стр.", "Вторая стр."],
                }
            ],
        }
        encoded_pages = encode_conversation_block(block_pages)
        words_pages = [struct.unpack_from("<H", encoded_pages, i)[0] for i in range(0, len(encoded_pages), 2)]

        # Format b: "text_ru" with \f
        block_formfeed = {
            "id": "block_ff",
            "offset": "0x05F810",
            "allocated_budget_bytes": 176,
            "bubbles": [
                {
                    "bubble_index": 1,
                    "speaker": "Лина",
                    "speaker_opcode": "0x9109",
                    "text_ru": "Первая стр.\fВторая стр.",
                }
            ],
        }
        encoded_ff = encode_conversation_block(block_formfeed)
        words_ff = [struct.unpack_from("<H", encoded_ff, i)[0] for i in range(0, len(encoded_ff), 2)]

        # Both formats must yield identical binary streams
        self.assertEqual(encoded_pages, encoded_ff)

        # First word is Speaker Opcode (0x9109)
        self.assertEqual(words_pages[0], 0x9109)

        # Last word is OPCODE_BLOCK_END (0x00FF)
        self.assertEqual(words_pages[-1], OPCODE_BLOCK_END)

        # Must have exactly one 0x00FD delimiter
        self.assertEqual(words_pages.count(OPCODE_BUBBLE_ADVANCE), 1)

        fd_idx = words_pages.index(OPCODE_BUBBLE_ADVANCE)
        # Word following 0x00FD must be the first glyph of page 2 (< 0x9000), NOT a speaker opcode
        next_word = words_pages[fd_idx + 1]
        self.assertLess(next_word, 0x9000, f"Expected glyph code < 0x9000 after 0x00FD, got 0x{next_word:04X}")
        self.assertEqual(next_word, COMBAT_CHARMAP["В"])

    def test_multi_bubble_with_pagination_encoding(self):
        """Test multi-bubble with pagination:
        Bubble 1 (2 pages) + Bubble 2 (1 page) encodes as:
        [Spk1] [P1] [0x00FD] [P2] [0x00FD] [Spk2] [B2] [0x00FF].
        """
        block = {
            "id": "block_multi_paginated",
            "offset": "0x05F810",
            "allocated_budget_bytes": 256,
            "bubbles": [
                {
                    "bubble_index": 1,
                    "speaker": "Лина",
                    "speaker_opcode": "0x9109",
                    "pages": ["Лина: Стр 1", "Лина: Стр 2"],
                },
                {
                    "bubble_index": 2,
                    "speaker": "Нага",
                    "speaker_opcode": "0xD123",
                    "pages": ["Нага: Ответ"],
                },
            ],
        }
        encoded = encode_conversation_block(block)
        words = [struct.unpack_from("<H", encoded, i)[0] for i in range(0, len(encoded), 2)]

        # Word 0: Spk1 (0x9109)
        self.assertEqual(words[0], 0x9109)

        # Last word: 0x00FF
        self.assertEqual(words[-1], OPCODE_BLOCK_END)

        # Exactly two 0x00FD occurrences
        fd_indices = [idx for idx, w in enumerate(words) if w == OPCODE_BUBBLE_ADVANCE]
        self.assertEqual(len(fd_indices), 2)

        # First 0x00FD is followed by Page 2 of Bubble 1 (glyph code < 0x9000, 'Л')
        first_fd = fd_indices[0]
        word_after_fd1 = words[first_fd + 1]
        self.assertLess(word_after_fd1, 0x9000)
        self.assertEqual(word_after_fd1, COMBAT_CHARMAP["Л"])

        # Second 0x00FD is followed by Spk2 (0xD123 >= 0x9000)
        second_fd = fd_indices[1]
        word_after_fd2 = words[second_fd + 1]
        self.assertEqual(word_after_fd2, 0xD123)

    def test_decoding_paginated_streams(self):
        """Test that decoding paginated streams reconstructs pages correctly:
        - 0x00FD followed by glyph (< 0x9000) is recognized as page advance for current speaker.
        - 0x00FD followed by speaker opcode (>= 0x9000) is recognized as a new bubble.
        """
        block = {
            "id": "block_decode_test",
            "bubbles": [
                {
                    "bubble_index": 1,
                    "speaker_opcode": "0x9109",
                    "pages": ["Страница 1\nСтрока 2", "Страница 2"],
                },
                {
                    "bubble_index": 2,
                    "speaker_opcode": "0xD123",
                    "pages": ["Реплика Наги"],
                },
            ],
        }
        encoded = encode_conversation_block(block)

        # Decode via decode_conversation_block and decode_conversation_bubbles
        decoded_block = decode_conversation_block(encoded)
        self.assertIn("bubbles", decoded_block)
        bubbles = decoded_block["bubbles"]
        self.assertEqual(len(bubbles), 2)

        # Direct decode_conversation_bubbles matches
        bubbles_direct = decode_conversation_bubbles(encoded)
        self.assertEqual(bubbles, bubbles_direct)

        # Bubble 1 checks
        b1 = bubbles[0]
        self.assertEqual(b1["bubble_index"], 1)
        self.assertEqual(b1["speaker_opcode"], "0x9109")
        self.assertEqual(b1["pages"], ["Страница 1\nСтрока 2", "Страница 2"])
        self.assertEqual(b1["text_ru"], "Страница 1\nСтрока 2\fСтраница 2")

        # Bubble 2 checks
        b2 = bubbles[1]
        self.assertEqual(b2["bubble_index"], 2)
        self.assertEqual(b2["speaker_opcode"], "0xD123")
        self.assertEqual(b2["pages"], ["Реплика Наги"])
        self.assertEqual(b2["text_ru"], "Реплика Наги")

        # Roundtrip re-encoding matches original byte-exact
        re_encoded = encode_conversation_block(decoded_block)
        self.assertEqual(re_encoded, encoded)

    def test_validation_multi_page_bubbles(self):
        """Test that validation passes for multi-page bubbles where each page has <= 3 lines
        and <= 21 chars, even though total lines across pages > 3.
        """
        # Valid catalog: Bubble with 2 pages, 3 lines each (total 6 lines > 3)
        valid_cat_pages = {
            "blocks": [
                {
                    "id": "block_valid_p",
                    "bubbles": [
                        {
                            "bubble_index": 1,
                            "speaker_opcode": "0x9109",
                            "pages": [
                                "Строка 1\nСтрока 2\nСтрока 3",
                                "Вторая 1\nВторая 2\nВторая 3",
                            ],
                        }
                    ],
                }
            ]
        }
        issues = validate_dialogue_formatting(valid_cat_pages)
        self.assertEqual(issues, [], f"Valid multi-page bubble should have no issues, got: {issues}")

        # Also valid when specified via text_ru with \f
        valid_cat_ff = {
            "blocks": [
                {
                    "id": "block_valid_ff",
                    "bubbles": [
                        {
                            "bubble_index": 1,
                            "speaker_opcode": "0x9109",
                            "text_ru": "Строка 1\nСтрока 2\nСтрока 3\fВторая 1\nВторая 2\nВторая 3",
                        }
                    ],
                }
            ]
        }
        issues_ff = validate_dialogue_formatting(valid_cat_ff)
        self.assertEqual(issues_ff, [], f"Valid multi-page bubble with \\f should have no issues, got: {issues_ff}")

        # Invalid catalog: Page 1 has 4 lines (> 3)
        invalid_cat_lines = {
            "blocks": [
                {
                    "id": "block_inv_lines",
                    "bubbles": [
                        {
                            "bubble_index": 1,
                            "speaker_opcode": "0x9109",
                            "pages": [
                                "Стр 1\nСтр 2\nСтр 3\nСтр 4",
                                "Стр 1\nСтр 2",
                            ],
                        }
                    ],
                }
            ]
        }
        issues_lines = validate_dialogue_formatting(invalid_cat_lines)
        self.assertEqual(len(issues_lines), 1)
        self.assertIn("exceeds max 3", issues_lines[0])

        # Invalid catalog: Page 2 line 1 exceeds 21 chars
        invalid_cat_chars = {
            "blocks": [
                {
                    "id": "block_inv_chars",
                    "bubbles": [
                        {
                            "bubble_index": 1,
                            "speaker_opcode": "0x9109",
                            "pages": [
                                "Короткая строка",
                                "Эта строка намеренно длиннее двадцати одного символа!",
                            ],
                        }
                    ],
                }
            ]
        }
        issues_chars = validate_dialogue_formatting(invalid_cat_chars)
        self.assertEqual(len(issues_chars), 1)
        self.assertIn("exceeds max 21", issues_chars[0])

    def test_budget_overflow_detected(self):
        """Test that exceeding allocated budget raises ValueError."""
        block = {
            "id": "overflow_block",
            "offset": "0x05F810",
            "allocated_budget_bytes": 10,  # Far too small
            "bubbles": [
                {
                    "bubble_index": 1,
                    "speaker": "Лина",
                    "speaker_opcode": "0x9109",
                    "text_ru": "Это очень длинный текст, который гарантированно вызовет переполнение бюджета!",
                },
            ],
        }
        mock_e7 = bytearray(b"\x00" * 0x100000)
        with self.assertRaises(ValueError):
            patch_dialogue_blocks(bytes(mock_e7), {"blocks": [block]})

    def test_zero_table_modification_invariants(self):
        """Test strict invariants: Table 1, 2, 3, buttons, and MIPS instruction untouched."""
        self.assertTrue(DEFAULT_BIN.is_file(), f"Binary not found: {DEFAULT_BIN}")
        _, _, _, orig_e7 = extract_entry_data_and_info(DEFAULT_BIN, ENTRY_COMBAT_DATA)

        # Create a mock catalog with a small valid block at 0x05F810
        block = {
            "id": "block_001",
            "offset": "0x05F810",
            "allocated_budget_bytes": 176,
            "bubbles": [
                {
                    "bubble_index": 1,
                    "speaker": "Лина",
                    "speaker_opcode": "0x9109",
                    "text_ru": "Тестовый диалог!",
                }
            ],
        }
        patched_e7 = patch_dialogue_blocks(orig_e7, {"blocks": [block]})
        patched_e7 = patch_combat_system_strings(bytearray(patched_e7))

        # Must verify without assertion error
        verify_entry_7_invariants(orig_e7, patched_e7)

        # Explicit checks
        self.assertEqual(patched_e7[:OFFSET_SYSTEM_BUTTONS_START], orig_e7[:OFFSET_SYSTEM_BUTTONS_START])
        ui_table_end = OFFSET_TABLE2_START + 4 * UI_POINTER_COUNT
        self.assertEqual(patched_e7[ui_table_end:DIALOGUE_STREAM_START], orig_e7[ui_table_end:DIALOGUE_STREAM_START])
        self.assertEqual(patched_e7[OFFSET_TABLE3_START:], orig_e7[OFFSET_TABLE3_START:])
        self.assertEqual(patched_e7[OFFSET_MIPS_INIT_EXIT:OFFSET_MIPS_INIT_EXIT + 8], orig_e7[OFFSET_MIPS_INIT_EXIT:OFFSET_MIPS_INIT_EXIT + 8])
        self.assertEqual(patched_e7[OFFSET_TABLE1_START:OFFSET_SYSTEM_BUTTONS_START], orig_e7[OFFSET_TABLE1_START:OFFSET_SYSTEM_BUTTONS_START])
    def test_all_114_blocks_in_catalog(self):
        """Verify all 114 conversation blocks in combat_dialogues_ru.json:
        - 114 blocks total.
        - Each block offset in 0x05F810..0x06286A.
        - Encoded block length <= allocated_budget_bytes.
        - Dialogue box limits: <= 21 chars/line, <= 3 lines/bubble.
        - Mercenary dialogue at 0x06241C is present and fits budget.
        """
        self.assertTrue(DEFAULT_CATALOG.is_file(), f"Catalog not found: {DEFAULT_CATALOG}")
        catalog = json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))
        blocks = catalog.get("blocks", [])
        self.assertEqual(len(blocks), 114, f"Expected 114 blocks, found {len(blocks)}")

        found_mercenary_block = False
        for b in blocks:
            block_id = b.get("id")
            raw_off = b.get("offset")
            offset = int(raw_off, 16) if isinstance(raw_off, str) else int(raw_off)
            budget = int(b.get("allocated_budget_bytes", 0))

            self.assertGreaterEqual(offset, DIALOGUE_STREAM_START)
            self.assertLess(offset, DIALOGUE_STREAM_END)

            encoded = encode_conversation_block(b)
            self.assertLessEqual(
                len(encoded),
                budget,
                f"Block {block_id} (0x{offset:06X}) encoded size {len(encoded)} exceeds budget {budget}",
            )

            if offset == 0x06241C:
                found_mercenary_block = True

            for bub in b.get("bubbles", []):
                if "pages" in bub and bub["pages"] is not None:
                    pages = []
                    for p in bub["pages"]:
                        pages.extend(p.split("\f"))
                else:
                    pages = bub.get("text_ru", "").split("\f")
                for page_idx, page in enumerate(pages, 1):
                    lines = page.split("\n")
                    self.assertLessEqual(
                        len(lines),
                        3,
                        f"Block {block_id} bubble {bub.get('bubble_index')} page {page_idx} has {len(lines)} lines > 3: {page!r}",
                    )
                    for l in lines:
                        self.assertLessEqual(
                            len(l),
                            21,
                            f"Block {block_id} bubble {bub.get('bubble_index')} page {page_idx} line exceeds 21 chars ({len(l)}): {l!r}",
                        )
        self.assertTrue(found_mercenary_block, "Dialogue block at 0x06241C not found in catalog!")


class TestDryRunPipeline(unittest.TestCase):
    """Test patch_combat_dialogues with --dry-run flag."""

    def test_pipeline_dry_run(self):
        """Test running pipeline against disc image."""
        self.assertTrue(DEFAULT_BIN.is_file(), f"Binary not found: {DEFAULT_BIN}")

        # If translations file exists, test against it; otherwise test with mock catalog
        mock_cat_path = None
        if not DEFAULT_CATALOG.is_file():
            mock_cat = {
                "metadata": {"version": "1.0", "total_blocks": 1},
                "blocks": [
                    {
                        "id": "block_001",
                        "offset": "0x05F810",
                        "allocated_budget_bytes": 176,
                        "bubbles": [
                            {
                                "bubble_index": 1,
                                "speaker": "Лина",
                                "speaker_opcode": "0x9109",
                                "text_ru": "Тест сухой прогонки!",
                            }
                        ],
                    }
                ],
            }
            mock_cat_path = REPO_ROOT / "translations" / "_mock_combat_dialogues.json"
            mock_cat_path.write_text(json.dumps(mock_cat, ensure_ascii=False, indent=2), encoding="utf-8")

        cat_to_use = DEFAULT_CATALOG if DEFAULT_CATALOG.is_file() else mock_cat_path
        try:
            result = patch_combat_dialogues(
                bin_path=DEFAULT_BIN,
                catalog_path=cat_to_use,
                dry_run=True,
            )
            self.assertTrue(result["dry_run"])
            self.assertGreater(result["blocks_patched"], 0)
            self.assertLessEqual(result["compressed_font_size"], COMBAT_FONT_MAX_SIZE)
            self.assertEqual(result["entry_7_sectors"], 745)
            self.assertEqual(result["entry_142_sectors"], 23)
        finally:
            if mock_cat_path and mock_cat_path.is_file():
                mock_cat_path.unlink()

    def test_cli_invocation_dry_run(self):
        """Test CLI execution of patch_combat_dialogues.py with --dry-run and --verify."""
        import subprocess

        mock_cat_path = None
        if not DEFAULT_CATALOG.is_file():
            mock_cat = {
                "metadata": {"version": "1.0", "total_blocks": 1},
                "blocks": [
                    {
                        "id": "block_001",
                        "offset": "0x05F810",
                        "allocated_budget_bytes": 176,
                        "bubbles": [
                            {
                                "bubble_index": 1,
                                "speaker": "Лина",
                                "speaker_opcode": "0x9109",
                                "text_ru": "Тест CLI прогонки!",
                            }
                        ],
                    }
                ],
            }
            mock_cat_path = REPO_ROOT / "translations" / "_mock_cli_dialogues.json"
            mock_cat_path.write_text(json.dumps(mock_cat, ensure_ascii=False, indent=2), encoding="utf-8")

        cat_to_use = DEFAULT_CATALOG if DEFAULT_CATALOG.is_file() else mock_cat_path
        try:
            cmd = [
                "python3",
                str(REPO_ROOT / "tools" / "patch_combat_dialogues.py"),
                "--bin",
                str(DEFAULT_BIN),
                "--catalog",
                str(cat_to_use),
                "--dry-run",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"CLI dry-run failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
            self.assertIn("DRY RUN", res.stdout)
            self.assertIn("Invariants verified", res.stdout)
        finally:
            if mock_cat_path and mock_cat_path.is_file():
                mock_cat_path.unlink()

class TestCombatSystemStrings(unittest.TestCase):
    """Battle UI labels: 37 strings packed in 0x05F278..0x05F470, addressed via the table at 0x05F470."""

    def test_catalog_has_37_strings_in_table_order(self):
        texts = load_system_strings()
        self.assertEqual(len(texts), UI_POINTER_COUNT)
        self.assertEqual(texts[0], "СТАРТ")

    def test_pack_fits_region_and_dedupes(self):
        texts = load_system_strings()
        region, overflow, targets = pack_ui_strings(texts)
        self.assertEqual(len(region), OFFSET_SYSTEM_BUTTONS_END - OFFSET_SYSTEM_BUTTONS_START)
        self.assertEqual(len(targets), UI_POINTER_COUNT)
        self.assertEqual(overflow, b"")
        # identical labels share one record
        dup = [i for i, t in enumerate(texts) if texts.index(t) != i]
        for i in dup:
            self.assertEqual(targets[i], targets[texts.index(texts[i])])
        # every target starts right after a terminator (or at the region start)
        for t in targets:
            self.assertTrue(OFFSET_SYSTEM_BUTTONS_START <= t < OFFSET_SYSTEM_BUTTONS_END)
            if t > OFFSET_SYSTEM_BUTTONS_START:
                rel = t - OFFSET_SYSTEM_BUTTONS_START
                self.assertEqual(region[rel - 2 : rel], struct.pack("<H", OPCODE_BLOCK_END))

    def test_patch_combat_system_strings_rewrites_pointer_table(self):
        dummy_e7 = bytearray(b"\xAA" * (745 * 2048))
        canary_before = b"\x12\x34\x56\x78"
        dummy_e7[OFFSET_SYSTEM_BUTTONS_START - 4 : OFFSET_SYSTEM_BUTTONS_START] = canary_before
        canary_after = b"\xDE\xAD\xBE\xEF"
        table_end = OFFSET_TABLE2_START + 4 * UI_POINTER_COUNT
        dummy_e7[table_end : table_end + 4] = canary_after

        patched = patch_combat_system_strings(dummy_e7)
        self.assertEqual(patched[OFFSET_SYSTEM_BUTTONS_START - 4 : OFFSET_SYSTEM_BUTTONS_START], canary_before)
        self.assertEqual(patched[table_end : table_end + 4], canary_after)
        texts = load_system_strings()
        for k, text in enumerate(texts):
            ptr = struct.unpack_from("<I", patched, OFFSET_TABLE2_START + 4 * k)[0]
            target = ptr - UI_POINTER_BASE
            expected = encode_combat_dialogue_string(text, COMBAT_CHARMAP) + struct.pack("<H", OPCODE_BLOCK_END)
            self.assertEqual(bytes(patched[target : target + len(expected)]), expected, text)
        verify_combat_system_strings(bytes(patched))

    def test_overflow_goes_to_free_area_or_raises(self):
        dummy_e7 = bytearray(745 * 2048)
        long_texts = [f"ОЧЕНЬДЛИННАЯ{i:02d}" for i in range(UI_POINTER_COUNT)]
        patched = patch_combat_system_strings(dummy_e7, texts=long_texts)
        verify_combat_system_strings(bytes(patched), texts=long_texts)
        way_too_long = ["Ж" * 60 + f"{i:02d}" for i in range(UI_POINTER_COUNT)]
        with self.assertRaises(ValueError):
            patch_combat_system_strings(bytearray(745 * 2048), texts=way_too_long)

    def test_pipeline_alias(self):
        """Verify patch_combat_dialogues_pipeline alias is identical to patch_combat_dialogues."""
        self.assertIs(patch_combat_dialogues_pipeline, patch_combat_dialogues)

if __name__ == "__main__":
    unittest.main()
