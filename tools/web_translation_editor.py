#!/usr/bin/env python3
"""Slayers Royal (PS1) — Modern Web-based Translation Editor & Hardware Limits Engine.

Features:
- REST API and embedded Single Page Application (SPA) with sleek Dark Mode & PS1 retro aesthetic.
- Supports all 11 translation catalogs in translations/:
  * story_dialogues_ru.json (4,514 dialogues, 30 scenes)
  * combat_dialogues_ru.json (114 blocks, 264 bubbles)
  * room_inspection_ru.json (149 rooms, 734 entries)
  * room_names_ru.json (160 rooms)
  * minigames_ru.json (rules, quiz, system prompts)
  * town_services_ru.json (tavern, inn, icons, menus)
  * shop_dialogues_ru.json (98 dialogues + 91 shop items)
  * world_map_ru.json (20 locations)
  * location_banners_ru.json (23 banners)
  * lore_cards_ru.json (13 lore cards)
  * spells_ru.json (119 spells & combat menu)
- Real-time Hardware Limits Engine with line-by-line char counter, line count, control codes validation.
- "Issues / Needs Fixing" Dashboard with 1-click jump to edit.
- Live PS1 Dialogue Box preview simulating the 16x16 pixel display.
- Atomic disk save with Ctrl+S / Cmd+S shortcut.
- Integration with ./build.sh --validate runner.
- Zero external pip dependencies required (Python standard library only).
"""

from __future__ import annotations

import argparse
import copy
import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Base repository directory
REPO_ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS_DIR = REPO_ROOT / "translations"

# Regex for escape tags like <00BF>
TAG_RE = re.compile(r"<[0-9A-Fa-f]{4}>")

# Catalog definitions and their hardware constraints
CATALOG_DEFS: dict[str, dict[str, Any]] = {
    "story_dialogues": {
        "file": "story_dialogues_ru.json",
        "title": "Сюжетные диалоги",
        "badge": "4,514 реплик / 30 сцен",
        "icon": "💬",
        "description": "Сюжетные реплики, сцены, развилки и диалоги NPC (PROG.UNT 0x03B..0x057)",
        "limits": {
            "max_chars_per_line": 15,
            "min_lines_per_page": 1,
            "max_lines_per_page": 3,
            "allow_page_break": True,
            "single_line": False,
            "ignore_tags": False,
        },
    },
    "combat_dialogues": {
        "file": "combat_dialogues_ru.json",
        "title": "Боевые диалоги",
        "badge": "114 блоков",
        "icon": "⚔️",
        "description": "Боевые реплики персонажей и диалоговые оверлеи (PROG.UNT 0x007, шрифт 0x142)",
        "limits": {
            "max_chars_per_line": 21,
            "min_lines_per_page": 1,
            "max_lines_per_page": 3,
            "allow_page_break": True,
            "single_line": False,
            "ignore_tags": False,
        },
    },
    "room_inspection": {
        "file": "room_inspection_ru.json",
        "title": "Осмотр комнат",
        "badge": "149 комнат / 734 реплики",
        "icon": "🔍",
        "description": "Тексты осмотра предметов и окружения в комнатах (PROG.UNT 0x059..0x0EE)",
        "limits": {
            "max_chars_per_line": 15,
            "min_lines_per_page": 1,
            "max_lines_per_page": 3,
            "allow_page_break": False,
            "single_line": False,
            "ignore_tags": False,
        },
    },
    "room_names": {
        "file": "room_names_ru.json",
        "title": "Названия комнат",
        "badge": "160 локаций",
        "icon": "🚪",
        "description": "Названия комнат для баннера локации 160px (PROG.UNT 0x059..0x0F8)",
        "limits": {
            "max_chars_total": 10,
            "single_line": True,
            "allow_page_break": False,
            "ignore_tags": False,
        },
    },
    "minigames": {
        "file": "minigames_ru.json",
        "title": "Мини-игры и викторина",
        "badge": "5 игр / 100 вопросов",
        "icon": "🎮",
        "description": "Правила 5 мини-игр, 100 вопросов викторины и системные подсказки (PROG.UNT 13..17)",
        "limits": {
            "max_chars_per_line": 20,
            "max_lines": 10,
            "max_lines_per_page": 10,
            "allow_page_break": True,
            "single_line": False,
            "ignore_tags": False,
        },
    },
    "town_services": {
        "file": "town_services_ru.json",
        "title": "Городские службы",
        "badge": "Таверна / Отель / Меню",
        "icon": "🍺",
        "description": "Меню таверны, ночлег в гостинице, иконки городских служб и диалоги покупки",
        "limits": {
            "allow_page_break": True,
            "single_line": False,
            "ignore_tags": False,
        },
    },
    "shop_dialogues": {
        "file": "shop_dialogues_ru.json",
        "title": "Магазины и товары",
        "badge": "98 диалогов / 91 товар",
        "icon": "🛍️",
        "description": "Диалоги торговцев, торг персонажей и 91 название товаров лавки (PROG.UNT 0x003)",
        "limits": {
            "max_chars_per_line": 15,
            "min_lines_per_page": 1,
            "max_lines_per_page": 3,
            "allow_page_break": True,
            "single_line": False,
            "ignore_tags": True,
        },
    },
    "world_map": {
        "file": "world_map_ru.json",
        "title": "Карта мира",
        "badge": "20 локаций",
        "icon": "🗺️",
        "description": "Названия локаций на глобальной карте мира (PROG.UNT 0x001)",
        "limits": {
            "max_chars_total": 14,
            "single_line": True,
            "allow_page_break": False,
            "ignore_tags": False,
        },
    },
    "location_banners": {
        "file": "location_banners_ru.json",
        "title": "Вывески локаций",
        "badge": "23 плашки",
        "icon": "🏷️",
        "description": "Графические плашки и вывески в городах (BASYOG.UNT Entry 466)",
        "limits": {
            "max_chars_total": 12,
            "single_line": True,
            "allow_page_break": False,
            "ignore_tags": False,
        },
    },
    "lore_cards": {
        "file": "lore_cards_ru.json",
        "title": "Справочные карточки",
        "badge": "13 персонажей и лора",
        "icon": "📜",
        "description": "Справочные карточки персонажей (PROG.UNT) и заголовки галереи (OPT.UNT)",
        "limits": {
            "max_chars_per_line": 45,
            "max_lines": 10,
            "max_lines_per_page": 10,
            "allow_page_break": False,
            "single_line": False,
            "allow_empty_lines": True,
            "ignore_tags": False,
        },
    },
    "spells": {
        "file": "spells_ru.json",
        "title": "Заклинания и магия",
        "badge": "119 заклинаний",
        "icon": "✨",
        "description": "Описания и названия заклинаний в бою (PROG.UNT 325..443, Entry 0x007)",
        "limits": {
            "max_chars_per_line": 38,
            "min_lines_per_page": 1,
            "max_lines_per_page": 3,
            "allow_page_break": True,
            "single_line": False,
            "ignore_tags": False,
        },
    },
}

# Speaker colors for UI
SPEAKER_COLORS: dict[str, str] = {
    "Lina": "#ef4444",
    "Лина": "#ef4444",
    "Gourry": "#f59e0b",
    "Гаури": "#f59e0b",
    "Naga": "#a855f7",
    "Нага": "#a855f7",
    "Amelia": "#3b82f6",
    "Амелия": "#3b82f6",
    "Zelgadis": "#06b6d4",
    "Зелгадис": "#06b6d4",
    "Sylphiel": "#10b981",
    "Сильфиль": "#10b981",
    "Lark": "#8b5cf6",
    "Ларк": "#8b5cf6",
    "Emilia": "#ec4899",
    "Эмилия": "#ec4899",
}


def clean_length(text: str, ignore_tags: bool = False) -> int:
    """Calculate character length, optionally ignoring escape tags like <00BF>."""
    if ignore_tags:
        text = TAG_RE.sub("", text)
    return len(text)


def validate_text(text: str, limits: dict[str, Any]) -> dict[str, Any]:
    """Validate text against specific hardware limits."""
    raw_cleaned = text.replace("\r", "")
    normalized = unicodedata.normalize("NFC", raw_cleaned)
    errors: list[str] = []
    warnings: list[str] = []

    if "\r" in text:
        errors.append("Содержит недопустимый символ возврата каретки (\\r)")
    if normalized != raw_cleaned:
        warnings.append("Текст не в нормализации Unicode NFC")

    single_line = limits.get("single_line", False)
    allow_page_break = limits.get("allow_page_break", True)
    max_c_total = limits.get("max_chars_total")
    max_c_line = limits.get("max_chars_per_line")
    max_lines = limits.get("max_lines")
    max_lines_page = limits.get("max_lines_per_page", 3)
    min_lines_page = limits.get("min_lines_per_page", 1)
    allow_empty_lines = limits.get("allow_empty_lines", False)
    ignore_tags = limits.get("ignore_tags", False)
    max_bytes = limits.get("max_bytes")
    if max_bytes is not None:
        try:
            from tools.patch_town_services import encode_string
            b_len = len(encode_string(text))
            if b_len > max_bytes:
                errors.append(f"Размер в бинарном формате {b_len} Б превышает лимит {max_bytes} Б")
        except Exception:
            pass

    pages = normalized.split("\f")
    if len(pages) > 1 and not allow_page_break:
        errors.append("Разделение на страницы (\\f) запрещено для этой записи")

    if single_line:
        if "\n" in normalized or "\f" in normalized:
            errors.append("Переносы строк не допускаются для этого поля")
        cur_len = clean_length(normalized, ignore_tags)
        if max_c_total and cur_len > max_c_total:
            errors.append(f"Длина {cur_len} превышает лимит {max_c_total} симв.")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "pages_count": 1,
            "lines_per_page": [1],
            "line_lengths": [[cur_len]],
            "max_line_len": cur_len,
            "exceeds_limits": len(errors) > 0,
        }

    lines_per_page: list[int] = []
    line_lengths: list[list[int]] = []
    overall_max_len = 0
    total_lines = 0

    for p_idx, page in enumerate(pages, 1):
        lines = page.split("\n")
        lines_per_page.append(len(lines))
        p_lengths: list[int] = []
        total_lines += len(lines)

        if max_lines_page and len(lines) > max_lines_page:
            errors.append(f"Стр. {p_idx}: {len(lines)} строк (максимум {max_lines_page})")
        if min_lines_page and len(lines) < min_lines_page:
            errors.append(f"Стр. {p_idx}: меньше {min_lines_page} строк")

        for l_idx, line in enumerate(lines, 1):
            c_len = clean_length(line, ignore_tags)
            p_lengths.append(c_len)
            if c_len > overall_max_len:
                overall_max_len = c_len
            if not line and len(lines) > 1 and not allow_empty_lines:
                errors.append(f"Стр. {p_idx}, строка {l_idx} пустая")
            if max_c_line and c_len > max_c_line:
                errors.append(f"Стр. {p_idx}, строка {l_idx}: {c_len} симв. (макс. {max_c_line})")

        line_lengths.append(p_lengths)

    if max_lines and total_lines > max_lines:
        errors.append(f"Всего строк {total_lines} (максимум {max_lines})")

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "pages_count": len(pages),
        "lines_per_page": lines_per_page,
        "line_lengths": line_lengths,
        "max_line_len": overall_max_len,
        "exceeds_limits": len(errors) > 0,
    }


class CatalogManager:
    """Manages loading, parsing, caching, validation, and saving of catalogs."""

    def __init__(self, translations_dir: Path = TRANSLATIONS_DIR):
        self.translations_dir = translations_dir
        self.lock = threading.Lock()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._parsed_entries: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def get_catalog_file_path(self, cat_id: str) -> Path:
        if cat_id not in CATALOG_DEFS:
            raise ValueError(f"Unknown catalog: {cat_id}")
        return self.translations_dir / CATALOG_DEFS[cat_id]["file"]

    def load_raw_json(self, cat_id: str) -> Any:
        path = self.get_catalog_file_path(cat_id)
        if not path.is_file():
            raise FileNotFoundError(f"Catalog file not found: {path}")

        mtime = path.stat().st_mtime
        with self.lock:
            if cat_id in self._cache:
                cached_mtime, data = self._cache[cat_id]
                if cached_mtime == mtime:
                    return data

            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            self._cache[cat_id] = (mtime, data)
            return data

    def save_raw_json(self, cat_id: str, data: Any) -> None:
        path = self.get_catalog_file_path(cat_id)
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)

        # Atomic disk write
        with tempfile.NamedTemporaryFile("w", dir=parent, encoding="utf-8", delete=False) as tf:
            json.dump(data, tf, ensure_ascii=False, indent=2)
            tf.write("\n")
            temp_name = tf.name

        os.replace(temp_name, path)

        with self.lock:
            mtime = path.stat().st_mtime
            self._cache[cat_id] = (mtime, data)
            # Invalidate parsed cache
            self._parsed_entries.pop(cat_id, None)

    def get_all_entries(self, cat_id: str) -> list[dict[str, Any]]:
        path = self.get_catalog_file_path(cat_id)
        mtime = path.stat().st_mtime if path.is_file() else 0

        with self.lock:
            if cat_id in self._parsed_entries:
                cached_mtime, entries = self._parsed_entries[cat_id]
                if cached_mtime == mtime:
                    return entries

        data = self.load_raw_json(cat_id)
        limits_def = CATALOG_DEFS[cat_id]["limits"]
        parsed: list[dict[str, Any]] = []

        if cat_id == "story_dialogues":
            for scene in data.get("scenes", []):
                s_id = scene.get("scene_id", "")
                s_title = scene.get("title", f"Сцена {s_id}")
                for d in scene.get("dialogues", []):
                    text_ru = d.get("text_ru", "")
                    entry_limits = dict(limits_def)
                    entry_limits["allow_page_break"] = d.get("allow_page_break", True)
                    v_res = validate_text(text_ru, entry_limits)
                    parsed.append({
                        "id": d.get("context", ""),
                        "catalog_id": cat_id,
                        "catalog_title": CATALOG_DEFS[cat_id]["title"],
                        "scene_id": s_id,
                        "scene_title": s_title,
                        "category": s_title,
                        "speaker": d.get("speaker", ""),
                        "speaker_ru": d.get("speaker_ru", d.get("speaker", "")),
                        "text_jp": d.get("text_jp", ""),
                        "text_en": d.get("text_en", ""),
                        "text_ru": text_ru,
                        "allow_page_break": d.get("allow_page_break", True),
                        "extra": {
                            "record": d.get("record"),
                            "index": d.get("index"),
                            "controls": d.get("controls", []),
                        },
                        "limits": entry_limits,
                        "validation": v_res,
                    })

        elif cat_id == "combat_dialogues":
            for block in data.get("blocks", []):
                b_id = block.get("id", "")
                b_ram = block.get("ram_address", "")
                b_title = f"Блок {b_id} ({b_ram})"
                for bub in block.get("bubbles", []):
                    idx = bub.get("bubble_index", 1)
                    entry_id = f"{b_id}:{idx}"
                    text_ru = bub.get("text_ru", "")
                    entry_limits = dict(limits_def)
                    v_res = validate_text(text_ru, entry_limits)
                    parsed.append({
                        "id": entry_id,
                        "catalog_id": cat_id,
                        "catalog_title": CATALOG_DEFS[cat_id]["title"],
                        "scene_id": b_id,
                        "scene_title": b_title,
                        "category": b_title,
                        "speaker": bub.get("speaker", ""),
                        "speaker_ru": bub.get("speaker", ""),
                        "text_jp": bub.get("text_jp", ""),
                        "text_en": bub.get("text_en", ""),
                        "text_ru": text_ru,
                        "allow_page_break": True,
                        "extra": {
                            "block_id": b_id,
                            "bubble_index": idx,
                            "allocated_budget_bytes": block.get("allocated_budget_bytes"),
                        },
                        "limits": entry_limits,
                        "validation": v_res,
                    })

        elif cat_id == "room_inspection":
            for eng_k, val in data.items():
                text_ru = val.get("russian", "")
                rooms = val.get("rooms", [])
                primary_room = rooms[0] if rooms else "0x000"
                s_title = f"Комнаты: {', '.join(rooms)}" if rooms else "Осмотр"
                entry_limits = dict(limits_def)
                v_res = validate_text(text_ru, entry_limits)
                parsed.append({
                    "id": eng_k,
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "scene_id": primary_room,
                    "scene_title": s_title,
                    "category": val.get("type", "description"),
                    "speaker": "",
                    "speaker_ru": "",
                    "text_jp": "",
                    "text_en": eng_k,
                    "text_ru": text_ru,
                    "allow_page_break": False,
                    "extra": {
                        "type": val.get("type"),
                        "rooms": rooms,
                        "frequency": val.get("frequency", 1),
                    },
                    "limits": entry_limits,
                    "validation": v_res,
                })

        elif cat_id == "room_names":
            entries_dict = data.get("entries", {})
            for hex_k, val in entries_dict.items():
                text_ru = val.get("name_ru", "")
                entry_limits = dict(limits_def)
                v_res = validate_text(text_ru, entry_limits)
                parsed.append({
                    "id": hex_k,
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "scene_id": hex_k,
                    "scene_title": f"Комната {hex_k}",
                    "category": f"Комната {val.get('entry_index')}",
                    "speaker": "",
                    "speaker_ru": "",
                    "text_jp": val.get("name_jp", ""),
                    "text_en": val.get("name_en", ""),
                    "text_ru": text_ru,
                    "allow_page_break": False,
                    "extra": {
                        "entry_index": val.get("entry_index"),
                        "description": val.get("description", ""),
                    },
                    "limits": entry_limits,
                    "validation": v_res,
                })

        elif cat_id == "minigames":
            mg_dict = data.get("minigames", {})
            for mg_k, mg_v in mg_dict.items():
                mg_title = mg_v.get("description") or f"Игра: {mg_k}"
                if "rules_ru" in mg_v:
                    t_ru = mg_v.get("rules_ru", "")
                    e_lim = {"max_chars_per_line": 20, "max_lines": 10, "max_lines_per_page": 10, "allow_page_break": False}
                    v_res = validate_text(t_ru, e_lim)
                    parsed.append({
                        "id": f"minigame:{mg_k}:rules",
                        "catalog_id": cat_id,
                        "catalog_title": CATALOG_DEFS[cat_id]["title"],
                        "scene_id": mg_k,
                        "scene_title": mg_title,
                        "category": "Правила игры",
                        "speaker": "",
                        "speaker_ru": "",
                        "text_jp": mg_v.get("rules_jp", ""),
                        "text_en": "",
                        "text_ru": t_ru,
                        "allow_page_break": False,
                        "extra": {"entry": mg_v.get("prog_entry"), "allocated_bytes": mg_v.get("allocated_bytes")},
                        "limits": e_lim,
                        "validation": v_res,
                    })
                if "title_banner" in mg_v:
                    t_ru = mg_v.get("title_banner", "")
                    e_lim = {"max_chars_total": 20, "single_line": True, "allow_page_break": False}
                    v_res = validate_text(t_ru, e_lim)
                    parsed.append({
                        "id": f"minigame:{mg_k}:title",
                        "catalog_id": cat_id,
                        "catalog_title": CATALOG_DEFS[cat_id]["title"],
                        "scene_id": mg_k,
                        "scene_title": mg_title,
                        "category": "Заголовок игры",
                        "speaker": "",
                        "speaker_ru": "",
                        "text_jp": "",
                        "text_en": "",
                        "text_ru": t_ru,
                        "allow_page_break": False,
                        "extra": {},
                        "limits": e_lim,
                        "validation": v_res,
                    })
                for s_k, s_v in mg_v.get("status_messages", {}).items():
                    e_lim = {"max_chars_per_line": 20, "max_lines_per_page": 3, "allow_page_break": True}
                    v_res = validate_text(s_v, e_lim)
                    parsed.append({
                        "id": f"minigame:{mg_k}:status:{s_k}",
                        "catalog_id": cat_id,
                        "catalog_title": CATALOG_DEFS[cat_id]["title"],
                        "scene_id": mg_k,
                        "scene_title": mg_title,
                        "category": f"Статус: {s_k}",
                        "speaker": "",
                        "speaker_ru": "",
                        "text_jp": "",
                        "text_en": "",
                        "text_ru": s_v,
                        "allow_page_break": True,
                        "extra": {},
                        "limits": e_lim,
                        "validation": v_res,
                    })
                for d_k, d_v in mg_v.get("dialogues", {}).items():
                    e_lim = {"max_chars_per_line": 20, "max_lines_per_page": 3, "allow_page_break": True}
                    v_res = validate_text(d_v, e_lim)
                    parsed.append({
                        "id": f"minigame:{mg_k}:dialogue:{d_k}",
                        "catalog_id": cat_id,
                        "catalog_title": CATALOG_DEFS[cat_id]["title"],
                        "scene_id": mg_k,
                        "scene_title": mg_title,
                        "category": f"Реплика: {d_k}",
                        "speaker": "",
                        "speaker_ru": "",
                        "text_jp": "",
                        "text_en": "",
                        "text_ru": d_v,
                        "allow_page_break": True,
                        "extra": {},
                        "limits": e_lim,
                        "validation": v_res,
                    })

            quiz_qs = data.get("quiz", {}).get("questions", [])
            for q in quiz_qs:
                qid = q.get("id")
                e_lim = {"max_chars_total": 15, "single_line": True, "allow_page_break": False}
                for fld, sub, label in [
                    ("q_line1_ru", "q_line1", "Вопрос (строка 1)"),
                    ("q_line2_ru", "q_line2", "Вопрос (строка 2)"),
                ]:
                    t_ru = q.get(fld, "")
                    v_res = validate_text(t_ru, e_lim)
                    parsed.append({
                        "id": f"quiz:{qid}:{sub}",
                        "catalog_id": cat_id,
                        "catalog_title": CATALOG_DEFS[cat_id]["title"],
                        "scene_id": "quiz",
                        "scene_title": "Викторина (100 вопросов)",
                        "category": f"Вопрос #{qid}: {label}",
                        "speaker": "",
                        "speaker_ru": "",
                        "text_jp": q.get(fld.replace("_ru", "_jp"), ""),
                        "text_en": q.get(fld.replace("_ru", "_en"), ""),
                        "text_ru": t_ru,
                        "allow_page_break": False,
                        "extra": {"question_id": qid},
                        "limits": e_lim,
                        "validation": v_res,
                    })
                for o_idx, opt in enumerate(q.get("options_ru", [])):
                    v_res = validate_text(opt, e_lim)
                    parsed.append({
                        "id": f"quiz:{qid}:opt{o_idx}",
                        "catalog_id": cat_id,
                        "catalog_title": CATALOG_DEFS[cat_id]["title"],
                        "scene_id": "quiz",
                        "scene_title": "Викторина (100 вопросов)",
                        "category": f"Вопрос #{qid}: Вариант {o_idx + 1}",
                        "speaker": "",
                        "speaker_ru": "",
                        "text_jp": q.get("options_jp", ["", "", ""])[o_idx] if o_idx < len(q.get("options_jp", [])) else "",
                        "text_en": q.get("options_en", ["", "", ""])[o_idx] if o_idx < len(q.get("options_en", [])) else "",
                        "text_ru": opt,
                        "allow_page_break": False,
                        "extra": {"question_id": qid, "option_index": o_idx},
                        "limits": e_lim,
                        "validation": v_res,
                    })

            for ent_k, ent_v in data.get("system_prompts", {}).items():
                if isinstance(ent_v, dict) and "prompts" in ent_v:
                    for pr_k, pr_v in ent_v.get("prompts", {}).items():
                        t_ru = pr_v.get("text_ru", "")
                        t_en = pr_v.get("text_en", "")
                        budget = pr_v.get("budget", 20)
                        e_lim = {"max_chars_per_line": 20, "max_lines_per_page": 3, "allow_page_break": True}
                        v_res = validate_text(t_ru, e_lim)
                        parsed.append({
                            "id": f"prompt:{ent_k}:{pr_k}",
                            "catalog_id": cat_id,
                            "catalog_title": CATALOG_DEFS[cat_id]["title"],
                            "scene_id": "prompts",
                            "scene_title": f"Системные подсказки ({ent_k})",
                            "category": f"Подсказка: {pr_k}",
                            "speaker": "",
                            "speaker_ru": "",
                            "text_jp": "",
                            "text_en": t_en,
                            "text_ru": t_ru,
                            "allow_page_break": True,
                            "extra": {"budget": budget, "offset_hex": pr_v.get("offset_hex")},
                            "limits": e_lim,
                            "validation": v_res,
                        })
                elif isinstance(ent_v, str):
                    e_lim = {"max_chars_total": 20, "single_line": True, "allow_page_break": False}
                    v_res = validate_text(ent_v, e_lim)
                    parsed.append({
                        "id": f"prompt:{ent_k}",
                        "catalog_id": cat_id,
                        "catalog_title": CATALOG_DEFS[cat_id]["title"],
                        "scene_id": "prompts",
                        "scene_title": "Системные подсказки",
                        "category": f"Подсказка: {ent_k}",
                        "speaker": "",
                        "speaker_ru": "",
                        "text_jp": "",
                        "text_en": "",
                        "text_ru": ent_v,
                        "allow_page_break": False,
                        "extra": {},
                        "limits": e_lim,
                        "validation": v_res,
                    })
        elif cat_id == "town_services":
            for k, v in data.get("tavern_services", {}).items():
                max_bytes = v.get("max_bytes", 24)
                t_ru = v.get("ru", "")
                e_lim = {"max_bytes": max_bytes, "single_line": ("\n" not in t_ru), "allow_page_break": False}
                v_res = validate_text(t_ru, e_lim)
                parsed.append({
                    "id": f"tavern:{k}",
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "scene_id": "tavern",
                    "scene_title": "Службы таверны",
                    "category": "Таверна",
                    "speaker": "",
                    "speaker_ru": "",
                    "text_jp": v.get("jp", ""),
                    "text_en": v.get("en", ""),
                    "text_ru": t_ru,
                    "allow_page_break": False,
                    "extra": {"max_bytes": max_bytes},
                    "limits": e_lim,
                    "validation": v_res,
                })

            for k, v in data.get("inn_services", {}).items():
                max_bytes = v.get("max_bytes", 28)
                t_ru = v.get("ru", "")
                e_lim = {"max_bytes": max_bytes, "single_line": ("\n" not in t_ru), "allow_page_break": False}
                v_res = validate_text(t_ru, e_lim)
                parsed.append({
                    "id": f"inn:{k}",
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "scene_id": "inn",
                    "scene_title": "Гостиница (ночлег)",
                    "category": "Гостиница",
                    "speaker": "",
                    "speaker_ru": "",
                    "text_jp": v.get("jp", ""),
                    "text_en": v.get("en", ""),
                    "text_ru": t_ru,
                    "allow_page_break": False,
                    "extra": {"max_bytes": max_bytes},
                    "limits": e_lim,
                    "validation": v_res,
                })

            for k, v in data.get("town_system_icons", {}).get("icons", {}).items():
                e_lim = {"single_line": False, "allow_page_break": True}
                t_ru = v.get("ru", "")
                v_res = validate_text(t_ru, e_lim)
                parsed.append({
                    "id": f"icon:{k}",
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "scene_id": "icons",
                    "scene_title": "Иконки городского меню",
                    "category": "Иконки меню",
                    "speaker": "",
                    "speaker_ru": "",
                    "text_jp": "",
                    "text_en": "",
                    "text_ru": t_ru,
                    "allow_page_break": False,
                    "extra": {"ptr_hex": v.get("ptr_hex")},
                    "limits": e_lim,
                    "validation": v_res,
                })

            for k, v in data.get("shop_dialogue", {}).items():
                max_bytes = v.get("max_bytes", 16)
                t_ru = v.get("ru", "")
                e_lim = {"max_bytes": max_bytes, "single_line": ("\n" not in t_ru), "allow_page_break": True}
                v_res = validate_text(t_ru, e_lim)
                parsed.append({
                    "id": f"shop_prompt:{k}",
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "scene_id": "shop_menu",
                    "scene_title": "Диалоги покупки/продажи",
                    "category": "Меню лавки",
                    "speaker": "",
                    "speaker_ru": "",
                    "text_jp": "",
                    "text_en": "",
                    "text_ru": t_ru,
                    "allow_page_break": False,
                    "extra": {"max_bytes": max_bytes},
                    "limits": e_lim,
                    "validation": v_res,
                })

        elif cat_id == "shop_dialogues":
            for d_id, d in data.get("dialogues", {}).items():
                text_ru = d.get("text_ru", "")
                entry_limits = dict(limits_def)
                v_res = validate_text(text_ru, entry_limits)
                parsed.append({
                    "id": f"shop_dialogue:{d_id}",
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "scene_id": d.get("category", "dialogues"),
                    "scene_title": f"Категория: {d.get('category', 'dialogues')}",
                    "category": d.get("category", "dialogues"),
                    "speaker": d.get("speaker") or "",
                    "speaker_ru": d.get("speaker") or "",
                    "text_jp": d.get("text_jp", ""),
                    "text_en": "",
                    "text_ru": text_ru,
                    "allow_page_break": True,
                    "extra": {"id": d_id, "offset_hex": d.get("offset_hex")},
                    "limits": entry_limits,
                    "validation": v_res,
                })

            for item in data.get("shop_items", []):
                idx = item.get("index", 0)
                text_ru = item.get("text_ru", "")
                e_lim = {"max_chars_total": 8, "single_line": True, "allow_page_break": False}
                v_res = validate_text(text_ru, e_lim)
                parsed.append({
                    "id": f"shop_item:{idx}",
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "scene_id": "items",
                    "scene_title": "Товары и экипировка (91)",
                    "category": "Товары лавки",
                    "speaker": "",
                    "speaker_ru": "",
                    "text_jp": item.get("text_jp", ""),
                    "text_en": "",
                    "text_ru": text_ru,
                    "allow_page_break": False,
                    "extra": {"index": idx, "offset_hex": item.get("offset_hex")},
                    "limits": e_lim,
                    "validation": v_res,
                })

        elif cat_id == "world_map":
            for loc in data.get("locations", []):
                loc_id = loc.get("id", "")
                text_ru = loc.get("text_ru", "")
                e_lim = dict(limits_def)
                v_res = validate_text(text_ru, e_lim)
                parsed.append({
                    "id": loc_id,
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "scene_id": "world_map",
                    "scene_title": "Локации карты мира",
                    "category": "Карта мира",
                    "speaker": "",
                    "speaker_ru": "",
                    "text_jp": "",
                    "text_en": loc.get("text_en", ""),
                    "text_ru": text_ru,
                    "allow_page_break": False,
                    "extra": {"index": loc.get("index")},
                    "limits": e_lim,
                    "validation": v_res,
                })

        elif cat_id == "location_banners":
            for k, v in data.get("banners", {}).items():
                text_ru = v.get("text_ru", "")
                e_lim = dict(limits_def)
                v_res = validate_text(text_ru, e_lim)
                parsed.append({
                    "id": k,
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "scene_id": "banners",
                    "scene_title": "Вывески локаций",
                    "category": "Вывески",
                    "speaker": "",
                    "speaker_ru": "",
                    "text_jp": "",
                    "text_en": v.get("text_en", ""),
                    "text_ru": text_ru,
                    "allow_page_break": False,
                    "extra": {
                        "font_size": v.get("font_size"),
                        "align": v.get("align"),
                        "offset_x": v.get("offset_x"),
                        "offset_y": v.get("offset_y"),
                    },
                    "limits": e_lim,
                    "validation": v_res,
                })

        elif cat_id == "lore_cards":
            for card in data.get("cards", []):
                cid = card.get("id", "")
                lines = card.get("lines", [])
                text_ru = "\n".join(lines) if lines else card.get("description", "")
                e_lim = dict(limits_def)
                v_res = validate_text(text_ru, e_lim)
                parsed.append({
                    "id": cid,
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "scene_id": cid,
                    "scene_title": card.get("title_main", cid),
                    "category": card.get("type", "split_card"),
                    "speaker": "",
                    "speaker_ru": "",
                    "text_jp": "",
                    "text_en": card.get("title_sub", ""),
                    "text_ru": text_ru,
                    "allow_page_break": False,
                    "extra": {
                        "title_main": card.get("title_main"),
                        "title_sub": card.get("title_sub"),
                        "banner_opt": card.get("banner_opt"),
                        "prog_entry": card.get("prog_entry"),
                        "opt_entry": card.get("opt_entry"),
                    },
                    "limits": e_lim,
                    "validation": v_res,
                })

        elif cat_id == "spells":
            for s in data:
                s_idx = s.get("entry_index", 0)
                pages = s.get("pages_ru", [])
                text_ru = "\f".join(pages) if pages else (s.get("desc_ru") or s.get("title_ru") or "")
                e_lim = dict(limits_def)
                v_res = validate_text(text_ru, e_lim)
                parsed.append({
                    "id": f"spell:{s_idx}",
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "scene_id": "spells",
                    "scene_title": "Заклинания магии",
                    "category": f"Заклинание #{s_idx}",
                    "speaker": s.get("name_en") or s.get("name_ru") or "",
                    "speaker_ru": s.get("name_ru") or s.get("title_ru") or "",
                    "text_jp": s.get("title_jp", ""),
                    "text_en": s.get("desc_en") or s.get("title_en") or "",
                    "text_ru": text_ru,
                    "allow_page_break": True,
                    "extra": {
                        "entry_index": s_idx,
                        "title_ru": s.get("title_ru"),
                        "name_ru": s.get("name_ru"),
                    },
                    "limits": e_lim,
                    "validation": v_res,
                })

        with self.lock:
            self._parsed_entries[cat_id] = (mtime, parsed)

        return parsed

    def query_catalog(
        self,
        cat_id: str,
        scene: Optional[str] = None,
        search: Optional[str] = None,
        issues_only: bool = False,
        speaker: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Query entries in a catalog with filters, search, and pagination."""
        entries = self.get_all_entries(cat_id)
        filtered = entries

        if scene:
            filtered = [e for e in filtered if e.get("scene_id") == scene]

        if speaker:
            filtered = [
                e for e in filtered
                if e.get("speaker") == speaker or e.get("speaker_ru") == speaker
            ]

        if issues_only:
            filtered = [e for e in filtered if e["validation"]["exceeds_limits"]]

        if search:
            q = search.lower().strip()
            filtered = [
                e for e in filtered
                if q in (e.get("text_ru") or "").lower()
                or q in (e.get("text_en") or "").lower()
                or q in (e.get("text_jp") or "").lower()
                or q in (e.get("id") or "").lower()
                or q in (e.get("speaker") or "").lower()
                or q in (e.get("speaker_ru") or "").lower()
                or q in (e.get("category") or "").lower()
            ]
        total_filtered = len(filtered)
        total_pages = max(1, (total_filtered + limit - 1) // limit)
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_entries = filtered[start_idx:end_idx]

        # Aggregate scene lists and speaker lists for sidebar
        scenes_map: dict[str, dict[str, Any]] = {}
        speakers_set: set[str] = set()
        issues_count = sum(1 for e in entries if e["validation"]["exceeds_limits"])

        for e in entries:
            s_id = e.get("scene_id") or "default"
            s_title = e.get("scene_title") or s_id
            if s_id not in scenes_map:
                scenes_map[s_id] = {
                    "id": s_id,
                    "title": s_title,
                    "count": 0,
                    "issues": 0,
                }
            scenes_map[s_id]["count"] += 1
            if e["validation"]["exceeds_limits"]:
                scenes_map[s_id]["issues"] += 1

            if e.get("speaker"):
                speakers_set.add(e["speaker"])
            if e.get("speaker_ru"):
                speakers_set.add(e["speaker_ru"])

        return {
            "catalog": CATALOG_DEFS[cat_id],
            "total_entries": len(entries),
            "filtered_entries": total_filtered,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "entries": paginated_entries,
            "scenes": list(scenes_map.values()),
            "speakers": sorted(speakers_set),
            "issues_count": issues_count,
        }

    def get_all_issues(self) -> dict[str, Any]:
        """Collect all entries exceeding hardware limits across all catalogs."""
        all_issues: list[dict[str, Any]] = []
        catalog_counts: dict[str, int] = {}

        for cat_id in CATALOG_DEFS:
            entries = self.get_all_entries(cat_id)
            cat_issues = [e for e in entries if e["validation"]["exceeds_limits"]]
            catalog_counts[cat_id] = len(cat_issues)
            for e in cat_issues:
                all_issues.append({
                    "catalog_id": cat_id,
                    "catalog_title": CATALOG_DEFS[cat_id]["title"],
                    "entry_id": e["id"],
                    "scene_id": e.get("scene_id", ""),
                    "scene_title": e.get("scene_title", ""),
                    "category": e.get("category", ""),
                    "speaker": e.get("speaker_ru") or e.get("speaker") or "",
                    "text_ru": e.get("text_ru", ""),
                    "errors": e["validation"]["errors"],
                    "warnings": e["validation"]["warnings"],
                    "limits": e["limits"],
                })

        return {
            "total_issues": len(all_issues),
            "catalogs": catalog_counts,
            "issues": all_issues,
        }

    def get_stats(self) -> dict[str, Any]:
        """Generate comprehensive statistics across all catalogs."""
        catalogs_stat: list[dict[str, Any]] = []
        total_all = 0
        issues_all = 0

        for cat_id, cat_info in CATALOG_DEFS.items():
            entries = self.get_all_entries(cat_id)
            total = len(entries)
            issues = sum(1 for e in entries if e["validation"]["exceeds_limits"])
            total_all += total
            issues_all += issues
            catalogs_stat.append({
                "id": cat_id,
                "title": cat_info["title"],
                "badge": cat_info["badge"],
                "icon": cat_info["icon"],
                "total_entries": total,
                "issues_count": issues,
                "limits": cat_info["limits"],
            })

        return {
            "total_catalogs": len(CATALOG_DEFS),
            "total_entries": total_all,
            "total_issues": issues_all,
            "catalogs": catalogs_stat,
        }

    def update_entry(self, cat_id: str, entry_id: str, new_text_ru: str) -> dict[str, Any]:
        """Update an entry's Russian text and write atomically back to disk."""
        new_text_ru = re.sub(r"\\f\r?\n?", "\f", new_text_ru)
        data = copy.deepcopy(self.load_raw_json(cat_id))
        found = False

        if cat_id == "story_dialogues":
            for scene in data.get("scenes", []):
                for d in scene.get("dialogues", []):
                    if d.get("context") == entry_id:
                        d["text_ru"] = new_text_ru
                        found = True
                        break
                if found:
                    break

        elif cat_id == "combat_dialogues":
            b_id, bub_idx = entry_id.split(":")
            idx = int(bub_idx)
            for block in data.get("blocks", []):
                if block.get("id") == b_id:
                    for bub in block.get("bubbles", []):
                        if bub.get("bubble_index") == idx:
                            bub["text_ru"] = new_text_ru
                            bub["pages"] = new_text_ru.split("\f")
                            found = True
                            break
                if found:
                    break

        elif cat_id == "room_inspection":
            if entry_id in data:
                data[entry_id]["russian"] = new_text_ru
                found = True

        elif cat_id == "room_names":
            entries = data.get("entries", {})
            if entry_id in entries:
                entries[entry_id]["name_ru"] = new_text_ru
                found = True

        elif cat_id == "minigames":
            if entry_id.startswith("minigame:"):
                parts = entry_id.split(":")
                mg_k, field = parts[1], parts[2]
                mg_v = data.get("minigames", {}).get(mg_k, {})
                if field == "rules":
                    mg_v["rules_ru"] = new_text_ru
                    found = True
                elif field == "title":
                    mg_v["title_banner"] = new_text_ru
                    found = True
                elif field == "status":
                    s_k = parts[3]
                    if s_k in mg_v.get("status_messages", {}):
                        mg_v["status_messages"][s_k] = new_text_ru
                        found = True
                elif field == "dialogue":
                    d_k = parts[3]
                    if d_k in mg_v.get("dialogues", {}):
                        mg_v["dialogues"][d_k] = new_text_ru
                        found = True
            elif entry_id.startswith("quiz:"):
                parts = entry_id.split(":")
                qid = int(parts[1])
                sub = parts[2]
                for q in data.get("quiz", {}).get("questions", []):
                    if q.get("id") == qid:
                        if sub == "q_line1":
                            q["q_line1_ru"] = new_text_ru
                            found = True
                        elif sub == "q_line2":
                            q["q_line2_ru"] = new_text_ru
                            found = True
                        elif sub.startswith("opt"):
                            opt_idx = int(sub[3:])
                            if "options_ru" in q and opt_idx < len(q["options_ru"]):
                                q["options_ru"][opt_idx] = new_text_ru
                                found = True
                        break
            elif entry_id.startswith("prompt:"):
                parts = entry_id.split(":")
                if len(parts) == 3:
                    ent_k, pr_k = parts[1], parts[2]
                    if ent_k in data.get("system_prompts", {}) and pr_k in data["system_prompts"][ent_k].get("prompts", {}):
                        data["system_prompts"][ent_k]["prompts"][pr_k]["text_ru"] = new_text_ru
                        found = True
                elif len(parts) == 2:
                    p_k = parts[1]
                    if p_k in data.get("system_prompts", {}):
                        data["system_prompts"][p_k] = new_text_ru
                        found = True
        elif cat_id == "town_services":
            if entry_id.startswith("tavern:"):
                k = entry_id.split(":", 1)[1]
                if k in data.get("tavern_services", {}):
                    data["tavern_services"][k]["ru"] = new_text_ru
                    found = True
            elif entry_id.startswith("inn:"):
                k = entry_id.split(":", 1)[1]
                if k in data.get("inn_services", {}):
                    data["inn_services"][k]["ru"] = new_text_ru
                    found = True
            elif entry_id.startswith("icon:"):
                k = entry_id.split(":", 1)[1]
                icons = data.get("town_system_icons", {}).get("icons", {})
                if k in icons:
                    icons[k]["ru"] = new_text_ru
                    found = True
            elif entry_id.startswith("shop_prompt:"):
                k = entry_id.split(":", 1)[1]
                if k in data.get("shop_dialogue", {}):
                    data["shop_dialogue"][k]["ru"] = new_text_ru
                    found = True

        elif cat_id == "shop_dialogues":
            if entry_id.startswith("shop_dialogue:"):
                d_id = entry_id.split(":", 1)[1]
                if d_id in data.get("dialogues", {}):
                    data["dialogues"][d_id]["text_ru"] = new_text_ru
                    found = True
            elif entry_id.startswith("shop_item:"):
                idx = int(entry_id.split(":", 1)[1])
                for item in data.get("shop_items", []):
                    if item.get("index") == idx:
                        item["text_ru"] = new_text_ru
                        found = True
                        break

        elif cat_id == "world_map":
            for loc in data.get("locations", []):
                if loc.get("id") == entry_id:
                    loc["text_ru"] = new_text_ru
                    found = True
                    break

        elif cat_id == "location_banners":
            if entry_id in data.get("banners", {}):
                data["banners"][entry_id]["text_ru"] = new_text_ru
                found = True

        elif cat_id == "lore_cards":
            for card in data.get("cards", []):
                if card.get("id") == entry_id:
                    card["lines"] = new_text_ru.split("\n")
                    found = True
                    break

        elif cat_id == "spells":
            s_idx = int(entry_id.split(":", 1)[1]) if ":" in entry_id else int(entry_id)
            for s in data:
                if s.get("entry_index") == s_idx:
                    pages = new_text_ru.split("\f")
                    s["pages_ru"] = pages
                    s["desc_ru"] = "\n\n".join(pages)
                    found = True
                    break

        if not found:
            raise KeyError(f"Entry {entry_id} not found in catalog {cat_id}")

        self.save_raw_json(cat_id, data)

        # Retrieve updated parsed entry
        entries = self.get_all_entries(cat_id)
        updated = next((e for e in entries if e["id"] == entry_id), None)
        return updated or {}


# Global Catalog Manager instance
MANAGER = CatalogManager()


class TranslationEditorHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler implementing REST API and serving SPA frontend."""

    def _send_json(self, status: int, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, status: int, html: str) -> None:
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        try:
            if path == "" or path == "/":
                self._send_html(200, EMBEDDED_SPA_HTML)
                return

            if path == "/api/catalogs":
                stats = MANAGER.get_stats()
                self._send_json(200, stats)
                return

            if path == "/api/stats":
                stats = MANAGER.get_stats()
                self._send_json(200, stats)
                return

            if path == "/api/issues":
                issues = MANAGER.get_all_issues()
                self._send_json(200, issues)
                return

            if path.startswith("/api/catalog/"):
                cat_id = path[len("/api/catalog/") :]
                if cat_id not in CATALOG_DEFS:
                    self._send_json(404, {"error": f"Catalog {cat_id} not found"})
                    return

                scene = query.get("scene", [None])[0]
                search = query.get("search", [None])[0]
                speaker = query.get("speaker", [None])[0]
                issues_only = query.get("issues_only", ["false"])[0].lower() in ("true", "1")
                page = int(query.get("page", ["1"])[0])
                limit = int(query.get("limit", ["50"])[0])

                res = MANAGER.query_catalog(
                    cat_id=cat_id,
                    scene=scene,
                    search=search,
                    issues_only=issues_only,
                    speaker=speaker,
                    page=page,
                    limit=limit,
                )
                self._send_json(200, res)
                return

            self._send_json(404, {"error": "Not found"})

        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode("utf-8")) if body else {}

            if path == "/api/entry":
                cat_id = payload.get("catalog_id")
                entry_id = payload.get("id")
                text_ru = payload.get("text_ru", "")

                if not cat_id or not entry_id:
                    self._send_json(400, {"error": "Missing catalog_id or id"})
                    return

                updated = MANAGER.update_entry(cat_id, entry_id, text_ru)
                self._send_json(200, {"success": True, "entry": updated})
                return

            if path == "/api/run_validate":
                # Execute ./build.sh --validate
                build_sh = REPO_ROOT / "build.sh"
                if not build_sh.is_file():
                    self._send_json(500, {"error": "build.sh not found", "output": ""})
                    return

                proc = subprocess.run(
                    [str(build_sh), "--validate"],
                    cwd=str(REPO_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=120,
                )
                self._send_json(200, {
                    "success": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "output": proc.stdout,
                })
                return

            self._send_json(404, {"error": "Not found"})

        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        # Keep terminal output concise
        if os.environ.get("DEBUG_HTTP"):
            super().log_message(format, *args)


# Embedded Single Page Application
EMBEDDED_SPA_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Slayers Royal (PS1) — Translation Studio & Hardware Limits Engine</title>
  <style>
    :root {
      --bg-base: #0b0e14;
      --bg-panel: #131822;
      --bg-card: #1c2333;
      --bg-input: #10141f;
      --bg-hover: #263045;
      --border-subtle: #252e42;
      --border-focus: #00d2ff;
      --text-main: #f0f6fc;
      --text-muted: #8b9bb4;
      --text-dim: #54627a;
      --accent-cyan: #00e5ff;
      --accent-blue: #3b82f6;
      --accent-gold: #f59e0b;
      --accent-green: #10b981;
      --accent-red: #ef4444;
      --accent-purple: #a855f7;
      --shadow-sm: 0 2px 4px rgba(0,0,0,0.4);
      --shadow-md: 0 4px 12px rgba(0,0,0,0.6);
      --font-mono: 'Consolas', 'Monaco', 'Courier New', monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg-base);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    /* Top Navigation */
    header {
      background: var(--bg-panel);
      border-bottom: 1px solid var(--border-subtle);
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 16px;
      gap: 16px;
      z-index: 100;
      flex-shrink: 0;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.5px;
      color: var(--text-main);
      white-space: nowrap;
    }
    .brand-icon {
      background: linear-gradient(135deg, #00e5ff, #3b82f6);
      color: #000;
      font-size: 13px;
      font-weight: 900;
      padding: 3px 7px;
      border-radius: 4px;
      box-shadow: 0 0 10px rgba(0, 229, 255, 0.4);
    }
    .catalog-selector-wrap {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    select.catalog-select {
      background: var(--bg-card);
      color: var(--text-main);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 6px 12px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      outline: none;
      transition: all 0.2s;
    }
    select.catalog-select:focus {
      border-color: var(--accent-cyan);
      box-shadow: 0 0 0 2px rgba(0,229,255,0.2);
    }

    .search-box {
      flex: 1;
      max-width: 360px;
      position: relative;
    }
    .search-box input {
      width: 100%;
      background: var(--bg-input);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 6px 12px 6px 32px;
      color: var(--text-main);
      font-size: 13px;
      outline: none;
      transition: all 0.2s;
    }
    .search-box input:focus {
      border-color: var(--accent-cyan);
      box-shadow: 0 0 0 2px rgba(0,229,255,0.2);
    }
    .search-box .icon {
      position: absolute;
      left: 10px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-dim);
      font-size: 13px;
    }

    .top-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--bg-card);
      color: var(--text-main);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 6px 12px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
      white-space: nowrap;
    }
    .btn:hover {
      background: var(--bg-hover);
      border-color: var(--text-dim);
    }
    .btn-primary {
      background: #0284c7;
      border-color: #38bdf8;
      color: #fff;
    }
    .btn-primary:hover {
      background: #0369a1;
      box-shadow: 0 0 10px rgba(56, 189, 248, 0.4);
    }
    .btn-danger {
      background: rgba(239, 68, 68, 0.15);
      border-color: var(--accent-red);
      color: #fca5a5;
    }
    .btn-danger:hover {
      background: rgba(239, 68, 68, 0.3);
    }
    .btn-active {
      background: rgba(239, 68, 68, 0.25) !important;
      border-color: var(--accent-red) !important;
      color: #fff !important;
      box-shadow: 0 0 10px rgba(239, 68, 68, 0.3);
    }
    .save-indicator {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      padding: 4px 8px;
      border-radius: 4px;
      background: rgba(16, 185, 129, 0.1);
      color: var(--accent-green);
      border: 1px solid rgba(16, 185, 129, 0.3);
    }

    /* Main Workspace Layout */
    .app-body {
      flex: 1;
      display: flex;
      overflow: hidden;
    }

    /* Left Sidebar */
    aside.sidebar {
      width: 280px;
      background: var(--bg-panel);
      border-right: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
    }
    .sidebar-header {
      padding: 12px 14px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: var(--text-dim);
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .sidebar-list {
      flex: 1;
      overflow-y: auto;
      list-style: none;
      padding: 6px 0;
    }
    .sidebar-item {
      padding: 8px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      font-size: 13px;
      color: var(--text-muted);
      transition: all 0.15s;
      border-left: 3px solid transparent;
    }
    .sidebar-item:hover {
      background: var(--bg-hover);
      color: var(--text-main);
    }
    .sidebar-item.active {
      background: var(--bg-card);
      color: var(--accent-cyan);
      border-left-color: var(--accent-cyan);
      font-weight: 600;
    }
    .sidebar-badge {
      font-size: 11px;
      padding: 2px 6px;
      border-radius: 10px;
      background: var(--bg-input);
      color: var(--text-dim);
    }
    .sidebar-badge.has-error {
      background: rgba(239, 68, 68, 0.2);
      color: var(--accent-red);
      font-weight: 700;
    }

    /* Main Content Area */
    main.content {
      flex: 1;
      display: flex;
      flex-direction: column;
      background: var(--bg-base);
      overflow: hidden;
    }

    /* Top Subbar */
    .content-subbar {
      padding: 10px 20px;
      background: var(--bg-panel);
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-shrink: 0;
    }
    .breadcrumb {
      font-size: 13px;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .breadcrumb strong {
      color: var(--text-main);
    }
    .pagination-bar {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      color: var(--text-muted);
    }

    /* Center Split: Editor & Entry List */
    .workspace-split {
      flex: 1;
      display: flex;
      overflow: hidden;
    }

    /* Left Pane: Entry List */
    .entry-list-pane {
      width: 420px;
      border-right: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      background: var(--bg-panel);
      flex-shrink: 0;
    }
    .entry-list-items {
      flex: 1;
      overflow-y: auto;
    }
    .entry-row {
      padding: 12px 14px;
      border-bottom: 1px solid var(--border-subtle);
      cursor: pointer;
      transition: all 0.15s;
    }
    .entry-row:hover {
      background: var(--bg-hover);
    }
    .entry-row.active {
      background: var(--bg-card);
      box-shadow: inset 3px 0 0 var(--accent-cyan);
    }
    .entry-row-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 4px;
    }
    .speaker-pill {
      font-size: 11px;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: 4px;
      color: #fff;
      display: inline-block;
    }
    .ctx-pill {
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-dim);
    }
    .entry-row-text {
      font-size: 13px;
      color: var(--text-main);
      white-space: pre-wrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-height: 38px;
      line-height: 1.4;
    }
    .entry-row-status {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-top: 6px;
    }
    .status-badge {
      font-size: 10px;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: 4px;
      text-transform: uppercase;
    }
    .status-ok { background: rgba(16, 185, 129, 0.15); color: var(--accent-green); }
    .status-err { background: rgba(239, 68, 68, 0.2); color: var(--accent-red); }

    /* Right Pane: Active Editor Card */
    .editor-pane {
      flex: 1;
      overflow-y: auto;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }

    .editor-card {
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      padding: 20px;
      box-shadow: var(--shadow-sm);
    }
    .editor-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--border-subtle);
    }
    .editor-title-block {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .editor-id-badge {
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--accent-cyan);
      background: rgba(0, 229, 255, 0.08);
      padding: 2px 8px;
      border-radius: 4px;
      display: inline-block;
      cursor: pointer;
    }

    /* Reference boxes */
    .ref-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 16px;
    }
    .ref-box {
      background: var(--bg-input);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 12px;
    }
    .ref-label {
      font-size: 11px;
      font-weight: 700;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 6px;
    }
    .ref-text {
      font-size: 14px;
      line-height: 1.5;
      color: var(--text-main);
      white-space: pre-wrap;
    }
    .ref-text-jp {
      font-family: "Meiryo", "Yu Gothic", "MS Gothic", sans-serif;
    }

    /* Russian Textarea & Realtime Limits */
    .editor-main-box {
      margin-bottom: 16px;
    }
    .editor-label-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    .editor-label {
      font-size: 12px;
      font-weight: 700;
      color: var(--text-main);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .editor-gauges {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 12px;
    }
    .gauge-pill {
      padding: 3px 8px;
      border-radius: 4px;
      font-family: var(--font-mono);
      font-weight: 700;
      font-size: 11px;
    }
    .gauge-pill.ok {
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent-green);
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .gauge-pill.bad {
      background: rgba(239, 68, 68, 0.2);
      color: var(--accent-red);
      border: 1px solid var(--accent-red);
      animation: pulse-border 1.5s infinite;
    }
    @keyframes pulse-border {
      0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
      50% { box-shadow: 0 0 8px 2px rgba(239, 68, 68, 0.6); }
    }

    .textarea-wrap {
      position: relative;
    }
    textarea.ru-editor {
      width: 100%;
      min-height: 110px;
      background: var(--bg-input);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 12px;
      color: #fff;
      font-family: var(--font-mono);
      font-size: 15px;
      line-height: 1.5;
      resize: vertical;
      outline: none;
      transition: all 0.15s;
    }
    textarea.ru-editor:focus {
      border-color: var(--accent-cyan);
      box-shadow: 0 0 0 2px rgba(0, 229, 255, 0.2);
    }
    textarea.ru-editor.has-error {
      border-color: var(--accent-red);
    }

    /* Line-by-line char meters */
    .line-meters-container {
      margin-top: 8px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .page-meter-banner {
      width: 100%;
      font-size: 11px;
      font-weight: 700;
      color: var(--accent-blue);
      margin: 8px 0 2px 0;
      padding-bottom: 2px;
      border-bottom: 1px dashed rgba(59, 130, 246, 0.4);
      display: flex;
      align-items: center;
      gap: 6px;
      gap: 6px;
    }
    .line-meter {
      font-family: var(--font-mono);
      font-size: 11px;
      padding: 3px 8px;
      border-radius: 4px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .line-meter.ok {
      background: rgba(16, 185, 129, 0.1);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.2);
    }
    .line-meter.err {
      background: rgba(239, 68, 68, 0.2);
      color: #f87171;
      border: 1px solid var(--accent-red);
      font-weight: 700;
    }

    /* Notification Alerts */
    .alert-box {
      margin-top: 10px;
      padding: 10px 14px;
      border-radius: 6px;
      font-size: 13px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .alert-danger {
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid var(--accent-red);
      color: #fca5a5;
    }

    /* Helper toolbar */
    .editor-toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 14px;
    }
    .toolbar-left, .toolbar-right {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    /* PS1 Dialogue Box Simulator */
    .ps1-sim-container {
      background: #000;
      border: 2px solid #334155;
      border-radius: 8px;
      padding: 16px;
      position: relative;
      overflow: hidden;
      box-shadow: 0 8px 24px rgba(0,0,0,0.8);
    }
    .ps1-sim-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 1px;
      color: #64748b;
    }
    .ps1-dialogue-window {
      background: linear-gradient(180deg, #091e42 0%, #030b18 100%);
      border: 4px ridge #60a5fa;
      border-radius: 4px;
      padding: 14px 18px;
      min-height: 90px;
      position: relative;
      box-shadow: inset 0 0 10px rgba(0,0,0,0.8);
    }
    .ps1-speaker-tag {
      position: absolute;
      top: -12px;
      left: 14px;
      background: #1e3a8a;
      border: 2px solid #93c5fd;
      color: #fff;
      font-size: 11px;
      font-weight: 800;
      padding: 2px 10px;
      letter-spacing: 1px;
      text-transform: uppercase;
      box-shadow: 0 2px 4px rgba(0,0,0,0.6);
    }
    .ps1-dialogue-text {
      font-family: var(--font-mono);
      font-size: 17px;
      line-height: 1.45;
      letter-spacing: 1.2px;
      color: #f8fafc;
      text-shadow: 2px 2px 0 #000;
      white-space: pre;
    }
    .ps1-page-indicator {
      position: absolute;
      bottom: 8px;
      right: 12px;
      font-size: 11px;
      color: #93c5fd;
      display: flex;
      align-items: center;
      gap: 8px;
      background: rgba(0,0,0,0.5);
      padding: 2px 8px;
      border-radius: 4px;
    }
    .scanlines-overlay {
      position: absolute;
      top: 0; left: 0; right: 0; bottom: 0;
      background: repeating-linear-gradient(
        0deg,
        rgba(0,0,0,0.15),
        rgba(0,0,0,0.15) 1px,
        transparent 1px,
        transparent 2px
      );
      pointer-events: none;
    }

    /* Modal Styles */
    .modal-overlay {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.75);
      backdrop-filter: blur(4px);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
    }
    .modal-dialog {
      background: var(--bg-panel);
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      width: 90%;
      max-width: 900px;
      max-height: 85vh;
      display: flex;
      flex-direction: column;
      box-shadow: var(--shadow-md);
      overflow: hidden;
    }
    .modal-header {
      padding: 14px 20px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--bg-card);
    }
    .modal-title {
      font-size: 16px;
      font-weight: 700;
    }
    .modal-body {
      padding: 20px;
      overflow-y: auto;
      flex: 1;
    }
    .terminal-output {
      background: #000;
      color: #38bdf8;
      font-family: var(--font-mono);
      font-size: 12px;
      line-height: 1.5;
      padding: 16px;
      border-radius: 6px;
      white-space: pre-wrap;
      max-height: 480px;
      overflow-y: auto;
      border: 1px solid #1e293b;
    }

    /* Issues Table */
    .issues-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    .issues-table th {
      text-align: left;
      padding: 8px 12px;
      background: var(--bg-card);
      border-bottom: 2px solid var(--border-subtle);
      color: var(--text-dim);
      font-size: 11px;
      text-transform: uppercase;
    }
    .issues-table td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border-subtle);
      vertical-align: top;
    }
    .issues-table tr:hover {
      background: var(--bg-hover);
    }
  </style>
</head>
<body>

  <!-- Top Navigation Header -->
  <header>
    <div class="brand">
      <span class="brand-icon">PS1</span>
      <span>SLAYERS ROYAL</span>
      <span style="color:var(--text-dim);font-weight:400;font-size:12px;">| Редактор перевода</span>
    </div>

    <div class="catalog-selector-wrap">
      <select id="catalogSelect" class="catalog-select" onchange="onCatalogChange(this.value)">
        <!-- Loaded dynamically -->
      </select>
    </div>

    <div class="search-box">
      <span class="icon">🔍</span>
      <input type="text" id="globalSearchInput" placeholder="Поиск (рус, яп, англ, id)..." oninput="onSearchInput(this.value)">
    </div>

    <div class="top-actions">
      <button id="issuesFilterBtn" class="btn btn-danger" onclick="toggleIssuesOnly()">
        <span>⚠️ Только ошибки</span>
        <span id="globalIssuesBadge" class="sidebar-badge has-error">0</span>
      </button>

      <button class="btn btn-primary" onclick="openIssuesDashboard()">
        <span>📋 Дашборд проблем</span>
      </button>

      <button class="btn" onclick="runValidation()">
        <span>⚙️ Валидация build.sh</span>
      </button>

      <div id="saveIndicator" class="save-indicator">
        <span>✓</span>
        <span>Сохранено</span>
      </div>
    </div>
  </header>

  <!-- Workspace Body -->
  <div class="app-body">

    <!-- Left Sidebar: Scenes & Categories -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <span id="sidebarTitle">Сцены / Разделы</span>
        <span id="sidebarCount" class="sidebar-badge">0</span>
      </div>
      <ul id="sidebarList" class="sidebar-list">
        <!-- Loaded dynamically -->
      </ul>
    </aside>

    <!-- Center Content -->
    <main class="content">

      <!-- Subbar with breadcrumbs and pagination -->
      <div class="content-subbar">
        <div class="breadcrumb" id="breadcrumb">
          <span>Каталог</span>
          <span>›</span>
          <strong id="breadcrumbCurrent">Загрузка...</strong>
        </div>

        <div class="pagination-bar">
          <button class="btn" style="padding:3px 8px;" onclick="prevPage()">‹</button>
          <span id="pageInfo">Стр. 1 из 1</span>
          <button class="btn" style="padding:3px 8px;" onclick="nextPage()">›</button>
          <span id="entriesCountInfo" style="color:var(--text-dim);margin-left:8px;">(0 записей)</span>
        </div>
      </div>

      <!-- Center Split: Entry list on left, Editor card on right -->
      <div class="workspace-split">

        <!-- Entry List Pane -->
        <div class="entry-list-pane">
          <div id="entryListItems" class="entry-list-items">
            <!-- Loaded dynamically -->
          </div>
        </div>

        <!-- Editor & Preview Pane -->
        <div class="editor-pane">

          <!-- Active Entry Editor Card -->
          <div class="editor-card" id="editorCard">
            <div class="editor-header">
              <div class="editor-title-block">
                <div style="display:flex;align-items:center;gap:8px;">
                  <span id="speakerPill" class="speaker-pill" style="background:#ef4444;">Лина</span>
                  <span id="editorIdBadge" class="editor-id-badge" onclick="copyContextId()" title="Кликните для копирования">ID</span>
                  <span id="pageBreakAllowedBadge" class="status-badge status-ok">Мультистраничный</span>
                </div>
                <div id="editorLimitsInfo" style="font-size:12px;color:var(--text-dim);">Лимит: ≤15 симв./строка, 1..3 строки</div>
              </div>

              <div>
                <button class="btn btn-primary" onclick="saveCurrentEntry()">
                  <span>💾 Сохранить (Ctrl+S)</span>
                </button>
              </div>
            </div>

            <!-- Japanese Source & English Reference -->
            <div class="ref-grid">
              <div class="ref-box">
                <div class="ref-label">Японский оригинал (PS1 VRAM)</div>
                <div id="textJpBox" class="ref-text ref-text-jp">—</div>
              </div>
              <div class="ref-box">
                <div class="ref-label">Английский референс</div>
                <div id="textEnBox" class="ref-text">—</div>
              </div>
            </div>

            <!-- Russian Editor Field -->
            <div class="editor-main-box">
              <div class="editor-label-bar">
                <div class="editor-label">Русский перевод</div>
                <div class="editor-gauges">
                  <div id="lineCountGauge" class="gauge-pill ok">2 / 3 строки</div>
                  <div id="maxCharGauge" class="gauge-pill ok">Макс. 14 / 15 симв.</div>
                </div>
              </div>

              <div class="textarea-wrap">
                <textarea id="ruEditorTextarea" class="ru-editor" oninput="onEditorInput()"></textarea>
              </div>

              <!-- Line-by-line char indicators -->
              <div id="lineMetersContainer" class="line-meters-container">
                <!-- Line indicators generated in real time -->
              </div>

              <!-- Live alert notifications -->
              <div id="editorAlertBox" class="alert-box alert-danger" style="display:none;"></div>
            </div>

            <!-- Toolbar buttons -->
            <div class="editor-toolbar">
              <div class="toolbar-left">
                <button class="btn" onclick="insertControlCode('\\n')"><span>+ \\n (Строка)</span></button>
                <button class="btn" onclick="insertControlCode('\\f')"><span>+ \\f (Страница)</span></button>
                <button class="btn" onclick="autoWrapText()"><span>✨ Авто-перенос по лимиту</span></button>
              </div>
              <div class="toolbar-right">
                <button class="btn" onclick="revertCurrentEntry()"><span>↺ Сбросить</span></button>
              </div>
            </div>
          </div>

          <!-- Live PS1 Dialogue Box Simulator -->
          <div class="ps1-sim-container">
            <div class="ps1-sim-header">
              <span>Симулятор окна диалогов PS1 (16×16 Pixel Engine)</span>
              <div style="display:flex;align-items:center;gap:12px;">
                <label style="cursor:pointer;display:flex;align-items:center;gap:4px;">
                  <input type="checkbox" id="scanlinesToggle" checked onchange="toggleScanlines(this.checked)">
                  <span>Scanlines CRT</span>
                </label>
              </div>
            </div>

            <div class="ps1-dialogue-window">
              <div id="ps1SpeakerTag" class="ps1-speaker-tag">ЛИHА</div>
              <div id="ps1DialogueText" class="ps1-dialogue-text">На вкус прямо
недурно.</div>
              <div id="ps1PageIndicator" class="ps1-page-indicator" style="display:none;">
                <span onclick="prevPs1Page()" style="cursor:pointer;">◀</span>
                <span id="ps1PageNum">Стр. 1 / 1</span>
                <span onclick="nextPs1Page()" style="cursor:pointer;">▶</span>
              </div>
            </div>

            <div id="scanlinesOverlay" class="scanlines-overlay"></div>
          </div>

        </div>

      </div>

    </main>

  </div>

  <!-- Modal: Issues Dashboard -->
  <div id="issuesModal" class="modal-overlay" style="display:none;">
    <div class="modal-dialog" style="max-width:960px;">
      <div class="modal-header">
        <div class="modal-title">📋 Дашборд проблем и лимитов (Все каталоги)</div>
        <button class="btn" onclick="closeIssuesDashboard()">✕</button>
      </div>
      <div class="modal-body">
        <div id="issuesSummaryBar" style="margin-bottom:16px;display:flex;gap:12px;"></div>
        <table class="issues-table">
          <thead>
            <tr>
              <th>Каталог</th>
              <th>Контекст / ID</th>
              <th>Ошибки лимитов</th>
              <th>Текст</th>
              <th>Действие</th>
            </tr>
          </thead>
          <tbody id="issuesTableBody">
            <!-- Loaded dynamically -->
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Modal: Validation Output -->
  <div id="validationModal" class="modal-overlay" style="display:none;">
    <div class="modal-dialog">
      <div class="modal-header">
        <div class="modal-title">⚙️ Результат валидации проекта (./build.sh --validate)</div>
        <button class="btn" onclick="closeValidationModal()">✕</button>
      </div>
      <div class="modal-body">
        <div id="validationOutput" class="terminal-output">Запуск валидации...</div>
      </div>
    </div>
  </div>

  <script>
    // Constants for clean page breaks without escape ambiguities
    const FF = String.fromCharCode(12);
    const LF = String.fromCharCode(10);
    const PAGE_TAG = String.fromCharCode(92) + "f" + LF;

    function toVisible(text) {
      if (!text) return "";
      return text.split(FF).join(PAGE_TAG);
    }

    function toInternal(text) {
      if (!text) return "";
      return text.split(PAGE_TAG).join(FF).split(String.fromCharCode(92) + "f").join(FF);
    }

    function splitPages(text) {
      if (!text) return [""];
      return toInternal(text).split(FF);
    }

    // State
    // State
    let currentCatalogId = "story_dialogues";
    let currentSceneId = null;
    let currentSearch = "";
    let currentIssuesOnly = false;
    let currentPage = 1;
    let totalPages = 1;
    let currentEntries = [];
    let activeEntry = null;
    let ps1ActivePage = 0;
    let allCatalogsMeta = [];

    // Colors mapping
    const SPEAKER_COLORS = {
      "Lina": "#ef4444", "Лина": "#ef4444",
      "Gourry": "#f59e0b", "Гаури": "#f59e0b",
      "Naga": "#a855f7", "Нага": "#a855f7",
      "Amelia": "#3b82f6", "Амелия": "#3b82f6",
      "Zelgadis": "#06b6d4", "Зелгадис": "#06b6d4",
      "Sylphiel": "#10b981", "Сильфиль": "#10b981",
      "Lark": "#8b5cf6", "Ларк": "#8b5cf6",
      "Emilia": "#ec4899", "Эмилия": "#ec4899"
    };

    async function init() {
      await loadCatalogsList();
      await loadCurrentCatalog();
      setupKeyboardShortcuts();
    }

    async function loadCatalogsList() {
      try {
        const res = await fetch("/api/catalogs");
        const data = await res.json();
        allCatalogsMeta = data.catalogs || [];

        const select = document.getElementById("catalogSelect");
        select.innerHTML = "";

        let globalIssues = 0;
        allCatalogsMeta.forEach(c => {
          globalIssues += c.issues_count;
          const opt = document.createElement("option");
          opt.value = c.id;
          const badgeText = c.issues_count > 0 ? ` ⚠️ [${c.issues_count}]` : "";
          opt.textContent = `${c.icon} ${c.title} (${c.total_entries})${badgeText}`;
          if (c.id === currentCatalogId) opt.selected = true;
          select.appendChild(opt);
        });

        document.getElementById("globalIssuesBadge").textContent = globalIssues;
      } catch (err) {
        console.error("Failed to load catalogs:", err);
      }
    }

    async function loadCurrentCatalog(keepActiveEntryId = null) {
      try {
        let url = `/api/catalog/${currentCatalogId}?page=${currentPage}&limit=50`;
        if (currentSceneId) url += `&scene=${encodeURIComponent(currentSceneId)}`;
        if (currentSearch) url += `&search=${encodeURIComponent(currentSearch)}`;
        if (currentIssuesOnly) url += `&issues_only=true`;

        const res = await fetch(url);
        const data = await res.json();

        currentEntries = data.entries || [];
        totalPages = data.total_pages || 1;
        currentPage = data.page || 1;

        // Update Breadcrumb & Header info
        document.getElementById("breadcrumbCurrent").textContent = `${data.catalog.title} (${data.filtered_entries} из ${data.total_entries})`;
        document.getElementById("pageInfo").textContent = `Стр. ${currentPage} из ${totalPages}`;
        document.getElementById("entriesCountInfo").textContent = `(${data.filtered_entries} найдено)`;

        // Render Sidebar Scenes / Categories
        renderSidebar(data.scenes || []);

        // Render Entry List
        renderEntryList();

        // Select active entry
        if (currentEntries.length > 0) {
          if (keepActiveEntryId) {
            const found = currentEntries.find(e => e.id === keepActiveEntryId);
            setActiveEntry(found || currentEntries[0]);
          } else {
            setActiveEntry(currentEntries[0]);
          }
        } else {
          setActiveEntry(null);
        }

      } catch (err) {
        console.error("Error loading catalog data:", err);
      }
    }

    function renderSidebar(scenes) {
      const list = document.getElementById("sidebarList");
      list.innerHTML = "";

      // "All" item
      const allItem = document.createElement("li");
      allItem.className = `sidebar-item ${currentSceneId === null ? "active" : ""}`;
      allItem.onclick = () => selectScene(null);
      allItem.innerHTML = `<span>Все разделы</span><span class="sidebar-badge">${scenes.reduce((acc, s) => acc + s.count, 0)}</span>`;
      list.appendChild(allItem);

      scenes.forEach(s => {
        const item = document.createElement("li");
        item.className = `sidebar-item ${currentSceneId === s.id ? "active" : ""}`;
        item.onclick = () => selectScene(s.id);
        const errClass = s.issues > 0 ? "has-error" : "";
        const errText = s.issues > 0 ? `⚠️ ${s.issues}` : s.count;
        item.innerHTML = `<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${s.title}">${s.title}</span><span class="sidebar-badge ${errClass}">${errText}</span>`;
        list.appendChild(item);
      });

      document.getElementById("sidebarCount").textContent = scenes.length;
    }

    function renderEntryList() {
      const container = document.getElementById("entryListItems");
      container.innerHTML = "";

      if (currentEntries.length === 0) {
        container.innerHTML = `<div style="padding:24px;text-align:center;color:var(--text-dim);">Записей не найдено</div>`;
        return;
      }

      currentEntries.forEach(e => {
        const row = document.createElement("div");
        row.className = `entry-row ${activeEntry && activeEntry.id === e.id ? "active" : ""}`;
        row.onclick = () => setActiveEntry(e);

        const speakerName = e.speaker_ru || e.speaker || "—";
        const speakerColor = SPEAKER_COLORS[speakerName] || SPEAKER_COLORS[e.speaker] || "#64748b";

        const isErr = e.validation.exceeds_limits;
        const statusClass = isErr ? "status-err" : "status-ok";
        const statusText = isErr ? "ОШИБКА ЛИМИТА" : "OK";

        row.innerHTML = `
          <div class="entry-row-header">
            ${e.speaker ? `<span class="speaker-pill" style="background:${speakerColor}">${speakerName}</span>` : `<span></span>`}
            <span class="ctx-pill">${e.id}</span>
          </div>
          <div class="entry-row-text">${escapeHtml(e.text_ru || "—")}</div>
          <div class="entry-row-status">
            <span class="status-badge ${statusClass}">${statusText}</span>
            <span style="font-size:11px;color:var(--text-dim);">${e.category || ""}</span>
          </div>
        `;
        container.appendChild(row);
      });
    }

    function setActiveEntry(entry) {
      activeEntry = entry;
      ps1ActivePage = 0;

      // Update active highlight in entry list
      document.querySelectorAll(".entry-row").forEach((row, i) => {
        if (currentEntries[i] && activeEntry && currentEntries[i].id === activeEntry.id) {
          row.classList.add("active");
        } else {
          row.classList.remove("active");
        }
      });

      if (!entry) {
        document.getElementById("editorCard").style.display = "none";
        return;
      }

      document.getElementById("editorCard").style.display = "block";

      // Speaker & ID
      const speakerName = entry.speaker_ru || entry.speaker || "—";
      const spPill = document.getElementById("speakerPill");
      if (entry.speaker) {
        spPill.style.display = "inline-block";
        spPill.textContent = speakerName;
        spPill.style.background = SPEAKER_COLORS[speakerName] || SPEAKER_COLORS[entry.speaker] || "#64748b";
      } else {
        spPill.style.display = "none";
      }

      document.getElementById("editorIdBadge").textContent = entry.id;

      // Allow page break badge
      const pbBadge = document.getElementById("pageBreakAllowedBadge");
      if (entry.limits && entry.limits.single_line) {
        pbBadge.textContent = "Одна строка";
        pbBadge.className = "status-badge status-ok";
      } else if (entry.allow_page_break) {
        pbBadge.textContent = "Мультистраничный (\\f OK)";
        pbBadge.className = "status-badge status-ok";
      } else {
        pbBadge.textContent = "1 страница (\\f ЗАПРЕЩЕН)";
        pbBadge.className = "status-badge status-err";
      }

      // Limits description
      let limDesc = "";
      if (entry.limits.single_line) {
        limDesc = `Лимит: одна строка ≤ ${entry.limits.max_chars_total || entry.limits.max_chars_per_line} симв.`;
      } else {
        limDesc = `Лимит: ≤ ${entry.limits.max_chars_per_line || 15} симв./строку, 1..${entry.limits.max_lines_page || 3} строки`;
      }
      document.getElementById("editorLimitsInfo").textContent = limDesc;

      // References
      document.getElementById("textJpBox").textContent = entry.text_jp || "—";
      document.getElementById("textEnBox").textContent = entry.text_en || "—";

      // Textarea
      const textarea = document.getElementById("ruEditorTextarea");
      textarea.value = toVisible(entry.text_ru);

      // Realtime validation
      updateRealtimeGauges();
      updatePs1Preview();
    }

    function onEditorInput() {
      if (!activeEntry) return;
      activeEntry.text_ru = toInternal(document.getElementById("ruEditorTextarea").value);
      updateRealtimeGauges();
      updatePs1Preview();
      markUnsaved();
    }

    function updateRealtimeGauges() {
      if (!activeEntry) return;
      const text = document.getElementById("ruEditorTextarea").value;
      const limits = activeEntry.limits || {};

      const linesGauge = document.getElementById("lineCountGauge");
      const maxCharGauge = document.getElementById("maxCharGauge");
      const metersContainer = document.getElementById("lineMetersContainer");
      const alertBox = document.getElementById("editorAlertBox");
      const textarea = document.getElementById("ruEditorTextarea");

      metersContainer.innerHTML = "";
      alertBox.innerHTML = "";
      alertBox.style.display = "none";

      const pages = splitPages(text);
      let overallMax = 0;
      let totalLines = 0;
      let errors = [];

      if (pages.length > 1 && limits.allow_page_break === false) {
        errors.push("Символ \\f запрещен для этой записи (должна быть строго 1 страница)!");
      }

      pages.forEach((p, pIdx) => {
        if (pages.length > 1) {
          const banner = document.createElement("div");
          banner.className = "page-meter-banner";
          banner.textContent = `📄 Страница ${pIdx + 1} из ${pages.length}`;
          metersContainer.appendChild(banner);
        }
        const lines = p.split(LF).map(l => l.endsWith(String.fromCharCode(13)) ? l.slice(0, -1) : l);
        totalLines += lines.length;

        if (lines.length > (limits.max_lines_per_page || 3) && !limits.single_line) {
          errors.push(`Страница ${pIdx + 1} содержит ${lines.length} строк (максимум ${limits.max_lines_per_page || 3})`);
        }

        lines.forEach((l, lIdx) => {
          const lLen = l.length;
          if (lLen > overallMax) overallMax = lLen;

          const maxLimit = limits.single_line ? (limits.max_chars_total || 10) : (limits.max_chars_per_line || 15);
          const isOver = lLen > maxLimit;

          if (isOver) {
            errors.push(`Стр. ${pIdx + 1}, строка ${lIdx + 1}: ${lLen} симв. (превышает лимит ${maxLimit} на ${lLen - maxLimit} симв.)`);
          }

          if (!l && lines.length > 1) {
            errors.push(`Стр. ${pIdx + 1}, строка ${lIdx + 1} пустая (пустые строки не допускаются)`);
          }

          const meter = document.createElement("span");
          meter.className = `line-meter ${isOver ? "err" : "ok"}`;
          meter.textContent = `Стр ${pIdx+1}:Стрк ${lIdx+1} → ${lLen} / ${maxLimit} с.`;
          metersContainer.appendChild(meter);
        });
      });

      // Update Top Gauges
      const maxLimit = limits.single_line ? (limits.max_chars_total || 10) : (limits.max_chars_per_line || 15);
      const isCharBad = overallMax > maxLimit;
      maxCharGauge.textContent = `Макс. ${overallMax} / ${maxLimit} симв.`;
      maxCharGauge.className = `gauge-pill ${isCharBad ? "bad" : "ok"}`;

      if (limits.single_line) {
        linesGauge.textContent = "1 строка";
        linesGauge.className = text.includes("\\n") ? "gauge-pill bad" : "gauge-pill ok";
      } else {
        const isLinesBad = pages.some(p => p.split(LF).length > (limits.max_lines_per_page || 3));
        linesGauge.textContent = `${totalLines} строк(и)`;
        linesGauge.className = `gauge-pill ${isLinesBad ? "bad" : "ok"}`;
      }

      if (errors.length > 0) {
        alertBox.style.display = "block";
        alertBox.innerHTML = errors.map(e => `<div>⚠️ ${escapeHtml(e)}</div>`).join("");
        textarea.classList.add("has-error");
      } else {
        textarea.classList.remove("has-error");
      }
    }

    function updatePs1Preview() {
      if (!activeEntry) return;
      const text = document.getElementById("ruEditorTextarea").value;
      const pages = splitPages(text);

      const speakerName = activeEntry.speaker_ru || activeEntry.speaker || "";
      const spTag = document.getElementById("ps1SpeakerTag");
      if (speakerName) {
        spTag.style.display = "block";
        spTag.textContent = speakerName.toUpperCase();
      } else {
        spTag.style.display = "none";
      }

      // Page pagination in preview
      const pageIndicator = document.getElementById("ps1PageIndicator");
      if (pages.length > 1) {
        pageIndicator.style.display = "flex";
        if (ps1ActivePage >= pages.length) ps1ActivePage = 0;
        document.getElementById("ps1PageNum").textContent = `Стр. ${ps1ActivePage + 1} / ${pages.length}`;
      } else {
        pageIndicator.style.display = "none";
        ps1ActivePage = 0;
      }

      const activePageText = pages[ps1ActivePage] || "";
      document.getElementById("ps1DialogueText").textContent = activePageText;
    }

    function prevPs1Page() {
      const text = document.getElementById("ruEditorTextarea").value;
      const pages = splitPages(text);
      if (pages.length <= 1) return;
      ps1ActivePage = (ps1ActivePage - 1 + pages.length) % pages.length;
      updatePs1Preview();
    }

    function nextPs1Page() {
      const text = document.getElementById("ruEditorTextarea").value;
      const pages = splitPages(text);
      if (pages.length <= 1) return;
      ps1ActivePage = (ps1ActivePage + 1) % pages.length;
      updatePs1Preview();
    }

    function toggleScanlines(enabled) {
      document.getElementById("scanlinesOverlay").style.display = enabled ? "block" : "none";
    }

    function insertControlCode(code) {
      const textarea = document.getElementById("ruEditorTextarea");
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const val = textarea.value;
      const insertText = code === "\\f" ? PAGE_TAG : code;
      textarea.value = val.substring(0, start) + insertText + val.substring(end);
      textarea.selectionStart = textarea.selectionEnd = start + insertText.length;
      textarea.focus();
      onEditorInput();
    }

    function autoWrapText() {
      if (!activeEntry) return;
      const textarea = document.getElementById("ruEditorTextarea");
      const text = textarea.value;
      const maxLen = (activeEntry.limits && activeEntry.limits.max_chars_per_line) || 15;

      // Smart auto-wrapper: splits into words and wraps at maxLen
      const pages = splitPages(text);
      const wrappedPages = pages.map(page => {
        const words = page.split(LF).join(" ").split(String.fromCharCode(13)).join("").split(" ").filter(Boolean);
        const lines = [];
        let curLine = "";
        for (const w of words) {
          if (!curLine) {
            curLine = w;
          } else if (curLine.length + 1 + w.length <= maxLen) {
            curLine += " " + w;
          } else {
            lines.push(curLine);
            curLine = w;
          }
        }
        if (curLine) lines.push(curLine);
        return lines.join(LF);
      });

      textarea.value = wrappedPages.join(LF + PAGE_TAG);
      onEditorInput();
    }

    async function saveCurrentEntry() {
      if (!activeEntry) return;
      const rawVal = document.getElementById("ruEditorTextarea").value;
      const newText = toInternal(rawVal);
      setSaveStatus("saving");
      try {
        const res = await fetch("/api/entry", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            catalog_id: activeEntry.catalog_id,
            id: activeEntry.id,
            text_ru: newText
          })
        });

        const data = await res.json();
        if (data.success && data.entry) {
          activeEntry = data.entry;
          // Update in entries array
          const idx = currentEntries.findIndex(e => e.id === activeEntry.id);
          if (idx !== -1) currentEntries[idx] = activeEntry;
          renderEntryList();
          setSaveStatus("saved");
          loadCatalogsList(); // refresh issue counters
        } else {
          setSaveStatus("error");
          alert("Ошибка сохранения: " + (data.error || "Неизвестная ошибка"));
        }
      } catch (err) {
        console.error("Save failed:", err);
        setSaveStatus("error");
      }
    }

    function revertCurrentEntry() {
      if (!activeEntry) return;
      document.getElementById("ruEditorTextarea").value = toVisible(activeEntry.text_ru);
      onEditorInput();
      setSaveStatus("saved");
    }

    function markUnsaved() {
      setSaveStatus("unsaved");
    }

    function setSaveStatus(status) {
      const ind = document.getElementById("saveIndicator");
      if (status === "saved") {
        ind.style.background = "rgba(16, 185, 129, 0.1)";
        ind.style.borderColor = "rgba(16, 185, 129, 0.3)";
        ind.style.color = "var(--accent-green)";
        ind.innerHTML = "<span>✓</span><span>Сохранено</span>";
      } else if (status === "saving") {
        ind.style.background = "rgba(0, 229, 255, 0.1)";
        ind.style.borderColor = "rgba(0, 229, 255, 0.3)";
        ind.style.color = "var(--accent-cyan)";
        ind.innerHTML = "<span>⏳</span><span>Сохранение...</span>";
      } else if (status === "unsaved") {
        ind.style.background = "rgba(245, 158, 11, 0.1)";
        ind.style.borderColor = "rgba(245, 158, 11, 0.3)";
        ind.style.color = "var(--accent-gold)";
        ind.innerHTML = "<span>●</span><span>Не сохранено</span>";
      } else if (status === "error") {
        ind.style.background = "rgba(239, 68, 68, 0.1)";
        ind.style.borderColor = "rgba(239, 68, 68, 0.3)";
        ind.style.color = "var(--accent-red)";
        ind.innerHTML = "<span>✕</span><span>Ошибка сохранения</span>";
      }
    }

    function onCatalogChange(catId) {
      currentCatalogId = catId;
      currentSceneId = null;
      currentPage = 1;
      loadCurrentCatalog();
    }

    function selectScene(sceneId) {
      currentSceneId = sceneId;
      currentPage = 1;
      loadCurrentCatalog();
    }

    function onSearchInput(val) {
      currentSearch = val;
      currentPage = 1;
      loadCurrentCatalog();
    }

    function toggleIssuesOnly() {
      currentIssuesOnly = !currentIssuesOnly;
      const btn = document.getElementById("issuesFilterBtn");
      if (currentIssuesOnly) {
        btn.classList.add("btn-active");
      } else {
        btn.classList.remove("btn-active");
      }
      currentPage = 1;
      loadCurrentCatalog();
    }

    function prevPage() {
      if (currentPage > 1) {
        currentPage--;
        loadCurrentCatalog();
      }
    }

    function nextPage() {
      if (currentPage < totalPages) {
        currentPage++;
        loadCurrentCatalog();
      }
    }

    function copyContextId() {
      if (!activeEntry) return;
      navigator.clipboard.writeText(activeEntry.id);
      const b = document.getElementById("editorIdBadge");
      const orig = b.textContent;
      b.textContent = "Скопировано!";
      setTimeout(() => b.textContent = orig, 1200);
    }

    async function openIssuesDashboard() {
      const modal = document.getElementById("issuesModal");
      modal.style.display = "flex";

      const tbody = document.getElementById("issuesTableBody");
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:24px;">Загрузка списка ошибок...</td></tr>`;

      try {
        const res = await fetch("/api/issues");
        const data = await res.json();
        const issues = data.issues || [];

        // Summary bar
        const sumBar = document.getElementById("issuesSummaryBar");
        sumBar.innerHTML = `
          <div style="background:var(--bg-card);padding:10px 16px;border-radius:6px;border:1px solid var(--border-subtle);flex:1;">
            <div style="font-size:11px;color:var(--text-dim);">ВСЕГО ОШИБОК</div>
            <div style="font-size:20px;font-weight:800;color:var(--accent-red);">${data.total_issues}</div>
          </div>
        `;

        Object.entries(data.catalogs || {}).forEach(([catId, count]) => {
          if (count > 0) {
            const card = document.createElement("div");
            card.style.cssText = "background:var(--bg-card);padding:10px 16px;border-radius:6px;border:1px solid var(--border-subtle);cursor:pointer;";
            card.onclick = () => { closeIssuesDashboard(); currentCatalogId = catId; onCatalogChange(catId); };
            card.innerHTML = `<div style="font-size:11px;color:var(--text-dim);">${catId}</div><div style="font-size:18px;font-weight:700;color:var(--accent-red);">${count}</div>`;
            sumBar.appendChild(card);
          }
        });

        tbody.innerHTML = "";
        if (issues.length === 0) {
          tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--accent-green);font-weight:700;">✓ Все каталоги удовлетворяют аппаратным ограничениям PS1! Ошибок нет.</td></tr>`;
          return;
        }

        issues.forEach(iss => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td style="font-weight:600;">${iss.catalog_title}</td>
            <td style="font-family:var(--font-mono);font-size:11px;color:var(--accent-cyan);">${iss.entry_id}</td>
            <td style="color:var(--accent-red);">${iss.errors.map(escapeHtml).join("<br>")}</td>
            <td style="font-family:var(--font-mono);font-size:12px;white-space:pre-wrap;max-width:250px;">${escapeHtml(iss.text_ru)}</td>
            <td>
              <button class="btn btn-primary" style="padding:4px 8px;font-size:11px;" onclick="jumpToIssue('${iss.catalog_id}', '${iss.scene_id}', '${escapeAttr(iss.entry_id)}')">
                Перейти
              </button>
            </td>
          `;
          tbody.appendChild(tr);
        });

      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--accent-red);">Ошибка загрузки: ${err}</td></tr>`;
      }
    }

    function closeIssuesDashboard() {
      document.getElementById("issuesModal").style.display = "none";
    }

    function jumpToIssue(catId, sceneId, entryId) {
      closeIssuesDashboard();
      currentCatalogId = catId;
      document.getElementById("catalogSelect").value = catId;
      currentSceneId = sceneId || null;
      currentPage = 1;
      currentIssuesOnly = false;
      document.getElementById("issuesFilterBtn").classList.remove("btn-active");
      loadCurrentCatalog(entryId);
    }

    async function runValidation() {
      const modal = document.getElementById("validationModal");
      const out = document.getElementById("validationOutput");
      modal.style.display = "flex";
      out.textContent = "Запуск ./build.sh --validate... Пожалуйста, подождите...\\n";

      try {
        const res = await fetch("/api/run_validate", { method: "POST" });
        const data = await res.json();
        out.textContent = data.output || "Нет вывода.";
      } catch (err) {
        out.textContent = "Ошибка выполнения валидации: " + err;
      }
    }

    function closeValidationModal() {
      document.getElementById("validationModal").style.display = "none";
    }

    function setupKeyboardShortcuts() {
      window.addEventListener("keydown", (e) => {
        // Ctrl+S / Cmd+S: Save
        if ((e.ctrlKey || e.metaKey) && e.key === "s") {
          e.preventDefault();
          saveCurrentEntry();
        }
        // Alt+Down: Next entry
        if (e.altKey && e.key === "ArrowDown") {
          e.preventDefault();
          if (activeEntry && currentEntries.length > 0) {
            const idx = currentEntries.findIndex(item => item.id === activeEntry.id);
            if (idx !== -1 && idx < currentEntries.length - 1) {
              setActiveEntry(currentEntries[idx + 1]);
            }
          }
        }
        // Alt+Up: Prev entry
        if (e.altKey && e.key === "ArrowUp") {
          e.preventDefault();
          if (activeEntry && currentEntries.length > 0) {
            const idx = currentEntries.findIndex(item => item.id === activeEntry.id);
            if (idx > 0) {
              setActiveEntry(currentEntries[idx - 1]);
            }
          }
        }
      });
    }

    function escapeHtml(text) {
      if (!text) return "";
      return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function escapeAttr(text) {
      if (!text) return "";
      return text.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    // Start on load
    window.addEventListener("DOMContentLoaded", init);
  </script>
</body>
</html>
"""


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    """Start HTTP server."""
    server_address = (host, port)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    httpd = socketserver.ThreadingTCPServer(server_address, TranslationEditorHandler)

    url = f"http://{host}:{port}/"
    print("=" * 68)
    print("  SLAYERS ROYAL (PS1) — TRANSLATION STUDIO & HARDWARE LIMITS ENGINE")
    print("=" * 68)
    print(f"[*] Сервер запущен: {url}")
    print(f"[*] Каталогов подключено: {len(CATALOG_DEFS)}")
    print("    - story_dialogues_ru.json (4,514 реплик, 30 сцен)")
    print("    - combat_dialogues_ru.json (114 блоков, 264 реплики)")
    print("    - room_inspection_ru.json (149 комнат, 734 реплики)")
    print("    - room_names_ru.json (160 комнат)")
    print("    - minigames_ru.json (правила 5 игр, викторина)")
    print("    - town_services_ru.json (таверна, отель, иконки)")
    print("    - shop_dialogues_ru.json (диалоги лавки + 91 предмет)")
    print("    - world_map_ru.json (20 локаций)")
    print("    - location_banners_ru.json (23 вывески)")
    print("    - lore_cards_ru.json (13 справочных карточек)")
    print("    - spells_ru.json (119 заклинаний)")
    print("[*] Для остановки нажмите Ctrl+C")
    print("=" * 68)

    if open_browser:
        import webbrowser
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Завершение работы сервера...")
    finally:
        httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Slayers Royal (PS1) Web-based Translation Editor & Hardware Limits Engine"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Хост для прослушивания (по умолчанию: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Порт для прослушивания (по умолчанию: 8765)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Автоматически открыть браузер после запуска",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Выполнить проверку аппаратных ограничений всех каталогов и выйти",
    )
    args = parser.parse_args()

    if args.validate_only:
        issues = MANAGER.get_all_issues()
        print(f"Всего нарушений аппаратных ограничений: {issues['total_issues']}")
        for cat_id, cnt in issues["catalogs"].items():
            print(f"  {cat_id:20s}: {cnt} нарушений")
        sys.exit(0 if issues["total_issues"] == 0 else 1)

    run_server(host=args.host, port=args.port, open_browser=args.open)


if __name__ == "__main__":
    main()
