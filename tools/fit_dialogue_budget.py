"""Dialogue budget fitting optimizer for PlayStation 1 localized scenes.

Tightens multi-page dialogues in overflowing scenes to ensure every scene fits
within its pre-allocated hardware sector boundary: new_footer_end <= len(scene_data).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Mapping

# Ensure patch_repo and root are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from localization.cli import _apply_english_base, _load_workspace
from localization.disc import ENGLISH_PROG_SHA256, read_prog
from localization.glyphs import allocate_glyphs
from localization.po import PoEntry, write_po
from localization.script import (
    SCENE_ENTRIES,
    SPECIAL_ENTRIES,
    _patch_regular_scene,
    _patch_special_scene,
    expand_for_dialogue,
    parse_scene,
    parse_special,
    parse_target,
    read_entries,
    validate_catalog,
)
from tools.story_dialogue_overrides import POLISHED_OVERRIDES
from tools.text_wrapper import shorten_lines, wrap_dialogue


def tighten_entry_to_pages(text: str, max_pages: int, context: str) -> str:
    """Tighten multi-page dialogue text to at most max_pages."""
    if not text:
        return ""
    pages = text.split("\f")
    if len(pages) <= max_pages:
        return text

    if max_pages == 1:
        raw = " ".join(" ".join(p.splitlines()) for p in pages)
        result = wrap_dialogue(raw, allow_continuation=False)
        parse_target(result, 0x00FF, context)
        return result

    # max_pages == 2 (or more)
    all_lines = []
    for p in pages:
        all_lines.extend(p.splitlines())

    max_lines = max_pages * 3
    if len(all_lines) > max_lines:
        kept = all_lines[: max_lines - 1]
        last = all_lines[max_lines - 1]
        ellipsis = "..."
        max_prefix = 15 - len(ellipsis)
        if len(last) <= max_prefix:
            kept.append(last.rstrip(" ,.!?—") + ellipsis)
        else:
            cand = ""
            for w in last.split():
                test = (cand + " " + w).strip() if cand else w
                if len(test) <= max_prefix:
                    cand = test
                else:
                    break
            if not cand:
                cand = last[:max_prefix]
            kept.append(cand.rstrip(" ,.!?—") + ellipsis)
        all_lines = kept

    new_pages = []
    for i in range(0, len(all_lines), 3):
        new_pages.append("\n".join(all_lines[i : i + 3]))
    result = "\f".join(new_pages)
    parse_target(result, 0x00FD, context)
    return result


def tighten_entry_to_lines(text: str, max_lines: int, context: str) -> str:
    """Shorten single-page dialogue to max_lines."""
    result = shorten_lines(text, max_lines=max_lines)
    parse_target(result, 0x00FF, context)
    return result


def fit_scene_budget(
    source_bin: Path,
    workspace: Path,
    locale: str = "ru",
    dry_run: bool = False,
    verbose: bool = True,
) -> dict[str, object]:
    """Inspect and tighten dialogue in overflowing scenes so all scenes fit."""
    source_prog, language, catalog, state = _load_workspace(
        source_bin, workspace, locale, allow_incomplete=True
    )
    translations: dict[str, PoEntry] = dict(state["translations"])
    for ctx, ov_text in POLISHED_OVERRIDES.items():
        if ctx in translations:
            translations[ctx] = replace(translations[ctx], translation=ov_text)
    expanded = expand_for_dialogue(source_prog)
    entries = read_entries(expanded)

    # Temporary english base to allocate real glyphs and compact tokens
    descriptor, temporary_name = tempfile.mkstemp(prefix=".eng_base.", suffix=".bin")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        if verbose:
            print("Applying English base to inspect exact glyph and compact allocations...")
        _apply_english_base(source_bin, temporary)
        english_prog = read_prog(temporary, ENGLISH_PROG_SHA256)
    finally:
        temporary.unlink(missing_ok=True)

    def get_charmap_and_compact() -> tuple[dict[str, int], dict[str, int]]:
        charmap, compact, _ = allocate_glyphs(
            source_prog,
            english_prog,
            [e.translation for e in catalog],
            language,
            [
                e.translation
                for e in catalog
                if e.context.startswith("dialogue/03E/")
            ],
        )
        return charmap, compact

    charmap, compact = get_charmap_and_compact()

    scene_reports: list[dict[str, object]] = []
    modified_contexts: set[str] = set()

    for entry_index in SCENE_ENTRIES:
        entry = entries[entry_index]
        scene = parse_scene(entry, expanded)
        source = entry.extract(expanded)
        comp = compact if entry_index == 0x03E else {}
        allocated = len(source)

        # Check if scene already fits
        fits = False
        free_bytes = 0
        try:
            patched = _patch_regular_scene(source, scene, translations, charmap, comp)
            free_bytes = allocated - len(patched)
            fits = True
            status = "OK (initial)"
        except Exception as exc:
            status = str(exc)

        sc_entries = [
            e
            for e in catalog
            if e.context.startswith(f"dialogue/{entry_index:03X}/") and e.translation and e.context not in POLISHED_OVERRIDES
        ]

        if not fits:
            phase1_count = 0
            # Phase 1: Cap entries with > 2 pages to 2 pages
            for e in sc_entries:
                curr = translations[e.context].translation
                if len(curr.split("\f")) > 2:
                    new_val = tighten_entry_to_pages(curr, 2, e.context)
                    if new_val != curr:
                        translations[e.context] = replace(e, translation=new_val)
                        modified_contexts.add(e.context)
                        phase1_count += 1

            try:
                patched = _patch_regular_scene(
                    source, scene, translations, charmap, comp
                )
                free_bytes = allocated - len(patched)
                fits = True
                status = f"OK after Phase 1 (capped {phase1_count} entries to 2 pages)"
            except Exception:
                pass

        if not fits:
            # Phase 2: Progressively tighten 2-page entries to 1 page
            p2_candidates = [
                e
                for e in sc_entries
                if len(translations[e.context].translation.split("\f")) == 2
            ]
            p2_candidates.sort(
                key=lambda e: len(translations[e.context].translation), reverse=True
            )
            phase2_count = 0
            for e in p2_candidates:
                curr = translations[e.context].translation
                new_val = tighten_entry_to_pages(curr, 1, e.context)
                if new_val != curr:
                    translations[e.context] = replace(e, translation=new_val)
                    modified_contexts.add(e.context)
                    phase2_count += 1
                try:
                    patched = _patch_regular_scene(
                        source, scene, translations, charmap, comp
                    )
                    free_bytes = allocated - len(patched)
                    fits = True
                    status = (
                        f"OK after Phase 2 ({phase1_count} >2p, {phase2_count} 2p->1p)"
                    )
                    break
                except Exception:
                    continue

        if not fits:
            # Phase 3: Progressively shorten 3-line entries to 2 lines
            p3_candidates = [
                e
                for e in sc_entries
                if len(translations[e.context].translation.splitlines()) == 3
                and "\f" not in translations[e.context].translation
            ]
            p3_candidates.sort(
                key=lambda e: len(translations[e.context].translation), reverse=True
            )
            phase3_count = 0
            for e in p3_candidates:
                curr = translations[e.context].translation
                new_val = tighten_entry_to_lines(curr, 2, e.context)
                if new_val != curr:
                    translations[e.context] = replace(e, translation=new_val)
                    modified_contexts.add(e.context)
                    phase3_count += 1
                try:
                    patched = _patch_regular_scene(
                        source, scene, translations, charmap, comp
                    )
                    free_bytes = allocated - len(patched)
                    fits = True
                    status = (
                        f"OK after Phase 3 ({phase1_count} >2p, {phase2_count} 2p->1p, {phase3_count} 3L->2L)"
                    )
                    break
                except Exception:
                    continue

        if not fits:
            raise RuntimeError(f"Scene 0x{entry_index:03X} could not be fitted!")

        scene_reports.append(
            {
                "entry_index": f"0x{entry_index:03X}",
                "allocated_bytes": allocated,
                "free_bytes": free_bytes,
                "status": status,
                "fitted": fits,
            }
        )
        if verbose:
            print(f"Scene 0x{entry_index:03X} ({allocated} B): {status} (headroom: {free_bytes} B)")

    # Check special entries
    for special_index in SPECIAL_ENTRIES:
        entry = entries[special_index]
        scene = parse_special(entry, expanded)
        source = entry.extract(expanded)
        patched = _patch_special_scene(source, scene, translations, charmap, {})
        free_bytes = len(source) - len(patched)
        scene_reports.append(
            {
                "entry_index": f"0x{special_index:03X} (special)",
                "allocated_bytes": len(source),
                "free_bytes": free_bytes,
                "status": "OK",
                "fitted": True,
            }
        )
        if verbose:
            print(f"Special 0x{special_index:03X} ({len(source)} B): OK (headroom: {free_bytes} B)")

    # Build updated catalog
    updated_catalog = [translations.get(e.context, e) for e in catalog]

    # Validate catalog
    if verbose:
        print("Validating fitted catalog...")
    validate_catalog(source_prog, updated_catalog, allow_incomplete=True)
    if verbose:
        print(f"Validation PASSED! Modified {len(modified_contexts)} entries.")

    if not dry_run:
        po_path = workspace / "dialogue.po"
        if verbose:
            print(f"Writing fitted catalog to {po_path}...")
        write_po(po_path, updated_catalog, language=str(language["name"]))
        if verbose:
            print("Successfully updated dialogue.po.")

    return {
        "scenes": scene_reports,
        "modified_entries_count": len(modified_contexts),
        "total_scenes": len(scene_reports),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fit Russian dialogue into PS1 hardware scene sector budgets."
    )
    parser.add_argument(
        "--bin",
        type=Path,
        default=REPO_ROOT / "downloads" / "sr.bin",
        help="Path to source sr.bin",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=PATCH_REPO / "localization-work" / "ru",
        help="Path to localization workspace",
    )
    parser.add_argument(
        "--locale",
        default="ru",
        help="Target locale (default: ru)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect without writing dialogue.po",
    )
    args = parser.parse_args()

    report = fit_scene_budget(
        source_bin=args.bin.resolve(),
        workspace=args.workspace.resolve(),
        locale=args.locale,
        dry_run=args.dry_run,
        verbose=True,
    )
    print(
        f"Dialogue budget fitting complete: {report['total_scenes']} scenes verified, "
        f"{report['modified_entries_count']} entries tightened."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
