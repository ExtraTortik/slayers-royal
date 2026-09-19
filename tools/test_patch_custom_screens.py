#!/usr/bin/env python3
"""Unit tests for tools/patch_custom_screens.py.

Validates:
1. Catalog loading and specifications in translations/custom_screens_ru.json:
   - OPT 203: "БЕСКОНЕЧНАЯ ИГРА" (LBA 228713, 1 sec, 4bpp, 64x16)
   - OPT 221: "ХОД" (LBA 228916, 3 sec, 8bpp, 80x64)
   - OPT 225: "СТАРТ" (LBA 228926, 1 sec, 4bpp, 64x16)
   - PROG 323: "КОНЕЦ ИГРЫ" (LBA 233202, 5 sec, 8bpp, 320x240, LZSS mode 1)
2. Discovery of custom screen PNG files in data/custom_screens/ and alias parsing.
3. TIM encoding for OPT 203, OPT 221, OPT 225, and PROG 323.
4. unt_lz compression and sector budget enforcement (<= 10,240 B) for PROG 323.
5. Sector budget verification and bit-exact Mode 2 Form 1 EDC/ECC repair.
6. Full verification suite execution on target disc images.
7. Visual preview generation (640x360 RGBA).
8. CLI argument parsing and dry-run execution.
"""

from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile

import numpy as np
from PIL import Image
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
for p in (REPO_ROOT, PATCH_REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools.patch_custom_screens import (
    CUSTOM_SCREENS_SPECS,
    DEFAULT_CATALOG,
    DEFAULT_PREVIEW_PATH,
    DEFAULT_SCREENS_DIR,
    DEFAULT_TARGET_BIN,
    ENTRY_ID_MAP,
    RAW_SECTOR_SIZE,
    USER_DATA_OFFSET,
    USER_DATA_SIZE,
    encode_custom_screen,
    encode_opt_203,
    encode_opt_221,
    encode_opt_225,
    encode_prog_323,
    find_custom_screens,
    generate_preview,
    load_catalog,
    parse_cli_args,
    parse_entry_id,
    patch_custom_screens,
    patch_disc_extent,
    tim_to_rgba,
    verify_custom_screens,
)

try:
    from localization.disc import CdChecksums
except ImportError:
    from patch_repo.localization.disc import CdChecksums

try:
    from localization import unt_lz
except ImportError:
    from patch_repo.localization import unt_lz


class TestCustomScreensCatalog:
    """Tests for translations/custom_screens_ru.json catalog."""

    def test_catalog_file_exists(self):
        assert DEFAULT_CATALOG.is_file(), f"Catalog not found: {DEFAULT_CATALOG}"

    def test_catalog_structure(self):
        data = load_catalog(DEFAULT_CATALOG)
        assert "metadata" in data
        assert "screens" in data
        screens = data["screens"]
        assert len(screens) == 4

        entry_indices = {s["entry_index"] for s in screens}
        assert entry_indices == {203, 221, 225, 323}

    def test_entry_specifications(self):
        data = load_catalog(DEFAULT_CATALOG)
        screens_by_idx = {s["entry_index"]: s for s in data["screens"]}

        # 1. OPT 203
        s203 = screens_by_idx[203]
        assert s203["archive"] == "OPT.UNT"
        assert s203["lba"] == 228713
        assert s203["sectors"] == 1
        assert s203["budget"] == 2048
        assert s203["width"] == 64
        assert s203["height"] == 16
        assert s203["bpp"] == 4
        assert s203["clut_colors"] == 16
        assert s203["compressed"] is False

        # 2. OPT 221
        s221 = screens_by_idx[221]
        assert s221["archive"] == "OPT.UNT"
        assert s221["lba"] == 228916
        assert s221["sectors"] == 3
        assert s221["budget"] == 6144
        assert s221["width"] == 80
        assert s221["height"] == 64
        assert s221["bpp"] == 8
        assert s221["clut_colors"] == 256
        assert s221["compressed"] is False

        # 3. OPT 225
        s225 = screens_by_idx[225]
        assert s225["archive"] == "OPT.UNT"
        assert s225["lba"] == 228926
        assert s225["sectors"] == 1
        assert s225["budget"] == 2048
        assert s225["width"] == 64
        assert s225["height"] == 16
        assert s225["bpp"] == 4
        assert s225["clut_colors"] == 16
        assert s225["compressed"] is False

        # 4. PROG 323
        s323 = screens_by_idx[323]
        assert s323["archive"] == "PROG.UNT"
        assert s323["lba"] == 233202
        assert s323["sectors"] == 5
        assert s323["budget"] == 10240
        assert s323["width"] == 320
        assert s323["height"] == 240
        assert s323["bpp"] == 8
        assert s323["clut_colors"] == 256
        assert s323["compressed"] is True


class TestDiscoveryAndIdentifiers:
    """Tests for file discovery and identifier resolution."""

    def test_find_custom_screens(self):
        found = find_custom_screens(DEFAULT_SCREENS_DIR)
        assert len(found) == 4, f"Expected 4 custom screens in {DEFAULT_SCREENS_DIR}, got {len(found)}: {found}"
        assert set(found.keys()) == {203, 221, 225, 323}
        for idx, p in found.items():
            assert p.is_file(), f"File for entry {idx} does not exist: {p}"

    def test_parse_entry_id(self):
        assert parse_entry_id(203) == 203
        assert parse_entry_id("203") == 203
        assert parse_entry_id("turn") == 203
        assert parse_entry_id("opt_203") == 203

        assert parse_entry_id(221) == 221
        assert parse_entry_id("unlimited_play") == 221
        assert parse_entry_id("opt_221") == 221

        assert parse_entry_id(225) == 225
        assert parse_entry_id("start") == 225
        assert parse_entry_id("opt_225") == 225

        assert parse_entry_id(323) == 323
        assert parse_entry_id("game_over") == 323
        assert parse_entry_id("prog_323") == 323

        with pytest.raises(ValueError):
            parse_entry_id("nonexistent_screen")


class TestTimEncoding:
    """Tests for TIM encoding of each individual custom screen."""

    @pytest.fixture
    def screens_files(self):
        found = find_custom_screens(DEFAULT_SCREENS_DIR)
        assert len(found) == 4
        return found

    def test_encode_opt_203(self, screens_files):
        payload = encode_opt_203(screens_files[203])
        assert len(payload) == 2048, "Payload must be padded to 2048 bytes (1 sector)"

        # TIM header
        magic, flag = struct.unpack_from("<II", payload, 0)
        assert magic == 0x10
        assert flag == 0x08  # 4bpp with CLUT

        # CLUT block: len=44, x=0, y=497, w=16, h=1
        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", payload, 8)
        assert clut_len == 44
        assert (cx, cy, cw, ch) == (0, 497, 16, 1)

        # IMG block: len=1036, x=640, y=448, w=16, h=16
        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", payload, 8 + clut_len)
        assert img_len == 1036
        assert (ix, iy, iw, ih) == (640, 448, 16, 16)

        # Trailing bytes in sector must be zero padded
        assert all(b == 0 for b in payload[1088:])

    def test_encode_opt_221(self, screens_files):
        payload = encode_opt_221(screens_files[221])
        assert len(payload) == 6144, "Payload must be padded to 6144 bytes (3 sectors)"

        magic, flag = struct.unpack_from("<II", payload, 0)
        assert magic == 0x10
        assert flag == 0x09  # 8bpp with CLUT

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", payload, 8)
        assert clut_len == 524
        assert (cx, cy, cw, ch) == (0, 489, 256, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", payload, 8 + clut_len)
        assert img_len == 5132
        assert (ix, iy, iw, ih) == (960, 0, 40, 64)

        assert all(b == 0 for b in payload[5664:])

    def test_encode_opt_225(self, screens_files):
        payload = encode_opt_225(screens_files[225])
        assert len(payload) == 2048, "Payload must be padded to 2048 bytes (1 sector)"

        magic, flag = struct.unpack_from("<II", payload, 0)
        assert magic == 0x10
        assert flag == 0x08  # 4bpp with CLUT

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", payload, 8)
        assert clut_len == 44
        assert (cx, cy, cw, ch) == (0, 490, 16, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", payload, 8 + clut_len)
        assert img_len == 524
        assert (ix, iy, iw, ih) == (1000, 0, 16, 16)

        assert all(b == 0 for b in payload[576:])

    def test_encode_prog_323(self, screens_files):
        uncomp_tim, payload = encode_prog_323(screens_files[323])
        assert len(uncomp_tim) == 77344, "Uncompressed TIM must be 77,344 bytes"
        assert len(payload) == 10240, "Payload must be padded to 10,240 bytes (5 sectors)"

        # Decompress payload with unt_lz
        decomp, consumed = unt_lz.decompress(payload)
        assert consumed <= 10240, f"Compressed data consumed {consumed} bytes > 10,240 budget!"
        assert decomp == uncomp_tim, "Roundtrip decompression must match uncompressed TIM"

        magic, flag = struct.unpack_from("<II", uncomp_tim, 0)
        assert magic == 0x10
        assert flag == 0x09  # 8bpp with CLUT

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", uncomp_tim, 8)
        assert clut_len == 524
        assert (cx, cy, cw, ch) == (0, 480, 256, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", uncomp_tim, 8 + clut_len)
        assert img_len == 76812
        assert (ix, iy, iw, ih) == (0, 0, 160, 240)


class TestDiscVerificationAndEdcEcc:
    """Tests for disc patching, EDC/ECC calculations, and verification."""

    def test_verify_production_disc(self):
        if not DEFAULT_TARGET_BIN.is_file():
            pytest.skip("Target disc image not available")

        results = verify_custom_screens(DEFAULT_TARGET_BIN)
        assert len(results) == 4
        for r in results:
            assert r["edc_ecc_valid"] is True
            assert r["tim_valid"] is True
            assert r["consumed_bytes"] <= r["budget_bytes"]

    def test_patch_extent_edc_ecc_recalculation(self):
        chk = CdChecksums()
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
            temp_path = Path(tf.name)

        try:
            # Create a mock disc image with 2 sectors
            sec_blank = bytearray(RAW_SECTOR_SIZE)
            sec_blank[0:12] = b"\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x00"
            sec_blank[15] = 2  # Mode 2
            sec_blank[18] = 0x08  # Form 1

            with temp_path.open("wb") as f:
                f.write(sec_blank * 2)

            test_payload = b"TEST_CUSTOM_SCREEN_DATA" * 50
            padded_payload = test_payload.ljust(USER_DATA_SIZE, b"\x00")

            patch_disc_extent(temp_path, lba=0, payload=padded_payload)

            with temp_path.open("rb") as f:
                sec_patched = f.read(RAW_SECTOR_SIZE)

            # Check EDC and ECC
            expected_edc = chk.compute_edc(sec_patched[0x10:0x818])
            assert sec_patched[0x818:0x81C] == expected_edc

            expected_ecc_p = chk.compute_ecc(sec_patched[0x10:], 86, 24, 2, 86)
            assert sec_patched[0x81C:0x8C8] == expected_ecc_p

            expected_ecc_q = chk.compute_ecc(sec_patched[0x10:], 52, 43, 86, 88)
            assert sec_patched[0x8C8:0x930] == expected_ecc_q

        finally:
            if temp_path.is_file():
                temp_path.unlink()


class TestPreviewAndCli:
    """Tests for visual preview generation and CLI."""

    def test_generate_preview(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            prev_path = Path(tf.name)

        try:
            out = generate_preview(output_path=prev_path)
            assert out.is_file()
            img = Image.open(out)
            assert img.size == (640, 360)
            assert img.mode == "RGBA"
        finally:
            if prev_path.is_file():
                prev_path.unlink()

    def test_cli_dry_run(self):
        results = patch_custom_screens(
            bin_path=DEFAULT_TARGET_BIN,
            screens_dir=DEFAULT_SCREENS_DIR,
            dry_run=True,
        )
        assert len(results) == 4
        for r in results:
            assert r["dry_run"] is True
            assert r["status"] == "dry_run"

    def test_cli_args_parsing(self):
        args = parse_cli_args(["--dry-run", "--entry", "game_over", "--verify"])
        assert args.dry_run is True
        assert args.entry == "game_over"
        assert args.verify is True
