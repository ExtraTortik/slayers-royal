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

from patch_repo.localization.disc import (
    CdChecksums,
    RAW_SECTOR_SIZE,
    USER_DATA_SIZE,
    read_extent,
)
from tools.patch_world_map import (
    DEFAULT_CHARMAP,
    DEFAULT_TARGET_BIN,
    DEFAULT_TRANSLATIONS,
    DELIMITER,
    MAX_TABLE_BYTES,
    NUM_LOCATIONS,
    RAM_BASE,
    RAM_BASE_1606,
    RAM_BASE_1607,
    ROAD_SLOTS_TABLE_1,
    SECTOR_89_LBA,
    SECTOR_89_TABLE_OFFSET,
    SECTOR_93_LBA,
    SECTOR_93_PTR_OFFSET,
    SECTOR_1606_LBA,
    SECTOR_1606_T1_OFFSET,
    SECTOR_1606_T1_PTR_COUNT,
    SECTOR_1606_T1_PTR_OFFSET,
    SECTOR_1606_T2_OFFSET,
    SECTOR_1607_LBA,
    SECTOR_1607_T2_PTR_COUNT,
    SECTOR_1607_T2_PTR_OFFSET,
    SPECIAL_GLYPH_NAMES,
    TABLE_1_ITEMS,
    TABLE_2_ITEMS,
    TABLE_START_IN_ENTRY,
    TOWN_SLOTS_TABLE_1,
    calculate_pointers,
    decode_location_entry,
    decode_location_strings,
    encode_location_entry,
    encode_location_strings,
    load_world_map_translations,
    patch_world_map_sectors,
    patch_world_map_sectors_1606_1607,
    verify_world_map_bin,
    verify_world_map_sectors_1606_1607,
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


def test_sector_1606_table_1_pointers_and_strings():
    """Verify all 34 pointers at 0x388 in Sector 1606 point to valid strings.

    Specifically verify:
    - All 34 pointers point to valid non-empty strings.
    - Pointer at 0x3A0 points to 'ИЗЕЛЬСЕН' without any dot.
    - Pointer at 0x3A4 points to 'ФРИГРАНТ'.
    """
    if not DEFAULT_TARGET_BIN.is_file():
        pytest.skip(f"Target disc not found: {DEFAULT_TARGET_BIN}")

    sec1606 = read_extent(DEFAULT_TARGET_BIN, SECTOR_1606_LBA, USER_DATA_SIZE)
    ptrs = struct.unpack_from(f"<{SECTOR_1606_T1_PTR_COUNT}I", sec1606, SECTOR_1606_T1_PTR_OFFSET)
    assert len(ptrs) == 34

    for idx, ptr in enumerate(ptrs):
        rel = ptr - RAM_BASE_1606
        assert SECTOR_1606_T1_OFFSET <= rel < SECTOR_1606_T1_PTR_OFFSET, (
            f"Pointer [{idx}] 0x{ptr:08X} (rel: 0x{rel:04X}) out of valid range"
        )
        s = decode_location_entry(sec1606, rel)
        assert len(s) > 0, f"Pointer [{idx}] points to empty string"

    # Pointer at 0x3A0 (index 6): 'ИЗЕЛЬСЕН' without dot
    ptr_3a0 = struct.unpack_from("<I", sec1606, 0x3A0)[0]
    s_3a0 = decode_location_entry(sec1606, ptr_3a0 - RAM_BASE_1606)
    assert s_3a0 == "ИЗЕЛЬСЕН", f"Expected 'ИЗЕЛЬСЕН' at 0x3A0, got '{s_3a0}'"
    assert "." not in s_3a0
    assert "。" not in s_3a0

    # Pointer at 0x3A4 (index 7): 'ФРИГРАНТ'
    ptr_3a4 = struct.unpack_from("<I", sec1606, 0x3A4)[0]
    s_3a4 = decode_location_entry(sec1606, ptr_3a4 - RAM_BASE_1606)
    assert s_3a4 == "ФРИГРАНТ", f"Expected 'ФРИГРАНТ' at 0x3A4, got '{s_3a4}'"


def test_sector_1607_table_2_pointers_and_strings():
    """Verify all 30 pointers at 0x0DC in Sector 1607 point to valid strings."""
    if not DEFAULT_TARGET_BIN.is_file():
        pytest.skip(f"Target disc not found: {DEFAULT_TARGET_BIN}")

    sec1606 = read_extent(DEFAULT_TARGET_BIN, SECTOR_1606_LBA, USER_DATA_SIZE)
    sec1607 = read_extent(DEFAULT_TARGET_BIN, SECTOR_1607_LBA, USER_DATA_SIZE)
    buf = sec1606 + sec1607

    ptrs = struct.unpack_from(f"<{SECTOR_1607_T2_PTR_COUNT}I", sec1607, SECTOR_1607_T2_PTR_OFFSET)
    assert len(ptrs) == 30

    for idx, ptr in enumerate(ptrs):
        rel = ptr - RAM_BASE_1606
        assert SECTOR_1606_T2_OFFSET <= rel < USER_DATA_SIZE + SECTOR_1607_T2_PTR_OFFSET, (
            f"Pointer [{idx}] 0x{ptr:08X} (rel: 0x{rel:04X}) out of Table 2 range"
        )
        s = decode_location_entry(buf, rel)
        assert len(s) > 0, f"Pointer [{idx}] points to empty string"

    # Check first two towns
    assert decode_location_entry(buf, ptrs[0] - RAM_BASE_1606) == "ЛЕЙКВУД"
    assert decode_location_entry(buf, ptrs[1] - RAM_BASE_1606) == "БАРКЛЕНД"

    # Check boundary straddling string (index 19 at 0x128)
    ptr_19 = ptrs[19]
    rel_19 = ptr_19 - RAM_BASE_1606
    assert rel_19 < USER_DATA_SIZE < rel_19 + 20, "String 19 should straddle sector boundary at 0x800"
    assert decode_location_entry(buf, rel_19) == "ВОСТ.БАРК"


def test_sector_1606_1607_edc_ecc_checksums():
    """Verify Mode 2 Form 1 EDC/ECC checksums for Sector 1606 and Sector 1607."""
    if not DEFAULT_TARGET_BIN.is_file():
        pytest.skip(f"Target disc not found: {DEFAULT_TARGET_BIN}")

    checksums = CdChecksums()
    with DEFAULT_TARGET_BIN.open("rb") as handle:
        for lba in (SECTOR_1606_LBA, SECTOR_1607_LBA):
            handle.seek(lba * RAW_SECTOR_SIZE)
            raw = handle.read(RAW_SECTOR_SIZE)
            assert len(raw) == RAW_SECTOR_SIZE, f"Failed to read LBA {lba}"
            # EDC check
            expected_edc = checksums.compute_edc(raw[0x10:0x818])
            assert raw[0x818:0x81C] == expected_edc, f"Mode 2 Form 1 EDC checksum mismatch at LBA {lba}"
            # ECC P-parity check
            expected_ecc_p = checksums.compute_ecc(raw[0x10:], 86, 24, 2, 86)
            assert raw[0x81C:0x8C8] == expected_ecc_p, f"Mode 2 Form 1 ECC P-parity mismatch at LBA {lba}"
            # ECC Q-parity check
            expected_ecc_q = checksums.compute_ecc(raw[0x10:], 52, 43, 86, 88)
            assert raw[0x8C8:0x930] == expected_ecc_q, f"Mode 2 Form 1 ECC Q-parity mismatch at LBA {lba}"


def test_verify_world_map_sectors_1606_1607_report():
    """Test verify_world_map_sectors_1606_1607 function."""
    if not DEFAULT_TARGET_BIN.is_file():
        pytest.skip(f"Target disc not found: {DEFAULT_TARGET_BIN}")

    report = verify_world_map_sectors_1606_1607(DEFAULT_TARGET_BIN)
    assert report["verified"] is True
    assert report["sector_1606_lba"] == SECTOR_1606_LBA
    assert report["sector_1607_lba"] == SECTOR_1607_LBA
    assert report["t1_pointers_count"] == 34
    assert report["t2_pointers_count"] == 30
    assert report["iselsen"] == "ИЗЕЛЬСЕН"
    assert report["frigrant"] == "ФРИГРАНТ"


def test_table_1_and_2_in_memory_simulation():
    """Test in-memory packing and pointer resolution for Table 1 and Table 2."""
    sec1606 = bytearray(USER_DATA_SIZE)
    sec1607 = bytearray(USER_DATA_SIZE)

    # Pack Table 1
    cur_off = SECTOR_1606_T1_OFFSET
    t1_offsets = []
    for idx, item in TABLE_1_ITEMS:
        enc = encode_location_entry(item)
        t1_offsets.append(cur_off)
        sec1606[cur_off : cur_off + len(enc)] = enc
        cur_off += len(enc)

    assert cur_off <= SECTOR_1606_T1_PTR_OFFSET
    t1_ptrs = [
        RAM_BASE_1606 + t1_offsets[0],
        RAM_BASE_1606 + t1_offsets[0],
    ] + [RAM_BASE_1606 + t1_offsets[i] for i in range(1, 33)]
    assert len(t1_ptrs) == 34
    struct.pack_into(f"<{SECTOR_1606_T1_PTR_COUNT}I", sec1606, SECTOR_1606_T1_PTR_OFFSET, *t1_ptrs)

    # Pack Table 2
    buf = bytearray(sec1606 + sec1607)
    cur_off_t2 = SECTOR_1606_T2_OFFSET
    t2_offsets = []
    for idx, item in TABLE_2_ITEMS:
        enc = encode_location_entry(item)
        t2_offsets.append(cur_off_t2)
        buf[cur_off_t2 : cur_off_t2 + len(enc)] = enc
        cur_off_t2 += len(enc)

    assert cur_off_t2 <= USER_DATA_SIZE + SECTOR_1607_T2_PTR_OFFSET
    sec1606 = buf[:USER_DATA_SIZE]
    sec1607 = buf[USER_DATA_SIZE : USER_DATA_SIZE * 2]
    t2_ptrs = [RAM_BASE_1606 + off for off in t2_offsets]
    struct.pack_into(f"<{SECTOR_1607_T2_PTR_COUNT}I", sec1607, SECTOR_1607_T2_PTR_OFFSET, *t2_ptrs)

    # Verify decoded results
    assert decode_location_entry(sec1606, t1_ptrs[6] - RAM_BASE_1606) == "ИЗЕЛЬСЕН"
    assert decode_location_entry(sec1606, t1_ptrs[7] - RAM_BASE_1606) == "ФРИГРАНТ"
    assert decode_location_entry(buf, t2_ptrs[0] - RAM_BASE_1606) == "ЛЕЙКВУД"
    assert decode_location_entry(buf, t2_ptrs[19] - RAM_BASE_1606) == "ВОСТ.БАРК"
