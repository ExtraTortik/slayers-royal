#!/usr/bin/env python3
"""Extract and catalog Russian character lore card texts from Slayers Royal: Ren'Py Edition.

Parses renpy_extracted/game/script.rpy and help_cards.rpy for character info,
merges with the full 13 character lore card resource slots identified in PROG.UNT and OPT.UNT,
and produces the structured dataset translations/lore_cards_ru.json.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class LoreCard:
    id: str
    prog_entry: int
    opt_entry: Optional[int]
    type: str
    title_main: str
    title_sub: str
    banner_opt: Optional[str]
    description: str
    lines: list[str]
    renpy_source: Optional[dict[str, Any]] = None


# Specifications for all 13 lore cards in Slayers Royal PS1
# Aligned with PROG.UNT and OPT.UNT archives
CARD_METADATA: list[dict[str, Any]] = [
    {
        "id": "lina",
        "prog_entry": 32,
        "opt_entry": 182,
        "type": "split_card",
        "title_main": "[Л] Лина Инверс",
        "title_sub": "(Волшебница и гроза воров)",
        "banner_opt": "ЛИНА ИНВЕРС",
        "description": "Первоклассный мечник и выдающаяся волшебница, Лина — наша главная героиня. Среди её прозвищ — «Гроза воров» и «Та, кого обходит дракон». Она грабит бандитов ради забавы и выгоды. Её конёк — разрушительная магия, а сдержанность явно не входит в число её достоинств.",
        "lines": [
            "Первоклассный мечник и выдающаяся",
            "волшебница, Лина — наша главная",
            "героиня. Среди её прозвищ — «Гроза",
            "воров» и «Та, кого обходит дракон».",
            "Она грабит бандитов ради забавы",
            "и выгоды. Её конёк — разрушительная",
            "магия, а сдержанность явно не входит",
            "в число её достоинств.",
        ],
    },
    {
        "id": "gourry",
        "prog_entry": 34,
        "opt_entry": 183,
        "type": "split_card",
        "title_main": "[Г] Гаури Габриев",
        "title_sub": "(Мечник и опекун)",
        "banner_opt": "ГАУРИ ГАБРИЕВ",
        "description": "Первоклассный мечник и писаный красавец. Всё бы хорошо, но память у него как у слизня, а житейского ума и того меньше. Повстречав Лину в пути, он почему-то возомнил себя её опекуном. Лина же часто держит его просто за удобный инструмент. Самопровозглашённый опекун Лины.",
        "lines": [
            "Первоклассный мечник и писаный",
            "красавец. Всё бы хорошо, но память",
            "у него как у слизня, а житейского",
            "ума и того меньше. Повстречав Лину",
            "в пути, он почему-то возомнил себя",
            "её опекуном. Лина же часто держит",
            "его просто за удобный инструмент.",
            "Самопровозглашённый опекун Лины.",
        ],
    },
    {
        "id": "naga",
        "prog_entry": 36,
        "opt_entry": 184,
        "type": "split_card",
        "title_main": "[С] Нага Белая Змея",
        "title_sub": "(Нага Змеюка)",
        "banner_opt": "НАГА ЗМЕЮКА",
        "description": "Была напарницей Лины до её встречи с Гаури. Самопровозглашённая величайшая и сильнейшая соперница Лины.\n\nЕё магический талант может даже превосходить талант Лины, однако в применении этого таланта кроется фатальный недостаток: Нага нередко получает серьёзные повреждения.\n\nСиноним: помёт золотой рыбки.",
        "lines": [
            "Была напарницей Лины до её встречи",
            "с Гаури. Самопровозглашённая величайшая",
            "и сильнейшая соперница Лины. Её магический",
            "талант может даже превосходить талант Лины,",
            "однако в применении этого таланта кроется",
            "фатальный недостаток: Нага нередко",
            "получает серьёзные повреждения.",
            "Синоним: помёт золотой рыбки.",
        ],
    },
    {
        "id": "map_controls",
        "prog_entry": 37,
        "opt_entry": 185,
        "type": "combined_8bpp",
        "title_main": "[К] Карта местности",
        "title_sub": "(Управление на карте)",
        "banner_opt": "УПРАВЛЕНИЕ",
        "description": "Если значение значка вам неизвестно, наведите на него курсор и нажмите кнопку SELECT на контроллере. На экране появится краткая справка.\n\nКнопка О: Выбрать / Осмотреть\nКнопка Х: Показать / Скрыть значки",
        "lines": [
            "Если значение значка вам неизвестно,",
            "наведите на него курсор и нажмите",
            "кнопку SELECT на контроллере.",
            "На экране появится краткая справка.",
            "",
            "Кнопка О: Выбрать / Осмотреть",
            "Кнопка Х: Показать / Скрыть значки",
        ],
    },
    {
        "id": "spell_traits",
        "prog_entry": 38,
        "opt_entry": 186,
        "type": "combined_8bpp",
        "title_main": "[З] Свойства заклинаний",
        "title_sub": "(Особенности магии)",
        "banner_opt": "СВОЙСТВА ЗАКЛИНАНИЙ",
        "description": "Среди видов астральной магии, не относящихся к чёрной магии, такие заклинания, как Эльмекия Ланс и Ра Тилт, способны наносить урон врагу с астрального плана. Поэтому они эффективны даже против таких существ, как демоны, чья сущность близка к астральной. Однако чем выше ранг демона, тем сильнее его защита от магии, из-за чего эффект таких заклинаний ослабевает.",
        "lines": [
            "Среди видов астральной магии, не относящихся",
            "к чёрной магии, такие заклинания, как",
            "Эльмекия Ланс и Ра Тилт, способны наносить",
            "урон врагу с астрального плана. Поэтому они",
            "эффективны даже против таких существ, как",
            "демоны, чья сущность близка к астральной.",
            "Однако чем выше ранг демона, тем сильнее его",
            "защита от магии, из-за чего эффект таких",
            "заклинаний ослабевает.",
        ],
    },
    {
        "id": "rezarium_legend",
        "prog_entry": 40,
        "opt_entry": 187,
        "type": "split_card",
        "title_main": "[Л] Легенда о Резариуме",
        "title_sub": "(Запечатанный город эльфов)",
        "banner_opt": "ЛЕГЕНДА О РЕЗАРИУМЕ",
        "description": "Это эльфийский замок из далёкого прошлого. Согласно легенде, его построили эльфы, изучавшие магию, для своих исследований. Однако магия, заключённая в нём, оказалась настолько могущественной, что, так и не применив созданное заклинание, они запечатали замок. Говорят, где-то в мире есть ожерелья, способные снять эту печать.",
        "lines": [
            "Это эльфийский замок из далёкого прошлого.",
            "Согласно легенде, его построили эльфы,",
            "изучавшие магию, для своих исследований.",
            "Однако магия, заключённая в нём, оказалась",
            "настолько могущественной, что, так и не",
            "применив созданное заклинание, они запечатали",
            "замок. Говорят, где-то в мире есть ожерелья,",
            "способные снять эту печать.",
        ],
    },
    {
        "id": "campaign_guide",
        "prog_entry": 41,
        "opt_entry": 188,
        "type": "combined_8bpp",
        "title_main": "[А] Акция гостиниц",
        "title_sub": "(Специальная акция)",
        "banner_opt": "АКЦИЯ ГОСТИНИЦ",
        "description": "Совместная акция гильдий трактирщиков Сейруна и Союза Прибрежных Государств. Если собрать жетоны, выдаваемые постояльцам в гостиницах, и отнести их на базар в городе Кьюзак, то... вас ждёт нечто интересное?!",
        "lines": [
            "Совместная акция гильдий трактирщиков",
            "Сейруна и Союза Прибрежных Государств.",
            "Если собрать жетоны, выдаваемые",
            "постояльцам в гостиницах, и отнести их",
            "на базар в городе Кьюзак, то...",
            "вас ждёт нечто интересное?!",
        ],
    },
    {
        "id": "necklace",
        "prog_entry": 43,
        "opt_entry": 189,
        "type": "split_card",
        "title_main": "[О] Ожерелья Резариума",
        "title_sub": "(Ключи от запечатанного замка)",
        "banner_opt": "ОЖЕРЕЛЬЕ РЕЗАРИУМА",
        "description": "Ожерелья, которые могут использовать только Ларк и Линея — потомки рода Флеймдол. С одним ожерельем можно открыть двери Резариума, но для снятия печати Резариума необходимы оба. Их сила устроена так, чтобы никто не мог овладеть ею в одиночку.",
        "lines": [
            "Ожерелья, которые могут использовать только",
            "Ларк и Линея — потомки рода Флеймдол. С одним",
            "ожерельем можно открыть двери Резариума, но",
            "для снятия печати Резариума необходимы оба.",
            "Их сила устроена так, чтобы никто не мог",
            "овладеть ею в одиночку.",
        ],
    },
    {
        "id": "zelgadis",
        "prog_entry": 45,
        "opt_entry": 190,
        "type": "split_card",
        "title_main": "[З] Зелгадис Грейвордс",
        "title_sub": "(Химера-мечник)",
        "banner_opt": "ЗЕЛГАДИС",
        "description": "Путешествует, чтобы вернуть себе человеческое тело после того, как его превратили в химеру из смеси броу-демона и каменного голема. Обладает магической силой демона и защитными способностями голема, а также владеет высокоуровневой шаманской магией.\n\nПосле того, как он стал общаться с Линой и остальными, этот холодный мечник-маг иногда показывает и свою озорную сторону.",
        "lines": [
            "Путешествует, чтобы вернуть себе человеческое",
            "тело после того, как его превратили в химеру",
            "из смеси броу-демона и каменного голема.",
            "Обладает магической силой демона и защитными",
            "способностями голема, а также владеет",
            "высокоуровневой шаманской магией.",
            "После того, как он стал общаться с Линой и",
            "остальными, этот холодный мечник-маг иногда",
            "показывает и свою озорную сторону.",
        ],
    },
    {
        "id": "amelia",
        "prog_entry": 47,
        "opt_entry": 191,
        "type": "split_card",
        "title_main": "[А] Амелия Вил Тесла Сейрун",
        "title_sub": "(Принцесса Сейруна)",
        "banner_opt": "АМЕЛИЯ СЕЙРУН",
        "description": "Ярый борец за справедливость, помешанный на любви, правосудии и истине. Жрица и непоседливая принцесса Сейруна, она верит, что её долг — искоренять зло, следуя девизу «Справедливость всегда побеждает». Превосходно владеет белой и шаманской магией, а также искусна в рукопашном бою.",
        "lines": [
            "Ярый борец за справедливость, помешанный на",
            "любви, правосудии и истине. Жрица и",
            "непоседливая принцесса Сейруна, она верит,",
            "что её долг — искоренять зло, следуя девизу",
            "«Справедливость всегда побеждает».",
            "Превосходно владеет белой и шаманской магией,",
            "а также искусна в рукопашном бою.",
        ],
    },
    {
        "id": "sylphiel",
        "prog_entry": 49,
        "opt_entry": 192,
        "type": "split_card",
        "title_main": "[С] Сильфиль Нельс Лаада",
        "title_sub": "(Жрица Сайраага)",
        "banner_opt": "СИЛЬФИЛЬ ЛААДА",
        "description": "Дочь верховного священника города Сайрааг, утончённая красавица с длинными волосами, излучающая благородство. Обладает выдающимися магическими способностями. Вероятно, единственный в компании человек со здравым рассудком и моральными принципами… хотя иногда она теряет самообладание, когда дело касается Гаури.",
        "lines": [
            "Дочь верховного священника города Сайрааг,",
            "утончённая красавица с длинными волосами,",
            "излучающая благородство. Обладает выдающимися",
            "магическими способностями. Вероятно,",
            "единственный в компании человек со здравым",
            "рассудком и моральными принципами… хотя",
            "иногда она теряет самообладание, когда дело",
            "касается Гаури.",
        ],
    },
    {
        "id": "rezarium_magic",
        "prog_entry": 51,
        "opt_entry": 193,
        "type": "split_card",
        "title_main": "[М] Магия Резариума",
        "title_sub": "(Два древних устройства)",
        "banner_opt": "МАГИЯ РЕЗАРИУМА",
        "description": "В Резариуме запечатана не магия как таковая, а некое магическое устройство.\n\nРезариум состоит из двух за́мков: один служит аппаратом, визуализирующим события прошлого, другой выполняет роль управляющего механизма. Два ожерелья являются ключами для активации каждого из этих устройств.",
        "lines": [
            "В Резариуме запечатана не магия как таковая,",
            "а некое магическое устройство.",
            "Резариум состоит из двух за́мков: один служит",
            "аппаратом, визуализирующим события прошлого,",
            "другой выполняет роль управляющего механизма.",
            "Два ожерелья являются ключами для активации",
            "каждого из этих устройств.",
        ],
    },
    {
        "id": "galef",
        "prog_entry": 53,
        "opt_entry": None,
        "type": "split_card",
        "title_main": "[Г] Галеф Кайнзард",
        "title_sub": "(Лидер общества «Зайн»)",
        "banner_opt": None,
        "description": "Основатель и лидер тайного общества «Зайн». Обладая огромными магическими силами и амбициями покорения мира, он потерпел неудачу, и организация распалась из-за нехватки средств. Его бросили не только подчинённые, но даже жена и дети. «Соберись, старик...»",
        "lines": [
            "Основатель и лидер тайного общества «Зайн».",
            "Обладая огромными магическими силами и",
            "амбициями покорения мира, он потерпел",
            "неудачу, и организация распалась из-за",
            "нехватки средств. Его бросили не только",
            "подчинённые, но даже жена и дети. «Соберись,",
            "старик...»",
        ],
    },
]


def extract_renpy_card_calls(script_path: Path) -> dict[str, dict[str, Any]]:
    """Parse renpy_extracted/game/script.rpy for show_character_info invocations."""
    if not script_path.exists():
        return {}

    content = script_path.read_text(encoding="utf-8")
    extracted: dict[str, dict[str, Any]] = {}

    # Find balanced calls to show_character_info
    idx = 0
    while True:
        pos = content.find("call show_character_info", idx)
        if pos == -1:
            break

        open_paren = content.find("(", pos)
        if open_paren == -1:
            break

        depth = 0
        in_string = False
        escape = False
        end_paren = -1
        for i in range(open_paren, len(content)):
            c = content[i]
            if in_string:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_string = False
            else:
                if c == '"':
                    in_string = True
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        end_paren = i
                        break

        if end_paren != -1:
            inner = content[open_paren + 1 : end_paren].strip()
            try:
                parsed = ast.literal_eval(f"({inner})")
                name = parsed[0] if len(parsed) > 0 else ""
                desc = parsed[1] if len(parsed) > 1 else ""
                bg = parsed[2] if len(parsed) > 2 else ""

                # Associate by characteristic substrings
                card_key = None
                nl = name.lower()
                if "нага" in nl:
                    card_key = "naga"
                elif "заклинани" in nl:
                    card_key = "spell_traits"
                elif "легенда" in nl:
                    card_key = "rezarium_legend"
                elif "ожерель" in nl:
                    card_key = "necklace"
                elif "зелгадис" in nl:
                    card_key = "zelgadis"
                elif "амелия" in nl:
                    card_key = "amelia"
                elif "галеф" in nl:
                    card_key = "galef"
                elif "сильфиль" in nl:
                    card_key = "sylphiel"
                elif "магия" in nl:
                    card_key = "rezarium_magic"

                if card_key and card_key not in extracted:
                    extracted[card_key] = {
                        "name": name,
                        "desc": desc,
                        "bg": bg,
                        "char_offset": pos,
                    }
            except Exception as err:
                print(f"Warning: failed to parse call at {pos}: {err}", file=sys.stderr)

            idx = end_paren + 1
        else:
            idx = pos + len("call show_character_info")

    return extracted


def build_lore_cards(
    renpy_calls: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build complete 13-card catalog by combining metadata and Ren'Py source data."""
    catalog: list[dict[str, Any]] = []

    for item in CARD_METADATA:
        card_id = item["id"]
        source_data = renpy_calls.get(card_id)

        card = {
            "id": card_id,
            "prog_entry": item["prog_entry"],
            "opt_entry": item["opt_entry"],
            "type": item["type"],
            "title_main": item["title_main"],
            "title_sub": item["title_sub"],
            "banner_opt": item["banner_opt"],
            "description": item["description"],
            "lines": item["lines"],
        }
        if source_data:
            card["renpy_source"] = {
                "name": source_data["name"],
                "desc": source_data["desc"],
                "bg_frame": source_data["bg"],
            }
        catalog.append(card)

    return catalog


def verify_catalog(data: Any) -> bool:
    """Verify integrity of extracted card dataset."""
    if isinstance(data, dict) and "cards" in data:
        catalog = data["cards"]
    elif isinstance(data, list):
        catalog = data
    else:
        print("Verification ERROR: unrecognized catalog data format", file=sys.stderr)
        return False

    expected_count = 13
    if len(catalog) != expected_count:
        print(f"Verification ERROR: expected {expected_count} cards, got {len(catalog)}", file=sys.stderr)
        return False

    valid = True
    seen_ids = set()
    for idx, card in enumerate(catalog, start=1):
        cid = card.get("id")
        if not cid:
            print(f"Card #{idx} missing 'id'", file=sys.stderr)
            valid = False
        if cid in seen_ids:
            print(f"Duplicate card id: {cid}", file=sys.stderr)
            valid = False
        seen_ids.add(cid)

        prog_entry = card.get("prog_entry")
        if not isinstance(prog_entry, int) or prog_entry <= 0:
            print(f"Card '{cid}' invalid prog_entry: {prog_entry}", file=sys.stderr)
            valid = False

        title_main = card.get("title_main", "")
        if not title_main.startswith("[") or "]" not in title_main:
            print(f"Card '{cid}' title_main missing bracket tag: {title_main}", file=sys.stderr)
            valid = False

        title_sub = card.get("title_sub", "")
        if not title_sub.startswith("(") or not title_sub.endswith(")"):
            print(f"Card '{cid}' title_sub missing parentheses: {title_sub}", file=sys.stderr)
            valid = False

        lines = card.get("lines", [])
        if not isinstance(lines, list) or len(lines) == 0:
            print(f"Card '{cid}' lines empty or invalid", file=sys.stderr)
            valid = False
        else:
            for l_idx, line in enumerate(lines):
                if len(line) > 50:
                    print(f"Card '{cid}' line {l_idx+1} too long ({len(line)} chars): {line}", file=sys.stderr)
                    valid = False

    return valid


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract and catalog Russian lore cards from Ren'Py Edition"
    )
    parser.add_argument(
        "--script",
        type=Path,
        default=Path("renpy_extracted/game/script.rpy"),
        help="Path to script.rpy",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "translations" / "lore_cards_ru.json",
        help="Output JSON file path (default: translations/lore_cards_ru.json)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run verification check on output",
    )
    args = parser.parse_args()

    print(f"Extracting Ren'Py character info calls from {args.script}...")
    renpy_calls = extract_renpy_card_calls(args.script)
    print(f"Found {len(renpy_calls)} unique character info calls in script.rpy.")

    catalog = build_lore_cards(renpy_calls)
    print(f"Structured {len(catalog)} Russian lore cards.")

    output_dataset = {
        "metadata": {
            "title": "Slayers Royal (PS1) — Каталог справочных карточек персонажей и лора",
            "description": "Этот файл содержит тексты всех 13 справочных карточек (PROG.UNT) и 12 заголовков-баннеров галереи (OPT.UNT).",
            "instructions": {
                "title_main": "Главный заголовок с буквенным индексом: '[Буква] Имя' (до 28 символов).",
                "title_sub": "Подзаголовок в круглых скобках: '(Описание)' (до 32 символов).",
                "banner_opt": "Текст плашки для меню бонусов OPT.UNT (до 24 символов) или null.",
                "description": "Полный текст описания из Ren'Py / оригинальной игры (для удобного чтения и редактирования человеком).",
                "lines": "Массив строк текста для отображения на экране PS1 (320x224). Рекомендуется не более 8-9 строк до 45 символов в строке. Если опустить или оставить пустым, текст будет автоматически разбит по строкам из поля description.",
                "type": "Тип карточки: 'split_card' (4bpp оверлей текста) или 'combined_8bpp' (8bpp объединённый арт с текстом).",
            },
        },
        "cards": catalog,
    }

    if not verify_catalog(output_dataset):
        print("Verification failed!", file=sys.stderr)
        return 1

    # Ensure output dir exists
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(output_dataset, f, ensure_ascii=False, indent=2)
    print(f"Successfully saved catalog to {args.output}")

    # Synchronize data/lore_cards_ru.json if writing to translations/lore_cards_ru.json
    data_sync = REPO_ROOT / "data" / "lore_cards_ru.json"
    if args.output.resolve() == (REPO_ROOT / "translations" / "lore_cards_ru.json").resolve():
        with data_sync.open("w", encoding="utf-8") as f:
            json.dump(output_dataset, f, ensure_ascii=False, indent=2)
        print(f"Synchronized copy saved to {data_sync}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
