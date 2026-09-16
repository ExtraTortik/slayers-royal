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
from tools.patch_town_services import (
    CURRENCY_TILES_SPEC,
    DEFAULT_CATALOG,
    DEFAULT_CHARMAP,
    DEFAULT_SHOP_CATALOG,
    DELIMITER,
    DYNAMIC_ALLOC_LIMIT,
    DYNAMIC_ALLOC_START,
    ENTRY3_LBA,
    ENTRY3_SECTORS,
    ENTRY3_SIZE,
    ENTRY_03A_LBA,
    ENTRY_03A_SECTORS,
    ENTRY_03A_SIZE,
    INN_BOX_WIDTH_OFFSET,
    INN_BOX_X_OFFSET,
    INN_PRICE_SUFFIX_OFFSET,
    LEGACY_SHOP_HUD_OFFSET,
    RAM_BASE,
    REVERSE_CHARMAP,
    SHOP_ITEMS_COUNT,
    SHOP_ITEMS_TABLE_END,
    SHOP_ITEMS_TABLE_START,
    SHOP_TABLE1_COUNT,
    SHOP_TABLE1_END,
    SHOP_TABLE1_START,
    SHOP_TABLE2_COUNT,
    SHOP_TABLE2_END,
    SHOP_TABLE2_START,
    TAVERN_BOX_WIDTH_OFFSET,
    TAVERN_BOX_X_OFFSET,
    TAVERN_PRICE_SUFFIX_OFFSET,
    TOTAL_SHOP_POINTERS,
    decode_string,
    encode_rejection_scene,
    encode_string,
    get_font_pixel,
    load_catalog,
    patch_entry3_buffer,
    patch_menu_typography,
    patch_shop_dialogues_buffer,
    patch_town_services,
    render_currency_tiles,
    set_font_pixel,
    verify_town_services,
)


@pytest.fixture
def catalog() -> dict[str, Any]:
    """Load canonical town services Russian translation catalog."""
    return load_catalog(DEFAULT_CATALOG)


@pytest.fixture
def shop_catalog() -> dict[str, Any]:
    """Load canonical shop dialogues Russian translation catalog."""
    return load_catalog(DEFAULT_SHOP_CATALOG)

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
    assert t_cfg["status_just_ate"]["max_bytes"] <= 32
    assert int(t_cfg["status_just_ate"]["offset_hex"], 16) + t_cfg["status_just_ate"]["max_bytes"] <= 0x02D4CC


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

    # Check that legacy Japanese shop HUD is neutralized at 0x017F48 (jr $ra; nop)
    assert patched_buf[LEGACY_SHOP_HUD_OFFSET : LEGACY_SHOP_HUD_OFFSET + 8] == bytes.fromhex("0800e00300000000")
    # Check that Tavern City Cue Table at 0x02D4CC is preserved (not overwritten by status_just_ate)
    assert patched_buf[0x02D4CC : 0x02D4CE] == b"\x00\x00"

    # Check that Hotel City Cue Table at 0x02DF70..0x02DF88 is preserved
    # Test with dummy buffer having original hotel cues
    test_buf = bytearray(ENTRY3_SIZE)
    hotel_cues = bytes.fromhex("0000 a104 a304 0000 a604 0000 e304 e804 f504 0e06 3506 5306")
    test_buf[0x02DF70 : 0x02DF70 + len(hotel_cues)] = hotel_cues
    test_buf[0x02D4CC : 0x02D4CE] = b"\x12\x34"
    patched_test, _ = patch_entry3_buffer(test_buf, cat)
    assert patched_test[0x02D4CC : 0x02D4CE] == b"\x12\x34", "Tavern cue table at 0x02D4CC must not be overwritten"
    assert patched_test[0x02DF70 : 0x02DF70 + len(hotel_cues)] == hotel_cues, "Hotel cue table must be preserved"
    assert patched_test[0x02DF78 : 0x02DF7A] == b"\xa6\x04", "Sonia hotel cue 0x04A6 must be preserved"

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


def test_shop_dialogues_authoritative_encoding(shop_catalog: dict[str, Any]):
    """Test that all 98 dialogue and menu strings in translations/shop_dialogues_ru.json

    encode cleanly with the authoritative Cyrillic charmap.
    """
    assert "dialogues" in shop_catalog
    dialogues = shop_catalog["dialogues"]
    assert len(dialogues) == 98, f"Expected 98 dialogue items, got {len(dialogues)}"

    encoded_count = 0
    total_pointers = 0
    for d_id, item in dialogues.items():
        text = item.get("text_ru") or item.get("ru") or ""
        spk = item.get("speaker_code_hex")
        if spk and not text.startswith("<"):
            spk_val = int(str(spk), 16)
            fmt_text = f"<{spk_val:04X}>{text}"
        else:
            fmt_text = text

        encoded = encode_string(fmt_text, DEFAULT_CHARMAP)
        assert len(encoded) > 0
        assert encoded.endswith(b"\xff\x00"), f"String '{d_id}' must end with 0x00FF terminator"

        # Verify decoding back
        decoded = decode_string(encoded)
        assert len(decoded) > 0

        ptrs = item.get("pointer_offsets_hex", [])
        total_pointers += len(ptrs)
        encoded_count += 1

    assert encoded_count == 98
    assert total_pointers == 100, f"Expected 100 pointers, got {total_pointers}"


def test_weapon_shop_greeting_exact_words():
    """Test that weapon shop merchant greeting '<D9A1>Что нужно?' encodes to the exact expected words

    (0xD9A1, 0x001F, 0x003C, 0x0037, 0x007D, 0x0036, 0x003D, 0x002E, 0x0036, 0x0037, 0x00A7).

    Validates that:
    - 'Ч' -> 0x001F (NOT obsolete shifted 0x0021 'Щ' or 0x0020 'Ш')
    - 'т' -> 0x003C (NOT obsolete shifted 0x003E 'ф'/'Ф' or 0x003D)
    - 'о' -> 0x0037 (NOT obsolete shifted 0x0039 'п'/'Р' or 0x0038)
    - ' ' -> 0x007D
    - 'н' -> 0x0036
    - 'у' -> 0x003D
    - 'ж' -> 0x002E
    - '?' -> 0x00A7
    This strictly eliminates the 'ЩФР ПХИПР?' mojibake bug shown in Image #1.
    """
    expected_words = [
        0xD9A1,  # Speaker code: weapon shop merchant
        0x001F,  # 'Ч'
        0x003C,  # 'т'
        0x0037,  # 'о'
        0x007D,  # ' '
        0x0036,  # 'н'
        0x003D,  # 'у'
        0x002E,  # 'ж'
        0x0036,  # 'н'
        0x0037,  # 'о'
        0x00A7,  # '?'
    ]

    # 1. Test encoding with embedded escape
    enc1 = encode_string("<D9A1>Что нужно?", DEFAULT_CHARMAP)
    words1 = [struct.unpack_from("<H", enc1, i)[0] for i in range(0, len(enc1) - 2, 2)]
    assert words1 == expected_words, f"Encoded words mismatch: {words1} != {expected_words}"
    assert enc1.endswith(b"\xff\x00")

    # 2. Test encoding with speaker_hex parameter
    enc2 = encode_string("Что нужно?", DEFAULT_CHARMAP, speaker_hex="0xD9A1")
    words2 = [struct.unpack_from("<H", enc2, i)[0] for i in range(0, len(enc2) - 2, 2)]
    assert words2 == expected_words, f"Speaker-param encoded words mismatch: {words2} != {expected_words}"
    assert enc1 == enc2

    # 3. Assert individual glyph codes in authoritative charmap (synchronized with PROG.UNT 0x03A VRAM font)
    assert DEFAULT_CHARMAP["Ч"] == 0x001F, "Glyph 'Ч' must be 0x001F"
    assert DEFAULT_CHARMAP["т"] == 0x003C, "Glyph 'т' must be 0x003C"
    assert DEFAULT_CHARMAP["о"] == 0x0037, "Glyph 'о' must be 0x0037"
    assert DEFAULT_CHARMAP[" "] == 0x007D, "Glyph ' ' must be 0x007D"
    assert DEFAULT_CHARMAP["н"] == 0x0036, "Glyph 'н' must be 0x0036"
    assert DEFAULT_CHARMAP["у"] == 0x003D, "Glyph 'у' must be 0x003D"
    assert DEFAULT_CHARMAP["ж"] == 0x002E, "Glyph 'ж' must be 0x002E"
    assert DEFAULT_CHARMAP["?"] == 0x00A7, "Glyph '?' must be 0x00A7"

    # Verify that decoding recovers the exact text
    dec = decode_string(enc1)
    assert dec == "<D9A1>Что нужно?"

def test_shop_table1_table2_pointers_and_allocations(shop_catalog: dict[str, Any]):
    """Test that all pointers in Table 1 (0x031F14..0x032060) and Table 2 (0x0322B0..0x0322EC)

    are correctly updated and point to valid strings within Entry 3.
    """
    dummy_buf = bytearray(ENTRY3_SIZE)
    patched_buf, report, dyn_alloc = patch_shop_dialogues_buffer(dummy_buf, shop_catalog)

    assert report["in_place_count"] + report["relocated_count"] == 98
    assert len(report["pointer_updates"]) == 191  # 100 dialogue pointers + 91 shop item pointers
    assert dyn_alloc >= DYNAMIC_ALLOC_START
    assert dyn_alloc <= DYNAMIC_ALLOC_LIMIT

    # Check Table 1: 84 pointers
    table1_ptrs = []
    for off in range(SHOP_TABLE1_START, SHOP_TABLE1_END, 4):
        ptr_val = struct.unpack("<I", patched_buf[off : off + 4])[0]
        assert ptr_val >= RAM_BASE, f"Table 1 pointer at 0x{off:06X} invalid: 0x{ptr_val:08X}"
        rel_off = ptr_val - RAM_BASE
        assert rel_off < ENTRY3_SIZE, f"Table 1 pointer at 0x{off:06X} out of bounds: rel 0x{rel_off:06X}"
        table1_ptrs.append((off, ptr_val, rel_off))
    assert len(table1_ptrs) == SHOP_TABLE1_COUNT == 84

    # Check Table 2: 16 pointers
    table2_ptrs = []
    for off in range(SHOP_TABLE2_START, SHOP_TABLE2_END, 4):
        ptr_val = struct.unpack("<I", patched_buf[off : off + 4])[0]
        assert ptr_val >= RAM_BASE, f"Table 2 pointer at 0x{off:06X} invalid: 0x{ptr_val:08X}"
        rel_off = ptr_val - RAM_BASE
        assert rel_off < ENTRY3_SIZE, f"Table 2 pointer at 0x{off:06X} out of bounds: rel 0x{rel_off:06X}"
        table2_ptrs.append((off, ptr_val, rel_off))
    assert len(table2_ptrs) == SHOP_TABLE2_COUNT == 16

    # Verify that prompt_who has 2 pointers pointing to the same offset
    p1 = struct.unpack("<I", patched_buf[0x031F14 : 0x031F18])[0]
    p2 = struct.unpack("<I", patched_buf[0x031F18 : 0x031F1C])[0]
    prompt_who_alloc = report["dialogue_allocations"]["prompt_who"]["offset"]
    assert p1 == p2 == RAM_BASE + prompt_who_alloc
    assert decode_string(patched_buf[prompt_who_alloc : prompt_who_alloc + 30]) == "КОМУ ПОКУПАТЬ?"
    # Verify weapon shop greeting pointer at 0x031F20 points to 0x030F88
    pw = struct.unpack("<I", patched_buf[0x031F20 : 0x031F24])[0]
    assert pw == RAM_BASE + 0x030F88
    greeting_raw = patched_buf[0x030F88 : 0x030F88 + 24]
    assert decode_string(greeting_raw) == "<D9A1>Что нужно?"



def test_shop_items_table_030A20(shop_catalog: dict[str, Any]):
    """Test patching and pointer verification of all 91 shop items in table 0x030A20."""
    dummy_buf = bytearray(ENTRY3_SIZE)
    patched_buf, report, dyn_alloc = patch_shop_dialogues_buffer(dummy_buf, shop_catalog)

    assert "shop_items" in report
    assert report["shop_items"]["count"] == 91

    # Verify all 91 pointers in Table 0
    table0_ptrs = []
    for off in range(SHOP_ITEMS_TABLE_START, SHOP_ITEMS_TABLE_END, 4):
        ptr_val = struct.unpack("<I", patched_buf[off : off + 4])[0]
        assert ptr_val >= RAM_BASE
        rel_off = ptr_val - RAM_BASE
        assert rel_off < ENTRY3_SIZE
        table0_ptrs.append((off, ptr_val, rel_off))
    assert len(table0_ptrs) == SHOP_ITEMS_COUNT == 91

    # Verify specific items
    item_tests = [
        (0, "Лина"),
        (7, "Ф.Атк"),
        (32, "Меч Света"),
        (36, "Длинный меч"),
        (47, "Короткий меч"),
    ]
    for idx, exp_name in item_tests:
        p_off = SHOP_ITEMS_TABLE_START + idx * 4
        ptr_val = struct.unpack("<I", patched_buf[p_off : p_off + 4])[0]
        rel_off = ptr_val - RAM_BASE
        decoded_name = decode_string(patched_buf[rel_off : rel_off + 48])
        assert decoded_name == exp_name, f"Item {idx} decoded {decoded_name!r} != {exp_name!r}"

    # Verify buy_suggest_weapon has <00BF> at start of Line 2
    ptr_suggest = struct.unpack("<I", patched_buf[0x031F24 : 0x031F28])[0]
    rel_suggest = ptr_suggest - RAM_BASE
    raw_suggest = patched_buf[rel_suggest : rel_suggest + 80]
    suggest_words = [struct.unpack_from("<H", raw_suggest, i)[0] for i in range(0, len(raw_suggest), 2)]
    first_nl = suggest_words.index(0x00FE)
    assert suggest_words[first_nl + 1] == 0x00BF, "<00BF> must be at start of Line 2 in buy_suggest_weapon"

def test_entry3_edc_ecc_verification():
    """Test Mode 2 Form 1 EDC/ECC sector verification for Entry 3 on target disc image."""
    bin_path = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
    if not bin_path.is_file():
        pytest.skip(f"Target disc image not found: {bin_path}")

    res = verify_town_services(bin_path, DEFAULT_CATALOG, DEFAULT_SHOP_CATALOG)
    assert res["status"] == "valid"
    assert res["verified_sectors"] == ENTRY3_SECTORS == 296
    assert res["verified_03a_sectors"] == ENTRY_03A_SECTORS == 27
    assert res["verified_shop_dialogues"] == 98
    assert res["verified_shop_pointers"] == 100
    assert res["verified_shop_items"] == 91
    assert res["table0_pointers"] == 91
    assert res["table1_pointers"] == 84
    assert res["table2_pointers"] == 16
