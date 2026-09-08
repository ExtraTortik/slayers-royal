#!/usr/bin/env python3
"""Room object inspection string translation and patching pipeline for Slayers Royal PS1.

This tool:
1. Parses PROG.UNT room inspection entries (0x058..0x138).
2. Extracts string tables and 32-bit RAM pointer tables.
3. Encodes Russian inspection strings into 16-bit big-endian words using Cyrillic charmaps.
4. Rebuilds the string block and pointer table, adjusting 32-bit RAM pointers (base 0x00200000).
5. Updates entry header pointers at 0x0024, 0x002C, and 0x0030 while preserving the trailing data block.
6. Verifies that rebuilt entries do not exceed their allocated sector capacity.
7. Supports patching standalone UNT archives or full PS1 CD-ROM BIN disc images with EDC/ECC repair.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

# Ensure repository root and patch_repo are in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))

try:
    from localization.disc import replace_extent_in_place
except ImportError:
    replace_extent_in_place = None

try:
    from tools.text_wrapper import shorten_lines
except ImportError:
    try:
        from text_wrapper import shorten_lines
    except ImportError:
        shorten_lines = None

# Slayers Royal PS1 Hardware & Architecture Constants
RAM_BASE = 0x00200000
SECTOR_SIZE = 2048
RAW_SECTOR_SIZE = 2352
USER_OFFSET = 24
USER_SIZE = 2048

# Control Glyphs in 16-bit Slayers Royal script
CHAR_NEWLINE = 0x00FE
CHAR_PAGE_CONTINUE = 0x00FD
CHAR_STRING_TERMINATOR = 0x00FF

# Header field offsets in room inspection entries
HDR_PTR_TABLE_OFFSET = 0x0024
HDR_TRAILING_PTR_1 = 0x002C
HDR_TRAILING_PTR_2 = 0x0030
HDR_ROOM_NAME_PTR = 0x003C
# Entry range for room inspection entries in PROG.UNT
ROOM_ENTRIES_START = 0x059
ROOM_ENTRIES_END = 0x0F8
DEFAULT_MISSING_ROOMS = REPO_ROOT / "data" / "missing_rooms_jp_ru.json"
DEFAULT_SOURCE_BIN = REPO_ROOT / "downloads" / "sr.bin"


def load_missing_rooms(path: str | Path | None = None) -> dict[str, Any]:
    """Load omitted room translations mapping from JSON."""
    if path is not None:
        p = Path(path)
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    elif DEFAULT_MISSING_ROOMS.is_file():
        return json.loads(DEFAULT_MISSING_ROOMS.read_text(encoding="utf-8"))
    return {}


def get_missing_room_strings(
    entry_idx: int, missing_rooms_doc: dict[str, Any] | None
) -> list[str] | None:
    """Retrieve translated strings list for an entry from missing_rooms dictionary."""
    if not missing_rooms_doc:
        return None
    keys = [
        f"0x{entry_idx:03X}",
        f"0x{entry_idx:03x}",
        f"0x{entry_idx:X}",
        f"0x{entry_idx:x}",
        str(entry_idx),
        entry_idx,
    ]
    for k in keys:
        if k in missing_rooms_doc:
            val = missing_rooms_doc[k]
            if isinstance(val, dict):
                return val.get("strings_ru") or val.get("strings") or []
            elif isinstance(val, list):
                return list(val)
    return None


def extract_prog_from_path(path: str | Path) -> bytes:
    """Extract PROG.UNT bytes from either a standalone archive or a PS1 BIN disc image."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {p}")
    if p.stat().st_size > 100 * 1024 * 1024:
        pvd = read_sector(p, 16)
        root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
        root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
        root_dir = parse_iso_dir(p, root_lba, root_size)
        if "PROG.UNT" not in root_dir:
            raise ValueError(f"PROG.UNT not found in ISO root directory of {p}")
        prog_lba, prog_size = root_dir["PROG.UNT"]
        return read_extent(p, prog_lba, prog_size)
    return p.read_bytes()


# Canonical Russian charmap mapping characters to 16-bit glyph IDs
# Derived from patch_repo glyph allocation for Slayers Royal PS1 Russian localization.
DEFAULT_CHARMAP: dict[str, int] = {
    # English / ASCII base glyphs
    " ": 0x007D,
    "!": 0x00A6,
    '"': 0x00A3,
    "'": 0x031B,
    "(": 0x0001,
    ")": 0x0002,
    "*": 0x0003,
    ",": 0x00A1,
    "-": 0x00A4,
    ".": 0x00A2,
    "/": 0x0004,
    ":": 0x00BC,
    ";": 0x0005,
    "?": 0x00A7,
    "=": 0x0006,
    "0": 0x00A8,
    "1": 0x00A9,
    "2": 0x00AA,
    "3": 0x00AB,
    "4": 0x00AC,
    "5": 0x00AD,
    "6": 0x00AE,
    "7": 0x00AF,
    "8": 0x00B0,
    "9": 0x00B1,
    "A": 0x00BE,
    "B": 0x014C,
    "C": 0x0128,
    "D": 0x00BF,
    "E": 0x00B6,
    "F": 0x014D,
    "G": 0x0088,
    "H": 0x0091,
    "I": 0x0081,
    "J": 0x014F,
    "K": 0x0192,
    "L": 0x0082,
    "M": 0x0148,
    "N": 0x0086,
    "O": 0x00BB,
    "P": 0x019B,
    "Q": 0x01A7,
    "R": 0x0099,
    "S": 0x0090,
    "T": 0x008D,
    "U": 0x01D2,
    "V": 0x00BD,
    "W": 0x008E,
    "X": 0x01FD,
    "Y": 0x009A,
    "Z": 0x0209,
    "a": 0x0017,
    "b": 0x0031,
    "c": 0x003A,
    "d": 0x0040,
    "e": 0x0048,
    "f": 0x004A,
    "g": 0x004B,
    "h": 0x004D,
    "i": 0x004F,
    "j": 0x0055,
    "k": 0x005F,
    "l": 0x0060,
    "m": 0x0062,
    "n": 0x0063,
    "o": 0x0067,
    "p": 0x0068,
    "q": 0x0069,
    "r": 0x006B,
    "s": 0x006D,
    "t": 0x006E,
    "u": 0x006F,
    "v": 0x0070,
    "w": 0x0071,
    "x": 0x0074,
    "y": 0x0075,
    "z": 0x0076,
    # Russian Cyrillic Glyphs (Uppercase)
    "А": 0x0009,
    "Б": 0x000A,
    "В": 0x000B,
    "Г": 0x000C,
    "Д": 0x000D,
    "Е": 0x000E,
    "Ё": 0x0008,
    "Ж": 0x000F,
    "З": 0x0010,
    "И": 0x0011,
    "Й": 0x0012,
    "К": 0x0013,
    "Л": 0x0014,
    "М": 0x0015,
    "Н": 0x0016,
    "О": 0x0018,
    "П": 0x0019,
    "Р": 0x001A,
    "С": 0x001B,
    "Т": 0x001C,
    "У": 0x001D,
    "Ф": 0x001E,
    "Х": 0x001F,
    "Ц": 0x0020,
    "Ч": 0x0021,
    "Ш": 0x0022,
    "Щ": 0x0023,
    "Ъ": 0x0024,
    "Ы": 0x0025,
    "Ь": 0x0026,
    "Э": 0x0027,
    "Ю": 0x0028,
    "Я": 0x0029,
    # Russian Cyrillic Glyphs (Lowercase)
    "а": 0x002A,
    "б": 0x002B,
    "в": 0x002C,
    "г": 0x002D,
    "д": 0x002E,
    "е": 0x002F,
    "ё": 0x0052,
    "ж": 0x0030,
    "з": 0x0032,
    "и": 0x0033,
    "й": 0x0034,
    "к": 0x0035,
    "л": 0x0036,
    "м": 0x0037,
    "н": 0x0038,
    "о": 0x0039,
    "п": 0x003B,
    "р": 0x003C,
    "с": 0x003D,
    "т": 0x003E,
    "у": 0x003F,
    "ф": 0x0041,
    "х": 0x0042,
    "ц": 0x0043,
    "ч": 0x0044,
    "ш": 0x0045,
    "щ": 0x0046,
    "ъ": 0x0047,
    "ы": 0x0049,
    "ь": 0x004C,
    "э": 0x004E,
    "ю": 0x0050,
    "я": 0x0051,
    # Typographic Punctuation
    "«": 0x0053,
    "»": 0x0054,
    "—": 0x0056,
    "…": 0x0057,
    "„": 0x0058,
    "“": 0x0059,
}


@dataclass(frozen=True)
class ArchiveEntry:
    index: int
    start_sector: int
    sector_count: int

    @property
    def offset(self) -> int:
        return self.start_sector * SECTOR_SIZE

    @property
    def size(self) -> int:
        return self.sector_count * SECTOR_SIZE

    def extract(self, archive: bytes) -> bytes:
        return archive[self.offset : self.offset + self.size]


@dataclass
class InspectionEntryInfo:
    entry_index: int
    ptr_table_offset: int
    ptr_table_end: int
    num_pointers: int
    pointers: list[int]
    pointer_offsets: list[int]
    min_str_offset: int
    max_str_offset: int
    trailing_block: bytes
    offset_2c_rel: int
    offset_30_rel: int
    extracted_strings: list[str]


@dataclass
class InspectionPatchResult:
    entry_index: int
    allocated_size: int
    used_size: int
    free_margin: int
    strings_count: int
    pointer_table_offset: int


def load_charmap(path: str | Path | None = None) -> dict[str, int]:
    """Load character-to-glyph mapping dictionary from JSON, or return DEFAULT_CHARMAP."""
    if path is not None:
        p = Path(path)
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if "characters" in data:
                cm = dict(DEFAULT_CHARMAP)
                for item in data["characters"]:
                    cm[item["text"]] = int(item["glyph"], 16)
                return cm
            elif isinstance(data, dict):
                return {k: int(v, 16) if isinstance(v, str) and v.startswith("0x") else int(v) for k, v in data.items()}

    # Try default workspace path
    default_build_map = PATCH_REPO / "localization-work" / "ru" / "build" / "glyph_map.json"
    if default_build_map.is_file():
        try:
            data = json.loads(default_build_map.read_text(encoding="utf-8"))
            if "characters" in data:
                cm = dict(DEFAULT_CHARMAP)
                for item in data["characters"]:
                    cm[item["text"]] = int(item["glyph"], 16)
                return cm
        except Exception:
            pass

    return dict(DEFAULT_CHARMAP)


def encode_string(
    text: str,
    charmap: dict[str, int],
    terminator: int = CHAR_STRING_TERMINATOR,
) -> bytes:
    """Encode a Unicode string into Slayers Royal 16-bit big-endian words.

    Supports Unicode characters via charmap, newline '\\n' as CHAR_NEWLINE (0x00FE),
    form-feed '\\f' as CHAR_PAGE_CONTINUE (0x00FD), and hex escapes '<XXXX>' (e.g. '<0007>').
    """
    words: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "<" and i + 5 < n and text[i + 5] == ">":
            hex_part = text[i + 1 : i + 5]
            try:
                val = int(hex_part, 16)
                words.append(val)
                i += 6
                continue
            except ValueError:
                pass

        ch = text[i]
        if ch == "\n":
            words.append(CHAR_NEWLINE)
        elif ch == "\f":
            words.append(CHAR_PAGE_CONTINUE)
        elif ch == "\r":
            i += 1
            continue
        elif ch in charmap:
            words.append(charmap[ch])
        else:
            raise KeyError(
                f"Character {ch!r} (U+{ord(ch):04X}) not found in charmap"
            )
        i += 1
    words.append(terminator)
    return struct.pack(f">{len(words)}H", *words)


def decode_string(
    words: Sequence[int],
    reverse_charmap: dict[int, str],
) -> str:
    """Decode a sequence of 16-bit words into a Unicode string."""
    chars: list[str] = []
    for w in words:
        if w == CHAR_NEWLINE:
            chars.append("\n")
        elif w in (CHAR_PAGE_CONTINUE, CHAR_STRING_TERMINATOR):
            break
        elif w in reverse_charmap:
            chars.append(reverse_charmap[w])
        elif 32 <= w <= 126:
            chars.append(chr(w))
        else:
            chars.append(f"<{w:04X}>")
    return "".join(chars)


def parse_inspection_entry(
    entry_bytes: bytes,
    entry_index: int = 0,
    charmap: dict[str, int] | None = None,
) -> InspectionEntryInfo:
    """Parse a room inspection entry's pointer table, strings, and header pointers."""
    if len(entry_bytes) < 0x0100:
        raise ValueError(f"Entry {entry_index:#05x} too short ({len(entry_bytes)} bytes)")

    ptr_table_val = struct.unpack_from(">I", entry_bytes, HDR_PTR_TABLE_OFFSET)[0]
    if ptr_table_val < RAM_BASE:
        raise ValueError(
            f"Entry {entry_index:#05x} has invalid pointer table header at 0x0024: {ptr_table_val:#010x}"
        )
    ptr_table_offset = ptr_table_val - RAM_BASE

    val_2c = struct.unpack_from(">I", entry_bytes, HDR_TRAILING_PTR_1)[0] - RAM_BASE
    val_30 = struct.unpack_from(">I", entry_bytes, HDR_TRAILING_PTR_2)[0] - RAM_BASE
    ptr_table_end = min(val_2c, val_30)

    if ptr_table_end <= ptr_table_offset or (ptr_table_end - ptr_table_offset) % 4 != 0:
        raise ValueError(
            f"Entry {entry_index:#05x} invalid pointer table range: 0x{ptr_table_offset:04X}..0x{ptr_table_end:04X}"
        )

    num_pointers = (ptr_table_end - ptr_table_offset) // 4
    pointers = [
        struct.unpack_from(">I", entry_bytes, ptr_table_offset + i * 4)[0]
        for i in range(num_pointers)
    ]
    pointer_offsets = [p - RAM_BASE for p in pointers]

    for p_off in pointer_offsets:
        if p_off < 0 or p_off >= len(entry_bytes):
            raise ValueError(
                f"Entry {entry_index:#05x} pointer offset 0x{p_off:04X} out of bounds"
            )

    min_str_offset = min(pointer_offsets)
    max_str_offset = max(pointer_offsets)

    # Trailing data block immediately follows the pointer table
    nz_indices = [i for i, b in enumerate(entry_bytes) if b != 0]
    last_nz = max(nz_indices) if nz_indices else ptr_table_end
    trailing_block = entry_bytes[ptr_table_end : last_nz + 1]

    # Relative offsets of 0x002C and 0x0030 relative to ptr_table_end
    offset_2c_rel = val_2c - ptr_table_end
    offset_30_rel = val_30 - ptr_table_end

    # Extract strings
    reverse_map = {v: k for k, v in (charmap or DEFAULT_CHARMAP).items()}
    extracted_strings: list[str] = []
    for p_off in pointer_offsets:
        words: list[int] = []
        curr = p_off
        while curr + 2 <= len(entry_bytes):
            w = struct.unpack_from(">H", entry_bytes, curr)[0]
            curr += 2
            words.append(w)
            if w in (CHAR_STRING_TERMINATOR, CHAR_PAGE_CONTINUE):
                break
        extracted_strings.append(decode_string(words, reverse_map))

    return InspectionEntryInfo(
        entry_index=entry_index,
        ptr_table_offset=ptr_table_offset,
        ptr_table_end=ptr_table_end,
        num_pointers=num_pointers,
        pointers=pointers,
        pointer_offsets=pointer_offsets,
        min_str_offset=min_str_offset,
        max_str_offset=max_str_offset,
        trailing_block=trailing_block,
        offset_2c_rel=offset_2c_rel,
        offset_30_rel=offset_30_rel,
        extracted_strings=extracted_strings,
    )


def _encode_entry_payload(
    info: InspectionEntryInfo,
    strings: Sequence[str],
    charmap: dict[str, int],
) -> tuple[bytearray, bytearray, int, int]:
    """Encode string block and pointer table for an inspection entry."""
    target_to_new_offset: dict[int, int] = {}
    new_pointer_offsets: list[int] = []
    curr_offset = info.min_str_offset
    string_payload = bytearray()

    for orig_target, text in zip(info.pointer_offsets, strings):
        if orig_target in target_to_new_offset:
            new_pointer_offsets.append(target_to_new_offset[orig_target])
        else:
            enc = encode_string(text, charmap)
            target_to_new_offset[orig_target] = curr_offset
            new_pointer_offsets.append(curr_offset)
            string_payload.extend(enc)
            curr_offset += len(enc)

    new_pt_offset = (curr_offset + 3) & ~3
    pad_len = new_pt_offset - curr_offset
    string_payload.extend(b"\x00" * pad_len)

    pointer_table_payload = bytearray()
    for p_off in new_pointer_offsets:
        pointer_table_payload.extend(struct.pack(">I", RAM_BASE + p_off))

    new_pt_end = new_pt_offset + len(pointer_table_payload)
    new_data_end = new_pt_end + len(info.trailing_block)
    return string_payload, pointer_table_payload, new_pt_offset, new_data_end


def rebuild_inspection_entry(
    original_bytes: bytes,
    translated_strings: Sequence[str],
    charmap: dict[str, int] | None = None,
    entry_index: int = 0,
    room_name: str | None = None,
    progressive_shorten: bool = True,
    allocated_size: int | None = None,
) -> tuple[bytes, InspectionPatchResult]:
    """Rebuild an inspection entry with new translated strings and updated pointers.

    Enforces sector budget (rebuilt_size <= allocated). If rebuilt data exceeds
    allocated capacity and progressive_shorten is True, automatically shortens
    multi-line strings until it fits within sector budget.

    Returns:
        (rebuilt_entry_bytes, InspectionPatchResult)
    """
    cm = charmap if charmap is not None else DEFAULT_CHARMAP
    info = parse_inspection_entry(original_bytes, entry_index=entry_index, charmap=cm)
    allocated = allocated_size if allocated_size is not None else len(original_bytes)

    if len(translated_strings) != info.num_pointers:
        raise ValueError(
            f"Entry {entry_index:#05x} requires {info.num_pointers} strings, but got {len(translated_strings)}"
        )

    working_strings = list(translated_strings)
    (
        string_payload,
        pointer_table_payload,
        new_pt_offset,
        new_data_end,
    ) = _encode_entry_payload(info, working_strings, cm)

    # Sector budget enforcement with progressive condensation
    if new_data_end > allocated and progressive_shorten and shorten_lines is not None:
        # Build map from orig_target to list of string indices to keep duplicates synchronized
        target_to_indices: dict[int, list[int]] = {}
        for i, target in enumerate(info.pointer_offsets):
            target_to_indices.setdefault(target, []).append(i)

        # Pass 1: Shorten strings with > 2 lines down to at most 2 lines (longest first)
        cand_targets_p1 = [
            t
            for t, indices in target_to_indices.items()
            if len(working_strings[indices[0]].splitlines()) > 2
        ]
        cand_targets_p1.sort(
            key=lambda t: len(working_strings[target_to_indices[t][0]]), reverse=True
        )
        for t in cand_targets_p1:
            indices = target_to_indices[t]
            shortened = shorten_lines(working_strings[indices[0]], max_lines=2)
            if shortened != working_strings[indices[0]]:
                for k in indices:
                    working_strings[k] = shortened
                (
                    string_payload,
                    pointer_table_payload,
                    new_pt_offset,
                    new_data_end,
                ) = _encode_entry_payload(info, working_strings, cm)
                if new_data_end <= allocated:
                    break

        # Pass 2: If still overflowing, shorten strings with > 1 line down to 1 line (longest first)
        if new_data_end > allocated:
            cand_targets_p2 = [
                t
                for t, indices in target_to_indices.items()
                if len(working_strings[indices[0]].splitlines()) > 1
            ]
            cand_targets_p2.sort(
                key=lambda t: len(working_strings[target_to_indices[t][0]]), reverse=True
            )
            for t in cand_targets_p2:
                indices = target_to_indices[t]
                shortened = shorten_lines(working_strings[indices[0]], max_lines=1)
                if shortened != working_strings[indices[0]]:
                    for k in indices:
                        working_strings[k] = shortened
                    (
                        string_payload,
                        pointer_table_payload,
                        new_pt_offset,
                        new_data_end,
                    ) = _encode_entry_payload(info, working_strings, cm)
                    if new_data_end <= allocated:
                        break

    if new_data_end > allocated:
        raise ValueError(
            f"Entry {entry_index:#05x} rebuilt data size ({new_data_end} bytes) "
            f"exceeds allocated capacity ({allocated} bytes) by {new_data_end - allocated} bytes"
        )

    new_pt_end = new_pt_offset + len(pointer_table_payload)
    trailing_block = info.trailing_block

    # Construct complete rebuilt entry
    rebuilt = bytearray(original_bytes[: info.min_str_offset])
    rebuilt.extend(string_payload)
    rebuilt.extend(pointer_table_payload)
    rebuilt.extend(trailing_block)
    rebuilt.extend(b"\x00" * (allocated - len(rebuilt)))

    # Update header pointers
    struct.pack_into(">I", rebuilt, HDR_PTR_TABLE_OFFSET, RAM_BASE + new_pt_offset)
    struct.pack_into(">I", rebuilt, HDR_TRAILING_PTR_1, RAM_BASE + new_pt_end + info.offset_2c_rel)
    struct.pack_into(">I", rebuilt, HDR_TRAILING_PTR_2, RAM_BASE + new_pt_end + info.offset_30_rel)

    # Optionally encode room name if specified (e.g. "БАР" at 0x0044)
    if room_name is not None and len(original_bytes) >= 0x0050:
        room_name_ptr = struct.unpack_from(">I", original_bytes, HDR_ROOM_NAME_PTR)[0]
        if room_name_ptr >= RAM_BASE:
            rn_offset = room_name_ptr - RAM_BASE
            rn_enc = encode_string(room_name, cm)
            # Ensure it fits in the room name slot without colliding with subsequent structures
            next_hdr = struct.unpack_from(">I", original_bytes, 0x0008)[0] - RAM_BASE
            if rn_offset + len(rn_enc) <= next_hdr:
                rebuilt[rn_offset : rn_offset + len(rn_enc)] = rn_enc

    result = InspectionPatchResult(
        entry_index=entry_index,
        allocated_size=allocated,
        used_size=new_data_end,
        free_margin=allocated - new_data_end,
        strings_count=len(working_strings),
        pointer_table_offset=new_pt_offset,
    )
    return bytes(rebuilt), result

def read_unt_index(archive_bytes: bytes) -> list[ArchiveEntry]:
    """Parse UNT entry allocation table from sector 0."""
    if len(archive_bytes) % SECTOR_SIZE != 0:
        raise ValueError("Archive is not sector aligned")
    entries: list[ArchiveEntry] = []
    expected = 1
    for offset in range(0, SECTOR_SIZE, 4):
        start = int.from_bytes(archive_bytes[offset : offset + 2], "little")
        count = int.from_bytes(archive_bytes[offset + 2 : offset + 4], "little")
        if start != expected or count == 0:
            break
        entries.append(ArchiveEntry(len(entries), start, count))
        expected += count
    return entries


def patch_unt_entry(
    archive_bytes: bytearray,
    entry_index: int,
    payload: bytes,
) -> tuple[int, int, int]:
    """Inject payload into a UNT entry, verifying sector limits and padding with zeros.

    Returns:
        (offset, allocated_size, payload_size)
    """
    entries = read_unt_index(archive_bytes)
    if entry_index >= len(entries):
        raise IndexError(
            f"Entry {entry_index:#05x} out of range (archive has {len(entries)} entries)"
        )
    entry = entries[entry_index]
    allocated = entry.size
    if len(payload) > allocated:
        raise ValueError(
            f"Entry {entry_index:#05x} payload ({len(payload)} bytes) exceeds allocated budget ({allocated} bytes)"
        )
    padded = payload.ljust(allocated, b"\x00")
    archive_bytes[entry.offset : entry.offset + allocated] = padded
    return entry.offset, allocated, len(payload)


def resolve_entry_translations(
    info: InspectionEntryInfo,
    translations_doc: dict[str, Any],
) -> tuple[list[str], str | None]:
    """Resolve the list of translated strings for an entry from the translations JSON.

    Supports both:
    1. Master Catalog schema (translations/room_inspection_ru.json):
       English string -> {"russian": "...", ...} or direct string.
    2. Specific Entries schema (data/inspection_ru.json):
       "entries" -> {"0x05D": {"strings": [...], "room_name": "..."}}
       and "common" -> {"orig": "trans"}.

    If a translation is non-empty, replaces the English string.
    If empty or not found, preserves the existing string unchanged.
    """
    entry_hex = f"0x{info.entry_index:03X}"
    entry_hex_lower = f"0x{info.entry_index:03x}"
    entry_dec = str(info.entry_index)

    entries_map = translations_doc.get("entries", {})
    entry_spec = (
        entries_map.get(entry_hex)
        or entries_map.get(entry_hex_lower)
        or entries_map.get(entry_dec)
        or entries_map.get(info.entry_index)
    )

    common_map = translations_doc.get("common", {})
    room_name: str | None = None

    if isinstance(entry_spec, list):
        candidate_strings = list(entry_spec)
    elif isinstance(entry_spec, dict):
        candidate_strings = list(entry_spec.get("strings", []))
        room_name = entry_spec.get("room_name")
    else:
        candidate_strings = []

    # If full list provided for this entry, use directly if all strings non-empty
    if len(candidate_strings) == info.num_pointers and all(candidate_strings):
        return candidate_strings, room_name

    def extract_ru(val: Any) -> str | None:
        if isinstance(val, dict):
            ru = val.get("russian")
            if isinstance(ru, str) and ru.strip():
                return ru
        elif isinstance(val, str) and val.strip():
            return val
        return None

    resolved: list[str] = []
    for idx, orig_text in enumerate(info.extracted_strings):
        if idx < len(candidate_strings) and candidate_strings[idx]:
            resolved.append(candidate_strings[idx])
        elif orig_text in translations_doc and extract_ru(translations_doc[orig_text]) is not None:
            resolved.append(extract_ru(translations_doc[orig_text]))
        elif orig_text in common_map and extract_ru(common_map[orig_text]) is not None:
            resolved.append(extract_ru(common_map[orig_text]))
        else:
            resolved.append(orig_text)

    return resolved, room_name


def patch_inspection_entries(
    prog_archive: bytearray,
    translations_doc: dict[str, Any],
    charmap: dict[str, int] | None = None,
    target_entries: Sequence[int] | None = None,
    all_rooms: bool = False,
    verbose: bool = False,
    progressive_shorten: bool = True,
    missing_rooms_doc: dict[str, Any] | None = None,
    source_prog: bytes | None = None,
) -> list[InspectionPatchResult]:
    """Patch room inspection entries in a PROG.UNT archive in memory."""
    cm = charmap if charmap is not None else DEFAULT_CHARMAP
    entries = read_unt_index(prog_archive)
    results: list[InspectionPatchResult] = []

    # Auto-load missing rooms doc if not explicitly provided and default file exists
    if missing_rooms_doc is None and DEFAULT_MISSING_ROOMS.is_file():
        try:
            missing_rooms_doc = json.loads(DEFAULT_MISSING_ROOMS.read_text(encoding="utf-8"))
        except Exception:
            missing_rooms_doc = None

    # Auto-load source_prog if not explicitly provided and DEFAULT_SOURCE_BIN exists
    if source_prog is None and DEFAULT_SOURCE_BIN.is_file():
        try:
            source_prog = extract_prog_from_path(DEFAULT_SOURCE_BIN)
        except Exception:
            source_prog = None

    source_entries = read_unt_index(source_prog) if source_prog is not None else None

    if target_entries is not None:
        entry_indices = list(target_entries)
    elif all_rooms or "entries" not in translations_doc:
        # Batch mode: iterate over all room entries 0x059..0x0F8
        entry_indices = [
            idx for idx in range(ROOM_ENTRIES_START, min(ROOM_ENTRIES_END + 1, len(entries)))
        ]
    else:
        # Resolve target entries from JSON keys
        target_set: set[int] = set()
        for key in translations_doc.get("entries", {}):
            try:
                target_set.add(int(str(key), 16 if str(key).lower().startswith("0x") else 10))
            except ValueError:
                pass
        if missing_rooms_doc:
            for key in missing_rooms_doc:
                try:
                    target_set.add(int(str(key), 16 if str(key).lower().startswith("0x") else 10))
                except ValueError:
                    pass
        entry_indices = sorted(target_set)

    for entry_idx in entry_indices:
        if entry_idx >= len(entries):
            continue
        entry = entries[entry_idx]
        orig_bytes = entry.extract(prog_archive)
        if not any(orig_bytes):
            if target_entries is None or entry_idx not in target_entries:
                continue
            if source_prog is None:
                continue

        missing_strings = get_missing_room_strings(entry_idx, missing_rooms_doc)
        use_missing_rooms = False

        orig_info: InspectionEntryInfo | None = None
        try:
            orig_info = parse_inspection_entry(orig_bytes, entry_index=entry_idx, charmap=cm)
        except Exception:
            orig_info = None

        if missing_strings is not None:
            if orig_info is None:
                use_missing_rooms = True
            else:
                is_zeroed = not any(s.strip() for s in orig_info.extracted_strings)
                has_catalog_trans = False
                if not is_zeroed and translations_doc:
                    for s in orig_info.extracted_strings:
                        if s in translations_doc or s in translations_doc.get("common", {}):
                            has_catalog_trans = True
                            break
                if is_zeroed or not has_catalog_trans:
                    use_missing_rooms = True

        if use_missing_rooms:
            if source_prog is not None and source_entries is not None and entry_idx < len(source_entries):
                base_bytes = source_entries[entry_idx].extract(source_prog)
            else:
                base_bytes = orig_bytes

            try:
                base_info = parse_inspection_entry(base_bytes, entry_index=entry_idx, charmap=cm)
            except Exception:
                continue

            rebuilt_bytes, result = rebuild_inspection_entry(
                base_bytes,
                missing_strings,
                charmap=cm,
                entry_index=entry_idx,
                allocated_size=entry.size,
                progressive_shorten=progressive_shorten,
            )
            patch_unt_entry(prog_archive, entry_idx, rebuilt_bytes)
            results.append(result)

            if verbose:
                print(
                    f"  Entry {result.entry_index:#05x} (omitted room): {result.strings_count} strings, "
                    f"{result.used_size}/{result.allocated_size} bytes (margin: {result.free_margin} bytes)"
                )
            continue

        if orig_info is None:
            continue

        translated_strings, room_name = resolve_entry_translations(orig_info, translations_doc)
        rebuilt_bytes, result = rebuild_inspection_entry(
            orig_bytes,
            translated_strings,
            charmap=cm,
            entry_index=entry_idx,
            room_name=room_name,
            allocated_size=entry.size,
            progressive_shorten=progressive_shorten,
        )

        patch_unt_entry(prog_archive, entry_idx, rebuilt_bytes)
        results.append(result)

        if verbose:
            print(
                f"  Entry {result.entry_index:#05x}: {result.strings_count} strings, "
                f"{result.used_size}/{result.allocated_size} bytes (margin: {result.free_margin} bytes)"
            )

    return results


def read_sector(disc_path: Path, lba: int) -> bytes:
    """Read a single 2048-byte user sector from a raw 2352-byte/sector BIN image."""
    with disc_path.open("rb") as f:
        f.seek(lba * RAW_SECTOR_SIZE + USER_OFFSET)
        return f.read(USER_SIZE)


def read_extent(disc_path: Path, lba: int, size: int) -> bytes:
    """Read an extent of arbitrary byte size from raw CD-ROM 2352 sectors."""
    sectors = (size + USER_SIZE - 1) // USER_SIZE
    with disc_path.open("rb") as f:
        buf = bytearray()
        for s in range(sectors):
            f.seek((lba + s) * RAW_SECTOR_SIZE + USER_OFFSET)
            buf.extend(f.read(USER_SIZE))
        return bytes(buf[:size])


def parse_iso_dir(disc_path: Path, lba: int, size: int) -> dict[str, tuple[int, int]]:
    """Parse ISO9660 directory records returning {filename: (extent_lba, size)}."""
    data = read_extent(disc_path, lba, size)
    pos = 0
    records: dict[str, tuple[int, int]] = {}
    while pos < size:
        length = data[pos]
        if length == 0:
            pos = ((pos // USER_SIZE) + 1) * USER_SIZE
            continue
        record = data[pos : pos + length]
        extent_lba = struct.unpack_from("<I", record, 2)[0]
        extent_size = struct.unpack_from("<I", record, 10)[0]
        name_len = record[32]
        name = record[33 : 33 + name_len].decode("ascii", errors="replace")
        records[name.split(";")[0]] = (extent_lba, extent_size)
        pos += length
    return records


def patch_disc_image(
    disc_path: Path,
    translations_doc: dict[str, Any],
    charmap: dict[str, int] | None = None,
    target_entries: Sequence[int] | None = None,
    all_rooms: bool = False,
    verbose: bool = False,
    progressive_shorten: bool = True,
    missing_rooms_doc: dict[str, Any] | None = None,
    source_prog: bytes | None = None,
) -> list[InspectionPatchResult]:
    """Patch PROG.UNT directly within a PS1 CD-ROM BIN image with EDC/ECC repair."""
    if replace_extent_in_place is None:
        raise RuntimeError("localization.disc.replace_extent_in_place is required for BIN patching")

    pvd = read_sector(disc_path, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(disc_path, root_lba, root_size)

    if "PROG.UNT" not in root_dir:
        raise ValueError(f"PROG.UNT not found in ISO root directory of {disc_path}")

    prog_lba, prog_size = root_dir["PROG.UNT"]
    prog_archive = bytearray(read_extent(disc_path, prog_lba, prog_size))

    results = patch_inspection_entries(
        prog_archive,
        translations_doc,
        charmap=charmap,
        target_entries=target_entries,
        all_rooms=all_rooms,
        verbose=verbose,
        progressive_shorten=progressive_shorten,
        missing_rooms_doc=missing_rooms_doc,
        source_prog=source_prog,
    )

    replace_extent_in_place(disc_path, prog_lba, bytes(prog_archive))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Translate and patch room inspection entries for Slayers Royal PS1."
    )
    default_trans = REPO_ROOT / "translations" / "room_inspection_ru.json"
    if not default_trans.is_file():
        default_trans = REPO_ROOT / "data" / "inspection_ru.json"
    parser.add_argument("--bin", type=Path, help="Path to PS1 CD-ROM BIN image to patch")
    parser.add_argument("--prog", type=Path, help="Path to standalone PROG.UNT archive")
    parser.add_argument(
        "--translations",
        type=Path,
        default=default_trans,
        help="Path to room_inspection_ru.json or inspection_ru.json",
    )
    parser.add_argument(
        "--missing-rooms",
        type=Path,
        default=DEFAULT_MISSING_ROOMS if DEFAULT_MISSING_ROOMS.is_file() else None,
        help="Path to missing_rooms_jp_ru.json containing translations for omitted rooms",
    )
    parser.add_argument(
        "--source-bin",
        "--source-prog",
        dest="source_bin",
        type=Path,
        default=DEFAULT_SOURCE_BIN if DEFAULT_SOURCE_BIN.is_file() else None,
        help="Path to Japanese source BIN (sr.bin) or PROG.UNT archive for fallback pointer layouts",
    )
    parser.add_argument("--charmap", type=Path, help="Path to custom glyph_map.json")
    parser.add_argument(
        "--entry",
        type=str,
        help="Target entry to patch or inspect (hex e.g. 0x05D or decimal)",
    )
    parser.add_argument(
        "--all-rooms",
        "--batch",
        action="store_true",
        help="Batch patch all room inspection entries (0x059..0x0F8)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="Dump strings from target entry instead of patching",
    )
    parser.add_argument("--output", type=Path, help="Optional output path for standalone PROG.UNT")

    args = parser.parse_args()

    charmap = load_charmap(args.charmap)

    # Resolve target entry index if specified
    target_entry_idx: int | None = None
    if args.entry:
        target_entry_idx = int(args.entry, 16 if args.entry.lower().startswith("0x") else 10)

    # Handle Dump operation
    if args.dump:
        if not args.bin and not args.prog:
            parser.error("--dump requires either --bin or --prog")
        if target_entry_idx is None:
            target_entry_idx = 0x05D  # Default to 0x05D Lakewood Tavern

        if args.prog:
            archive_data = args.prog.read_bytes()
        else:
            assert args.bin is not None
            pvd = read_sector(args.bin, 16)
            root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
            root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
            root_dir = parse_iso_dir(args.bin, root_lba, root_size)
            prog_lba, prog_size = root_dir["PROG.UNT"]
            archive_data = read_extent(args.bin, prog_lba, prog_size)

        entries = read_unt_index(archive_data)
        if target_entry_idx >= len(entries):
            print(f"Entry {target_entry_idx:#05x} out of bounds")
            return 1

        entry_bytes = entries[target_entry_idx].extract(archive_data)
        info = parse_inspection_entry(entry_bytes, entry_index=target_entry_idx, charmap=charmap)
        print(f"=== Room Inspection Entry {target_entry_idx:#05x} ===")
        print(f"Pointer Table: 0x{info.ptr_table_offset:04X}..0x{info.ptr_table_end:04X} ({info.num_pointers} pointers)")
        print(f"String Region: 0x{info.min_str_offset:04X}..0x{info.max_str_offset:04X}")
        print(f"Trailing Data: {len(info.trailing_block)} bytes (2c_rel={info.offset_2c_rel}, 30_rel={info.offset_30_rel})")
        print("\nStrings:")
        for idx, (p_off, s) in enumerate(zip(info.pointer_offsets, info.extracted_strings)):
            print(f"  [{idx:02d}] (0x{p_off:04X}): {repr(s)}")
        return 0

    # Load translations document
    if not args.translations.is_file():
        print(f"Translations file not found: {args.translations}", file=sys.stderr)
        return 1
    translations_doc = json.loads(args.translations.read_text(encoding="utf-8"))

    target_entries = [target_entry_idx] if target_entry_idx is not None else None
    missing_rooms_doc: dict[str, Any] | None = None
    if args.missing_rooms and args.missing_rooms.is_file():
        missing_rooms_doc = json.loads(args.missing_rooms.read_text(encoding="utf-8"))

    source_prog: bytes | None = None
    if args.source_bin and args.source_bin.is_file():
        source_prog = extract_prog_from_path(args.source_bin)


    # Handle BIN image patching
    if args.bin:
        print(f"Patching disc image: {args.bin}")
        results = patch_disc_image(
            args.bin,
            translations_doc,
            charmap=charmap,
            target_entries=target_entries,
            all_rooms=args.all_rooms,
            verbose=args.verbose,
            missing_rooms_doc=missing_rooms_doc,
            source_prog=source_prog,
        )
        print(f"Successfully patched {len(results)} inspection entries in {args.bin}:")
        if not args.verbose:
            for r in results[:5]:
                print(
                    f"  Entry {r.entry_index:#05x}: {r.strings_count} strings, "
                    f"{r.used_size}/{r.allocated_size} bytes (margin: {r.free_margin} bytes)"
                )
            if len(results) > 5:
                print(f"  ... and {len(results) - 5} more entries.")
        return 0

    # Handle standalone PROG.UNT patching
    if args.prog:
        print(f"Patching PROG.UNT archive: {args.prog}")
        archive = bytearray(args.prog.read_bytes())
        results = patch_inspection_entries(
            archive,
            translations_doc,
            charmap=charmap,
            target_entries=target_entries,
            all_rooms=args.all_rooms,
            verbose=args.verbose,
            missing_rooms_doc=missing_rooms_doc,
            source_prog=source_prog,
        )
        out_path = args.output if args.output else args.prog
        out_path.write_bytes(archive)
        print(f"Successfully patched {len(results)} inspection entries -> {out_path}:")
        if not args.verbose:
            for r in results[:5]:
                print(
                    f"  Entry {r.entry_index:#05x}: {r.strings_count} strings, "
                    f"{r.used_size}/{r.allocated_size} bytes (margin: {r.free_margin} bytes)"
                )
            if len(results) > 5:
                print(f"  ... and {len(results) - 5} more entries.")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
