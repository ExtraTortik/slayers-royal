#!/usr/bin/env python3
"""Unit tests for tools/patch_basyog_162.py.

Validates:
1. PS1 disc constants and sector budget for BASYOG.UNT Entry 162.
2. PNG to 8bpp TIM conversion producing exact 66,080-byte binary.
3. TIM header, CLUT header, and Image block dimensions and geometry.
4. unt_lz mode 1 LZSS compression fitting within the 4-sector (8,192 bytes) budget.
5. Bit-exact roundtrip decompression.
6. Graceful skip when preview_basyog_162_ru.png is absent.
7. Fallback to preview_basyog_162_en.png when --force is enabled.
8. Disc patching, Mode 2 Form 1 EDC/ECC repair, and verify_basyog_162 validation.
9. CLI options (--verify, --dry-run, --force).
"""

from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "patch_repo") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from localization import unt_lz
    from localization.disc import RAW_SECTOR_SIZE
except ImportError:
    from patch_repo.localization import unt_lz
    from patch_repo.localization.disc import RAW_SECTOR_SIZE

from tools.patch_basyog_162 import (
    BASYOG_LBA,
    CLUT_BLOCK_SIZE,
    DEFAULT_EN_PNG,
    DEFAULT_RU_PNG,
    ENTRY_162_BUDGET,
    ENTRY_162_LBA,
    ENTRY_162_OFFSET,
    ENTRY_162_SECTORS,
    IMAGE_HEADER_SIZE,
    PIXEL_DATA_SIZE,
    TIM_HEIGHT,
    TIM_WIDTH,
    UNCOMPRESSED_TIM_SIZE,
    main,
    patch_basyog_162,
    png_to_basyog_162_tim,
    verify_basyog_162,
)


@pytest.fixture
def target_disc() -> Path:
    """Find a candidate disc image in repo for testing."""
    candidates = [
        REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin",
        REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin",
        REPO_ROOT / "build" / "en_patched" / "sr_patched.bin",
        REPO_ROOT / "downloads" / "sr.bin",
    ]
    for c in candidates:
        if c.is_file():
            return c
    pytest.skip("No real PS1 BIN disc image found in repo")


class TestConstants:
    """Validate disc layout and memory constants."""

    def test_disc_constants(self):
        assert BASYOG_LBA == 233328
        assert ENTRY_162_OFFSET == 6046
        assert ENTRY_162_SECTORS == 4
        assert ENTRY_162_BUDGET == 8192
        assert ENTRY_162_LBA == 239374
        assert ENTRY_162_LBA == BASYOG_LBA + ENTRY_162_OFFSET

    def test_tim_geometry_constants(self):
        assert TIM_WIDTH == 256
        assert TIM_HEIGHT == 256
        assert PIXEL_DATA_SIZE == 65536
        assert CLUT_BLOCK_SIZE == 524
        assert IMAGE_HEADER_SIZE == 12
        assert UNCOMPRESSED_TIM_SIZE == 8 + CLUT_BLOCK_SIZE + IMAGE_HEADER_SIZE + PIXEL_DATA_SIZE
        assert UNCOMPRESSED_TIM_SIZE == 66080

    def test_default_paths(self):
        assert DEFAULT_RU_PNG == REPO_ROOT / "data" / "preview_basyog_162_ru.png"
        assert DEFAULT_EN_PNG == REPO_ROOT / "data" / "preview_basyog_162_en.png"


class TestPngToTimConversion:
    """Validate PNG conversion to 8bpp TIM format."""

    def test_png_to_tim_exact_size(self):
        assert DEFAULT_EN_PNG.is_file(), f"Missing required reference image: {DEFAULT_EN_PNG}"
        tim_bytes = png_to_basyog_162_tim(DEFAULT_EN_PNG)
        assert len(tim_bytes) == UNCOMPRESSED_TIM_SIZE
        assert len(tim_bytes) == 66080

    def test_tim_headers_and_geometry(self):
        tim_bytes = png_to_basyog_162_tim(DEFAULT_EN_PNG)

        # Magic: 0x00000010, Flags: 0x00000009 (8bpp with CLUT)
        magic, flags = struct.unpack_from("<II", tim_bytes, 0)
        assert magic == 0x10, f"Expected TIM magic 0x10, got 0x{magic:08X}"
        assert flags == 0x09, f"Expected TIM flags 0x09 (8bpp + CLUT), got 0x{flags:08X}"

        # CLUT header: len 524, x=0, y=480, w=256, h=1
        clut_len, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", tim_bytes, 8)
        assert clut_len == 524
        assert clut_x == 0
        assert clut_y == 480
        assert clut_w == 256
        assert clut_h == 1

        # Image header: len 65548, x=0, y=0, w=128 (words = 256 px), h=256
        img_offset = 8 + clut_len
        img_len, img_x, img_y, img_w, img_h = struct.unpack_from("<IHHHH", tim_bytes, img_offset)
        assert img_len == 12 + 65536
        assert img_x == 0
        assert img_y == 0
        assert img_w == 128
        assert img_h == 256

        # Pixel data size
        pixel_data = tim_bytes[img_offset + 12 :]
        assert len(pixel_data) == 65536

    def test_invalid_dimensions_raise_error(self, tmp_path: Path):
        bad_img = Image.new("RGBA", (200, 200), (0, 0, 0, 255))
        bad_png = tmp_path / "bad.png"
        bad_img.save(bad_png)

        with pytest.raises(ValueError, match="Invalid image dimensions"):
            png_to_basyog_162_tim(bad_png)

    def test_missing_file_raises_not_found(self, tmp_path: Path):
        nonexistent = tmp_path / "missing.png"
        with pytest.raises(FileNotFoundError):
            png_to_basyog_162_tim(nonexistent)


class TestCompressionAndRoundtrip:
    """Validate LZSS mode 1 compression within the 4-sector budget."""

    def test_lzss_fits_budget(self):
        tim_bytes = png_to_basyog_162_tim(DEFAULT_EN_PNG)
        compressed = unt_lz.compress(tim_bytes)
        assert len(compressed) <= ENTRY_162_BUDGET, (
            f"Compressed size ({len(compressed)} B) exceeds budget ({ENTRY_162_BUDGET} B)"
        )
        margin = ENTRY_162_BUDGET - len(compressed)
        assert margin >= 1000, f"Expected comfortable margin, got {margin} bytes"

    def test_roundtrip_decompression_bit_exact(self):
        tim_bytes = png_to_basyog_162_tim(DEFAULT_EN_PNG)
        compressed = unt_lz.compress(tim_bytes)
        decompressed, consumed = unt_lz.decompress(compressed)
        assert decompressed == tim_bytes
        assert consumed == len(compressed)


class TestDiscPatchAndVerification:
    """Validate disc image injection and EDC/ECC verification."""

    def test_verify_on_real_disc(self, target_disc: Path):
        result = verify_basyog_162(target_disc)
        assert result["status"] == "ok"
        assert result["lba"] == ENTRY_162_LBA
        assert result["sectors"] == ENTRY_162_SECTORS
        assert result["budget"] == ENTRY_162_BUDGET
        assert result["compressed_size"] <= ENTRY_162_BUDGET
        assert result["tim_size"] == UNCOMPRESSED_TIM_SIZE
        assert result["edc_ecc_valid"] is True
        assert result["clut_info"]["w"] == 256
        assert result["image_info"]["h"] == 256

    def test_patch_skips_when_ru_missing(self, target_disc: Path, tmp_path: Path):
        nonexistent_ru = tmp_path / "nonexistent_preview_ru.png"
        result = patch_basyog_162(
            bin_path=target_disc,
            png_path=nonexistent_ru,
            force=False,
        )
        assert result["status"] == "skipped"
        assert "not found" in result["reason"]

    def test_patch_force_fallback(self, target_disc: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        # When forcing fallback to English PNG in dry_run mode
        monkeypatch.setattr("tools.patch_basyog_162.DEFAULT_RU_PNG", tmp_path / "nonexistent.png")
        result = patch_basyog_162(
            bin_path=target_disc,
            png_path=None,
            force=True,
            dry_run=True,
        )
        assert result["status"] == "dry_run"
        assert result["png_path"] == str(DEFAULT_EN_PNG)
        assert result["compressed_size"] <= ENTRY_162_BUDGET
        assert result["margin"] > 0
        assert result["dry_run"] is True

    def test_patch_and_verify_temporary_disc(self, target_disc: Path, tmp_path: Path):
        temp_disc = tmp_path / "temp_disc.bin"
        total_bytes = (ENTRY_162_LBA + ENTRY_162_SECTORS + 1) * RAW_SECTOR_SIZE

        # Read actual sectors from real disc to obtain valid Mode 2 Form 1 headers
        with open(target_disc, "rb") as src:
            src.seek(ENTRY_162_LBA * RAW_SECTOR_SIZE)
            real_sectors = src.read(ENTRY_162_SECTORS * RAW_SECTOR_SIZE)

        with open(temp_disc, "wb") as dst:
            dst.truncate(total_bytes)
            dst.seek(ENTRY_162_LBA * RAW_SECTOR_SIZE)
            dst.write(real_sectors)

        # Verify initial slice
        init_res = verify_basyog_162(temp_disc)
        assert init_res["status"] == "ok"

        # Patch the slice with English reference atlas
        patch_res = patch_basyog_162(
            bin_path=temp_disc,
            png_path=DEFAULT_EN_PNG,
            force=False,
            dry_run=False,
        )
        assert patch_res["status"] == "success"
        assert patch_res["compressed_size"] <= ENTRY_162_BUDGET
        assert patch_res["dry_run"] is False

        # Verify post-patch slice has valid EDC/ECC and correct TIM
        verify_res = verify_basyog_162(temp_disc)
        assert verify_res["status"] == "ok"
        assert verify_res["edc_ecc_valid"] is True
        assert verify_res["tim_size"] == UNCOMPRESSED_TIM_SIZE


class TestCli:
    """Validate CLI execution."""

    def test_cli_verify(self, target_disc: Path):
        code = main(["--verify", "--bin", str(target_disc)])
        assert code == 0

    def test_cli_dry_run_force(self, target_disc: Path):
        code = main(["--dry-run", "--force", "--bin", str(target_disc)])
        assert code == 0

    def test_cli_skip_when_ru_missing(self, target_disc: Path, tmp_path: Path):
        fake_png = tmp_path / "no_ru.png"
        code = main(["--png", str(fake_png), "--bin", str(target_disc)])
        assert code == 0
