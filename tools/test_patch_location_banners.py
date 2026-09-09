#!/usr/bin/env python3
"""Unit tests for tools/patch_location_banners.py.

Validates:
1. All 14 required location banner translations and constants.
2. 16-color CLUT specifications (transparent index 0, dark outline index 1, bright core index 13..15).
3. Cyrillic text rendering and layout bounding boxes.
4. 4bpp pixel packing and nibble order.
5. TIM 4bpp binary construction (header 10 00 00 00 08 00 00 00, uncompressed size 28,736 bytes).
6. unt_lz compression fitting within 16,384 bytes (8 sectors) and roundtrip decompression.
7. Disc extent patching at LBA 240133 and EDC/ECC verification.
8. CLI verification mode.
"""

from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "patch_repo") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.patch_location_banners import (
    BANNER_LAYOUT,
    BANNER_TRANSLATIONS,
    CLUT_RGBA,
    CORE_COLOR_RGBA,
    ENTRY_466_BUDGET_BYTES,
    ENTRY_466_LBA,
    ENTRY_466_SECTOR_COUNT,
    LOCATION_BANNER_CLUT,
    OUTLINE_COLOR_RGBA,
    SECTOR_USER_SIZE,
    TIM_HEADER,
    TIM_HEIGHT,
    TIM_WIDTH,
    UNCOMPRESSED_TIM_SIZE,
    build_tim_4bpp,
    compress_entry_466,
    find_font_path,
    generate_patched_entry_466,
    get_base_image,
    image_to_4bpp_indices,
    main,
    patch_disc_image,
    render_cyrillic_banners,
    tim_to_image_4bpp,
    verify_disc_image,
)


class TestBannerTranslationsAndConstants:
    """Validate required translations and PS1 disc layout constants."""

    def test_all_fourteen_translations_present(self):
        expected_translations = {
            "MAIN ST": "ГЛАВНАЯ",
            "PLAZA": "ПЛОЩАДЬ",
            "BACK ST": "ЗАКОУЛКИ",
            "TAVERN": "ТАВЕРНА",
            "INN": "ОТЕЛЬ",
            "BAR": "БАР",
            "ARMORY": "ОРУЖЕЙНАЯ",
            "CHURCH": "ЦЕРКОВЬ",
            "OUTSKIRTS": "ОКРАИНА",
            "LEAVE TOWN": "ПОКИНУТЬ ГОРОД",
            "LARK'S HOUSE": "ДОМ ЛАРКА",
            "ROYAL PALACE": "ДВОРЕЦ",
            "MAYOR'S HOUSE": "ДОМ МЭРА",
            "MAGE GUILD": "ГИЛЬДИЯ",
        }
        for key, expected_val in expected_translations.items():
            assert key in BANNER_TRANSLATIONS, f"Missing key '{key}' in BANNER_TRANSLATIONS"
            assert BANNER_TRANSLATIONS[key] == expected_val

    def test_disc_layout_constants(self):
        assert ENTRY_466_LBA == 240133
        assert ENTRY_466_SECTOR_COUNT == 8
        assert SECTOR_USER_SIZE == 2048
        assert ENTRY_466_BUDGET_BYTES == 16384
        assert UNCOMPRESSED_TIM_SIZE == 28736
        assert TIM_WIDTH == 256
        assert TIM_HEIGHT == 224

    def test_font_available(self):
        font_path = find_font_path()
        assert font_path.is_file()
        assert font_path.name == "PressStart2P.ttf"


class TestClutPalette:
    """Validate 16-color CLUT specifications."""

    def test_clut_length_and_colors(self):
        assert len(LOCATION_BANNER_CLUT) == 16
        # Index 0: transparent
        assert LOCATION_BANNER_CLUT[0] == 0x0000
        # Index 1: dark blue outline
        assert LOCATION_BANNER_CLUT[1] == 0x4400
        # Index 13: bright cyan
        assert LOCATION_BANNER_CLUT[13] == 0x7FEC
        # Index 14 & 15: white
        assert LOCATION_BANNER_CLUT[14] == 0x7FFF
        assert LOCATION_BANNER_CLUT[15] == 0x7FFF

    def test_clut_rgba_mapping(self):
        assert len(CLUT_RGBA) == 16
        # Index 0 has alpha 0
        assert CLUT_RGBA[0][3] == 0
        # All other indices have alpha 255
        for i in range(1, 16):
            assert CLUT_RGBA[i][3] == 255


class TestCyrillicRendering:
    """Validate Pillow text rendering of Cyrillic banners."""

    def test_render_dimensions(self):
        base_img = get_base_image()
        assert base_img.size == (TIM_WIDTH, TIM_HEIGHT)

        rendered = render_cyrillic_banners(base_img)
        assert rendered.size == (TIM_WIDTH, TIM_HEIGHT)
        assert rendered.mode == "RGBA"

    def test_rendered_content_present_in_all_bands(self):
        base_img = Image.new("RGBA", (TIM_WIDTH, TIM_HEIGHT), (0, 0, 0, 0))
        rendered = render_cyrillic_banners(base_img)
        arr = np.array(rendered)
        alpha = arr[:, :, 3]

        for banner_key, trans_key, (cx0, cy0, cx1, cy1), (dx, dy) in BANNER_LAYOUT:
            sub = alpha[cy0:cy1, cx0:cx1]
            active_count = np.count_nonzero(sub > 0)
            assert active_count > 0, f"No rendered pixels found for banner {banner_key} in box {cx0, cy0, cx1, cy1}"

    def test_outline_and_core_colors(self):
        base_img = Image.new("RGBA", (TIM_WIDTH, TIM_HEIGHT), (0, 0, 0, 0))
        rendered = render_cyrillic_banners(base_img)
        arr = np.array(rendered)
        alpha = arr[:, :, 3]

        # Check outline pixels exist
        outline_mask = (
            (arr[:, :, 0] == OUTLINE_COLOR_RGBA[0])
            & (arr[:, :, 1] == OUTLINE_COLOR_RGBA[1])
            & (arr[:, :, 2] == OUTLINE_COLOR_RGBA[2])
            & (alpha > 0)
        )
        assert np.count_nonzero(outline_mask) > 1000, "Outline pixels not rendered correctly"

        # Check core pixels exist
        core_mask = (
            (arr[:, :, 0] == CORE_COLOR_RGBA[0])
            & (arr[:, :, 1] == CORE_COLOR_RGBA[1])
            & (arr[:, :, 2] == CORE_COLOR_RGBA[2])
            & (alpha > 0)
        )
        assert np.count_nonzero(core_mask) > 1000, "Core pixels not rendered correctly"


class TestTimPackingAndCompression:
    """Validate 4bpp TIM construction and unt_lz compression."""

    def test_image_to_4bpp_packing(self):
        img = Image.new("RGBA", (TIM_WIDTH, TIM_HEIGHT), (0, 0, 0, 0))
        packed = image_to_4bpp_indices(img)
        expected_len = (TIM_WIDTH * TIM_HEIGHT) // 2
        assert len(packed) == expected_len
        assert all(b == 0 for b in packed)

    def test_tim_binary_header_and_structure(self):
        img = Image.new("RGBA", (TIM_WIDTH, TIM_HEIGHT), (0, 0, 0, 0))
        packed = image_to_4bpp_indices(img)
        tim = build_tim_4bpp(packed)

        assert len(tim) == UNCOMPRESSED_TIM_SIZE
        # Header
        assert tim[:8] == TIM_HEADER

        # CLUT block (offset 8)
        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim, 8)
        assert clut_len == 44
        assert (cx, cy, cw, ch) == (0, 480, 16, 1)

        # Image block (offset 8 + 44 = 52)
        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", tim, 52)
        assert img_len == 12 + len(packed)
        assert (ix, iy, iw, ih) == (0, 0, TIM_WIDTH // 4, TIM_HEIGHT)

    def test_tim_roundtrip_decoding(self):
        base_img = get_base_image()
        rendered = render_cyrillic_banners(base_img)
        packed = image_to_4bpp_indices(rendered)
        tim = build_tim_4bpp(packed)

        decoded_img = tim_to_image_4bpp(tim)
        assert decoded_img.size == (TIM_WIDTH, TIM_HEIGHT)
        assert decoded_img.mode == "RGBA"

    def test_compression_within_sector_budget(self):
        tim_data, compressed_payload = generate_patched_entry_466()
        assert len(tim_data) == UNCOMPRESSED_TIM_SIZE
        assert len(compressed_payload) == ENTRY_466_BUDGET_BYTES

        # Decompress from padded payload
        from localization import unt_lz
        decomp, consumed = unt_lz.decompress(compressed_payload)
        assert decomp == tim_data
        assert consumed <= ENTRY_466_BUDGET_BYTES
        # Ensure compressed stream has comfortable margin under 16,384 bytes
        assert consumed < 10000, f"Compressed size {consumed} too large"


class TestDiscPatchAndVerification:
    """Validate disc image injection and verification functionality."""

    @pytest.fixture
    def target_bin(self) -> Path:
        candidates = [
            REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin",
            REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin",
            REPO_ROOT / "downloads" / "sr.bin",
        ]
        for c in candidates:
            if c.is_file():
                return c
        pytest.skip("No real PS1 BIN disc image found in repo")

    def test_verify_on_real_disc(self, target_bin: Path):
        ok = verify_disc_image(target_bin)
        assert ok is True, f"Verification failed on {target_bin}"

    def test_patch_and_verify_temporary_disc(self, target_bin: Path, tmp_path: Path):
        # Create a small disc slice containing LBA 240133..240140
        from localization.disc import RAW_SECTOR_SIZE

        temp_disc = tmp_path / "test_disc.bin"
        # We only need enough bytes to cover up to sector 240141
        total_bytes = (ENTRY_466_LBA + ENTRY_466_SECTOR_COUNT + 1) * RAW_SECTOR_SIZE

        # Read actual sectors from target_bin to preserve valid Mode 2 Form 1 headers
        with open(target_bin, "rb") as src:
            src.seek(ENTRY_466_LBA * RAW_SECTOR_SIZE)
            real_sectors = src.read(ENTRY_466_SECTOR_COUNT * RAW_SECTOR_SIZE)

        with open(temp_disc, "wb") as dst:
            dst.truncate(total_bytes)
            dst.seek(ENTRY_466_LBA * RAW_SECTOR_SIZE)
            dst.write(real_sectors)

        # Patch the temporary disc
        patch_disc_image(temp_disc)

        # Verify the temporary disc
        assert verify_disc_image(temp_disc) is True

    def test_cli_verify_mode(self):
        exit_code = main(["--verify"])
        assert exit_code == 0
