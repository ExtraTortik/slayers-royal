#!/usr/bin/env python3
"""Bidirectional synchronization and validation tool for Slayers Royal story dialogues.

Synchronizes between the developer-friendly JSON format (translations/story_dialogues_ru.json)
and the compiler PO catalog (patch_repo/localization-work/ru/dialogue.po), enforcing all PS1
hardware layout rules (<=15 chars/line, 1-3 lines/page, form feed \\f restrictions, NFC).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure patch_repo is on python path for localization.po and localization.script
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))

try:
    from localization.po import PoEntry, PoError, read_po, write_po
except ImportError as exc:
    raise RuntimeError(f"Failed to import localization.po from {REPO_ROOT / 'patch_repo'}: {exc}") from exc

DEFAULT_PO_PATH = REPO_ROOT / "patch_repo" / "localization-work" / "ru" / "dialogue.po"
DEFAULT_JSON_PATH = REPO_ROOT / "translations" / "story_dialogues_ru.json"

MAX_CHARS_PER_LINE = 15
MIN_LINES_PER_PAGE = 1
MAX_LINES_PER_PAGE = 3
TOTAL_EXPECTED_ENTRIES = 4514
TOTAL_EXPECTED_SCENES = 30

SPEAKERS_GLOSSARY: dict[str, str] = {
    "Lina": "Лина",
    "Gourry": "Гаури",
    "Naga": "Нага",
    "Zelgadis": "Зелгадис",
    "Amelia": "Амелия",
    "Sylphiel": "Сильфиль",
    "Lark": "Ларк",
    "Emilia": "Эмилия",
}

SCENE_TITLES: dict[str, str] = {
    "03B": "Сцена 0x03B: Таверна Лейквуда / Встреча с Нагой",
    "03C": "Сцена 0x03C: Лейквуд / Главная улица и знакомство с Ларком",
    "03D": "Сцена 0x03D: Окраины Лейквуда / По следам бандитов",
    "03E": "Сцена 0x03E: Город Сония / Поиски подсказок и встреча с Зелгадисом",
    "03F": "Сцена 0x03F: Руины Маркуэллс / Древние развалины",
    "040": "Сцена 0x040: Город Изельсен / Поиски Зодда",
    "041": "Сцена 0x041: Город Квезакс / Расследование и поиски улик",
    "042": "Сцена 0x042: Город Квезакс / Базарная площадь и разговоры",
    "043": "Сцена 0x043: Дорога на Сэйрун / Неожиданная засада",
    "044": "Сцена 0x044: Город Баркленд / Отдых и разговоры",
    "045": "Сцена 0x045: Город Тул-Сити / Подготовка к походу",
    "046": "Сцена 0x046: Лесная развилка / Путь через чащу",
    "047": "Сцена 0x047: Знакомство с Ларком Диа Флеймдолом",
    "048": "Сцена 0x048: Слежка и преследование бандитами",
    "049": "Сцена 0x049: Дорога в Грамсток через лес",
    "04A": "Сцена 0x04A: Опасная развилка / Заблудившийся отряд",
    "04B": "Сцена 0x04B: Допрос бандитов и разведка Зелгадиса",
    "04C": "Сцена 0x04C: Застава бандитов / Блокпост",
    "04D": "Сцена 0x04D: Горный перевал / Привал отряда",
    "04E": "Сцена 0x04E: Поиски по наводке Эмилии",
    "04F": "Сцена 0x04F: Священная столица Сэйрун",
    "050": "Сцена 0x050: Нападение охотника за головами (Встреча 1)",
    "051": "Сцена 0x051: Нападение охотника за головами (Встреча 2)",
    "052": "Сцена 0x052: Нападение охотника за головами (Встреча 3)",
    "053": "Сцена 0x053: Долина драконов / В поисках Галефа",
    "054": "Сцена 0x054: Нападение охотника за головами (Встреча 4)",
    "055": "Сцена 0x055: Лагерь на пути к святилищу",
    "056": "Сцена 0x056: Нападение охотника за головами (Встреча 5)",
    "057": "Сцена 0x057: Финальные сборы перед решающей битвой",
    "139": "Сцена 0x139: Специальный банк сюжетных развилок и подсказок",
}


def parse_entry_comments(comments: tuple[str, ...]) -> dict[str, Any]:
    """Extract metadata from PO comments."""
    family = "tagged"
    speaker: str | None = None
    allow_page_break = True
    controls: list[str] = []

    for c in comments:
        c_stripped = c.strip()
        if c_stripped.startswith("PROG entry"):
            parts = [p.strip() for p in c_stripped.split(";")]
            if len(parts) > 1:
                family = parts[1]
        elif c_stripped.startswith("Probable speaker:"):
            speaker = c_stripped.split(":", 1)[1].strip()
        elif "Use \\f between additional pages" in c_stripped:
            allow_page_break = True
        elif "This FF segment cannot add another page" in c_stripped:
            allow_page_break = False
        elif c_stripped.startswith("Preserved engine controls:"):
            controls = c_stripped.split(":", 1)[1].strip().split()

    return {
        "family": family,
        "speaker": speaker,
        "allow_page_break": allow_page_break,
        "controls": controls,
    }


def export_dialogues(po_path: Path, json_path: Path) -> dict[str, Any]:
    """Export dialogue.po to formatted translations/story_dialogues_ru.json."""
    if not po_path.exists():
        raise FileNotFoundError(f"Source PO file not found: {po_path}")

    entries = read_po(po_path)

    # Group entries by scene
    scenes_map: dict[str, dict[str, Any]] = {}

    for entry in entries:
        parts = entry.context.split("/")
        if len(parts) != 4 or parts[0] != "dialogue":
            raise ValueError(f"Unexpected context format: {entry.context!r}")

        scene_id = parts[1]
        record_key = parts[2]
        segment_index = int(parts[3])

        meta = parse_entry_comments(entry.comments)

        if scene_id not in scenes_map:
            scenes_map[scene_id] = {
                "scene_id": scene_id,
                "entry_hex": f"0x{scene_id}",
                "family": meta["family"],
                "title": SCENE_TITLES.get(scene_id, f"Сцена 0x{scene_id}"),
                "records_set": set(),
                "dialogues": [],
            }

        scenes_map[scene_id]["records_set"].add(record_key)
        speaker = meta["speaker"]
        speaker_ru = SPEAKERS_GLOSSARY.get(speaker) if speaker else None

        scenes_map[scene_id]["dialogues"].append(
            {
                "context": entry.context,
                "record": record_key,
                "index": segment_index,
                "speaker": speaker,
                "speaker_ru": speaker_ru,
                "allow_page_break": meta["allow_page_break"],
                "controls": meta["controls"],
                "text_jp": entry.source,
                "text_ru": entry.translation,
            }
        )

    # Format scenes list
    scenes_list: list[dict[str, Any]] = []
    total_dialogues = 0

    for scene_id, scene_info in scenes_map.items():
        segment_count = len(scene_info["dialogues"])
        total_dialogues += segment_count
        scenes_list.append(
            {
                "scene_id": scene_id,
                "entry_hex": scene_info["entry_hex"],
                "family": scene_info["family"],
                "title": scene_info["title"],
                "record_count": len(scene_info["records_set"]),
                "segment_count": segment_count,
                "dialogues": scene_info["dialogues"],
            }
        )

    rel_po = str(po_path)
    try:
        rel_po = str(po_path.relative_to(REPO_ROOT))
    except ValueError:
        pass

    data: dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "metadata": {
            "title": "Slayers Royal (PS1) — Каталог сюжетных диалогов",
            "version": "1.0",
            "description": "4514 реплик сюжетных диалогов, сцен, развилок и NPC (PROG.UNT 0x03B..0x057, 0x139)",
            "target_po": rel_po,
            "target_archive": "PROG.UNT",
            "locale": "ru",
            "total_scenes": len(scenes_list),
            "total_entries": total_dialogues,
            "rules": {
                "max_chars_per_line": MAX_CHARS_PER_LINE,
                "max_lines_per_page": MAX_LINES_PER_PAGE,
                "line_break": "\\n",
                "page_break": "\\f",
                "ff_rule": (
                    "Если allow_page_break == false (FF-сегмент), символ \\f запрещён — "
                    "реплика должна умещаться на одной странице (до 3 строк)."
                ),
            },
            "speakers_glossary": SPEAKERS_GLOSSARY,
        },
        "scenes": scenes_list,
    }

    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return data


def validate_dialogue_text(
    text: str,
    allow_page_break: bool,
    context: str,
) -> list[str]:
    """Validate a single dialogue string against PS1 hardware limits.

    Returns a list of error strings (empty if valid).
    """
    errors: list[str] = []

    # 1. NFC normalization check
    raw_cleaned = text.replace("\r", "")
    normalized = unicodedata.normalize("NFC", raw_cleaned)
    if normalized != raw_cleaned:
        errors.append(f"{context}: текст должен использовать нормализованный Unicode (NFC)")

    # 2. Check for carriage returns
    if "\r" in text:
        errors.append(f"{context}: присутствуют недопустимые символы возврата каретки (\\r)")

    # 3. Form feed check
    pages = normalized.split("\f")
    if len(pages) > 1 and not allow_page_break:
        errors.append(
            f"{context}: сегмент с терминатором FF не поддерживает разделение страниц (найден символ \\f)"
        )

    # 4. Per-page and per-line checks
    for page_idx, page in enumerate(pages, 1):
        lines = page.split("\n")
        if not (MIN_LINES_PER_PAGE <= len(lines) <= MAX_LINES_PER_PAGE):
            errors.append(
                f"{context}: страница {page_idx} содержит {len(lines)} строк (допустимо от {MIN_LINES_PER_PAGE} до {MAX_LINES_PER_PAGE})"
            )

        for line_idx, line in enumerate(lines, 1):
            if not line:
                errors.append(
                    f"{context}: страница {page_idx}, строка {line_idx} пустая (не допускаются пустые строки)"
                )
            elif len(line) > MAX_CHARS_PER_LINE:
                errors.append(
                    f"{context}: страница {page_idx}, строка {line_idx} содержит {len(line)} символов "
                    f"(максимум {MAX_CHARS_PER_LINE}): {line!r}"
                )

    return errors


def validate_catalog(
    json_path: Path,
    expected_contexts: set[str] | None = None,
    check_total_count: bool = True,
) -> tuple[bool, list[str]]:
    """Validate entire story_dialogues_ru.json file.

    Returns (is_valid, list_of_errors).
    """
    if not json_path.exists():
        return False, [f"Файл не найден: {json_path}"]

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return False, [f"Ошибка парсинга JSON: {exc}"]

    errors: list[str] = []

    scenes = data.get("scenes")
    if not isinstance(scenes, list):
        return False, ["Корневой ключ 'scenes' должен быть списком"]

    found_contexts: set[str] = set()
    total_dialogues = 0

    for scene in scenes:
        scene_id = scene.get("scene_id", "???")
        dialogues = scene.get("dialogues")
        if not isinstance(dialogues, list):
            errors.append(f"Сцена {scene_id}: ключ 'dialogues' должен быть списком")
            continue

        for d in dialogues:
            total_dialogues += 1
            context = d.get("context")
            if not context:
                errors.append(f"Сцена {scene_id}: реплика не имеет поля 'context'")
                continue

            if context in found_contexts:
                errors.append(f"Дублирующийся контекст: {context}")
            found_contexts.add(context)

            allow_page_break = bool(d.get("allow_page_break", True))
            text_ru = d.get("text_ru")
            if text_ru is None:
                errors.append(f"{context}: отсутствует поле 'text_ru'")
                continue

            entry_errors = validate_dialogue_text(text_ru, allow_page_break, context)
            errors.extend(entry_errors)

    # Check completeness
    if expected_contexts is not None:
        missing = sorted(expected_contexts - found_contexts)
        extra = sorted(found_contexts - expected_contexts)
        if missing:
            errors.append(f"Отсутствуют реплики ({len(missing)} шт.): {missing[:5]}...")
        if extra:
            errors.append(f"Лишние реплики ({len(extra)} шт.): {extra[:5]}...")
    elif check_total_count and total_dialogues != TOTAL_EXPECTED_ENTRIES:
        errors.append(
            f"Неверное общее количество реплик: {total_dialogues} (ожидалось {TOTAL_EXPECTED_ENTRIES})"
        )

    return len(errors) == 0, errors


def apply_dialogues(json_path: Path, po_path: Path) -> int:
    """Apply translated Russian dialogues from JSON to PO catalog."""
    if not json_path.exists():
        raise FileNotFoundError(f"JSON catalog not found: {json_path}")
    if not po_path.exists():
        raise FileNotFoundError(f"PO catalog not found: {po_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Read original PO to preserve headers, comments, and order
    po_entries = read_po(po_path)
    expected_contexts = {entry.context for entry in po_entries}

    # Validate first against the PO's contexts
    is_valid, errors = validate_catalog(json_path, expected_contexts=expected_contexts)
    if not is_valid:
        print(f"[!] Ошибка валидации {json_path}: найдено {len(errors)} ошибок:", file=sys.stderr)
        for err in errors[:10]:
            print(f"    - {err}", file=sys.stderr)
        if len(errors) > 10:
            print(f"    ... и ещё {len(errors) - 10} ошибок", file=sys.stderr)
        raise ValueError("Cannot apply invalid JSON catalog to PO")

    # Map context -> text_ru
    json_translations: dict[str, str] = {}
    for scene in data.get("scenes", []):
        for d in scene.get("dialogues", []):
            ctx = d.get("context")
            if ctx and "text_ru" in d:
                json_translations[ctx] = d["text_ru"]

    # Verify all PO entries exist in JSON
    missing_in_json = [e.context for e in po_entries if e.context not in json_translations]
    if missing_in_json:
        raise ValueError(
            f"JSON is missing {len(missing_in_json)} entries present in PO: {missing_in_json[:5]}"
        )

    # Update PO entries
    updated_entries: list[PoEntry] = []
    changed_count = 0
    for entry in po_entries:
        new_translation = json_translations[entry.context]
        if new_translation != entry.translation:
            changed_count += 1
        updated_entries.append(
            PoEntry(
                context=entry.context,
                source=entry.source,
                translation=new_translation,
                comments=entry.comments,
            )
        )

    # Write back PO
    write_po(po_path, updated_entries, language="Russian")
    return changed_count

def sync_if_newer(json_path: Path, po_path: Path) -> bool:
    """Check modification times; if JSON is newer than PO, apply changes to PO."""
    if not json_path.exists():
        print(f"[-] {json_path} не существует, синхронизация пропущена.")
        return False

    if not po_path.exists():
        print(f"[*] {po_path} не существует, создание из {json_path}...")
        apply_dialogues(json_path, po_path)
        return True

    json_mtime = json_path.stat().st_mtime
    po_mtime = po_path.stat().st_mtime

    if json_mtime > po_mtime:
        print(
            f"[*] {json_path.name} новее {po_path.name} "
            f"({datetime.fromtimestamp(json_mtime).strftime('%H:%M:%S')} > "
            f"{datetime.fromtimestamp(po_mtime).strftime('%H:%M:%S')}). Накатывание изменений..."
        )
        changed = apply_dialogues(json_path, po_path)
        print(f"[✓] Синхронизировано {po_path.name}: изменено {changed} реплик.")
        return True
    else:
        print(f"[✓] {po_path.name} актуален по отношению к {json_path.name}.")
        return False


def show_status(json_path: Path, po_path: Path) -> None:
    """Display catalog statistics, scene breakdowns, and sync status."""
    print("=" * 65)
    print("   Slayers Royal (PS1) — Каталог сюжетных диалогов: Статус")
    print("=" * 65)

    print(f"PO файл:   {po_path}")
    if po_path.exists():
        po_stat = po_path.stat()
        po_time = datetime.fromtimestamp(po_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"           Размер: {po_stat.st_size:,} байт, mtime: {po_time}")
    else:
        print("           [НЕ НАЙДЕН]")

    print(f"JSON файл: {json_path}")
    if json_path.exists():
        json_stat = json_path.stat()
        json_time = datetime.fromtimestamp(json_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"           Размер: {json_stat.st_size:,} байт, mtime: {json_time}")
    else:
        print("           [НЕ НАЙДЕН]")

    if json_path.exists() and po_path.exists():
        diff = json_path.stat().st_mtime - po_path.stat().st_mtime
        if abs(diff) < 1.0:
            print("Статус:    Синхронизированы (mtime равны)")
        elif diff > 0:
            print(f"Статус:    JSON НОВЕЕ на {diff:.1f} сек (требуется --apply или сборка)")
        else:
            print(f"Статус:    PO новее на {-diff:.1f} сек")

    if not json_path.exists():
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    scenes = data.get("scenes", [])
    total_entries = sum(len(s.get("dialogues", [])) for s in scenes)
    speaker_counts: Counter[str] = Counter()

    for s in scenes:
        for d in s.get("dialogues", []):
            sp = d.get("speaker_ru") or (SPEAKERS_GLOSSARY.get(d.get("speaker")) if d.get("speaker") else "NPC / Выбор")
            speaker_counts[sp] += 1

    print("-" * 65)
    print(f"Всего сцен:    {len(scenes)} (ожидается {TOTAL_EXPECTED_SCENES})")
    print(f"Всего реплик:  {total_entries} (ожидается {TOTAL_EXPECTED_ENTRIES})")
    print("-" * 65)
    print("Распределение реплик по персонажам:")
    for sp, cnt in speaker_counts.most_common():
        pct = (cnt / total_entries * 100) if total_entries else 0
        print(f"  {sp:<20} {cnt:>5} ({pct:>5.1f}%)")

    print("-" * 65)
    print("Сцены игры:")
    print(f"  {'ID':<5} {'Тип':<15} {'Записей':<8} {'Реплик':<8} {'Название'}")
    for s in scenes:
        print(
            f"  {s.get('scene_id', ''):<5} "
            f"{s.get('family', ''):<15} "
            f"{s.get('record_count', 0):<8} "
            f"{s.get('segment_count', 0):<8} "
            f"{s.get('title', '')}"
        )
    print("=" * 65)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Синхронизация и валидация каталога сюжетных диалогов Slayers Royal"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--export",
        action="store_true",
        help="Экспорт dialogue.po в translations/story_dialogues_ru.json",
    )
    group.add_argument(
        "--apply",
        action="store_true",
        help="Накатить изменения из JSON обратно в dialogue.po",
    )
    group.add_argument(
        "--sync-if-newer",
        action="store_true",
        help="Обновить dialogue.po, если JSON был изменён",
    )
    group.add_argument(
        "--validate",
        action="store_true",
        help="Валидация JSON-каталога по всем аппаратным ограничениям PS1",
    )
    group.add_argument(
        "--status",
        action="store_true",
        help="Показать статистику и состояние каталогов",
    )

    parser.add_argument(
        "--po",
        type=Path,
        default=DEFAULT_PO_PATH,
        help=f"Путь к dialogue.po (по умолчанию: {DEFAULT_PO_PATH})",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"Путь к story_dialogues_ru.json (по умолчанию: {DEFAULT_JSON_PATH})",
    )

    args = parser.parse_args()

    po_path = args.po.resolve()
    json_path = args.json.resolve()

    if args.export:
        print(f"[*] Экспорт сюжетных диалогов из {po_path} в {json_path}...")
        data = export_dialogues(po_path, json_path)
        print(
            f"[✓] Экспорт успешно завершён: {data['metadata']['total_entries']} реплик "
            f"в {data['metadata']['total_scenes']} сценах сохранены в {json_path}"
        )

    elif args.apply:
        print(f"[*] Применение переводов из {json_path} в {po_path}...")
        changed = apply_dialogues(json_path, po_path)
        print(f"[✓] Каталог {po_path.name} успешно обновлен! (изменено {changed} реплик)")

    elif args.sync_if_newer:
        sync_if_newer(json_path, po_path)

    elif args.validate:
        print(f"[*] Проверка каталога сюжетных диалогов: {json_path}...")
        is_valid, errors = validate_catalog(json_path)
        if not is_valid:
            print(f"[✗] ОШИБКА: Обнаружено {len(errors)} нарушений правил PS1:", file=sys.stderr)
            for err in errors[:20]:
                print(f"    - {err}", file=sys.stderr)
            if len(errors) > 20:
                print(f"    ... и ещё {len(errors) - 20} ошибок", file=sys.stderr)
            sys.exit(1)
        print("[✓] Все 4 514 реплик в 30 сценах строго соответствуют спецификации PS1!")
        print("    - Unicode NFC нормализация: OK")
        print("    - Длина каждой строки <= 15 символов: OK")
        print("    - Количество строк на страницу от 1 до 3: OK")
        print("    - Запрет пагинации \\f для FF-сегментов: OK")

    elif args.status:
        show_status(json_path, po_path)


if __name__ == "__main__":
    main()
