#!/usr/bin/env python3
"""Unit tests for the PS1 FMV pipeline, toolchain setup, and movie stream sector map.

Validates:
1. psxavenc executable availability and responsiveness.
2. MOVIE_MAP exact sector bounds, continuity, and total sector sum (184,290 sectors).
3. MovieInfo calculation (LBA, byte offsets, subbed flags).
4. Availability of clean webm video sources (s00..s11) and Russian subtitles (s01_ru..s11_ru).
5. Alignment with downloads/sr.bin original disc image if present.
6. Sector padding and boundary enforcement via pad_str_to_sectors.
7. Subtitle burning via FFmpeg with custom styling and raw AVI formatting.
8. PlayStation 1 STR encoding via psxavenc and sector format verification.
9. End-to-end movie encoding and disc extraction via encode_movie.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

from tools.fmv_pipeline import (
    BIN_DIR,
    MOVIE_MAP,
    MOVIE_STR_LBA,
    MOVIE_STR_TOTAL_SECTORS,
    PSXAVENC_PATH,
    SECTOR_RAW_SIZE,
    VIDEOS_DIR,
    batch_encode_all_movies,
    burn_subtitles_to_avi,
    check_psxavenc,
    concat_movies_to_str,
    encode_avi_to_str,
    encode_movie,
    get_movie_info,
    get_psxavenc_path,
    get_video_assets,
    inject_movie_str_into_disc,
    make_padding_sector,
    pad_str_to_sectors,
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


class TestPadStrToSectors:
    """Validate CD-XA Mode 2 Form 1 sector padding and bounds enforcement."""

    def test_make_padding_sector_format(self):
        sec = make_padding_sector(0)
        assert len(sec) == SECTOR_RAW_SIZE
        # Sync bytes
        assert sec[:12] == b"\x00" + b"\xff" * 10 + b"\x00"
        # CD-XA Mode 2 byte
        assert sec[15] == 2
        # Subheader: 8 zero bytes
        assert sec[16:24] == b"\x00" * 8
        # Payload: all zeros
        assert sec[24:] == b"\x00" * (SECTOR_RAW_SIZE - 24)

    @pytest.mark.parametrize("target_sectors", [0, 1, 5, 128, 12800])
    def test_padding_exact_length(self, target_sectors: int):
        padded = pad_str_to_sectors(b"", target_sectors)
        assert len(padded) == target_sectors * SECTOR_RAW_SIZE

    def test_padding_preserves_exact_size(self):
        exact_bytes = b"\xaa" * (3 * SECTOR_RAW_SIZE)
        result = pad_str_to_sectors(exact_bytes, 3)
        assert result == exact_bytes

    def test_truncation_when_exceeding_target(self):
        excess_bytes = b"\xbb" * (5 * SECTOR_RAW_SIZE)
        result = pad_str_to_sectors(excess_bytes, 2)
        assert len(result) == 2 * SECTOR_RAW_SIZE
        assert result == excess_bytes[: 2 * SECTOR_RAW_SIZE]

    def test_unaligned_input_padding(self):
        partial_data = b"PAYLOAD" * 50  # 350 bytes
        result = pad_str_to_sectors(partial_data, 2)
        assert len(result) == 2 * SECTOR_RAW_SIZE
        assert result[: len(partial_data)] == partial_data
        # Remainder of first sector should be zero-padded
        assert result[len(partial_data) : SECTOR_RAW_SIZE] == b"\x00" * (SECTOR_RAW_SIZE - len(partial_data))
        # Second sector should be a valid padding sector
        sec2 = result[SECTOR_RAW_SIZE:]
        assert sec2[:12] == b"\x00" + b"\xff" * 10 + b"\x00"
        assert sec2[16:24] == b"\x00" * 8

    def test_negative_target_sectors_raises(self):
        with pytest.raises(ValueError):
            pad_str_to_sectors(b"", -1)


class TestSubtitleBurning:
    """Validate subtitle burning with FFmpeg into raw uncompressed AVI."""

    def test_burn_subtitles_to_avi_output_spec(self, tmp_path: Path):
        webm_file = VIDEOS_DIR / "s01.webm"
        srt_file = VIDEOS_DIR / "s01_ru.srt"
        out_avi = tmp_path / "burned_test.avi"

        burn_subtitles_to_avi(webm_file, srt_file, out_avi, duration=0.2)
        assert out_avi.is_file()
        assert out_avi.stat().st_size > 50000

        # Probe video stream: 320x240, 15fps
        res_v = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate",
                "-of",
                "csv=p=0",
                str(out_avi),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert res_v.stdout.strip() == "320,240,15/1"

        # Probe audio stream: 18900 Hz, mono (1 channel)
        res_a = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate,channels",
                "-of",
                "csv=p=0",
                str(out_avi),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert res_a.stdout.strip() == "18900,1"

    def test_burn_without_subtitles(self, tmp_path: Path):
        webm_file = VIDEOS_DIR / "s00.webm"
        out_avi = tmp_path / "nosub_test.avi"
        burn_subtitles_to_avi(webm_file, None, out_avi, duration=0.2)
        assert out_avi.is_file()
        assert out_avi.stat().st_size > 50000

    def test_burn_missing_input_video_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            burn_subtitles_to_avi(tmp_path / "missing.webm", None, tmp_path / "out.avi")

    def test_burn_missing_srt_raises(self, tmp_path: Path):
        webm_file = VIDEOS_DIR / "s01.webm"
        with pytest.raises(FileNotFoundError):
            burn_subtitles_to_avi(webm_file, tmp_path / "missing.srt", tmp_path / "out.avi")


class TestEncodeAviToStrAndStreamValidation:
    """Validate encoding uncompressed AVI to PS1 STR and CD-XA sector layout."""

    def test_encode_and_validate_mdec_and_xa_sectors(self, tmp_path: Path):
        webm_file = VIDEOS_DIR / "s10.webm"
        srt_file = VIDEOS_DIR / "s10_ru.srt"
        avi_file = tmp_path / "s10.avi"
        str_file = tmp_path / "s10.str"

        burn_subtitles_to_avi(webm_file, srt_file, avi_file, duration=0.5)
        encode_avi_to_str(avi_file, str_file)

        assert str_file.is_file()
        data = str_file.read_bytes()
        assert len(data) > 0
        assert len(data) % SECTOR_RAW_SIZE == 0
        total_sectors = len(data) // SECTOR_RAW_SIZE
        assert total_sectors >= 5

        # Inspect all sectors
        video_sectors = []
        audio_sectors = []
        for i in range(total_sectors):
            sec = data[i * SECTOR_RAW_SIZE : (i + 1) * SECTOR_RAW_SIZE]
            # Verify CD-ROM Sync pattern: 00 FF ... FF 00
            assert sec[:12] == b"\x00" + b"\xff" * 10 + b"\x00", f"Sector {i} missing sync"
            # Verify Mode 2 indicator
            assert sec[15] == 2

            submode = sec[18]
            if submode == 0x48:  # Video
                video_sectors.append((i, sec))
            elif submode == 0x64:  # Audio XA-ADPCM
                audio_sectors.append((i, sec))

        # Both video and audio sectors must be present
        assert len(video_sectors) > 0, "No video sectors found in STR output"
        assert len(audio_sectors) > 0, "No audio sectors found in STR output"

        # Verify MDEC STR payload header on first video sector
        _, first_video = video_sectors[0]
        # Payload begins at offset 24: magic 60 01 01 80 (type 0x8001)
        mdec_magic = first_video[24:28]
        assert mdec_magic == b"\x60\x01\x01\x80", f"Invalid MDEC magic: {mdec_magic.hex()}"

        # Verify CD-XA audio subheader and coding info
        _, first_audio = audio_sectors[0]
        # Subheader repeats at 16..20 and 20..24
        assert first_audio[16:20] == first_audio[20:24]
        # File 1, Channel 1, Submode 0x64, Coding 0x04 (4-bit mono 18900Hz)
        assert first_audio[16] == 1  # File
        assert first_audio[17] == 1  # Channel
        assert first_audio[18] == 0x64  # Audio submode
        assert first_audio[19] == 0x04  # Coding info (mono 4-bit)

    def test_encode_missing_avi_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            encode_avi_to_str(tmp_path / "missing.avi", tmp_path / "out.str")


class TestEncodeMoviePipeline:
    """Validate full end-to-end movie encoding and disc extraction."""

    def test_encode_movie_0_extract_from_disc(self, tmp_path: Path):
        disc_bin = REPO_ROOT / "downloads" / "sr.bin"
        if not disc_bin.is_file():
            pytest.skip(f"Disc image {disc_bin} not available")

        out_str = tmp_path / "s00.str"
        bytes_written = encode_movie(0, VIDEOS_DIR, out_str)
        info = get_movie_info(0)
        assert bytes_written == info.raw_size_bytes
        assert out_str.stat().st_size == info.raw_size_bytes
        assert bytes_written == 13501 * SECTOR_RAW_SIZE

        # Validate extracted movie starts with valid STR sector
        with open(out_str, "rb") as f:
            sec0 = f.read(SECTOR_RAW_SIZE)
            assert sec0[:12] == b"\x00" + b"\xff" * 10 + b"\x00"
            assert sec0[18] == 0x48
            assert sec0[24:28] == b"\x60\x01\x01\x80"

    def test_encode_movie_with_subtitles_and_padding(self, tmp_path: Path):
        # Movie 10 (s10) has 3,456 sectors (smallest movie: ~8 MB)
        out_str = tmp_path / "s10_padded.str"
        info = get_movie_info(10)
        bytes_written = encode_movie(10, VIDEOS_DIR, out_str, duration=0.5)

        assert bytes_written == info.raw_size_bytes
        assert out_str.stat().st_size == info.raw_size_bytes
        assert bytes_written == 3456 * SECTOR_RAW_SIZE

        data = out_str.read_bytes()
        # Initial sector should be valid encoded stream sector
        sec0 = data[:SECTOR_RAW_SIZE]
        assert sec0[:12] == b"\x00" + b"\xff" * 10 + b"\x00"
        assert sec0[18] in (0x48, 0x64)

        # Final sector must be a valid zero-padding CD-XA sector
        last_sec = data[-SECTOR_RAW_SIZE:]
        assert last_sec[:12] == b"\x00" + b"\xff" * 10 + b"\x00"
        assert last_sec[15] == 2
        assert last_sec[16:24] == b"\x00" * 8
        assert last_sec[24:] == b"\x00" * (SECTOR_RAW_SIZE - 24)

    def test_encode_movie_invalid_index_raises(self, tmp_path: Path):
        with pytest.raises(KeyError):
            encode_movie(99, VIDEOS_DIR, tmp_path / "out.str")

    def test_encode_movie_missing_video_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            encode_movie(1, tmp_path / "empty_videos", tmp_path / "out.str")


class TestConcatMoviesToStr:
    """Validate concatenating individual movie STR streams into MOVIE.STR."""

    def test_concat_movies_missing_file_raises(self, tmp_path: Path):
        missing = tmp_path / "missing.str"
        with pytest.raises(FileNotFoundError):
            concat_movies_to_str([missing], tmp_path / "out.str")

    def test_concat_movies_size_mismatch_raises(self, tmp_path: Path):
        dummy = tmp_path / "dummy.str"
        dummy.write_bytes(b"\x00" * 2352)
        with pytest.raises(ValueError):
            concat_movies_to_str([dummy], tmp_path / "out.str")


class TestBatchEncodeAllMovies:
    """Validate batch encoding orchestrator."""

    def test_batch_encode_missing_videos_dir_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            batch_encode_all_movies(videos_dir=tmp_path / "nonexistent", out_dir=tmp_path / "out")


class TestInjectMovieStrIntoDisc:
    """Validate injecting MOVIE.STR into target disc image."""

    def test_inject_disc_not_found_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            inject_movie_str_into_disc(tmp_path / "missing.bin", tmp_path)

    def test_inject_disc_invalid_size_raises(self, tmp_path: Path):
        bad_disc = tmp_path / "bad.bin"
        bad_disc.write_bytes(b"\x00" * 1000)
        with pytest.raises(ValueError, match="Invalid target disc size"):
            inject_movie_str_into_disc(bad_disc, tmp_path)

    def test_inject_disc_from_movies_directory(self, tmp_path: Path):
        # Create mock 712,300,848-byte disc image
        mock_disc = tmp_path / "disc.bin"
        with open(mock_disc, "wb") as f:
            f.truncate(712_300_848)

        # Create 12 mock movie files with correct sync & MDEC header
        movies_dir = tmp_path / "movies"
        movies_dir.mkdir()
        for idx in range(12):
            info = get_movie_info(idx)
            movie_file = movies_dir / f"{info.name}.str"
            # First sector needs sync and MDEC magic
            first_sec = bytearray(b"\x00" * SECTOR_RAW_SIZE)
            first_sec[:12] = b"\x00" + b"\xff" * 10 + b"\x00"
            first_sec[15] = 2
            first_sec[18] = 0x48
            first_sec[24:28] = b"\x60\x01\x01\x80"
            with open(movie_file, "wb") as f:
                f.write(first_sec)
                if info.raw_size_bytes > SECTOR_RAW_SIZE:
                    f.truncate(info.raw_size_bytes)

        bytes_injected = inject_movie_str_into_disc(mock_disc, movies_dir)
        assert bytes_injected == MOVIE_STR_TOTAL_SECTORS * SECTOR_RAW_SIZE
        assert mock_disc.stat().st_size == 712_300_848

        # Verify injected sectors at movie boundaries
        with open(mock_disc, "rb") as f:
            for idx in range(12):
                info = get_movie_info(idx)
                f.seek(info.raw_offset)
                sec = f.read(SECTOR_RAW_SIZE)
                assert sec[:12] == b"\x00" + b"\xff" * 10 + b"\x00"
                assert sec[24:28] == b"\x60\x01\x01\x80"

    def test_inject_disc_from_single_movie_str(self, tmp_path: Path):
        mock_disc = tmp_path / "disc.bin"
        with open(mock_disc, "wb") as f:
            f.truncate(712_300_848)

        # Create mock MOVIE.STR of exact size
        movie_str_file = tmp_path / "MOVIE.STR"
        with open(movie_str_file, "wb") as f:
            f.truncate(MOVIE_STR_TOTAL_SECTORS * SECTOR_RAW_SIZE)
            # Stamp first sector of each movie
            for idx in range(12):
                info = get_movie_info(idx)
                sec = bytearray(b"\x00" * SECTOR_RAW_SIZE)
                sec[:12] = b"\x00" + b"\xff" * 10 + b"\x00"
                sec[15] = 2
                sec[18] = 0x48
                sec[24:28] = b"\x60\x01\x01\x80"
                f.seek(info.rel_sec * SECTOR_RAW_SIZE)
                f.write(sec)

        bytes_injected = inject_movie_str_into_disc(mock_disc, movie_str_file)
        assert bytes_injected == MOVIE_STR_TOTAL_SECTORS * SECTOR_RAW_SIZE
        assert mock_disc.stat().st_size == 712_300_848
