#!/usr/bin/env python3
"""Unit tests for tools/patch_lore_cards.py.

Verifies:
1. TIM header and CLUT format specifications (magic 0x10, 4bpp, 16-color CLUT, transparent zero).
2. 4bpp pixel packing and nibble order.
3. Output dimensions (320x224 for overlays, 160x32 for banners).
4. Decompressibility and roundtrip fidelity via unt_lz.decompress.
5. Pillow text rendering of card overlays and banners.
6. Strict sector budget compliance for all 13 cards in data/lore_cards_ru.json.
7. UNT archive patching logic, zero-padding, and error handling on budget overflow.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.patch_lore_cards import (
    BANNER_HEIGHT,
    BANNER_WIDTH,
    DEFAULT_OPT_SPECS,
    DEFAULT_PROG_SPECS,
    OPT_CLUT_WORDS,
    OVERLAY_HEIGHT,
    OVERLAY_WIDTH,
    PROG_CLUT_WORDS,
    USER_SIZE,
    build_tim_4bpp,
    image_to_tim_4bpp,
    patch_lore_cards,
    patch_unt_entry,
    read_unt_index,
    render_banner,
    render_lore_card_text,
    rgba_to_4bpp_indices,
)

try:
    from localization.unt_lz import compress, decompress
except ImportError:
    # Add patch_repo
    sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
    from localization.unt_lz import compress, decompress


def parse_tim_header(tim_bytes: bytes) -> dict:
    """Helper to parse and validate TIM header fields."""
    assert len(tim_bytes) >= 8, "TIM file too short for header"
    magic = tim_bytes[:4]
    flag = int.from_bytes(tim_bytes[4:8], "little")
    pmode = flag & 7
    has_clut = bool(flag & 8)

    pos = 8
    clut_info = None
    if has_clut:
        clut_len = int.from_bytes(tim_bytes[pos : pos + 4], "little")
        clut_x = int.from_bytes(tim_bytes[pos + 4 : pos + 6], "little")
        clut_y = int.from_bytes(tim_bytes[pos + 6 : pos + 8], "little")
        clut_w = int.from_bytes(tim_bytes[pos + 8 : pos + 10], "little")
        clut_h = int.from_bytes(tim_bytes[pos + 10 : pos + 12], "little")
        colors = [
            int.from_bytes(tim_bytes[pos + 12 + i * 2 : pos + 14 + i * 2], "little")
            for i in range((clut_len - 12) // 2)
        ]
        clut_info = {
            "len": clut_len,
            "x": clut_x,
            "y": clut_y,
            "w": clut_w,
            "h": clut_h,
            "colors": colors,
        }
        pos += clut_len

    img_len = int.from_bytes(tim_bytes[pos : pos + 4], "little")
    img_x = int.from_bytes(tim_bytes[pos + 4 : pos + 6], "little")
    img_y = int.from_bytes(tim_bytes[pos + 6 : pos + 8], "little")
    img_w = int.from_bytes(tim_bytes[pos + 8 : pos + 10], "little")
    img_h = int.from_bytes(tim_bytes[pos + 10 : pos + 12], "little")
    pixel_data = tim_bytes[pos + 12 : pos + img_len]

    return {
        "magic": magic,
        "pmode": pmode,
        "has_clut": has_clut,
        "clut": clut_info,
        "img": {
            "len": img_len,
            "x": img_x,
            "y": img_y,
            "w": img_w,
            "h": img_h,
            "pixel_data_len": len(pixel_data),
        },
        "total_len": pos + img_len,
    }


class TestTimFormatAndClut:
    """1. TIM header and CLUT format tests."""

    def test_tim_header_magic_and_flags(self):
        packed = bytes((OVERLAY_WIDTH * OVERLAY_HEIGHT) // 2)
        tim = build_tim_4bpp(packed, OVERLAY_WIDTH, OVERLAY_HEIGHT, PROG_CLUT_WORDS)
        parsed = parse_tim_header(tim)

        assert parsed["magic"] == b"\x10\x00\x00\x00"
        assert parsed["pmode"] == 0  # 4bpp
        assert parsed["has_clut"] is True

    def test_clut_structure_and_transparency(self):
        packed = bytes((OVERLAY_WIDTH * OVERLAY_HEIGHT) // 2)
        tim = build_tim_4bpp(packed, OVERLAY_WIDTH, OVERLAY_HEIGHT, PROG_CLUT_WORDS, clut_x=0, clut_y=480)
        parsed = parse_tim_header(tim)

        clut = parsed["clut"]
        assert clut is not None
        assert clut["len"] == 44  # 12 header + 32 color data
        assert clut["w"] == 16
        assert clut["h"] == 1
        assert clut["x"] == 0
        assert clut["y"] == 480
        assert len(clut["colors"]) == 16
        # Color 0 must be transparent black 0x0000
        assert clut["colors"][0] == 0x0000
        # Color 1 is white text core 0x7FFF
        assert clut["colors"][1] == 0x7FFF
        # Color 15 is dark shadow 0x0842
        assert clut["colors"][15] == 0x0842


class TestPixelPacking:
    """2. 4bpp pixel packing and nibble order."""

    def test_nibble_packing_order(self):
        # Create a tiny 4x1 image with 4 known pixels
        # Pixels: 0 (trans), 1 (white), 15 (shadow), 8 (mid-gray)
        # Expected packed bytes:
        # byte 0: (pixel[1] << 4) | (pixel[0] & 0xF) = (1 << 4) | 0 = 0x10
        # byte 1: (pixel[3] << 4) | (pixel[2] & 0xF) = (8 << 4) | 15 = 0x8F
        im = Image.new("RGBA", (4, 1), (0, 0, 0, 0))
        pixels = [
            (0, 0, 0, 0),        # Index 0
            (255, 255, 255, 255), # Index 1 (white)
            (16, 16, 16, 255),   # Index 15 (dark gray / shadow)
            (128, 128, 128, 255), # Index 8 (mid gray)
        ]
        im.putdata(pixels)

        packed = rgba_to_4bpp_indices(im, PROG_CLUT_WORDS, alpha_threshold=64)
        assert len(packed) == 2
        assert packed[0] == 0x10
        assert packed[1] == 0x8F

        # Unpack and verify roundtrip
        unpacked_0 = packed[0] & 0x0F
        unpacked_1 = (packed[0] >> 4) & 0x0F
        unpacked_2 = packed[1] & 0x0F
        unpacked_3 = (packed[1] >> 4) & 0x0F

        assert (unpacked_0, unpacked_1, unpacked_2, unpacked_3) == (0, 1, 15, 8)


class TestOutputDimensions:
    """3. Output dimensions verification (320x224 and 160x32)."""

    def test_overlay_dimensions_and_sizes(self):
        card_sample = {
            "id": "test_card",
            "title_main": "[Т] Тестовая карта",
            "title_sub": "(Тестовое описание)",
            "lines": ["Первая строка теста.", "Вторая строка текста."],
        }
        im = render_lore_card_text(card_sample)
        assert im.size == (OVERLAY_WIDTH, OVERLAY_HEIGHT)
        assert im.mode == "RGBA"

        tim = image_to_tim_4bpp(im, PROG_CLUT_WORDS, vram_x=0, vram_y=0)
        # Expected TIM size: 8 (header) + 44 (clut) + 12 (img header) + 320*224/2 (pixel data)
        # 8 + 44 + 12 + 35840 = 35904 bytes
        assert len(tim) == 35904

        parsed = parse_tim_header(tim)
        assert parsed["img"]["w"] == 80  # 80 16-bit words = 320 4bpp pixels
        assert parsed["img"]["h"] == 224
        assert parsed["img"]["pixel_data_len"] == 35840

    def test_banner_dimensions_and_sizes(self):
        im = render_banner("ТЕСТОВЫЙ БАННЕР")
        assert im.size == (BANNER_WIDTH, BANNER_HEIGHT)
        assert im.mode == "RGBA"

        tim = image_to_tim_4bpp(
            im, OPT_CLUT_WORDS, vram_x=576, vram_y=296, clut_x=0, clut_y=507
        )
        # Expected TIM size: 8 (header) + 44 (clut) + 12 (img header) + 160*32/2 (pixel data)
        # 8 + 44 + 12 + 2560 = 2624 bytes
        assert len(tim) == 2624

        parsed = parse_tim_header(tim)
        assert parsed["img"]["w"] == 40  # 40 16-bit words = 160 4bpp pixels
        assert parsed["img"]["h"] == 32
        assert parsed["img"]["pixel_data_len"] == 2560


class TestDecompressibility:
    """4. Decompressibility via unt_lz.decompress."""

    def test_unt_lz_compression_roundtrip(self):
        card_sample = {
            "id": "naga",
            "title_main": "[С] Нага Белая Змея",
            "title_sub": "(Нага Змеюка)",
            "lines": [
                "Была напарницей Лины до встречи с Гаури.",
                "Самопровозглашённая величайшая и сильнейшая соперница Лины.",
            ],
        }
        im = render_lore_card_text(card_sample)
        tim_original = image_to_tim_4bpp(im, PROG_CLUT_WORDS)

        compressed = compress(tim_original)
        assert compressed[0] == 1  # LZ mode 1
        decomp_len = int.from_bytes(compressed[1:5], "little")
        assert decomp_len == len(tim_original)

        decompressed, bytes_read = decompress(compressed)
        assert bytes_read == len(compressed)
        assert decompressed == tim_original
        assert len(decompressed) == 35904


class TestRendering:
    """5. Visual element rendering tests."""

    def test_rendered_overlay_has_content(self):
        card_sample = {
            "id": "sample",
            "title_main": "[Л] Лина Инверс",
            "title_sub": "(Волшебница)",
            "lines": ["Строка 1", "Строка 2"],
        }
        im = render_lore_card_text(card_sample)
        # Verify that the image is not completely transparent
        colors = im.getcolors(maxcolors=10000)
        assert colors is not None
        assert len(colors) > 1  # Contains transparent background + drawn text/outline

    def test_rendered_banner_has_content(self):
        im = render_banner("ЛИНА ИНВЕРС")
        colors = im.getcolors(maxcolors=10000)
        assert colors is not None
        assert len(colors) > 1

    def test_banner_autoscale_long_title(self):
        # Long title should not crash or overflow bounds
        im = render_banner("СВОЙСТВА ДРЕВНИХ ЗАКЛИНАНИЙ РЕЗАРИУМА")
        assert im.size == (BANNER_WIDTH, BANNER_HEIGHT)


class TestSectorBudgetsAll13Cards:
    """6. All 13 Russian lore cards budget and sector compliance."""

    def test_all_cards_within_sector_limits(self):
        json_path = REPO_ROOT / "data" / "lore_cards_ru.json"
        assert json_path.exists(), f"Dataset {json_path} missing"

        with json_path.open("r", encoding="utf-8") as f:
            cards = json.load(f)

        assert len(cards) == 13, f"Expected exactly 13 cards, found {len(cards)}"

        for card in cards:
            cid = card["id"]
            pe = card["prog_entry"]
            assert pe in DEFAULT_PROG_SPECS, f"Card {cid} prog_entry {pe} not in default specs"

            spec_p = DEFAULT_PROG_SPECS[pe]
            budget_p = spec_p["sectors"] * USER_SIZE

            # Render, encode, compress
            im_text = render_lore_card_text(card)
            tim_p = image_to_tim_4bpp(
                im_text,
                clut_words=PROG_CLUT_WORDS,
                vram_x=spec_p["vram_x"],
                vram_y=spec_p["vram_y"],
                clut_x=spec_p["clut_x"],
                clut_y=spec_p["clut_y"],
            )
            comp_p = compress(tim_p)

            # Assert compression fits within budget
            assert len(comp_p) <= budget_p, (
                f"Card {cid} (entry {pe}) compressed size {len(comp_p)} exceeds "
                f"sector budget {budget_p} ({spec_p['sectors']} sectors)"
            )
            margin = budget_p - len(comp_p)
            assert margin > 0, f"Card {cid} has non-positive safety margin: {margin}"

            # Check banner if present
            oe = card.get("opt_entry")
            if oe is not None:
                assert oe in DEFAULT_OPT_SPECS, f"Card {cid} opt_entry {oe} not in default specs"
                spec_o = DEFAULT_OPT_SPECS[oe]
                budget_o = spec_o["sectors"] * USER_SIZE
                im_banner = render_banner(card["banner_opt"])
                tim_o = image_to_tim_4bpp(
                    im_banner,
                    clut_words=OPT_CLUT_WORDS,
                    vram_x=spec_o["vram_x"],
                    vram_y=spec_o["vram_y"],
                    clut_x=spec_o["clut_x"],
                    clut_y=spec_o["clut_y"],
                )
                assert len(tim_o) <= budget_o, (
                    f"Card {cid} banner size {len(tim_o)} exceeds budget {budget_o}"
                )


class TestArchivePatching:
    """7. UNT archive patching and error handling."""

    def test_mock_unt_patch_and_padding(self):
        # Create a mock UNT archive with 3 entries:
        # Sector 0: table
        # Entry 0: start=1, count=2 (sectors 1..2, 4096 bytes)
        # Entry 1: start=3, count=4 (sectors 3..6, 8192 bytes)
        # Entry 2: start=7, count=3 (sectors 7..9, 6144 bytes)
        total_sectors = 10
        archive = bytearray(total_sectors * USER_SIZE)

        # Build sector 0 table
        entries = [(1, 2), (3, 4), (7, 3)]
        for i, (start, count) in enumerate(entries):
            archive[i * 4 : i * 4 + 2] = start.to_bytes(2, "little")
            archive[i * 4 + 2 : i * 4 + 4] = count.to_bytes(2, "little")

        # Patch Entry 1 (offset = 3 * 2048 = 6144, size = 4 * 2048 = 8192)
        payload = b"TEST_PAYLOAD_DATA" * 50  # 850 bytes
        offset, allocated, payload_len = patch_unt_entry(archive, 1, payload)

        assert offset == 3 * USER_SIZE
        assert allocated == 4 * USER_SIZE
        assert payload_len == len(payload)

        # Check that data was written and padded with zeros
        written = archive[offset : offset + allocated]
        assert written[: len(payload)] == payload
        assert written[len(payload) :] == b"\x00" * (allocated - len(payload))

    def test_patch_unt_entry_overflow_raises(self):
        archive = bytearray(4 * USER_SIZE)
        # Entry 0: start=1, count=1 (2048 bytes)
        archive[0:2] = (1).to_bytes(2, "little")
        archive[2:4] = (1).to_bytes(2, "little")

        oversized_payload = bytes(2049)
        with pytest.raises(ValueError, match="exceeds allocated sector budget"):
            patch_unt_entry(archive, 0, oversized_payload)

    def test_patch_unt_entry_index_error(self):
        archive = bytearray(2 * USER_SIZE)
        # Entry 0: start=1, count=1
        archive[0:2] = (1).to_bytes(2, "little")
        archive[2:4] = (1).to_bytes(2, "little")

        with pytest.raises(IndexError, match="out of range"):
            patch_unt_entry(archive, 5, b"data")
