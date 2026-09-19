#!/usr/bin/env python3
"""Unit tests for tools/patch_extra_screens.py.

Validates:
1. Specifications of all 15 translated screens/textures in EXTRA_SCREENS_SPECS.
2. Discovery of source PNG files and alias resolution.
3. Hardware-accurate TIM encoding for OPT 137..232, OPTCINE 01, and PROG 54..57, 317, 324.
4. Sector budget constraints and unt_lz LZSS mode 1 compression for PROG entries.
5. Bit-exact Mode 2 Form 1 EDC/ECC and TIM structure verification on target disc.
6. Dry-run patching behavior without modifying disc images.
"""

from __future__ import annotations

from pathlib import Path
import struct
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
for p in (REPO_ROOT, PATCH_REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools.patch_extra_screens import (
    DEFAULT_TARGET_BIN,
    EXTRA_SCREENS_SPECS,
    FALLBACK_CLUTS,
    encode_opt_screen,
    encode_optcine_01,
    encode_prog_screen,
    encode_screen,
    find_screen_images,
    parse_entry_id,
    patch_extra_screens,
    verify_extra_screens,
)

try:
    from patch_repo.localization import unt_lz
except ImportError:
    try:
        from localization import unt_lz
    except ImportError:
        unt_lz = None


class TestExtraScreensSpecs:
    """Validate specifications of all 15 translated assets."""

    def test_all_15_entries_defined(self):
        expected_ids = {
            "opt_137",
            "opt_171",
            "opt_172",
            "opt_173",
            "opt_174",
            "opt_206",
            "opt_207",
            "opt_232",
            "optcine_01",
            "prog_054",
            "prog_055",
            "prog_056",
            "prog_057",
            "prog_317",
            "prog_324",
        }
        assert set(EXTRA_SCREENS_SPECS.keys()) == expected_ids
        assert len(EXTRA_SCREENS_SPECS) == 15

    def test_spec_required_keys(self):
        required_keys = {
            "id",
            "name",
            "archive",
            "entry_index",
            "lba",
            "sector_offset",
            "sectors",
            "budget",
            "width",
            "height",
            "bpp",
            "vram_x",
            "vram_y",
            "vram_w",
            "clut_x",
            "clut_y",
            "clut_w",
            "clut_h",
            "clut_colors",
            "clut_block_len",
            "img_block_len",
            "raw_tim_len",
            "compressed",
            "filenames",
        }
        for spec_id, spec in EXTRA_SCREENS_SPECS.items():
            missing = required_keys - set(spec.keys())
            assert not missing, f"Spec {spec_id} missing keys: {missing}"
            assert spec["budget"] == spec["sectors"] * 2048

    def test_archive_specific_invariants(self):
        for spec_id, spec in EXTRA_SCREENS_SPECS.items():
            if spec["archive"] == "OPT.UNT":
                assert spec["bpp"] == 4
                assert spec["compressed"] is False
                assert spec["sector_offset"] == 0
                assert spec["clut_colors"] == 16
                assert spec["clut_block_len"] == 44
            elif spec["archive"] == "OPTCINE.GRP":
                assert spec["bpp"] == 4
                assert spec["compressed"] is False
                assert spec["sector_offset"] == 544
                assert spec["clut_colors"] == 256
                assert spec["clut_block_len"] == 524
                assert spec["raw_tim_len"] == 33312
            elif spec["archive"] == "PROG.UNT":
                assert spec["compressed"] is True
                assert spec["sector_offset"] == 0
                if spec["bpp"] == 8:
                    assert spec["clut_colors"] == 256
                    assert spec["clut_block_len"] == 524
                    assert spec["raw_tim_len"] == 72224
                elif spec["bpp"] == 4:
                    assert spec["clut_colors"] == 16
                    assert spec["clut_block_len"] == 44


class TestDiscoveryAndIdentifiers:
    """Validate file discovery and identifier resolution."""

    def test_find_all_source_images(self):
        images = find_screen_images()
        assert len(images) == 15, f"Expected 15 source images, found {len(images)}: {list(images.keys())}"
        for spec_id, path in images.items():
            assert path.is_file(), f"File for {spec_id} does not exist: {path}"

    def test_parse_entry_id(self):
        assert parse_entry_id("opt_137") == "opt_137"
        assert parse_entry_id(137) == "opt_137"
        assert parse_entry_id("137") == "opt_137"
        assert parse_entry_id("opt137") == "opt_137"

        assert parse_entry_id("opt_171") == "opt_171"
        assert parse_entry_id(171) == "opt_171"
        assert parse_entry_id("opt_232") == "opt_232"
        assert parse_entry_id(232) == "opt_232"

        assert parse_entry_id("optcine_01") == "optcine_01"
        assert parse_entry_id("optcine") == "optcine_01"
        assert parse_entry_id("optcine01") == "optcine_01"

        assert parse_entry_id("prog_054") == "prog_054"
        assert parse_entry_id(54) == "prog_054"
        assert parse_entry_id("54") == "prog_054"
        assert parse_entry_id("prog54") == "prog_054"
        assert parse_entry_id("prog_54") == "prog_054"


        assert parse_entry_id("prog_317") == "prog_317"
        assert parse_entry_id(317) == "prog_317"
        assert parse_entry_id("317") == "prog_317"
        assert parse_entry_id("prog317") == "prog_317"

        assert parse_entry_id("prog_324") == "prog_324"
        assert parse_entry_id(324) == "prog_324"
        assert parse_entry_id("324") == "prog_324"
        assert parse_entry_id("prog324") == "prog_324"
        with pytest.raises(ValueError):
            parse_entry_id("invalid_asset_name_xyz")


class TestTimEncoding:
    """Validate TIM encoding for all 15 individual assets."""

    @pytest.fixture
    def images(self):
        return find_screen_images()

    def test_encode_opt_137(self, images):
        tim_bytes, payload = encode_opt_screen("opt_137", images["opt_137"])
        assert len(tim_bytes) == 2624
        assert len(payload) == 4096

        magic, flag = struct.unpack_from("<II", tim_bytes, 0)
        assert magic == 0x10 and flag == 0x08

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim_bytes, 8)
        assert (clut_len, cx, cy, cw, ch) == (44, 0, 507, 16, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", tim_bytes, 8 + clut_len)
        assert (img_len, ix, iy, iw, ih) == (2572, 640, 480, 40, 32)
        assert all(b == 0 for b in payload[2624:])

    def test_encode_opt_171(self, images):
        tim_bytes, payload = encode_opt_screen("opt_171", images["opt_171"])
        assert len(tim_bytes) == 6208
        assert len(payload) == 8192

        magic, flag = struct.unpack_from("<II", tim_bytes, 0)
        assert magic == 0x10 and flag == 0x08

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim_bytes, 8)
        assert (clut_len, cx, cy, cw, ch) == (44, 0, 494, 16, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", tim_bytes, 8 + clut_len)
        assert (img_len, ix, iy, iw, ih) == (6156, 960, 16, 64, 48)

    def test_encode_opt_172(self, images):
        tim_bytes, payload = encode_opt_screen("opt_172", images["opt_172"])
        assert len(tim_bytes) == 2752
        assert len(payload) == 4096

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim_bytes, 8)
        assert (clut_len, cx, cy, cw, ch) == (44, 0, 495, 16, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", tim_bytes, 8 + clut_len)
        assert (img_len, ix, iy, iw, ih) == (2700, 896, 16, 42, 32)

    def test_encode_opt_173(self, images):
        tim_bytes, payload = encode_opt_screen("opt_173", images["opt_173"])
        assert len(tim_bytes) == 1344
        assert len(payload) == 2048

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim_bytes, 8)
        assert (clut_len, cx, cy, cw, ch) == (44, 0, 503, 16, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", tim_bytes, 8 + clut_len)
        assert (img_len, ix, iy, iw, ih) == (1292, 960, 0, 40, 16)

    def test_encode_opt_174(self, images):
        tim_bytes, payload = encode_opt_screen("opt_174", images["opt_174"])
        assert len(tim_bytes) == 98368
        assert len(payload) == 100352

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim_bytes, 8)
        assert (clut_len, cx, cy, cw, ch) == (44, 0, 491, 16, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", tim_bytes, 8 + clut_len)
        assert (img_len, ix, iy, iw, ih) == (98316, 640, 0, 192, 256)

    def test_encode_opt_206(self, images):
        tim_bytes, payload = encode_opt_screen("opt_206", images["opt_206"])
        assert len(tim_bytes) == 3136
        assert len(payload) == 4096

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim_bytes, 8)
        assert (clut_len, cx, cy, cw, ch) == (44, 0, 484, 16, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", tim_bytes, 8 + clut_len)
        assert (img_len, ix, iy, iw, ih) == (3084, 448, 256, 48, 32)

    def test_encode_opt_207(self, images):
        tim_bytes, payload = encode_opt_screen("opt_207", images["opt_207"])
        assert len(tim_bytes) == 3136
        assert len(payload) == 4096

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim_bytes, 8)
        assert (clut_len, cx, cy, cw, ch) == (44, 0, 485, 16, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", tim_bytes, 8 + clut_len)
        assert (img_len, ix, iy, iw, ih) == (3084, 448, 288, 48, 32)

    def test_encode_opt_232(self, images):
        tim_bytes, payload = encode_opt_screen("opt_232", images["opt_232"])
        assert len(tim_bytes) == 35904
        assert len(payload) == 36864

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim_bytes, 8)
        assert (clut_len, cx, cy, cw, ch) == (44, 0, 480, 16, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", tim_bytes, 8 + clut_len)
        assert (ix, iy, iw, ih) == (320, 0, 80, 224)
        assert img_len in (71692, 35852)

    def test_encode_optcine_01(self, images):
        tim_bytes, payload = encode_optcine_01(images["optcine_01"])
        assert len(tim_bytes) == 33312
        assert len(payload) == 33312

        magic, flag = struct.unpack_from("<II", tim_bytes, 0)
        assert magic == 0x10 and flag == 0x08

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim_bytes, 8)
        assert (clut_len, cx, cy, cw, ch) == (524, 0, 496, 16, 16)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", tim_bytes, 8 + clut_len)
        assert (img_len, ix, iy, iw, ih) == (32780, 768, 256, 64, 256)

    def test_encode_prog_54(self, images):
        uncomp_tim, payload = encode_prog_screen("prog_054", images["prog_054"])
        assert len(uncomp_tim) == 72224
        assert len(payload) == 14336
        decomp, consumed = unt_lz.decompress(payload)
        assert decomp == uncomp_tim
        assert consumed <= 14336

    def test_encode_prog_55(self, images):
        uncomp_tim, payload = encode_prog_screen("prog_055", images["prog_055"])
        assert len(uncomp_tim) == 72224
        assert len(payload) == 14336
        decomp, consumed = unt_lz.decompress(payload)
        assert decomp == uncomp_tim
        assert consumed <= 14336

    def test_encode_prog_56(self, images):
        uncomp_tim, payload = encode_prog_screen("prog_056", images["prog_056"])
        assert len(uncomp_tim) == 72224
        assert len(payload) == 16384
        decomp, consumed = unt_lz.decompress(payload)
        assert decomp == uncomp_tim
        assert consumed <= 16384

    def test_encode_prog_57(self, images):
        uncomp_tim, payload = encode_prog_screen("prog_057", images["prog_057"])
        assert len(uncomp_tim) == 72224
        assert len(payload) == 14336
        decomp, consumed = unt_lz.decompress(payload)
        assert decomp == uncomp_tim
        assert consumed <= 14336

    def test_encode_prog_317(self, images):
        uncomp_tim, payload = encode_prog_screen("prog_317", images["prog_317"])
        assert len(uncomp_tim) == 19264
        assert len(payload) == 4096

        magic, flag = struct.unpack_from("<II", uncomp_tim, 0)
        assert magic == 0x10 and flag == 0x08

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", uncomp_tim, 8)
        assert (clut_len, cx, cy, cw, ch) == (44, 0, 480, 16, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", uncomp_tim, 8 + clut_len)
        assert (img_len, ix, iy, iw, ih) == (19212, 0, 0, 20, 480)

        decomp, consumed = unt_lz.decompress(payload)
        assert decomp == uncomp_tim
        assert consumed <= 4096

    def test_encode_prog_324(self, images):
        uncomp_tim, payload = encode_prog_screen("prog_324", images["prog_324"])
        assert len(uncomp_tim) == 5824
        assert len(payload) == 4096

        magic, flag = struct.unpack_from("<II", uncomp_tim, 0)
        assert magic == 0x10 and flag == 0x08

        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", uncomp_tim, 8)
        assert (clut_len, cx, cy, cw, ch) == (44, 0, 480, 16, 1)

        img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", uncomp_tim, 8 + clut_len)
        assert (img_len, ix, iy, iw, ih) == (5772, 0, 0, 12, 240)

        decomp, consumed = unt_lz.decompress(payload)
        assert decomp == uncomp_tim
        assert consumed <= 4096


class TestBudgetConstraints:
    """Verify sector budget constraints for all 15 entries."""

    def test_all_payloads_within_budget(self):
        images = find_screen_images()
        for spec_id, spec in EXTRA_SCREENS_SPECS.items():
            tim_bytes, payload = encode_screen(spec_id, images[spec_id])
            if spec["archive"] == "OPTCINE.GRP":
                assert len(payload) == 33312
                assert 544 + len(payload) <= spec["budget"]
            else:
                assert len(payload) == spec["budget"]
                if spec["compressed"]:
                    decomp, consumed = unt_lz.decompress(payload)
                    assert consumed <= spec["budget"]


class TestDiscVerification:
    """Verify patched disc image integrity."""

    @pytest.mark.skipif(not DEFAULT_TARGET_BIN.is_file(), reason="Target disc image not found")
    def test_verify_all_entries_on_target_disc(self):
        results = verify_extra_screens(DEFAULT_TARGET_BIN)
        assert len(results) == 15
        for r in results:
            assert r["status"] == "PASS"

    @pytest.mark.skipif(not DEFAULT_TARGET_BIN.is_file(), reason="Target disc image not found")
    def test_verify_single_entry(self):
        results_opt = verify_extra_screens(DEFAULT_TARGET_BIN, target_entry="opt_137")
        assert len(results_opt) == 1
        assert results_opt[0]["id"] == "opt_137"
        assert results_opt[0]["status"] == "PASS"

        results_prog = verify_extra_screens(DEFAULT_TARGET_BIN, target_entry="prog_054")
        assert len(results_prog) == 1
        assert results_prog[0]["id"] == "prog_054"
        assert results_prog[0]["status"] == "PASS"

        results_cine = verify_extra_screens(DEFAULT_TARGET_BIN, target_entry="optcine_01")
        assert len(results_cine) == 1
        assert results_cine[0]["id"] == "optcine_01"
        assert results_cine[0]["status"] == "PASS"

        results_317 = verify_extra_screens(DEFAULT_TARGET_BIN, target_entry="prog_317")
        assert len(results_317) == 1
        assert results_317[0]["id"] == "prog_317"
        assert results_317[0]["status"] == "PASS"

        results_324 = verify_extra_screens(DEFAULT_TARGET_BIN, target_entry="prog_324")
        assert len(results_324) == 1
        assert results_324[0]["id"] == "prog_324"
        assert results_324[0]["status"] == "PASS"


class TestDryRunPatching:
    """Verify patcher execution in dry-run mode."""

    def test_dry_run_execution(self):
        results = patch_extra_screens(bin_path=DEFAULT_TARGET_BIN, dry_run=True)
        assert len(results) == 15
        for r in results:
            assert r["dry_run"] is True
            assert r["patched"] is False
            assert r["payload_len"] == r["budget"] or (r["id"] == "optcine_01" and r["payload_len"] == 33312)
