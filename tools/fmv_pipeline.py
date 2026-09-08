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


def main() -> None:
    """CLI helper to inspect MOVIE_MAP and test psxavenc installation."""
    parser = argparse.ArgumentParser(description="Slayers Royal PS1 FMV Pipeline")
    parser.add_argument("--verify", action="store_true", help="Verify MOVIE_MAP and psxavenc")
    parser.add_argument("--list", action="store_true", help="List all 12 movies and sector bounds")
    parser.add_argument("--info", type=int, metavar="IDX", help="Show details for movie index (0..11)")
    args = parser.parse_args()

    if args.verify or (not args.list and args.info is None):
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


if __name__ == "__main__":
    main()
