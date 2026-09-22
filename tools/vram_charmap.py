#!/usr/bin/env python3
"""Single source of truth for the runtime (PROG.UNT 0x03A) glyph map.

Why this module exists
----------------------
The English toolkit (``patch_repo/localization/glyphs.py``) allocates a font
cell for every non-Latin character **dynamically** at build time: it collects
every character used in the story catalogue plus ``language.json``
``required_characters``, sorts them by code point and hands out free cells in
that order.  Consequently the glyph ID of ``А`` depends on how many other
characters sort before it (``(``, ``)``, ``/``, ``~``, ``«``, ``»`` ...).  Add or
remove one such character anywhere in the story text and *every* Cyrillic
glyph ID shifts by one.  Any tool that hard-codes the IDs then silently emits
mojibake ("Пвже" instead of "Обед").

Rules enforced here:

* the map is **never** hard-coded in a tool; it is read from
  ``patch_repo/localization-work/ru/build/glyph_map.json`` (written by the
  last ``localize.py build``) or from the committed snapshot
  ``translations/glyph_map_ru.json``;
* if both exist they must agree, otherwise the build stops with an explanation
  (that is the drift this module is designed to catch);
* a character with no glyph is a hard error; the message lists the offending
  characters and where they came from.

CLI::

    python3 tools/vram_charmap.py --check               # drift check
    python3 tools/vram_charmap.py --refresh-snapshot    # live -> snapshot
    python3 tools/vram_charmap.py --print               # dump the map
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
LIVE_GLYPH_MAP = PATCH_REPO / "localization-work" / "ru" / "build" / "glyph_map.json"
SNAPSHOT_GLYPH_MAP = REPO_ROOT / "translations" / "glyph_map_ru.json"
ENV_OVERRIDE = "SLAYERS_GLYPH_MAP"

# Control words shared by every 16-bit text consumer of the main font.
CHAR_NEWLINE = 0x00FE
CHAR_PAGE_CONTINUE = 0x00FD
CHAR_STRING_TERMINATOR = 0x00FF
SPACE_GLYPH = 0x007D

# Cells owned by the English release.  These are *static*: the English patch
# fixes them, and the toolkit reserves them (``BASE_CHAR_TO_GLYPH``).  They are
# duplicated here only so that tools can encode ASCII when the toolkit is not
# importable; ``load_vram_charmap`` prefers the toolkit's own table.
_LOWERCASE_GLYPHS = (
    0x0017, 0x0031, 0x003A, 0x0040, 0x0048, 0x004A, 0x004B,
    0x004D, 0x004F, 0x0055, 0x005F, 0x0060, 0x0062, 0x0063,
    0x0067, 0x0068, 0x0069, 0x006B, 0x006D, 0x006E, 0x006F,
    0x0070, 0x0071, 0x0074, 0x0075, 0x0076,
)
FALLBACK_BASE_CHARMAP: dict[str, int] = {
    **{chr(ord("a") + i): g for i, g in enumerate(_LOWERCASE_GLYPHS)},
    "A": 0x00BE, "B": 0x014C, "C": 0x0128, "D": 0x00BF, "E": 0x00B6,
    "F": 0x014D, "G": 0x0088, "H": 0x0091, "I": 0x0081, "J": 0x014F,
    "K": 0x0192, "L": 0x0082, "M": 0x0148, "N": 0x0086, "O": 0x00BB,
    "P": 0x019B, "Q": 0x01A7, "R": 0x0099, "S": 0x0090, "T": 0x008D,
    "U": 0x01D2, "V": 0x00BD, "W": 0x008E, "X": 0x01FD, "Y": 0x009A,
    "Z": 0x0209, "'": 0x031B,
    " ": SPACE_GLYPH,
    ",": 0x00A1, ".": 0x00A2, "-": 0x00A4, "!": 0x00A6, "?": 0x00A7,
    ":": 0x00BC, "♥": 0x00B4, "♪": 0x00B5,
    **{str(v): 0x00A8 + v for v in range(10)},
}


class GlyphMapError(RuntimeError):
    """Raised when no trustworthy glyph map is available or it drifted."""


def _toolkit_base_charmap() -> dict[str, int]:
    """Return the toolkit's ``BASE_CHAR_TO_GLYPH`` if importable, else the copy above."""
    for root in (PATCH_REPO,):
        if str(root) not in sys.path and root.is_dir():
            sys.path.insert(0, str(root))
    try:
        from localization.glyphs import BASE_CHAR_TO_GLYPH  # type: ignore
    except Exception:
        return dict(FALLBACK_BASE_CHARMAP)
    base = dict(BASE_CHAR_TO_GLYPH)
    base.setdefault(" ", SPACE_GLYPH)
    return base


def _read_glyph_map_file(path: Path) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "characters" not in data:
        raise GlyphMapError(f"{path} is not a toolkit glyph_map.json (no 'characters')")
    return {item["text"]: int(item["glyph"], 16) for item in data["characters"]}


def glyph_map_sources() -> tuple[Path | None, Path | None, Path | None]:
    """Return (override, live, snapshot) paths that exist (None when absent)."""
    override = os.environ.get(ENV_OVERRIDE)
    override_path = Path(override) if override else None
    if override_path is not None and not override_path.is_file():
        raise GlyphMapError(f"{ENV_OVERRIDE}={override_path} does not exist")
    live = LIVE_GLYPH_MAP if LIVE_GLYPH_MAP.is_file() else None
    snap = SNAPSHOT_GLYPH_MAP if SNAPSHOT_GLYPH_MAP.is_file() else None
    return override_path, live, snap


def load_glyph_map(path: str | os.PathLike[str] | None = None) -> dict[str, int]:
    """Return {character: glyph_id} for the locale characters.

    Resolution order: explicit ``path`` > ``$SLAYERS_GLYPH_MAP`` > live build
    output > committed snapshot.  When both the live file and the snapshot are
    present they must be identical for every character present in either.
    """
    if path is not None:
        return _read_glyph_map_file(Path(path))
    override, live, snap = glyph_map_sources()
    if override is not None:
        return _read_glyph_map_file(override)
    if live is None and snap is None:
        raise GlyphMapError(
            "no glyph map available: run the story build first "
            f"(writes {LIVE_GLYPH_MAP}) or restore the snapshot {SNAPSHOT_GLYPH_MAP}"
        )
    if live is not None and snap is not None:
        live_map = _read_glyph_map_file(live)
        snap_map = _read_glyph_map_file(snap)
        drift = sorted(
            (ch, live_map.get(ch), snap_map.get(ch))
            for ch in set(live_map) | set(snap_map)
            if live_map.get(ch) != snap_map.get(ch)
        )
        if drift:
            preview = ", ".join(
                f"{ch!r}: live={'-' if a is None else f'0x{a:04X}'} "
                f"snapshot={'-' if b is None else f'0x{b:04X}'}"
                for ch, a, b in drift[:8]
            )
            raise GlyphMapError(
                "glyph map drift: the font written by the last story build no "
                "longer matches translations/glyph_map_ru.json "
                f"({len(drift)} characters differ: {preview}). The story text "
                "gained or lost a character that sorts before the Cyrillic block, "
                "which shifted every glyph ID. If the new font is intended, run "
                "'python3 tools/vram_charmap.py --refresh-snapshot' and rebuild "
                "every menu/inspection/minigame patch; otherwise revert the text."
            )
        return live_map
    return _read_glyph_map_file(live or snap)  # type: ignore[arg-type]


def load_vram_charmap(path: str | os.PathLike[str] | None = None) -> dict[str, int]:
    """Full encoder map for the runtime font: English base cells + locale cells."""
    charmap = _toolkit_base_charmap()
    locale = load_glyph_map(path)
    for ch, glyph in locale.items():
        charmap[ch] = glyph
    charmap[" "] = SPACE_GLYPH
    return charmap


def missing_characters(text: Iterable[str], charmap: Mapping[str, int]) -> list[str]:
    """Characters of ``text`` that have no glyph (control characters excluded)."""
    seen: list[str] = []
    for ch in text:
        if ch in ("\n", "\r", "\f") or ch in charmap or ch in seen:
            continue
        seen.append(ch)
    return seen


def assert_encodable(text: str, charmap: Mapping[str, int], where: str = "") -> None:
    """Raise ``GlyphMapError`` naming every character of ``text`` without a glyph.

    Hex escapes of the form ``<XXXX>`` are engine words and are skipped.
    """
    stripped = []
    i = 0
    while i < len(text):
        if text[i] == "<" and i + 5 < len(text) and text[i + 5] == ">":
            i += 6
            continue
        stripped.append(text[i])
        i += 1
    missing = missing_characters(stripped, charmap)
    if missing:
        listing = ", ".join(f"{ch!r} (U+{ord(ch):04X})" for ch in missing)
        raise GlyphMapError(
            f"{where + ': ' if where else ''}no runtime glyph for {listing}. "
            "Either replace the character in the catalogue or add it to "
            "'required_characters' in translations/language_ru.json and rebuild "
            "the story (that reallocates the font; refresh the snapshot afterwards)."
        )


def locale_characters(path: str | os.PathLike[str] | None = None) -> dict[str, int]:
    """Only the characters the toolkit allocated for the locale (English base cells excluded)."""
    base = _toolkit_base_charmap()
    return {ch: g for ch, g in load_glyph_map(path).items() if base.get(ch) != g}


def max_locale_glyph(charmap: Mapping[str, int] | None = None) -> int:
    """Highest glyph ID handed to a locale character (for range guards)."""
    locale = locale_characters() if charmap is None else charmap
    return max(locale.values()) if locale else 0


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="verify live map and snapshot agree")
    parser.add_argument("--refresh-snapshot", action="store_true", help="copy the live map over the snapshot")
    parser.add_argument("--print", action="store_true", help="print the resolved map")
    args = parser.parse_args()
    override, live, snap = glyph_map_sources()
    if args.refresh_snapshot:
        if live is None:
            print(f"error: {LIVE_GLYPH_MAP} does not exist; run the story build first", file=sys.stderr)
            return 1
        SNAPSHOT_GLYPH_MAP.write_bytes(live.read_bytes())
        print(f"snapshot refreshed from {live}")
        return 0
    try:
        charmap = load_vram_charmap()
    except GlyphMapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    source = override or live or snap
    locale = locale_characters()
    print(f"glyph map source: {source} ({len(locale)} locale characters, highest locale glyph 0x{max_locale_glyph(locale):04X})")
    if args.print:
        for ch, glyph in sorted(charmap.items(), key=lambda kv: kv[1]):
            print(f"  0x{glyph:04X}  {ch!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
