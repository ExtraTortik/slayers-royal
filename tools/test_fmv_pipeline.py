#!/usr/bin/env python3
"""Unit tests for the PS1 FMV pipeline, toolchain setup, and movie stream sector map.

Validates:
1. psxavenc executable availability and responsiveness.
2. MOVIE_MAP exact sector bounds, continuity, and total sector sum (184,290 sectors).
3. MovieInfo calculation (LBA, byte offsets, subbed flags).
4. Availability of clean webm video sources (s00..s11) and Russian subtitles (s01_ru..s11_ru).
5. Alignment with downloads/sr.bin original disc image if present.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tools.fmv_pipeline import (
    BIN_DIR,
    MOVIE_MAP,
    MOVIE_STR_LBA,
    MOVIE_STR_TOTAL_SECTORS,
    PSXAVENC_PATH,
    REPO_ROOT,
    SECTOR_RAW_SIZE,
    VIDEOS_DIR,
    check_psxavenc,
    get_movie_info,
    get_psxavenc_path,
    get_video_assets,
    verify_movie_map,
)


class TestPsxavencToolchain:
    """Validate psxavenc compiler output and binary capabilities."""

    def test_binary_exists_and_executable(self):
        assert PSXAVENC_PATH.is_file(), f"psxavenc binary missing at {PSXAVENC_PATH}"
        assert os.access(PSXAVENC_PATH, os.X_OK), f"psxavenc at {PSXAVENC_PATH} not executable"

    def test_version_output(self):
        version_str = check_psxavenc()
        assert "psxavenc" in version_str.lower(), f"Unexpected version banner: {version_str}"

    def test_help_strcd_format_available(self):
        bin_path = get_psxavenc_path()
        res = subprocess.run(
            [str(bin_path), "-t", "strcd", "-h"],
            capture_output=True,
            text=True,
        )
        combined = res.stdout + res.stderr
        assert "strcd" in combined, "psxavenc does not report strcd support"
        assert "2352-byte sectors" in combined, "psxavenc strcd format missing 2352-byte sector support"


class TestMovieStreamMapping:
    """Validate MOVIE_MAP sector layout and bounds."""

    def test_movie_count(self):
        assert len(MOVIE_MAP) == 12, f"Expected 12 movies, got {len(MOVIE_MAP)}"
        for i in range(12):
            assert i in MOVIE_MAP, f"Missing movie index {i}"
            assert MOVIE_MAP[i]["name"] == f"s{i:02d}"

    def test_subbed_flags(self):
        assert MOVIE_MAP[0]["subbed"] is False, "Movie 0 (Opening) should not be subbed"
        for i in range(1, 12):
            assert MOVIE_MAP[i]["subbed"] is True, f"Movie {i} should be flagged as subbed"

    def test_sector_continuity_and_sum(self):
        assert verify_movie_map() is True
        total = sum(entry["sectors"] for entry in MOVIE_MAP.values())
        assert total == MOVIE_STR_TOTAL_SECTORS
        assert total == 184290

    def test_relative_sector_offsets(self):
        expected_offsets = {
            0: 0,
            1: 13501,
            2: 26301,
            3: 49700,
            4: 60008,
            5: 72392,
            6: 91962,
            7: 101754,
            8: 111674,
            9: 123551,
            10: 150353,
            11: 153809,
        }
        for idx, expected_rel in expected_offsets.items():
            assert MOVIE_MAP[idx]["rel_sec"] == expected_rel

    def test_movie_info_helper(self):
        info0 = get_movie_info(0)
        assert info0.index == 0
        assert info0.name == "s00"
        assert info0.start_lba == MOVIE_STR_LBA  # 127
        assert info0.sectors == 13501
        assert info0.end_lba == 127 + 13501
        assert info0.raw_offset == 127 * SECTOR_RAW_SIZE
        assert info0.raw_size_bytes == 13501 * SECTOR_RAW_SIZE
        assert info0.subbed is False

        info11 = get_movie_info(11)
        assert info11.index == 11
        assert info11.name == "s11"
        assert info11.start_lba == 127 + 153809
        assert info11.end_lba == 127 + 184290
        assert info11.sectors == 30481
        assert info11.subbed is True

    def test_movie_info_out_of_bounds(self):
        with pytest.raises(KeyError):
            get_movie_info(12)
        with pytest.raises(KeyError):
            get_movie_info(-1)


class TestSourceAssetsAvailability:
    """Validate source webm videos and Russian subtitles exist in the repository."""

    @pytest.mark.parametrize("idx", range(12))
    def test_video_assets_exist(self, idx: int):
        webm, srt = get_video_assets(idx)
        assert webm.is_file(), f"Video missing: {webm}"
        assert webm.stat().st_size > 10000, f"Video file abnormally small: {webm}"

        if idx == 0:
            assert srt is None
        else:
            assert srt is not None
            assert srt.is_file(), f"Subtitle missing: {srt}"
            assert srt.stat().st_size > 10, f"Subtitle file empty: {srt}"


class TestDiscImageAlignment:
    """Validate MOVIE_MAP matches real sectors in downloads/sr.bin if available."""

    @pytest.fixture
    def disc_bin(self):
        path = REPO_ROOT / "downloads" / "sr.bin"
        if not path.is_file():
            pytest.skip(f"Disc image {path} not available for alignment test")
        return path

    def test_all_movie_stream_headers_in_disc(self, disc_bin: Path):
        with open(disc_bin, "rb") as f:
            for idx in range(12):
                info = get_movie_info(idx)
                f.seek(info.raw_offset)
                sector = f.read(SECTOR_RAW_SIZE)
                assert len(sector) == SECTOR_RAW_SIZE

                # Sync bytes: 00 FF ... FF 00
                assert sector[:12] == b"\x00" + b"\xff" * 10 + b"\x00"
                # Submode byte at offset 18: should be 0x48 (CD-XA Audio/Video stream)
                submode = sector[18]
                assert submode == 0x48, f"Movie {idx} LBA {info.start_lba}: expected submode 0x48, got {hex(submode)}"

                # Payload starts at offset 24: STR header
                # 60 01 01 80 -> magic / type
                # 00 00 -> chunk 0
                # xx 00 -> chunk count
                # 01 00 -> frame 1
                payload = sector[24:40]
                assert payload[:4] == b"\x60\x01\x01\x80", f"Movie {idx} missing STR header magic: {payload[:4].hex()}"
                chunk_idx = int.from_bytes(payload[4:6], "little")
                frame_idx = int.from_bytes(payload[8:10], "little")
                assert chunk_idx == 0, f"Movie {idx} did not start at chunk 0 (got {chunk_idx})"
                assert frame_idx == 1, f"Movie {idx} did not start at frame 1 (got {frame_idx})"
