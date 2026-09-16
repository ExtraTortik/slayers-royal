"""Unit and integration tests for tools/patch_world_map.py."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from patch_repo.localization.disc import USER_DATA_SIZE
from tools.patch_world_map import (
    DEFAULT_CHARMAP,
    DEFAULT_TARGET_BIN,
    DEFAULT_TRANSLATIONS,
    DELIMITER,
    MAX_TABLE_BYTES,
    NUM_LOCATIONS,
    RAM_BASE,
    SECTOR_89_LBA,
    SECTOR_89_TABLE_OFFSET,
    SECTOR_93_LBA,
    SECTOR_93_PTR_OFFSET,
    TABLE_START_IN_ENTRY,
    calculate_pointers,
    decode_location_strings,
    encode_location_strings,
    load_world_map_translations,
    patch_world_map_sectors,
    verify_world_map_bin,
)


@pytest.fixture
def translations_catalog() -> list[str]:
    """Load canonical Russian translations catalog."""
    return load_world_map_translations(DEFAULT_TRANSLATIONS)


def test_load_world_map_translations(translations_catalog: list[str]):
    """Test loading and verifying all 20 Russian location names from catalog."""
    assert len(translations_catalog) == NUM_LOCATIONS

    expected_samples = {
        0: "ЛЕЙКВУД",
        1: "БАРКЛЕНД",
        2: "ГРАМСТОК",
        3: "СОНИЯ",
        4: "МАРК-УЭЛЛС",
        5: "ИЗЕЛЬСЕН",
        6: "ФРИГРАНТ",
        7: "КЬЮЗАК",
        8: "СЕЙРУН",
        9: "САМБУРГ",
        10: "ТУР-СИТИ",
        11: "ЛЕЗАРИАМ",
        12: "В. ЛЕС БАРКЛЕНДА",
        13: "З. ЛЕС БАРКЛЕНДА",
        14: "В. ГРАМСТОК",
        15: "ТРАКТ СОНИИ",
        16: "ЗАКОУЛКИ СОНИИ",
        17: "ПЕРЕУЛКИ СОНИИ",
        18: "Ю. ЛЕС БАРКЛЕНДА",
        19: "В. ЛЕС БАРКЛЕНДА",
    }

    for idx, expected in expected_samples.items():
        assert translations_catalog[idx] == expected, (
            f"Location [{idx:02d}] mismatch: expected '{expected}', got '{translations_catalog[idx]}'"
        )


def test_encode_location_strings(translations_catalog: list[str]):
    """Test encoding Russian strings as 16-bit LE words delimited by 0x00FF."""
    table_bytes, offsets = encode_location_strings(translations_catalog)

    assert isinstance(table_bytes, bytes)
    assert len(offsets) == NUM_LOCATIONS
    assert offsets[0] == 0

    # All offsets must be even (16-bit aligned)
    for off in offsets:
        assert off % 2 == 0, f"Offset {off} is not 16-bit aligned"

    # Verify first string: "ЛЕЙКВУД"
    expected_words_0 = [
        DEFAULT_CHARMAP["Л"],
        DEFAULT_CHARMAP["Е"],
        DEFAULT_CHARMAP["Й"],
        DEFAULT_CHARMAP["К"],
        DEFAULT_CHARMAP["В"],
        DEFAULT_CHARMAP["У"],
        DEFAULT_CHARMAP["Д"],
        DELIMITER,
    ]
    words_0 = [struct.unpack_from("<H", table_bytes, i)[0] for i in range(0, len(expected_words_0) * 2, 2)]
    assert words_0 == expected_words_0

    # Verify second string: "БАРКЛЕНД"
    off_1 = offsets[1]
    assert off_1 == len(expected_words_0) * 2  # 16 bytes
    expected_words_1 = [
        DEFAULT_CHARMAP["Б"],
        DEFAULT_CHARMAP["А"],
        DEFAULT_CHARMAP["Р"],
        DEFAULT_CHARMAP["К"],
        DEFAULT_CHARMAP["Л"],
        DEFAULT_CHARMAP["Е"],
        DEFAULT_CHARMAP["Н"],
        DEFAULT_CHARMAP["Д"],
        DELIMITER,
    ]
    words_1 = [struct.unpack_from("<H", table_bytes, off_1 + i)[0] for i in range(0, len(expected_words_1) * 2, 2)]
    assert words_1 == expected_words_1

def test_encode_invalid_strings():
    """Test error handling for missing glyphs or incorrect string counts."""
    with pytest.raises(ValueError, match="Expected 20 strings"):
        encode_location_strings(["СТОЛИЦА", "ЛЕЙКВУД"])

    bad_strings = ["СТОЛИЦА"] * 19 + ["ЛЕЙКВУД\U0001F600"]  # contains emoji
    with pytest.raises(ValueError, match="is missing from charmap"):
        encode_location_strings(bad_strings)


def test_table_boundary_check(translations_catalog: list[str]):
    """Test that total table length <= 458 bytes and overflow raises ValueError."""
    table_bytes, _ = encode_location_strings(translations_catalog)
    assert len(table_bytes) <= MAX_TABLE_BYTES, (
        f"Table size {len(table_bytes)} exceeds maximum budget of {MAX_TABLE_BYTES} bytes"
    )

    oversized_strings = ["СЕЙРУНСЕЙРУНСЕЙРУНСЕЙРУНСЕЙРУН"] * 20
    with pytest.raises(ValueError, match="exceeds maximum budget"):
        encode_location_strings(oversized_strings)


def test_pointer_calculation(translations_catalog: list[str]):
    """Test pointer calculation formula: 0x8005BDB0 + offset."""
    _, offsets = encode_location_strings(translations_catalog)
    pointers = calculate_pointers(offsets)

    assert len(pointers) == NUM_LOCATIONS

    # RAM base 0x8005BDB0 + TABLE_START_IN_ENTRY (0x05FC) = 0x8005C3AC
    expected_base_ptr = RAM_BASE + TABLE_START_IN_ENTRY  # 0x8005C3AC
    assert expected_base_ptr == 0x8005C3AC

    for idx, (off, ptr) in enumerate(zip(offsets, pointers)):
        expected_ptr = expected_base_ptr + off
        assert ptr == expected_ptr, (
            f"Pointer [{idx:02d}] mismatch: expected 0x{expected_ptr:08X}, got 0x{ptr:08X}"
        )
        assert ptr % 2 == 0, f"Pointer 0x{ptr:08X} must be 16-bit aligned"

    # Pointer 0 and 1 checks
    assert pointers[0] == 0x8005C3AC
    assert pointers[1] == 0x8005C3AC + 16  # "ЛЕЙКВУД" is 7 chars + delimiter = 16 bytes

def test_round_trip_encoding_and_decoding(translations_catalog: list[str]):
    """Test round-trip fidelity: encode -> decode reproduces original strings."""
    table_bytes, _ = encode_location_strings(translations_catalog)
    decoded = decode_location_strings(table_bytes, NUM_LOCATIONS)

    assert len(decoded) == NUM_LOCATIONS
    assert decoded == translations_catalog


def test_patch_world_map_sectors_in_memory(translations_catalog: list[str]):
    """Test sector injection in memory: Sector 89 table + padding and Sector 93 pointers."""
    dummy_sec89 = bytearray(b"\x00" * 0x07C6 + b"\x5A" * (USER_DATA_SIZE - 0x07C6))
    dummy_sec93 = bytearray(USER_DATA_SIZE)

    new_sec89, new_sec93, ptrs = patch_world_map_sectors(bytes(dummy_sec89), bytes(dummy_sec93), translations_catalog)

    assert len(new_sec89) == USER_DATA_SIZE
    assert len(new_sec93) == USER_DATA_SIZE
    assert len(ptrs) == NUM_LOCATIONS

    # Verify system table at 0x07C6 is preserved
    assert new_sec89[0x07C6:] == dummy_sec89[0x07C6:]

    # Verify Sector 89 table starting offset
    table_bytes, offsets = encode_location_strings(translations_catalog)
    assert new_sec89[SECTOR_89_TABLE_OFFSET : SECTOR_89_TABLE_OFFSET + len(table_bytes)] == table_bytes

    # Verify padding between table and 0x07C6 is zeros
    pad_start = SECTOR_89_TABLE_OFFSET + len(table_bytes)
    assert all(b == 0 for b in new_sec89[pad_start:0x07C6])

    # Verify Sector 93 pointer values
    expected_ptrs = calculate_pointers(offsets)
    for idx, expected_ptr in enumerate(expected_ptrs):
        ptr_off = SECTOR_93_PTR_OFFSET + idx * 4
        actual_ptr = struct.unpack_from("<I", new_sec93, ptr_off)[0]
        assert actual_ptr == expected_ptr

    short_sec = b"\x00" * 1000
    valid_sec = b"\x00" * USER_DATA_SIZE
    with pytest.raises(ValueError, match="Sector 89 must be 2048 bytes"):
        patch_world_map_sectors(short_sec, valid_sec, translations_catalog)

    with pytest.raises(ValueError, match="Sector 93 must be 2048 bytes"):
        patch_world_map_sectors(valid_sec, short_sec, translations_catalog)


def test_verify_on_target_disc():
    """Verify world map patch on target disc if present."""
    if not DEFAULT_TARGET_BIN.is_file():
        pytest.skip(f"Target disc not found: {DEFAULT_TARGET_BIN}")

    report = verify_world_map_bin(DEFAULT_TARGET_BIN, DEFAULT_TRANSLATIONS)
    assert report["verified"] is True
    assert report["locations_count"] == NUM_LOCATIONS
    assert report["table_bytes"] <= MAX_TABLE_BYTES
    assert report["sector_89_lba"] == SECTOR_89_LBA
    assert report["sector_93_lba"] == SECTOR_93_LBA
    assert report["edc_ecc_verified_sectors"] == 2
    assert report["first_location"] == "ЛЕЙКВУД"
    assert report["second_location"] == "БАРКЛЕНД"


def test_cli_verify_mode():
    """Test CLI execution with --verify flag."""
    if not DEFAULT_TARGET_BIN.is_file():
        pytest.skip(f"Target disc not found: {DEFAULT_TARGET_BIN}")

    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "patch_world_map.py"),
        "--bin",
        str(DEFAULT_TARGET_BIN),
        "--verify",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"CLI --verify failed: {res.stderr}"
    assert "[PASS] World map patch verification successful!" in res.stdout


def test_cli_dry_run():
    """Test CLI execution with --dry-run flag."""
    if not DEFAULT_TARGET_BIN.is_file():
        pytest.skip(f"Target disc not found: {DEFAULT_TARGET_BIN}")

    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "patch_world_map.py"),
        "--bin",
        str(DEFAULT_TARGET_BIN),
        "--dry-run",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"CLI --dry-run failed: {res.stderr}"
    assert "[OK] Dry run successful" in res.stdout
