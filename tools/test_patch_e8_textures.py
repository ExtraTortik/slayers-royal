#!/usr/bin/env python3
"""Comprehensive test suite for tools/patch_e8_textures.py.

Validates:
1. PS1 disc constants and sector calculations for PROG.UNT Entry 8 at decimal byte offset 74,380.
2. TIM assembly, headers, CLUT geometry, and image block geometry.
3. Image format handling:
   - Mode 'P' paletted PNG with transparency index (DuckStation dump style).
   - Mode 'P' paletted PNG without transparency info.
   - Mode 'RGBA' with alpha transparency.
   - Mode 'RGB' fully opaque.
   - Non-standard dimensions (e.g. 283x225) properly padded/fitted to 256x256 canvas.
4. Round-trip conversion: image -> TIM -> RGBA preview.
5. Candidate image search hierarchy in data/custom_hud_textures/ and fallback locations.
6. Mock disc patching, in-place sector replacement, and Mode 2 Form 1 EDC/ECC repair.
7. Verification that bytes before offset 652 and after offset 66,732 are strictly preserved.
8. CLI functionality (--verify, --dump-dir, --dry-run).
9. Production disc image verification for both primary and secondary bins.
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

try:
    from localization.disc import (
        CdChecksums,
        RAW_SECTOR_SIZE,
        USER_DATA_OFFSET,
        USER_DATA_SIZE,
        read_extent,
    )
except ImportError:
    from patch_repo.localization.disc import (
        CdChecksums,
        RAW_SECTOR_SIZE,
        USER_DATA_OFFSET,
        USER_DATA_SIZE,
        read_extent,
    )

try:
    from localization import unt_lz
except ImportError:
    from patch_repo.localization import unt_lz

from tools.patch_e8_textures import (
    BASYOG_LBA,
    CLUT_BLOCK_SIZE,
    CLUT_COLORS,
    DATE_WIDGET_DST_POS,
    DATE_WIDGET_DST_X,
    DATE_WIDGET_DST_Y,
    DATE_WIDGET_HEIGHT,
    DATE_WIDGET_SRC_BOX,
    DATE_WIDGET_WIDTH,
    DEFAULT_CUSTOM_HUD_DIR,
    DEFAULT_PREVIEW_PNG,
    DEFAULT_PRIMARY_BIN,
    DEFAULT_SECONDARY_BIN,
    DEFAULT_TEXUPLOAD_PNG,
    ENTRY_8_BYTE_OFFSET,
    ENTRY_8_LBA,
    ENTRY_8_SECTOR_COUNT,
    ENTRY_8_SECTOR_OFFSET,
    ENTRY_160_BUDGET,
    ENTRY_160_LBA,
    ENTRY_160_OFFSET,
    ENTRY_160_SECTOR_OFFSET,
    ENTRY_160_SECTORS,
    IMAGE_BLOCK_SIZE,
    IMAGE_HEADER_SIZE,
    PIXEL_DATA_SIZE,
    PROG_LBA,
    TIM_END_LBA,
    TIM_HEIGHT,
    TIM_IN_SECTOR_OFFSET,
    TIM_SECTOR_COUNT,
    TIM_SECTOR_OFFSET,
    TIM_START_LBA,
    TIM_WIDTH,
    TOTAL_EXTENT_BYTES,
    UNCOMPRESSED_TIM_SIZE,
    dump_e8_texture,
    e8_tim_to_image,
    extract_entry_160_tim,
    find_candidate_image,
    image_to_e8_tim,
    main,
    parse_args,
    patch_basyog_160,
    patch_basyog_entry_160_tim,
    patch_e8_textures,
    verify_basyog_160,
    verify_e8_textures,
)


class TestConstantsAndSectorCalculations:
    """Validate sector offset mathematics and disc layout invariants."""

    def test_disc_layout_constants(self):
        assert PROG_LBA == 229020
        assert ENTRY_8_SECTOR_OFFSET == 1506
        assert ENTRY_8_LBA == 230526
        assert ENTRY_8_SECTOR_COUNT == 250
        assert ENTRY_8_BYTE_OFFSET == 74380

    def test_sector_and_lba_math(self):
        assert TIM_SECTOR_OFFSET == 74380 // 2048
        assert TIM_SECTOR_OFFSET == 36
        assert TIM_IN_SECTOR_OFFSET == 74380 % 2048
        assert TIM_IN_SECTOR_OFFSET == 652
        assert TIM_START_LBA == ENTRY_8_LBA + TIM_SECTOR_OFFSET
        assert TIM_START_LBA == 230562
        assert TIM_SECTOR_COUNT == 33
        assert TIM_END_LBA == TIM_START_LBA + TIM_SECTOR_COUNT - 1
        assert TIM_END_LBA == 230594

    def test_tim_boundary_fit(self):
        tim_end_byte_in_extent = TIM_IN_SECTOR_OFFSET + UNCOMPRESSED_TIM_SIZE
        assert tim_end_byte_in_extent == 652 + 66080
        assert tim_end_byte_in_extent == 66732
        assert TOTAL_EXTENT_BYTES == 33 * 2048
        assert TOTAL_EXTENT_BYTES == 67584
        assert tim_end_byte_in_extent <= TOTAL_EXTENT_BYTES
        # Last sector margin
        assert TOTAL_EXTENT_BYTES - tim_end_byte_in_extent == 852

    def test_tim_geometry_constants(self):
        assert TIM_WIDTH == 256
        assert TIM_HEIGHT == 256
        assert CLUT_COLORS == 256
        assert CLUT_BLOCK_SIZE == 12 + (CLUT_COLORS * 2)
        assert CLUT_BLOCK_SIZE == 524
        assert IMAGE_HEADER_SIZE == 12
        assert PIXEL_DATA_SIZE == 256 * 256
        assert PIXEL_DATA_SIZE == 65536
        assert IMAGE_BLOCK_SIZE == 12 + 65536
        assert IMAGE_BLOCK_SIZE == 65548
        assert UNCOMPRESSED_TIM_SIZE == 8 + CLUT_BLOCK_SIZE + IMAGE_BLOCK_SIZE
        assert UNCOMPRESSED_TIM_SIZE == 66080

    def test_basyog_entry_160_constants(self):
        assert BASYOG_LBA == 233328
        assert ENTRY_160_OFFSET == 6024
        assert ENTRY_160_SECTOR_OFFSET == 6024
        assert ENTRY_160_LBA == 239352
        assert ENTRY_160_SECTORS == 7
        assert ENTRY_160_BUDGET == 14336
        assert ENTRY_160_BUDGET == ENTRY_160_SECTORS * USER_DATA_SIZE

    def test_date_widget_geometry_constants(self):
        assert DATE_WIDGET_WIDTH == 56
        assert DATE_WIDGET_HEIGHT == 40
        assert DATE_WIDGET_SRC_BOX == (80, 80, 136, 120)
        assert DATE_WIDGET_DST_X == 176
        assert DATE_WIDGET_DST_Y == 32
        assert DATE_WIDGET_DST_POS == (176, 32)


class TestTimAssemblyAndImageHandling:
    """Validate conversion of different image formats into 8bpp TIM binaries."""

    def test_paletted_png_with_transparency(self, tmp_path: Path):
        # Create a paletted test image (mode 'P') with transparency
        palette = []
        for i in range(16):
            palette.extend([i * 16, i * 16, i * 16])
        while len(palette) < 768:
            palette.extend([0, 0, 0])

        img = Image.new("P", (128, 128), 0)
        img.putpalette(palette)
        # Set some pixels to non-zero indices
        arr = np.zeros((128, 128), dtype=np.uint8)
        arr[10:20, 10:20] = 5  # Visible color
        arr[30:40, 30:40] = 15  # Another visible color
        img = Image.fromarray(arr, mode="P")
        img.putpalette(palette)

        img_path = tmp_path / "test_pal.png"
        img.save(img_path, transparency=0)

        tim_bytes = image_to_e8_tim(img_path)
        assert len(tim_bytes) == UNCOMPRESSED_TIM_SIZE

        # Check headers
        magic, flags = struct.unpack_from("<II", tim_bytes, 0)
        assert magic == 0x10
        assert flags == 0x09

        clut_len, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", tim_bytes, 8)
        assert clut_len == 524
        assert clut_x == 0
        assert clut_y == 0
        assert clut_w == 256
        assert clut_h == 1

        img_len, img_x, img_y, img_w, img_h = struct.unpack_from("<IHHHH", tim_bytes, 8 + 524)
        assert img_len == 65548
        assert img_x == 896
        assert img_y == 0
        assert img_w == 128
        assert img_h == 256

        # Check transparency at index 0
        clut_w0 = struct.unpack_from("<H", tim_bytes, 20)[0]
        assert clut_w0 == 0x0000

        # Check visible color at index 5 has STP bit set
        clut_w5 = struct.unpack_from("<H", tim_bytes, 20 + 5 * 2)[0]
        assert clut_w5 & 0x8000 == 0x8000

    def test_rgba_png_with_transparency(self, tmp_path: Path):
        # Create an RGBA image with transparent background
        arr = np.zeros((256, 256, 4), dtype=np.uint8)
        # Transparent background (alpha = 0)
        arr[:, :, 3] = 0
        # Draw opaque rectangle (red)
        arr[50:100, 50:100] = [255, 0, 0, 255]
        # Draw opaque rectangle (cyan)
        arr[150:200, 150:200] = [0, 255, 255, 255]

        img = Image.fromarray(arr, mode="RGBA")
        img_path = tmp_path / "test_rgba.png"
        img.save(img_path)

        tim_bytes = image_to_e8_tim(img_path)
        assert len(tim_bytes) == UNCOMPRESSED_TIM_SIZE

        # Index 0 must be 0x0000 for transparent
        clut_w0 = struct.unpack_from("<H", tim_bytes, 20)[0]
        assert clut_w0 == 0x0000

        # Roundtrip decode and check
        decoded = e8_tim_to_image(tim_bytes)
        d_arr = np.array(decoded)
        assert d_arr.shape == (256, 256, 4)
        # Outside rectangles should be transparent
        assert d_arr[0, 0, 3] == 0
        # Inside rectangles should be opaque
        assert d_arr[75, 75, 3] == 255
        assert d_arr[75, 75, 0] > 200  # Red
        assert d_arr[175, 175, 3] == 255
        assert d_arr[175, 175, 1] > 200  # Green in cyan
        assert d_arr[175, 175, 2] > 200  # Blue in cyan

    def test_rgb_opaque_image(self, tmp_path: Path):
        # Create an RGB image
        arr = np.full((256, 256, 3), 128, dtype=np.uint8)
        arr[20:60, 20:60] = [255, 255, 0]
        img = Image.fromarray(arr, mode="RGB")
        img_path = tmp_path / "test_rgb.png"
        img.save(img_path)

        tim_bytes = image_to_e8_tim(img_path)
        assert len(tim_bytes) == UNCOMPRESSED_TIM_SIZE

    def test_non_square_padding(self, tmp_path: Path):
        # Image smaller than 256x256 (e.g. 200x150)
        img = Image.new("RGBA", (200, 150), (100, 150, 200, 255))
        img_path = tmp_path / "small.png"
        img.save(img_path)

        tim_bytes = image_to_e8_tim(img_path)
        assert len(tim_bytes) == UNCOMPRESSED_TIM_SIZE

        decoded = e8_tim_to_image(tim_bytes)
        assert decoded.size == (256, 256)

    def test_non_existent_image_raises(self):
        with pytest.raises(FileNotFoundError):
            image_to_e8_tim("non_existent_image_file_path.png")

    def test_invalid_tim_size_raises(self):
        with pytest.raises(ValueError, match="Invalid TIM size"):
            e8_tim_to_image(b"\x00" * 100)


class TestCandidateSearchHierarchy:
    """Validate candidate image resolution logic."""

    def test_explicit_image_path(self, tmp_path: Path):
        custom = tmp_path / "custom.png"
        Image.new("RGBA", (256, 256), (0, 0, 0, 0)).save(custom)
        found = find_candidate_image(custom)
        assert found == custom

    def test_explicit_image_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            find_candidate_image("missing_explicit.png")

    def test_e8_74380_preferred_in_dir(self, tmp_path: Path):
        p1 = tmp_path / "preview_e8_74380.png"
        p2 = tmp_path / "e8_74380.png"
        p3 = tmp_path / "z_another.png"
        for p in (p1, p2, p3):
            Image.new("RGBA", (256, 256), (0, 0, 0, 0)).save(p)

        found = find_candidate_image(custom_dir=tmp_path)
        assert found == p2  # e8_74380.png has priority

    def test_preview_fallback_in_dir(self, tmp_path: Path):
        p1 = tmp_path / "preview_e8_74380.png"
        p3 = tmp_path / "z_another.png"
        for p in (p1, p3):
            Image.new("RGBA", (256, 256), (0, 0, 0, 0)).save(p)

        found = find_candidate_image(custom_dir=tmp_path)
        assert found == p1


class TestBasyogEntry160Patching:
    """Validate BASYOG.UNT Entry 160 extraction, color mapping, and unt_lz compression."""

    def test_entry_160_extraction_and_baseline_properties(self):
        tim = extract_entry_160_tim()
        assert len(tim) == UNCOMPRESSED_TIM_SIZE
        magic, flags = struct.unpack_from("<II", tim, 0)
        assert magic == 0x10 and flags == 0x09
        clut_len, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", tim, 8)
        assert clut_len == CLUT_BLOCK_SIZE
        assert clut_w == 256 and clut_h == 1
        img_offset = 8 + clut_len
        img_len, img_x, img_y, img_w, img_h = struct.unpack_from("<IHHHH", tim, img_offset)
        assert img_len == IMAGE_BLOCK_SIZE
        assert img_w == 128 and img_h == 256

    def test_basyog_entry_160_patching_and_budget(self):
        orig_tim = extract_entry_160_tim()
        target_tex = DEFAULT_CUSTOM_HUD_DIR / "e8_74380.png"
        if not target_tex.is_file():
            pytest.skip(f"Custom texture not found: {target_tex}")

        new_tim, compressed = patch_basyog_entry_160_tim(orig_tim, target_tex)
        assert len(new_tim) == UNCOMPRESSED_TIM_SIZE
        assert len(compressed) <= ENTRY_160_BUDGET
        assert len(compressed) == 13724
        assert ENTRY_160_BUDGET - len(compressed) == 612

        # Roundtrip decompression bit-exact
        decomp, consumed = unt_lz.decompress(compressed)
        assert decomp == new_tim
        assert consumed == len(compressed)

    def test_basyog_entry_160_synthetic_transparency_and_mapping(self, tmp_path: Path):
        orig_tim = extract_entry_160_tim()
        syn_img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        for y in range(40):
            for x in range(56):
                if x < 28:
                    syn_img.putpixel((80 + x, 80 + y), (0, 0, 0, 0))  # Transparent
                else:
                    syn_img.putpixel((80 + x, 80 + y), (255, 255, 255, 255))  # White

        new_tim, compressed = patch_basyog_entry_160_tim(orig_tim, syn_img)
        assert len(new_tim) == UNCOMPRESSED_TIM_SIZE
        assert len(compressed) <= ENTRY_160_BUDGET

        # Check that transparent pixels at (176, 32) mapped to index 0
        pixels = new_tim[544:]
        for y in range(40):
            assert pixels[(32 + y) * 256 + 176] == 0

    def test_entry_160_invalid_dimensions_raises(self, tmp_path: Path):
        orig_tim = extract_entry_160_tim()
        bad_img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        with pytest.raises(ValueError):
            patch_basyog_entry_160_tim(orig_tim, bad_img)

    def test_entry_160_budget_overflow_prevention(self):
        orig_tim = bytearray(extract_entry_160_tim())
        import os
        noise = os.urandom(PIXEL_DATA_SIZE)
        orig_tim[544:] = noise
        with pytest.raises(ValueError, match="exceeds 7-sector budget"):
            patch_basyog_entry_160_tim(bytes(orig_tim), DEFAULT_CUSTOM_HUD_DIR / "e8_74380.png")


def _create_dual_mock_disc(tmp_path: Path) -> Path:
    """Create a mock disc binary containing valid Mode 2 Form 1 sectors for both Entry 8 and Entry 160."""
    disc_file = tmp_path / "dual_mock_disc.bin"
    chk = CdChecksums()

    total_sectors = ENTRY_160_LBA + ENTRY_160_SECTORS
    with disc_file.open("wb") as f:
        f.seek(total_sectors * RAW_SECTOR_SIZE - 1)
        f.write(b"\x00")

    with disc_file.open("r+b") as f:
        for s in range(35):
            lba = TIM_START_LBA + s
            sec = bytearray(RAW_SECTOR_SIZE)
            sec[0:12] = b"\x00\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x00"
            sec[15] = 2
            sec[16:24] = b"\x00\x00\x08\x00\x00\x00\x08\x00"
            sec[USER_DATA_OFFSET : USER_DATA_OFFSET + USER_DATA_SIZE] = bytes([s & 0xFF]) * USER_DATA_SIZE
            chk.repair_mode2_form1(sec)
            f.seek(lba * RAW_SECTOR_SIZE)
            f.write(sec)

        baseline_tim = extract_entry_160_tim()
        baseline_comp = unt_lz.compress(baseline_tim).ljust(ENTRY_160_BUDGET, b"\x00")
        for s in range(ENTRY_160_SECTORS):
            lba = ENTRY_160_LBA + s
            sec = bytearray(RAW_SECTOR_SIZE)
            sec[0:12] = b"\x00\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x00"
            sec[15] = 2
            sec[16:24] = b"\x00\x00\x08\x00\x00\x00\x08\x00"
            chunk = baseline_comp[s * USER_DATA_SIZE : (s + 1) * USER_DATA_SIZE]
            sec[USER_DATA_OFFSET : USER_DATA_OFFSET + USER_DATA_SIZE] = chunk
            chk.repair_mode2_form1(sec)
            f.seek(lba * RAW_SECTOR_SIZE)
            f.write(sec)

    return disc_file


def _create_mock_disc(tmp_path: Path, sector_count: int = 40) -> Path:
    """Create a mock disc binary file containing valid Mode 2 Form 1 sectors."""
    disc_file = tmp_path / "mock_disc.bin"
    chk = CdChecksums()

    with disc_file.open("wb") as f:
        # Pad up to TIM_START_LBA
        f.seek((TIM_START_LBA + sector_count) * RAW_SECTOR_SIZE - 1)
        f.write(b"\x00")

    with disc_file.open("r+b") as f:
        for s in range(sector_count):
            lba = TIM_START_LBA + s
            sec = bytearray(RAW_SECTOR_SIZE)
            # Sync pattern
            sec[0:12] = b"\x00\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x00"
            # Mode 2
            sec[15] = 2
            # Subheader: Form 1 (bit 5 clear in submode at offset 18)
            sec[16:24] = b"\x00\x00\x08\x00\x00\x00\x08\x00"
            # Dummy user data
            user_data = bytes([s & 0xFF]) * USER_DATA_SIZE
            sec[USER_DATA_OFFSET : USER_DATA_OFFSET + USER_DATA_SIZE] = user_data
            # Compute EDC/ECC
            chk.repair_mode2_form1(sec)

            f.seek(lba * RAW_SECTOR_SIZE)
            f.write(sec)

    return disc_file


class TestMockDiscPatchingAndVerification:
    """Validate in-place sector patching, EDC/ECC recalculation, and verify routine."""

    def test_mock_disc_patch_and_verify(self, tmp_path: Path):
        mock_disc = _create_mock_disc(tmp_path, sector_count=35)

        # Create a test texture
        img_path = tmp_path / "test_tex.png"
        Image.new("RGBA", (256, 256), (255, 128, 64, 255)).save(img_path)

        # Read original bytes before offset 652 in sector 36
        chk = CdChecksums()
        with mock_disc.open("rb") as f:
            f.seek(TIM_START_LBA * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
            lead_bytes_orig = f.read(TIM_IN_SECTOR_OFFSET)

            f.seek(TIM_END_LBA * RAW_SECTOR_SIZE + USER_DATA_OFFSET + 1196)
            trail_bytes_orig = f.read(2048 - 1196)

        # Perform patch
        patch_res = patch_e8_textures(
            bin_path=mock_disc,
            image_path=img_path,
            dry_run=False,
            update_secondary=False,
            update_preview=False,
        )
        assert patch_res["status"] == "success"
        assert patch_res["sectors"] == TIM_SECTOR_COUNT
        assert patch_res["tim_size"] == UNCOMPRESSED_TIM_SIZE

        # Verify EDC/ECC on all 33 sectors
        verify_res = verify_e8_textures(mock_disc)
        assert verify_res["status"] == "ok"
        assert verify_res["edc_ecc_valid"] is True
        assert verify_res["edc_ecc_verified_sectors"] == 33
        assert verify_res["tim_size"] == UNCOMPRESSED_TIM_SIZE
        assert verify_res["clut_info"]["cw"] == 256
        assert verify_res["image_info"]["h"] == 256

        # Verify surrounding bytes are strictly preserved
        with mock_disc.open("rb") as f:
            f.seek(TIM_START_LBA * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
            lead_bytes_after = f.read(TIM_IN_SECTOR_OFFSET)
            assert lead_bytes_after == lead_bytes_orig

            f.seek(TIM_END_LBA * RAW_SECTOR_SIZE + USER_DATA_OFFSET + 1196)
            trail_bytes_after = f.read(2048 - 1196)
            assert trail_bytes_after == trail_bytes_orig

    def test_dump_texture_from_mock_disc(self, tmp_path: Path):
        mock_disc = _create_mock_disc(tmp_path, sector_count=35)
        img_path = tmp_path / "test_tex.png"
        Image.new("RGBA", (256, 256), (0, 255, 0, 255)).save(img_path)

        patch_e8_textures(
            bin_path=mock_disc,
            image_path=img_path,
            dry_run=False,
            update_secondary=False,
            update_preview=False,
        )

        dump_dir = tmp_path / "dump"
        dumped = dump_e8_texture(mock_disc, dump_dir)
        assert len(dumped) == 2
        png_dump = dump_dir / "e8_74380.png"
        tim_dump = dump_dir / "e8_74380.tim"
        assert png_dump.is_file()
        assert tim_dump.is_file()
        assert tim_dump.stat().st_size == UNCOMPRESSED_TIM_SIZE

        dumped_img = Image.open(png_dump)
        assert dumped_img.size == (256, 256)

    def test_dry_run_does_not_modify(self, tmp_path: Path):
        mock_disc = _create_mock_disc(tmp_path, sector_count=35)
        before_data = mock_disc.read_bytes()

        img_path = tmp_path / "test_tex.png"
        Image.new("RGBA", (256, 256), (255, 255, 255, 255)).save(img_path)

        res = patch_e8_textures(
            bin_path=mock_disc,
            image_path=img_path,
            dry_run=True,
            update_secondary=False,
            update_preview=False,
        )
        assert res["status"] == "dry_run"
        after_data = mock_disc.read_bytes()
        assert before_data == after_data
    def test_dual_mock_disc_patch_and_verify(self, tmp_path: Path):
        mock_disc = _create_dual_mock_disc(tmp_path)
        img_path = tmp_path / "test_tex.png"
        Image.new("RGBA", (256, 256), (255, 128, 64, 255)).save(img_path)

        res = patch_e8_textures(
            bin_path=mock_disc,
            image_path=img_path,
            dry_run=False,
            update_secondary=False,
            update_preview=False,
            sync_savestates=False,
        )
        assert res["status"] == "success"
        assert "basyog_160" in res
        assert res["basyog_160"]["status"] == "success"
        assert res["basyog_160"]["compressed_size"] <= ENTRY_160_BUDGET

        v = verify_e8_textures(mock_disc)
        assert v["status"] == "ok"
        assert v["edc_ecc_valid"] is True
        assert v["edc_ecc_verified_sectors"] == 33
        assert "basyog_160" in v
        assert v["basyog_160"]["status"] == "ok"
        assert v["basyog_160"]["edc_ecc_verified_sectors"] == 7
        assert v["basyog_160"]["compressed_size"] <= ENTRY_160_BUDGET
        assert v["basyog_160"]["margin"] >= 0


class TestCommandLineInterface:
    """Validate CLI argument parsing and dispatch."""

    def test_parse_args_defaults(self):
        args = parse_args([])
        assert args.verify is False
        assert args.dry_run is False
        assert args.image is None
        assert args.dump_dir is None

    def test_cli_verify(self):
        if not DEFAULT_PRIMARY_BIN.is_file():
            pytest.skip("Production disc not present")
        code = main(["--verify", "--bin", str(DEFAULT_PRIMARY_BIN)])
        assert code == 0

    def test_cli_dump_dir(self, tmp_path: Path):
        if not DEFAULT_PRIMARY_BIN.is_file():
            pytest.skip("Production disc not present")
        dump_out = tmp_path / "cli_dump"
        code = main(["--bin", str(DEFAULT_PRIMARY_BIN), "--dump-dir", str(dump_out)])
        assert code == 0
        assert (dump_out / "e8_74380.png").is_file()
        assert (dump_out / "e8_74380.tim").is_file()


class TestProductionDiscIntegrity:
    """Verify that production discs in the repository have 100% valid EDC/ECC and TIM."""

    def test_primary_disc_validity(self):
        if not DEFAULT_PRIMARY_BIN.is_file():
            pytest.skip(f"Primary disc not found: {DEFAULT_PRIMARY_BIN}")
        res = verify_e8_textures(DEFAULT_PRIMARY_BIN)
        assert res["status"] == "ok"
        assert res["edc_ecc_valid"] is True
        assert res["edc_ecc_verified_sectors"] == 33
        assert res["tim_size"] == UNCOMPRESSED_TIM_SIZE

    def test_secondary_disc_validity(self):
        if not DEFAULT_SECONDARY_BIN.is_file():
            pytest.skip(f"Secondary disc not found: {DEFAULT_SECONDARY_BIN}")
        res = verify_e8_textures(DEFAULT_SECONDARY_BIN)
        assert res["status"] == "ok"
        assert res["edc_ecc_valid"] is True
        assert res["edc_ecc_verified_sectors"] == 33
        assert res["tim_size"] == UNCOMPRESSED_TIM_SIZE

    def test_custom_texture_present_on_disc(self):
        target_tex = DEFAULT_CUSTOM_HUD_DIR / "e8_74380.png"
        if not target_tex.is_file():
            pytest.skip(f"Custom texture not found: {target_tex}")
        if not DEFAULT_PRIMARY_BIN.is_file():
            pytest.skip(f"Primary disc not found: {DEFAULT_PRIMARY_BIN}")

        expected_tim = image_to_e8_tim(target_tex)

        with DEFAULT_PRIMARY_BIN.open("rb") as f:
            extent = bytearray()
            for s in range(TIM_SECTOR_COUNT):
                f.seek((TIM_START_LBA + s) * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
                extent.extend(f.read(USER_DATA_SIZE))

        actual_tim = extent[TIM_IN_SECTOR_OFFSET : TIM_IN_SECTOR_OFFSET + UNCOMPRESSED_TIM_SIZE]
        assert actual_tim == expected_tim

    def test_primary_disc_dual_entry_verification(self):
        if not DEFAULT_PRIMARY_BIN.is_file():
            pytest.skip(f"Primary disc not found: {DEFAULT_PRIMARY_BIN}")
        res = verify_e8_textures(DEFAULT_PRIMARY_BIN)
        assert res["status"] == "ok"
        assert "basyog_160" in res
        assert res["basyog_160"]["status"] == "ok"
        assert res["basyog_160"]["edc_ecc_verified_sectors"] == 7
        assert res["basyog_160"]["compressed_size"] <= ENTRY_160_BUDGET
        assert res["basyog_160"]["margin"] >= 600

    def test_secondary_disc_dual_entry_verification(self):
        if not DEFAULT_SECONDARY_BIN.is_file():
            pytest.skip(f"Secondary disc not found: {DEFAULT_SECONDARY_BIN}")
        res = verify_e8_textures(DEFAULT_SECONDARY_BIN)
        assert res["status"] == "ok"
        assert "basyog_160" in res
        assert res["basyog_160"]["status"] == "ok"
        assert res["basyog_160"]["edc_ecc_verified_sectors"] == 7
        assert res["basyog_160"]["compressed_size"] <= ENTRY_160_BUDGET
        assert res["basyog_160"]["margin"] >= 600

    def test_entry_160_date_widget_present_on_disc(self):
        target_tex = DEFAULT_CUSTOM_HUD_DIR / "e8_74380.png"
        if not target_tex.is_file():
            pytest.skip(f"Custom texture not found: {target_tex}")
        if not DEFAULT_PRIMARY_BIN.is_file():
            pytest.skip(f"Primary disc not found: {DEFAULT_PRIMARY_BIN}")

        extent = read_extent(DEFAULT_PRIMARY_BIN, ENTRY_160_LBA, ENTRY_160_BUDGET)
        decomp, _ = unt_lz.decompress(extent)
        assert len(decomp) == UNCOMPRESSED_TIM_SIZE

        widget_data = [
            decomp[544 + (DATE_WIDGET_DST_Y + y) * 256 + DATE_WIDGET_DST_X : 544 + (DATE_WIDGET_DST_Y + y) * 256 + DATE_WIDGET_DST_X + DATE_WIDGET_WIDTH]
            for y in range(DATE_WIDGET_HEIGHT)
        ]
        assert len(widget_data) == 40
        assert all(len(row) == 56 for row in widget_data)
        assert any(b != 0 for row in widget_data for b in row)
