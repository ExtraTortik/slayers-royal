#!/usr/bin/env python3
"""Run the English toolkit's story build with the Russian port's settings.

The upstream toolkit (``patch_repo`` = gourry-hacks/slayers_royal_1_patch) is
used **unmodified**.  Everything the port needs on top of it lives in this
repository and is applied here:

* ``translations/language_ru.json``      -> workspace ``language.json``
  (required characters, compact-glyph limit, ISO data-preparer string);
* ``translations/scene_expansion_ru.json`` -> extra PROG.UNT sectors per story
  scene, borrowed from donor entry 0x011 (the toolkit's default table is sized
  for English text and the Russian text is longer);
* ``translations/story_dialogues_ru.json`` -> ``dialogue.po`` via
  ``tools/sync_story_dialogues.py``.

Sub-commands::

    python3 tools/localize_ru.py build    --bin downloads/sr.bin --output-dir localization-output/ru
    python3 tools/localize_ru.py measure  --bin downloads/sr.bin      # print needed sectors per scene
    python3 tools/localize_ru.py validate --bin downloads/sr.bin

The workspace (``patch_repo/localization-work/ru``) is created on first use.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
PATCH_REPO = REPO_ROOT / "patch_repo"
WORKSPACE = PATCH_REPO / "localization-work" / "ru"
LANGUAGE_PRESET = REPO_ROOT / "translations" / "language_ru.json"
EXPANSION_FILE = REPO_ROOT / "translations" / "scene_expansion_ru.json"
STORY_JSON = REPO_ROOT / "translations" / "story_dialogues_ru.json"
SYNC_TOOL = REPO_ROOT / "tools" / "sync_story_dialogues.py"

MAX_SCENE_SECTORS = 19  # 0x9800 bytes: scene at 0x80121000, container 0x058 at 0x8012A800


def _require_patch_repo() -> None:
    if not (PATCH_REPO / "localization" / "cli.py").is_file():
        raise SystemExit(
            f"error: {PATCH_REPO} is missing or incomplete.\n"
            "Clone https://github.com/gourry-hacks/slayers_royal_1_patch into patch_repo/ "
            "(or symlink an existing checkout there)."
        )
    if str(PATCH_REPO) not in sys.path:
        sys.path.insert(0, str(PATCH_REPO))
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

def _load_expansion() -> dict[int, int]:
    doc = json.loads(EXPANSION_FILE.read_text(encoding="utf-8"))
    table = {int(k, 16): int(v) for k, v in doc["expansion_sectors"].items()}
    limit = int(doc.get("max_scene_sectors", MAX_SCENE_SECTORS))
    if limit != MAX_SCENE_SECTORS:
        raise SystemExit(f"error: {EXPANSION_FILE} max_scene_sectors must be {MAX_SCENE_SECTORS}")
    return table


def _relayout_copy_dialogue_entries(localized: bytes, english: bytes) -> bytes:
    """Merge localized story scenes into the English archive with the localized layout.

    The upstream ``copy_dialogue_entries`` requires both archives to share one
    expansion table.  The Russian text needs more sectors than the English
    release, so the English archive is re-laid out here: every non-story entry
    keeps its English payload (the donor 0x011 just loses more of its zero
    tail), story entries take the localized payload, and the index is rebuilt.
    """
    from localization import script  # type: ignore

    loc_entries = script.read_entries(localized)
    eng_entries = script.read_entries(english)
    if len(loc_entries) != len(eng_entries):
        raise script.ScriptError("localized and English PROG entry counts differ")
    story = set(script.SCENE_ENTRIES) | set(script.SPECIAL_ENTRIES)
    result = bytearray(localized[: script.SECTOR_SIZE])
    start_sector = 1
    for index, (loc, eng) in enumerate(zip(loc_entries, eng_entries)):
        if index in story:
            payload = loc.extract(localized)
        else:
            payload = eng.extract(english)
            if loc.sector_count < eng.sector_count:
                cut = payload[loc.size :]
                if any(cut):
                    raise script.ScriptError(
                        f"PROG entry {index:03X} would lose non-zero data while re-laying out"
                    )
                payload = payload[: loc.size]
            elif loc.sector_count > eng.sector_count:
                raise script.ScriptError(
                    f"PROG entry {index:03X} is larger in the localized layout than in English"
                )
        count = len(payload) // script.SECTOR_SIZE
        offset = index * 4
        result[offset : offset + 2] = start_sector.to_bytes(2, "little")
        result[offset + 2 : offset + 4] = count.to_bytes(2, "little")
        result.extend(payload)
        start_sector += count
    if len(result) != len(english):
        raise script.ScriptError("re-laid PROG.UNT changed size")
    return bytes(result)


def _install_expansion(table: dict[int, int]) -> None:
    from localization import script, cli  # type: ignore

    script.DEFAULT_EXPANSION_SECTORS = dict(table)
    if hasattr(script, "EXTRA_EXPANSION_SECTORS"):
        script.EXTRA_EXPANSION_SECTORS.clear()
    if hasattr(cli, "EXTRA_EXPANSION_SECTORS"):
        cli.EXTRA_EXPANSION_SECTORS.clear()
    cli.copy_dialogue_entries = _relayout_copy_dialogue_entries

def ensure_workspace(source_bin: Path) -> None:
    """Create/refresh the PO workspace from the repository catalogues."""
    _require_patch_repo()
    po = WORKSPACE / "dialogue.po"
    if not po.is_file():
        print(f"[*] exporting Japanese source catalogue into {WORKSPACE} ...")
        subprocess.run(
            [sys.executable, str(PATCH_REPO / "localize.py"), "export",
             "--bin", str(source_bin), "--locale", "ru", "--output", str(WORKSPACE), "--force"],
            check=True,
        )
        subprocess.run(
            [sys.executable, str(SYNC_TOOL), "--apply", "--po", str(po), "--json", str(STORY_JSON)],
            check=True,
        )
    else:
        subprocess.run(
            [sys.executable, str(SYNC_TOOL), "--sync-if-newer", "--po", str(po), "--json", str(STORY_JSON)],
            check=True,
        )
    preset = json.loads(LANGUAGE_PRESET.read_text(encoding="utf-8"))
    (WORKSPACE / "language.json").write_text(
        json.dumps(preset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def measure(source_bin: Path) -> dict[int, int]:
    """Return {scene_entry: extra_sectors} needed by the current catalogue."""
    _require_patch_repo()
    from localization import script, glyphs  # type: ignore
    from localization.po import read_po  # type: ignore
    from localization.disc import read_extent  # type: ignore
    from tools.patch_inspection import parse_iso_dir, read_sector  # type: ignore
    import struct

    def prog_of(path: Path) -> bytes:
        pvd = read_sector(path, 16)
        root_lba = struct.unpack_from("<I", pvd, 158)[0]
        root_size = struct.unpack_from("<I", pvd, 166)[0]
        lba, size = parse_iso_dir(path, root_lba, root_size)["PROG.UNT"]
        return read_extent(path, lba, size)

    src = prog_of(source_bin)
    english_bin = WORKSPACE.parent.parent / "localization-output" / "ru" / "slayers_royal_ru.bin"
    catalog = read_po(WORKSPACE / "dialogue.po")
    translations = script.validate_catalog(src, catalog, True)
    language = json.loads((WORKSPACE / "language.json").read_text(encoding="utf-8"))
    # Glyph IDs do not influence byte counts (every glyph is one 16-bit word),
    # so a provisional map is enough for measuring.
    charmap = dict(glyphs.BASE_CHAR_TO_GLYPH)
    chars = sorted(set("".join(e.translation for e in catalog) + language["required_characters"]) - {"\n", "\r", "\f"})
    next_id = 1
    for ch in chars:
        if ch not in charmap:
            charmap[ch] = next_id
            next_id += 1
    entries = script.read_entries(src)
    needed: dict[int, int] = {}
    for idx in script.SCENE_ENTRIES:
        entry = entries[idx]
        scene = script.parse_scene(entry, src)
        data = entry.extract(src)
        try:
            script._patch_regular_scene(data, scene, translations, charmap, {})
            over = 0
        except script.ScriptError as exc:
            match = re.search(r"by 0x([0-9A-F]+)", str(exc))
            if not match:
                raise
            over = int(match.group(1), 16)
        extra = math.ceil(over / 2048) if over else 0
        total = entry.sector_count + extra
        flag = "  <-- exceeds runtime ceiling!" if total > MAX_SCENE_SECTORS else ""
        print(f"0x{idx:03X}: {entry.sector_count:2d} + {extra} = {total:2d} sectors{flag}")
        if extra:
            needed[idx] = extra
    print(f"total extra sectors: {sum(needed.values())}")
    del english_bin
    return needed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "validate", "measure"):
        p = sub.add_parser(name)
        p.add_argument("--bin", type=Path, required=True, help="original Japanese sr.bin")
        if name == "build":
            p.add_argument("--output-dir", type=Path, required=True)
            p.add_argument("--allow-incomplete", action="store_true")
        if name == "measure":
            p.add_argument("--write", action="store_true", help="update translations/scene_expansion_ru.json")
    args = parser.parse_args()

    ensure_workspace(args.bin)
    if args.command == "measure":
        needed = measure(args.bin)
        over = [f"0x{k:03X}" for k, v in needed.items()]
        if args.write:
            doc = json.loads(EXPANSION_FILE.read_text(encoding="utf-8"))
            doc["expansion_sectors"] = {f"0x{k:03X}": v for k, v in sorted(needed.items())}
            EXPANSION_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"wrote {EXPANSION_FILE}")
        return 0

    table = _load_expansion()
    _install_expansion(table)
    from localization.cli import main as toolkit_main  # type: ignore

    argv = [args.command, "--bin", str(args.bin), "--locale", "ru", "--workspace", str(WORKSPACE)]
    if args.command == "build":
        argv += ["--output-dir", str(args.output_dir), "--force"]
        if args.allow_incomplete:
            argv.append("--allow-incomplete")
    sys.argv = ["localize.py", *argv]
    return int(toolkit_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
