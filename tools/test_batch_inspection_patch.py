#!/usr/bin/env python3
"""Comprehensive test suite for batch room inspection patching and sector budget enforcement.

Validates:
1. Loading and resolving translations from translations/room_inspection_ru.json (Schema A)
   and data/inspection_ru.json (Schema B).
2. Sector budget enforcement and progressive condensation using tools.text_wrapper.shorten_lines.
3. Batch patching multiple synthetic room entries in a UNT archive.
4. Batch patching all 149 valid room inspection entries from real disc images with zero sector overflows.
5. CLI execution with --translations and --all-rooms flags.
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure repository root and patch_repo are in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))

from tools.patch_inspection import (
    DEFAULT_CHARMAP,
    HDR_PTR_TABLE_OFFSET,
    HDR_ROOM_NAME_PTR,
    HDR_TRAILING_PTR_1,
    HDR_TRAILING_PTR_2,
    RAM_BASE,
    ROOM_ENTRIES_END,
    ROOM_ENTRIES_START,
    SECTOR_SIZE,
    encode_string,
    load_charmap,
    parse_inspection_entry,
    parse_iso_dir,
    patch_inspection_entries,
    patch_unt_entry,
    read_extent,
    read_sector,
    read_unt_index,
    rebuild_inspection_entry,
    resolve_entry_translations,
)
from tools.text_wrapper import shorten_lines


@pytest.fixture
def charmap() -> dict[str, int]:
    return load_charmap()


@pytest.fixture
def reverse_charmap(charmap: dict[str, int]) -> dict[int, str]:
    return {v: k for k, v in charmap.items()}


@pytest.fixture
def sample_disc_bin() -> Path | None:
    for candidate in [
        REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin",
        REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin",
        REPO_ROOT / "downloads" / "sr.bin",
    ]:
        if candidate.is_file():
            return candidate
    return None


@pytest.fixture
def catalog_path() -> Path:
    return REPO_ROOT / "translations" / "room_inspection_ru.json"

@pytest.fixture
def missing_rooms_path() -> Path:
    return REPO_ROOT / "data" / "missing_rooms_jp_ru.json"


@pytest.fixture
def source_bin_path() -> Path | None:
    p = REPO_ROOT / "downloads" / "sr.bin"
    return p if p.is_file() else None


@pytest.fixture
def missing_rooms_doc(missing_rooms_path: Path) -> dict[str, Any]:
    return json.loads(missing_rooms_path.read_text(encoding="utf-8"))


def build_synthetic_room_entry(
    strings: list[str],
    charmap: dict[str, int],
    allocated_size: int = 2048,
    entry_index: int = 0x05A,
) -> bytes:
    """Construct a valid synthetic room inspection entry of exact allocated_size."""
    cm = charmap
    # Header: 0x0100 bytes minimum
    header = bytearray(0x0160)
    struct.pack_into(">I", header, 0x0000, 0x00200100)
    struct.pack_into(">I", header, 0x0008, 0x00200100)

    # Encode strings
    encoded_payload = bytearray()
    pointer_offsets: list[int] = []
    curr_offset = 0x0160
    for s in strings:
        enc = encode_string(s, cm)
        pointer_offsets.append(curr_offset)
        encoded_payload.extend(enc)
        curr_offset += len(enc)

    # Align pointer table to 4 bytes
    pt_offset = (curr_offset + 3) & ~3
    encoded_payload.extend(b"\x00" * (pt_offset - curr_offset))

    # Pointer table
    pt_payload = bytearray()
    for p_off in pointer_offsets:
        pt_payload.extend(struct.pack(">I", RAM_BASE + p_off))
    pt_end = pt_offset + len(pt_payload)

    # Trailing block (e.g. 64 bytes)
    trailing_block = b"\x11\x22\x33\x44" * 16
    trailing_offset = pt_end
    data_end = trailing_offset + len(trailing_block)

    if data_end > allocated_size:
        raise ValueError(
            f"Synthetic entry data ({data_end}) exceeds allocated size ({allocated_size})"
        )

    # Pack header pointers
    struct.pack_into(">I", header, HDR_PTR_TABLE_OFFSET, RAM_BASE + pt_offset)
    struct.pack_into(">I", header, HDR_TRAILING_PTR_1, RAM_BASE + trailing_offset)
    struct.pack_into(">I", header, HDR_TRAILING_PTR_2, RAM_BASE + trailing_offset + 0x10)
    struct.pack_into(">I", header, HDR_ROOM_NAME_PTR, RAM_BASE + 0x0040)

    entry = bytearray(allocated_size)
    entry[:0x0160] = header
    entry[0x0160 : 0x0160 + len(encoded_payload)] = encoded_payload
    entry[pt_offset:pt_end] = pt_payload
    entry[trailing_offset:data_end] = trailing_block
    return bytes(entry)


def build_synthetic_unt_archive(
    room_entries: dict[int, bytes],
    total_entries: int = 260,
) -> bytearray:
    """Build a synthetic UNT archive with allocation table at sector 0 and given room entries."""
    archive = bytearray(SECTOR_SIZE)  # Sector 0 index table
    curr_sector = 1

    entry_specs: list[tuple[int, int]] = []
    payloads: list[bytes] = []

    for idx in range(total_entries):
        if idx in room_entries:
            data = room_entries[idx]
            sectors = (len(data) + SECTOR_SIZE - 1) // SECTOR_SIZE
            padded_len = sectors * SECTOR_SIZE
            padded_data = data.ljust(padded_len, b"\x00")
            entry_specs.append((curr_sector, sectors))
            payloads.append(padded_data)
            curr_sector += sectors
        else:
            # Dummy 1-sector entry
            entry_specs.append((curr_sector, 1))
            payloads.append(b"\x00" * SECTOR_SIZE)
            curr_sector += 1

    # Pack allocation table in sector 0
    for idx, (sec_start, sec_count) in enumerate(entry_specs):
        pos = idx * 4
        if pos + 4 <= SECTOR_SIZE:
            struct.pack_into("<HH", archive, pos, sec_start, sec_count)
    for p in payloads:
        archive.extend(p)

    return archive


# ===========================================================================
# 1. Translation Catalog Loading & Resolution Tests
# ===========================================================================

def test_catalog_file_exists_and_valid(catalog_path: Path):
    """Verify translations/room_inspection_ru.json is valid JSON with expected structure."""
    assert catalog_path.is_file(), f"Catalog not found at {catalog_path}"
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert len(data) >= 700, f"Expected >= 700 catalog entries, got {len(data)}"

    # Verify each entry has a non-empty russian string and expected metadata
    sample_key = next(iter(data))
    sample_val = data[sample_key]
    assert "russian" in sample_val
    assert isinstance(sample_val["russian"], str)
    assert len(sample_val["russian"]) > 0


def test_resolve_entry_translations_catalog_schema(charmap: dict[str, int]):
    """Verify resolve_entry_translations handles translations/room_inspection_ru.json schema."""
    original_strings = [
        "A tree.",
        "A stone wall.",
        "Unknown untranslated object.",
        "Empty translation object.",
    ]
    entry_bytes = build_synthetic_room_entry(original_strings, charmap, allocated_size=2048)
    info = parse_inspection_entry(entry_bytes, entry_index=0x05A, charmap=charmap)

    doc = {
        "A tree.": {
            "russian": "Дерево.",
            "type": "name",
            "rooms": ["0x05A"],
        },
        "A stone wall.": "Каменная стена.",  # direct string format
        "Empty translation object.": {
            "russian": "",
            "type": "description",
        },
    }

    resolved, room_name = resolve_entry_translations(info, doc)
    assert len(resolved) == 4
    # Translated with dict schema
    assert resolved[0] == "Дерево."
    # Translated with direct string schema
    assert resolved[1] == "Каменная стена."
    # Missing translation keeps original English string
    assert resolved[2] == "Unknown untranslated object."
    # Empty translation keeps original English string
    assert resolved[3] == "Empty translation object."
    assert room_name is None


def test_resolve_entry_translations_schema_b_compatibility(charmap: dict[str, int]):
    """Verify resolve_entry_translations retains backward compatibility with data/inspection_ru.json."""
    original_strings = ["Diner ceiling.", "Just a wall.", "A water jar."]
    entry_bytes = build_synthetic_room_entry(original_strings, charmap, allocated_size=2048)
    info = parse_inspection_entry(entry_bytes, entry_index=0x05D, charmap=charmap)

    doc = {
        "entries": {
            "0x05D": {
                "room_name": "ТАВЕРНА",
                "strings": ["Потолок таверны.", "", "Кувшин с водой."],
            }
        },
        "common": {
            "Just a wall.": "Просто стена.",
        },
    }

    resolved, room_name = resolve_entry_translations(info, doc)
    assert resolved[0] == "Потолок таверны."
    assert resolved[1] == "Просто стена."  # Fallback to common
    assert resolved[2] == "Кувшин с водой."
    assert room_name == "ТАВЕРНА"


# ===========================================================================
# 2. Sector Budget Enforcement & Progressive Condensation Tests
# ===========================================================================

def test_progressive_condensation_resolves_overflow(charmap: dict[str, int]):
    """Verify that an entry exceeding its sector budget is automatically condensed to fit."""
    # Construct base strings that fit comfortably in 2048 bytes
    base_strings = [
        "Короткая строка.",
        "Ещё одна строка.",
        "И третья строка.",
    ]
    entry_bytes = build_synthetic_room_entry(base_strings, charmap, allocated_size=2048)

    # Now create candidate translations with long 3-line strings that would exceed 2048 bytes
    # Overhead in 2048 byte entry: header (0x0160=352) + PT (12) + trailing (64) = 428 bytes
    # Available for strings: 2048 - 428 = 1620 bytes.
    # We will create strings that take ~1630 bytes (overflow by ~10 bytes).
    # Each char is 2 bytes + 2 terminator.
    line_a = "Раз два три чет"  # 15 chars
    line_b = "Пять шесть семь"  # 15 chars
    line_c = "Восемь девять"  # 13 chars
    overflow_3line = f"{line_a}\n{line_b}\n{line_c}"

    # Build 30 pointers to simulate a real busy room
    busy_strings = [f"Объект номер {i:02d}." for i in range(25)]
    busy_entry_bytes = build_synthetic_room_entry(busy_strings, charmap, allocated_size=2048)
    info = parse_inspection_entry(busy_entry_bytes, entry_index=0x05A, charmap=charmap)

    # Fill translations with 3-line strings so total data exceeds 2048 bytes
    long_translations = [overflow_3line] * info.num_pointers

    # 1. With progressive_shorten=False, must raise ValueError
    with pytest.raises(ValueError, match="exceeds allocated capacity"):
        rebuild_inspection_entry(
            busy_entry_bytes,
            long_translations,
            charmap=charmap,
            entry_index=0x05A,
            progressive_shorten=False,
        )

    # 2. With progressive_shorten=True, progressive condensation applies shorten_lines
    rebuilt_bytes, result = rebuild_inspection_entry(
        busy_entry_bytes,
        long_translations,
        charmap=charmap,
        entry_index=0x05A,
        progressive_shorten=True,
    )

    assert result.used_size <= result.allocated_size
    assert result.free_margin >= 0
    assert len(rebuilt_bytes) == 2048

    # Verify that the rebuilt entry is valid and readable
    re_info = parse_inspection_entry(rebuilt_bytes, entry_index=0x05A, charmap=charmap)
    assert re_info.num_pointers == info.num_pointers
    # Assert progressive shortening occurred so that data fits
    assert any(len(s.splitlines()) <= 2 for s in re_info.extracted_strings)

def test_impossible_budget_overflow_still_raises_error(charmap: dict[str, int]):
    """Massive 1-line strings that cannot be condensed by shorten_lines must raise ValueError."""
    strings = ["Короткая строка."] * 10
    entry_bytes = build_synthetic_room_entry(strings, charmap, allocated_size=2048)
    info = parse_inspection_entry(entry_bytes, entry_index=0x05A, charmap=charmap)

    # Massive 1-line strings (each 300 characters, impossible in 2048 bytes)
    massive_1line = ["Очень длинная строка без переносов " * 8] * info.num_pointers

    with pytest.raises(ValueError, match="exceeds allocated capacity"):
        rebuild_inspection_entry(
            entry_bytes,
            massive_1line,
            charmap=charmap,
            entry_index=0x05A,
            progressive_shorten=True,
        )


# ===========================================================================
# 3. Synthetic Multi-Room UNT Batch Patching Tests
# ===========================================================================

def test_batch_patch_synthetic_unt_archive(charmap: dict[str, int]):
    """Verify batch patching across multiple synthetic rooms in a single UNT archive."""
    room_defs = {
        0x05A: (["Tree in garden.", "Wall near house."], 2048),
        0x05B: (["Fountain.", "Plaque on fountain.", "Flower bed."], 4096),
        0x05C: (["Iron gate.", "Stone path."], 2048),
    }

    room_entries = {}
    for r_idx, (s_list, size) in room_defs.items():
        room_entries[r_idx] = build_synthetic_room_entry(
            s_list, charmap, allocated_size=size, entry_index=r_idx
        )

    archive = build_synthetic_unt_archive(room_entries, total_entries=0x060)

    translations = {
        "Tree in garden.": {"russian": "Дерево в саду."},
        "Wall near house.": {"russian": "Стена у дома."},
        "Fountain.": {"russian": "Фонтан на площади."},
        "Plaque on fountain.": {"russian": "Табличка."},
        "Flower bed.": {"russian": "Клумба."},
        "Iron gate.": {"russian": "Кованые ворота."},
        "Stone path.": {"russian": "Каменная дорожка."},
    }

    results = patch_inspection_entries(
        archive,
        translations,
        charmap=charmap,
        all_rooms=True,
    )

    assert len(results) == 3
    result_map = {r.entry_index: r for r in results}

    for r_idx, (_, expected_size) in room_defs.items():
        assert r_idx in result_map
        r = result_map[r_idx]
        assert r.allocated_size == expected_size
        assert r.used_size <= expected_size
        assert r.free_margin >= 0

    # Re-parse patched entries from archive and verify translated text
    entries = read_unt_index(archive)
    info_5a = parse_inspection_entry(entries[0x05A].extract(archive), 0x05A, charmap)
    assert info_5a.extracted_strings == ["Дерево в саду.", "Стена у дома."]

    info_5b = parse_inspection_entry(entries[0x05B].extract(archive), 0x05B, charmap)
    assert info_5b.extracted_strings == ["Фонтан на площади.", "Табличка.", "Клумба."]

    info_5c = parse_inspection_entry(entries[0x05C].extract(archive), 0x05C, charmap)
    assert info_5c.extracted_strings == ["Кованые ворота.", "Каменная дорожка."]


# ===========================================================================
# 4. Real Disc Batch Patching & Sector Boundary Compliance Tests
# ===========================================================================

def test_batch_patching_real_disc_all_rooms(
    sample_disc_bin: Path | None,
    catalog_path: Path,
    charmap: dict[str, int],
):
    """Batch-patch all 149 room inspection entries in real PROG.UNT and verify sector limits."""
    if sample_disc_bin is None:
        pytest.skip("No real PS1 BIN image found in repo (downloads/sr.bin or localization-output/)")

    pvd = read_sector(sample_disc_bin, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(sample_disc_bin, root_lba, root_size)
    assert "PROG.UNT" in root_dir, "PROG.UNT not found in ISO directory"

    prog_lba, prog_size = root_dir["PROG.UNT"]
    prog_archive = bytearray(read_extent(sample_disc_bin, prog_lba, prog_size))
    entries = read_unt_index(prog_archive)
    assert len(entries) >= ROOM_ENTRIES_END

    translations_doc = json.loads(catalog_path.read_text(encoding="utf-8"))

    results = patch_inspection_entries(
        prog_archive,
        translations_doc,
        charmap=charmap,
        all_rooms=True,
    )

    # Exactly 149 valid room inspection entries exist in 0x059..0x0F8
    assert len(results) == 149, f"Expected 149 patched rooms, got {len(results)}"

    # Verify sector budget and boundary compliance across ALL 149 rooms
    for r in results:
        assert r.allocated_size % SECTOR_SIZE == 0, f"Room {r.entry_index:#05x} not sector aligned"
        assert (
            r.used_size <= r.allocated_size
        ), f"Room {r.entry_index:#05x} OVERFLOW: {r.used_size} > {r.allocated_size}"
        assert r.free_margin >= 0, f"Room {r.entry_index:#05x} negative margin: {r.free_margin}"
        assert r.pointer_table_offset >= 0x0160

    # Specifically verify Room 0x0C5 (which naturally overflows by 20 bytes without progressive shortening)
    c5_results = [r for r in results if r.entry_index == 0x0C5]
    assert len(c5_results) == 1
    c5 = c5_results[0]
    assert c5.allocated_size == 2048, "Room 0x0C5 must be 1 sector (2048 bytes)"
    assert c5.used_size <= 2048, f"Room 0x0C5 overflowed: {c5.used_size} > 2048"
    assert c5.free_margin >= 0
    # Re-parse sample room entries from patched archive to verify RAM pointers
    patched_entries = read_unt_index(prog_archive)

    # Specifically verify Room 0x059 (MAIN ST) patches with 43 Russian strings
    r59_results = [r for r in results if r.entry_index == 0x059]
    assert len(r59_results) == 1, "Room 0x059 must be patched"
    r59 = r59_results[0]
    assert r59.strings_count == 43, f"Room 0x059 must have 43 strings, got {r59.strings_count}"
    assert r59.used_size <= r59.allocated_size, f"Room 0x059 overflow: {r59.used_size} > {r59.allocated_size}"
    assert r59.free_margin >= 0

    info_59 = parse_inspection_entry(patched_entries[0x059].extract(prog_archive), 0x059, charmap)
    assert len(info_59.extracted_strings) == 43
    assert all(len(s.strip()) > 0 for s in info_59.extracted_strings), "All 43 strings in 0x059 must be non-empty"
    assert info_59.extracted_strings[0] == "Небо между\nдеревьями."

    for sample_idx in [0x05A, 0x05D, 0x0C5, 0x0BE]:
        sample_bytes = patched_entries[sample_idx].extract(prog_archive)
        info = parse_inspection_entry(sample_bytes, entry_index=sample_idx, charmap=charmap)
        assert info.num_pointers > 0
        assert info.min_str_offset >= 0x0160
        assert info.ptr_table_offset >= info.min_str_offset
        assert all(p >= info.min_str_offset for p in info.pointer_offsets)


# ===========================================================================
# 5. CLI Invocation Tests
# ===========================================================================

def test_cli_batch_patch_prog(catalog_path: Path, charmap: dict[str, int]):
    """Test CLI batch patching on standalone PROG.UNT with --prog and --all-rooms."""
    room_entries = {
        0x05A: build_synthetic_room_entry(["A tree."], charmap, 2048, 0x05A),
        0x05B: build_synthetic_room_entry(["A window."], charmap, 2048, 0x05B),
    }
    archive = build_synthetic_unt_archive(room_entries, total_entries=0x060)

    with tempfile.TemporaryDirectory() as tmpdir:
        prog_path = Path(tmpdir) / "TEST_PROG.UNT"
        prog_path.write_bytes(archive)

        cmd = [
            sys.executable,
            str(REPO_ROOT / "tools" / "patch_inspection.py"),
            "--prog",
            str(prog_path),
            "--translations",
            str(catalog_path),
            "--all-rooms",
            "--verbose",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 0, f"CLI failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        assert "Successfully patched 2 inspection entries" in proc.stdout
        assert "Entry 0x05a:" in proc.stdout
        assert "Entry 0x05b:" in proc.stdout

        # Verify modified binary
        modified_data = prog_path.read_bytes()
        mod_entries = read_unt_index(modified_data)
        mod_info = parse_inspection_entry(mod_entries[0x05A].extract(modified_data), 0x05A, charmap)
        assert len(mod_info.extracted_strings) == 1
        # In translations/room_inspection_ru.json, "A tree." or similar is translated
        assert mod_info.extracted_strings[0] != ""


# ===========================================================================
# 6. Omitted Rooms & Room 0x059 (MAIN ST) Restoration Tests
# ===========================================================================

def test_room_059_main_st_43_russian_strings(
    sample_disc_bin: Path | None,
    catalog_path: Path,
    missing_rooms_doc: dict[str, Any],
    charmap: dict[str, int],
):
    """Verify Lakewood MAIN ST (0x059) patches with exactly 43 Russian strings and 0 overflows."""
    if sample_disc_bin is None:
        pytest.skip("No PS1 BIN image found in repo")

    pvd = read_sector(sample_disc_bin, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(sample_disc_bin, root_lba, root_size)
    assert "PROG.UNT" in root_dir

    prog_lba, prog_size = root_dir["PROG.UNT"]
    prog_archive = bytearray(read_extent(sample_disc_bin, prog_lba, prog_size))

    cat = json.loads(catalog_path.read_text(encoding="utf-8"))
    results = patch_inspection_entries(
        prog_archive,
        cat,
        charmap=charmap,
        target_entries=[0x059],
        missing_rooms_doc=missing_rooms_doc,
    )
    assert len(results) == 1
    res = results[0]
    assert res.entry_index == 0x059
    assert res.strings_count == 43
    assert res.allocated_size == 4096
    assert res.used_size <= 4096, f"Room 0x059 overflow: {res.used_size} > 4096"
    assert res.free_margin >= 0

    # Extract and parse patched entry
    entries = read_unt_index(prog_archive)
    entry_bytes = entries[0x059].extract(prog_archive)
    info = parse_inspection_entry(entry_bytes, entry_index=0x059, charmap=charmap)
    assert info.num_pointers == 43
    assert len(info.extracted_strings) == 43
    assert all(len(s.strip()) > 0 for s in info.extracted_strings)

    # Validate key strings from Lakewood MAIN ST in Lina's voice
    assert info.extracted_strings[0] == "Небо между\nдеревьями."
    assert info.extracted_strings[1] == "Небо между\nдеревьями."
    assert info.extracted_strings[2] == "Хорошая погода."
    assert info.extracted_strings[3] == "Вон там вдали\nвидны деревья."
    assert info.extracted_strings[4] == "Здоровое такое\nдерево."


def test_all_37_omitted_rooms_zero_sector_overflows(
    sample_disc_bin: Path | None,
    catalog_path: Path,
    missing_rooms_doc: dict[str, Any],
    charmap: dict[str, int],
):
    """Verify all 37 omitted rooms patch cleanly with 0 sector overflows and non-empty strings."""
    if sample_disc_bin is None:
        pytest.skip("No PS1 BIN image found in repo")

    pvd = read_sector(sample_disc_bin, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(sample_disc_bin, root_lba, root_size)
    prog_lba, prog_size = root_dir["PROG.UNT"]
    prog_archive = bytearray(read_extent(sample_disc_bin, prog_lba, prog_size))

    target_rooms = [int(k, 16) for k in missing_rooms_doc.keys()]
    assert len(target_rooms) == 37

    cat = json.loads(catalog_path.read_text(encoding="utf-8"))
    results = patch_inspection_entries(
        prog_archive,
        cat,
        charmap=charmap,
        target_entries=target_rooms,
        missing_rooms_doc=missing_rooms_doc,
    )

    assert len(results) == 37
    result_map = {r.entry_index: r for r in results}

    entries = read_unt_index(prog_archive)
    for r_idx in target_rooms:
        assert r_idx in result_map, f"Room {r_idx:#05x} missing from results"
        r = result_map[r_idx]
        assert r.allocated_size % SECTOR_SIZE == 0
        assert r.used_size <= r.allocated_size, f"Room {r_idx:#05x} OVERFLOW: {r.used_size} > {r.allocated_size}"
        assert r.free_margin >= 0

        # Validate extracted strings are non-empty
        patched_bytes = entries[r_idx].extract(prog_archive)
        info = parse_inspection_entry(patched_bytes, entry_index=r_idx, charmap=charmap)
        expected_count = len(missing_rooms_doc[f"0x{r_idx:03X}"]["strings_ru"])
        assert info.num_pointers == expected_count
        assert len(info.extracted_strings) == expected_count
        assert all(len(s.strip()) > 0 for s in info.extracted_strings), f"Room {r_idx:#05x} has empty strings"


def test_zeroed_entry_fallback_to_source_prog(charmap: dict[str, int]):
    """Test that zeroed/corrupt room entries fall back to source_prog for pointer tables."""
    cm = charmap
    source_room = build_synthetic_room_entry(
        ["Japanese text 1.", "Japanese text 2."], cm, allocated_size=2048, entry_index=0x059
    )
    source_archive = build_synthetic_unt_archive({0x059: source_room}, total_entries=0x060)

    # Target archive entry has empty/zeroed strings
    zeroed_room = build_synthetic_room_entry(["", ""], cm, allocated_size=2048, entry_index=0x059)
    target_archive = build_synthetic_unt_archive({0x059: zeroed_room}, total_entries=0x060)

    test_missing_doc = {
        "0x059": {
            "strings_ru": ["Русская строка 1.", "Русская строка 2."]
        }
    }

    results = patch_inspection_entries(
        target_archive,
        translations_doc={},
        charmap=cm,
        target_entries=[0x059],
        missing_rooms_doc=test_missing_doc,
        source_prog=bytes(source_archive),
    )

    assert len(results) == 1
    assert results[0].entry_index == 0x059
    assert results[0].strings_count == 2
    assert results[0].free_margin >= 0

    entries = read_unt_index(target_archive)
    info = parse_inspection_entry(entries[0x059].extract(target_archive), 0x059, cm)
    assert info.extracted_strings == ["Русская строка 1.", "Русская строка 2."]


def test_cli_patch_room_059_missing_rooms(
    sample_disc_bin: Path | None,
    missing_rooms_path: Path,
    charmap: dict[str, int],
):
    """Test CLI patching Room 0x059 with --entry and --missing-rooms on standalone PROG.UNT."""
    if sample_disc_bin is None:
        pytest.skip("No PS1 BIN image found in repo")

    pvd = read_sector(sample_disc_bin, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(sample_disc_bin, root_lba, root_size)
    prog_lba, prog_size = root_dir["PROG.UNT"]
    archive_data = read_extent(sample_disc_bin, prog_lba, prog_size)

    with tempfile.TemporaryDirectory() as tmpdir:
        prog_path = Path(tmpdir) / "TEST_PROG.UNT"
        prog_path.write_bytes(archive_data)

        cmd = [
            sys.executable,
            str(REPO_ROOT / "tools" / "patch_inspection.py"),
            "--prog",
            str(prog_path),
            "--entry",
            "0x059",
            "--missing-rooms",
            str(missing_rooms_path),
            "--source-bin",
            str(sample_disc_bin),
            "--verbose",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 0, f"CLI failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        assert "Entry 0x059 (omitted room): 43 strings" in proc.stdout

        # Verify patched binary
        mod_data = prog_path.read_bytes()
        mod_entries = read_unt_index(mod_data)
        mod_info = parse_inspection_entry(mod_entries[0x059].extract(mod_data), 0x059, charmap)
        assert mod_info.num_pointers == 43
        assert mod_info.extracted_strings[0] == "Небо между\nдеревьями."
