#!/usr/bin/env python3
"""Unit tests for Slayers Royal Russian lore cards (4bpp split cards & 8bpp combined cards).

Covers:
1. All 13 cards: 8bpp combined format for 37, 38, 41 and 4bpp format for 10 split cards.
2. Decompressed size verification (72,224 bytes for 8bpp, 35,904 bytes for 4bpp).
3. OPT.UNT Banner 185 existence, specifications, and size limit.
4. Sector budgets and LZ compression for all 13 cards.
5. Decompression roundtrip verification.
6. Target disc image verification if available.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.patch_lore_cards import (
    BANNER_HEIGHT,
    BANNER_WIDTH,
    COMBINED_8BPP_ENTRIES,
    DEFAULT_OPT_SPECS,
    DEFAULT_PROG_SPECS,
    OPT_CLUT_WORDS,
    OVERLAY_HEIGHT,
    OVERLAY_WIDTH,
    PROG_CLUT_WORDS,
    SPLIT_CARD_ENTRIES,
    USER_SIZE,
    build_tim_4bpp,
    build_tim_8bpp,
    image_to_tim_4bpp,
    parse_iso_dir,
    read_extent,
    read_sector,
    read_unt_index,
    render_banner,
    render_combined_card_8bpp,
    render_lore_card_text,
)

try:
    from localization.unt_lz import compress, decompress
except ImportError:
    sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
    from localization.unt_lz import compress, decompress


def parse_tim_header(tim_bytes: bytes) -> dict:
    """Parse and validate TIM header fields."""
    assert len(tim_bytes) >= 8, f"TIM too short: {len(tim_bytes)} bytes"
    assert tim_bytes[:4] == b"\x10\x00\x00\x00", "Missing TIM magic 0x10"
    flag = int.from_bytes(tim_bytes[4:8], "little")
    pmode = flag & 7
    has_clut = bool(flag & 8)

    pos = 8
    clut = None
    if has_clut:
        clut_len = int.from_bytes(tim_bytes[pos : pos + 4], "little")
        clut_x = int.from_bytes(tim_bytes[pos + 4 : pos + 6], "little")
        clut_y = int.from_bytes(tim_bytes[pos + 6 : pos + 8], "little")
        clut_w = int.from_bytes(tim_bytes[pos + 8 : pos + 10], "little")
        clut_h = int.from_bytes(tim_bytes[pos + 10 : pos + 12], "little")
        colors = []
        for i in range(12, clut_len, 2):
            colors.append(int.from_bytes(tim_bytes[pos + i : pos + i + 2], "little"))
        clut = {
            "x": clut_x,
            "y": clut_y,
            "w": clut_w,
            "h": clut_h,
            "len": clut_len,
            "colors": colors,
        }
        pos += clut_len

    img_len = int.from_bytes(tim_bytes[pos : pos + 4], "little")
    img_x = int.from_bytes(tim_bytes[pos + 4 : pos + 6], "little")
    img_y = int.from_bytes(tim_bytes[pos + 6 : pos + 8], "little")
    img_w = int.from_bytes(tim_bytes[pos + 8 : pos + 10], "little")
    img_h = int.from_bytes(tim_bytes[pos + 10 : pos + 12], "little")

    bpp = {0: 4, 1: 8, 2: 16, 3: 24}.get(pmode, 0)
    pixel_w = img_w * (4 if pmode == 0 else 2 if pmode == 1 else 1)

    return {
        "pmode": pmode,
        "bpp": bpp,
        "has_clut": has_clut,
        "clut": clut,
        "img": {
            "x": img_x,
            "y": img_y,
            "w": img_w,
            "h": img_h,
            "pixel_w": pixel_w,
            "pixel_h": img_h,
            "len": img_len,
        },
        "total_len": pos + img_len,
    }


@pytest.fixture(scope="module")
def lore_cards_data():
    primary_path = REPO_ROOT / "translations" / "lore_cards_ru.json"
    fallback_path = REPO_ROOT / "data" / "lore_cards_ru.json"
    json_path = primary_path if primary_path.exists() else fallback_path
    assert json_path.exists(), f"Dataset {json_path} missing"
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    cards = data["cards"] if isinstance(data, dict) and "cards" in data else data
    assert len(cards) == 13, f"Expected 13 cards, found {len(cards)}"
    return cards


class TestCardCatalogAndSpecs:
    """Validate card classification and catalog coverage."""

    def test_all_13_cards_categorized(self, lore_cards_data):
        assert len(COMBINED_8BPP_ENTRIES) == 3
        assert COMBINED_8BPP_ENTRIES == {37, 38, 41}
        assert len(SPLIT_CARD_ENTRIES) == 10
        assert SPLIT_CARD_ENTRIES == {32, 34, 36, 40, 43, 45, 47, 49, 51, 53}

        for card in lore_cards_data:
            pe = card["prog_entry"]
            assert pe in DEFAULT_PROG_SPECS, f"Entry {pe} missing from specs"
            spec = DEFAULT_PROG_SPECS[pe]
            if pe in COMBINED_8BPP_ENTRIES:
                assert spec["type"] == "combined_8bpp"
                assert spec["bpp"] == 8
            else:
                assert spec["type"] == "split_card"
                assert spec["bpp"] == 4


class TestCardFormatsAndDecompressedSizes:
    """Validate decompressed sizes: 72,224 B for 8bpp and 35,904 B for 4bpp."""

    def test_combined_8bpp_cards_format_and_size(self, lore_cards_data):
        combined_cards = [c for c in lore_cards_data if c["prog_entry"] in COMBINED_8BPP_ENTRIES]
        assert len(combined_cards) == 3

        for card in combined_cards:
            pe = card["prog_entry"]
            tim_bytes = render_combined_card_8bpp(card)

            # Decompressed size MUST be exactly 72,224 bytes
            assert len(tim_bytes) == 72224, (
                f"Combined 8bpp card {card['id']} (entry {pe}) size is {len(tim_bytes)}, expected 72224"
            )

            hdr = parse_tim_header(tim_bytes)
            assert hdr["pmode"] == 1, f"Expected pmode=1 (8bpp), got {hdr['pmode']}"
            assert hdr["bpp"] == 8
            assert hdr["has_clut"] is True
            assert hdr["clut"]["len"] == 524
            assert len(hdr["clut"]["colors"]) == 256
            assert hdr["img"]["pixel_w"] == 320
            assert hdr["img"]["pixel_h"] == 224
            assert hdr["img"]["w"] == 160  # 160 halfwords per scanline

    def test_split_4bpp_cards_format_and_size(self, lore_cards_data):
        split_cards = [c for c in lore_cards_data if c["prog_entry"] in SPLIT_CARD_ENTRIES]
        assert len(split_cards) == 10

        for card in split_cards:
            pe = card["prog_entry"]
            im = render_lore_card_text(card)
            tim_bytes = image_to_tim_4bpp(im, PROG_CLUT_WORDS)

            # Decompressed size MUST be exactly 35,904 bytes
            assert len(tim_bytes) == 35904, (
                f"Split 4bpp card {card['id']} (entry {pe}) size is {len(tim_bytes)}, expected 35904"
            )

            hdr = parse_tim_header(tim_bytes)
            assert hdr["pmode"] == 0, f"Expected pmode=0 (4bpp), got {hdr['pmode']}"
            assert hdr["bpp"] == 4
            assert hdr["has_clut"] is True
            assert hdr["clut"]["len"] == 44
            assert len(hdr["clut"]["colors"]) == 16
            assert hdr["img"]["pixel_w"] == 320
            assert hdr["img"]["pixel_h"] == 224
            assert hdr["img"]["w"] == 80  # 80 halfwords per scanline


class TestBanner185:
    """Validate OPT.UNT banner 185 for card 37 (map_controls)."""

    def test_banner_185_spec_exists(self):
        assert 185 in DEFAULT_OPT_SPECS, "OPT entry 185 missing from DEFAULT_OPT_SPECS"
        spec = DEFAULT_OPT_SPECS[185]
        assert spec["id"] == "map_controls"
        assert spec["sectors"] == 2
        assert spec["vram_x"] == 576
        assert spec["vram_y"] == 392
        assert spec["clut_x"] == 0
        assert spec["clut_y"] == 507

    def test_banner_185_in_lore_cards_ru(self, lore_cards_data):
        card37 = next(c for c in lore_cards_data if c["id"] == "map_controls")
        assert card37["opt_entry"] == 185, f"Expected opt_entry 185, got {card37.get('opt_entry')}"
        assert card37["banner_opt"] == "УПРАВЛЕНИЕ"

    def test_banner_185_tim_size_and_budget(self):
        spec = DEFAULT_OPT_SPECS[185]
        budget = spec["sectors"] * USER_SIZE  # 4096 bytes
        im = render_banner("УПРАВЛЕНИЕ")
        assert im.size == (BANNER_WIDTH, BANNER_HEIGHT)

        tim_bytes = image_to_tim_4bpp(
            im,
            clut_words=OPT_CLUT_WORDS,
            vram_x=spec["vram_x"],
            vram_y=spec["vram_y"],
            clut_x=spec["clut_x"],
            clut_y=spec["clut_y"],
        )
        assert len(tim_bytes) <= budget, f"Banner 185 size {len(tim_bytes)} exceeds budget {budget}"
        hdr = parse_tim_header(tim_bytes)
        assert hdr["bpp"] == 4
        assert hdr["img"]["pixel_w"] == 160
        assert hdr["img"]["pixel_h"] == 32


class TestSectorBudgetsAndCompression:
    """Validate all 13 cards fit within allocated sector budgets and compress/decompress cleanly."""

    def test_all_cards_within_sector_budgets(self, lore_cards_data):
        for card in lore_cards_data:
            cid = card["id"]
            pe = card["prog_entry"]
            spec = DEFAULT_PROG_SPECS[pe]
            budget = spec["sectors"] * USER_SIZE

            if pe in COMBINED_8BPP_ENTRIES:
                tim = render_combined_card_8bpp(card)
                assert len(tim) == 72224
            else:
                im = render_lore_card_text(card)
                tim = image_to_tim_4bpp(
                    im,
                    clut_words=PROG_CLUT_WORDS,
                    vram_x=spec["vram_x"],
                    vram_y=spec["vram_y"],
                    clut_x=spec["clut_x"],
                    clut_y=spec["clut_y"],
                )
                assert len(tim) == 35904

            comp = compress(tim)
            assert len(comp) <= budget, (
                f"Card {cid} (entry {pe}) compressed size {len(comp)} exceeds budget {budget} ({spec['sectors']} sectors)"
            )
            margin = budget - len(comp)
            assert margin > 0, f"Card {cid} margin non-positive: {margin}"

    def test_compression_roundtrip_8bpp_and_4bpp(self, lore_cards_data):
        # Roundtrip 8bpp card (entry 37)
        card37 = next(c for c in lore_cards_data if c["prog_entry"] == 37)
        tim_8bpp = render_combined_card_8bpp(card37)
        comp_8bpp = compress(tim_8bpp)
        assert comp_8bpp[0] == 1  # Mode 1 LZ
        dec_len_8bpp = int.from_bytes(comp_8bpp[1:5], "little")
        assert dec_len_8bpp == 72224
        decomp_8bpp, bytes_read_8bpp = decompress(comp_8bpp)
        assert bytes_read_8bpp == len(comp_8bpp)
        assert decomp_8bpp == tim_8bpp
        assert len(decomp_8bpp) == 72224

        # Roundtrip 4bpp card (entry 32)
        card32 = next(c for c in lore_cards_data if c["prog_entry"] == 32)
        im_4bpp = render_lore_card_text(card32)
        tim_4bpp = image_to_tim_4bpp(im_4bpp, PROG_CLUT_WORDS)
        comp_4bpp = compress(tim_4bpp)
        assert comp_4bpp[0] == 1
        dec_len_4bpp = int.from_bytes(comp_4bpp[1:5], "little")
        assert dec_len_4bpp == 35904
        decomp_4bpp, bytes_read_4bpp = decompress(comp_4bpp)
        assert bytes_read_4bpp == len(comp_4bpp)
        assert decomp_4bpp == tim_4bpp
        assert len(decomp_4bpp) == 35904


class TestPatchedDiscImageVerification:
    """Verify patched target disc image if present on system."""

    def test_patched_disc_entries(self):
        disc_path = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
        if not disc_path.exists():
            pytest.skip("Target disc image slayers_royal_ru.bin not present")

        pvd = read_sector(disc_path, 16)
        root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
        root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
        root_dir = parse_iso_dir(disc_path, root_lba, root_size)

        prog_bytes = read_extent(disc_path, *root_dir["PROG.UNT"])
        opt_bytes = read_extent(disc_path, *root_dir["OPT.UNT"])
        prog_idx = read_unt_index(prog_bytes)
        opt_idx = read_unt_index(opt_bytes)

        # 1. Verify combined 8bpp cards (37, 38, 41)
        for pe in [37, 38, 41]:
            e = prog_idx[pe]
            raw = prog_bytes[e.offset : e.offset + e.size]
            dec, _ = decompress(raw)
            assert len(dec) == 72224, f"Disc entry {pe} decompressed size {len(dec)} != 72224"
            info = parse_tim_header(dec)
            assert info["pmode"] == 1
            assert info["bpp"] == 8
            assert info["img"]["pixel_w"] == 320
            assert info["img"]["pixel_h"] == 224

        # 2. Verify split 4bpp cards
        for pe in [32, 34, 36, 40, 43, 45, 47, 49, 51, 53]:
            e = prog_idx[pe]
            raw = prog_bytes[e.offset : e.offset + e.size]
            dec, _ = decompress(raw)
            assert len(dec) == 35904, f"Disc entry {pe} decompressed size {len(dec)} != 35904"
            info = parse_tim_header(dec)
            assert info["pmode"] == 0
            assert info["bpp"] == 4
            assert info["img"]["pixel_w"] == 320
            assert info["img"]["pixel_h"] == 224

        # 3. Verify OPT entry 185
        oe = opt_idx[185]
        raw_185 = opt_bytes[oe.offset : oe.offset + oe.size]
        info_185 = parse_tim_header(raw_185)
        assert info_185["pmode"] == 0
        assert info_185["bpp"] == 4
        assert info_185["img"]["pixel_w"] == 160
        assert info_185["img"]["pixel_h"] == 32
        assert info_185["img"]["x"] == 576
        assert info_185["img"]["y"] == 392
