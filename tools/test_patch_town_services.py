"""Unit tests for town services, shop menus, and currency display patcher.

Covers:
1. Encoding of all Russian strings via DEFAULT_CHARMAP (uint16_le, control codes).
2. Dynamic pointer table updates in RAM (Tavern, Inn, System icons, Shop menus).
3. Byte budget constraints and zero buffer overflows across all string slots.
4. MIPS suffix patch neutralization (0x0221F8).
5. Currency composite tile generation (16x16 4bpp tiles in font 0x03A).
6. In-memory Entry 3 patching and CLI --dry-run execution.
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from patch_repo.localization.disc import USER_DATA_SIZE, read_extent
from patch_repo.localization.glyphs import glyph_xy
try:
    from patch_repo.localization import unt_lz
except ImportError:
    from localization import unt_lz
from tools.patch_inspection import DEFAULT_CHARMAP
from tools.patch_town_services import (
    CURRENCY_TILES_SPEC,
    DEFAULT_CATALOG,
    DELIMITER,
    ENTRY3_LBA,
    ENTRY3_SECTORS,
    ENTRY3_SIZE,
    ENTRY_03A_LBA,
    ENTRY_03A_SECTORS,
    ENTRY_03A_SIZE,
    INN_BOX_WIDTH_OFFSET,
    INN_BOX_X_OFFSET,
    INN_PRICE_SUFFIX_OFFSET,
    RAM_BASE,
    TAVERN_BOX_WIDTH_OFFSET,
    TAVERN_BOX_X_OFFSET,
    TAVERN_PRICE_SUFFIX_OFFSET,
    encode_rejection_scene,
    encode_string,
    get_font_pixel,
    load_catalog,
    patch_entry3_buffer,
    patch_menu_typography,
    render_currency_tiles,
    set_font_pixel,
)


@pytest.fixture
def catalog() -> dict[str, Any]:
    """Load canonical town services Russian translation catalog."""
    return load_catalog(DEFAULT_CATALOG)


def test_catalog_structure(catalog: dict[str, Any]):
    """Verify JSON structure contains all required sections and valid metadata."""
    assert "meta" in catalog
    assert catalog["meta"]["entry_lba"] == ENTRY3_LBA
    assert catalog["meta"]["entry_sectors"] == ENTRY3_SECTORS
    assert catalog["meta"]["ram_base"] == hex(RAM_BASE).lower() or catalog["meta"]["ram_base"] == "0x8004E5B0"

    assert "currency_config" in catalog
    assert "tavern_services" in catalog
    assert "inn_services" in catalog
    assert "town_system_icons" in catalog
    assert "shop_dialogue" in catalog
    assert "menu_typography" in catalog
    typo = catalog["menu_typography"]
    assert typo["tavern_box_width"] == 160
    assert typo["tavern_box_x_offset"] == -50
    assert typo["inn_box_width"] == 240
    assert typo["inn_box_x_offset"] == -90
    assert "currency_tiles_layout" in catalog


def test_encode_all_strings(catalog: dict[str, Any]):
    """Test that all Russian strings in the catalog encode cleanly using DEFAULT_CHARMAP."""
    # 1. Tavern
    t_cfg = catalog["tavern_services"]
    for key, item in t_cfg.items():
        text = item["ru"]
        spk = item.get("speaker_code_hex")
        encoded = encode_string(text, speaker_hex=spk)
        assert len(encoded) > 0
        assert encoded.endswith(b"\xff\x00")

    # 2. Inn
    i_cfg = catalog["inn_services"]
    assert encode_string(i_cfg["rest_night"]["ru"]).endswith(b"\xff\x00")
    assert encode_string(i_cfg["sleep_morning"]["ru"]).endswith(b"\xff\x00")
    assert encode_string(i_cfg["dialogue_rest_night"]["ru"]).endswith(b"\xff\x00")
    assert encode_string(i_cfg["dialogue_sleep_morning"]["ru"]).endswith(b"\xff\x00")

    # 3. Inn Rejection Scene
    rej_cfg = i_cfg["rejection_scene"]
    cues = rej_cfg["dialogue_cues"]
    assert len(cues) == 8
    rej_bytes = encode_rejection_scene(cues, max_bytes=rej_cfg["max_bytes"])
    assert len(rej_bytes) == rej_cfg["max_bytes"]

    # 4. System Icons
    sys_cfg = catalog["town_system_icons"]
    for icon_name, icon_data in sys_cfg["icons"].items():
        encoded = encode_string(icon_data["ru"])
        assert len(encoded) > 0
        assert encoded.endswith(b"\xff\x00")

    # 5. Shop Dialogue
    shop_cfg = catalog["shop_dialogue"]
    for item_name, s_data in shop_cfg.items():
        encoded = encode_string(s_data["ru"])
        assert len(encoded) > 0
        assert encoded.endswith(b"\xff\x00")


def test_tavern_byte_budgets_and_zero_overflow(catalog: dict[str, Any]):
    """Test that Tavern Food Menu strings fit within byte limits."""
    t_cfg = catalog["tavern_services"]

    # Option 1 (СЫТНЫЙ ОБЕД) fits in 24 bytes
    # Option 1 (ОБЕД) fits in 24 bytes
    fm_bytes = encode_string(t_cfg["full_meal"]["ru"])
    assert len(fm_bytes) <= t_cfg["full_meal"]["max_bytes"]
    assert len(fm_bytes) == 10  # 4 chars * 2 + 2 = 10 bytes

    # Option 2 (ПЕРЕКУС) fits in 20 bytes at 0x02D510
    sn_bytes = encode_string(t_cfg["snack"]["ru"])
    assert len(sn_bytes) <= t_cfg["snack"]["max_bytes"]
    assert len(sn_bytes) == 16  # 7 chars * 2 + 2 = 16 bytes

    # Status messages
    nm_bytes = encode_string(
        t_cfg["status_no_money"]["ru"], speaker_hex=t_cfg["status_no_money"]["speaker_code_hex"]
    )
    assert len(nm_bytes) <= t_cfg["status_no_money"]["max_bytes"]

    ja_bytes = encode_string(
        t_cfg["status_just_ate"]["ru"], speaker_hex=t_cfg["status_just_ate"]["speaker_code_hex"]
    )
    assert len(ja_bytes) <= t_cfg["status_just_ate"]["max_bytes"]


def test_inn_byte_budgets_and_zero_overflow(catalog: dict[str, Any]):
    """Test that Inn Lodging Menu strings and dialogues fit within byte limits."""
    i_cfg = catalog["inn_services"]

    # Option 1 (ОТДЫХ ДО НОЧИ)
    rn_bytes = encode_string(i_cfg["rest_night"]["ru"])
    assert len(rn_bytes) <= i_cfg["rest_night"]["max_bytes"]
    assert len(rn_bytes) == 28

    # Option 2 (СОН ДО УТРА)
    sm_bytes = encode_string(i_cfg["sleep_morning"]["ru"])
    assert len(sm_bytes) <= i_cfg["sleep_morning"]["max_bytes"]
    assert len(sm_bytes) == 24

    # Combined options fit inside the 72-byte free space (0x02DF8C..0x02DFD4)
    assert len(rn_bytes) + len(sm_bytes) <= (0x02DFD4 - 0x02DF8C)

    # Dialogue lines
    drn_bytes = encode_string(i_cfg["dialogue_rest_night"]["ru"])
    assert len(drn_bytes) <= i_cfg["dialogue_rest_night"]["max_bytes"]

    dsm_bytes = encode_string(i_cfg["dialogue_sleep_morning"]["ru"])
    assert len(dsm_bytes) <= i_cfg["dialogue_sleep_morning"]["max_bytes"]

    # Rejection scene (8 cues, max 328 bytes)
    rej_bytes = encode_rejection_scene(i_cfg["rejection_scene"]["dialogue_cues"])
    assert len(rej_bytes) == 328


def test_system_icons_packing_no_overflow(catalog: dict[str, Any]):
    """Test that all 10 system icon help texts fit inside pack region (0x030BD8..0x030F20 = 840 B)."""
    sys_cfg = catalog["town_system_icons"]
    pack_start = int(sys_cfg["pack_region"]["start_offset_hex"], 16)
    pack_limit = int(sys_cfg["pack_region"]["end_offset_hex"], 16)
    budget = pack_limit - pack_start

    cur_off = pack_start
    for name, icon_data in sys_cfg["icons"].items():
        raw = encode_string(icon_data["ru"])
        if cur_off % 2 != 0:
            cur_off += 1
        cur_off += len(raw)

    total_used = cur_off - pack_start
    assert total_used <= budget, f"System icons pack overflow: {total_used} > {budget}"
    # Must leave positive safety headroom
    assert budget - total_used >= 32, "Expected at least 32 bytes headroom in system icon pack"


def test_currency_mips_and_headers(catalog: dict[str, Any]):
    """Test MIPS suffix instruction and currency header formats."""
    curr_cfg = catalog["currency_config"]
    mips_patch = curr_cfg.get("mips_suffix_patch", {})
    assert mips_patch.get("patched_ru_hex") == "24 02 7D 00"

    # Both suffix patch offsets configured (0x0180B0 for tavern, 0x0221F8 for inn/shops)
    mips_patches = curr_cfg.get("mips_suffix_patches", {})
    assert "tavern" in mips_patches
    assert mips_patches["tavern"]["offset_hex"].lower() == "0x0180b0"
    assert mips_patches["tavern"]["patched_ru_hex"] == "24 02 7D 00"
    assert "inn_and_shops" in mips_patches
    assert mips_patches["inn_and_shops"]["offset_hex"].lower() == "0x0221f8"
    assert mips_patches["inn_and_shops"]["patched_ru_hex"] == "24 02 7D 00"

    headers = curr_cfg["headers"]
    for cur_name in ("bronze", "silver", "gold"):
        assert cur_name in headers
        hdr = headers[cur_name]
        tiles = [int(x, 16) for x in hdr["composite_tiles"]]
        assert len(tiles) == 2
        assert hdr["max_bytes"] == 6


def test_currency_composite_tiles_rendering():
    """Test generation and geometry of the 6 Russian currency composite tiles."""
    tiles = render_currency_tiles()
    assert len(tiles) == 6

    expected_glyphs = {0x0242, 0x0244, 0x024A, 0x024B, 0x0254, 0x0259}
    assert set(tiles.keys()) == expected_glyphs

    for gid, rows in tiles.items():
        assert len(rows) == 16, f"Glyph 0x{gid:04X} must have 16 rows"
        for r_idx, row in enumerate(rows):
            assert len(row) == 16, f"Glyph 0x{gid:04X} row {r_idx} must be 16 chars wide"
            assert all(c in (".", "#") for c in row)

        # Must contain rendered pixel artwork (not completely blank)
        total_pixels = sum(row.count("#") for row in rows)
        assert total_pixels >= 10, f"Glyph 0x{gid:04X} has suspiciously few pixels ({total_pixels})"

    # Test that tile 0x0259 has "Ь" at col 1 (pad_left = 1)
    tile_0259 = tiles[0x0259]
    for r in range(4, 11):
        assert tile_0259[r][0] == ".", f"Row {r} col 0 must be transparent"
        assert tile_0259[r][1] == "#", f"Row {r} col 1 must be foreground '#' for pad_left=1"


def test_patch_entry3_buffer_pointers():
    """Test that patch_entry3_buffer correctly sets all RAM pointers and offsets."""
    cat = load_catalog(DEFAULT_CATALOG)
    dummy_buf = bytearray(ENTRY3_SIZE)

    patched_buf, report = patch_entry3_buffer(dummy_buf, cat)
    assert len(patched_buf) == ENTRY3_SIZE
    assert len(report["pointer_updates"]) >= 14

    # Check Tavern pointers
    fm_ptr_bytes = patched_buf[0x02D524 : 0x02D524 + 4]
    fm_ptr = struct.unpack("<I", fm_ptr_bytes)[0]
    assert fm_ptr == RAM_BASE + 0x02D414

    sn_ptr_bytes = patched_buf[0x02D528 : 0x02D528 + 4]
    sn_ptr = struct.unpack("<I", sn_ptr_bytes)[0]
    assert sn_ptr == RAM_BASE + 0x02D510

    # Check Inn pointers
    rn_ptr_bytes = patched_buf[0x02DFD4 : 0x02DFD4 + 4]
    rn_ptr = struct.unpack("<I", rn_ptr_bytes)[0]
    assert rn_ptr == RAM_BASE + 0x02DF8C

    sm_ptr_bytes = patched_buf[0x02DFD8 : 0x02DFD8 + 4]
    sm_ptr = struct.unpack("<I", sm_ptr_bytes)[0]
    assert sm_ptr == RAM_BASE + 0x02DFA8

    # Check MIPS instructions at 0x0180B0 (tavern) and 0x0221F8 (inn/shops)
    assert patched_buf[TAVERN_PRICE_SUFFIX_OFFSET : TAVERN_PRICE_SUFFIX_OFFSET + 4] == bytes.fromhex("7d000224")
    assert struct.unpack("<I", patched_buf[TAVERN_PRICE_SUFFIX_OFFSET : TAVERN_PRICE_SUFFIX_OFFSET + 4])[0] == 0x2402007D

    assert patched_buf[INN_PRICE_SUFFIX_OFFSET : INN_PRICE_SUFFIX_OFFSET + 4] == bytes.fromhex("7d000224")
    assert struct.unpack("<I", patched_buf[INN_PRICE_SUFFIX_OFFSET : INN_PRICE_SUFFIX_OFFSET + 4])[0] == 0x2402007D

    # Check Menu Typography MIPS instructions
    assert patched_buf[TAVERN_BOX_WIDTH_OFFSET : TAVERN_BOX_WIDTH_OFFSET + 4] == bytes.fromhex("a0000224")
    assert patched_buf[TAVERN_BOX_X_OFFSET : TAVERN_BOX_X_OFFSET + 4] == bytes.fromhex("ceff0224")
    assert patched_buf[INN_BOX_WIDTH_OFFSET : INN_BOX_WIDTH_OFFSET + 4] == bytes.fromhex("f0000324")
    assert patched_buf[INN_BOX_X_OFFSET : INN_BOX_X_OFFSET + 4] == bytes.fromhex("a6ff0324")

def test_cli_dry_run():
    """Test running tools/patch_town_services.py via CLI with --dry-run."""
    test_bin = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
    if not test_bin.is_file():
        test_bin = REPO_ROOT / "downloads" / "sr.bin"

    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "patch_town_services.py"),
        "--dry-run",
        "--bin",
        str(test_bin),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"patch_town_services.py failed: {res.stderr}"
    assert "Successfully patched town services" in res.stdout
    assert "DRY-RUN simulation" in res.stdout


def test_menu_typography_patching():
    """Test configurable menu typography patching in Entry 3 MIPS instructions."""
    dummy_buf = bytearray(ENTRY3_SIZE)
    dummy_buf[TAVERN_BOX_X_OFFSET : TAVERN_BOX_X_OFFSET + 4] = bytes.fromhex("00000000")
    dummy_buf[TAVERN_BOX_WIDTH_OFFSET : TAVERN_BOX_WIDTH_OFFSET + 4] = bytes.fromhex("00000000")
    dummy_buf[INN_BOX_X_OFFSET : INN_BOX_X_OFFSET + 4] = bytes.fromhex("00000000")
    dummy_buf[INN_BOX_WIDTH_OFFSET : INN_BOX_WIDTH_OFFSET + 4] = bytes.fromhex("00000000")

    cfg = {
        "tavern_box_width": 160,
        "tavern_box_x_offset": -50,
        "inn_box_width": 240,
        "inn_box_x_offset": -90,
    }

    report = patch_menu_typography(dummy_buf, cfg)
    assert len(report["modified_offsets"]) == 4

    # Tavern box width: addiu $v0, $zero, 160 -> 240200a0 -> a0000224
    assert dummy_buf[TAVERN_BOX_WIDTH_OFFSET : TAVERN_BOX_WIDTH_OFFSET + 4] == bytes.fromhex("a0000224")
    # Tavern box X offset: addiu $v0, $zero, -50 -> 2402ffce -> ceff0224
    assert dummy_buf[TAVERN_BOX_X_OFFSET : TAVERN_BOX_X_OFFSET + 4] == bytes.fromhex("ceff0224")
    # Inn box width: addiu $v1, $zero, 240 -> 240300f0 -> f0000324
    assert dummy_buf[INN_BOX_WIDTH_OFFSET : INN_BOX_WIDTH_OFFSET + 4] == bytes.fromhex("f0000324")
    # Inn box X offset: addiu $v1, $zero, -90 -> 2403ffa6 -> a6ff0324
    assert dummy_buf[INN_BOX_X_OFFSET : INN_BOX_X_OFFSET + 4] == bytes.fromhex("a6ff0324")

def test_entry_03a_decompressed_currency_tiles():
    """Verify that tile 0x0242 decompressed from Entry 0x03A on disc contains Cyrillic 'СЕР', not ASCII 'SI'."""
    bin_path = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
    if not bin_path.is_file():
        pytest.skip(f"Target disc image not found: {bin_path}")

    extent_03a = read_extent(bin_path, ENTRY_03A_LBA, ENTRY_03A_SIZE)
    decomp_03a, _ = unt_lz.decompress(extent_03a)
    assert len(decomp_03a) == 131616, f"Expected 131616 bytes TIM, got {len(decomp_03a)}"

    # Check tile 0x0242 (СЕР)
    gx, gy = glyph_xy(0x0242)
    tiles = render_currency_tiles()
    expected_rows = tiles[0x0242]

    # Verify tile contains Russian pixels
    for py in range(16):
        expected_row = expected_rows[py]
        for px in range(16):
            expected_val = 3 if expected_row[px] == "#" else 0
            actual_val = get_font_pixel(decomp_03a, gx + px, gy + py)
            assert actual_val == expected_val, (
                f"Pixel mismatch at ({px}, {py}) in tile 0x0242: "
                f"expected {expected_val}, got {actual_val}"
            )

    # Explicitly assert that ASCII 'SI' pattern is NOT present in tile 0x0242
    # In ASCII 'SI', row 7 is '..###...#..#....' whereas in Cyrillic 'СЕР' row 7 is '.#....###..###..'
    row7_actual = "".join("#" if get_font_pixel(decomp_03a, gx + px, gy + 7) != 0 else "." for px in range(16))
    assert row7_actual == ".#....###..###..", f"Expected Cyrillic 'СЕР' row 7, got: {row7_actual}"
    assert row7_actual != "..###...#..#....", "Found ASCII 'SI' in tile 0x0242!"

    # Verify all 6 Russian currency composite tiles
    for gid in (0x0242, 0x0244, 0x024A, 0x024B, 0x0254, 0x0259):
        tgx, tgy = glyph_xy(gid)
        exp = tiles[gid]
        for py in range(16):
            for px in range(16):
                val = 3 if exp[py][px] == "#" else 0
                pix = get_font_pixel(decomp_03a, tgx + px, tgy + py)
                assert pix == val, f"Glyph 0x{gid:04X} pixel mismatch at ({px}, {py})"

    # Check tile 0x0259 has "Ь" at col 1 (pad_left = 1) in Entry 0x03A
    tgx_0259, tgy_0259 = glyph_xy(0x0259)
    for py in range(4, 11):
        assert get_font_pixel(decomp_03a, tgx_0259 + 0, tgy_0259 + py) == 0
        assert get_font_pixel(decomp_03a, tgx_0259 + 1, tgy_0259 + py) == 3
