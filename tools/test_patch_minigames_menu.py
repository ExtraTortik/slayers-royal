#!/usr/bin/env python3
"""Unit tests for tools/patch_minigames_menu.py.

Validates:
1. Catalog loading and schema validation:
   - Correct JSON structure and required metadata.
   - All 17 required wooden plank text elements present.
   - Field validations (entry, sector_offset, dimensions, font_size, color_index).
   - Error handling for invalid catalogs and schema violations.
2. Font and TIM 4bpp structure:
   - Font discovery of PressStart2P.ttf.
   - Text mask rendering and bounds verification for all 17 items.
   - 4bpp pixel packing and nibble ordering (low nibble left, high nibble right).
   - PS1 TIM binary format assembly (magic 0x10, flag 0x08, CLUT, image header, zero-padding to 2048 bytes).
   - Parsing TIM and decoding to RGBA.
3. EDC/ECC calculation and sector patching:
   - Mode 2 Form 1 EDC checksum computation.
   - Mode 2 Form 1 ECC P/Q parity computation.
   - Sector patching with replace_extent_in_place on mock disc.
   - Verification of production disc image sectors at LBA 228506..228522.
4. Composite preview image generation:
   - Composite preview image created at data/preview_minigames_menu_ru.png.
   - Dimensions (320x540), RGBA format, and valid pixel content.
"""

from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile

from PIL import Image, ImageFont
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
for p in (REPO_ROOT, PATCH_REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools.patch_minigames_menu import (
    DEFAULT_CATALOG,
    DEFAULT_FONT_PATH,
    DEFAULT_TARGET_BIN,
    OPT_ARCHIVE_LBA,
    RAW_SECTOR_SIZE,
    REQUIRED_MENU_KEYS,
    USER_DATA_OFFSET,
    USER_DATA_SIZE,
    build_4bpp_pixel_data,
    build_tim,
    find_font,
    generate_preview,
    generate_tim_entry,
    load_minigames_menu_catalog,
    parse_tim,
    patch_menu_sector,
    patch_minigames_menu,
    read_raw_sector,
    read_sector_extent,
    render_text_mask,
    render_text_mask_with_tracking,
    tim_to_rgba_image,
    verify_minigames_menu,
)

try:
    from patch_repo.localization.disc import CdChecksums
except ImportError:
    from localization.disc import CdChecksums


class TestCatalogLoadingAndSchema:
    """Validate translations/minigames_menu_ru.json schema and item specifications."""

    def test_catalog_file_exists_and_loads(self):
        assert DEFAULT_CATALOG.is_file(), f"Missing catalog file: {DEFAULT_CATALOG}"
        cat = load_minigames_menu_catalog(DEFAULT_CATALOG)
        assert isinstance(cat, dict)
        assert "metadata" in cat
        assert "menu_items" in cat

    def test_catalog_metadata(self):
        cat = load_minigames_menu_catalog(DEFAULT_CATALOG)
        meta = cat["metadata"]
        assert meta.get("archive") == "OPT.UNT"
        assert meta.get("archive_lba") == 226000
        assert meta.get("total_entries") == 17
        assert meta.get("format") == "4bpp TIM"

    def test_all_seventeen_keys_present(self):
        cat = load_minigames_menu_catalog(DEFAULT_CATALOG)
        items = cat["menu_items"]
        assert len(items) == 17
        for k in REQUIRED_MENU_KEYS:
            assert k in items, f"Missing required menu key: {k}"

    def test_exact_entry_and_sector_offsets(self):
        cat = load_minigames_menu_catalog(DEFAULT_CATALOG)
        items = cat["menu_items"]

        expected_specs = {
            "header": (152, 2506, 120, 24, "МИНИ-ИГРЫ", 15),
            "nav_prompt": (153, 2507, 128, 16, "ВЫБОР: D-PAD", 15),
            "action_prompt": (154, 2508, 240, 16, "O: ВЫБОР   X: НАЗАД", 15),
            "knight_monster_line1": (155, 2509, 112, 32, "РЫЦАРЬ", 15),
            "knight_monster_line2": (156, 2510, 112, 32, "И МОНСТР", 15),
            "slot_machine_line1": (157, 2511, 112, 32, "СЛОТ", 15),
            "slot_machine_line2": (158, 2512, 112, 32, "МАШИНА", 15),
            "eating_contest_line1": (159, 2513, 112, 32, "ЛИНА И ГАУРИ", 15),
            "eating_contest_line2": (160, 2514, 112, 32, "ОБЕД", 15),
            "amelia_climb_line1": (161, 2515, 112, 32, "АМЕЛИЯ", 15),
            "amelia_climb_line2": (162, 2516, 112, 32, "ПРЫЖОК", 15),
            "naga_laugh_line1": (163, 2517, 112, 32, "НАГА", 15),
            "naga_laugh_line2": (164, 2518, 112, 32, "СМЕХ", 15),
            "slayers_quiz_line1": (165, 2519, 112, 32, "СЛЕЙЕРС", 15),
            "slayers_quiz_line2": (166, 2520, 112, 32, "КВИЗ", 15),
            "bandit_bullying_line1": (167, 2521, 112, 32, "ОТСТРЕЛ", 15),
            "bandit_bullying_line2": (168, 2522, 112, 32, "БАНДИТОВ", 15),
        }

        for k, (entry, sec_off, w, h, text, ci) in expected_specs.items():
            it = items[k]
            assert it["entry"] == entry
            assert it["sector_offset"] == sec_off
            assert it["width"] == w
            assert it["height"] == h
            assert it["text_ru"] == text
            assert it["color_index"] == ci
            assert it["width"] % 4 == 0
            assert it["font_size"] > 0

            assert "tracking" in it, f"Item {k} missing 'tracking' field"
            assert isinstance(it["tracking"], int) and it["tracking"] >= 0
    def test_all_seventeen_items_color_index_15(self):
        cat = load_minigames_menu_catalog(DEFAULT_CATALOG)
        items = cat["menu_items"]
        assert len(items) == 17
        for k, item in items.items():
            assert item["color_index"] == 15, f"Item {k} color_index={item['color_index']} != 15"

    def test_schema_error_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_minigames_menu_catalog(Path("/non/existent/catalog.json"))

    def test_schema_error_missing_key(self, tmp_path):
        bad_doc = {"menu_items": {}}
        bad_json = tmp_path / "bad.json"
        bad_json.write_text(json.dumps(bad_doc), encoding="utf-8")
        with pytest.raises(ValueError, match="Missing required menu item"):
            load_minigames_menu_catalog(bad_json)

    def test_schema_error_missing_field(self, tmp_path):
        bad_doc = {"menu_items": {"header": {"entry": 152}}}
        bad_json = tmp_path / "bad_field.json"
        bad_json.write_text(json.dumps(bad_doc), encoding="utf-8")
        with pytest.raises(ValueError, match="missing required field"):
            load_minigames_menu_catalog(bad_json)
    def test_schema_error_invalid_width(self, tmp_path):
        cat = load_minigames_menu_catalog(DEFAULT_CATALOG)
        cat["menu_items"]["header"]["width"] = 121  # not multiple of 4
        bad_json = tmp_path / "invalid_width.json"
        bad_json.write_text(json.dumps(cat), encoding="utf-8")
        with pytest.raises(ValueError, match="multiple of 4"):
            load_minigames_menu_catalog(bad_json)

    def test_schema_error_invalid_color_index(self, tmp_path):
        cat = load_minigames_menu_catalog(DEFAULT_CATALOG)
        cat["menu_items"]["header"]["color_index"] = 16  # out of 0..15
        bad_json = tmp_path / "invalid_ci.json"
        bad_json.write_text(json.dumps(cat), encoding="utf-8")
        with pytest.raises(ValueError, match="color_index"):
            load_minigames_menu_catalog(bad_json)


class TestTextRenderingAndTimFormat:
    """Validate font discovery, text mask rendering, and 4bpp TIM binary formatting."""

    def test_find_font(self):
        font_p = find_font()
        assert font_p.is_file()
        assert font_p.name == "PressStart2P.ttf"

    def test_render_all_items_masks_within_bounds(self):
        font_p = find_font()
        cat = load_minigames_menu_catalog(DEFAULT_CATALOG)
        for k, item in cat["menu_items"].items():
            mask = render_text_mask(
                item["text_ru"],
                font_p,
                item["font_size"],
                item["width"],
                item["height"],
                tracking=item.get("tracking", 0),
            )
            assert mask.size == (item["width"], item["height"])
            bbox = mask.getbbox()
            assert bbox is not None, f"Item {k} rendered completely empty"
            # Ensure text bounding box stays within dimensions
            assert 0 <= bbox[0] < bbox[2] <= item["width"], f"Item {k} X-overflow: bbox={bbox}"
            assert 0 <= bbox[1] < bbox[3] <= item["height"], f"Item {k} Y-overflow: bbox={bbox}"
            # Ensure 1px bevel at (x+1, y+1) stays within dimensions
            assert bbox[2] + 1 <= item["width"], f"Item {k} bevel X-overflow: bbox={bbox}"
            assert bbox[3] + 1 <= item["height"], f"Item {k} bevel Y-overflow: bbox={bbox}"

    def test_render_text_mask_with_tracking(self):
        font_p = find_font()
        font_obj = ImageFont.truetype(str(font_p), 8)
        text = "МИНИ-ИГРЫ"
        m0 = render_text_mask_with_tracking(text, font_obj, tracking=0)
        m1 = render_text_mask_with_tracking(text, font_obj, tracking=1)
        m2 = render_text_mask_with_tracking(text, font_obj, tracking=2)

        # With 9 characters, there are 8 gaps
        assert m1.size[0] == m0.size[0] + 8
        assert m2.size[0] == m0.size[0] + 16

        # Centered rendering with explicit width and height
        mc = render_text_mask_with_tracking(text, font_obj, tracking=2, width=120, height=24)
        assert mc.size == (120, 24)
        bbox = mc.getbbox()
        assert bbox is not None
        assert bbox[0] > 0 and bbox[2] < 120
        assert bbox[1] > 0 and bbox[3] < 24

    def test_generate_tim_entry_all_seventeen_items(self):
        font_p = find_font()
        cat = load_minigames_menu_catalog(DEFAULT_CATALOG)
        for k, item in cat["menu_items"].items():
            tim_sec = generate_tim_entry(item, font=font_p)
            assert len(tim_sec) == USER_DATA_SIZE
            parsed = parse_tim(tim_sec)
            assert parsed["pmode"] == 0
            assert parsed["has_clut"] is True
            assert parsed["pixel_width"] == item["width"]
            assert parsed["pixel_height"] == item["height"]

            # Verify CLUT Color 15 is 0x8000
            c15 = struct.unpack_from("<H", parsed["clut"]["data"], 30)[0]
            assert c15 == 0x8000, f"Item {k} Color 15 is 0x{c15:04X}, expected 0x8000"

            # Verify palette indices: strictly 0 (bg), 1 (bevel), 15 (core)
            indices = set()
            for b in parsed["pixel_data"]:
                indices.add(b & 0x0F)
                indices.add((b >> 4) & 0x0F)
            assert indices == {0, 1, 15}, f"Item {k} unexpected indices: {indices}"

            # Verify trailing sector padding is zeroed
            trailing = tim_sec[parsed["total_tim_len"] :]
            assert len(trailing) > 0
            assert set(trailing) == {0}

    def test_generate_tim_entry_bevel_offset_pattern(self):
        # Test with synthetic 1-char item to verify exact (x, y) core and (x+1, y+1) bevel
        item_spec = {
            "text_ru": "А",
            "width": 16,
            "height": 16,
            "font_size": 8,
            "tracking": 0,
            "color_index": 15,
        }
        tim_sec = generate_tim_entry(item_spec)
        parsed = parse_tim(tim_sec)
        pix = parsed["pixel_data"]
        w, h = 16, 16

        # Unpack 4bpp pixels
        grid = [[0] * w for _ in range(h)]
        for y in range(h):
            row_off = y * (w // 2)
            for x in range(0, w, 2):
                b = pix[row_off + (x // 2)]
                grid[y][x] = b & 0x0F
                grid[y][x + 1] = (b >> 4) & 0x0F

        # Every pixel with value 1 must have (x-1, y-1) with value 15
        has_bevel = False
        for y in range(h):
            for x in range(w):
                if grid[y][x] == 1:
                    has_bevel = True
                    assert x > 0 and y > 0
                    assert grid[y - 1][x - 1] == 15
        assert has_bevel
    def test_4bpp_nibble_packing(self):
        # Create small 4x2 mask
        mask = Image.new("1", (4, 2), 0)
        # Row 0: pixel (0,0)=1, pixel (1,0)=0, pixel (2,0)=1, pixel (3,0)=1
        mask.putpixel((0, 0), 1)
        mask.putpixel((1, 0), 0)
        mask.putpixel((2, 0), 1)
        mask.putpixel((3, 0), 1)

        ci = 0x0E  # 14
        pixel_data = build_4bpp_pixel_data(mask, color_index=ci)
        assert len(pixel_data) == (4 // 2) * 2  # 4 bytes

        # Byte 0: left pixel (x=0) is ci, right pixel (x=1) is 0
        # low nibble = 0x0E, high nibble = 0x00 -> 0x0E
        assert pixel_data[0] == 0x0E
        # Byte 1: left pixel (x=2) is ci, right pixel (x=3) is ci
        # low nibble = 0x0E, high nibble = 0x0E -> 0xEE
        assert pixel_data[1] == 0xEE
        # Row 1 is all 0
        assert pixel_data[2] == 0x00
        assert pixel_data[3] == 0x00

    def test_build_and_parse_tim_roundtrip(self):
        # Create dummy 16-color CLUT (32 bytes)
        clut_data = bytes([0x00, 0x00] + [0xFF, 0x7F] * 15)
        w, h = 120, 24
        pixel_data = b"\x01" * ((w // 2) * h)

        tim_buf = build_tim(
            clut_x=0,
            clut_y=500,
            clut_data=clut_data,
            img_x=512,
            img_y=288,
            width=w,
            height=h,
            pixel_data=pixel_data,
        )

        assert len(tim_buf) == USER_DATA_SIZE
        # Magic is 0x00000010, flags 0x00000008
        assert tim_buf[:8] == b"\x10\x00\x00\x00\x08\x00\x00\x00"

        # Parse TIM
        parsed = parse_tim(tim_buf)
        assert parsed["pmode"] == 0
        assert parsed["has_clut"] is True
        assert parsed["clut"]["len"] == 44
        assert parsed["clut"]["x"] == 0
        assert parsed["clut"]["y"] == 500
        assert parsed["clut"]["w"] == 16
        assert parsed["clut"]["h"] == 1
        expected_clut = bytearray(clut_data)
        expected_clut[30:32] = struct.pack("<H", 0x8000)
        assert parsed["clut"]["data"] == bytes(expected_clut)
        assert struct.unpack_from("<H", parsed["clut"]["data"], 30)[0] == 0x8000

        assert parsed["img_x"] == 512
        assert parsed["img_y"] == 288
        assert parsed["img_w"] == w // 4
        assert parsed["img_h"] == h
        assert parsed["pixel_width"] == w
        assert parsed["pixel_height"] == h
        assert parsed["pixel_data"] == pixel_data

        # Verify zero padding
        trailing = tim_buf[parsed["total_tim_len"] :]
        assert len(trailing) > 0
        assert set(trailing) == {0}

    def test_build_tim_sets_color_15_opaque_black(self):
        dummy_clut = bytes([0x12, 0x34] * 16)
        tim_bytes = build_tim(0, 0, dummy_clut, 0, 0, 16, 16, bytes(128))
        parsed = parse_tim(tim_bytes)
        c15 = struct.unpack_from("<H", parsed["clut"]["data"], 30)[0]
        assert c15 == 0x8000

    def test_tim_to_rgba_image(self):
        clut_data = bytes([0x00, 0x00] + [0x1F, 0x00] * 15)  # index 1 = red
        w, h = 8, 4
        # Set first 2 pixels to index 1 (byte 0 = 0x11)
        pixel_data = b"\x11" + b"\x00" * (((w // 2) * h) - 1)

        tim_buf = build_tim(0, 0, clut_data, 0, 0, w, h, pixel_data)
        rgba_img = tim_to_rgba_image(tim_buf, transparent_zero=True)

        assert rgba_img.size == (w, h)
        assert rgba_img.mode == "RGBA"
        # Pixel (0, 0) should be red with full alpha
        r, g, b, a = rgba_img.getpixel((0, 0))
        assert r > 0
        assert a == 255
        # Pixel (2, 0) should be transparent index 0
        _, _, _, a_bg = rgba_img.getpixel((2, 0))
        assert a_bg == 0


class TestEdcEccAndSectorPatching:
    """Validate PlayStation Mode 2 Form 1 EDC/ECC recalculation and sector patching."""

    def test_edc_ecc_computation(self):
        chk = CdChecksums()
        # Mock Mode 2 Form 1 sector
        sector = bytearray(RAW_SECTOR_SIZE)
        sector[0:12] = b"\x00\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x00"
        sector[15] = 2  # Mode 2
        sector[16] = 1  # File
        sector[17] = 1  # Channel
        sector[18] = 0x08  # Submode: Form 1 data
        sector[USER_DATA_OFFSET : USER_DATA_OFFSET + 10] = b"TESTSLAYER"

        chk.repair_mode2_form1(sector)

        # Check EDC
        edc_computed = chk.compute_edc(sector[0x10:0x818])
        assert sector[0x818:0x81C] == edc_computed

        # Check ECC P and Q
        ecc_p = chk.compute_ecc(sector[0x10:], 86, 24, 2, 86)
        ecc_q = chk.compute_ecc(sector[0x10:], 52, 43, 86, 88)
        assert sector[0x81C:0x8C8] == ecc_p
        assert sector[0x8C8:0x930] == ecc_q

    def test_patch_sector_on_mock_disc(self, tmp_path):
        chk = CdChecksums()
        mock_bin = tmp_path / "mock_disc.bin"
        lba = 100
        total_sectors = 105

        # Create mock disc
        with open(mock_bin, "wb") as f:
            for s in range(total_sectors):
                sec = bytearray(RAW_SECTOR_SIZE)
                sec[0:12] = b"\x00\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x00"
                sec[15] = 2
                sec[18] = 0x08
                chk.repair_mode2_form1(sec)
                f.write(sec)

        orig_size = mock_bin.stat().st_size

        payload = b"A" * 100 + b"\x00" * (USER_DATA_SIZE - 100)
        patch_menu_sector(mock_bin, lba, payload)

        assert mock_bin.stat().st_size == orig_size

        # Read back user data and verify EDC/ECC
        user_data = read_sector_extent(mock_bin, lba, 1)
        assert user_data == payload

        raw_sec = read_raw_sector(mock_bin, lba)
        edc_computed = chk.compute_edc(raw_sec[0x10:0x818])
        assert raw_sec[0x818:0x81C] == edc_computed
        ecc_p = chk.compute_ecc(raw_sec[0x10:], 86, 24, 2, 86)
        assert raw_sec[0x81C:0x8C8] == ecc_p

    def test_dry_run_patch(self):
        res = patch_minigames_menu(dry_run=True)
        assert res["status"] == "success"
        assert res["dry_run"] is True
        assert res["patched_entries"] == 17
        assert len(res["patched_sectors"]) == 17

    def test_verify_production_disc_image(self):
        if not DEFAULT_TARGET_BIN.is_file():
            pytest.skip(f"Production image {DEFAULT_TARGET_BIN} not present")

        res = verify_minigames_menu(DEFAULT_TARGET_BIN)
        assert res["status"] == "success"
        assert res["verified_items"] == 17
        assert res["verified_sectors"] == 17
        assert res["total_items"] == 17


class TestPreviewGeneration:
    """Validate composite preview generation."""

    def test_generate_preview_file(self, tmp_path):
        preview_file = tmp_path / "test_preview.png"
        cat = load_minigames_menu_catalog(DEFAULT_CATALOG)
        out = generate_preview(cat, output_path=preview_file)

        assert out.is_file()
        assert out == preview_file

        with Image.open(out) as im:
            assert im.size == (320, 540)
            assert im.mode == "RGBA"
            # Ensure not all blank
            colors = im.getcolors(maxcolors=1000)
            assert colors is not None
            assert len(colors) > 10
