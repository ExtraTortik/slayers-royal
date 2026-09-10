#!/usr/bin/env python3
"""Build and validate all 114 combat dialogue blocks for translations/combat_dialogues_ru.json."""

from __future__ import annotations
import json
from pathlib import Path
import struct
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from tools.combat_dialogue_charmap import build_combat_dialogue_charmap
from tools.patch_combat_dialogues import encode_conversation_block

CHARMAP = build_combat_dialogue_charmap()
OUTPUT_PATH = REPO_ROOT / "translations" / "combat_dialogues_ru.json"
RAM_BASE = 0x8004E110

def wrap_bubble_text(text: str, max_chars: int = 21, max_lines: int = 3) -> str:
    """Ensure dialogue bubble lines obey character length and height limits."""
    lines = [l.strip() for l in text.split("\n")]
    if len(lines) <= max_lines and all(len(l) <= max_chars for l in lines):
        return "\n".join(lines)
    
    words = text.replace("\n", " ").split()
    wrapped_lines: list[str] = []
    curr_line = ""
    for w in words:
        if not curr_line:
            curr_line = w
        elif len(curr_line) + 1 + len(w) <= max_chars:
            curr_line += " " + w
        else:
            wrapped_lines.append(curr_line)
            curr_line = w
    if curr_line:
        wrapped_lines.append(curr_line)
    
    if len(wrapped_lines) > max_lines:
        raise ValueError(f"Text cannot fit in {max_lines} lines: {wrapped_lines}")
    
    return "\n".join(wrapped_lines)


BLOCK_TRANSLATIONS: dict[int, list[str]] = {
    # Block 1 (0x05F810, budget 176B, 3 bubbles)
    0: [
        "Нага! Город рядом!\nБез мощной магии!",
        "О-хо-хо-хо!\nЯ всё знаю!",
        "Врёшь!\nГлаза бегают!"
    ],
    # Block 2 (0x05F8C0, budget 96B, 2 bubbles)
    1: [
        "Твой меч не ранит\nлессер-демона!",
        "Прорвёмся!"
    ],
    # Block 3 (0x05F920, budget 100B, 2 bubbles)
    2: [
        "Нага! Мы в доме!",
        "Этой мелочи магия\nне нужна!"
    ],
    # Block 4 (0x05F984, budget 80B, 1 bubble)
    3: [
        "О-хо-хо! Вызов мне\n— ваш конец!"
    ],
    # Block 5 (0x05F9D4, budget 248B, 5 bubbles)
    4: [
        "Гаури, будь моим\nщитом!♥",
        "С ума сошла?!",
        "Нага, не задень\nту эльфийку!",
        "За кого ты меня\nпринимаешь?!",
        "За пешку!♪"
    ],
    # Block 6 (0x05FACC, budget 132B, 2 bubbles)
    5: [
        "Тут можно бить\nмагией в полную\nсилу!",
        "Лина, не кипятись\nты так!"
    ],
    # Block 7 (0x05FB50, budget 200B, 5 bubbles)
    6: [
        "Тьфу, эта девка\nдопекла!",
        "Где Ринея?!",
        "Мне важны лишь\nкрасотки.",
        "Повезло тебе, Лина.",
        "В смысле?!"
    ],
    # Block 8 (0x05FC18, budget 36B, 1 bubble)
    7: [
        "Я пошёл! В бой!"
    ],
    # Block 9 (0x05FC3C, budget 52B, 2 bubbles)
    8: [
        "Ты кто?",
        "Я — Зодд."
    ],
    # Block 10 (0x05FC70, budget 56B, 2 bubbles)
    9: [
        "Он мазоку!",
        "Я знаю!"
    ],
    # Block 11 (0x05FCA8, budget 60B, 2 bubbles)
    10: [
        "Цель — амулет?",
        "Сам знаешь."
    ],
    # Block 12 (0x05FCE4, budget 96B, 3 bubbles)
    11: [
        "Он силён, будьте\nначеку!",
        "Не бойся!",
        "Я готов!"
    ],
    # Block 13 (0x05FD44, budget 120B, 2 bubbles)
    12: [
        "Для мазоку ты\nслабоват, дядя!",
        "Победи сначала,\nнаглец!"
    ],
    # Block 14 (0x05FDBC, budget 336B, 6 bubbles)
    13: [
        "Где этот Зодд?",
        "Хочешь сделки?",
        "Всё равно бить,\nк чему ждать его?",
        "Какая спесь.",
        "Он ждёт за горой\nна севере.",
        "Но живыми вам отсюда\nне уйти!"
    ],
    # Block 15 (0x05FF0C, budget 356B, 8 bubbles)
    14: [
        "Верните Ринею!",
        "Она пока жива.",
        "Хоть и как игрушка.",
        "Вы что, лоликонщики?!",
        "Сдурел совсем?",
        "Заткнись!",
        "Она подопытная!",
        "Она знает тайну\nЛезариама."
    ],
    # Block 16 (0x060070, budget 124B, 2 bubbles)
    15: [
        "Думал победить\nв городе?",
        "Мне нужно лишь\nпорвать девчонку!"
    ],
    # Block 17 (0x0600EC, budget 132B, 2 bubbles)
    16: [
        "Мне нужна только\nЛина Инверс!",
        "Сперва пройди через\nменя!"
    ],
    # Block 18 (0x060170, budget 204B, 4 bubbles)
    17: [
        "Раньше я дрался не\nв полную силу.",
        "Самоуверенно.",
        "Фогг боится девчонки?",
        "Фогг — последний?"
    ],
    # Block 19 (0x06023C, budget 64B, 2 bubbles)
    18: [
        "Покончим с этим!",
        "Согласен."
    ],
    # Block 20 (0x06027C, budget 96B, 2 bubbles)
    19: [
        "Сразись со мной!",
        "Жаль, что вы лишь\nлюдишки!"
    ],
    # Block 21 (0x0602DC, budget 52B, 1 bubble)
    20: [
        "Барьер прямо в\nСейруне?!"
    ],
    # Block 22 (0x060310, budget 24B, 1 bubble)
    21: [
        "Их много!"
    ],
    # Block 23 (0x060328, budget 36B, 1 bubble)
    22: [
        "Как назойливы!"
    ],
    # Block 24 (0x06034C, budget 52B, 1 bubble)
    23: [
        "Откуда они все\nвзялись?!"
    ],
    # Block 25 (0x060380, budget 380B, 7 bubbles)
    24: [
        "Поставим точку!",
        "Где Ринея?!",
        "Спасибо твоей сестре.",
        "С ней всё вышло легко.",
        "Ложь! Ринея не станет\nпомогать!",
        "Я обещал убить брата,\nесли откажет.",
        "Иначе зачем амулет?"
    ],
    # Block 26 (0x0604FC, budget 120B, 2 bubbles)
    25: [
        "Злодей, тебе нет\nпрощения!",
        "Важна лишь цель."
    ],
    # Block 27 (0x060574, budget 28B, 1 bubble)
    26: [
        "Их тьма!"
    ],
    # Block 28 (0x060590, budget 76B, 1 bubble)
    27: [
        "Ха-ха-ха! Мне даже\nдраться не нужно!"
    ],
    # Block 29 (0x0605DC, budget 120B, 2 bubbles)
    28: [
        "Вам не уйти живыми!",
        "О-хо-хо! Мертвецам\nне нужен дом!"
    ],
    # Block 30 (0x060654, budget 84B, 2 bubbles)
    29: [
        "Нас всего трое?",
        "Само собой!"
    ],
    # Block 31 (0x0606A8, budget 192B, 3 bubbles)
    30: [
        "Нага, подлечи нас,\nладно?",
        "А как драться мне?!",
        "Упадёшь — разбужу\nтапком!"
    ],
    # Block 32 (0x060768, budget 176B, 3 bubbles)
    31: [
        "Дион! Я не прощу тебя!",
        "Эльф смеет мне\nперечить?!",
        "Ради Ринеи я не\nсдамся!"
    ],
    # Block 33 (0x060818, budget 188B, 3 bubbles)
    32: [
        "Лина, их же тьма!",
        "Хватит ныть, читай\nзаклинание!",
        "Я же просил вправо!"
    ],
    # Block 34 (0x0608D4, budget 52B, 2 bubbles)
    33: [
        "Ларк, ты цел?",
        "Держусь!"
    ],
    # Block 35 (0x060908, budget 260B, 8 bubbles)
    34: [
        "Убью вас быстро!",
        "Вперёд, все вместе!",
        "Положись на меня!",
        "Да!",
        "Конечно!",
        "Есть!",
        "Драгу-Слейв здесь не\nсработает!",
        "Прорвёмся!"
    ],
    # Block 36 (0x060A0C, budget 180B, 2 bubbles)
    35: [
        "Глупцы, вам не\nпобедить.",
        "С верой в справедливость\nзло никогда не победит!"
    ],
    # Block 37 (0x060AC0, budget 248B, 4 bubbles)
    36: [
        "Эльф нанял тебя,\nзачем рисковать?",
        "Зачем идти на смерть?",
        "Терпеть не могу\nсдаваться!",
        "И крушу всех, кто мне\nне по нраву!"
    ],
    # Block 38 (0x060BB8, budget 56B, 2 bubbles)
    37: [
        "Ещё дерётесь?!",
        "Пока живы!"
    ],
    # Block 39 (0x060BF0, budget 68B, 2 bubbles)
    38: [
        "Сдайтесь!",
        "Я не умею сдаваться."
    ],
    # Block 40 (0x060C34, budget 112B, 2 bubbles)
    39: [
        "Эльф победит меня?!",
        "Ради Ринеи я не отступлю!"
    ],
    # Block 41 (0x060CA4, budget 120B, 2 bubbles)
    40: [
        "Девчонка дерзит?!",
        "Не стану смотреть\nна гибель мира!"
    ],
    # Block 42 (0x060D1C, budget 168B, 4 bubbles)
    41: [
        "Тут можно жахнуть\nДрагу-Слейвом.",
        "Лина, не вздумай.",
        "Не надо...",
        "Совесть есть?"
    ],
    # Block 43 (0x060DC4, budget 148B, 2 bubbles)
    42: [
        "Разберёмся по-быстрому!",
        "Разбили их логово —\nи бандитам конец."
    ],
    # Block 44 (0x060E58, budget 124B, 2 bubbles)
    43: [
        "Лина, без мощной магии!",
        "Не бойся, не умрут!♥"
    ],
    # Block 45 (0x060ED4, budget 124B, 2 bubbles)
    44: [
        "Лина, без мощной магии!",
        "Не бойся, не умрут!♥"
    ],
    # Block 46 (0x060F50, budget 124B, 2 bubbles)
    45: [
        "Лина, без мощной магии!",
        "Не бойся, не умрут!♥"
    ],
    # Block 47 (0x060FCC, budget 124B, 2 bubbles)
    46: [
        "Лина, без мощной магии!",
        "Не бойся, не умрут!♥"
    ],
    # Block 48 (0x061048, budget 168B, 3 bubbles)
    47: [
        "Добьём их и заберём\nдобычу!",
        "Лина, это ужасно...",
        "С бандитами закон не\nписан!"
    ],
    # Block 49 (0x0610F0, budget 88B, 2 bubbles)
    48: [
        "Одни тролли...",
        "Сокровища ждут!"
    ],
    # Block 50 (0x061148, budget 28B, 1 bubble)
    49: [
        "Где бандиты?"
    ],
    # Block 51 (0x061164, budget 28B, 1 bubble)
    50: [
        "Где бандиты?"
    ],
    # Block 52 (0x061180, budget 28B, 1 bubble)
    51: [
        "Где бандиты?"
    ],
    # Block 53 (0x06119C, budget 164B, 3 bubbles)
    52: [
        "До чего же надоели!",
        "Отдайте эльфа!",
        "Впрочем, вас я всё равно\nуничтожу!"
    ],
    # Block 54 (0x061240, budget 120B, 2 bubbles)
    53: [
        "Людишкам не одолеть меня!",
        "Посмотрим, когда попробуем!"
    ],
    # Block 55 (0x0612B8, budget 108B, 3 bubbles)
    54: [
        "Ринея цела?!",
        "Хочешь знать —\nиди с нами.",
        "Ни за что!"
    ],
    # Block 56 (0x061324, budget 28B, 1 bubble)
    55: [
        "Демон?!"
    ],
    # Block 57 (0x061340, budget 92B, 3 bubbles)
    56: [
        "Мазоку?!",
        "Нет!",
        "Сначала в бой!"
    ],
    # Block 58 (0x06139C, budget 100B, 2 bubbles)
    57: [
        "Что это за твари?",
        "Призраки! Руби их\nмечом!"
    ],
    # Block 59 (0x061400, budget 124B, 2 bubbles)
    58: [
        "Обычная магия слаба!",
        "Эльмекия-Ланс их пробьёт!"
    ],
    # Block 60 (0x06147C, budget 56B, 2 bubbles)
    59: [
        "Прорываемся!",
        "Я с тобой!"
    ],
    # Block 61 (0x0614B4, budget 72B, 2 bubbles)
    60: [
        "Тут много призраков!",
        "Не зевать!"
    ],
    # Block 62 (0x0614FC, budget 36B, 2 bubbles)
    61: [
        "Вперёд!",
        "Ага!"
    ],
    # Block 63 (0x061520, budget 268B, 7 bubbles)
    62: [
        "Низшие мазоку.",
        "Их много.",
        "Тут деревня Ларка,\nбез мощной магии!",
        "Ой, забыла...",
        "Что?!",
        "Без Драгу-Слейва!",
        "Да знаю я!"
    ],
    # Block 64 (0x06162C, budget 144B, 3 bubbles)
    63: [
        "Лина, призраки!",
        "Не реви! Ты жрица или кто?!",
        "Сама же испугалась!"
    ],
    # Block 65 (0x0616BC, budget 44B, 2 bubbles)
    64: [
        "Внимание!",
        "Есть!"
    ],
    # Block 66 (0x0616E8, budget 36B, 2 bubbles)
    65: [
        "Цел?",
        "Да!"
    ],
    # Block 67 (0x06170C, budget 44B, 2 bubbles)
    66: [
        "Ты в порядке?",
        "Да!"
    ],
    # Block 68 (0x061738, budget 128B, 2 bubbles)
    67: [
        "Амелия, бей по призракам\nсвоей магией!",
        "Н-но я..."
    ],
    # Block 69 (0x0617B8, budget 68B, 1 bubble)
    68: [
        "Столько лессер-демонов\nпризвал?!"
    ],
    # Block 70 (0x0617FC, budget 84B, 3 bubbles)
    69: [
        "Кто за Галевом?!",
        "Их тьма!",
        "Чёрт!"
    ],
    # Block 71 (0x061850, budget 76B, 2 bubbles)
    70: [
        "Старик скрылся!",
        "Быстро бегает!"
    ],
    # Block 72 (0x06189C, budget 36B, 1 bubble)
    71: [
        "Старик силён!"
    ],
    # Block 73 (0x0618C0, budget 32B, 1 bubble)
    72: [
        "Что за гады?!"
    ],
    # Block 74 (0x0618E0, budget 32B, 1 bubble)
    73: [
        "Наёмники."
    ],
    # Block 75 (0x061900, budget 104B, 2 bubbles)
    74: [
        "Он метит во владыки\nмира!",
        "Я приму вызов!"
    ],
    # Block 76 (0x061968, budget 48B, 2 bubbles)
    75: [
        "Он маг.",
        "Не бойся."
    ],
    # Block 77 (0x061998, budget 76B, 2 bubbles)
    76: [
        "Доспехи?!",
        "Слабая магия бессильна!"
    ],
    # Block 78 (0x0619E4, budget 60B, 1 bubble)
    77: [
        "В доме мощно не ударишь!"
    ],
    # Block 79 (0x061A20, budget 128B, 2 bubbles)
    78: [
        "Лина, можно сдуть их,\nне ломая дом?",
        "Знала б — сдула!"
    ],
    # Block 80 (0x061AA0, budget 36B, 1 bubble)
    79: [
        "Опять доспехи?!"
    ],
    # Block 81 (0x061AC4, budget 40B, 1 bubble)
    80: [
        "Бьём по одному!"
    ],
    # Block 82 (0x061AEC, budget 16B, 1 bubble)
    81: [
        "Опять!"
    ],
    # Block 83 (0x061AFC, budget 96B, 2 bubbles)
    82: [
        "Лучше, чем в доме.",
        "Бейте странного типа!"
    ],
    # Block 84 (0x061B5C, budget 160B, 2 bubbles)
    83: [
        "Гр-р! Вы сильны, но я\nещё вернусь!",
        "О-хо-хо! Лишь детей\nобижать горазд!"
    ],
    # Block 85 (0x061BFC, budget 44B, 2 bubbles)
    84: [
        "Гадина!",
        "Бежит?!"
    ],
    # Block 86 (0x061C28, budget 64B, 1 bubble)
    85: [
        "Влезли не в своё дело!"
    ],
    # Block 87 (0x061C68, budget 88B, 3 bubbles)
    86: [
        "Эмилия солгала...",
        "Стой!",
        "Увидимся."
    ],
    # Block 88 (0x061CC0, budget 84B, 2 bubbles)
    87: [
        "Людишки! Эмилия, добей!",
        "Убожество!"
    ],
    # Block 89 (0x061D14, budget 84B, 2 bubbles)
    88: [
        "Отступлю пока.",
        "Подумай над сделкой."
    ],
    # Block 90 (0x061D68, budget 84B, 2 bubbles)
    89: [
        "Недурно!",
        "Про Моссмана не соврали."
    ],
    # Block 91 (0x061DBC, budget 40B, 2 bubbles)
    90: [
        "Готов?",
        "Вроде да."
    ],
    # Block 92 (0x061DE4, budget 140B, 3 bubbles)
    91: [
        "Победили?",
        "Лина, почему он шёл\nза тобой?",
        "Без понятия. Это второй."
    ],
    # Block 93 (0x061E70, budget 144B, 3 bubbles)
    92: [
        "Минус третий!",
        "Фогг в Лезариаме?",
        "Если враги лишь Зодд и\nте бандиты."
    ],
    # Block 94 (0x061F00, budget 80B, 3 bubbles)
    93: [
        "Всё?",
        "Да, но...",
        "Остался Фогг."
    ],
    # Block 95 (0x061F50, budget 100B, 3 bubbles)
    94: [
        "Готово!",
        "Скорей, пока не\nпризван владыка!",
        "Знаю!"
    ],
    # Block 96 (0x061FB4, budget 96B, 2 bubbles)
    95: [
        "Быстрее, времени нет!",
        "Фогг был не один?!"
    ],
    # Block 97 (0x062014, budget 100B, 2 bubbles)
    96: [
        "Хватит мельтешить!",
        "Они слишком быстрые!"
    ],
    # Block 98 (0x062078, budget 92B, 2 bubbles)
    97: [
        "Палят Стрелами отовсюду!",
        "Они без мозгов!"
    ],
    # Block 99 (0x0620D4, budget 80B, 2 bubbles)
    98: [
        "Лина, скорее!",
        "Мелочи слишком много!"
    ],
    # Block 100 (0x062124, budget 176B, 3 bubbles)
    99: [
        "Что за призыв,\nобъясни?!",
        "Ритуал сорван, не бойся!",
        "Не зевай, Нага!"
    ],
    # Block 101 (0x0621D4, budget 152B, 2 bubbles)
    100: [
        "Ещё живы? Упорные.",
        "О-хо-хо! Мелким мазоку\nне одолеть меня!"
    ],
    # Block 102 (0x06226C, budget 156B, 2 bubbles)
    101: [
        "Нага, как вы смеете\nдразнить мазоку?!",
        "Побеждает тот, кто выше\nдухом!"
    ],
    # Block 103 (0x062308, budget 172B, 3 bubbles)
    102: [
        "Числом не задавите!",
        "Лина, старик разделся!",
        "Боится запачкать костюм!"
    ],
    # Block 104 (0x0623B4, budget 48B, 1 bubble)
    103: [
        "Големы крепкие!"
    ],
    # Block 105 (0x0623E4, budget 56B, 2 bubbles)
    104: [
        "Я устала...",
        "Держись!"
    ],
    # Block 106 (0x06241C, budget 196B, 3 bubbles) - User screenshot dialogue
    105: [
        "Пошла б ты с нами,\nне совали б нос!",
        "Заткнись!\nНи за что!",
        "Ой, как страшно!\nНадолго ль спеси?"
    ],
    # Block 107 (0x0624E0, budget 40B, 2 bubbles)
    106: [
        "Мазоку?",
        "Не они!"
    ],
    # Block 108 (0x062508, budget 168B, 3 bubbles)
    107: [
        "Опять влипли?",
        "Являешься под конец и\nдерзишь?!",
        "Впрочем, спасибо."
    ],
    # Block 109 (0x0625B0, budget 56B, 1 bubble)
    108: [
        "Они прячутся за\nколоннами!"
    ],
    # Block 110 (0x0625E8, budget 72B, 1 bubble)
    109: [
        "Призраки ранят разум!"
    ],
    # Block 111 (0x062630, budget 156B, 2 bubbles)
    110: [
        "Амелия, сбила бы пару\nврагов до появления!",
        "Что вы, это же подло!"
    ],
    # Block 112 (0x0626CC, budget 24B, 1 bubble)
    111: [
        "Готов!"
    ],
    # Block 113 (0x0626E4, budget 152B, 3 bubbles)
    112: [
        "Лина, кто это?",
        "Это Зодд, забыл?!",
        "Знаю, но он не такой,\nкак прежде."
    ],
    # Block 114 (0x06277C, budget 238B, 4 bubbles)
    113: [
        "Амелия, изгони\nпризраков!",
        "Но Святое Дыхание\nотнимет силы...",
        "Твои, не мои, так\nчто вперёд!",
        "Лина, вы жестоки..."
    ]
}


def verify_and_build(raw_blocks_path: Path):
    raw_blocks = json.loads(raw_blocks_path.read_text(encoding="utf-8"))
    assert len(raw_blocks) == 114, f"Expected 114 blocks, found {len(raw_blocks)}"
    
    total_encoded_bytes = 0
    total_budget_bytes = 0
    overflows = []
    line_errors = []
    
    final_blocks = []
    for i, b in enumerate(raw_blocks):
        trans = BLOCK_TRANSLATIONS.get(i)
        assert trans is not None, f"Missing translation for block {i+1}"
        assert len(trans) == len(b["bubbles"]), f"Block {i+1} has {len(b['bubbles'])} bubbles but {len(trans)} translations"
        
        block_dict = {
            "id": b["id"],
            "block_index": b["block_index"],
            "offset": b["offset"],
            "ram_address": b["ram_address"],
            "allocated_budget_bytes": b["allocated_budget_bytes"],
            "bubbles": []
        }
        
        # If block 106 (offset 0x06241C), add cue_id compatibility
        if b["offset"] == "0x06241C":
            block_dict["cue_id"] = "block_092"
            block_dict["legacy_id"] = "combat_dlg_092"
        
        for j, bub in enumerate(b["bubbles"]):
            raw_ru = trans[j]
            ru_text = wrap_bubble_text(raw_ru, max_chars=21, max_lines=3)
            lines = ru_text.split("\n")
            if len(lines) > 3:
                line_errors.append(f"Block {b['id']} bubble {j+1} has {len(lines)} lines > 3: {ru_text!r}")
            for l in lines:
                if len(l) > 21:
                    line_errors.append(f"Block {b['id']} bubble {j+1} line exceeds 21 chars: {l!r} (len={len(l)})")
            
            # Check English text for any corrupted kanji (characters outside ASCII/digraphs)
            en_text = bub["text_en"]
            for ch in en_text:
                if ord(ch) >= 0x4E00:
                    raise ValueError(f"Corrupted kanji {ch!r} found in English text of block {b['id']}")
            
            block_dict["bubbles"].append({
                "bubble_index": j + 1,
                "speaker": bub["speaker"],
                "speaker_opcode": bub["speaker_opcode"],
                "text_jp": bub["text_jp"],
                "text_en": en_text,
                "text_ru": ru_text
            })
        
        enc = encode_conversation_block(block_dict, CHARMAP)
        total_encoded_bytes += len(enc)
        total_budget_bytes += b["allocated_budget_bytes"]
        
        if len(enc) > b["allocated_budget_bytes"]:
            overflows.append((b["id"], b["offset"], len(enc), b["allocated_budget_bytes"], len(enc) - b["allocated_budget_bytes"]))
        
        final_blocks.append(block_dict)
    
    if line_errors:
        print(f"FAILED: {len(line_errors)} line formatting errors:")
        for err in line_errors[:10]:
            print("  ", err)
        return False, None
    
    if overflows:
        print(f"FAILED: {len(overflows)} budget overflows:")
        for ov in overflows:
            print(f"  {ov[0]} at {ov[1]}: {ov[2]} bytes > {ov[3]} budget (+{ov[4]} bytes)")
        return False, None
    
    print(f"SUCCESS: All 114 blocks verified! Encoded {total_encoded_bytes:,} bytes within {total_budget_bytes:,} budget.")
    
    catalog = {
        "metadata": {
            "version": "1.0",
            "source_archive": "PROG.UNT",
            "entry_index": "0x007",
            "dialogue_stream_offset": "0x05F810",
            "total_blocks": 114,
            "max_chars_per_line": 21,
            "max_lines_per_bubble": 3
        },
        "blocks": final_blocks
    }
    return True, catalog


if __name__ == "__main__":
    raw_path = REPO_ROOT / "data" / "raw_extracted_combat_blocks.json"
    ok, catalog = verify_and_build(raw_path)
    if not ok:
        sys.exit(1)
    
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved verified catalog to {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size:,} bytes)")
