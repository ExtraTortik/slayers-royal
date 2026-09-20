#!/usr/bin/env python3
"""Comprehensive test suite for BASYOG.UNT Town Map Illustration Patcher (Entries 467..476).

Tests:
1. JSON Catalog integrity (translations/town_maps_ru.json, translations/translations_index.json).
2. TIM 8bpp encoding, headers, CLUT, geometry, and tim_to_town_map_png roundtrip.
3. Dimension validation and error handling on invalid image sizes.
4. unt_lz mode 1 compression and strict sector budget compliance.
5. Budget overflow detection and error handling.
6. Custom maps discovery and filename alias matching.
7. CLI interface (help, dry-run, single-entry, dump-dir).
8. Mode 2 Form 1 EDC/ECC checksum integrity on disc images.
"""

from __future__ import annotations

import json
import struct
import tempfile
from pathlib import Path

import numpy as np
import pytest
import sys
from PIL import Image
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "patch_repo") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from localization import unt_lz
    from localization.disc import (
        CdChecksums,
        RAW_SECTOR_SIZE,
        read_extent,
    )
except ImportError:
    from patch_repo.localization import unt_lz
    from patch_repo.localization.disc import (
        CdChecksums,
        RAW_SECTOR_SIZE,
        read_extent,
    )

from tools.patch_town_maps import (
    CLUT_BLOCK_SIZE,
    DEFAULT_BIN,
    DEFAULT_CATALOG,
    DEFAULT_MAPS_DIR,
    IMAGE_BLOCK_SIZE,
    IMAGE_HEADER_SIZE,
    PIXEL_DATA_SIZE,
    SECONDARY_BIN,
    TIM_HEADER,
    TIM_HEIGHT,
    TIM_WIDTH,
    TOWN_MAPS_SPECS,
    UNCOMPRESSED_TIM_SIZE,
    dump_town_maps,
    find_custom_maps,
    get_town_map_clut,
    patch_town_map,
    patch_town_maps,
    png_to_town_map_tim,
    tim_to_town_map_png,
    verify_town_maps,
)


class TestTownMapsCatalogIntegrity:
    """Validate JSON catalog and translations_index.json."""

    def test_catalog_file_exists_and_valid(self):
        assert DEFAULT_CATALOG.is_file(), f"Missing catalog file: {DEFAULT_CATALOG}"
        data = json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))
        assert "towns" in data
        assert len(data["towns"]) == 10

    def test_all_10_town_specs_complete(self):
        data = json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))
        entries = {t["entry_index"]: t for t in data["towns"]}
        assert sorted(entries.keys()) == list(range(467, 477))

        for idx in range(467, 477):
            t = entries[idx]
            spec = TOWN_MAPS_SPECS[idx]
            assert t["entry_index"] == idx
            assert t["id"] == spec["id"]
            assert t["name_en"] == spec["name_en"]
            assert t["name_ru"] == spec["name_ru"]
            assert t["sector_offset"] == spec["sector_offset"]
            assert t["lba"] == spec["lba"]
            assert t["sector_count"] == spec["sectors"]
            assert t["budget_bytes"] == spec["budget"]
            assert t["budget_bytes"] == t["sector_count"] * 2048
            assert t["width"] == TIM_WIDTH
            assert t["height"] == TIM_HEIGHT
            assert t["bpp"] == 8
            assert t["vram_x"] == spec["vram_x"]
            assert t["vram_y"] == spec["vram_y"]
            assert t["clut_x"] == spec["clut_x"]
            assert t["clut_y"] == spec["clut_y"]
            assert t["clut_colors"] == 256
            assert len(t["aliases"]) >= 3

    def test_sumbulk_special_vram_coordinate(self):
        # Entry 476 (Sumbulk) is at VRAM (0, 0), others are at (320, 0)
        assert TOWN_MAPS_SPECS[476]["vram_x"] == 0
        assert TOWN_MAPS_SPECS[476]["vram_y"] == 0
        for idx in range(467, 476):
            assert TOWN_MAPS_SPECS[idx]["vram_x"] == 320
            assert TOWN_MAPS_SPECS[idx]["vram_y"] == 0

    def test_registered_in_translations_index(self):
        index_file = REPO_ROOT / "translations" / "translations_index.json"
        assert index_file.is_file()
        doc = json.loads(index_file.read_text(encoding="utf-8"))
        catalog_ids = [c["id"] for c in doc["catalogs"]]
        assert "town_maps" in catalog_ids


class TestTimEncodingAndDecoding:
    """Validate PNG <-> TIM conversion, headers, geometry, and CLUT."""

    def test_png_to_tim_valid_dimensions_and_headers(self):
        # Create a blank 224x168 test image
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            im = Image.new("RGB", (TIM_WIDTH, TIM_HEIGHT), (100, 150, 200))
            im.save(tmp.name)

            tim = png_to_town_map_tim(tmp.name, entry_index=468)
            assert len(tim) == UNCOMPRESSED_TIM_SIZE
            assert tim[:8] == TIM_HEADER

            # Verify CLUT block
            clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim, 8)
            assert clut_len == CLUT_BLOCK_SIZE
            assert cx == 0 and cy == 480
            assert cw == 256 and ch == 1

            # Verify Image block
            img_offset = 8 + clut_len
            img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", tim, img_offset)
            assert img_len == IMAGE_BLOCK_SIZE
            assert ix == 320 and iy == 0
            assert iw == 112 and ih == 168

    def test_png_to_tim_sumbulk_vram_coordinates(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            im = Image.new("RGB", (TIM_WIDTH, TIM_HEIGHT), (50, 80, 120))
            im.save(tmp.name)

            tim = png_to_town_map_tim(tmp.name, entry_index=476)
            img_offset = 8 + CLUT_BLOCK_SIZE
            img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", tim, img_offset)
            assert ix == 0 and iy == 0

    def test_invalid_dimensions_raise_value_error(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            im = Image.new("RGB", (256, 256), (0, 0, 0))
            im.save(tmp.name)
            with pytest.raises(ValueError, match="Invalid image dimensions"):
                png_to_town_map_tim(tmp.name, entry_index=468)

    def test_invalid_entry_raises_value_error(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            im = Image.new("RGB", (TIM_WIDTH, TIM_HEIGHT), (0, 0, 0))
            im.save(tmp.name)
            with pytest.raises(ValueError, match="Invalid town map entry"):
                png_to_town_map_tim(tmp.name, entry_index=999)

    def test_tim_to_png_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            im = Image.new("RGB", (TIM_WIDTH, TIM_HEIGHT), (64, 128, 192))
            im.save(tmp.name)

            tim = png_to_town_map_tim(tmp.name, entry_index=468)
            decoded = tim_to_town_map_png(tim)
            assert decoded.size == (TIM_WIDTH, TIM_HEIGHT)
            assert decoded.mode == "RGB"

    def test_custom_palette_generation(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            # Multi-colored image
            arr = np.zeros((TIM_HEIGHT, TIM_WIDTH, 3), dtype=np.uint8)
            arr[:84, :, 0] = 200
            arr[84:, :, 1] = 200
            Image.fromarray(arr, "RGB").save(tmp.name)

            tim = png_to_town_map_tim(tmp.name, entry_index=468, custom_palette=True)
            assert len(tim) == UNCOMPRESSED_TIM_SIZE
            decoded = tim_to_town_map_png(tim)
            assert decoded.size == (TIM_WIDTH, TIM_HEIGHT)


class TestUntLzCompressionAndBudgets:
    """Validate unt_lz mode 1 compression and sector budget boundaries."""

    def test_basyog_468_compression_and_budget_margin(self):
        test_png = DEFAULT_MAPS_DIR / "basyog_468.png"
        if not test_png.is_file():
            test_png = DEFAULT_MAPS_DIR / "burkland.png"
        assert test_png.is_file()

        tim = png_to_town_map_tim(test_png, entry_index=468)
        compressed = unt_lz.compress(tim)

        budget = TOWN_MAPS_SPECS[468]["budget"]
        assert len(compressed) <= budget
        margin = budget - len(compressed)
        # Verify comfortable margin (> 1KB)
        assert margin >= 1000

        # Bit-exact roundtrip
        decomp, consumed = unt_lz.decompress(compressed)
        assert decomp == tim
        assert consumed == len(compressed)

    def test_budget_overflow_raises_value_error(self):
        # Create uncompressible noise image that would exceed sector budget
        np.random.seed(42)
        noise = np.random.randint(0, 256, (TIM_HEIGHT, TIM_WIDTH, 3), dtype=np.uint8)
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            Image.fromarray(noise, "RGB").save(tmp.name)

            # Test on lowest budget entry (Entry 471: 12 sectors = 24,576 B) with custom palette
            with pytest.raises(ValueError, match="exceeds allocated"):
                patch_town_map(
                    bin_path=DEFAULT_BIN,
                    entry_index=471,
                    image_path=tmp.name,
                    custom_palette=True,
                    dry_run=True,
                )


class TestCustomMapsDiscovery:
    """Validate custom map detection in maps directory."""

    def test_find_custom_maps_detects_entry_468(self):
        maps = find_custom_maps(DEFAULT_MAPS_DIR)
        assert 468 in maps
        assert maps[468].is_file()
        assert maps[468].name in ["basyog_468.png", "burkland.png"]

    def test_find_custom_maps_nonexistent_dir(self):
        maps = find_custom_maps(REPO_ROOT / "nonexistent_dir_12345")
        assert maps == {}

    def test_find_custom_maps_with_various_aliases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            # Create dummy image
            dummy = Image.new("RGB", (TIM_WIDTH, TIM_HEIGHT), (0, 0, 0))
            dummy.save(td / "lakewood.png")
            dummy.save(td / "basyog_469_224x168.png")
            dummy.save(td / "sonia_city.png")
            dummy.save(td / "iselsen.png")
            dummy.save(td / "freeground.png")
            dummy.save(td / "truecity.png")
            dummy.save(td / "476.png")
            matched = find_custom_maps(td)
            assert matched[467].name == "lakewood.png"
            assert matched[469].name == "basyog_469_224x168.png"
            assert matched[470].name == "sonia_city.png"
            assert matched[471].name == "iselsen.png"
            assert matched[472].name == "freeground.png"
            assert matched[474].name == "truecity.png"
            assert matched[476].name == "476.png"


class TestPatchTownMapsDryRunAndCLI:
    """Validate dry-run execution and dumping."""

    def test_dry_run_patch_town_maps(self):
        results = patch_town_maps(
            bin_path=DEFAULT_BIN,
            maps_dir=DEFAULT_MAPS_DIR,
            dry_run=True,
        )
        assert len(results) >= 1
        r468 = next(r for r in results if r["entry_index"] == 468)
        assert r468["status"] == "dry_run"
        assert r468["dry_run"] is True
        assert r468["budget"] == 30720
        assert r468["compressed_size"] < 30720
        assert r468["margin"] > 0

    def test_dump_town_maps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dumped = dump_town_maps(DEFAULT_BIN, dump_dir=tmpdir, entry_index=468)
            assert len(dumped) == 2
            p1 = Path(tmpdir) / "basyog_468.png"
            p2 = Path(tmpdir) / "burkland.png"
            assert p1.is_file()
            assert p2.is_file()
            im = Image.open(p1)
            assert im.size == (TIM_WIDTH, TIM_HEIGHT)


class TestDiscImageIntegrityAndEdcEcc:
    """Validate Mode 2 Form 1 EDC/ECC and TIM integrity on target disc image."""

    def test_verify_all_10_town_maps_on_primary_bin(self):
        results = verify_town_maps(DEFAULT_BIN)
        assert len(results) == 10
        for r in results:
            assert r["edc_ecc_valid"] is True
            assert r["margin"] >= 0
            assert r["decompressed_size"] == UNCOMPRESSED_TIM_SIZE

    def test_verify_all_10_town_maps_on_secondary_bin(self):
        if SECONDARY_BIN.is_file():
            results = verify_town_maps(SECONDARY_BIN)
            assert len(results) == 10
            for r in results:
                assert r["edc_ecc_valid"] is True
                assert r["margin"] >= 0
                assert r["decompressed_size"] == UNCOMPRESSED_TIM_SIZE

    def test_all_136_town_map_sectors_have_valid_edc_ecc(self):
        # 16 + 15 + 14 + 13 + 12 + 14 + 12 + 14 + 13 + 13 = 136 sectors
        checksums = CdChecksums()
        with DEFAULT_BIN.open("rb") as f:
            for lba in range(240141, 240277):
                f.seek(lba * RAW_SECTOR_SIZE)
                sec = f.read(RAW_SECTOR_SIZE)
                assert sec[15] == 2
                assert sec[0x818:0x81C] == checksums.compute_edc(sec[0x10:0x818])
                assert sec[0x81C:0x8C8] == checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86)
                assert sec[0x8C8:0x930] == checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88)
