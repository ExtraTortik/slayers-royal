#!/usr/bin/env python3
"""Video asset pipeline and movie stream mapping for Slayers Royal PS1.

Handles:
1. Exact sector layout of the 12 FMV cutscenes in MOVIE.STR (LBA 127, 184,290 sectors).
2. PS1 STR video encoding toolchain interface via psxavenc.
3. Verification of video sector bounds, continuity, and source assets.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Repository paths
REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
BIN_DIR = TOOLS_DIR / "bin"
PSXAVENC_PATH = BIN_DIR / "psxavenc"
VIDEOS_DIR = REPO_ROOT / "renpy_extracted" / "game" / "videos"

PATCH_REPO = REPO_ROOT / "patch_repo"
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))

try:
    from localization.disc import CdChecksums
except ImportError:
    class CdChecksums:  # type: ignore[no-redef]
        """EDC/ECC generator for PlayStation Mode 2 Form 1 sectors."""

        def __init__(self) -> None:
            self.ecc_f = [0] * 256
            self.ecc_b = [0] * 256
            self.edc = [0] * 256
            for value in range(256):
                forward = ((value << 1) ^ (0x11D if value & 0x80 else 0)) & 0xFF
                self.ecc_f[value] = forward
                self.ecc_b[value ^ forward] = value
                crc = value
                for _ in range(8):
                    crc = (crc >> 1) ^ (0xD8018001 if crc & 1 else 0)
                self.edc[value] = crc

        def compute_edc(self, data: bytes) -> bytes:
            crc = 0
            for value in data:
                crc = (crc >> 8) ^ self.edc[(crc ^ value) & 0xFF]
            return crc.to_bytes(4, "little")

        def compute_ecc(
            self,
            source: bytes,
            major_count: int,
            minor_count: int,
            major_mult: int,
            minor_inc: int,
        ) -> bytes:
            address = b"\0\0\0\0"
            length = major_count * minor_count
            output = bytearray(major_count * 2)
            for major in range(major_count):
                index = (major >> 1) * major_mult + (major & 1)
                ecc_a = 0
                ecc_b = 0
                for _ in range(minor_count):
                    value = address[index] if index < 4 else source[index - 4]
                    index = (index + minor_inc) % length
                    ecc_a ^= value
                    ecc_b ^= value
                    ecc_a = self.ecc_f[ecc_a]
                ecc_a = self.ecc_b[self.ecc_f[ecc_a] ^ ecc_b]
                output[major] = ecc_a
                output[major + major_count] = ecc_a ^ ecc_b
            return bytes(output)

        def repair_mode2_form1(self, sector: bytearray) -> None:
            if len(sector) != SECTOR_RAW_SIZE or sector[15] != 2 or sector[18] & 0x20:
                raise ValueError("target sector is not MODE2/2352 Form 1")
            sector[0x818:0x81C] = self.compute_edc(sector[0x10:0x818])
            sector[0x81C:0x8C8] = self.compute_ecc(sector[0x10:], 86, 24, 2, 86)
            sector[0x8C8:0x930] = self.compute_ecc(sector[0x10:], 52, 43, 86, 88)
# PS1 CD-ROM and MOVIE.STR constants
MOVIE_STR_LBA = 127
MOVIE_STR_TOTAL_SECTORS = 184290
SECTOR_RAW_SIZE = 2352
SECTOR_USER_SIZE = 2048

# Exact movie stream sector layout in MOVIE.STR (12 movies)
MOVIE_MAP: dict[int, dict[str, Any]] = {
    0:  {"name": "s00", "rel_sec": 0,      "sectors": 13501, "subbed": False},  # Opening
    1:  {"name": "s02", "rel_sec": 13501,  "sectors": 12800, "subbed": True},   # Lark story
    2:  {"name": "s03", "rel_sec": 26301,  "sectors": 23399, "subbed": True},   # Road fork
    3:  {"name": "s04", "rel_sec": 49700,  "sectors": 10308, "subbed": True},   # Book found
    4:  {"name": "s05", "rel_sec": 60008,  "sectors": 12384, "subbed": True},   # Ruins entry
    5:  {"name": "s06", "rel_sec": 72392,  "sectors": 19570, "subbed": True},   # Library
    6:  {"name": "s07", "rel_sec": 91962,  "sectors": 9792,  "subbed": True},   # Necklace
    7:  {"name": "s08", "rel_sec": 101754, "sectors": 9920,  "subbed": True},   # Too late
    8:  {"name": "s09", "rel_sec": 111674, "sectors": 11877, "subbed": True},   # Fireball
    9:  {"name": "s10", "rel_sec": 123551, "sectors": 26802, "subbed": True},   # Treasures
    10: {"name": "s11", "rel_sec": 150353, "sectors": 3456,  "subbed": True},   # Ending
    11: {"name": "s01", "rel_sec": 153809, "sectors": 30481, "subbed": True},   # Lakewood exit
}


@dataclass(frozen=True)
class MovieInfo:
    """Metadata and sector boundaries for a single FMV cutscene."""
    index: int
    name: str
    rel_sec: int
    sectors: int
    subbed: bool
    start_lba: int
    end_lba: int
    raw_offset: int
    raw_size_bytes: int


def get_movie_info(idx: int) -> MovieInfo:
    """Return MovieInfo with absolute LBA and byte offsets for a movie index (0..11)."""
    if idx not in MOVIE_MAP:
        raise KeyError(f"Invalid movie index: {idx}. Must be between 0 and 11.")
    entry = MOVIE_MAP[idx]
    rel_sec = entry["rel_sec"]
    sectors = entry["sectors"]
    start_lba = MOVIE_STR_LBA + rel_sec
    end_lba = start_lba + sectors
    raw_offset = start_lba * SECTOR_RAW_SIZE
    raw_size_bytes = sectors * SECTOR_RAW_SIZE
    return MovieInfo(
        index=idx,
        name=entry["name"],
        rel_sec=rel_sec,
        sectors=sectors,
        subbed=entry["subbed"],
        start_lba=start_lba,
        end_lba=end_lba,
        raw_offset=raw_offset,
        raw_size_bytes=raw_size_bytes,
    )


def verify_movie_map() -> bool:
    """Validate MOVIE_MAP sector continuity, bounds, and total sector sum.

    Raises:
        ValueError: If any continuity gap, overlap, or sum mismatch is found.

    Returns:
        True if the map is completely valid.
    """
    if len(MOVIE_MAP) != 12:
        raise ValueError(f"Expected 12 movie entries, found {len(MOVIE_MAP)}")

    expected_rel_sec = 0
    total_sectors = 0

    for idx in range(12):
        if idx not in MOVIE_MAP:
            raise ValueError(f"Missing movie index: {idx}")
        entry = MOVIE_MAP[idx]
        rel_sec = entry["rel_sec"]
        sectors = entry["sectors"]

        if rel_sec != expected_rel_sec:
            raise ValueError(
                f"Movie {idx} ({entry['name']}): expected rel_sec={expected_rel_sec}, "
                f"got rel_sec={rel_sec} (gap or overlap detected)"
            )
        if sectors <= 0:
            raise ValueError(f"Movie {idx} has invalid sector count: {sectors}")

        expected_rel_sec += sectors
        total_sectors += sectors

    if total_sectors != MOVIE_STR_TOTAL_SECTORS:
        raise ValueError(
            f"Total sectors mismatch: sum={total_sectors}, expected={MOVIE_STR_TOTAL_SECTORS}"
        )

    return True


def get_psxavenc_path() -> Path:
    """Return verified path to psxavenc executable."""
    if not PSXAVENC_PATH.is_file():
        raise FileNotFoundError(
            f"psxavenc binary not found at {PSXAVENC_PATH}. "
            "Build and install it from psxavenc repository."
        )
    if not os.access(PSXAVENC_PATH, os.X_OK):
        raise PermissionError(f"psxavenc at {PSXAVENC_PATH} is not executable.")
    return PSXAVENC_PATH


def check_psxavenc() -> str:
    """Execute psxavenc and return version/usage banner."""
    bin_path = get_psxavenc_path()
    res = subprocess.run(
        [str(bin_path), "-V"],
        capture_output=True,
        text=True,
    )
    # psxavenc outputs version info on stderr with code 1
    output = (res.stdout + "\n" + res.stderr).strip()
    return output


def get_video_assets(idx: int) -> tuple[Path, Path | None]:
    """Return paths to source webm video and Russian srt subtitle (if subbed)."""
    info = get_movie_info(idx)
    webm_file = VIDEOS_DIR / f"{info.name}.webm"
    if not webm_file.is_file():
        raise FileNotFoundError(f"Source video missing: {webm_file}")

    srt_file: Path | None = None
    if info.subbed:
        srt_file = VIDEOS_DIR / f"{info.name}_ru.srt"
        if not srt_file.is_file():
            raise FileNotFoundError(f"Russian subtitle missing: {srt_file}")

    return webm_file, srt_file


def extract_movie_from_bin(bin_path: Path, movie_idx: int, out_path: Path) -> int:
    """Extract raw movie sectors from a CD-ROM BIN image to a standalone STR file.

    Returns the number of bytes written.
    """
    info = get_movie_info(movie_idx)
    with open(bin_path, "rb") as f_in:
        f_in.seek(info.raw_offset)
        data = f_in.read(info.raw_size_bytes)
        if len(data) != info.raw_size_bytes:
            raise IOError(
                f"Unexpected EOF reading movie {movie_idx}: read {len(data)} of {info.raw_size_bytes} bytes"
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f_out:
        f_out.write(data)

    return len(data)

def lba_to_msf(lba: int) -> bytes:
    """Convert a CD-ROM LBA address to 3-byte physical BCD MSF (Minute, Second, Frame).

    Applies the standard 150-sector (+2 seconds) CD-ROM pregap offset.
    Returns 3 bytes: (BCD_M, BCD_S, BCD_F).
    """
    total_frames = lba + 150
    m = (total_frames // 75) // 60
    s = (total_frames // 75) % 60
    f = total_frames % 75
    return bytes([
        ((m // 10) << 4) | (m % 10),
        ((s // 10) << 4) | (s % 10),
        ((f // 10) << 4) | (f % 10),
    ])


def make_padding_sector(sector_lba: int = 0) -> bytes:
    """Generate a single 2,352-byte CD-XA Mode 2 Form 1 zero-padding sector."""
    sync = b"\x00" + b"\xff" * 10 + b"\x00"
    header = lba_to_msf(sector_lba) + b"\x02"
    subheader = b"\x00" * 8
    payload = b"\x00" * (SECTOR_RAW_SIZE - 24)
    sector = bytearray(sync + header + subheader + payload)
    checksums = CdChecksums()
    checksums.repair_mode2_form1(sector)
    return bytes(sector)


def pad_str_to_sectors(str_bytes: bytes, target_sectors: int, start_lba: int = 0) -> bytes:
    """Enforce exact sector count on an STR stream matching target_sectors * 2352 bytes.

    - If str_bytes is shorter than target_sectors * 2352, appends valid CD-XA zero-padding
      sectors (subheader 0x00 * 8) with accurate physical BCD MSF headers and Mode 2 Form 1 EDC/ECC.
    - If str_bytes is longer, truncates trailing bytes to target_sectors * 2352.
    """
    if target_sectors < 0:
        raise ValueError(f"target_sectors must be non-negative, got {target_sectors}")

    target_bytes = target_sectors * SECTOR_RAW_SIZE
    if len(str_bytes) == target_bytes:
        return str_bytes

    if len(str_bytes) > target_bytes:
        return str_bytes[:target_bytes]

    result = bytearray(str_bytes)
    # If unaligned, pad remainder of partial sector with zeros
    rem = len(result) % SECTOR_RAW_SIZE
    if rem != 0:
        needed = min(SECTOR_RAW_SIZE - rem, target_bytes - len(result))
        result.extend(b"\x00" * needed)
        completed_sec_start = len(result) - SECTOR_RAW_SIZE
        sec_slice = result[completed_sec_start:]
        if len(sec_slice) == SECTOR_RAW_SIZE and sec_slice[15] == 2 and not (sec_slice[18] & 0x20):
            sector_ba = bytearray(sec_slice)
            checksums = CdChecksums()
            checksums.repair_mode2_form1(sector_ba)
            result[completed_sec_start:] = sector_ba

    current_sec_count = len(result) // SECTOR_RAW_SIZE
    remaining_secs = target_sectors - current_sec_count

    if remaining_secs > 0:
        padding_chunks = []
        for i in range(remaining_secs):
            sec_lba = start_lba + current_sec_count + i
            padding_chunks.append(make_padding_sector(sec_lba))
        result.extend(b"".join(padding_chunks))

    return bytes(result[:target_bytes])


def burn_subtitles_to_avi(
    webm_path: Path | str,
    srt_path: Path | str | None,
    out_avi_path: Path | str,
    duration: float | int | None = None,
) -> Path:
    """Burn Russian subtitles into a 320x240 15fps uncompressed AVI video using FFmpeg.

    Video filter: scale=320:240,subtitles={srt_path}:force_style=...
    Audio: 18900 Hz, mono (ac 1), pcm_s16le
    Output: raw uncompressed AVI (yuv420p + pcm_s16le)
    """
    webm_path = Path(webm_path)
    if not webm_path.is_file():
        raise FileNotFoundError(f"Source video file not found: {webm_path}")

    out_avi_path = Path(out_avi_path)
    out_avi_path.parent.mkdir(parents=True, exist_ok=True)

    if srt_path is not None:
        srt_p = Path(srt_path).resolve()
        if not srt_p.is_file():
            raise FileNotFoundError(f"Subtitle file not found: {srt_p}")
        # In ffmpeg filter syntax, escape colons and backslashes in the subtitle path
        escaped_srt = str(srt_p).replace("\\", "/").replace(":", "\\:")
        vf = (
            f"scale=320:240,"
            f"subtitles='{escaped_srt}':force_style="
            f"'FontName=Liberation Sans,FontSize=15,Outline=1.8,"
            f"OutlineColor=&H00000000,PrimaryColour=&H00FFFFFF,MarginV=12'"
        )
    else:
        vf = "scale=320:240"

    cmd = ["ffmpeg", "-y"]
    if duration is not None:
        cmd.extend(["-t", str(duration)])
    cmd.extend([
        "-i", str(webm_path),
        "-vf", vf,
        "-r", "15",
        "-c:v", "rawvideo",
        "-pix_fmt", "yuv420p",
        "-ar", "18900",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(out_avi_path),
    ])

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"FFmpeg subtitle burning failed (code {res.returncode}):\n{res.stderr}"
        )

    return out_avi_path


def encode_avi_to_str(
    avi_path: Path | str,
    out_str_path: Path | str,
    start_lba: int | None = None,
) -> Path:
    """Encode an uncompressed AVI into a PlayStation 1 MDEC STR CD-XA stream via psxavenc.

    Uses:
        psxavenc -t strcd -f 18900 -c 1 -F 1 -C 1 -r 15 -x 2 -T 0x8001 [-L {start_lba}] -X {avi_path} {out_str_path}
    Produces 2,352-byte CD-XA Mode 2 Form 1 interleaved audio/video sectors (1/32 audio interleave).
    """
    avi_path = Path(avi_path)
    if not avi_path.is_file():
        raise FileNotFoundError(f"Input AVI file not found: {avi_path}")

    out_str_path = Path(out_str_path)
    out_str_path.parent.mkdir(parents=True, exist_ok=True)

    psxavenc = get_psxavenc_path()
    cmd = [
        str(psxavenc),
        "-t", "strcd",
        "-f", "18900",
        "-c", "1",
        "-F", "1",
        "-C", "1",
        "-r", "15",
        "-x", "2",
        "-T", "0x8001",
    ]
    if start_lba is not None:
        cmd.extend(["-L", str(start_lba)])
    cmd.append("-X")
    cmd.extend([
        str(avi_path),
        str(out_str_path),
    ])

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"psxavenc encoding failed (code {res.returncode}):\n{res.stderr or res.stdout}"
        )

    return out_str_path


def encode_movie(
    movie_idx: int,
    videos_dir: Path | str,
    out_str_path: Path | str,
    source_bin_path: Path | str | None = None,
    duration: float | int | None = None,
) -> int:
    """Encode or extract a single movie stream for MOVIE.STR.

    - Movie 0 (s00, unsubbed opening): extracted directly from the original CD-ROM BIN image.
    - Movies 1..11 (s01..s11, Russian subtitled cutscenes): burns subtitles with FFmpeg,
      encodes to PS1 STR with psxavenc, and pads to exact MOVIE_MAP sector count.

    Returns the number of bytes written to out_str_path.
    """
    info = get_movie_info(movie_idx)
    out_path = Path(out_str_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if movie_idx == 0:
        bin_path = (
            Path(source_bin_path)
            if source_bin_path is not None
            else (REPO_ROOT / "downloads" / "sr.bin")
        )
        if not bin_path.is_file():
            raise FileNotFoundError(
                f"Source CD-ROM disc image not found at {bin_path} to extract movie 0 ({info.name})"
            )
        return extract_movie_from_bin(bin_path, movie_idx, out_path)

    v_dir = Path(videos_dir)
    webm_file = v_dir / f"{info.name}.webm"
    if not webm_file.is_file():
        raise FileNotFoundError(f"Source video missing: {webm_file}")

    srt_file: Path | None = None
    if info.subbed:
        srt_file = v_dir / f"{info.name}_ru.srt"
        if not srt_file.is_file():
            raise FileNotFoundError(f"Russian subtitle missing: {srt_file}")

    with tempfile.TemporaryDirectory(prefix="fmv_") as tmpdir:
        temp_avi = Path(tmpdir) / f"{info.name}.avi"
        temp_str = Path(tmpdir) / f"{info.name}.str"

        burn_subtitles_to_avi(webm_file, srt_file, temp_avi, duration=duration)
        encode_avi_to_str(temp_avi, temp_str, start_lba=info.start_lba)

        raw_bytes = temp_str.read_bytes()
        final_bytes = pad_str_to_sectors(raw_bytes, info.sectors, start_lba=info.start_lba)
        out_path.write_bytes(final_bytes)

    return len(final_bytes)

def concat_movies_to_str(movie_paths: list[Path | str], out_path: Path | str) -> int:
    """Concatenate individual movie STR files into a unified MOVIE.STR stream."""
    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    with open(out_p, "wb") as f_out:
        for p in movie_paths:
            p = Path(p)
            if not p.is_file():
                raise FileNotFoundError(f"Cannot concatenate missing movie file: {p}")
            with open(p, "rb") as f_in:
                while chunk := f_in.read(1024 * 1024):
                    f_out.write(chunk)
                    total_bytes += len(chunk)
    expected_bytes = MOVIE_STR_TOTAL_SECTORS * SECTOR_RAW_SIZE
    if total_bytes != expected_bytes:
        raise ValueError(
            f"Combined MOVIE.STR size mismatch: got {total_bytes:,} bytes, expected {expected_bytes:,} bytes"
        )
    return total_bytes


def batch_encode_all_movies(
    videos_dir: Path | str = VIDEOS_DIR,
    out_dir: Path | str | None = None,
    source_bin_path: Path | str | None = None,
    duration: float | int | None = None,
    force: bool = False,
) -> list[Path]:
    """Batch encode all 12 movies (s00..s11) into PS1 STR files and generate MOVIE.STR.

    - s00: extracted directly from source_bin_path (downloads/sr.bin) as unsubbed opening.
    - s01..s11: burned with Russian subtitles via FFmpeg, encoded to STR via psxavenc,
      and padded to exact MOVIE_MAP sector bounds.

    Returns a list of generated STR file paths.
    """
    videos_path = Path(videos_dir)
    out_path = Path(out_dir) if out_dir is not None else (REPO_ROOT / "build" / "movies")
    out_path.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []
    print(f"Batch encoding all 12 movies into {out_path}...")
    for idx in range(12):
        info = get_movie_info(idx)
        dest_str = out_path / f"{info.name}.str"
        if not force and duration is None and dest_str.is_file() and dest_str.stat().st_size == info.raw_size_bytes:
            print(f"[{idx+1:2d}/12] Movie {idx:2d} ({info.name}) already encoded ({info.raw_size_bytes:,} bytes), reusing.")
            results.append(dest_str)
            continue

        print(f"[{idx+1:2d}/12] Encoding movie {idx:2d} ({info.name}): target {info.sectors:,} sectors ({info.raw_size_bytes:,} bytes)...")
        bytes_written = encode_movie(
            movie_idx=idx,
            videos_dir=videos_path,
            out_str_path=dest_str,
            source_bin_path=source_bin_path,
            duration=duration,
        )
        if bytes_written != info.raw_size_bytes:
            raise ValueError(
                f"Movie {info.name} size mismatch: got {bytes_written} bytes, expected {info.raw_size_bytes}"
            )
        results.append(dest_str)

    combined_str_path = out_path / "MOVIE.STR"
    if not force and duration is None and combined_str_path.is_file() and combined_str_path.stat().st_size == MOVIE_STR_TOTAL_SECTORS * SECTOR_RAW_SIZE:
        print(f"Combined MOVIE.STR already exists ({combined_str_path.stat().st_size:,} bytes), reusing.")
    else:
        print(f"Concatenating all 12 movies into {combined_str_path}...")
        concat_movies_to_str(results, combined_str_path)
    print("Batch encoding completed successfully.")
    return results


def inject_movie_str_into_disc(
    disc_path: Path | str,
    movies_dir: Path | str,
) -> int:
    """Inject the combined 184,290-sector MOVIE.STR into a PS1 CD-ROM disc image.

    Can accept:
    - A directory containing s00.str..s11.str (or MOVIE.STR).
    - A single combined MOVIE.STR file.

    Writes exactly 433,450,080 bytes (184,290 sectors) at LBA 127 (raw byte offset 298,704).
    Validates disc size and movie stream headers.

    Returns the total number of bytes written.
    """
    disc_p = Path(disc_path)
    if not disc_p.is_file():
        raise FileNotFoundError(f"Target disc image not found: {disc_p}")

    disc_size = disc_p.stat().st_size
    if disc_size != 712_300_848:
        raise ValueError(
            f"Invalid target disc size: expected 712,300,848 bytes, got {disc_size:,} bytes"
        )

    movies_p = Path(movies_dir)
    movie_str_file: Path | None = None
    if movies_p.is_file():
        movie_str_file = movies_p
    elif (movies_p / "MOVIE.STR").is_file():
        movie_str_file = movies_p / "MOVIE.STR"

    total_bytes_written = 0
    disc_start_offset = MOVIE_STR_LBA * SECTOR_RAW_SIZE
    expected_total_bytes = MOVIE_STR_TOTAL_SECTORS * SECTOR_RAW_SIZE

    if movie_str_file is not None and movie_str_file.stat().st_size == expected_total_bytes:
        print(f"Injecting combined {movie_str_file.name} ({expected_total_bytes:,} bytes) into {disc_p} at LBA {MOVIE_STR_LBA}...")
        with open(disc_p, "r+b") as f_disc, open(movie_str_file, "rb") as f_movie:
            f_disc.seek(disc_start_offset)
            while chunk := f_movie.read(1024 * 1024):
                f_disc.write(chunk)
                total_bytes_written += len(chunk)
    else:
        print(f"Injecting individual movies from directory {movies_p} into {disc_p}...")
        with open(disc_p, "r+b") as f_disc:
            for idx in range(12):
                info = get_movie_info(idx)
                movie_file = movies_p / f"{info.name}.str"
                if not movie_file.is_file():
                    raise FileNotFoundError(f"Missing movie file: {movie_file}")
                if movie_file.stat().st_size != info.raw_size_bytes:
                    raise ValueError(
                        f"Movie {movie_file.name} size mismatch: "
                        f"{movie_file.stat().st_size:,} != expected {info.raw_size_bytes:,}"
                    )
                f_disc.seek(info.raw_offset)
                with open(movie_file, "rb") as f_movie:
                    while chunk := f_movie.read(1024 * 1024):
                        f_disc.write(chunk)
                        total_bytes_written += len(chunk)

    if total_bytes_written != expected_total_bytes:
        raise ValueError(
            f"Injected {total_bytes_written:,} bytes, expected {expected_total_bytes:,} bytes"
        )

    # Post-injection integrity check: verify start of each movie
    with open(disc_p, "rb") as f_disc:
        for idx in range(12):
            info = get_movie_info(idx)
            f_disc.seek(info.raw_offset)
            sec = f_disc.read(SECTOR_RAW_SIZE)
            if len(sec) != SECTOR_RAW_SIZE:
                raise IOError(f"Failed to read movie {idx} start sector from disc")
            if sec[:12] != b"\x00" + b"\xff" * 10 + b"\x00":
                raise ValueError(f"Movie {idx} at LBA {info.start_lba} has invalid sync bytes")
            if sec[15] != 2:
                raise ValueError(f"Movie {idx} at LBA {info.start_lba} is not Mode 2")
            expected_msf = lba_to_msf(info.start_lba)
            if sec[12:15] != expected_msf:
                raise ValueError(
                    f"Movie {idx} at LBA {info.start_lba} MSF mismatch: "
                    f"got {sec[12:15].hex()}, expected {expected_msf.hex()}"
                )
            if sec[18] not in (0x48, 0x64):
                raise ValueError(
                    f"Movie {idx} at LBA {info.start_lba} has unexpected submode: 0x{sec[18]:02X}"
                )
            # Find and verify first video sector within first 8 sectors
            found_mdec = False
            for s in range(min(8, info.sectors)):
                f_disc.seek(info.raw_offset + s * SECTOR_RAW_SIZE)
                cand = f_disc.read(SECTOR_RAW_SIZE)
                if cand[18] == 0x48 and cand[24:28] == b"\x60\x01\x01\x80":
                    found_mdec = True
                    break
            if not found_mdec:
                raise ValueError(f"Movie {idx} at LBA {info.start_lba} missing MDEC video stream")
    new_disc_size = disc_p.stat().st_size
    if new_disc_size != 712_300_848:
        raise ValueError(f"Disc size corrupted after injection: {new_disc_size:,} bytes")

    print(f"Successfully injected {total_bytes_written:,} bytes into {disc_p} (size={new_disc_size:,} bytes).")
    return total_bytes_written


def main() -> None:
    """CLI helper to inspect MOVIE_MAP and test psxavenc installation."""
    parser = argparse.ArgumentParser(description="Slayers Royal PS1 FMV Pipeline")
    parser.add_argument("--verify", action="store_true", help="Verify MOVIE_MAP and psxavenc")
    parser.add_argument("--list", action="store_true", help="List all 12 movies and sector bounds")
    parser.add_argument("--info", type=int, metavar="IDX", help="Show details for movie index (0..11)")
    parser.add_argument("--encode", type=int, metavar="IDX", help="Encode movie index (0..11) to PS1 STR")
    parser.add_argument("--out", type=Path, metavar="OUT_STR", help="Output STR file path for --encode")
    parser.add_argument("--duration", type=float, metavar="SECS", help="Limit encoding duration in seconds")
    parser.add_argument("--bin", type=Path, metavar="BIN", help="Source disc image BIN path (for s00)")
    parser.add_argument("--all-movies", action="store_true", help="Batch encode all 12 movies (s00..s11)")
    parser.add_argument("--inject-disc", "--disc", type=Path, dest="inject_disc", metavar="BIN", help="Inject MOVIE.STR into target disc image")
    parser.add_argument("--videos-dir", type=Path, default=VIDEOS_DIR, help="Source videos directory containing webm and srt")
    parser.add_argument("--movies-dir", type=Path, help="Directory containing encoded sXX.str or MOVIE.STR")
    parser.add_argument("--force", action="store_true", help="Force re-encoding even if output files exist")
    args = parser.parse_args()
    if args.verify or (not args.list and args.info is None and args.encode is None and not args.all_movies and args.inject_disc is None):
        verify_movie_map()
        print("MOVIE_MAP verified: 12 movies, 184,290 sectors, contiguous.")
        version = check_psxavenc()
        print(f"psxavenc tool verified: {version}")

    if args.list:
        print(f"{'Idx':<4} {'Name':<6} {'Start LBA':<10} {'End LBA':<10} {'Sectors':<9} {'Bytes':<12} {'Subbed'}")
        print("-" * 65)
        for idx in range(12):
            info = get_movie_info(idx)
            print(
                f"{info.index:<4} {info.name:<6} {info.start_lba:<10} {info.end_lba:<10} "
                f"{info.sectors:<9} {info.raw_size_bytes:<12} {info.subbed}"
            )

    if args.info is not None:
        info = get_movie_info(args.info)
        webm, srt = get_video_assets(args.info)
        print(f"Movie {info.index} ({info.name}):")
        print(f"  Relative Sectors : {info.rel_sec} .. {info.rel_sec + info.sectors - 1} ({info.sectors} sectors)")
        print(f"  Absolute LBA     : {info.start_lba} .. {info.end_lba - 1}")
        print(f"  Raw Byte Range   : 0x{info.raw_offset:08X} .. 0x{info.raw_offset + info.raw_size_bytes - 1:08X}")
        print(f"  Subbed           : {info.subbed}")
        print(f"  Webm Asset       : {webm}")
        print(f"  SRT Asset        : {srt}")

    if args.encode is not None:
        idx = args.encode
        info = get_movie_info(idx)
        out_file = args.out or (REPO_ROOT / "build" / f"{info.name}.str")
        print(f"Encoding movie {idx} ({info.name}) -> {out_file}...")
        bytes_written = encode_movie(
            movie_idx=idx,
            videos_dir=VIDEOS_DIR,
            out_str_path=out_file,
            source_bin_path=args.bin,
            duration=args.duration,
        )
        sectors = bytes_written // SECTOR_RAW_SIZE
        print(f"Done! Written {bytes_written:,} bytes ({sectors:,} sectors). Target was {info.sectors:,} sectors.")

    if args.all_movies:
        target_dir = args.movies_dir or args.out or (REPO_ROOT / "build" / "movies")
        batch_encode_all_movies(
            videos_dir=args.videos_dir,
            out_dir=target_dir,
            source_bin_path=args.bin,
            duration=args.duration,
            force=args.force,
        )
        if args.inject_disc is not None:
            inject_movie_str_into_disc(
                disc_path=args.inject_disc,
                movies_dir=target_dir,
            )
    elif args.inject_disc is not None:
        target_dir = args.movies_dir or args.out or (REPO_ROOT / "build" / "movies")
        inject_movie_str_into_disc(
            disc_path=args.inject_disc,
            movies_dir=target_dir,
        )
if __name__ == "__main__":
    main()
