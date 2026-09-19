import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import struct
import tempfile
from pathlib import Path

import pytest

from tools.sync_savestates import (
    SEC1606_LBA,
    SEC1607_LBA,
    SEC1606_RAM_BASE,
    SEC1607_RAM_BASE,
    SEC1606_RAM_OFFSET,
    SEC1607_RAM_OFFSET,
    compress_zstd,
    decompress_zstd,
    find_ram_offset,
    find_zstd_magic_offsets,
    is_world_map_in_payload,
    sync_single_savestate,
    verify_savestates,
)


def test_sector_constants():
    assert SEC1606_LBA == 230626
    assert SEC1607_LBA == 230627
    assert SEC1606_RAM_BASE == 0x800805B0
    assert SEC1607_RAM_BASE == 0x80080DB0
    assert SEC1606_RAM_OFFSET == 0x0805B0
    assert SEC1607_RAM_OFFSET == 0x080DB0


def test_find_ram_offset_system_chunk():
    # Standard chunk at offset 0
    payload = bytearray(0x250000)
    payload[0:10] = b"\x06\x00\x00\x00System"
    assert find_ram_offset(bytes(payload)) == 0x1A62

    # Shifted chunk (like savestate 6 with screenshot stream in payload)
    payload2 = bytearray(0x280000)
    payload2[0x30000 : 0x30000 + 10] = b"\x06\x00\x00\x00System"
    assert find_ram_offset(bytes(payload2)) == 0x31A62


def test_is_world_map_in_payload_detection():
    payload = bytearray(0x250000)
    ram_off = 0x1A62
    sec1606_off = ram_off + SEC1606_RAM_OFFSET

    # Initially empty
    assert not is_world_map_in_payload(bytes(payload), ram_off)

    # With ЛЕЙК at 0x150
    payload[sec1606_off + 0x150 : sec1606_off + 0x158] = b"\x12\x00\x0c\x00\x10\x00\x11\x00"
    assert is_world_map_in_payload(bytes(payload), ram_off)

    # Without ЛЕЙК, but with pointer at 0x388
    payload[sec1606_off + 0x150 : sec1606_off + 0x158] = b"\x00" * 8
    struct.pack_into("<I", payload, sec1606_off + 0x0388, 0x80080700)
    assert is_world_map_in_payload(bytes(payload), ram_off)


def test_sync_single_savestate_world_map():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        sav_file = tmp / "SLPS-01363_1.sav"

        # Construct a mock DuckStation savestate
        ram_payload = bytearray(0x220000)
        ram_payload[0:10] = b"\x06\x00\x00\x00System"
        ram_off = 0x1A62
        sec1606_off = ram_off + SEC1606_RAM_OFFSET
        sec1607_off = ram_off + SEC1607_RAM_OFFSET

        # Mark as world map with pointer table
        struct.pack_into("<I", ram_payload, sec1606_off + 0x0388, 0x80080700)
        # Old sector contents
        ram_payload[sec1606_off : sec1606_off + 2048] = b"\xAA" * 2048
        struct.pack_into("<I", ram_payload, sec1606_off + 0x0388, 0x80080700)
        ram_payload[sec1607_off : sec1607_off + 2048] = b"\xBB" * 2048

        # Compress into savestate
        compressed = compress_zstd(bytes(ram_payload))
        # 2-stream mock (stream 0 screenshot, stream 1 state)
        fake_screenshot = compress_zstd(b"screenshot")
        full_sav = b"\x00" * 0x100 + fake_screenshot + compressed
        sav_file.write_bytes(full_sav)

        fake_sec1606 = b"\x11" * 2048
        fake_sec1607 = b"\x22" * 2048

        # 1. Dry run
        rep = sync_single_savestate(
            sav_file,
            sec1606_disc=fake_sec1606,
            sec1607_disc=fake_sec1607,
            dry_run=True,
        )
        assert rep["status"] == "dry_run"
        assert rep["sec1606_updated"] is True
        assert rep["sec1606_offset"] == hex(sec1606_off)
        assert rep["sec1607_offset"] == hex(sec1607_off)

        # Savestate should not have been modified in dry_run
        assert sav_file.read_bytes() == full_sav

        # 2. Live run
        rep2 = sync_single_savestate(
            sav_file,
            sec1606_disc=fake_sec1606,
            sec1607_disc=fake_sec1607,
            dry_run=False,
            backup=True,
        )
        assert rep2["status"] == "updated"
        assert rep2["sec1606_updated"] is True
        assert (tmp / "SLPS-01363_1.sav.bak").is_file()

        # Check modified payload in .sav
        new_data = sav_file.read_bytes()
        magics = find_zstd_magic_offsets(new_data)
        decomp = decompress_zstd(new_data[magics[1]:])
        assert decomp[sec1606_off : sec1606_off + 2048] == fake_sec1606
        assert decomp[sec1607_off : sec1607_off + 2048] == fake_sec1607
