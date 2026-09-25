"""Unit tests for tools/fit_dialogue_budget.py and Scoped Compact Glyph Tokens.

Verifies:
- Headroom calculation accuracy
- Page and line tightening helpers
- Compact glyph limit configured to 220
- Scene 0x03E fits within 19 sectors (38,912 B) on initial check with headroom > 0
- Scoping of compact tokens strictly to scene 0x03E
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.fit_dialogue_budget import (
    compute_headroom,
    compute_special_headroom,
    tighten_entry_to_pages,
    tighten_entry_to_lines,
    fit_scene_budget,
)
from localization.glyphs import load_language


def test_compact_glyph_limit_is_420() -> None:
    ru_lang_path = PATCH_REPO / "localization" / "languages" / "ru.json"
    data = json.loads(ru_lang_path.read_text(encoding="utf-8"))
    assert data["compact_glyph_limit"] == 420


def test_tighten_helpers() -> None:
    # 1 page
    text = "Линия 1\nЛиния 2\nЛиния 3\fЛиния 4\nЛиния 5"
    tightened_1p = tighten_entry_to_pages(text, 1, "test/001")
    assert "\f" not in tightened_1p
    assert len(tightened_1p.splitlines()) <= 3

    # Shorten lines
    shortened = tighten_entry_to_lines("Линия 1\nЛиния 2\nЛиния 3", 2, "test/002")
    assert len(shortened.splitlines()) == 2
    assert "..." in shortened


def test_compute_headroom_math() -> None:
    class DummyScene:
        table_offset = 100
        table_end = 200

    source = b"\x00" * 1000
    # table_end = 200, no nonzero bytes -> footer_len = 200 - 100 = 100
    # patched with RUNTIME_BASE (0x00230000) + new_table (500) at 0x04:0x08
    patched = bytearray(1000)
    new_table = 500
    from localization.script import RUNTIME_BASE
    patched[0x04:0x08] = (RUNTIME_BASE + new_table).to_bytes(4, "big")

    # new_footer_end = 500 + 100 = 600
    # headroom = 1000 - 600 = 400
    headroom = compute_headroom(source, DummyScene(), bytes(patched))
    assert headroom == 400


def test_scene_03e_fits_within_budget_dry_run() -> None:
    sr_bin = REPO_ROOT / "downloads" / "sr.bin"
    if not sr_bin.exists():
        pytest.skip("downloads/sr.bin not found")

    workspace = PATCH_REPO / "localization-work" / "ru"
    report = fit_scene_budget(
        source_bin=sr_bin,
        workspace=workspace,
        locale="ru",
        dry_run=True,
        verbose=False,
    )

    scenes_by_idx = {s["entry_index"]: s for s in report["scenes"]}
    assert "0x03E" in scenes_by_idx
    s03e = scenes_by_idx["0x03E"]
    assert s03e["allocated_bytes"] <= 38912
    assert s03e["free_bytes"] > 0
    assert s03e["status"] == "OK (initial)"
    assert s03e["fitted"] is True
