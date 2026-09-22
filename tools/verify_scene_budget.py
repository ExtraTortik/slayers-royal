#!/usr/bin/env python3
"""Guard the PROG.UNT archive layout of a built image against runtime overflow.

Facts this enforces (see docs/LOCALIZATION_GUIDE.md):

* every story scene entry 0x03B..0x057 must be <= 19 sectors (0x9800 bytes).
  The engine loads the current scene at RAM 0x80121000 and the next container
  (entry 0x058) at 0x8012A800; a larger scene is overwritten and the text
  scanner walks into garbage (the "inn hang");
* entries 0x058 and above must keep their original start sector and size;
* the archive must keep its original total size (growth is zero-sum: sectors
  are borrowed from the zero tail of donor entry 0x011).

Usage: python3 tools/verify_scene_budget.py --bin localization-output/ru/slayers_royal_ru.bin
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.patch_inspection import parse_iso_dir, read_sector, read_extent, read_unt_index  # noqa: E402

SCENE_ENTRIES = range(0x03B, 0x058)
MAX_SCENE_SECTORS = 19
DONOR_ENTRY = 0x011
# Original Japanese layout for the entries that must not move.
ORIGINAL_0x058_START = 3290
ORIGINAL_ENTRY_COUNT = 444
ORIGINAL_TOTAL_SECTORS = 4308


def prog_archive(disc: Path) -> bytes:
    pvd = read_sector(disc, 16)
    root_lba = struct.unpack_from("<I", pvd, 158)[0]
    root_size = struct.unpack_from("<I", pvd, 166)[0]
    lba, size = parse_iso_dir(disc, root_lba, root_size)["PROG.UNT"]
    return read_extent(disc, lba, size)


def check(disc: Path) -> list[str]:
    archive = prog_archive(disc)
    entries = read_unt_index(archive)
    problems: list[str] = []
    if len(entries) != ORIGINAL_ENTRY_COUNT:
        problems.append(f"PROG.UNT has {len(entries)} entries, expected {ORIGINAL_ENTRY_COUNT}")
    for idx in SCENE_ENTRIES:
        n = entries[idx].sector_count
        if n > MAX_SCENE_SECTORS:
            problems.append(
                f"scene 0x{idx:03X} is {n} sectors; the runtime window allows {MAX_SCENE_SECTORS} "
                f"(0x80121000..0x8012A800). Shorten the scene text or use compact glyphs."
            )
    e058 = entries[0x058]
    if e058.start_sector != ORIGINAL_0x058_START:
        problems.append(f"entry 0x058 starts at sector {e058.start_sector}, expected {ORIGINAL_0x058_START}")
    last = entries[-1]
    if last.start_sector + last.sector_count != ORIGINAL_TOTAL_SECTORS:
        problems.append("PROG.UNT total size changed")
    donor = entries[DONOR_ENTRY].extract(archive)
    if donor[-2048:].count(0) != 2048:
        problems.append("donor entry 0x011 has no zero sector left at its tail")
    for idx in range(1, len(entries)):
        prev, cur = entries[idx - 1], entries[idx]
        if cur.start_sector != prev.start_sector + prev.sector_count:
            problems.append(f"entry 0x{idx:03X} is not contiguous with 0x{idx - 1:03X}")
            break
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bin", type=Path, required=True)
    args = parser.parse_args()
    problems = check(args.bin)
    archive_entries = read_unt_index(prog_archive(args.bin))
    for idx in SCENE_ENTRIES:
        n = archive_entries[idx].sector_count
        print(f"  scene 0x{idx:03X}: {n:2d}/{MAX_SCENE_SECTORS} sectors{'  (at ceiling)' if n == MAX_SCENE_SECTORS else ''}")
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        return 1
    print("[ok] scene budgets and archive layout are within runtime limits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
