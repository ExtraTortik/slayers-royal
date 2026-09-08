#!/usr/bin/env python3
"""Extract and catalog all unique room inspection strings across all rooms in PROG.UNT.

This tool:
1. Locates or builds the English PROG.UNT archive from downloads/sr.bin or provided image.
2. Iterates over all room entries (0x059..0x0F8) in PROG.UNT using tools.patch_inspection.
3. Filters out engine placeholders ("UNDER\\nCONSTRUCTION") and empty strings.
4. Categorizes strings into object names and descriptions based on object triplets.
5. Deduplicates strings, tracks occurrences and room IDs, and pre-populates existing
   translations from data/inspection_ru.json.
6. Outputs formatted, user-editable JSON to translations/room_inspection_ru.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any

# Ensure repository root and patch_repo are in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))

from patch_repo.localization.cli import _apply_english_base
from patch_repo.localization.disc import ENGLISH_PROG_SHA256, read_prog
from tools.patch_inspection import (
    DEFAULT_CHARMAP,
    load_charmap,
    parse_inspection_entry,
    parse_iso_dir,
    read_extent,
    read_sector,
    read_unt_index,
)

SOURCE_BIN_SHA256 = "89760d728f0580dba1c6176f024d3cd6f8fc105b79bd1c27a819208fa0b4d0fe"
ENGLISH_BASE_BIN_SHA256 = "0e85c5b9fc1f894e0bcafe631f890c7c1961011df29ad3f96abef21d91da7f04"

DEFAULT_TRANSLATIONS_PATH = REPO_ROOT / "data" / "inspection_ru.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "translations" / "room_inspection_ru.json"
DEFAULT_SOURCE_BIN = REPO_ROOT / "downloads" / "sr.bin"


def get_english_prog(
    bin_path: Path | None = None,
    prog_path: Path | None = None,
    verbose: bool = True,
) -> bytes:
    """Obtain the pristine English PROG.UNT binary data."""
    if prog_path is not None and prog_path.is_file():
        if verbose:
            print(f"Reading PROG.UNT directly from {prog_path}...")
        return prog_path.read_bytes()

    target_bin = bin_path or DEFAULT_SOURCE_BIN
    if not target_bin.is_file():
        # Check alternative locations
        alt_bins = [
            REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin",
            REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin",
        ]
        for alt in alt_bins:
            if alt.is_file():
                target_bin = alt
                break

    if not target_bin.is_file():
        raise FileNotFoundError(f"No source BIN or PROG.UNT found. Tried {target_bin}")

    # Check file hash or apply English patch if it's the Japanese source BIN
    with target_bin.open("rb") as f:
        head = f.read(1024 * 1024)
    # Quick probe: if it's downloads/sr.bin, apply English base
    if target_bin.resolve() == DEFAULT_SOURCE_BIN.resolve():
        if verbose:
            print("Applying English base patch to downloads/sr.bin...")
        descriptor, temp_path = tempfile.mkstemp(prefix=".eng_base.", suffix=".bin")
        os.close(descriptor)
        temp_bin = Path(temp_path)
        try:
            _apply_english_base(target_bin, temp_bin)
            return read_prog(temp_bin, ENGLISH_PROG_SHA256)
        finally:
            temp_bin.unlink(missing_ok=True)

    # Otherwise read PROG.UNT from ISO filesystem in the BIN
    pvd = read_sector(target_bin, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(target_bin, root_lba, root_size)
    if "PROG.UNT" not in root_dir:
        raise ValueError(f"PROG.UNT not found in ISO root directory of {target_bin}")

    prog_lba, prog_size = root_dir["PROG.UNT"]
    if verbose:
        print(f"Reading PROG.UNT from {target_bin} (LBA {prog_lba}, {prog_size} bytes)...")
    return read_extent(target_bin, prog_lba, prog_size)


def classify_string_role(
    string_text: str,
    name_counts: dict[str, int],
    desc_counts: dict[str, int],
) -> str:
    """Classify an inspection string as either 'name' or 'description'.

    Uses object triplet roles (name_idx vs desc_idx) in the room entries,
    plus disambiguation heuristics for multi-role and unreferenced strings.
    """
    # Specific edge case overrides for sentences vs names
    known_descriptions = {
        "Come to think,\nI haven't seen\nother guests at",
        "Elf towns don't\nlook different\nfrom human",
        "It's a window\nthat opens\noutward.",
        "Item shops sell\ntravel goods,\nlike capes.",
        "Let's go\nsomewhere else.",
        "More carpet\non the floor.",
        "Nothing here.",
        "Same as on the\nmain street...\nWalk in the",
        "These houses\nface north.",
        "Don't put boxes\nhere. Someone\ncould trip.",
        "He's neatly\ndressed.",
        "No need to\ngo inside.",
        "The entrance is\nright by it.\nWhy a window?",
        "The two doors\naren't the same\nsize.",
        "Watch this box.\nWith all this\nstuff lying",
    }
    if string_text in known_descriptions:
        return "description"

    known_names = {
        "Two doors.",
        "A-I-U-E-O",
        "A plaque above\nthe door.",
        "A local.",
        "A window.",
        "A woman.",
        "An old man.",
        "Quite a crowd.",
        "The innkeeper.",
    }
    if string_text in known_names:
        return "name"

    n_c = name_counts.get(string_text, 0)
    d_c = desc_counts.get(string_text, 0)

    if n_c > 0 and d_c == 0:
        return "name"
    if d_c > 0 and n_c == 0:
        return "description"
    if n_c > 0:
        # If used in both roles, object fallback descriptions duplicate the name.
        return "name"

    # Default fallback for unreferenced strings
    if "\n" in string_text:
        return "description"
    return "name"


def load_prepopulated_translations(
    translations_path: Path | None,
    prog_data: bytes,
    charmap: dict[str, int],
) -> dict[str, str]:
    """Extract existing translations from data/inspection_ru.json."""
    if translations_path is None or not translations_path.is_file():
        return {}

    doc = json.loads(translations_path.read_text(encoding="utf-8"))
    translations_map: dict[str, str] = {}

    entries = read_unt_index(prog_data)

    # 1. Extract from entry-specific translations (e.g. 0x05D Lakewood Tavern)
    for entry_key, entry_spec in doc.get("entries", {}).items():
        try:
            entry_idx = int(entry_key, 16 if entry_key.lower().startswith("0x") else 10)
        except ValueError:
            continue
        if entry_idx >= len(entries):
            continue

        entry_bytes = entries[entry_idx].extract(prog_data)
        try:
            info = parse_inspection_entry(entry_bytes, entry_index=entry_idx, charmap=charmap)
        except Exception:
            continue

        ru_strings: list[str] = []
        if isinstance(entry_spec, list):
            ru_strings = entry_spec
        elif isinstance(entry_spec, dict):
            ru_strings = entry_spec.get("strings", [])

        for eng_s, ru_s in zip(info.extracted_strings, ru_strings):
            if eng_s and ru_s and eng_s != "UNDER\nCONSTRUCTION":
                translations_map[eng_s] = ru_s

    # 2. Extract from common dictionary
    for eng_s, ru_s in doc.get("common", {}).items():
        if eng_s and ru_s and eng_s not in translations_map:
            translations_map[eng_s] = ru_s

    return translations_map


def extract_inspection_catalog(
    prog_data: bytes,
    translations_path: Path | None = None,
    charmap: dict[str, int] | None = None,
    start_entry: int = 0x059,
    end_entry: int = 0x0F8,
) -> dict[str, dict[str, Any]]:
    """Scan PROG.UNT room entries, extract and deduplicate inspection strings into catalog.

    Returns:
        dict[english_string, {
            "russian": str,
            "type": "name" | "description",
            "rooms": list[str],
            "frequency": int
        }]
    """
    cm = charmap or DEFAULT_CHARMAP
    entries = read_unt_index(prog_data)

    # Pre-parse all rooms to gather string instances and object triplet roles
    parsed_rooms: list[tuple[int, list[str]]] = []
    name_role_counts: dict[str, int] = {}
    desc_role_counts: dict[str, int] = {}

    for entry_idx in range(start_entry, min(end_entry + 1, len(entries))):
        entry_bytes = entries[entry_idx].extract(prog_data)
        try:
            info = parse_inspection_entry(entry_bytes, entry_index=entry_idx, charmap=cm)
        except Exception:
            continue

        parsed_rooms.append((entry_idx, info.extracted_strings))

        # Check header pointers for object table (0x10 -> 0x14)
        if len(entry_bytes) > 0x14:
            ptr_10 = struct.unpack_from(">I", entry_bytes, 0x10)[0] - 0x00200000
            ptr_14 = struct.unpack_from(">I", entry_bytes, 0x14)[0] - 0x00200000
            if 0 <= ptr_10 < ptr_14 <= len(entry_bytes) and (ptr_14 - ptr_10) % 2 == 0:
                count = (ptr_14 - ptr_10) // 2
                indices = [
                    struct.unpack_from(">H", entry_bytes, ptr_10 + k * 2)[0]
                    for k in range(count)
                ]
                # Process triplets [name, desc1, desc2]
                for k in range(0, count - 2, 3):
                    n_idx, d1_idx, d2_idx = indices[k], indices[k + 1], indices[k + 2]
                    if n_idx < len(info.extracted_strings):
                        ns = info.extracted_strings[n_idx]
                        if ns and ns != "UNDER\nCONSTRUCTION":
                            name_role_counts[ns] = name_role_counts.get(ns, 0) + 1
                    if d1_idx < len(info.extracted_strings):
                        d1s = info.extracted_strings[d1_idx]
                        if d1s and d1s != "UNDER\nCONSTRUCTION":
                            desc_role_counts[d1s] = desc_role_counts.get(d1s, 0) + 1
                    if d2_idx < len(info.extracted_strings):
                        d2s = info.extracted_strings[d2_idx]
                        if d2s and d2s != "UNDER\nCONSTRUCTION":
                            desc_role_counts[d2s] = desc_role_counts.get(d2s, 0) + 1

    # Load existing translations
    prepopulated = load_prepopulated_translations(translations_path, prog_data, cm)

    # Build catalog in natural order of appearance across rooms
    catalog: dict[str, dict[str, Any]] = {}
    for entry_idx, strings in parsed_rooms:
        room_hex = f"0x{entry_idx:03X}"
        for s in strings:
            if not s or s == "UNDER\nCONSTRUCTION":
                continue

            if s not in catalog:
                str_type = classify_string_role(s, name_role_counts, desc_role_counts)
                ru_text = prepopulated.get(s, "")
                catalog[s] = {
                    "russian": ru_text,
                    "type": str_type,
                    "rooms": [room_hex],
                    "frequency": 1,
                }
            else:
                catalog[s]["frequency"] += 1
                if room_hex not in catalog[s]["rooms"]:
                    catalog[s]["rooms"].append(room_hex)

    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract all unique room inspection strings from PROG.UNT into user-editable JSON."
    )
    parser.add_argument(
        "--bin",
        type=Path,
        help="Path to source BIN image (defaults to downloads/sr.bin)",
    )
    parser.add_argument(
        "--prog",
        type=Path,
        help="Path to standalone PROG.UNT archive",
    )
    parser.add_argument(
        "--translations",
        type=Path,
        default=DEFAULT_TRANSLATIONS_PATH,
        help="Path to existing data/inspection_ru.json for pre-populating translations",
    )
    parser.add_argument(
        "--charmap",
        type=Path,
        help="Path to custom glyph_map.json",
    )
    parser.add_argument(
        "--output",
        "--out",
        dest="output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output path for editable JSON (defaults to translations/room_inspection_ru.json)",
    )

    args = parser.parse_args()

    charmap = load_charmap(args.charmap)
    prog_data = get_english_prog(bin_path=args.bin, prog_path=args.prog)

    catalog = extract_inspection_catalog(
        prog_data=prog_data,
        translations_path=args.translations,
        charmap=charmap,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    formatted_json = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(formatted_json, encoding="utf-8")

    prepopulated_count = sum(1 for v in catalog.values() if v["russian"])
    total_instances = sum(v["frequency"] for v in catalog.values())

    print(f"Extracted {len(catalog)} unique inspection strings ({total_instances} instances across rooms).")
    print(f"Pre-populated {prepopulated_count} strings with known translations.")
    print(f"Wrote user-editable JSON catalog to: {args.output}")

    if len(catalog) != 734:
        print(f"WARNING: Expected 734 unique strings, got {len(catalog)}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
