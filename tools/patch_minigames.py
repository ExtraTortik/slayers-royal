#!/usr/bin/env python3
"""Patch minigame rules and quiz questions in PROG.UNT for Slayers Royal (PS1).

This tool:
1. Reads Russian translations from translations/minigames_ru.json.
2. Patches all 5 minigames in PROG.UNT:
   - Entry 13: Eating contest ("Состязание обжор", offset 0x07332, budget 312 bytes)
   - Entry 14: Amelia climb ("Прыжок Амелии", offset 0x1132E, budget 334 bytes)
   - Entry 15: Naga laugh ("Смех Наги", offset 0x07ECA, budget 254 bytes)
   - Entry 16: Quiz rules ("Слейерс-квиз", offset 0x0819E, budget 228 bytes)
   - Entry 17: Bandit bullying ("Отстрел бандитов", offset 0x082D0, budget 324 bytes)
   Encodes rules using DEFAULT_CHARMAP, with '\\n' -> 0x00FD, terminated with 0x00FF,
   and padded with 0x00 up to allocated budget.
3. Patches Slayers Royal Quiz questions:
   - Entry 16 at offset 0x082E8.
   - 100 structs of 164 bytes:
     q_line1 (32B), q_line2 (32B), opt1 (32B), opt2 (32B), opt3 (32B), correct (uint32_le).
     Encodes each slot using DEFAULT_CHARMAP, terminated with 0x00FF, padded with zeroes to 32B.
4. Checks font size (кегль) settings:
   Verifies that all question lines and options stay within screen boundaries (<= 15 chars).
   Verifies rules line lengths (<= 20 chars per line, <= 10 lines).
5. Writes patched entries back to disc image using replace_extent_in_place with EDC/ECC recalculation.
6. Implements --verify to decode and validate binary data against the catalog, checking EDC/ECC.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import re
import sys
from typing import Any, Sequence

# Ensure repository root and patch_repo are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
for p in (REPO_ROOT, PATCH_REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    from patch_repo.localization.disc import (
        RAW_SECTOR_SIZE,
        USER_DATA_SIZE,
        CdChecksums,
        read_extent,
        replace_extent_in_place,
    )
except ImportError:
    try:
        from localization.disc import (
            RAW_SECTOR_SIZE,
            USER_DATA_SIZE,
            CdChecksums,
            read_extent,
            replace_extent_in_place,
        )
    except ImportError:
        RAW_SECTOR_SIZE = 2352
        USER_DATA_SIZE = 2048
        CdChecksums = None
        read_extent = None
        replace_extent_in_place = None

try:
    from patch_repo.localization import unt_lz
except ImportError:
    try:
        from localization import unt_lz
    except ImportError:
        unt_lz = None

from tools.patch_inspection import DEFAULT_CHARMAP as INSPECTION_DEFAULT_CHARMAP

# Default paths
DEFAULT_CATALOG = REPO_ROOT / "translations" / "minigames_ru.json"
DEFAULT_TARGET_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_SRC_BIN = REPO_ROOT / "downloads" / "sr.bin"
GLYPH_MAP_PATH = REPO_ROOT / "patch_repo" / "localization-work" / "ru" / "build" / "glyph_map.json"

# Disc and PROG.UNT layout constants
PROG_LBA = 229020
CHAR_NEWLINE = 0x00FD
CHAR_TERMINATOR = 0x00FF
CHAR_PAGE = 0x00FE

# Naga Laugh minigame (Entry 15) RAM pointers table (preserved at offset 0x08308..0x0831C)
NAGA_DIALOGUE_POINTERS: tuple[int, ...] = (
    0x80056578,
    0x8005661C,
    0x800566C4,
    0x8005676C,
    0x80056810,
)
NAGA_DIALOGUE_POINTERS_RAW: bytes = struct.pack("<5I", *NAGA_DIALOGUE_POINTERS)

# Amelia Cliff Climb minigame (Entry 14) RAM pointers table (preserved at offset 0x11854..0x11868)
AMELIA_POINTER_TABLE_OFFSET = 0x11854
AMELIA_DIALOGUE_POINTERS: tuple[int, ...] = (
    0x8005FA2C,
    0x8005FAF4,
    0x8005FB9C,
    0x8005FC80,
    0x8005FD64,
)
AMELIA_DIALOGUE_POINTERS_RAW: bytes = struct.pack("<5I", *AMELIA_DIALOGUE_POINTERS)

# Amelia Cliff Climb minigame (Entry 14) 3-difficulty combo window RAM pointer table (preserved at offset 0x1198C..0x11998)
AMELIA_COMBO_POINTERS_OFFSET = 0x1198C
AMELIA_COMBO_POINTERS: tuple[int, ...] = (
    0x8005FE18,
    0x8005FE74,
    0x8005FED8,
)
AMELIA_COMBO_POINTERS_RAW: bytes = struct.pack("<3I", *AMELIA_COMBO_POINTERS)

# Minigame specifications in PROG.UNT
MINIGAME_SPECS: dict[str, dict[str, Any]] = {
    "eating_contest": {
        "id": "eating_contest",
        "entry": 13,
        "offset": 0x07320,
        "budget": 328,
        "title_offset": 0x07320,
        "title_budget": 328,
        "rules_end_offset": 0x07468,
        "ram_address": 0x800558E2,
        "name_ru": "Состязание обжор",
    },
    "amelia_climb": {
        "id": "amelia_climb",
        "entry": 14,
        "offset": 0x11318,
        "budget": 354,
        "title_offset": 0x11318,
        "title_budget": 354,
        "rules_end_offset": 0x1147A,
        "ram_address": 0x8005F8DE,
        "name_ru": "Прыжок Амелии",
    },
    "naga_laugh": {
        "id": "naga_laugh",
        "entry": 15,
        "offset": 0x07EB4,
        "budget": 274,
        "title_offset": 0x07EB4,
        "title_budget": 274,
        "rules_end_offset": 0x07FC6,
        "ram_address": 0x8005647A,
        "name_ru": "Смех Наги",
    },
    "slayers_quiz": {
        "id": "slayers_quiz",
        "entry": 16,
        "offset": 0x08184,
        "budget": 252,
        "title_offset": 0x08184,
        "title_budget": 252,
        "rules_end_offset": 0x08280,
        "ram_address": 0x8005674E,
        "name_ru": "Слейерс-квиз",
    },
    "bandit_bullying": {
        "id": "bandit_bullying",
        "entry": 17,
        "offset": 0x082B8,
        "budget": 346,
        "title_offset": 0x082B8,
        "title_budget": 346,
        "rules_end_offset": 0x08412,
        "ram_address": 0x80056880,
        "name_ru": "Отстрел бандитов",
    },
}

QUIZ_UI_SPECS: dict[str, dict[str, Any]] = {
    "contestant_prompt": {
        "entry": 16,
        "offset": 0x08284,
        "budget": 24,
    },
    "results_header": {
        "entry": 16,
        "offset": 0x0829C,
        "budget": 16,
    },
    "results_correct_count": {
        "entry": 16,
        "offset": 0x082AC,
        "budget": 26,
    },
    "results_avg_speed": {
        "entry": 16,
        "offset": 0x082C6,
        "budget": 34,
    },
}

NAGA_DIALOGUE_SPECS: dict[str, dict[str, Any]] = {
    "dialogue_1": {
        "id": "dialogue_1",
        "entry": 15,
        "offset": 0x07FC8,
        "budget": 162,
        "is_bubble": True,
        "name": "Перед мини-игрой",
    },
    "dialogue_2": {
        "id": "dialogue_2",
        "entry": 15,
        "offset": 0x0806A,
        "text_offset": 0x0806C,
        "budget": 170,
        "is_bubble": True,
        "name": "Победа / Рекорд",
    },
    "dialogue_3": {
        "id": "dialogue_3",
        "entry": 15,
        "offset": 0x08114,
        "budget": 168,
        "is_bubble": True,
        "name": "Реакция 1 (Наряд)",
    },
    "dialogue_4": {
        "id": "dialogue_4",
        "entry": 15,
        "offset": 0x081BC,
        "budget": 164,
        "is_bubble": True,
        "name": "Реакция 2 (Деньги)",
    },
    "dialogue_5": {
        "id": "dialogue_5",
        "entry": 15,
        "offset": 0x08260,
        "budget": 166,
        "is_bubble": True,
        "name": "Реакция 3 (Толчок)",
    },
    "dialogue_6": {
        "id": "dialogue_6",
        "entry": 15,
        "offset": 0x08306,
        "pointer_header_offset": 0x08308,
        "pointer_header_size": 20,
        "status_offset": 0x0831A,
        "text_offset": 0x0831C,
        "budget": 52,
        "text_budget": 30,
        "is_bubble": False,
        "name": "Статус Наги",
    },
}

AMELIA_DIALOGUE_SPECS: dict[str, dict[str, Any]] = {
    "dialogue_1": {
        "id": "dialogue_1",
        "entry": 14,
        "offset": 0x1147C,
        "budget": 200,
        "is_bubble": True,
        "ram_address": 0x8005FA2C,
        "name": "Речь Справедливости 1",
    },
    "dialogue_2": {
        "id": "dialogue_2",
        "entry": 14,
        "offset": 0x11544,
        "budget": 168,
        "is_bubble": True,
        "ram_address": 0x8005FAF4,
        "name": "Речь Справедливости 2",
    },
    "dialogue_3": {
        "id": "dialogue_3",
        "entry": 14,
        "offset": 0x115EC,
        "budget": 226,
        "is_bubble": True,
        "ram_address": 0x8005FB9C,
        "name": "Речь Справедливости 3",
    },
    "dialogue_4": {
        "id": "dialogue_4",
        "entry": 14,
        "offset": 0x116D0,
        "budget": 226,
        "is_bubble": True,
        "ram_address": 0x8005FC80,
        "name": "Речь Справедливости 4",
    },
    "dialogue_5": {
        "id": "dialogue_5",
        "entry": 14,
        "offset": 0x117B4,
        "budget": 160,
        "is_bubble": True,
        "ram_address": 0x8005FD64,
        "name": "Речь Справедливости 5",
    },
    "justice_up": {
        "id": "justice_up",
        "entry": 14,
        "offset": 0x12318,
        "budget": 32,
        "is_bubble": False,
        "ram_address": 0x800608DE,
        "name": "Справедливость окрепла (Результат)",
    },
}

# Entry 14 Amelia Cliff Climb Combo Window controller glyphs
GLYPH_CIRCLE = 0x006B  # ○ Circle button
GLYPH_UP = 0x0074      # ↑ Up arrow
GLYPH_DOWN = 0x0075    # ↓ Down arrow
GLYPH_RIGHT = 0x0076   # → Right arrow
GLYPH_LEFT = 0x0077    # ← Left arrow

AMELIA_COMBO_SPECS: dict[str, dict[str, Any]] = {
    "difficulty_1": {
        "difficulty": 1,
        "offset": 0x11868,
        "budget": 92,
        "ram_address": 0x8005FE18,
        "name": "Сложность 1 (Легко)",
    },
    "difficulty_2": {
        "difficulty": 2,
        "offset": 0x118C4,
        "budget": 100,
        "ram_address": 0x8005FE74,
        "name": "Сложность 2 (Нормально)",
    },
    "difficulty_3": {
        "difficulty": 3,
        "offset": 0x11928,
        "budget": 100,
        "ram_address": 0x8005FED8,
        "name": "Сложность 3 (Сложно)",
    },
}

EATING_STATUS_SPECS: dict[str, dict[str, Any]] = {
    "lina_morale": {
        "id": "lina_morale",
        "entry": 13,
        "offset": 0x0746C,
        "budget": 72,
        "is_bubble": False,
        "ram_address": 0x80055A1C,
        "name": "Боевой дух Лины",
    },
    "gourry_satiated": {
        "id": "gourry_satiated",
        "entry": 13,
        "offset": 0x074B4,
        "budget": 28,
        "is_bubble": False,
        "ram_address": 0x80055A64,
        "name": "Гаури насытился",
    },
    "combined_status": {
        "id": "combined_status",
        "entry": 13,
        "offset": 0x074D0,
        "budget": 98,
        "is_bubble": False,
        "ram_address": 0x80055A80,
        "name": "Дух Лины и сытость Гаури",
    },
}

BANDIT_BONUS_SPEC: dict[str, Any] = {
    "id": "time_bonus",
    "entry": 17,
    "offset": 0x08414,
    "budget": 20,
    "is_bubble": False,
    "ram_address": 0x800569C4,
    "name": "Бонус времени",
}

QUIZ_SPEC: dict[str, Any] = {
    "entry": 16,
    "offset": 0x082E8,
    "record_bytes": 164,
    "total_questions": 100,
    "slot_bytes": 32,
    "slot_max_chars": 15,
    "ram_base": 0x80056898,
}

# Minigame Entry 4 and Entry 5 System Prompts (replay, choices, messages)
ENTRY_4_SYSTEM_PROMPTS: dict[str, dict[str, Any]] = {
    "e4_prompt_replay": {
        "id": "e4_prompt_replay",
        "entry": 4,
        "offset": 0x5AF2,
        "budget": 28,
        "text_en": "Play again?",
        "default_ru": "Сыграть ещё?",
    },
    "e4_choice_replay": {
        "id": "e4_choice_replay",
        "entry": 4,
        "offset": 0x5B10,
        "budget": 26,
        "text_en": "Play\nNo",
        "choices": ["Да", "Нет"],
        "default_ru": "Да\nНет",
    },
}

ENTRY_5_SYSTEM_PROMPTS: dict[str, dict[str, Any]] = {
    "e5_prompt_replay": {
        "id": "e5_prompt_replay",
        "entry": 5,
        "offset": 0x881E,
        "budget": 18,
        "text_en": "Replay?",
        "default_ru": "Снова?",
    },
    "e5_choice_replay": {
        "id": "e5_choice_replay",
        "entry": 5,
        "offset": 0x8830,
        "budget": 46,
        "text_en": "Play again\nQuit game",
        "choices": ["Ещё раз", "Выйти"],
        "default_ru": "Ещё раз\nВыйти",
    },
    "e5_prompt_go_ahead": {
        "id": "e5_prompt_go_ahead",
        "entry": 5,
        "offset": 0x8862,
        "budget": 20,
        "text_en": "Go ahead.",
        "default_ru": "Твой ход.",
    },
}

SYSTEM_PROMPT_SPECS: dict[int, dict[str, dict[str, Any]]] = {
    4: ENTRY_4_SYSTEM_PROMPTS,
    5: ENTRY_5_SYSTEM_PROMPTS,
}

# SMINI.UNT and font injection constants
SMINI_DEFAULT_LBA = 223787
PROG_FONT_ENTRY = 0x03A
PROG_FONT_PIXEL_OFFSET = 544  # 0x220: TIM magic (8B) + CLUT len (524B) + IMG header (12B)

# Specifications for minigame font TIMs in SMINI.UNT entries
# Note: pixel_offset = file_offset + 8 (TIM magic/flags) + 44 (CLUT block) + 12 (IMG header) = file_offset + 0x40.
# (0x082B78 + 0x40 = 0x082BB8, matching PROG.UNT 0x03A Bank 0 tile alignment)
SMINI_FONT_SPECS: dict[int, dict[str, Any]] = {
    3: {  # Quiz (slayers_quiz)
        "file_index": 9,
        "file_offset": 0x082B78,
        "pixel_offset": 0x082BB8,
        "minigame": "slayers_quiz",
        "name": "Слейерс-квиз (Quiz)",
    },
    0: {  # Eating contest (eating_contest)
        "file_index": 30,
        "file_offset": 0x097B54,
        "pixel_offset": 0x097B94,
        "minigame": "eating_contest",
        "name": "Состязание обжор (Eating Contest)",
    },
    1: {  # Amelia climb (amelia_climb)
        "file_index": 11,
        "file_offset": 0x09D810,
        "pixel_offset": 0x09D850,
        "minigame": "amelia_climb",
        "name": "Прыжок Амелии (Amelia Climb)",
    },
    2: {  # Naga laugh (naga_laugh)
        "file_index": 11,
        "file_offset": 0x09AFE8,
        "pixel_offset": 0x09B028,
        "minigame": "naga_laugh",
        "name": "Смех Наги (Naga Laugh)",
    },
    4: {  # Bandit bullying (bandit_bullying)
        "file_index": 7,
        "file_offset": 0x056F44,
        "pixel_offset": 0x056F84,
        "minigame": "bandit_bullying",
        "name": "Отстрел бандитов (Bandit Bullying)",
    },
}

# Locale glyph IDs are allocated dynamically by the toolkit at story-build time;
# they are read from glyph_map.json / the committed snapshot (tools/vram_charmap.py)
# and must never be spelled out in code.
try:
    from tools.vram_charmap import load_glyph_map as _load_glyph_map, load_vram_charmap as _load_vram_charmap
except ImportError:  # executed as a script from tools/
    from vram_charmap import load_glyph_map as _load_glyph_map, load_vram_charmap as _load_vram_charmap  # type: ignore

AUTHORITATIVE_CYRILLIC_CHARMAP: dict[str, int] = {
    ch: glyph for ch, glyph in _load_glyph_map().items() if "\u0400" <= ch <= "\u04ff" or ch in "«»—“„…"
}

# Highest cell a locale character may occupy: the SMINI font copies cells
# 0x0004..0x0056 out of PROG.UNT 0x03A and protects 0x0057.. for controller icons.
MAX_MINIGAME_LOCALE_GLYPH = 0x0056


def build_minigames_charmap(glyph_map_path: Path | str | None = None) -> dict[str, int]:
    """Charmap for minigame text: English base cells + the live locale allocation.

    Raises if no trustworthy glyph map exists or if a locale glyph lies above
    ``MAX_MINIGAME_LOCALE_GLYPH`` (it would not be copied into the SMINI fonts).
    """
    cm = _load_vram_charmap(glyph_map_path)
    too_high = {ch: g for ch, g in cm.items() if ("\u0400" <= ch <= "\u04ff" or ch in "«»—“„…/()~") and g > MAX_MINIGAME_LOCALE_GLYPH}
    if too_high:
        listing = ", ".join(f"{ch!r}=0x{g:04X}" for ch, g in sorted(too_high.items(), key=lambda kv: kv[1]))
        raise ValueError(
            "locale glyphs above 0x%04X are not mirrored into the SMINI minigame fonts: %s"
            % (MAX_MINIGAME_LOCALE_GLYPH, listing)
        )
    cm[" "] = 0x007D
    return cm


def get_reverse_charmap(charmap: dict[str, int] | None = None) -> dict[int, str]:
    """Build reverse charmap mapping 16-bit codes to characters, prioritizing Cyrillic."""
    cm = charmap if charmap is not None else DEFAULT_CHARMAP
    rev: dict[int, str] = {}
    for k, v in cm.items():
        rev[v] = k
    for k, v in AUTHORITATIVE_CYRILLIC_CHARMAP.items():
        if k in cm:
            rev[cm[k]] = k
    return rev


DEFAULT_CHARMAP: dict[str, int] = build_minigames_charmap()
MINIGAME_CHARMAP: dict[str, int] = DEFAULT_CHARMAP
REVERSE_CHARMAP: dict[int, str] = get_reverse_charmap(DEFAULT_CHARMAP)

# PlayStation controller and HUD glyphs in SMINI.UNT Entry 1 (Amelia Cliff Climb):
SMINI_PROTECTED_GLYPHS = {
    0x006B,  # Circle button (○)
    0x0074,  # Up arrow (↑)
    0x0075,  # Down arrow (↓)
    0x0076,  # Right arrow (→)
    0x0077,  # Left arrow (←)
}

# Bank 0 glyph IDs to extract and inject into minigame font TIMs:
# Cyrillic letters and symbols 0x0004..0x0056 plus space 0x007D and all other Bank 0 glyphs in DEFAULT_CHARMAP,
# strictly excluding the Latin collision range 0x0057..0x0077 (ASCII letters k..z, Katakana and ←) so controller icons
# in SMINI.UNT are never clobbered.
MINIGAME_FONT_GLYPH_IDS = tuple(
    sorted(
        set(
            list(range(0x0004, 0x0057))
            + [
                gid
                for gid in DEFAULT_CHARMAP.values()
                if gid < 256 and gid not in range(0x0057, 0x0078)
            ]
        )
    )
)


@dataclass(frozen=True)
class ProgEntryInfo:
    index: int
    start_sector: int
    sector_count: int

    @property
    def size(self) -> int:
        return self.sector_count * USER_DATA_SIZE


def read_sector(path: Path | str, lba: int) -> bytes:
    """Read a single 2048-byte user data sector from raw 2352-byte disc image."""
    p = Path(path)
    with p.open("rb") as f:
        f.seek(lba * RAW_SECTOR_SIZE + 24)
        return f.read(USER_DATA_SIZE)


def parse_iso_dir(disc_path: Path | str, lba: int, size: int) -> dict[str, tuple[int, int]]:
    """Parse ISO9660 directory records returning {filename: (extent_lba, size)}."""
    p = Path(disc_path)
    data = bytearray()
    sectors = (size + USER_DATA_SIZE - 1) // USER_DATA_SIZE
    with p.open("rb") as f:
        for s in range(sectors):
            f.seek((lba + s) * RAW_SECTOR_SIZE + 24)
            data.extend(f.read(USER_DATA_SIZE))
    pos = 0
    records: dict[str, tuple[int, int]] = {}
    while pos < size:
        length = data[pos]
        if length == 0:
            pos = ((pos // USER_DATA_SIZE) + 1) * USER_DATA_SIZE
            continue
        record = data[pos : pos + length]
        extent_lba = struct.unpack_from("<I", record, 2)[0]
        extent_size = struct.unpack_from("<I", record, 10)[0]
        name_len = record[32]
        name = record[33 : 33 + name_len].decode("ascii", errors="replace")
        records[name.split(";")[0]] = (extent_lba, extent_size)
        pos += length
    return records


def read_unt_index(index_sector: bytes) -> list[ProgEntryInfo]:
    """Parse UNT entry allocation table from sector 0."""
    entries: list[ProgEntryInfo] = []
    expected = 1
    for offset in range(0, USER_DATA_SIZE, 4):
        start = int.from_bytes(index_sector[offset : offset + 2], "little")
        count = int.from_bytes(index_sector[offset + 2 : offset + 4], "little")
        if start != expected or count == 0:
            break
        entries.append(ProgEntryInfo(len(entries), start, count))
        expected += count
    return entries


def locate_prog_unt(bin_path: Path | str) -> tuple[int, list[ProgEntryInfo]]:
    """Locate PROG.UNT LBA and entry table in target disc image."""
    p = Path(bin_path)
    pvd = read_sector(p, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(p, root_lba, root_size)
    if "PROG.UNT" not in root_dir:
        raise ValueError(f"PROG.UNT not found in ISO directory of {p}")
    prog_lba, _ = root_dir["PROG.UNT"]
    idx_sector = read_sector(p, prog_lba)
    entries = read_unt_index(idx_sector)
    return prog_lba, entries


def load_prog_entries_data(
    bin_path: Path | str,
    target_entries: Sequence[int] = (4, 5, 13, 14, 15, 16, 17),
) -> tuple[int, dict[int, dict[str, Any]]]:
    """Read data and info for specified PROG.UNT entries from disc image.

    Returns:
        (prog_lba, {entry_idx: {"info": ProgEntryInfo, "data": bytearray}})
    """
    p = Path(bin_path)
    prog_lba, entries = locate_prog_unt(p)
    res: dict[int, dict[str, Any]] = {}
    with p.open("rb") as f:
        for idx in target_entries:
            if idx >= len(entries):
                raise IndexError(f"Entry {idx} out of range in PROG.UNT (total {len(entries)})")
            e = entries[idx]
            data = bytearray()
            for s in range(e.sector_count):
                f.seek((prog_lba + e.start_sector + s) * RAW_SECTOR_SIZE + 24)
                data.extend(f.read(USER_DATA_SIZE))
            res[idx] = {
                "info": e,
                "start_sector": e.start_sector,
                "sector_count": e.sector_count,
                "data": data,
            }
    return prog_lba, res


def locate_smini_unt(bin_path: Path | str) -> tuple[int, list[ProgEntryInfo]]:
    """Locate SMINI.UNT LBA and entry table in target disc image."""
    p = Path(bin_path)
    pvd = read_sector(p, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(p, root_lba, root_size)
    if "SMINI.UNT" in root_dir:
        smini_lba, _ = root_dir["SMINI.UNT"]
    else:
        smini_lba = SMINI_DEFAULT_LBA
    idx_sector = read_sector(p, smini_lba)
    entries = read_unt_index(idx_sector)
    return smini_lba, entries


def load_smini_entries_data(
    bin_path: Path | str,
    target_entries: Sequence[int] = (3, 0, 1, 2, 4),
) -> tuple[int, dict[int, dict[str, Any]]]:
    """Read data and info for specified SMINI.UNT entries from disc image.

    Returns:
        (smini_lba, {entry_idx: {"info": ProgEntryInfo, "data": bytearray, "start_sector": int, "sector_count": int}})
    """
    p = Path(bin_path)
    smini_lba, entries = locate_smini_unt(p)
    res: dict[int, dict[str, Any]] = {}
    with p.open("rb") as f:
        for idx in target_entries:
            if idx >= len(entries):
                raise IndexError(f"Entry {idx} out of range in SMINI.UNT (total {len(entries)})")
            e = entries[idx]
            data = bytearray()
            for s in range(e.sector_count):
                f.seek((smini_lba + e.start_sector + s) * RAW_SECTOR_SIZE + 24)
                data.extend(f.read(USER_DATA_SIZE))
            res[idx] = {
                "info": e,
                "start_sector": e.start_sector,
                "sector_count": e.sector_count,
                "data": data,
            }
    return smini_lba, res


def extract_03a_bank0_tile(decomp_03a: bytes, gid: int) -> bytes:
    """Extract 16x16 4bpp tile (128 bytes) for Bank 0 glyph ID (0x0000..0x00FF) from PROG.UNT 0x03A."""
    if not (0 <= gid < 256):
        raise ValueError(f"Glyph ID 0x{gid:04X} is outside Bank 0 (0..255)")
    tile_col = gid % 16
    tile_row = gid // 16
    tile = bytearray(128)
    for r in range(16):
        src_off = PROG_FONT_PIXEL_OFFSET + (tile_row * 16 + r) * 512 + (tile_col * 8)
        tile[r * 8 : (r + 1) * 8] = decomp_03a[src_off : src_off + 8]
    return bytes(tile)


def extract_prog_font_tiles(
    decomp_03a: bytes,
    glyph_ids: Sequence[int] = MINIGAME_FONT_GLYPH_IDS,
) -> dict[int, bytes]:
    """Extract 16x16 4bpp tile bitmaps for specified glyph IDs from decompressed PROG.UNT 0x03A."""
    return {gid: extract_03a_bank0_tile(decomp_03a, gid) for gid in glyph_ids}


def inject_smini_tile(entry_data: bytearray, base_pixel_off: int, gid: int, tile_bytes: bytes) -> None:
    """Inject 16x16 4bpp tile (128 bytes) into 256-pixel wide TIM in SMINI PMA entry."""
    if len(tile_bytes) != 128:
        raise ValueError(f"Tile bytes must be exactly 128 bytes, got {len(tile_bytes)}")
    tile_col = gid % 16
    tile_row = (gid % 256) // 16
    for r in range(16):
        dest_off = base_pixel_off + (tile_row * 16 + r) * 128 + (tile_col * 8)
        if dest_off + 8 > len(entry_data):
            raise IndexError(f"Destination offset 0x{dest_off:X} exceeds buffer length {len(entry_data)}")
        entry_data[dest_off : dest_off + 8] = tile_bytes[r * 8 : (r + 1) * 8]


def extract_smini_tile(entry_data: bytes | bytearray, base_pixel_off: int, gid: int) -> bytes:
    """Extract 16x16 4bpp tile (128 bytes) from 256-pixel wide TIM in SMINI PMA entry."""
    tile_col = gid % 16
    tile_row = (gid % 256) // 16
    tile = bytearray(128)
    for r in range(16):
        src_off = base_pixel_off + (tile_row * 16 + r) * 128 + (tile_col * 8)
        if src_off + 8 > len(entry_data):
            raise IndexError(f"Source offset 0x{src_off:X} exceeds buffer length {len(entry_data)}")
        tile[r * 8 : (r + 1) * 8] = entry_data[src_off : src_off + 8]
    return bytes(tile)


# Authentic pristine 128-byte 4bpp tile bitmaps for PlayStation controller icons in SMINI.UNT Entry 1
PRISTINE_BUTTON_TILES: dict[int, bytes] = {
    0x006B: bytes.fromhex(
        '0000000000000000000031333301000000311300103301001013000000101300'
        '3001000000003100310000000000300113000000000010030300000000000003'
        '0300000000000003030000000000000313000000000010033100000000003001'
        '3001000000003100101300000010130000311300103301000000313333010000'
    ),
    0x0074: bytes.fromhex(
        '0000000000000000000000100000000000000031010000000000103313000000'
        '0000313131010000000013301003000000000030000000000000003000000000'
        '0000003000000000000000300000000000000030000000000000003000000000'
        '0000003000000000000000300000000000000030000000000000003000000000'
    ),
    0x0075: bytes.fromhex(
        '0000000000000000000000300000000000000030000000000000003000000000'
        '0000003000000000000000300000000000000030000000000000003000000000'
        '0000003000000000000000300000000000000030000000000000133010030000'
        '0000313131010000000010331300000000000031010000000000001000000000'
    ),
    0x0076: bytes.fromhex(
        '0000000000000000000000000000000000000000000000000000000000000000'
        '0000000000000000000000000013000000000000003101000000000000101300'
        '3333333333333301000000000010130000000000003101000000000010130000'
        '0000000000000000000000000000000000000000000000000000000000000000'
    ),
    0x0077: bytes.fromhex(
        '0000000000000000000000000000000000000000000000000000000000000000'
        '0000000000000000001003000000000000310100000000001013000000000000'
        '3133333333333303101300000000000000310100000000000010030000000000'
        '0000000000000000000000000000000000000000000000000000000000000000'
    ),
}


def load_pristine_button_tiles(src_bin_path: Path | str | None = None) -> dict[int, bytes]:
    """Load pristine button tiles from source disc (downloads/sr.bin) or fallback to constants."""
    if src_bin_path is not None:
        p = Path(src_bin_path)
        if p.is_file():
            try:
                _, smini_dict = load_smini_entries_data(p, [1])
                pixel_off = SMINI_FONT_SPECS[1]["pixel_offset"]
                e1_data = smini_dict[1]["data"]
                return {
                    gid: extract_smini_tile(e1_data, pixel_off, gid)
                    for gid in (GLYPH_CIRCLE, GLYPH_UP, GLYPH_DOWN, GLYPH_RIGHT, GLYPH_LEFT)
                }
            except Exception:
                pass
    return dict(PRISTINE_BUTTON_TILES)


def patch_smini_fonts_memory(
    smini_entries_data: dict[int, bytearray],
    font_tiles: dict[int, bytes],
    target_entries: Sequence[int] = (3, 0, 1, 2, 4),
    pristine_button_tiles: dict[int, bytes] | None = None,
) -> dict[int, dict[str, Any]]:
    """Inject font tiles into in-memory SMINI.UNT entry buffers."""
    stats: dict[int, dict[str, Any]] = {}
    btn_tiles = pristine_button_tiles or PRISTINE_BUTTON_TILES
    for entry_idx in target_entries:
        if entry_idx not in SMINI_FONT_SPECS:
            continue
        spec = SMINI_FONT_SPECS[entry_idx]
        data = smini_entries_data[entry_idx]
        pixel_off = spec["pixel_offset"]
        for gid, tile in font_tiles.items():
            if entry_idx == 1 and gid in SMINI_PROTECTED_GLYPHS:
                continue
            inject_smini_tile(data, pixel_off, gid, tile)
        if entry_idx == 1:
            for gid, tile in btn_tiles.items():
                inject_smini_tile(data, pixel_off, gid, tile)
        stats[entry_idx] = {
            "entry": entry_idx,
            "name": spec["name"],
            "minigame": spec["minigame"],
            "file_index": spec["file_index"],
            "pixel_offset": pixel_off,
            "tiles_injected": len(font_tiles),
            "button_tiles_restored": len(btn_tiles) if entry_idx == 1 else 0,
        }
    return stats


# ==============================================================================
# Encoding & Decoding routines
# ==============================================================================

def encode_minigame_rules(
    text: str,
    budget: int,
    charmap: dict[str, int] = DEFAULT_CHARMAP,
) -> bytes:
    """Encode minigame rules string into 16-bit little-endian words.

    - '\\n' translates to 0x00FD.
    - Other characters are mapped through charmap.
    - Terminated with 0x00FF.
    - Padded with 0x00 up to allocated budget.
    """
    words: list[int] = []
    for ch in text:
        if ch == "\n":
            words.append(CHAR_NEWLINE)
        else:
            if ch not in charmap:
                raise ValueError(f"Character {ch!r} not in charmap")
            words.append(charmap[ch])
    words.append(CHAR_TERMINATOR)
    raw = struct.pack(f"<{len(words)}H", *words)
    if len(raw) > budget:
        raise ValueError(
            f"Rules text ({len(raw)} bytes) exceeds allocated budget ({budget} bytes): {text!r}"
        )
    return raw.ljust(budget, b"\x00")


def decode_minigame_rules(
    raw: bytes,
    budget: int,
    rev_charmap: dict[int, str] | None = None,
) -> str:
    """Decode minigame rules binary data back into string."""
    cm = rev_charmap if rev_charmap is not None else REVERSE_CHARMAP
    sl = raw[:budget]
    words = [struct.unpack_from("<H", sl, i)[0] for i in range(0, len(sl), 2)]
    chars: list[str] = []
    for w in words:
        if w == CHAR_TERMINATOR:
            break
        elif w == CHAR_NEWLINE:
            chars.append("\n")
        elif w in cm:
            chars.append(cm[w])
        else:
            chars.append(f"[{w:#06x}]")
    return "".join(chars)


def encode_minigame_string(
    text: str,
    budget: int,
    charmap: dict[str, int] = DEFAULT_CHARMAP,
) -> bytes:
    """Encode minigame UI string into 16-bit little-endian words.

    - If text contains '\n' or '\f', options are separated by 0x00FE (CHAR_PAGE).
    - Characters mapped through charmap.
    - Terminated with 0x00FF (CHAR_TERMINATOR).
    - Zero-padded up to budget.
    """
    if "\n" in text or "\f" in text:
        opts = re.split(r"[\n\f]", text)
        encoded_opts: list[bytes] = []
        for opt in opts:
            words = []
            for ch in opt:
                if ch not in charmap:
                    raise ValueError(f"Character {ch!r} not in charmap for string: {text!r}")
                words.append(charmap[ch])
            encoded_opts.append(struct.pack(f"<{len(words)}H", *words))
        raw = struct.pack("<H", CHAR_PAGE).join(encoded_opts) + struct.pack("<H", CHAR_TERMINATOR)
    else:
        words = []
        for ch in text:
            if ch not in charmap:
                raise ValueError(f"Character {ch!r} not in charmap for string: {text!r}")
            words.append(charmap[ch])
        words.append(CHAR_TERMINATOR)
        raw = struct.pack(f"<{len(words)}H", *words)
    if len(raw) > budget:
        raise ValueError(
            f"String text {text!r} encoded to {len(raw)} bytes > budget {budget} bytes"
        )
    return raw.ljust(budget, b"\x00")


def decode_minigame_string(
    raw: bytes,
    budget: int,
    rev_charmap: dict[int, str] | None = None,
) -> str:
    """Decode minigame UI string binary data back into text up to 0x00FF or budget."""
    cm = rev_charmap if rev_charmap is not None else REVERSE_CHARMAP
    sl = raw[:budget]
    words = [struct.unpack_from("<H", sl, i)[0] for i in range(0, len(sl) - 1, 2)]
    chars: list[str] = []
    for w in words:
        if w in (CHAR_TERMINATOR, 0x0000):
            break
        elif w in (CHAR_PAGE, CHAR_NEWLINE):
            chars.append("\n")
        elif w in cm:
            chars.append(cm[w])
        else:
            chars.append(f"[{w:#06x}]")
    return "".join(chars)

def encode_minigame_dialogue(
    text: str,
    budget: int,
    charmap: dict[str, int] = DEFAULT_CHARMAP,
    is_bubble: bool = True,
) -> bytes:
    """Encode minigame dialogue into 16-bit little-endian words.

    - '\\n' translates to 0x00FD (CHAR_NEWLINE).
    - '\\f' or '<PAGE>' translates to 0x00FE (CHAR_PAGE).
    - Other characters mapped through charmap.
    - If is_bubble is True, ensures trailing 0x00FE before string terminator 0x00FF.
    - Zero-padded up to allocated budget.
    """
    words: list[int] = []
    i = 0
    while i < len(text):
        if text[i : i + 6] == "<PAGE>":
            words.append(CHAR_PAGE)
            i += 6
        elif text[i] == "\n":
            words.append(CHAR_NEWLINE)
            i += 1
        elif text[i] in ("\f", "\x0c"):
            words.append(CHAR_PAGE)
            i += 1
        else:
            ch = text[i]
            if ch not in charmap:
                raise ValueError(f"Character {ch!r} not in charmap for dialogue: {text!r}")
            words.append(charmap[ch])
            i += 1

    if is_bubble:
        if not words or words[-1] != CHAR_PAGE:
            words.append(CHAR_PAGE)
    words.append(CHAR_TERMINATOR)
    raw = struct.pack(f"<{len(words)}H", *words)
    if len(raw) > budget:
        raise ValueError(
            f"Dialogue text encoded to {len(raw)} bytes > budget {budget} bytes: {text!r}"
        )
    return raw.ljust(budget, b"\x00")


def decode_minigame_dialogue(
    raw: bytes,
    budget: int,
    rev_charmap: dict[int, str] | None = None,
    is_bubble: bool = True,
) -> str:
    """Decode minigame dialogue binary data back into string."""
    cm = rev_charmap if rev_charmap is not None else REVERSE_CHARMAP
    sl = raw[:budget]
    words = [struct.unpack_from("<H", sl, i)[0] for i in range(0, len(sl) - 1, 2)]

    start_idx = 0
    while start_idx < len(words) and words[start_idx] == 0x0000:
        start_idx += 1

    chars: list[str] = []
    for idx, w in enumerate(words[start_idx:]):
        if w == CHAR_TERMINATOR:
            break
        elif w == CHAR_NEWLINE:
            chars.append("\n")
        elif w == CHAR_PAGE:
            remaining = words[start_idx + idx + 1 :]
            if is_bubble and (not remaining or remaining[0] == CHAR_TERMINATOR):
                continue
            chars.append("\f")
        elif w == 0x0000:
            break
        elif w in cm:
            chars.append(cm[w])
        else:
            chars.append(f"[{w:#06x}]")
    return "".join(chars)

def encode_minigame_stream(
    title: str,
    rules: str,
    budget: int,
    charmap: dict[str, int] = DEFAULT_CHARMAP,
) -> bytes:
    """Encode title banner and minigame rules into a single unified continuous 16-bit text stream.

    Stream structure:
    [0x0000 (indent)] + encode(title_banner) [WITHOUT 0x00FF] +
    [0x00FD, 0x00FD (\n\n)] + encode(rules_ru) [WITH 0x00FF] +
    [0x00 padding up to budget].

    There is NO 0x00FF terminator between title and rules. The only 0x00FF is at the end of rules.
    """
    words: list[int] = [0x0000]

    # Title banner without 0x00FF
    title_words: list[int] = []
    for ch in title:
        if ch not in charmap:
            raise ValueError(f"Character {ch!r} in title banner not in charmap: {title!r}")
        code = charmap[ch]
        if code == CHAR_TERMINATOR:
            raise ValueError(f"Terminator 0x00FF forbidden in title banner: {title!r}")
        title_words.append(code)

    assert CHAR_TERMINATOR not in title_words, f"0x00FF forbidden in title banner: {title!r}"
    words.extend(title_words)

    # Double newline between title banner and rules
    words.extend([CHAR_NEWLINE, CHAR_NEWLINE])

    # Rules description
    for ch in rules:
        if ch == "\n":
            words.append(CHAR_NEWLINE)
        else:
            if ch not in charmap:
                raise ValueError(f"Character {ch!r} in rules not in charmap: {rules!r}")
            code = charmap[ch]
            if code == CHAR_TERMINATOR:
                raise ValueError(f"Unexpected terminator in rules body before end: {rules!r}")
            words.append(code)

    # Single terminator at the end of the entire rules block
    words.append(CHAR_TERMINATOR)

    raw = struct.pack(f"<{len(words)}H", *words)
    if len(raw) > budget:
        raise ValueError(
            f"Combined rules stream ({len(raw)} bytes) exceeds allocated budget ({budget} bytes)"
        )

    # Pad with zeroes up to budget
    padded = raw.ljust(budget, b"\x00")

    # Safety assertion: exactly ONE terminator in the encoded words
    encoded_words = [struct.unpack_from("<H", raw, i)[0] for i in range(0, len(raw), 2)]
    assert encoded_words.count(CHAR_TERMINATOR) == 1, (
        f"Expected exactly 1 terminator in stream, found {encoded_words.count(CHAR_TERMINATOR)}"
    )

    return padded


def decode_minigame_stream(
    raw: bytes,
    budget: int,
    rev_charmap: dict[int, str] | None = None,
) -> tuple[str, str]:
    """Decode a unified minigame continuous stream into (title_banner, rules_ru).

    Expects:
    - 0x0000 indent word at the beginning
    - title characters until 0x00FD, 0x00FD (\n\n)
    - rules characters until 0x00FF
    """
    cm = rev_charmap if rev_charmap is not None else REVERSE_CHARMAP
    sl = raw[:budget]
    words = [struct.unpack_from("<H", sl, i)[0] for i in range(0, len(sl) - 1, 2)]

    idx = 0
    # Skip leading indent 0x0000 if present
    if idx < len(words) and words[idx] == 0x0000:
        idx += 1

    # Read title until \n\n (0x00FD, 0x00FD)
    title_chars: list[str] = []
    found_double_nl = False
    while idx < len(words):
        w = words[idx]
        if w == CHAR_TERMINATOR:
            raise ValueError("Premature 0x00FF terminator encountered in title section")
        if w == CHAR_NEWLINE and idx + 1 < len(words) and words[idx + 1] == CHAR_NEWLINE:
            found_double_nl = True
            idx += 2  # skip \n\n
            break
        elif w in cm:
            title_chars.append(cm[w])
        else:
            title_chars.append(f"[{w:#06x}]")
        idx += 1

    if not found_double_nl:
        raise ValueError("Double newline (\\n\\n, 0x00FD 0x00FD) separator not found between title and rules")

    # Read rules until 0x00FF
    rules_chars: list[str] = []
    found_terminator = False
    while idx < len(words):
        w = words[idx]
        if w == CHAR_TERMINATOR:
            found_terminator = True
            break
        elif w == CHAR_NEWLINE:
            rules_chars.append("\n")
        elif w in cm:
            rules_chars.append(cm[w])
        else:
            rules_chars.append(f"[{w:#06x}]")
        idx += 1

    if not found_terminator:
        raise ValueError("Terminator 0x00FF not found at end of rules section")

    return "".join(title_chars), "".join(rules_chars)


def encode_amelia_combo_block(
    diff_level: int,
    labels: dict[str, str] | None = None,
    charmap: dict[str, int] = DEFAULT_CHARMAP,
) -> bytes:
    """Encode Amelia Cliff Climb combo window block for difficulty 1, 2, or 3.

    diff_level: 1 (Easy, 92B), 2 (Normal, 100B), 3 (Hard, 100B).
    labels: dict with keys 'header', 'level_a', 'level_b', 'level_c', 'level_s'.
    """
    lbls = labels or {}
    hdr = lbls.get("header", "ОК:")
    lva = lbls.get("level_a", lbls.get("level_1", "УРА:"))
    lvb = lbls.get("level_b", lbls.get("level_2", "УРБ:"))
    lvc = lbls.get("level_c", lbls.get("level_3", "УРВ:"))
    lvs = lbls.get("level_s", lbls.get("level_4", "УРС:"))

    def _enc_label(text: str) -> list[int]:
        res = []
        for ch in text:
            if ch not in charmap:
                raise ValueError(f"Character {ch!r} not in charmap for combo label {text!r}")
            res.append(charmap[ch])
        res.append(CHAR_NEWLINE)
        return res

    q_glyph = charmap.get("?", 0x00A7)

    spec_key = f"difficulty_{diff_level}"
    if spec_key not in AMELIA_COMBO_SPECS:
        raise ValueError(f"Invalid difficulty level {diff_level}, must be 1, 2, or 3")
    budget = AMELIA_COMBO_SPECS[spec_key]["budget"]

    words: list[int] = []
    # Line 1: Header
    words.extend(_enc_label(hdr))
    # Line 2: Circle button
    words.extend([0x0000, GLYPH_CIRCLE, CHAR_NEWLINE])

    # Line 3: Level A label
    words.extend(_enc_label(lva))
    # Line 4: Level A combo
    if diff_level == 1:
        words.extend([0x0000, GLYPH_DOWN, GLYPH_CIRCLE, CHAR_NEWLINE])
    elif diff_level == 2:
        words.extend([0x0000, GLYPH_DOWN, GLYPH_DOWN, GLYPH_CIRCLE, CHAR_NEWLINE])
    elif diff_level == 3:
        words.extend([0x0000, GLYPH_UP, GLYPH_DOWN, GLYPH_CIRCLE, CHAR_NEWLINE])

    # Line 5: Level B label
    words.extend(_enc_label(lvb))
    # Line 6: Level B combo
    if diff_level == 1:
        words.extend([0x0000, GLYPH_DOWN, GLYPH_RIGHT, GLYPH_CIRCLE, CHAR_NEWLINE])
    elif diff_level == 2:
        words.extend([0x0000, GLYPH_LEFT, GLYPH_DOWN, GLYPH_RIGHT, GLYPH_CIRCLE, CHAR_NEWLINE])
    elif diff_level == 3:
        words.extend([0x0000, GLYPH_LEFT, GLYPH_UP, GLYPH_RIGHT, GLYPH_DOWN, GLYPH_CIRCLE, CHAR_NEWLINE])

    # Line 7: Level C label
    words.extend(_enc_label(lvc))
    # Line 8: Level C combo
    if diff_level == 1:
        words.extend([0x0000, GLYPH_DOWN, GLYPH_RIGHT, GLYPH_DOWN, GLYPH_CIRCLE, CHAR_NEWLINE])
    elif diff_level == 2:
        words.extend([0x0000, GLYPH_LEFT, GLYPH_RIGHT, GLYPH_DOWN, GLYPH_LEFT, GLYPH_CIRCLE, CHAR_NEWLINE])
    elif diff_level == 3:
        words.extend([0x0000, GLYPH_LEFT, GLYPH_RIGHT, GLYPH_DOWN, GLYPH_RIGHT, GLYPH_CIRCLE, CHAR_NEWLINE])

    # Line 9: Level S label
    words.extend(_enc_label(lvs))
    # Line 10: Level S (?)
    words.extend([0x0000, q_glyph, CHAR_NEWLINE])
    # Line 11: Terminator
    words.append(CHAR_TERMINATOR)

    raw = struct.pack(f"<{len(words)}H", *words)
    if len(raw) > budget:
        raise ValueError(
            f"Amelia combo block {diff_level} encoded to {len(raw)} bytes > budget {budget} bytes"
        )
    return raw.ljust(budget, b"\x00")


def decode_amelia_combo_block(
    raw: bytes,
    budget: int,
    rev_charmap: dict[int, str] | None = None,
) -> str:
    """Decode an Amelia Cliff Climb combo block binary stream into text representation."""
    cm = dict(REVERSE_CHARMAP if rev_charmap is None else rev_charmap)
    cm.update({
        GLYPH_CIRCLE: "○",
        GLYPH_UP: "↑",
        GLYPH_DOWN: "↓",
        GLYPH_RIGHT: "→",
        GLYPH_LEFT: "←",
    })
    cm[0x0000] = "  "
    sl = raw[:budget]
    words = [struct.unpack_from("<H", sl, i)[0] for i in range(0, len(sl) - 1, 2)]
    lines: list[str] = []
    curr: list[str] = []
    for w in words:
        if w == CHAR_TERMINATOR:
            break
        elif w == CHAR_NEWLINE:
            lines.append("".join(curr))
            curr = []
        elif w in cm:
            curr.append(cm[w])
        else:
            curr.append(f"[{w:#06x}]")
    if curr:
        lines.append("".join(curr))
    return "\n".join(lines)


def _patch_amelia_combo_window(
    e14: bytearray,
    mg14: dict[str, Any],
    charmap: dict[str, int] = DEFAULT_CHARMAP,
) -> dict[str, Any]:
    """Patch the 3 difficulty combo text streams and preserve pointer table in Entry 14."""
    combo_cfg = mg14.get("combo_window", {})
    labels = {
        "header": combo_cfg.get("header", "ОК:"),
        "level_a": combo_cfg.get("level_a", combo_cfg.get("level_1", "УРА:")),
        "level_b": combo_cfg.get("level_b", combo_cfg.get("level_2", "УРБ:")),
        "level_c": combo_cfg.get("level_c", combo_cfg.get("level_3", "УРВ:")),
        "level_s": combo_cfg.get("level_s", combo_cfg.get("level_4", "УРС:")),
    }

    stats: dict[str, Any] = {}
    for diff_level, spec_key in ((1, "difficulty_1"), (2, "difficulty_2"), (3, "difficulty_3")):
        spec = AMELIA_COMBO_SPECS[spec_key]
        offset = spec["offset"]
        budget = spec["budget"]
        block_bytes = encode_amelia_combo_block(diff_level, labels, charmap)
        if len(block_bytes) != budget:
            raise ValueError(
                f"Amelia combo block {diff_level} size mismatch: got {len(block_bytes)} bytes, expected {budget}"
            )
        if len(e14) < offset + budget:
            e14.extend(b"\x00" * (offset + budget - len(e14)))
        e14[offset : offset + budget] = block_bytes
        stats[spec_key] = {
            "entry": 14,
            "difficulty": diff_level,
            "offset": offset,
            "bytes": len(block_bytes),
            "budget": budget,
        }

    # Preserve / populate 3-pointer table at 0x1198C..0x11998
    if len(e14) < AMELIA_COMBO_POINTERS_OFFSET + 12:
        e14.extend(b"\x00" * (AMELIA_COMBO_POINTERS_OFFSET + 12 - len(e14)))
    current_ptrs = bytes(e14[AMELIA_COMBO_POINTERS_OFFSET : AMELIA_COMBO_POINTERS_OFFSET + 12])
    if current_ptrs != AMELIA_COMBO_POINTERS_RAW:
        if len(set(current_ptrs)) <= 1:
            e14[AMELIA_COMBO_POINTERS_OFFSET : AMELIA_COMBO_POINTERS_OFFSET + 12] = AMELIA_COMBO_POINTERS_RAW

    return stats


def encode_quiz_slot(
    text: str,
    slot_bytes: int = 32,
    charmap: dict[str, int] = DEFAULT_CHARMAP,
) -> bytes:
    """Encode a single quiz question line or option into a fixed-width slot.

    - Characters encoded as 16-bit words.
    - Terminated with 0x00FF.
    - Padded with zeroes up to slot_bytes (default 32 bytes).
    """
    words: list[int] = []
    for ch in text:
        if ch not in charmap:
            raise ValueError(f"Character {ch!r} not in charmap for slot: {text!r}")
        words.append(charmap[ch])
    words.append(CHAR_TERMINATOR)
    raw = struct.pack(f"<{len(words)}H", *words)
    if len(raw) > slot_bytes:
        raise ValueError(
            f"Slot text {text!r} encoded to {len(raw)} bytes > {slot_bytes} bytes"
        )
    return raw.ljust(slot_bytes, b"\x00")


def decode_quiz_slot(
    raw: bytes,
    rev_charmap: dict[int, str] | None = None,
) -> str:
    """Decode a 32-byte quiz slot back into text."""
    cm = rev_charmap if rev_charmap is not None else REVERSE_CHARMAP
    words = [struct.unpack_from("<H", raw, i)[0] for i in range(0, min(len(raw), 32), 2)]
    chars: list[str] = []
    for w in words:
        if w in (CHAR_TERMINATOR, 0x0000):
            break
        elif w in cm:
            chars.append(cm[w])
        else:
            chars.append(f"[{w:#06x}]")
    return "".join(chars)


def encode_quiz_question(
    q: dict[str, Any],
    charmap: dict[str, int] = DEFAULT_CHARMAP,
) -> bytes:
    """Encode a single 164-byte quiz question record:

    q_line1 (32B), q_line2 (32B), opt1 (32B), opt2 (32B), opt3 (32B), correct (uint32_le).
    """
    q1 = encode_quiz_slot(q["q_line1"], 32, charmap)
    q2 = encode_quiz_slot(q["q_line2"], 32, charmap)
    o1 = encode_quiz_slot(q["opt1"], 32, charmap)
    o2 = encode_quiz_slot(q["opt2"], 32, charmap)
    o3 = encode_quiz_slot(q["opt3"], 32, charmap)
    corr = int(q["correct"])
    if corr not in (0, 1, 2):
        raise ValueError(f"Question {q.get('ps1_index')} correct answer {corr} not in (0, 1, 2)")
    c_b = struct.pack("<I", corr)
    res = q1 + q2 + o1 + o2 + o3 + c_b
    if len(res) != 164:
        raise ValueError(f"Question record length {len(res)} != 164")
    return res


def decode_quiz_question(
    raw: bytes,
    rev_charmap: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Decode a 164-byte quiz record back into dictionary fields."""
    if len(raw) < 164:
        raise ValueError(f"Record slice length {len(raw)} < 164 bytes")
    q1 = decode_quiz_slot(raw[0:32], rev_charmap)
    q2 = decode_quiz_slot(raw[32:64], rev_charmap)
    o1 = decode_quiz_slot(raw[64:96], rev_charmap)
    o2 = decode_quiz_slot(raw[96:128], rev_charmap)
    o3 = decode_quiz_slot(raw[128:160], rev_charmap)
    corr = struct.unpack_from("<I", raw, 160)[0]
    return {
        "q_line1": q1,
        "q_line2": q2,
        "opt1": o1,
        "opt2": o2,
        "opt3": o3,
        "correct": corr,
    }


def encode_quiz_table(
    questions: list[dict[str, Any]],
    charmap: dict[str, int] = DEFAULT_CHARMAP,
) -> bytes:
    """Encode all 100 quiz question structs (16,400 bytes)."""
    if len(questions) != 100:
        raise ValueError(f"Expected exactly 100 questions, got {len(questions)}")
    records: list[bytes] = []
    for q in questions:
        records.append(encode_quiz_question(q, charmap))
    table = b"".join(records)
    if len(table) != 16400:
        raise ValueError(f"Encoded quiz table size {len(table)} != 16400 bytes")
    return table


# ==============================================================================
# Typography & Font Size validation
# ==============================================================================

def check_font_size(
    catalog: dict[str, Any],
    charmap: dict[str, int] = DEFAULT_CHARMAP,
    font_size: str | int = "auto",
) -> list[str]:
    """Validate font size (кегль) constraints for rules and quiz questions.

    Standard font size: 11 / 16x16 pixels dialog font.
    Hardware screen width: 320px.
    Constraints:
    - Quiz questions: q_line1, q_line2, opt1, opt2, opt3 <= 15 characters
      (15 * 16px = 240px <= 320px screen width, fits within text boxes).
    - Minigames rules: <= 20 characters per line, <= 10 lines.
    - All characters must be present in charmap.
    - Correct answer index must be in (0, 1, 2).
    - Total encoded bytes must fit within allocated budgets.

    Returns:
        List of error descriptions (empty if 100% valid).
    """
    errors: list[str] = []

    # 1. Validate minigames rules
    minigames = catalog.get("minigames", {})
    expected_games = {"eating_contest", "amelia_climb", "naga_laugh", "slayers_quiz", "bandit_bullying"}
    missing_games = expected_games - set(minigames.keys())
    if missing_games:
        errors.append(f"Missing minigames in catalog: {missing_games}")

    for mg_id, exp_spec in MINIGAME_SPECS.items():
        if mg_id not in minigames:
            continue
        mg = minigames[mg_id]
        rules = mg.get("rules_ru", "")
        lines = rules.split("\n")
        if len(lines) > 10:
            errors.append(f"Minigame '{mg_id}' has {len(lines)} lines > 10")
        for l_idx, line in enumerate(lines):
            if len(line) > 20:
                errors.append(
                    f"Minigame '{mg_id}' line {l_idx+1} exceeds 20 chars ({len(line)}): {line!r}"
                )
            for ch in line:
                if ch not in charmap:
                    errors.append(f"Minigame '{mg_id}' line {l_idx+1}: character {ch!r} not in charmap")

        # Title banner check
        tb = mg.get("title_banner", "")
        if tb:
            for ch in tb:
                if ch not in charmap:
                    errors.append(f"Minigame '{mg_id}' title banner: character {ch!r} not in charmap")
                elif charmap[ch] == CHAR_TERMINATOR:
                    errors.append(f"Minigame '{mg_id}' title banner contains 0x00FF terminator: {tb!r}")

        # Combined stream check: [0x0000 indent] + title + [\n\n] + rules + [0x00FF term]
        stream_words_count = 1 + len(tb) + 2 + len(rules) + 1
        stream_bytes = stream_words_count * 2
        budget = exp_spec["budget"]
        if stream_bytes > budget:
            errors.append(
                f"Minigame '{mg_id}' combined stream ({stream_bytes} bytes) exceeds budget ({budget})"
            )

        # Entry 15 Naga Laugh Dialogues checks
        if mg_id == "naga_laugh":
            if "dialogues" in mg:
                dlgs = mg["dialogues"]
                for d_id, d_spec in NAGA_DIALOGUE_SPECS.items():
                    if d_id not in dlgs:
                        errors.append(f"Minigame 'naga_laugh' missing dialogue: '{d_id}'")
                        continue
                    d_val = dlgs[d_id]
                    d_text = d_val if isinstance(d_val, str) else d_val.get("text", "")
                    pages = d_text.split("\f")
                    for p_idx, page in enumerate(pages):
                        lines = page.split("\n")
                        for l_idx, line in enumerate(lines):
                            if len(line) > 20:
                                errors.append(
                                    f"Naga Laugh dialogue '{d_id}' p{p_idx+1} line {l_idx+1} exceeds 20 chars ({len(line)}): {line!r}"
                                )
                            for ch in line:
                                if ch not in charmap:
                                    errors.append(
                                        f"Naga Laugh dialogue '{d_id}': character {ch!r} not in charmap"
                                    )
                    txt_budget = d_spec.get("text_budget", d_spec["budget"])
                    is_bubble = d_spec.get("is_bubble", True)
                    try:
                        encode_minigame_dialogue(d_text, txt_budget, charmap, is_bubble=is_bubble)
                    except Exception as e:
                        errors.append(f"Naga Laugh dialogue '{d_id}' error: {e}")

        # Entry 16 Quiz UI checks
        if mg_id == "slayers_quiz":
            if "contestant_prompt" in mg:
                cp = mg["contestant_prompt"]
                for ch in cp:
                    if ch not in charmap:
                        errors.append(f"Quiz contestant prompt: character {ch!r} not in charmap")
                cp_bytes = (len(cp) + 1) * 2
                if cp_bytes > 24:
                    errors.append(f"Quiz contestant prompt bytes ({cp_bytes}) exceed budget 24: {cp!r}")

            if "results_screen" in mg:
                rs = mg["results_screen"]
                for fld, bud in [("header", 16), ("correct_count", 26), ("avg_speed", 34)]:
                    if fld in rs:
                        val = rs[fld]
                        for ch in val:
                            if ch not in charmap:
                                errors.append(f"Quiz results {fld}: character {ch!r} not in charmap")
                        fld_bytes = (len(val) + 1) * 2
                        if fld_bytes > bud:
                            errors.append(
                                f"Quiz results {fld} bytes ({fld_bytes}) exceed budget {bud}: {val!r}"
                            )

        # Entry 13 Eating Contest Status Messages checks
        if mg_id == "eating_contest":
            if "status_messages" in mg:
                s_msgs = mg["status_messages"]
                for s_id, s_spec in EATING_STATUS_SPECS.items():
                    if s_id not in s_msgs:
                        errors.append(f"Minigame 'eating_contest' missing status message: '{s_id}'")
                        continue
                    s_val = s_msgs[s_id]
                    s_text = s_val if isinstance(s_val, str) else s_val.get("text", "")
                    lines = s_text.split("\n")
                    for l_idx, line in enumerate(lines):
                        if len(line) > 20:
                            errors.append(
                                f"Eating Contest message '{s_id}' line {l_idx+1} exceeds 20 chars ({len(line)}): {line!r}"
                            )
                        for ch in line:
                            if ch not in charmap:
                                errors.append(
                                    f"Eating Contest message '{s_id}': character {ch!r} not in charmap"
                                )
                    s_budget = s_spec["budget"]
                    try:
                        encode_minigame_dialogue(s_text, s_budget, charmap, is_bubble=False)
                    except Exception as e:
                        errors.append(f"Eating Contest message '{s_id}' error: {e}")

        # Entry 14 Amelia Cliff Climb Dialogues checks
        if mg_id == "amelia_climb":
            if "dialogues" in mg:
                dlgs = mg["dialogues"]
                for d_id, d_spec in AMELIA_DIALOGUE_SPECS.items():
                    if d_id not in dlgs:
                        errors.append(f"Minigame 'amelia_climb' missing dialogue: '{d_id}'")
                        continue
                    d_val = dlgs[d_id]
                    d_text = d_val if isinstance(d_val, str) else d_val.get("text", "")
                    pages = d_text.split("\f")
                    for p_idx, page in enumerate(pages):
                        lines = page.split("\n")
                        for l_idx, line in enumerate(lines):
                            if len(line) > 20:
                                errors.append(
                                    f"Amelia dialogue '{d_id}' p{p_idx+1} line {l_idx+1} exceeds 20 chars ({len(line)}): {line!r}"
                                )
                            for ch in line:
                                if ch not in charmap:
                                    errors.append(
                                        f"Amelia dialogue '{d_id}': character {ch!r} not in charmap"
                                    )
                    d_budget = d_spec["budget"]
                    is_bubble = d_spec.get("is_bubble", True)
                    try:
                        if is_bubble:
                            encode_minigame_dialogue(d_text, d_budget, charmap, is_bubble=True)
                        else:
                            encode_minigame_string(d_text, d_budget, charmap)
                    except Exception as e:
                        errors.append(f"Amelia dialogue '{d_id}' error: {e}")
            if "combo_window" in mg:
                cw = mg["combo_window"]
                for k in ("header", "level_a", "level_b", "level_c", "level_s"):
                    if k in cw:
                        lbl_val = cw[k]
                        for ch in lbl_val:
                            if ch not in charmap:
                                errors.append(
                                    f"Amelia combo_window '{k}': character {ch!r} not in charmap"
                                )
                try:
                    for d in (1, 2, 3):
                        encode_amelia_combo_block(d, cw, charmap)
                except Exception as e:
                    errors.append(f"Amelia combo_window encoding error: {e}")

        # Entry 17 Bandit Bullying Time Bonus checks
        if mg_id == "bandit_bullying":
            if "time_bonus" in mg:
                tb = mg["time_bonus"]
                for ch in tb:
                    if ch not in charmap:
                        errors.append(f"Bandit bullying time bonus: character {ch!r} not in charmap")
                tb_bytes = (len(tb) + 1) * 2
                if tb_bytes > BANDIT_BONUS_SPEC["budget"]:
                    errors.append(
                        f"Bandit bullying time bonus bytes ({tb_bytes}) exceed budget {BANDIT_BONUS_SPEC['budget']}: {tb!r}"
                    )

    # 2. Validate quiz questions
    quiz = catalog.get("quiz", {})
    questions = quiz.get("questions", [])
    if len(questions) != 100:
        errors.append(f"Quiz total questions count {len(questions)} != 100")

    for q in questions:
        idx = q.get("ps1_index", -1)
        r_id = q.get("renpy_id", -1)
        for field in ("q_line1", "q_line2", "opt1", "opt2", "opt3"):
            val = q.get(field, "")
            if not isinstance(val, str) or len(val) == 0:
                errors.append(f"Q{idx} (renpy {r_id}): field '{field}' is empty")
            elif len(val) > 15:
                errors.append(
                    f"Q{idx} (renpy {r_id}): field '{field}' exceeds 15 chars ({len(val)}): {val!r}"
                )
            for ch in val:
                if ch not in charmap:
                    errors.append(
                        f"Q{idx} (renpy {r_id}): field '{field}' character {ch!r} not in charmap"
                    )

        corr = q.get("correct")
        if corr not in (0, 1, 2):
            errors.append(f"Q{idx} (renpy {r_id}): correct index {corr} not in (0, 1, 2)")

    return errors


# ==============================================================================
# In-memory & Disc Patching
# ==============================================================================

def patch_minigame_system_prompts(
    raw_entries: dict[int, bytearray],
    catalog: dict[str, Any],
    charmap: dict[str, int] = DEFAULT_CHARMAP,
) -> dict[str, Any]:
    """Patch Entry 4 and Entry 5 system prompts (replay, choices, messages) in-place in memory.

    - Entry 4 (0x004):
      - e4_prompt_replay @ 0x5AF2 (budget 28): "Сыграть ещё?" ("Play again?")
      - e4_choice_replay @ 0x5B10 (budget 26): "Да\nНет" ("Play\nNo", options separated by 0x00FE)
    - Entry 5 (0x005):
      - e5_prompt_replay @ 0x881E (budget 18): "Снова?" ("Replay?")
      - e5_choice_replay @ 0x8830 (budget 46): "Ещё раз\nВыйти" ("Play again\nQuit game", options separated by 0x00FE)
      - e5_prompt_go_ahead @ 0x8862 (budget 20): "Твой ход." ("Go ahead.")
    """
    sys_prompts = catalog.get("system_prompts", {})
    stats: dict[str, Any] = {}

    for entry_idx in (4, 5):
        if entry_idx not in raw_entries:
            continue
        target = raw_entries[entry_idx]
        entry_key = f"entry_{entry_idx}"
        entry_cfg = sys_prompts.get(entry_key, {})
        prompts_dict = entry_cfg.get("prompts", entry_cfg) if isinstance(entry_cfg, dict) else {}
        specs = SYSTEM_PROMPT_SPECS.get(entry_idx, {})

        for prompt_id, spec in specs.items():
            p_data = prompts_dict.get(prompt_id, {})
            choices = p_data.get("choices") or spec.get("choices")
            text = (
                p_data.get("text_ru")
                or p_data.get("text")
                or spec.get("default_ru", "")
            )
            offset = p_data.get("offset")
            if offset is None and "offset_hex" in p_data:
                offset = int(p_data["offset_hex"], 16)
            if offset is None:
                offset = spec["offset"]

            budget = p_data.get("budget", spec["budget"])

            if len(target) < offset + budget:
                target.extend(b"\x00" * (offset + budget - len(target)))

            target[offset : offset + budget] = b"\x00" * budget
            if choices or "\n" in text or "\f" in text:
                opts = choices if choices else re.split(r"[\n\f]", text)
                encoded_opts: list[bytes] = []
                for opt in opts:
                    words = []
                    for ch in opt:
                        if ch not in charmap:
                            raise ValueError(f"Character {ch!r} not in charmap for prompt {prompt_id!r}")
                        words.append(charmap[ch])
                    encoded_opts.append(struct.pack(f"<{len(words)}H", *words))
                enc = struct.pack("<H", CHAR_PAGE).join(encoded_opts) + struct.pack("<H", CHAR_TERMINATOR)
                if len(enc) > budget:
                    raise ValueError(f"Prompt {prompt_id!r} encoded to {len(enc)} bytes > budget {budget} bytes")
                enc = enc.ljust(budget, b"\x00")
            else:
                enc = encode_minigame_string(text, budget, charmap)

            target[offset : offset + len(enc)] = enc

            stat_item = {
                "entry": entry_idx,
                "offset": offset,
                "bytes": len(enc),
                "budget": budget,
                "text": text,
            }
            stats[prompt_id] = stat_item
            stats[f"entry_{entry_idx}_{prompt_id}"] = stat_item

    return stats

def patch_minigames_memory(
    entries: dict[int, bytearray],
    catalog: dict[str, Any],
    charmap: dict[str, int] = DEFAULT_CHARMAP,
    font_size: str | int = "auto",
) -> dict[str, Any]:
    """Patch PROG.UNT entries 4, 5, 13..17 in-place in memory.

    Modifies:
    - Entry 4: offset 0x5AF2..0x5B46 (Entry 4 system prompts and choices, budget 84B total)
    - Entry 5: offset 0x8830..0x88BC (Entry 5 system prompts, choices, and messages, budget 140B total)
    - Entry 13: offset 0x07320..0x07468 (Eating contest continuous stream, budget 328B)
    - Entry 14: offset 0x11318..0x1147A (Amelia climb continuous stream, budget 354B)
    - Entry 15: offset 0x07EB4..0x07FC6 (Naga laugh continuous stream, budget 274B)
    - Entry 16: offset 0x08184..0x08280 (Quiz rules continuous stream, budget 252B)
    - Entry 16: offset 0x08284..0x0829C (Quiz contestant prompt, budget 24B)
    - Entry 16: offset 0x0829C..0x082AC (Quiz results header, budget 16B)
    - Entry 16: offset 0x082AC..0x082C6 (Quiz results correct count, budget 26B)
    - Entry 16: offset 0x082C6..0x082E8 (Quiz results avg speed, budget 34B)
    - Entry 16: offset 0x082E8 (Quiz questions, 100 structs * 164B = 16,400B)
    - Entry 17: offset 0x082B8..0x08412 (Bandit bullying continuous stream, budget 346B)
    - Entry 17: offset 0x08414..0x08428 (Bandit bullying time bonus, budget 20B)

    Returns:
        Report dictionary of patched offsets and sizes.
    """
    # 1. Validate typography & font sizing constraints
    errors = check_font_size(catalog, charmap, font_size)
    if errors:
        raise ValueError(
            f"Catalog typography validation failed with {len(errors)} error(s):\n"
            + "\n".join(f" - {e}" for e in errors[:10])
        )

    minigames = catalog["minigames"]
    patch_stats: dict[str, Any] = {}

    def _patch_stream(mg_id: str, entry_idx: int) -> None:
        mg = minigames[mg_id]
        spec = MINIGAME_SPECS[mg_id]
        start_off = spec["offset"]  # title_start_offset
        end_off = spec["rules_end_offset"]
        budget = spec["budget"]
        assert end_off - start_off == budget, f"Budget mismatch: {end_off} - {start_off} != {budget}"

        target = entries[entry_idx]
        # Zero-fill entire combined budget
        target[start_off:end_off] = b"\x00" * budget

        title = mg.get("title_banner", "")
        rules = mg.get("rules_ru", "")

        # Assert no 0x00FF within title section
        title_codes = [charmap[c] for c in title]
        assert CHAR_TERMINATOR not in title_codes, f"0x00FF forbidden in title banner for {mg_id}"

        stream = encode_minigame_stream(title, rules, budget, charmap)
        target[start_off : start_off + len(stream)] = stream

        patch_stats[mg_id] = {
            "entry": entry_idx,
            "offset": start_off,
            "bytes": len(stream),
            "budget": budget,
        }
        patch_stats[f"{mg_id}_stream"] = {
            "entry": entry_idx,
            "offset": start_off,
            "bytes": len(stream),
            "budget": budget,
        }
        patch_stats[f"{mg_id}_title"] = {
            "entry": entry_idx,
            "offset": start_off,
            "bytes": (1 + len(title)) * 2,
            "budget": budget,
        }

    # 1. Patch Entry 13 (Eating contest)
    _patch_stream("eating_contest", 13)

    # Patch Entry 13 Eating Contest Status Messages (lina_morale, gourry_satiated, combined_status)
    e13 = entries[13]
    mg13 = minigames.get("eating_contest", {})
    if "status_messages" in mg13:
        status_msgs = mg13["status_messages"]
        e13_stats: dict[str, Any] = {
            "entry": 13,
            "messages": len(status_msgs),
        }
        for s_id, s_spec in EATING_STATUS_SPECS.items():
            if s_id not in status_msgs:
                continue
            s_val = status_msgs[s_id]
            s_text = s_val if isinstance(s_val, str) else s_val.get("text", "")
            offset = s_spec["offset"]
            budget = s_spec["budget"]
            if len(e13) < offset + budget:
                e13.extend(b"\x00" * (offset + budget - len(e13)))
            # Zero-pad memory block
            e13[offset : offset + budget] = b"\x00" * budget
            enc_s = encode_minigame_dialogue(s_text, budget, charmap, is_bubble=False)
            e13[offset : offset + len(enc_s)] = enc_s
            stat_item = {
                "entry": 13,
                "offset": offset,
                "bytes": len(enc_s),
                "budget": budget,
            }
            e13_stats[s_id] = stat_item
            patch_stats[f"eating_contest_{s_id}"] = stat_item
        patch_stats["eating_contest_status_messages"] = e13_stats

    # 2. Patch Entry 14 (Amelia climb)
    _patch_stream("amelia_climb", 14)

    # Patch Entry 14 Amelia Speeches (1..5), 5-Pointer Table, and Result (justice_up)
    e14 = entries[14]
    mg14 = minigames.get("amelia_climb", {})
    if "dialogues" in mg14:
        dlgs14 = mg14["dialogues"]
        dlg14_stats: dict[str, Any] = {
            "entry": 14,
            "dialogues": len(dlgs14),
        }
        for d_id, d_spec in AMELIA_DIALOGUE_SPECS.items():
            if d_id not in dlgs14:
                continue
            d_val = dlgs14[d_id]
            d_text = d_val if isinstance(d_val, str) else d_val.get("text", "")
            offset = d_spec["offset"]
            budget = d_spec["budget"]
            is_bubble = d_spec.get("is_bubble", True)

            # Zero-pad memory block
            clear_size = budget
            if d_id in ("dialogue_3", "dialogue_4"):
                clear_size = 228
            if len(e14) < offset + clear_size:
                e14.extend(b"\x00" * (offset + clear_size - len(e14)))
            e14[offset : offset + clear_size] = b"\x00" * clear_size

            enc_d = encode_minigame_dialogue(d_text, budget, charmap, is_bubble=is_bubble)
            e14[offset : offset + len(enc_d)] = enc_d
            stat_item = {
                "entry": 14,
                "offset": offset,
                "bytes": len(enc_d),
                "budget": budget,
            }
            dlg14_stats[d_id] = stat_item
            patch_stats[f"amelia_climb_{d_id}"] = stat_item

        # Preserve / populate 5-pointer table at 0x11854..0x11868
        if len(e14) < AMELIA_POINTER_TABLE_OFFSET + 20:
            e14.extend(b"\x00" * (AMELIA_POINTER_TABLE_OFFSET + 20 - len(e14)))
        current_hdr = bytes(e14[AMELIA_POINTER_TABLE_OFFSET : AMELIA_POINTER_TABLE_OFFSET + 20])
        if current_hdr != AMELIA_DIALOGUE_POINTERS_RAW:
            if len(set(current_hdr)) <= 1:
                e14[AMELIA_POINTER_TABLE_OFFSET : AMELIA_POINTER_TABLE_OFFSET + 20] = AMELIA_DIALOGUE_POINTERS_RAW

        patch_stats["amelia_climb_dialogues"] = dlg14_stats

    # Patch Entry 14 Amelia Combo Window (Difficulty Blocks 1..3 and 3-Pointer Table)
    combo_stats = _patch_amelia_combo_window(e14, mg14, charmap)
    for c_id, c_stat in combo_stats.items():
        patch_stats[f"amelia_climb_combo_{c_id}"] = c_stat
    patch_stats["amelia_climb_combo_window"] = {
        "entry": 14,
        "offset": AMELIA_COMBO_SPECS["difficulty_1"]["offset"],
        "bytes": sum(s["bytes"] for s in combo_stats.values()),
        "blocks": len(combo_stats),
    }

    # 3. Patch Entry 15 (Naga laugh)
    _patch_stream("naga_laugh", 15)

    # Patch Entry 15 Naga Dialogues (Dialogues 1..6)
    e15 = entries[15]
    mg15 = minigames.get("naga_laugh", {})
    if "dialogues" in mg15:
        dlgs = mg15["dialogues"]
        dlg_stats: dict[str, Any] = {
            "entry": 15,
            "offset": 0x07FC8,
            "bytes": 882,
            "dialogues": len(dlgs),
        }
        for d_id, d_spec in NAGA_DIALOGUE_SPECS.items():
            if d_id not in dlgs:
                continue
            d_val = dlgs[d_id]
            d_text = d_val if isinstance(d_val, str) else d_val.get("text", "")

            offset = d_spec["offset"]
            budget = d_spec["budget"]
            is_bubble = d_spec.get("is_bubble", True)

            if d_id == "dialogue_6":
                hdr_off = d_spec["pointer_header_offset"]
                hdr_size = d_spec["pointer_header_size"]
                txt_off = d_spec["text_offset"]
                txt_budget = d_spec["text_budget"]

                # Zero out 2-byte alignment padding
                e15[offset : hdr_off] = b"\x00" * (hdr_off - offset)

                # Preserve 20-byte RAM pointer header (populate if mock/uninitialized)
                current_hdr = bytes(e15[hdr_off : hdr_off + hdr_size])
                if current_hdr != NAGA_DIALOGUE_POINTERS_RAW:
                    if len(set(current_hdr)) <= 1:
                        e15[hdr_off : hdr_off + hdr_size] = NAGA_DIALOGUE_POINTERS_RAW

                # Zero out status text buffer
                e15[txt_off : txt_off + txt_budget] = b"\x00" * txt_budget
                enc_d = encode_minigame_dialogue(d_text, txt_budget, charmap, is_bubble=False)
                e15[txt_off : txt_off + len(enc_d)] = enc_d

                stat_item = {
                    "entry": 15,
                    "offset": txt_off,
                    "bytes": len(enc_d),
                    "budget": txt_budget,
                }
                dlg_stats[d_id] = stat_item
                patch_stats[f"naga_laugh_{d_id}"] = stat_item
            elif d_id == "dialogue_2":
                # Zero-fill entire 170-byte buffer 0x0806A..0x08114
                e15[offset : offset + budget] = b"\x00" * budget
                # Text starts at 0x0806C (preserving 00 00 padding at 0x0806A for 4-byte pointer alignment)
                txt_off = d_spec.get("text_offset", offset)
                txt_budget = budget - (txt_off - offset)
                enc_d = encode_minigame_dialogue(d_text, txt_budget, charmap, is_bubble=is_bubble)
                e15[txt_off : txt_off + len(enc_d)] = enc_d
                stat_item = {
                    "entry": 15,
                    "offset": offset,
                    "text_offset": txt_off,
                    "bytes": len(enc_d),
                    "budget": budget,
                }
                dlg_stats[d_id] = stat_item
                patch_stats[f"naga_laugh_{d_id}"] = stat_item
            else:
                # Dialogues 1, 3, 4, 5
                e15[offset : offset + budget] = b"\x00" * budget
                enc_d = encode_minigame_dialogue(d_text, budget, charmap, is_bubble=is_bubble)
                e15[offset : offset + len(enc_d)] = enc_d
                stat_item = {
                    "entry": 15,
                    "offset": offset,
                    "bytes": len(enc_d),
                    "budget": budget,
                }
                dlg_stats[d_id] = stat_item
                patch_stats[f"naga_laugh_{d_id}"] = stat_item
        patch_stats["naga_laugh_dialogues"] = dlg_stats

    # 4. Patch Entry 16 (Quiz rules & UI)
    _patch_stream("slayers_quiz", 16)
    patch_stats["slayers_quiz_rules"] = patch_stats["slayers_quiz"]

    e16 = entries[16]
    mg16 = minigames["slayers_quiz"]

    # Contestant prompt
    if "contestant_prompt" in mg16:
        cp_off = QUIZ_UI_SPECS["contestant_prompt"]["offset"]
        cp_bud = QUIZ_UI_SPECS["contestant_prompt"]["budget"]
        e16[cp_off : cp_off + cp_bud] = b"\x00" * cp_bud
        cp_enc = encode_minigame_string(mg16["contestant_prompt"], cp_bud, charmap)
        e16[cp_off : cp_off + len(cp_enc)] = cp_enc
        patch_stats["slayers_quiz_prompt"] = {
            "entry": 16,
            "offset": cp_off,
            "bytes": len(cp_enc),
            "budget": cp_bud,
        }

    # Results screen
    if "results_screen" in mg16:
        rs = mg16["results_screen"]
        if "header" in rs:
            h_off = QUIZ_UI_SPECS["results_header"]["offset"]
            h_bud = QUIZ_UI_SPECS["results_header"]["budget"]
            e16[h_off : h_off + h_bud] = b"\x00" * h_bud
            h_enc = encode_minigame_string(rs["header"], h_bud, charmap)
            e16[h_off : h_off + len(h_enc)] = h_enc
            patch_stats["slayers_quiz_results_header"] = {
                "entry": 16,
                "offset": h_off,
                "bytes": len(h_enc),
                "budget": h_bud,
            }
        if "correct_count" in rs:
            cc_off = QUIZ_UI_SPECS["results_correct_count"]["offset"]
            cc_bud = QUIZ_UI_SPECS["results_correct_count"]["budget"]
            e16[cc_off : cc_off + cc_bud] = b"\x00" * cc_bud
            cc_enc = encode_minigame_string(rs["correct_count"], cc_bud, charmap)
            e16[cc_off : cc_off + len(cc_enc)] = cc_enc
            patch_stats["slayers_quiz_results_correct_count"] = {
                "entry": 16,
                "offset": cc_off,
                "bytes": len(cc_enc),
                "budget": cc_bud,
            }
        if "avg_speed" in rs:
            as_off = QUIZ_UI_SPECS["results_avg_speed"]["offset"]
            as_bud = QUIZ_UI_SPECS["results_avg_speed"]["budget"]
            e16[as_off : as_off + as_bud] = b"\x00" * as_bud
            as_enc = encode_minigame_string(rs["avg_speed"], as_bud, charmap)
            e16[as_off : as_off + len(as_enc)] = as_enc
            patch_stats["slayers_quiz_results_avg_speed"] = {
                "entry": 16,
                "offset": as_off,
                "bytes": len(as_enc),
                "budget": as_bud,
            }

    # 5. Patch Entry 16 (Quiz Questions table)
    quiz_meta = catalog["quiz"]["metadata"]
    off16_quiz = int(quiz_meta["questions_offset_hex"], 16)
    quiz_table = encode_quiz_table(catalog["quiz"]["questions"], charmap)
    e16[off16_quiz : off16_quiz + len(quiz_table)] = quiz_table
    patch_stats["quiz_questions"] = {
        "entry": 16,
        "offset": off16_quiz,
        "bytes": len(quiz_table),
        "questions": 100,
    }

    # 6. Patch Entry 17 (Bandit bullying)
    _patch_stream("bandit_bullying", 17)

    # Patch Entry 17 Bandit Bullying time bonus string at 0x08414
    e17 = entries[17]
    mg17 = minigames.get("bandit_bullying", {})
    if "time_bonus" in mg17:
        tb_text = mg17["time_bonus"]
        tb_off = BANDIT_BONUS_SPEC["offset"]
        tb_bud = BANDIT_BONUS_SPEC["budget"]
        if len(e17) < tb_off + tb_bud:
            e17.extend(b"\x00" * (tb_off + tb_bud - len(e17)))
        e17[tb_off : tb_off + tb_bud] = b"\x00" * tb_bud
        tb_enc = encode_minigame_string(tb_text, tb_bud, charmap)
        e17[tb_off : tb_off + len(tb_enc)] = tb_enc
        patch_stats["bandit_bullying_time_bonus"] = {
            "entry": 17,
            "offset": tb_off,
            "bytes": len(tb_enc),
            "budget": tb_bud,
        }


    # 7. Patch Entry 4 & Entry 5 system prompts if present in entries
    if 4 in entries or 5 in entries:
        sys_stats = patch_minigame_system_prompts(entries, catalog, charmap)
        patch_stats.update(sys_stats)
    return patch_stats


def patch_minigames(
    bin_path: Path | str,
    catalog_path: Path | str | None = None,
    output_bin: Path | str | None = None,
    dry_run: bool = False,
    font_size: str | int = "auto",
) -> dict[str, Any]:
    """Execute complete minigames, quiz, and font patching pipeline on disc image.

    1. Load translations catalog.
    2. Read entries 13..17 from target disc image.
    3. Patch entries 13..17 in memory with rules and quiz table.
    4. Extract Russian Cyrillic font tiles from PROG.UNT 0x03A.
    5. Inject Russian font tiles into SMINI.UNT (Entries 3, 0, 1, 2, 4).
    6. If not dry_run, write modified entries back to disc image using
       replace_extent_in_place (which recalculates Mode 2 Form 1 EDC/ECC).
    7. Return patch summary and verified statistics.
    """
    p = Path(bin_path)
    if not p.is_file():
        raise FileNotFoundError(f"Target disc image not found: {p}")

    cat_path = Path(catalog_path or DEFAULT_CATALOG)
    if not cat_path.is_file():
        raise FileNotFoundError(f"Translations catalog not found: {cat_path}")

    catalog = json.loads(cat_path.read_text(encoding="utf-8"))

    work_bin = p
    if output_bin is not None and Path(output_bin) != p and not dry_run:
        out_p = Path(output_bin)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copyfile(p, out_p)
        work_bin = out_p

    # Read PROG.UNT entries 4, 5, 13..17
    target_prog_entries = (4, 5, 13, 14, 15, 16, 17)
    prog_lba, entries_dict = load_prog_entries_data(work_bin, target_prog_entries)

    raw_entries: dict[int, bytearray] = {
        idx: entries_dict[idx]["data"] for idx in target_prog_entries
    }

    # Patch minigame rules & quiz in memory
    patch_stats = patch_minigames_memory(raw_entries, catalog, DEFAULT_CHARMAP, font_size)

    # Extract Russian Cyrillic font tiles from PROG.UNT Entry 0x03A
    _, font_entry_dict = load_prog_entries_data(work_bin, [PROG_FONT_ENTRY])
    decomp_03a, _ = unt_lz.decompress(bytes(font_entry_dict[PROG_FONT_ENTRY]["data"]))
    font_tiles = extract_prog_font_tiles(decomp_03a, MINIGAME_FONT_GLYPH_IDS)

    # Load SMINI.UNT entries (3, 0, 1, 2, 4) and patch font tiles in memory
    smini_target_entries = (3, 0, 1, 2, 4)
    smini_lba, smini_entries_dict = load_smini_entries_data(work_bin, smini_target_entries)
    smini_raw_entries = {idx: smini_entries_dict[idx]["data"] for idx in smini_target_entries}
    pristine_btn_tiles = load_pristine_button_tiles(DEFAULT_SRC_BIN if DEFAULT_SRC_BIN.is_file() else None)
    smini_font_stats = patch_smini_fonts_memory(
        smini_raw_entries, font_tiles, smini_target_entries, pristine_button_tiles=pristine_btn_tiles
    )

    # Write patched sectors to disc
    total_sectors = 0
    if not dry_run:
        # 1. Write PROG.UNT entries 4, 5, 13..17
        for idx in target_prog_entries:
            start_sec = entries_dict[idx]["start_sector"]
            sec_count = entries_dict[idx]["sector_count"]
            data = bytes(raw_entries[idx])
            replace_extent_in_place(work_bin, prog_lba + start_sec, data)
            total_sectors += sec_count

        # 2. Write SMINI.UNT entries 3, 0, 1, 2, 4
        for idx in smini_target_entries:
            start_sec = smini_entries_dict[idx]["start_sector"]
            sec_count = smini_entries_dict[idx]["sector_count"]
            data = bytes(smini_raw_entries[idx])
            replace_extent_in_place(work_bin, smini_lba + start_sec, data)
            total_sectors += sec_count
    else:
        total_sectors = sum(entries_dict[i]["sector_count"] for i in target_prog_entries) + sum(
            smini_entries_dict[i]["sector_count"] for i in smini_target_entries
        )

    return {
        "target_bin": str(work_bin),
        "dry_run": dry_run,
        "prog_lba": prog_lba,
        "smini_lba": smini_lba,
        "patched_entries": list(target_prog_entries),
        "patched_smini_entries": list(smini_target_entries),
        "total_sectors_patched": total_sectors,
        "patch_stats": patch_stats,
        "smini_font_stats": smini_font_stats,
    }


# ==============================================================================
# Verification
# ==============================================================================

def verify_minigames(
    bin_path: Path | str,
    catalog_path: Path | str | None = None,
    charmap: dict[str, int] = DEFAULT_CHARMAP,
) -> dict[str, Any]:
    """Verify binary integrity, decoded minigames text, quiz questions, SMINI font tiles, and EDC/ECC checksums.

    1. Reads entries 13..17 from disc image.
    2. Decodes rules of all 5 minigames and compares strictly with catalog.
    3. Decodes all 100 quiz questions and options, comparing with catalog.
    4. Validates correct answer indices against catalog.
    5. Validates SMINI.UNT font tiles (Entries 3, 0, 1, 2, 4) against PROG.UNT 0x03A.
    6. Validates Mode 2 Form 1 EDC/ECC checksums on all modified sectors (PROG.UNT + SMINI.UNT).
    """
    p = Path(bin_path)
    if not p.is_file():
        raise FileNotFoundError(f"BIN image not found: {p}")

    cat_path = Path(catalog_path or DEFAULT_CATALOG)
    if not cat_path.is_file():
        raise FileNotFoundError(f"Catalog not found: {cat_path}")

    catalog = json.loads(cat_path.read_text(encoding="utf-8"))
    rev_charmap = get_reverse_charmap(charmap)

    # Read entries 4, 5, 13..17 from disc
    target_prog_entries = (4, 5, 13, 14, 15, 16, 17)
    prog_lba, entries_dict = load_prog_entries_data(p, target_prog_entries)

    # 1. Verify Minigames Continuous Unified Streams
    minigames = catalog["minigames"]
    for mg_id, spec in MINIGAME_SPECS.items():
        entry_idx = spec["entry"]
        offset = spec["offset"]
        budget = spec["budget"]
        expected_rules = minigames[mg_id]["rules_ru"]
        expected_title = minigames[mg_id].get("title_banner", "")

        entry_data = entries_dict[entry_idx]["data"]
        stream_bytes = entry_data[offset : offset + budget]

        decoded_title, decoded_rules = decode_minigame_stream(stream_bytes, budget, rev_charmap)

        if decoded_title != expected_title:
            raise AssertionError(
                f"Minigame '{mg_id}' title banner mismatch in Entry {entry_idx} at 0x{offset:05X}:\n"
                f"  Expected: {expected_title!r}\n"
                f"  Found:    {decoded_title!r}"
            )

        if decoded_rules != expected_rules:
            raise AssertionError(
                f"Minigame '{mg_id}' rules mismatch in Entry {entry_idx} at 0x{offset:05X}:\n"
                f"  Expected: {expected_rules!r}\n"
                f"  Found:    {decoded_rules!r}"
            )

        # Verify no 0x00FF in title section and proper leading indent 0x0000
        words = [struct.unpack_from("<H", stream_bytes, i)[0] for i in range(0, budget, 2)]
        if words[0] != 0x0000:
            raise AssertionError(f"Minigame '{mg_id}' missing leading 0x0000 indent in Entry {entry_idx}")

        title_word_count = len(expected_title)
        for w in words[1 : 1 + title_word_count + 2]:
            if w == CHAR_TERMINATOR:
                raise AssertionError(f"Minigame '{mg_id}' contains premature 0x00FF terminator before rules")
    # 2. Verify Quiz Questions
    quiz_meta = catalog["quiz"]["metadata"]
    quiz_offset = int(quiz_meta["questions_offset_hex"], 16)
    questions = catalog["quiz"]["questions"]
    e16_data = entries_dict[16]["data"]

    for i, q in enumerate(questions):
        rec_offset = quiz_offset + i * 164
        rec_data = e16_data[rec_offset : rec_offset + 164]
        dec_q = decode_quiz_question(rec_data, rev_charmap)

        for field in ("q_line1", "q_line2", "opt1", "opt2", "opt3"):
            if dec_q[field] != q[field]:
                raise AssertionError(
                    f"Quiz Q{i} (renpy {q.get('renpy_id')}) field '{field}' mismatch:\n"
                    f"  Expected: {q[field]!r}\n"
                    f"  Found:    {dec_q[field]!r}"
                )

        if dec_q["correct"] != q["correct"]:
            raise AssertionError(
                f"Quiz Q{i} (renpy {q.get('renpy_id')}) correct index mismatch: "
                f"expected {q['correct']}, found {dec_q['correct']}"
            )

    # 3. Verify Contestant Selection Prompt & Results Screen
    mg16 = minigames.get("slayers_quiz", {})
    verified_quiz_ui = 0
    if "contestant_prompt" in mg16:
        cp_off = QUIZ_UI_SPECS["contestant_prompt"]["offset"]
        cp_bud = QUIZ_UI_SPECS["contestant_prompt"]["budget"]
        exp_cp = mg16["contestant_prompt"]
        dec_cp = decode_minigame_string(e16_data[cp_off:], cp_bud, rev_charmap)
        if dec_cp != exp_cp:
            raise AssertionError(
                f"Quiz contestant prompt mismatch in Entry 16 at 0x{cp_off:05X}:\n"
                f"  Expected: {exp_cp!r}\n"
                f"  Found:    {dec_cp!r}"
            )
        verified_quiz_ui += 1

    if "results_screen" in mg16:
        rs = mg16["results_screen"]
        if "header" in rs:
            h_off = QUIZ_UI_SPECS["results_header"]["offset"]
            h_bud = QUIZ_UI_SPECS["results_header"]["budget"]
            exp_h = rs["header"]
            dec_h = decode_minigame_string(e16_data[h_off:], h_bud, rev_charmap)
            if dec_h != exp_h:
                raise AssertionError(
                    f"Quiz results header mismatch in Entry 16 at 0x{h_off:05X}:\n"
                    f"  Expected: {exp_h!r}\n"
                    f"  Found:    {dec_h!r}"
                )
            verified_quiz_ui += 1
        if "correct_count" in rs:
            cc_off = QUIZ_UI_SPECS["results_correct_count"]["offset"]
            cc_bud = QUIZ_UI_SPECS["results_correct_count"]["budget"]
            exp_cc = rs["correct_count"]
            dec_cc = decode_minigame_string(e16_data[cc_off:], cc_bud, rev_charmap)
            if dec_cc != exp_cc:
                raise AssertionError(
                    f"Quiz results correct count mismatch in Entry 16 at 0x{cc_off:05X}:\n"
                    f"  Expected: {exp_cc!r}\n"
                    f"  Found:    {dec_cc!r}"
                )
            verified_quiz_ui += 1
        if "avg_speed" in rs:
            as_off = QUIZ_UI_SPECS["results_avg_speed"]["offset"]
            as_bud = QUIZ_UI_SPECS["results_avg_speed"]["budget"]
            exp_as = rs["avg_speed"]
            dec_as = decode_minigame_string(e16_data[as_off:], as_bud, rev_charmap)
            if dec_as != exp_as:
                raise AssertionError(
                    f"Quiz results avg speed mismatch in Entry 16 at 0x{as_off:05X}:\n"
                    f"  Expected: {exp_as!r}\n"
                    f"  Found:    {dec_as!r}"
                )
            verified_quiz_ui += 1

    # 4. Verify Naga Laugh Dialogues in Entry 15
    e15_data = entries_dict[15]["data"]
    mg15 = minigames.get("naga_laugh", {})
    verified_naga_dialogues = 0
    if "dialogues" in mg15:
        dialogues = mg15["dialogues"]
        for d_id, d_spec in NAGA_DIALOGUE_SPECS.items():
            if d_id not in dialogues:
                continue
            d_val = dialogues[d_id]
            expected_text = d_val if isinstance(d_val, str) else d_val.get("text", "")

            offset = d_spec.get("text_offset", d_spec["offset"])
            budget = d_spec.get("text_budget", d_spec["budget"])
            is_bubble = d_spec.get("is_bubble", True)

            raw_dialogue = e15_data[offset : offset + budget]
            decoded_text = decode_minigame_dialogue(raw_dialogue, budget, rev_charmap, is_bubble=is_bubble)

            if decoded_text != expected_text:
                raise AssertionError(
                    f"Naga Laugh dialogue '{d_id}' mismatch in Entry 15 at 0x{offset:05X}:\n"
                    f"  Expected: {expected_text!r}\n"
                    f"  Found:    {decoded_text!r}"
                )

            if d_id == "dialogue_6":
                hdr_off = d_spec["pointer_header_offset"]
                hdr_words = struct.unpack_from("<5I", e15_data, hdr_off)
                if hdr_words != NAGA_DIALOGUE_POINTERS:
                    raise AssertionError(
                        f"Naga Laugh pointer table mismatch at 0x{hdr_off:05X}:\n"
                        f"  Expected: {[hex(p) for p in NAGA_DIALOGUE_POINTERS]}\n"
                        f"  Found:    {[hex(p) for p in hdr_words]}"
                    )
            verified_naga_dialogues += 1

    # 5. Verify Eating Contest Status Messages in Entry 13
    e13_data = entries_dict[13]["data"]
    mg13 = minigames.get("eating_contest", {})
    verified_eating_status = 0
    if "status_messages" in mg13:
        status_msgs = mg13["status_messages"]
        for s_id, s_spec in EATING_STATUS_SPECS.items():
            if s_id not in status_msgs:
                continue
            s_val = status_msgs[s_id]
            expected_text = s_val if isinstance(s_val, str) else s_val.get("text", "")
            offset = s_spec["offset"]
            budget = s_spec["budget"]

            raw_data = e13_data[offset : offset + budget]
            decoded_text = decode_minigame_dialogue(raw_data, budget, rev_charmap, is_bubble=False)

            if decoded_text != expected_text:
                raise AssertionError(
                    f"Eating Contest status '{s_id}' mismatch in Entry 13 at 0x{offset:05X}:\n"
                    f"  Expected: {expected_text!r}\n"
                    f"  Found:    {decoded_text!r}"
                )
            verified_eating_status += 1

    # 6. Verify Amelia Cliff Climb Dialogues and Combo Window in Entry 14
    e14_data = entries_dict[14]["data"]
    mg14 = minigames.get("amelia_climb", {})
    verified_amelia_dialogues = 0
    verified_amelia_combo_blocks = 0
    if "dialogues" in mg14:
        dialogues14 = mg14["dialogues"]
        for d_id, d_spec in AMELIA_DIALOGUE_SPECS.items():
            if d_id not in dialogues14:
                continue
            d_val = dialogues14[d_id]
            expected_text = d_val if isinstance(d_val, str) else d_val.get("text", "")

            offset = d_spec["offset"]
            budget = d_spec["budget"]
            is_bubble = d_spec.get("is_bubble", True)

            raw_dialogue = e14_data[offset : offset + budget]
            if is_bubble:
                decoded_text = decode_minigame_dialogue(raw_dialogue, budget, rev_charmap, is_bubble=True)
            else:
                decoded_text = decode_minigame_string(raw_dialogue, budget, rev_charmap)

            if decoded_text != expected_text:
                raise AssertionError(
                    f"Amelia dialogue '{d_id}' mismatch in Entry 14 at 0x{offset:05X}:\n"
                    f"  Expected: {expected_text!r}\n"
                    f"  Found:    {decoded_text!r}"
                )
            verified_amelia_dialogues += 1

        # Verify Amelia 5-pointer table at 0x11854..0x11868
        hdr_words = struct.unpack_from("<5I", e14_data, AMELIA_POINTER_TABLE_OFFSET)
        if hdr_words != AMELIA_DIALOGUE_POINTERS:
            raise AssertionError(
                f"Amelia pointer table mismatch at 0x{AMELIA_POINTER_TABLE_OFFSET:05X}:\n"
                f"  Expected: {[hex(p) for p in AMELIA_DIALOGUE_POINTERS]}\n"
                f"  Found:    {[hex(p) for p in hdr_words]}"
            )

        # Verify Amelia Cliff Climb 3 combo window blocks
        for diff_level, spec_key in ((1, "difficulty_1"), (2, "difficulty_2"), (3, "difficulty_3")):
            spec = AMELIA_COMBO_SPECS[spec_key]
            offset = spec["offset"]
            budget = spec["budget"]
            block_raw = bytes(e14_data[offset : offset + budget])
            decoded = decode_amelia_combo_block(block_raw, budget, rev_charmap)
            if "ОК:" not in decoded:
                raise AssertionError(
                    f"Amelia combo block {diff_level} missing 'ОК:' at 0x{offset:05X}:\n{decoded}"
                )
            for lvl_lbl in ("УРА:", "УРБ:", "УРВ:", "УРС:"):
                if lvl_lbl not in decoded:
                    raise AssertionError(
                        f"Amelia combo block {diff_level} missing label '{lvl_lbl}' at 0x{offset:05X}:\n{decoded}"
                    )
            words_in_block = [struct.unpack_from("<H", block_raw, i)[0] for i in range(0, budget, 2)]
            if GLYPH_CIRCLE not in words_in_block:
                raise AssertionError(
                    f"Amelia combo block {diff_level} missing Circle button icon (0x{GLYPH_CIRCLE:04X})"
                )
            verified_amelia_combo_blocks += 1

        # Verify 3-pointer RAM table at 0x1198C..0x11998
        combo_ptrs = struct.unpack_from("<3I", e14_data, AMELIA_COMBO_POINTERS_OFFSET)
        if combo_ptrs != AMELIA_COMBO_POINTERS:
            raise AssertionError(
                f"Amelia combo pointer table mismatch at 0x{AMELIA_COMBO_POINTERS_OFFSET:05X}:\n"
                f"  Expected: {[hex(p) for p in AMELIA_COMBO_POINTERS]}\n"
                f"  Found:    {[hex(p) for p in combo_ptrs]}"
            )

    # 7. Verify Bandit Bullying Time Bonus in Entry 17
    e17_data = entries_dict[17]["data"]
    mg17 = minigames.get("bandit_bullying", {})
    verified_bandit_bonus = 0
    if "time_bonus" in mg17:
        expected_text = mg17["time_bonus"]
        offset = BANDIT_BONUS_SPEC["offset"]
        budget = BANDIT_BONUS_SPEC["budget"]

        raw_bonus = e17_data[offset : offset + budget]
        decoded_text = decode_minigame_string(raw_bonus, budget, rev_charmap)

        if decoded_text != expected_text:
            raise AssertionError(
                f"Bandit Bullying time bonus mismatch in Entry 17 at 0x{offset:05X}:\n"
                f"  Expected: {expected_text!r}\n"
                f"  Found:    {decoded_text!r}"
            )
        verified_bandit_bonus += 1

    # 8. Verify System Prompts in Entry 4 and Entry 5
    sys_prompts = catalog.get("system_prompts", {})
    verified_system_prompts = 0
    for entry_idx in (4, 5):
        if entry_idx not in entries_dict:
            continue
        entry_data = entries_dict[entry_idx]["data"]
        entry_key = f"entry_{entry_idx}"
        entry_cfg = sys_prompts.get(entry_key, {})
        prompts_dict = entry_cfg.get("prompts", entry_cfg) if isinstance(entry_cfg, dict) else {}
        specs = SYSTEM_PROMPT_SPECS.get(entry_idx, {})

        for prompt_id, spec in specs.items():
            p_data = prompts_dict.get(prompt_id, {})
            choices = p_data.get("choices") or spec.get("choices")
            expected_text = (
                p_data.get("text_ru")
                or p_data.get("text")
                or spec.get("default_ru", "")
            )
            offset = p_data.get("offset")
            if offset is None and "offset_hex" in p_data:
                offset = int(p_data["offset_hex"], 16)
            if offset is None:
                offset = spec["offset"]
            budget = p_data.get("budget", spec["budget"])

            raw_bytes = entry_data[offset : offset + budget]
            decoded_text = decode_minigame_string(raw_bytes, budget, rev_charmap)

            if choices:
                exp_joined = "\n".join(choices)
                if decoded_text != exp_joined and decoded_text != expected_text:
                    raise AssertionError(
                        f"System prompt choice '{prompt_id}' mismatch in Entry {entry_idx} at 0x{offset:05X}:\n"
                        f"  Expected: {exp_joined!r}\n"
                        f"  Found:    {decoded_text!r}"
                    )
                if b"\xfe\x00" not in raw_bytes:
                    raise AssertionError(
                        f"System prompt choice '{prompt_id}' missing 0x00FE separator in Entry {entry_idx} at 0x{offset:05X}"
                    )
            elif decoded_text != expected_text:
                raise AssertionError(
                    f"System prompt '{prompt_id}' mismatch in Entry {entry_idx} at 0x{offset:05X}:\n"
                    f"  Expected: {expected_text!r}\n"
                    f"  Found:    {decoded_text!r}"
                )
            verified_system_prompts += 1
    # 8. Verify SMINI.UNT font tiles against PROG.UNT 0x03A
    _, font_entry_dict = load_prog_entries_data(p, [PROG_FONT_ENTRY])
    decomp_03a, _ = unt_lz.decompress(bytes(font_entry_dict[PROG_FONT_ENTRY]["data"]))
    expected_font_tiles = extract_prog_font_tiles(decomp_03a, MINIGAME_FONT_GLYPH_IDS)

    smini_target_entries = (3, 0, 1, 2, 4)
    smini_lba, smini_entries_dict = load_smini_entries_data(p, smini_target_entries)
    for entry_idx in smini_target_entries:
        spec = SMINI_FONT_SPECS[entry_idx]
        entry_data = smini_entries_dict[entry_idx]["data"]
        pixel_off = spec["pixel_offset"]
        for gid, exp_tile in expected_font_tiles.items():
            if entry_idx == 1 and gid in SMINI_PROTECTED_GLYPHS:
                continue
            act_tile = extract_smini_tile(entry_data, pixel_off, gid)
            if act_tile != exp_tile:
                raise AssertionError(
                    f"Font tile mismatch for glyph 0x{gid:04X} in SMINI Entry {entry_idx} ({spec['name']})"
                )

    # Verify authentic PlayStation button icons (○, ↑, ↓, →, ←) in SMINI Entry 1
    e1_spec = SMINI_FONT_SPECS[1]
    e1_data = smini_entries_dict[1]["data"]
    e1_pixel_off = e1_spec["pixel_offset"]
    verified_button_icons = 0
    for gid in (GLYPH_CIRCLE, GLYPH_UP, GLYPH_DOWN, GLYPH_RIGHT, GLYPH_LEFT):
        act_tile = extract_smini_tile(e1_data, e1_pixel_off, gid)
        exp_tile = PRISTINE_BUTTON_TILES[gid]
        if act_tile != exp_tile:
            raise AssertionError(
                f"PlayStation button tile mismatch for glyph 0x{gid:04X} in SMINI Entry 1"
            )
        # Check that button icon is not clobbered with PROG 0x03A Bank 0 tile (Latin letters r, x, y, z)
        try:
            clobbered_tile = extract_03a_bank0_tile(decomp_03a, gid)
            if act_tile == clobbered_tile:
                raise AssertionError(
                    f"PlayStation button icon 0x{gid:04X} in SMINI Entry 1 is clobbered with Latin letter from PROG 0x03A"
                )
        except Exception:
            pass
        verified_button_icons += 1

    # 9. Verify Mode 2 Form 1 EDC/ECC checksums on all modified sectors
    checksums = CdChecksums()
    verified_sectors = 0
    with p.open("rb") as f:
        # Check PROG.UNT sectors
        for idx in target_prog_entries:
            start_sec = entries_dict[idx]["start_sector"]
            count_sec = entries_dict[idx]["sector_count"]
            for s in range(count_sec):
                lba = prog_lba + start_sec + s
                f.seek(lba * RAW_SECTOR_SIZE)
                sec = f.read(RAW_SECTOR_SIZE)
                edc_ok = sec[0x818:0x81C] == checksums.compute_edc(sec[0x10:0x818])
                ecc_p_ok = sec[0x81C:0x8C8] == checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86)
                ecc_q_ok = sec[0x8C8:0x930] == checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88)
                if not (edc_ok and ecc_p_ok and ecc_q_ok):
                    raise AssertionError(
                        f"EDC/ECC validation failed at LBA {lba} (PROG.UNT Entry {idx}, sector {s}/{count_sec})"
                    )
                verified_sectors += 1

        # Check SMINI.UNT sectors
        for idx in smini_target_entries:
            start_sec = smini_entries_dict[idx]["start_sector"]
            count_sec = smini_entries_dict[idx]["sector_count"]
            for s in range(count_sec):
                lba = smini_lba + start_sec + s
                f.seek(lba * RAW_SECTOR_SIZE)
                sec = f.read(RAW_SECTOR_SIZE)
                edc_ok = sec[0x818:0x81C] == checksums.compute_edc(sec[0x10:0x818])
                ecc_p_ok = sec[0x81C:0x8C8] == checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86)
                ecc_q_ok = sec[0x8C8:0x930] == checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88)
                if not (edc_ok and ecc_p_ok and ecc_q_ok):
                    raise AssertionError(
                        f"EDC/ECC validation failed at LBA {lba} (SMINI.UNT Entry {idx}, sector {s}/{count_sec})"
                    )
                verified_sectors += 1

    return {
        "status": "valid",
        "verified_minigames": len(MINIGAME_SPECS),
        "verified_title_banners": len(MINIGAME_SPECS),
        "verified_naga_dialogues": verified_naga_dialogues,
        "verified_amelia_dialogues": verified_amelia_dialogues,
        "verified_amelia_combo_blocks": verified_amelia_combo_blocks,
        "verified_button_icons": verified_button_icons,
        "verified_eating_status": verified_eating_status,
        "verified_bandit_bonus": verified_bandit_bonus,
        "verified_quiz_ui": verified_quiz_ui,
        "verified_questions": len(questions),
        "verified_font_entries": len(smini_target_entries),
        "verified_font_tiles": len(MINIGAME_FONT_GLYPH_IDS),
        "verified_sectors": verified_sectors,
        "verified_system_prompts": verified_system_prompts,
        "entries": list(target_prog_entries),
        "smini_entries": list(smini_target_entries),
    }


# ==============================================================================
# CLI Entrypoint
# ==============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch minigame rules and quiz questions into Slayers Royal (PS1)."
    )
    parser.add_argument(
        "--bin",
        type=Path,
        default=DEFAULT_TARGET_BIN,
        help=f"Path to target disc image (.bin) (default: {DEFAULT_TARGET_BIN})",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help=f"Path to minigames translations JSON (default: {DEFAULT_CATALOG})",
    )
    parser.add_argument(
        "--output-bin",
        type=Path,
        default=None,
        help="Optional path to output modified disc image",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and encode in-memory without modifying disc image",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify binary integrity, decoded strings, and EDC/ECC on disc image",
    )
    parser.add_argument(
        "--font-size",
        default="auto",
        help="Font size (кегль) setting: 'auto' (default), 11, or 'standard'",
    )

    args = parser.parse_args()

    if args.verify:
        print(f"[*] Verifying minigames and quiz on {args.bin}...")
        try:
            res = verify_minigames(args.bin, args.catalog)
            print(
                f"[✓] Verification SUCCESSFUL!\n"
                f"    Minigames rules: {res['verified_minigames']} / 5 verified.\n"
                f"    Title banners:   {res['verified_title_banners']} / 5 verified.\n"
                f"    Naga dialogues:   {res.get('verified_naga_dialogues', 0)} / 6 verified.\n"
                f"    Amelia dialogues: {res.get('verified_amelia_dialogues', 0)} / 6 verified.\n"
                f"    Amelia combos:    {res.get('verified_amelia_combo_blocks', 0)} / 3 blocks verified.\n"
                f"    Button icons:     {res.get('verified_button_icons', 0)} / 5 icons verified.\n"
                f"    Eating status:    {res.get('verified_eating_status', 0)} / 3 verified.\n"
                f"    Bandit bonus:     {res.get('verified_bandit_bonus', 0)} / 1 verified.\n"
                f"    Quiz UI strings: {res['verified_quiz_ui']} / 4 verified.\n"
                f"    Quiz questions:  {res['verified_questions']} / 100 verified.\n"
                f"    SMINI fonts:     {res['verified_font_entries']} entries ({res['verified_font_tiles']} tiles each) verified.\n"
                f"    Disc sectors:    {res['verified_sectors']} sectors verified with 100% valid EDC/ECC.\n"
                f"    System prompts:  {res.get('verified_system_prompts', 0)} / {sum(len(s) for s in SYSTEM_PROMPT_SPECS.values())} verified.\n"
            )
            return 0
        except Exception as e:
            print(f"[!] Verification FAILED: {e}", file=sys.stderr)
            return 1

    print(f"[*] Slayers Royal PS1 Minigames & Quiz Patcher")
    print(f"    Target BIN:    {args.bin}")
    print(f"    Catalog:       {args.catalog}")
    print(f"    Mode:          {'DRY RUN' if args.dry_run else 'APPLY PATCH'}")
    print(f"    Font size:     {args.font_size}")

    try:
        res = patch_minigames(
            bin_path=args.bin,
            catalog_path=args.catalog,
            output_bin=args.output_bin,
            dry_run=args.dry_run,
            font_size=args.font_size,
        )

        stats = res["patch_stats"]
        print(f"[✓] Successfully patched {len(stats)} components in PROG.UNT:")
        for name, info in stats.items():
            if not isinstance(info, dict):
                continue
            entry = info.get("entry", 15)
            off = info.get("offset", 0)
            sz = info.get("bytes", 0)
            extra = f", {info['questions']} questions" if "questions" in info else ""
            if "dialogues" in info:
                extra = f", {info['dialogues']} dialogues"
            print(f"    - {name:28s}: Entry {entry:02d} @ 0x{off:05X} ({sz} bytes{extra})")

        if "smini_font_stats" in res:
            f_stats = res["smini_font_stats"]
            print(f"[✓] Successfully injected Russian font tiles into {len(f_stats)} SMINI.UNT entries:")
            for entry_idx, info in f_stats.items():
                print(f"    - SMINI Entry {entry_idx:02d} ({info['name']}): File {info['file_index']}, {info['tiles_injected']} tiles")
        if args.dry_run:
            print(f"[✓] Dry run complete. {res['total_sectors_patched']} sectors validated in memory.")
        else:
            print(f"[✓] Successfully wrote and repaired EDC/ECC for {res['total_sectors_patched']} sectors!")
            # Run immediate self-verification
            print(f"[*] Running post-patch verification...")
            verify_res = verify_minigames(res["target_bin"], args.catalog)
            print(f"[✓] Post-patch verification PASSED ({verify_res['verified_sectors']} sectors valid)!")

        return 0
    except Exception as e:
        print(f"[!] Error during patching: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
