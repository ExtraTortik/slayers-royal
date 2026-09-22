#!/usr/bin/env python3
"""Combat text extractor, manager, and encoder for Slayers Royal (PS1).

Covers PROG.UNT entry 0x007:
- System menu commands and prompts (0x05F278..0x05F470): START, CONFIG, ATTACK,
  COUNTER, SPELL, MOVE, SLIPPER, LAUGH, HIT BACK, EVADE, FLEE, GUARD, WARD,
  CAST, BACK, MAGIC, AUTO, MANUAL, PICK UNIT, PICK ICON, PICK SPELL, MOVE TO?,
  TARGET?, AREA?, FIGHTING, WAIT., PICK TYPE, SAVE, LOAD, etc.
- Story combat dialogues (0x05F810..0x06286A): 101 speaker dialogue cues.

Generates and validates translations/combat_ru.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from localization.disc import read_extent, RAW_SECTOR_SIZE, USER_DATA_SIZE, USER_DATA_OFFSET
from localization.sr_charmap import build_charmap
from tools.patch_inspection import (
    parse_iso_dir,
    read_sector,
    read_unt_index,
    DEFAULT_CHARMAP,
)
from tools.patch_combat_font import CANONICAL_ASCII_GLYPHS

# The battle overlay renders every 16-bit string of entry 0x007 (UI labels,
# prompts, dialogue cues, save browser) with the battle-resident font 0x142.
# That font mirrors the English Latin cells of the main font and carries the
# Cyrillic block at 0x0150..0x0191 (tools/combat_dialogue_charmap.py).  It has
# nothing to do with the main-font allocation in glyph_map.json.
RUSSIAN_LETTERS = set("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя")


def load_combat_charmap(path: Path | str | None = None) -> dict[str, int]:
    """Return the font-0x142 charmap used for everything written into entry 0x007."""
    if path is not None:
        raise ValueError("combat text uses the fixed font-0x142 charmap; a glyph_map.json override is not applicable")
    from tools.combat_dialogue_charmap import build_combat_dialogue_charmap

    cm = build_combat_dialogue_charmap()
    cm.setdefault(" ", 0x007D)
    for ch in RUSSIAN_LETTERS:
        code = cm.get(ch)
        if code is None:
            raise ValueError(f"Russian letter {ch!r} missing from combat charmap")
        if not (0x0150 <= code <= 0x0191):
            raise ValueError(f"Russian letter {ch!r} has code 0x{code:04X} outside the font-0x142 Cyrillic block 0x0150..0x0191")
    return cm


def build_combat_charmap(path: Path | str | None = None) -> dict[str, int]:
    """Build charmap dictionary mapping characters to 16-bit combat tile codes."""
    return load_combat_charmap(path)


def build_reverse_charmap(charmap: Mapping[str, int] | None = None) -> dict[int, str]:
    """Build reverse charmap mapping 16-bit codes to characters, prioritizing Cyrillic."""
    cm = charmap if charmap is not None else load_combat_charmap()
    rev: dict[int, str] = {}
    for k, v in cm.items():
        if k not in RUSSIAN_LETTERS:
            rev[v] = k
    for k, v in cm.items():
        if k in RUSSIAN_LETTERS:
            rev[v] = k
    return rev
# Entry 0x007 is loaded contiguously at 0x8004E5B0 (verified against the
# original pointer tables: UI table 0x05F470, cue table 0x06286C and the spell
# table 0x06F4D8 all resolve with this base).  The 23 words at 0x05F1FC are
# NOT a string table: under this base they point at 16-byte descriptors at
# 0x05EDD8 and must be left untouched.
RAM_BASE = 0x8004E5B0
PROG_ENTRY_COMBAT = 0x007

JP_CHARMAP = build_charmap()
ASCII_TO_GLYPH = dict(CANONICAL_ASCII_GLYPHS)
GLYPH_TO_ASCII = {v: k for k, v in CANONICAL_ASCII_GLYPHS.items()}

# 16-bit speaker opcodes mapped to character names
SPEAKER_NAMES: dict[int, str] = {
    0x9106: "Лина",
    0x9107: "Лина",
    0x9108: "Лина",
    0x9109: "Лина",
    0x9165: "Зелгадис",
    0x9184: "Амелия",
    0x91C4: "Сильфиль",
    0x91D1: "Лина",
    0xD147: "Гаури",
    0xD163: "Зелгадис",
    0xD16D: "Зелгадис",
    0xD189: "Амелия",
    0xD1A6: "Ларк",
    0xD1B1: "Ларк",
    0xD1E5: "Враг",
    0xD263: "Наёмник",
    0xD26A: "Наёмник",
}

# The 16 speaker opcodes identifying the 101 dialogue cues
SCOUT_SPEAKER_OPCODES = (
    0xD1E5, 0x9184, 0xD26A, 0x91C4, 0xD263, 0x9107, 0xD147, 0x9165,
    0xD189, 0xD1B1, 0x9106, 0xD163, 0x91D1, 0xD16D, 0x9109, 0xD1A6
)

# Canonical 37 System Strings metadata
SYSTEM_STRING_DEFS: list[dict[str, Any]] = [
    {"id": "START", "offset": 0x05F278, "en_offset": 0x05F278, "jp": "戦態開始", "en": "START", "ru": "СТАРТ"},
    {"id": "CONFIG", "offset": 0x05F284, "en_offset": 0x05F284, "jp": "コンフィグ", "en": "CONFIG", "ru": "НАСТРОЙКИ"},
    {"id": "ATTACK_SET", "offset": 0x05F290, "en_offset": 0x05F292, "jp": "攻撃設定", "en": "ATTACK", "ru": "АТАКА"},
    {"id": "COUNTER_SET", "offset": 0x05F29C, "en_offset": 0x05F2A0, "jp": "反撃設定", "en": "COUNTER", "ru": "КОНТРАТАКА"},
    {"id": "SPELL_SET", "offset": 0x05F2A8, "en_offset": 0x05F2B0, "jp": "呪文設定", "en": "SPELL", "ru": "МАГИЯ"},
    {"id": "ATTACK_ACT", "offset": 0x05F2B4, "en_offset": 0x05F2BC, "jp": "こうげきする", "en": "ATTACK", "ru": "АТАКОВАТЬ"},
    {"id": "HIT", "offset": 0x05F2C4, "en_offset": 0x05F2CA, "jp": "なぐる", "en": "HIT", "ru": "УДАРИТЬ"},
    {"id": "RAM", "offset": 0x05F2CC, "en_offset": 0x05F2D2, "jp": "たいあたり", "en": "RAM", "ru": "ТАРАН"},
    {"id": "MOVE", "offset": 0x05F2D8, "en_offset": 0x05F2DA, "jp": "いどう", "en": "MOVE", "ru": "ДВИЖЕНИЕ"},
    {"id": "SLIPPER", "offset": 0x05F2E0, "en_offset": 0x05F2E4, "jp": "スリッパ", "en": "SLIPPER", "ru": "ТАПОК"},
    {"id": "LAUGH", "offset": 0x05F2EC, "en_offset": 0x05F2F4, "jp": "高笑い", "en": "LAUGH", "ru": "ХОХОТ"},
    {"id": "COUNTER_ACT", "offset": 0x05F2F4, "en_offset": 0x05F300, "jp": "やりかえす", "en": "COUNTER", "ru": "ОТВЕТИТЬ"},
    {"id": "HIT_BACK", "offset": 0x05F300, "en_offset": 0x05F310, "jp": "なぐりかえす", "en": "HIT BACK", "ru": "ОТВЕТНЫЙ УДАР"},
    {"id": "EVADE", "offset": 0x05F310, "en_offset": 0x05F322, "jp": "よける", "en": "EVADE", "ru": "УКЛОНЕНИЕ"},
    {"id": "FLEE", "offset": 0x05F318, "en_offset": 0x05F32E, "jp": "にげる", "en": "FLEE", "ru": "ПОБЕГ"},
    {"id": "ENDURE", "offset": 0x05F320, "en_offset": 0x05F338, "jp": "がまんする", "en": "ENDURE", "ru": "ТЕРПЕТЬ"},
    {"id": "GUARD", "offset": 0x05F32C, "en_offset": 0x05F346, "jp": "ぼうぎょ", "en": "GUARD", "ru": "ЗАЩИТА"},
    {"id": "WARD", "offset": 0x05F338, "en_offset": 0x05F352, "jp": "バリア", "en": "WARD", "ru": "БАРЬЕР"},
    {"id": "CAST", "offset": 0x05F340, "en_offset": 0x05F35C, "jp": "となえる", "en": "CAST", "ru": "ПРИМЕНИТЬ"},
    {"id": "BACK", "offset": 0x05F34C, "en_offset": 0x05F366, "jp": "やめる", "en": "BACK", "ru": "НАЗАД"},
    {"id": "MAGIC", "offset": 0x05F354, "en_offset": 0x05F370, "jp": "まほう", "en": "MAGIC", "ru": "ЗАКЛИНАНИЕ"},
    {"id": "AUTO", "offset": 0x05F35C, "en_offset": 0x05F37C, "jp": "自動設定", "en": "AUTO", "ru": "АВТО"},
    {"id": "TYPE_ATTACK", "offset": 0x05F368, "en_offset": 0x05F386, "jp": "こうげき型", "en": "ATTACK", "ru": "АТАКУЮЩИЙ"},
    {"id": "TYPE_DEFEND", "offset": 0x05F374, "en_offset": 0x05F394, "jp": "ぼうぎょ型", "en": "DEFEND", "ru": "ЗАЩИТНЫЙ"},
    {"id": "TYPE_AUTO", "offset": 0x05F380, "en_offset": 0x05F3A2, "jp": "おまかせ型", "en": "AUTO", "ru": "СБАЛАНС."},
    {"id": "MANUAL", "offset": 0x05F38C, "en_offset": 0x05F3AC, "jp": "自分で操作", "en": "MANUAL", "ru": "ВРУЧНУЮ"},
    {"id": "PICK_UNIT", "offset": 0x05F398, "en_offset": 0x05F3BA, "jp": "ユニットをえらんでね.", "en": "PICK UNIT", "ru": "ВЫБЕРИТЕ ЮНИТ"},
    {"id": "PICK_ICON", "offset": 0x05F3B0, "en_offset": 0x05F3CE, "jp": "アイコンをえらんでね.", "en": "PICK ICON", "ru": "ВЫБЕРИТЕ ИКОНКУ"},
    {"id": "PICK_SPELL", "offset": 0x05F3C8, "en_offset": 0x05F3E2, "jp": "呪文をえらんでね.", "en": "PICK SPELL", "ru": "ВЫБЕРИТЕ ЗАКЛИНАНИЕ"},
    {"id": "MOVE_TO", "offset": 0x05F3DC, "en_offset": 0x05F3F8, "jp": "どこにいどうする?", "en": "MOVE TO?", "ru": "КУДА ИДТИ?"},
    {"id": "TARGET", "offset": 0x05F3F0, "en_offset": 0x05F40A, "jp": "だれをこうげきする?", "en": "TARGET?", "ru": "КОГО АТАКОВАТЬ?"},
    {"id": "AREA", "offset": 0x05F408, "en_offset": 0x05F41A, "jp": "どこにこうげきする?", "en": "AREA?", "ru": "КУДА АТАКОВАТЬ?"},
    {"id": "FIGHTING", "offset": 0x05F420, "en_offset": 0x05F426, "jp": "ただいま戦闘中!", "en": "FIGHTING", "ru": "ИДЕТ БОЙ!"},
    {"id": "WAIT", "offset": 0x05F434, "en_offset": 0x05F438, "jp": "ちょっとまってね.", "en": "WAIT.", "ru": "ПОДОЖДИТЕ."},
    {"id": "PICK_TYPE", "offset": 0x05F448, "en_offset": 0x05F444, "jp": "タイプをえらんでね.", "en": "PICK TYPE", "ru": "ВЫБЕРИТЕ ТИП"},
    {"id": "SAVE", "offset": 0x05F460, "en_offset": 0x05F458, "jp": "セ-ブ", "en": "SAVE", "ru": "СОХРАНИТЬ"},
    {"id": "LOAD", "offset": 0x05F468, "en_offset": 0x05F462, "jp": "ロ-ド", "en": "LOAD", "ru": "ЗАГРУЗИТЬ"},
]

# Additional combat mode strings (actions, memory card, calibration, save/load)
EXTRA_COMBAT_STRING_DEFS: list[dict[str, Any]] = [
    # 0x00154C - Memory Card Commands & Status
    {"id": "CARD_CHECK", "offset": 0x00154C, "max_bytes": 18, "jp": "メモリ-カ-ドを", "en": "MEM CARD", "ru": "КАРТА"},
    {"id": "CARD_READING", "offset": 0x001560, "max_bytes": 16, "jp": "チェック中です", "en": "READING", "ru": "ЧТЕНИЕ"},
    # 0x0015E0 - Format and Save Results
    {"id": "FORMAT_OK", "offset": 0x0015E0, "max_bytes": 22, "jp": "初期化が終わりました", "en": "FORMAT OK", "ru": "ФОРМАТ OK"},
    {"id": "CARD_FORMAT", "offset": 0x0015F8, "max_bytes": 26, "jp": "メモリ-カ-ドの初期化に", "en": "CARD FORMAT", "ru": "ФОРМАТ КАРТЫ"},
    {"id": "OP_FAILED", "offset": 0x001614, "max_bytes": 14, "jp": "失敗しました", "en": "FAILED", "ru": "ОШИБКА"},
    {"id": "SAVE_FAILED", "offset": 0x001624, "max_bytes": 22, "jp": "セ-ブに失敗しました", "en": "SAVE FAIL", "ru": "СБОЙ СЕЙВА"},
    # 0x0634C8 - Controller Stick & Vibration Settings
    {"id": "STICK_CALIB", "offset": 0x0634C8, "max_bytes": 88, "jp": "0位置正スティックから手を放して", "en": "CENTER STICK\nLET GO OF STICK\nPRESS O TO SET", "ru": "ЦЕНТР СТИКА\nОТПУСТИТЕ СТИК\nНАЖМИТЕ O"},
    {"id": "VIB_OFF", "offset": 0x063522, "max_bytes": 68, "jp": "バイブレ-ションオフ", "en": "VIBRATION OFF", "ru": "ВИБРАЦИЯ\nВИБРАЦИЯ ВЫКЛ"},
    {"id": "VIB_ON", "offset": 0x063566, "max_bytes": 68, "jp": "バイブレ-ションオン", "en": "VIBRATION ON", "ru": "ВИБРАЦИЯ\nВИБРАЦИЯ ВКЛ"},
    # 0x0635EC - Screen Header Titles
    {"id": "TITLE_MAP", "offset": 0x0635EC, "max_bytes": 10, "jp": "場所画面", "en": "MAP", "ru": "ЗОНА"},
    {"id": "TITLE_BTL", "offset": 0x0635F8, "max_bytes": 10, "jp": "戦闘画面", "en": "BTL", "ru": "БОЙ"},
    {"id": "TITLE_SYS", "offset": 0x063604, "max_bytes": 10, "jp": "システム", "en": "SYS", "ru": "СИС"},
    {"id": "TITLE_VIB", "offset": 0x063610, "max_bytes": 10, "jp": "振動", "en": "VIBE", "ru": "ВИБР"},
    # 0x0713C4 - Save / Load UI and Confirmation Strings
    {"id": "SAVE_PROMPT", "offset": 0x0713C4, "max_bytes": 8, "jp": "セ-ブ", "en": "SAVE", "ru": "СОХ"},
    {"id": "LOAD_PROMPT", "offset": 0x0713CC, "max_bytes": 8, "jp": "ロ-ド", "en": "LOAD", "ru": "ЗАГ"},
    {"id": "INVALID", "offset": 0x0713D4, "max_bytes": 16, "jp": "使用できません", "en": "INVALID", "ru": "НЕЛЬЗЯ"},
    {"id": "NO_DATA", "offset": 0x0713E4, "max_bytes": 20, "jp": "デ-タがありません", "en": "NO DATA", "ru": "НЕТ ФАЙЛА"},
    {"id": "MEM_CARD_LOC", "offset": 0x0713F8, "max_bytes": 18, "jp": "メモリ-カ-ドが", "en": "MEM CARD", "ru": "КАРТА"},
    {"id": "MISSING", "offset": 0x07140C, "max_bytes": 18, "jp": "認識されていません", "en": "MISSING", "ru": "НЕ ВИДНО"},
    {"id": "NOT_READY", "offset": 0x071420, "max_bytes": 22, "jp": "初期化されていません", "en": "NOT READY", "ru": "НЕ ГОТОВО"},
    {"id": "FORMAT_QUERY", "offset": 0x071438, "max_bytes": 18, "jp": "初期化しますか?", "en": "FORMAT?", "ru": "ФОРМАТ?"},
    {"id": "BTL_MID", "offset": 0x07144C, "max_bytes": 8, "jp": "戦闘中", "en": "BTL", "ru": "БОЙ"},
    {"id": "THIS_DATA", "offset": 0x071454, "max_bytes": 14, "jp": "このデ-タは", "en": "DATA", "ru": "ДАННЫЕ"},
    {"id": "CORRUPT", "offset": 0x071464, "max_bytes": 26, "jp": "正しく読む事が出来ません", "en": "CORRUPT", "ru": "ПОВРЕЖДЕНЫ"},
    {"id": "FREE_BLOCKS", "offset": 0x071480, "max_bytes": 16, "jp": "空きブロックが", "en": "FREE", "ru": "МЕСТА"},
    {"id": "TOO_FEW", "offset": 0x071490, "max_bytes": 16, "jp": "不足しています", "en": "TOO FEW", "ru": "МАЛО"},
    {"id": "BAD", "offset": 0x0714A0, "max_bytes": 10, "jp": "不良です", "en": "BAD", "ru": "СБОЙ"},
    # 0x071744 - In-Progress Prompts & Warning
    {"id": "SAVING", "offset": 0x071744, "max_bytes": 14, "jp": "セ-ブ中です", "en": "SAVING", "ru": "ЗАПИСЬ"},
    {"id": "KEEP_IN", "offset": 0x071754, "max_bytes": 18, "jp": "抜かないで下さい", "en": "KEEP IN", "ru": "ЖДИТЕ..."},
    {"id": "FORMATTING", "offset": 0x071768, "max_bytes": 14, "jp": "初期化中です", "en": "FORMAT", "ru": "ФОРМАТ"},
    {"id": "KEEP_IN2", "offset": 0x071778, "max_bytes": 20, "jp": "抜かないで下さい", "en": "KEEP IN", "ru": "ЖДИТЕ..."},
    # 0x0717A0 - Access Failure
    {"id": "ACCESS_FAIL", "offset": 0x0717A0, "max_bytes": 26, "jp": "アクセスに失敗しました", "en": "ACCESS FAIL", "ru": "СБОЙ ДОСТУПА"},
]

# Digraph / ligature decoder for English patch (gourry-hacks)
GOURRY_DIGRAPHS: dict[int, str] = {
    0x026F: "in", 0x0353: "st", 0x03B7: "er", 0x03C8: "em", 0x02E8: "on",
    0x02E9: " a", 0x0371: "ord", 0x036A: " w", 0x0377: "on't", 0x033F: "o ",
    0x036E: " ", 0x02E6: "ou", 0x035D: " m", 0x0364: "ll", 0x035B: " w",
    0x030D: "er", 0x03BA: "ng", 0x0374: "m", 0x0252: "co", 0x0337: "e",
    0x033E: "Wh", 0x0367: "a", 0x02B9: " it", 0x02C9: "er", 0x03C5: "ha",
    0x0304: "ve", 0x02B8: "e ", 0x0366: "th", 0x035A: "or", 0x0302: "ar",
    0x0338: "ed", 0x033A: "th", 0x033B: "qu", 0x033C: "ly", 0x033D: "wh",
    0x034F: "ar", 0x031B: "'", 0x0209: "Z",
}

# Canonical Russian translations for all 101 dialogue cues
DIALOGUE_RU_TRANSLATIONS: list[str] = [
    "Нага! Учти, город совсем рядом! Никаких мощных заклинаний!",
    "Гаури! Твой меч бесполезен против лессер демона!",
    "Как-нибудь прорвёмся!",
    "Нага, надеюсь, ты понимаешь — мы внутри дома!",
    "Нага! Ни в коем случае не задевай эту эльфийку!",
    "Чёрт, эльфийская девчонка доставляет столько хлопот!",
    "Ринея... Что вы сделали с Ринеей?!",
    "Да почём мне знать? Меня интересуют только фигуристые красотки.",
    "Наконец-то мой выход! Вперёд!",
    "Гаури, кажется, он мазоку!",
    "Знаю я!",
    "Их цель — ожерелье Ларка?",
    "Наш противник всё-таки мазоку! Он весьма силён!",
    "Не беспокойся!",
    "Я всё понял!",
    "Куда подевался этот Зодд?",
    "Верните Ринею! Немедленно верните Ринею!",
    "Ч-что?! Неужели вы... л-лоликонщики?!",
    "Заткнитесь!",
    "Неужели вы думали, что победите нас в черте города?",
    "Пора с этим покончить!",
    "До чего же вы надоедливые!",
    "Да откуда они вообще все вылезли?!",
    "Пора поставить точку в этом деле!",
    "Э-это ложь! Ринея ни за что не станет помогать мазоку!",
    "Слишком много мелких сошек.",
    "Не надейтесь выбраться отсюда живыми!",
    "Само собой, именно так!",
    "Нага, я особо не надеюсь, но подлечи нас, ладно?",
    "Ничего, если отключишься, я тебя тапком мигом разбужу!",
    "Дион, вот уж кого я ни за что не прощу — так это тебя!",
    "Жалкая эльфийка посмела мне перечить? Не смеши меня!",
    "Ради себя, ради Ринеи... я ни за что не сдамся!",
    "Хватит болтать! Если есть время молоть языком, лучше прочитайте заклинание!",
    "Ларк, ты ещё жив?",
    "У меня сегодня отличное настроение. Убью вас как можно быстрее и без мучений!",
    "Это последний бой! Все вперёд!",
    "Ага, положись на меня!",
    "Вперёд!",
    "Конечно!",
    "Да!",
    "Госпожа Лина! Драгу Слейв здесь не сработает!",
    "Всё в порядке, прорвёмся!",
    "Глупцы, какие же вы глупцы. Пытаться противиться тому, кого невозможно победить.",
    "Ха! Смешно! Если в сердце живёт справедливость, зло никогда не победит! Последними стоять на ногах будем мы!",
    "Увы, но я терпеть не могу сдаваться, даже не попробовав!",
    "А я просто не умею сдаваться.",
    "Ради себя, ради Ринеи... я не отступлю!",
    "Жалкая девчонка смеет со мной драться?!",
    "Как же вы меня достали!",
    "С Ринеей ведь всё в порядке?!",
    "Лессер демон?!",
    "Нет, это не он.",
    "Разговоры потом, сначала разберёмся с ними!",
    "Это просто призраки, Гаури. Твой меч с ними справится!",
    "Обычная магия здесь не подействует.",
    "Гаури, Ларк, прорываемся!",
    "Положись на меня!",
    "Не теряйте бдительности.",
    "Их слишком много.",
    "Не реви! Это же просто призраки! Ты вообще-то жрица или кто?!",
    "Ларк, не дай себя окружить!",
    "Ларк, ты в порядке?",
    "Подумать только, призвать столько лессер демонов...",
    "Кто-нибудь может догнать Галева?!",
    "Их слишком много, не пробиться!",
    "Чёрт, ничего не поделаешь!",
    "Хм, а этот старик не так прост!",
    "Его наверняка нанял Галев.",
    "Судя по всему, он маг.",
    "Слабые заклинания им нипочём!",
    "Чёрт, в доме особо не разгуляешься с мощной магией!",
    "Проклятье, опять ожившие доспехи?!",
    "Придётся уничтожать их по одному, наверняка.",
    "Всё лучше, чем драться в тесном доме.",
    "Сначала разберитесь с тем странным типом среди доспехов!",
    "Решил сбежать?!",
    "С ними покончено!",
    "Если Шабранигдо будет призван... Пожалуйста, поторопитесь!",
    "Я знаю!",
    "Быстрее! Времени совсем не осталось!",
    "Мельтешат и мельтешат... До чего же назойливые твари!",
    "Они слишком быстро двигаются!",
    "Они палят Огненными Стрелами отовсюду!",
    "Они вообще соображают, что творят?!",
    "Госпожа Лина, прошу вас, быстрее!",
    "Я знаю, но этой мелочи вокруг слишком много!",
    "Похоже, ритуал призыва сорван, так что не переживайте!",
    "Госпожа Нага, как вы можете так дразнить мазоку?!",
    "Думаете, задавите нас числом?! Не выйдет!",
    "Держитесь!",
    "Тьфу! Если бы ты пошла с нами, эти типы не совали бы свой нос куда не просят!",
    "Заткнись! С какой стати мне идти с вами?!",
    "Ой-ой, как страшно! Посмотрим, надолго ли хватит твоей спеси!",
    "Мазоку?!",
    "Нет, похоже, кто-то другой!",
    "Ну, по крайней мере, спасибо скажу.",
    "Осторожно, они прячутся за колоннами!",
    "Атаки призраков бьют прямо по разуму, будьте начеку!",
    "Амелия, ну вот почему перед тем, как явиться, ты не смела парочку врагов?!",
    "Минус второй!",
]


def extract_prog_007(source_bin: Path) -> bytes:
    """Read PROG.UNT entry 0x007 from a disc image or UNT file."""
    if source_bin.stat().st_size > 100 * 1024 * 1024:
        pvd = read_sector(source_bin, 16)
        root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
        root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
        root_dir = parse_iso_dir(source_bin, root_lba, root_size)
        if "PROG.UNT" not in root_dir:
            raise ValueError("PROG.UNT not found in ISO directory")
        prog_lba, _ = root_dir["PROG.UNT"]
        sector0 = read_extent(source_bin, prog_lba, 2048)
        entries = read_unt_index(sector0)
        e = entries[PROG_ENTRY_COMBAT]
        return read_extent(source_bin, prog_lba + e.start_sector, e.size)
    elif source_bin.name.upper().endswith(".UNT"):
        data = source_bin.read_bytes()
        entries = read_unt_index(data[:2048])
        e = entries[PROG_ENTRY_COMBAT]
        start = e.start_sector * 2048
        return data[start : start + e.size]
    else:
        return source_bin.read_bytes()


def decode_16le_string(data: bytes, offset: int, stop_at_page: bool = True) -> list[int]:
    """Read sequence of 16-bit little endian words until delimiter."""
    words = []
    curr = offset
    while curr + 2 <= len(data):
        w = struct.unpack_from("<H", data, curr)[0]
        words.append(w)
        curr += 2
        if w == 0x00FF or (stop_at_page and w == 0x00FD):
            break
    return words


def format_jp_text(words: list[int]) -> str:
    """Format Japanese words using JP_CHARMAP."""
    parts = []
    for w in words:
        if (w & 0xF000) in (0x9000, 0xD000):
            continue
        elif w == 0x00FE:
            parts.append("\n")
        elif w in (0x00FD, 0x00FF):
            continue
        else:
            parts.append(JP_CHARMAP.get(w, f"[{w:04X}]"))
    return "".join(parts).strip()


def format_en_text(words: list[int]) -> str:
    """Format English words using GOURRY_DIGRAPHS and ASCII table."""
    parts = []
    for w in words:
        if (w & 0xF000) in (0x9000, 0xD000):
            continue
        elif w == 0x00FE:
            parts.append("\n")
        elif w in (0x00FD, 0x00FF):
            continue
        elif w in GOURRY_DIGRAPHS:
            parts.append(GOURRY_DIGRAPHS[w])
        elif w in GLYPH_TO_ASCII:
            parts.append(GLYPH_TO_ASCII[w])
        elif w in JP_CHARMAP:
            parts.append(JP_CHARMAP[w])
        else:
            parts.append(f"[{w:04X}]")
    return "".join(parts).strip()

def format_ru_text(words: list[int], reverse_charmap: Mapping[int, str] | None = None) -> str:
    """Format Russian words using reverse combat charmap."""
    rev = reverse_charmap if reverse_charmap is not None else build_reverse_charmap()
    parts = []
    for w in words:
        if (w & 0xF000) in (0x9000, 0xD000):
            continue
        elif w == 0x00FE:
            parts.append("\n")
        elif w == 0x00FD:
            parts.append("\f")
        elif w == 0x00FF:
            continue
        elif w in rev:
            parts.append(rev[w])
        else:
            parts.append(f"[{w:04X}]")
    return "".join(parts).strip()


def encode_combat_string(text: str, charmap: Mapping[str, int] | None = None) -> bytes:
    """Encode a text string into 16-bit little endian words with 0x00FF terminator.

    Control codes:
        0x00FD: speaker change / page continuation ('\\f' or '<00FD>')
        0x00FE: newline ('\\n')
        0x00FF: string terminator (automatically appended)

    Russian letters must come from the font-0x142 Cyrillic block (0x0150..0x0191).
    """
    cm = charmap if charmap is not None else load_combat_charmap()
    output = bytearray()
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "<" and i + 5 < n and text[i + 5] == ">":
            hex_part = text[i + 1 : i + 5]
            try:
                val = int(hex_part, 16)
                output.extend(val.to_bytes(2, "little"))
                i += 6
                continue
            except ValueError:
                pass

        ch = text[i]
        if ch == "\n":
            output.extend(b"\xFE\x00")
        elif ch == "\f":
            output.extend(b"\xFD\x00")
        elif ch in cm:
            code = cm[ch]
            if ch in RUSSIAN_LETTERS and not (0x0150 <= code <= 0x0191):
                raise ValueError(
                    f"Russian character {ch!r} code 0x{code:04X} is outside the font-0x142 Cyrillic block "
                    "0x0150..0x0191 (battle text must use tools/combat_dialogue_charmap.py)"
                )
            output.extend(code.to_bytes(2, "little"))
        else:
            raise ValueError(f"Character {ch!r} (U+{ord(ch):04X}) not in combat charmap")
        i += 1

    output.extend(b"\xFF\x00")
    return bytes(output)


def encode_text(text: str, charmap: Mapping[str, int] | None = None) -> bytes:
    """Encode a text string into 16-bit little endian words with 0x00FF terminator."""
    return encode_combat_string(text, charmap)

def extract_all_combat_data(prog_jp: bytes, prog_en: bytes) -> dict[str, Any]:
    """Extract complete structured dataset of combat strings."""
    # 1. System strings
    system_strings = []
    for s_def in SYSTEM_STRING_DEFS:
        off = s_def["offset"]
        en_off = s_def["en_offset"]
        w_jp = decode_16le_string(prog_jp, off, stop_at_page=False)
        w_en = decode_16le_string(prog_en, en_off, stop_at_page=False)

        system_strings.append({
            "id": s_def["id"],
            "offset": f"0x{off:06X}",
            "en_offset": f"0x{en_off:06X}",
            "ram_address": f"0x{RAM_BASE + off:08X}",
            "text_jp": s_def["jp"],
            "text_en": s_def["en"],
            "text_ru": s_def["ru"],
        })

    # 2. Dialogue cues (101 cues)
    dialogue_cues = []
    pos = 0x05F810
    raw_cues = []
    while pos < 0x06286A:
        w = struct.unpack_from("<H", prog_jp, pos)[0]
        if w in SCOUT_SPEAKER_OPCODES:
            raw_cues.append((pos, w))
        pos += 2

    if len(raw_cues) != 101:
        raise ValueError(f"Expected 101 dialogue cues, found {len(raw_cues)}")

    for idx, (off, spk) in enumerate(raw_cues):
        next_off = raw_cues[idx + 1][0] if idx + 1 < len(raw_cues) else 0x06286A
        w_jp = decode_16le_string(prog_jp, off + 2, stop_at_page=True)
        w_en = decode_16le_string(prog_en, off + 2, stop_at_page=True)

        jp_text = format_jp_text(w_jp)
        en_text = format_en_text(w_en)
        ru_text = DIALOGUE_RU_TRANSLATIONS[idx]

        dialogue_cues.append({
            "id": f"combat_dlg_{idx+1:03d}",
            "index": idx + 1,
            "offset": f"0x{off:06X}",
            "ram_address": f"0x{RAM_BASE + off:08X}",
            "speaker_opcode": f"0x{spk:04X}",
            "speaker": SPEAKER_NAMES.get(spk, f"0x{spk:04X}"),
            "text_jp": jp_text,
            "text_en": en_text,
            "text_ru": ru_text,
        })
    # 3. Extra Combat Strings
    extra_combat_strings = []
    for es in EXTRA_COMBAT_STRING_DEFS:
        off = es["offset"]
        extra_combat_strings.append({
            "id": es["id"],
            "offset": f"0x{off:06X}",
            "max_bytes": es["max_bytes"],
            "text_jp": es["jp"],
            "text_en": es["en"],
            "text_ru": es["ru"],
        })

    charmap = build_combat_charmap()
    charmap_hex = {k: f"0x{v:04X}" for k, v in sorted(charmap.items(), key=lambda x: x[1])}

    return {
        "metadata": {
            "title": "Slayers Royal (PS1) - Combat Mode Localization Catalog",
            "source_archive": "PROG.UNT",
            "entry_index": "0x007",
            "combat_font_entry": "0x142",
            "ram_base": f"0x{RAM_BASE:08X}",
            "system_strings_count": len(system_strings),
            "dialogues_count": len(dialogue_cues),
            "extra_combat_strings_count": len(extra_combat_strings),
        },
        "system_strings": system_strings,
        "extra_combat_strings": extra_combat_strings,
        "dialogues": dialogue_cues,
        "charmap": charmap_hex,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract and verify Slayers Royal combat text.")
    parser.add_argument("--bin-jp", type=Path, default=REPO_ROOT / "downloads" / "sr.bin", help="Path to Japanese disc image")
    parser.add_argument("--bin-ru", type=Path, default=REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin", help="Path to patched disc image")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "translations" / "combat_ru.json", help="Path to output JSON")
    parser.add_argument("--verify", action="store_true", help="Verify extracted catalog integrity")

    args = parser.parse_args()

    if not args.bin_jp.is_file():
        print(f"Error: Japanese source BIN not found at {args.bin_jp}", file=sys.stderr)
        return 1
    if not args.bin_ru.is_file():
        print(f"Error: Patched source BIN not found at {args.bin_ru}", file=sys.stderr)
        return 1

    if args.verify and args.output.is_file():
        print(f"Loading combat catalog from {args.output} for verification...")
        catalog = json.loads(args.output.read_text(encoding="utf-8"))
    else:
        print(f"Extracting combat text from {args.bin_jp.name} and {args.bin_ru.name}...")
        prog_jp = extract_prog_007(args.bin_jp)
        prog_ru = extract_prog_007(args.bin_ru)

        catalog = extract_all_combat_data(prog_jp, prog_ru)

        print(f"Extracted {len(catalog['system_strings'])} system strings.")
        print(f"Extracted {len(catalog['dialogues'])} combat dialogue cues.")

        # Save to JSON
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved combat catalog to {args.output} ({args.output.stat().st_size:,} bytes)")
    if args.verify:
        print("Verifying catalog integrity...")
        assert len(catalog["system_strings"]) >= 35, "Missing system strings!"
        assert len(catalog["dialogues"]) == 101, "Expected exactly 101 dialogue cues!"

        # Verify key strings
        pick_unit = next(s for s in catalog["system_strings"] if s["id"] == "PICK_UNIT")
        assert pick_unit["text_en"] == "PICK UNIT"
        assert pick_unit["offset"] == "0x05F398"

        start_cmd = next(s for s in catalog["system_strings"] if s["id"] == "START")
        assert start_cmd["text_en"] == "START"
        assert start_cmd["offset"] == "0x05F278"

        dlg_92 = next(d for d in catalog["dialogues"] if d["offset"] == "0x06241C")
        assert "interfeer" in dlg_92["text_en"] or "interfer" in dlg_92["text_en"]
        assert dlg_92["speaker"] == "Наёмник"

        # Verify charmap encoding on all Russian translations
        cm = build_combat_charmap()
        for s in catalog["system_strings"]:
            enc = encode_combat_string(s["text_ru"], cm)
            assert enc.endswith(b"\xFF\x00")

        for d in catalog["dialogues"]:
            enc = encode_combat_string(d["text_ru"], cm)
            assert enc.endswith(b"\xFF\x00")

        print("Verification PASSED: All 37 system strings and 101 dialogues encoded cleanly with charmap!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
