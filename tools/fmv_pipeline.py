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

# PS1 CD-ROM and MOVIE.STR constants
MOVIE_STR_LBA = 127
MOVIE_STR_TOTAL_SECTORS = 184290
SECTOR_RAW_SIZE = 2352
SECTOR_USER_SIZE = 2048

# Exact movie stream sector layout in MOVIE.STR (12 movies)
MOVIE_MAP: dict[int, dict[str, Any]] = {
    0:  {"name": "s00", "rel_sec": 0,      "sectors": 13501, "subbed": False},
    1:  {"name": "s01", "rel_sec": 13501,  "sectors": 12800, "subbed": True},
    2:  {"name": "s02", "rel_sec": 26301,  "sectors": 23399, "subbed": True},
    3:  {"name": "s03", "rel_sec": 49700,  "sectors": 10308, "subbed": True},
    4:  {"name": "s04", "rel_sec": 60008,  "sectors": 12384, "subbed": True},
    5:  {"name": "s05", "rel_sec": 72392,  "sectors": 19570, "subbed": True},
    6:  {"name": "s06", "rel_sec": 91962,  "sectors": 9792,  "subbed": True},
    7:  {"name": "s07", "rel_sec": 101754, "sectors": 9920,  "subbed": True},
    8:  {"name": "s08", "rel_sec": 111674, "sectors": 11877, "subbed": True},
    9:  {"name": "s09", "rel_sec": 123551, "sectors": 26802, "subbed": True},
    10: {"name": "s10", "rel_sec": 150353, "sectors": 3456,  "subbed": True},
    11: {"name": "s11", "rel_sec": 153809, "sectors": 30481, "subbed": True},
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

def make_padding_sector(sector_num: int = 0) -> bytes:
    """Generate a single 2,352-byte CD-XA Mode 2 Form 1 zero-padding sector."""
    sync = b"\x00" + b"\xff" * 10 + b"\x00"
    lba = 150 + sector_num
    m = (lba // 75) // 60
    s = (lba // 75) % 60
    f = lba % 75
    header = bytes([
        ((m // 10) << 4) | (m % 10),
        ((s // 10) << 4) | (s % 10),
        ((f // 10) << 4) | (f % 10),
        2,
    ])
    subheader = b"\x00" * 8
    payload = b"\x00" * (SECTOR_RAW_SIZE - 24)
    return sync + header + subheader + payload


def pad_str_to_sectors(str_bytes: bytes, target_sectors: int) -> bytes:
    """Enforce exact sector count on an STR stream matching target_sectors * 2352 bytes.

    - If str_bytes is shorter than target_sectors * 2352, appends valid CD-XA zero-padding
      sectors (subheader 0x00 * 8) with accurate Mode 2 CD-ROM sector timing.
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

    current_sec_count = len(result) // SECTOR_RAW_SIZE
    remaining_secs = target_sectors - current_sec_count

    if remaining_secs > 0:
        sync = b"\x00" + b"\xff" * 10 + b"\x00"
        subheader = b"\x00" * 8
        payload = b"\x00" * (SECTOR_RAW_SIZE - 24)
        padding_chunks = []
        for i in range(remaining_secs):
            sec_idx = current_sec_count + i
            lba = 150 + sec_idx
            m = (lba // 75) // 60
            s = (lba // 75) % 60
            f = lba % 75
            header = bytes([
                ((m // 10) << 4) | (m % 10),
                ((s // 10) << 4) | (s % 10),
                ((f // 10) << 4) | (f % 10),
                2,
            ])
            padding_chunks.append(sync + header + subheader + payload)
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


def encode_avi_to_str(avi_path: Path | str, out_str_path: Path | str) -> Path:
    """Encode an uncompressed AVI into a PlayStation 1 MDEC STR CD-XA stream via psxavenc.

    Uses:
        psxavenc -t strcd -f 18900 -c 1 -F 1 -C 1 -r 15 -x 2 -T 0x8001 {avi_path} {out_str_path}
    Produces 2,352-byte CD-XA Mode 2 Form 1 interleaved audio/video sectors.
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
        str(avi_path),
        str(out_str_path),
    ]

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
        encode_avi_to_str(temp_avi, temp_str)

        raw_bytes = temp_str.read_bytes()
        final_bytes = pad_str_to_sectors(raw_bytes, info.sectors)
        out_path.write_bytes(final_bytes)

    return len(final_bytes)


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
    args = parser.parse_args()

    if args.verify or (not args.list and args.info is None and args.encode is None):
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


if __name__ == "__main__":
    main()
