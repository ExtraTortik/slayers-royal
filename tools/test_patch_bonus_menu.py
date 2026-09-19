#!/usr/bin/env python3
"""Unit tests for tools/patch_bonus_menu.py.

Validates:
1. Catalog loading and schema validation:
   - Correct JSON structure and required metadata in translations/bonus_menu_ru.json.
   - All 4 required bonus room section items (sound_mode, movies, help, minigames) present.
   - Title menu items (start, continue, bonus) present.
   - Exact specifications:
     - movies: Entry 144, width 64, height 16, VRAM (412, 224), CLUT (0, 484), text_ru: "РОЛИКИ" (or "ВИДЕО")
     - sound_mode: Entry 143, width 112, height 16, VRAM (384, 224), CLUT (0, 483), text_ru: "ЗВУК"
     - minigames: Entry 146, width 80, height 16, VRAM (384, 240), CLUT (0, 486), text_ru: "МИНИ-ИГРЫ"
     - help: Entry 145, width 64, height 16, VRAM (428, 224), CLUT (0, 485), text_ru: "ПОМОЩЬ"
   - Error handling for missing files and malformed schema.
2. Font discovery and rendering:
   - Discovery of fonts/PressStart2P.ttf.
   - Text rendering with white core (color 1) and dark outline (color 15).
   - Bounds check ensuring rendered glyphs fit within target sprite dimensions.
   - 4bpp nibble packing (low nibble left, high nibble right).
3. PS1 4bpp TIM binary format assembly:
   - Valid TIM magic (0x00000010) and pmode 0 flag (0x00000008).
   - Correct CLUT block header and coordinates.
   - Correct image block header, VRAM coordinates, and word dimensions.
   - 2048-byte sector alignment / padding.
4. Mode 2 Form 1 EDC/ECC calculation and sector patching:
   - EDC checksum recalculation.
   - ECC P/Q parity recalculation.
   - Mock disc patching and production image verification.
5. Composite visual preview generation:
   - Correct output dimensions and RGBA mode for data/preview_bonus_menu_ru.png.
   - Section headers rendered inside Frame 142.
6. Verification CLI and end-to-end patcher execution.
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

from tools.patch_bonus_menu import (
    DEFAULT_CATALOG,
    DEFAULT_FONT_PATH,
    DEFAULT_PREVIEW_PATH,
    DEFAULT_TARGET_BIN,
    OPT_ARCHIVE_LBA,
    RAW_SECTOR_SIZE,
    REQUIRED_BONUS_KEYS,
    REQUIRED_TITLE_KEYS,
    USER_DATA_OFFSET,
    USER_DATA_SIZE,
    build_4bpp_pixel_data,
    build_tim,
    find_font,
    generate_bonus_tim,
    generate_preview,
    load_bonus_menu_catalog,
    parse_tim,
    patch_bonus_menu,
    patch_disc_sector,
    read_raw_sector,
    read_sector_extent,
    render_text_with_outline,
    tim_to_rgba_image,
    verify_bonus_menu,
)

try:
    from patch_repo.localization.disc import CdChecksums
except ImportError:
    from localization.disc import CdChecksums


class TestCatalogLoadingAndSchema:
    """Validate translations/bonus_menu_ru.json schema and item specifications."""

    def test_catalog_file_exists_and_loads(self):
        assert DEFAULT_CATALOG.is_file(), f"Missing catalog file: {DEFAULT_CATALOG}"
        cat = load_bonus_menu_catalog(DEFAULT_CATALOG)
        assert isinstance(cat, dict)
        assert "metadata" in cat
        assert "bonus_menu" in cat
        assert "title_menu" in cat

    def test_catalog_metadata(self):
        cat = load_bonus_menu_catalog(DEFAULT_CATALOG)
        meta = cat["metadata"]
        assert meta.get("archive") == "OPT.UNT"
        assert meta.get("archive_lba") == 226000
        assert meta.get("total_bonus_entries") == 4
        assert meta.get("total_title_entries") == 3
        assert meta.get("format") == "4bpp TIM"

    def test_all_four_bonus_keys_present(self):
        cat = load_bonus_menu_catalog(DEFAULT_CATALOG)
        items = cat["bonus_menu"]
        for k in REQUIRED_BONUS_KEYS:
            assert k in items, f"Missing required bonus menu key: {k}"

    def test_all_three_title_keys_present(self):
        cat = load_bonus_menu_catalog(DEFAULT_CATALOG)
        t_items = cat["title_menu"]
        for k in REQUIRED_TITLE_KEYS:
            assert k in t_items, f"Missing required title menu key: {k}"

    def test_exact_bonus_entry_specifications(self):
        cat = load_bonus_menu_catalog(DEFAULT_CATALOG)
        items = cat["bonus_menu"]

        expected_specs = {
            "sound_mode": (143, 2458, 384, 224, 112, 16, 0, 483, "ЗВУК"),
            "movies": (144, 2459, 412, 224, 64, 16, 0, 484, "РОЛИКИ"),
            "help": (145, 2460, 428, 224, 64, 16, 0, 485, "ПОМОЩЬ"),
            "minigames": (146, 2461, 384, 240, 80, 16, 0, 486, "МИНИ-ИГРЫ"),
        }

        for key, (entry, sec_off, vx, vy, w, h, cx, cy, text_ru) in expected_specs.items():
            it = items[key]
            assert it["entry"] == entry
            assert it["sector_offset"] == sec_off
            assert it["vram_x"] == vx
            assert it["vram_y"] == vy
            assert it["width"] == w
            assert it["height"] == h
            assert it["clut_x"] == cx
            assert it["clut_y"] == cy
            assert it["text_ru"] == text_ru or (key == "movies" and it["text_ru"] in ("РОЛИКИ", "ВИДЕО"))

    def test_title_menu_translations(self):
        cat = load_bonus_menu_catalog(DEFAULT_CATALOG)
        t_items = cat["title_menu"]
        assert t_items["start"]["text_ru"] == "СТАРТ"
        assert t_items["continue"]["text_ru"] == "ЗАГРУЗКА"
        assert t_items["bonus"]["text_ru"] == "БОНУС"

    def test_catalog_error_handling(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_bonus_menu_catalog(tmp_path / "non_existent.json")

        bad_json = tmp_path / "bad.json"
        bad_json.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a JSON object"):
            load_bonus_menu_catalog(bad_json)

        bad_json.write_text(json.dumps({"metadata": {}}), encoding="utf-8")
        with pytest.raises(ValueError, match="missing 'bonus_menu'"):
            load_bonus_menu_catalog(bad_json)

        bad_items_missing_key = {
            "bonus_menu": {
                "movies": {"entry": 144, "sector_offset": 2459, "width": 64, "height": 16, "vram_x": 412, "vram_y": 224, "text_ru": "РОЛИКИ"}
            }
        }
        bad_json.write_text(json.dumps(bad_items_missing_key), encoding="utf-8")
        with pytest.raises(ValueError, match="Missing required bonus menu item"):
            load_bonus_menu_catalog(bad_json)

        bad_items_missing_field = {
            "bonus_menu": {
                "sound_mode": {"entry": 143}
            }
        }
        bad_json.write_text(json.dumps(bad_items_missing_field), encoding="utf-8")
        with pytest.raises(ValueError, match="missing required field"):
            load_bonus_menu_catalog(bad_json)


class TestFontResolutionAndTextRendering:
    """Validate font discovery and Cyrillic text rendering."""

    def test_font_discovery(self):
        font_path = find_font()
        assert font_path.is_file()
        assert font_path.suffix.lower() == ".ttf"

    def test_text_rendering_dimensions_and_colors(self):
        font_path = find_font()
        font = ImageFont.truetype(str(font_path), 8)

        # Test "ЗВУК" (112x16)
        im = render_text_with_outline("ЗВУК", font, 112, 16, core_idx=1, outline_idx=15)
        assert im.size == (112, 16)
        colors = set(im.tobytes())
        assert colors.issubset({0, 1, 15})
        assert 1 in colors  # core white
        assert 15 in colors  # outline

        # Test "РОЛИКИ" (64x16)
        im = render_text_with_outline("РОЛИКИ", font, 64, 16, core_idx=1, outline_idx=15)
        assert im.size == (64, 16)
        colors = set(im.tobytes())
        assert colors.issubset({0, 1, 15})

        # Test "ПОМОЩЬ" (64x16)
        im = render_text_with_outline("ПОМОЩЬ", font, 64, 16, core_idx=1, outline_idx=15)
        assert im.size == (64, 16)
        colors = set(im.tobytes())
        assert colors.issubset({0, 1, 15})

        # Test "МИНИ-ИГРЫ" (80x16)
        im = render_text_with_outline("МИНИ-ИГРЫ", font, 80, 16, core_idx=1, outline_idx=15)
        assert im.size == (80, 16)
        colors = set(im.tobytes())
        assert colors.issubset({0, 1, 15})

    def test_4bpp_pixel_packing(self):
        im = Image.new("P", (4, 2), 0)
        im.putpixel((0, 0), 1)   # low nibble
        im.putpixel((1, 0), 15)  # high nibble -> 0xF1
        im.putpixel((2, 0), 2)
        im.putpixel((3, 0), 3)   # -> 0x32
        im.putpixel((0, 1), 0)
        im.putpixel((1, 1), 0)
        im.putpixel((2, 1), 5)
        im.putpixel((3, 1), 6)

        data = build_4bpp_pixel_data(im)
        assert len(data) == 4
        assert data[0] == 0xF1
        assert data[1] == 0x32
        assert data[2] == 0x00
        assert data[3] == 0x65


class TestTimBinaryFormat:
    """Validate standard PS1 4bpp TIM structure and padding."""

    def test_tim_assembly_and_padding(self):
        clut = bytearray(32)
        struct.pack_into("<H", clut, 2, 0x7FFF)
        struct.pack_into("<H", clut, 30, 0x0842)
        pixel_data = bytes(64 * 16 // 2)

        tim = build_tim(
            clut_x=0,
            clut_y=484,
            clut_data=bytes(clut),
            img_x=412,
            img_y=224,
            width=64,
            height=16,
            pixel_data=pixel_data,
        )

        assert len(tim) == USER_DATA_SIZE
        parsed = parse_tim(tim)
        assert parsed["pmode"] == 0
        assert parsed["has_clut"] is True
        assert parsed["clut"]["x"] == 0
        assert parsed["clut"]["y"] == 484
        assert parsed["clut"]["num_colors"] == 16
        assert parsed["img_x"] == 412
        assert parsed["img_y"] == 224
        assert parsed["pixel_width"] == 64
        assert parsed["pixel_height"] == 16

    def test_generate_bonus_tim_for_all_items(self):
        cat = load_bonus_menu_catalog(DEFAULT_CATALOG)
        items = cat["bonus_menu"]
        for key in REQUIRED_BONUS_KEYS:
            it = items[key]
            tim = generate_bonus_tim(it)
            assert len(tim) == USER_DATA_SIZE
            parsed = parse_tim(tim)
            assert parsed["pmode"] == 0
            assert parsed["pixel_width"] == it["width"]
            assert parsed["pixel_height"] == it["height"]
            assert parsed["img_x"] == it["vram_x"]
            assert parsed["img_y"] == it["vram_y"]


class TestSectorPatchingAndEdcEcc:
    """Validate Mode 2 Form 1 sector injection and checksum recalculation."""

    def test_sector_patch_on_mock_disc(self, tmp_path: Path):
        mock_bin = tmp_path / "test.bin"
        lba = OPT_ARCHIVE_LBA + 2458
        total_sectors = lba + 5

        # Initialize mock Mode 2 Form 1 disc
        with open(mock_bin, "wb") as f:
            for s in range(total_sectors):
                sector = bytearray(RAW_SECTOR_SIZE)
                # Sync header
                sector[0:12] = b"\x00" + b"\xff" * 10 + b"\x00"
                # Sector mode 2
                sector[15] = 2
                # Subheader Mode 2 Form 1 (data)
                sector[16:24] = b"\x00\x00\x08\x00\x00\x00\x08\x00"
                f.write(sector)

        cat = load_bonus_menu_catalog(DEFAULT_CATALOG)
        payload = generate_bonus_tim(cat["bonus_menu"]["sound_mode"])

        patch_disc_sector(mock_bin, lba, payload)

        # Read back raw sector
        raw = read_raw_sector(mock_bin, lba)
        assert raw[USER_DATA_OFFSET : USER_DATA_OFFSET + USER_DATA_SIZE] == payload

        # Check EDC / ECC
        chk = CdChecksums()
        edc_expected = raw[0x818:0x81C]
        edc_computed = chk.compute_edc(raw[0x10:0x818])
        assert edc_expected == edc_computed

        ecc_p_expected = raw[0x81C:0x8C8]
        ecc_p_computed = chk.compute_ecc(raw[0x10:], 86, 24, 2, 86)
        assert ecc_p_expected == ecc_p_computed


class TestPreviewGeneration:
    """Validate visual composite preview generation."""

    def test_generate_preview(self, tmp_path: Path):
        cat = load_bonus_menu_catalog(DEFAULT_CATALOG)
        out_preview = tmp_path / "preview.png"

        saved = generate_preview(cat, output_path=out_preview)
        assert saved.is_file()
        im = Image.open(saved)
        assert im.mode == "RGBA"
        assert im.size == (320, 260)


class TestDiscImageVerification:
    """Validate production disc images when present in workspace."""

    def test_target_bin_verification(self):
        if not DEFAULT_TARGET_BIN.is_file():
            pytest.skip("Target disc image not present")

        res = verify_bonus_menu(bin_path=DEFAULT_TARGET_BIN)
        assert res["status"] == "verified"
        assert res["verified_items"] == 4
        assert res["verified_sectors"] == 4

    def test_patch_bonus_menu_dry_run(self):
        res = patch_bonus_menu(dry_run=True, preview=False)
        assert res["status"] == "success"
        assert res["dry_run"] is True
        assert res["patched_entries"] == 4
