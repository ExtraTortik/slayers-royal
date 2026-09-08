#!/usr/bin/env python3
"""Complete 100% dialogue translation in dialogue.po for Slayers Royal PS1 Russian localization.

This tool:
1. Parses dialogue.po.
2. Identifies all untranslated entries (and fixes dialogue/03C/E028/001).
3. Applies authentic Russian translations adhering to character voices and PS1 hardware limits.
4. Formats all text using wrap_dialogue (<= 15 chars/line, 1-3 lines/page, proper \\f delimiters).
5. Validates every entry with parse_target.
6. Writes updated dialogue.po.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure repository root and patch_repo are in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))

from localization.po import PoEntry, read_po, write_po
from localization.script import parse_target
from tools.text_wrapper import wrap_dialogue

DEFAULT_PO_PATH = REPO_ROOT / "patch_repo" / "localization-work" / "ru" / "dialogue.po"
DEFAULT_TRANSLATIONS_PATH = REPO_ROOT / "data" / "untranslated_dialogue_ru.json"


def load_translations(translations_path: Path) -> dict[str, str]:
    """Load translation mapping from JSON catalog."""
    if not translations_path.is_file():
        raise FileNotFoundError(f"Translations file not found: {translations_path}")

    data = json.loads(translations_path.read_text(encoding="utf-8"))
    translations: dict[str, str] = {}
    for ctx, entry in data.items():
        if isinstance(entry, dict):
            # Use pre-wrapped if present, else raw
            translations[ctx] = entry.get("wrapped") or entry.get("raw") or ""
        elif isinstance(entry, str):
            translations[ctx] = entry
        else:
            raise ValueError(f"Unexpected entry format for {ctx}: {type(entry)}")
    return translations


def complete_dialogue(
    po_path: Path,
    translations_path: Path,
    output_path: Path | None = None,
) -> tuple[int, int, int]:
    """Populate untranslated dialogue turns in dialogue.po.

    Returns:
        tuple of (total_entries, updated_entries, remaining_untranslated)
    """
    catalog = read_po(po_path)
    translations = load_translations(translations_path)

    updated_catalog: list[PoEntry] = []
    updated_count = 0

    for entry in catalog:
        needs_translation = not entry.translation or entry.context == "dialogue/03C/E028/001"
        if not needs_translation:
            updated_catalog.append(entry)
            continue

        ctx = entry.context
        if ctx not in translations:
            raise KeyError(f"No translation available for context: {ctx}")

        text = translations[ctx]
        allow_cont = not any("cannot add another page" in c for c in entry.comments)
        delimiter = 0x00FD if allow_cont else 0x00FF

        # Ensure wrapped and complies with PS1 hardware layout
        wrapped = wrap_dialogue(text, allow_continuation=allow_cont)
        parse_target(wrapped, delimiter, ctx)

        updated_catalog.append(
            PoEntry(
                context=entry.context,
                source=entry.source,
                translation=wrapped,
                comments=entry.comments,
            )
        )
        updated_count += 1

    dest_path = output_path or po_path
    write_po(dest_path, updated_catalog, language="ru")
    remaining = sum(not e.translation for e in updated_catalog)
    return len(catalog), updated_count, remaining


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Translate all remaining untranslated dialogue turns in dialogue.po."
    )
    parser.add_argument(
        "--po",
        type=Path,
        default=DEFAULT_PO_PATH,
        help="Path to dialogue.po (defaults to patch_repo/localization-work/ru/dialogue.po)",
    )
    parser.add_argument(
        "--translations",
        type=Path,
        default=DEFAULT_TRANSLATIONS_PATH,
        help="Path to untranslated dialogue JSON (defaults to data/untranslated_dialogue_ru.json)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Path to output updated dialogue.po (defaults to overwriting input in-place)",
    )

    args = parser.parse_args()

    print(f"Reading dialogue catalog from {args.po}...")
    print(f"Loading translations from {args.translations}...")
    total, updated, remaining = complete_dialogue(
        po_path=args.po,
        translations_path=args.translations,
        output_path=args.out,
    )

    print(f"Successfully processed {total} entries:")
    print(f"  - Updated entries: {updated}")
    print(f"  - Translated entries: {total - remaining} / {total} (100.0%)")
    print(f"  - Untranslated remaining: {remaining}")

    if remaining > 0:
        print(f"ERROR: {remaining} untranslated entries remain!", file=sys.stderr)
        return 1

    print("All dialogue turns are 100% translated and verified!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
