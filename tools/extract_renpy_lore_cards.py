#!/usr/bin/env python3
"""Extract and catalog Russian character lore card texts from Slayers Royal: Ren'Py Edition.

This tool extracts dialogue, character descriptions, and card texts from
`renpy_extracted/game/script.rpy` and `help_cards.rpy`, harmonizes them with the
13 character lore card resource slots identified in PROG.UNT and OPT.UNT,
and produces the structured dataset `data/lore_cards_ru.json`.
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


@dataclass
class LoreCard:
    id: str
    prog_entry: int
    opt_entry: Optional[int]
    title_main: str
    title_sub: str
    banner_opt: Optional[str]
    lines: list[str]
    renpy_source: Optional[dict[str, Any]] = None


# Specifications for all 13 lore cards in Slayers Royal PS1
# Aligned with PROG.UNT and OPT.UNT archives
CARD_METADATA: list[dict[str, Any]] = [
    {
        "id": "lina",
        "prog_entry": 32,
        "opt_entry": 182,
        "title_main": "[Л] Лина Инверс",
        "title_sub": "(Волшебница и гроза воров)",
        "banner_opt": "ЛИНА ИНВЕРС",
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
        "title_main": "[Г] Гаури Габриев",
        "title_sub": "(Мечник и опекун)",
        "banner_opt": "ГАУРИ ГАБРИЕВ",
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
        "title_main": "[С] Нага Белая Змея",
        "title_sub": "(Нага Змеюка)",
        "banner_opt": "НАГА ЗМЕЮКА",
        "lines": [
            "Была напарницей Лины до встречи с Гаури.",
            "Самопровозглашённая величайшая и",
            "сильнейшая соперница Лины. Её магический",
            "талант может даже превосходить талант",
            "Лины, однако в его применении кроется",
            "фатальный изъян: Нага нередко калечит",
            "самое себя.",
            "Синоним: помёт золотой рыбки.",
        ],
    },
    {
        "id": "map_controls",
        "prog_entry": 37,
        "opt_entry": None,
        "title_main": "[К] Карта местности",
        "title_sub": "(Управление на карте)",
        "banner_opt": None,
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
        "title_main": "[З] Свойства заклинаний",
        "title_sub": "(Особенности магии)",
        "banner_opt": "СВОЙСТВА ЗАКЛИНАНИЙ",
        "lines": [
            "Среди видов астральной магии заклинания",
            "вроде Эльмекия Ланс и Ра Тилт наносят",
            "урон противнику из астрального плана.",
            "Они действуют даже на существ вроде",
            "демонов, чья природа близка к чистому",
            "духу. Однако чем выше ранг мазоку, тем",
            "сильнее их защита от магии, из-за чего",
            "сила этих заклинаний снижается.",
        ],
    },
    {
        "id": "rezarium_legend",
        "prog_entry": 40,
        "opt_entry": 187,
        "title_main": "[Л] Легенда о Резариуме",
        "title_sub": "(Запечатанный город эльфов)",
        "banner_opt": "ЛЕГЕНДА О РЕЗАРИУМЕ",
        "lines": [
            "Замок, возведённый эльфами в далёком",
            "прошлом для изучения магии. По преданию,",
            "созданное там заклинание оказалось столь",
            "сокрушительным, что эльфы, так ни разу",
            "и не применив его, предпочли запечатать",
            "весь замок целиком.",
            "Говорят, ключом к нему служат ожерелья,",
            "сокрытые где-то в этом мире.",
        ],
    },
    {
        "id": "campaign_guide",
        "prog_entry": 41,
        "opt_entry": 188,
        "title_main": "[А] Акция гостиниц",
        "title_sub": "(Специальная акция)",
        "banner_opt": "АКЦИЯ ГОСТИНИЦ",
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
        "title_main": "[О] Ожерелья Резариума",
        "title_sub": "(Ключи от запечатанного замка)",
        "banner_opt": "ОЖЕРЕЛЬЕ РЕЗАРИУМА",
        "lines": [
            "Древние ожерелья, подвластные лишь",
            "потомкам рода Флеймдол — Ларку",
            "и Линее. Любое из них способно отпереть",
            "врата Резариума, однако снять печать",
            "с замка удастся, только если собрать",
            "оба ожерелья вместе. Их сила устроена так,",
            "чтобы никто не мог овладеть ею в одиночку.",
        ],
    },
    {
        "id": "zelgadis",
        "prog_entry": 45,
        "opt_entry": 190,
        "title_main": "[З] Зелгадис Грейвордс",
        "title_sub": "(Химера-мечник)",
        "banner_opt": "ЗЕЛГАДИС",
        "lines": [
            "Странствует по свету в поисках способа",
            "вернуть себе человеческое тело после того,",
            "как стал химерой демона и голема.",
            "Сочетает магическую мощь демона",
            "с неуязвимостью каменного голема,",
            "владеет высшей шаманской магией.",
            "Странствия с Линой редко сулят этому",
            "хладнокровному мечнику хоть что-то,",
            "кроме бесконечных неприятностей.",
        ],
    },
    {
        "id": "amelia",
        "prog_entry": 47,
        "opt_entry": 191,
        "title_main": "[А] Амелия Вил Тесла Сейрун",
        "title_sub": "(Принцесса Сейруна)",
        "banner_opt": "АМЕЛИЯ СЕЙРУН",
        "lines": [
            "Пылкая защитница добра и справедливости,",
            "чья вера зиждется на девизе: «Правое дело",
            "всегда побеждает!». Жрица и непоседливая",
            "принцесса королевства Сейрун, искусная",
            "в белой и шаманской магии. Амелия также",
            "превосходно владеет рукопашным боем",
            "и питает слабость к эффектным появлениям.",
        ],
    },
    {
        "id": "sylphiel",
        "prog_entry": 49,
        "opt_entry": 192,
        "title_main": "[С] Сильфиль Нельс Лаада",
        "title_sub": "(Жрица Сейруна)",
        "banner_opt": "СИЛЬФИЛЬ ЛААДА",
        "lines": [
            "Дочь верховного жреца Сайраага,",
            "утончённая длинноволосая красавица",
            "и выдающийся целитель. Пожалуй,",
            "единственный человек во всей компании,",
            "обладающий здравым рассудком",
            "и хладнокровием. Впрочем, когда дело",
            "касается Гаури, даже Сильфиль способна",
            "напрочь потерять благоразумие.",
        ],
    },
    {
        "id": "rezarium_magic",
        "prog_entry": 51,
        "opt_entry": 193,
        "title_main": "[М] Магия Резариума",
        "title_sub": "(Два древних устройства)",
        "banner_opt": "МАГИЯ РЕЗАРИУМА",
        "lines": [
            "В Резариуме запечатано не заклинание,",
            "а два устройства, действующих на силе",
            "магии. Один замок служит аппаратом для",
            "воспроизведения событий прошлого, второй",
            "же выполняет роль управляющей системы.",
            "Два священных ожерелья являются ключами,",
            "каждое из которых запускает своё",
            "собственное устройство.",
        ],
    },
    {
        "id": "galef",
        "prog_entry": 53,
        "opt_entry": None,
        "title_main": "[Г] Галеф Кайнзард",
        "title_sub": "(Лидер общества «Зайн»)",
        "banner_opt": None,
        "lines": [
            "Создатель и глава тайного общества «Зайн».",
            "Обладает колоссальной магической силой",
            "и грезит о мировом господстве, однако из-за",
            "полной безалаберности не сумел свести концы",
            "с концами. В итоге от него сбежали не только",
            "все подчинённые, но даже жена и дети.",
            "«Шёл бы ты лучше работать, старик...»",
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
            "title_main": item["title_main"],
            "title_sub": item["title_sub"],
            "banner_opt": item["banner_opt"],
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


def verify_catalog(catalog: list[dict[str, Any]]) -> bool:
    """Verify integrity of extracted card dataset."""
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
        default=Path("data/lore_cards_ru.json"),
        help="Output JSON file path",
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

    if not verify_catalog(catalog):
        print("Verification failed!", file=sys.stderr)
        return 1

    # Ensure output dir exists
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    print(f"Successfully saved catalog to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
