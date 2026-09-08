#!/usr/bin/env python3
"""Unabridge all 143 truncated room inspection strings in translations/room_inspection_ru.json.

Eliminates mechanical trailing '...' truncations by re-authoring them into complete,
natural Russian sentences reflecting Lina Inverse's voice, complying strictly with
PS1 hardware constraints:
- <= 15 Unicode characters per line
- 1 to 3 lines per string (delimited by \n)
- NFC Unicode normalization
- 100% Cyrillic charmap validity against DEFAULT_CHARMAP
- 0 unexpected trailing '...' unless deliberate in English
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))

from tools.patch_inspection import DEFAULT_CHARMAP
from tools.text_wrapper import wrap_dialogue

CATALOG_PATH = REPO_ROOT / "translations" / "room_inspection_ru.json"
BUILD_TRANSLATIONS_PATH = REPO_ROOT / "tools" / "build_inspection_translations.py"

UNABRIDGED_MAPPINGS: dict[str, str] = {
    'A bay window.\nMaybe an attic\nis up there.': 'Эркер. Под\nкрышей, небось,\nмансарда.',
    'A bigger town\nmeans more\nfoot traffic.': 'Город большой,\nвот и народу на\nулицах полно!',
    'A ceiling?\nWhy make me say\nthe obvious?': 'Потолок! Зачем\nзаставлять меня\nэто твердить?',
    'A chandelier...': 'Люстра...',
    'A cup by the\nbottle... Is\nthe barkeep': 'Кружка у винца.\nНе хозяин ли\nсам пригубил?..',
    "A few people\nhere and there.\nWe're on a hill": 'Народу немного.\nОтсюда виден\nвесь этот порт.',
    "A flowerpot.\nIt's dried out.\nGive it some": 'Цветок в кадке.\nЗасох совсем,\nхоть бы полили!',
    'A hexagonal\ndoor, too?\nBold choice...': 'Шестигранная\nдверь? Ну и вид\nу зодчего...',
    'A white silk\ndress.\nAre we in the': 'Вся в шелку! Мы\nточно туда\nсвернули?',
    'A north-facing\nwindow. Must be\ncool in summer.': 'Окно на север.\nЛетом тут,\nнебось, свежо.',
    'A parent and\nchild. Shopping\nor out walking?': 'Родитель с\nмалышом. Гуляют\nили на базар?',
    "A stone atop\nthe barrel.\nDon't tell me": 'Камень на бочке\nсоленья прижал,\nчто ли?',
    'A town without\na single tree\nwould be sad.': 'Без деревьев в\nгороде было бы\nочень грустно.',
    'A tree this big\nought to have\nsome fruit.': 'Такой гигант!\nХоть бы яблоки\nросли на нём.',
    'A tree trunk.\nBent in the\nmiddle. Poor': 'Изогнутый ствол\nна бревна точно\nне сгодится.',
    'A nice, clean\ninn.': 'Вполне уютная\nгостиница,\nчисто везде.',
    'A wine glass...': 'Бокал под\nвино...',
    'All sorts of\nthings here.': 'Чего тут только\nне найдется!',
    "An inn's for\nsleeping, not\nsightseeing.": 'В отеле спят, а\nне видами из\nокон любуются!',
    'An odd house.\nNot a shop or\na church...': 'Странное место:\nни лавка, ни\nхрам...',
    'An old woman...\nIs she spacing\nout?': 'Старушка...\nЗамечталась о\nчём-то, что ли?',
    'At least hang\nsome curtains.': 'Хоть занавески\nповесили бы,\nчто ли!',
    'At night, they\ncast Lighting\non this lamp.': 'Ночью на фонарь\nколдуют чары\nСвета, небось.',
    'Big brown legs.\nSo thick...\nWait a sec...': 'Толстые ноги...\nТьфу ты, это ж\nножки стола!',
    'Big house.\nRed roof, of\ncourse.': 'Большой дом.\nКрыша, ясное\nдело, красная.',
    'Big houses for\na back street.\nThis town must': 'Для закоулка\nдома богатые.\nГород богатеет!',
    'Big place, but\nonly one door.': 'Зал большой, а\nдверь наружу\nвсего одна.',
    'Boats dock\nright by the\nport, so the': 'Суда у берега —\nзначит, здесь\nглубоко.',
    "Bottles on the\ntable. I don't\ncare who drinks": 'Бутылки кругом.\nПейте что есть,\nмне все равно.',
    'Brick and white\nplaster? In an\nelf town? They': 'И это у эльфов?\nМогли б орихалк\nв дело пустить!',
    'By the stairs,\ndirt replaces\nthe stone wall,': 'Перед лестницей\nвместо стены\nпоросший холм.',
    "Can't peek in.\nCan't reach it.": 'И не заглянешь,\nи не достать.',
    "Can't sell food\nhere. It gets\nfull sun.": 'Еду тут не\nпродашь — на\nсолнце стухнет!',
    'Carelessly\nleft out.\nMust be cheap.': 'Бросили тут —\nзначит, вещь\nгрошовая.',
    'Chimney means\na living room\nlies below...': 'Раз труба —\nвнизу, небось,\nгостиная...',
    'Climb these\nstairs, go on,\nthen down the': 'Вверх по этой,\nчуть дальше и\nвниз по другой.',
    'Coins get stuck\nbetween stones\nlike these...': 'В щелях камней\nмонеты вечно\nзастревают...',
    "Come to think,\nI haven't seen\nother guests at": 'А ведь других\nжильцов я тут и\nне видела.',
    'Cushions would\nbe nice, but\ntavern chairs': 'С подушкой было\nб лучше, но их\nв драке порвут!',
    "Don't chat by\nsomeone's home.\nYou'd block the": 'Чего у дверей\nболтать? Проход\nзагораживают.',
    "Don't put boxes\nhere. Someone\ncould trip.": 'Ящики у входа —\nведь расшибется\nкто-нибудь!',
    "Don't stare\nsomewhere rude!\n...I'm the one": 'Не пялься туда!\nОй, я же сама\nпялюсь...',
    "Don't tell me\nthis guy cooks\nthe food...": 'Не говори, что\nон еще и еду\nстряпает!..',
    'Drab shop, but\nflashy clothes.': 'Серая лавка, а\nнаряд торговца\nвырвиглазный.',
    'Dressed better,\nhe could pass\nfor a top-class': 'Оденься лучше —\nсошел бы за\nлихого бойца!',
    "Every book may\nhide treasure\ntales, but I'd": 'Тут море тайн,\nно жизни читать\nне хватит!',
    'Frilly skirt,\nan apron.\nDefinitely a': 'Оборки, фартук.\nТипичная девица\nна побегушках.',
    'From that peak,\nyou could see\nthe whole town.': 'С вершины весь\nгород виден как\nна ладони!',
    'Guest rooms lie\npast this door.\nIf the entrance': 'Тут номера. А\nчто тогда за\nтой дверью?',
    'Hand grime may\nbe why it\nshines... No,': 'От грязи с рук\nблестит?.. Фу,\nне хочу знать!',
    'Hard to tell\nfrom this far,\nAn old woman?': 'Издалека плохо\nвидно. Старушка\nтам, что ли?',
    'Hazy and far\naway.': 'Вся в дымке.\nДалековато до\nнеё будет.',
    'He may be\nfleeing the man\nbehind him.': 'Может, удирает\nот парня, что\nсзади идет?',
    'He only takes\norders...': 'Он лишь заказы\nпринимает...',
    'How many days\nhas it been\nsince we met': 'Сколько дней мы\nзнакомы с этим\nЛарком?',
    "I can't tell if\nthey're a man\nor a woman.": 'Кто это: парень\nили девица? Как\nу Гаури косы.',
    "I don't want to\nsee it. Please\nstop...": 'Глаза б мои не\nвидели! Хватит\nуже этого...',
    'I expected more\nfrom an elf\nvillage. It': 'Ждала чудес от\nэльфов, а тут\nпросто село.',
    'I feel like no\none would\nnotice if I': 'Свистни я вещь\n— никто ведь и\nне заметит!',
    "I'd like to ask\nthe old man and\nchild how old": 'Сколько же лет\nэтому деду и\nтому ребенку?',
    "I'm not Naga.\nI don't stare\nat the ground": 'Я вам не Нага,\nчтоб под ноги\nмонеты искать!',
    "I've seen this\nsomewhere.\nThen again, all": 'Где-то видела.\nВпрочем, кабаки\nвсе одинаковы!',
    "If every inn\nwere so clean,\nI'd have no": 'Будь везде так\nчисто, я б и не\nжаловалась!',
    "If it's this\nbig, it should\nbe enough for": 'Из громадины\nможно целый дом\nпостроить!',
    'If there were a\nwindow here,\nevery passerby': 'Будь тут окно —\nвсе бы внутрь\nзаглядывали.',
    'If we ran wild\nupstairs, this\ncould give way': 'Устроим бучу —\nпол проломится\nпрямо ко входу!',
    'It earns the\nCity in its\nname.': 'Не зря он Сити:\nгород и правда\nогромен!',
    "It may look far\nbelow, but I'm\nnot up in the": 'Кажется, я\nвысоко, но тут\nлишь пригорок.',
    "It's a town\nchurch, so it\nmust be used": 'В храме небось\nслужбы идут\nкаждый день.',
    "It's easily\ntwice as wide\nas I am.": 'В ширину она\nраза в два шире\nменя самой!',
    "It's polished\nenough to slide\ndown from the": 'Начищено так,\nчто можно вниз\nсъехать в холл!',
    'Item shops sell\ntravel goods,\nlike capes.': 'Тут продают\nвещи в дорогу —\nвроде плащей.',
    'Just imagining\nthe walk from\none end to the': 'Мысль обойти\nвесь порт — и\nноги уже гудят!',
    'Leaving by that\nhouse leads up\nthe mountain.': 'Выйдешь за дом\n— и прямиком в\nгору пойдешь.',
    'Light comes in\nthrough the\nwindow.': 'Из окна падает\nсвет, вот хоть\nчто-то и видно.',
    'Look them in\nthe face when\nyou speak.': 'Говоришь с\nкем-то — смотри\nпрямо в лицо.',
    'Looks like a\nchimney...': 'Похоже, это\nдымоход...',
    'Looks like this\njourney is\nalmost over...': 'Путь на исходе.\nЛишь бы награду\nнам отдали...',
    "Looks pricey.\nDon't spill a\ndrink on it.": 'Ковер дорогой:\nне вздумай на\nнего пролить!',
    'Lots of houses\nhere are round.': 'Круглых домов\nтут на диво\nмного.',
    'Maybe the tree\nwas here before\nthe town.': 'Это дерево тут\nросло еще до\nсамого города!',
    'More houses.\nYes, I know...\nRed roof again.': 'И там дома.\nДа-да, знаю...\nОпять же крыша.',
    'Need a weapon?\nAsk the owner.\nFaster than': 'Нужно оружие?\nСпроси хозяина,\nне глазей зря!',
    'Never saw this\ntower in town.': 'Вон та башня. В\nсамом городе её\nне замечала.',
    'No matter how\nmany times I\nlook at the': 'Сколько в стену\nни смотри — ума\nне прибавится!',
    'No matter where\nI go, and stand\non the ground,': 'Куда ни пойди,\nнад головой\nвсегда небо!',
    'No one travels\nwith this damn\nheavy thing': 'С такой тяжелой\nдурой никто в\nпуть не пойдет.',
    'No wonder meals\ncost so much.': 'Не зря дерут\nвтридорога за\nобычную еду!',
    'Not as grand as\nthose on the\nmain street,': 'Не такой пышный\nкак на главной,\nно просторный.',
    'Not just some\nold lady.\nSome merchants': 'Она в магии\nразбирается не\nхуже чародеев!',
    "Nothing's more\nawkward than\npeeking in and": 'В окно глянешь,\nа там хозяин —\nвот неловкость!',
    "Oh! For a\ntavern keeper,\nhe's unusually": 'Хозяин-то для\nкабатчика прямо\nна диво худ!',
    'Older than me.\nStill pretty\nyoung, though.': 'Старше меня, но\nвсё равно еще\nмолодой парень.',
    'One leg\nsupports this\nwhole table.': 'Целый стол — и\nна единственной\nножке стоит!',
    'One plate, one\nbottle, one\nglass, and this': 'Тарелка, кубок,\nбутылка — места\nбольше и нет.',
    "One's clearly\nan old lady.\nNo clue about": 'Одна — старуха,\nа вторую со\nспины не видно.',
    'Only this door\nopens two ways.\nHow do they': 'Дверь на обе\nстороны. И как\nее запирают?',
    'Plain ground.\nNo bricks like\non main street.': 'Просто земля, а\nне брусчатка,\nкак на главной.',
    'Poor kid, stuck\nlistening to a\nparent ramble.': 'Бедный ребенок:\nслушает чужую\nболтовню.',
    'Pretty big for\nan ordinary\nhome.': 'Для обычных\nлюдей дом явно\nвеликоват.',
    "Put stairs in a\nbusy market and\nsomeone's bound": 'На рынке с этих\nлестниц точно\nкто-то упадет!',
    'Same as on the\nmain street...\nWalk in the': 'Опять у стенки!\nИди по центру\nвсей дороги!',
    'She fell for a\nbust potion,\nthen worked for': 'Купила зелье\nдля груди и тут\nпашет задарма!',
    'She has that\nmother-of-three\nlook.': 'Вид, словно у\nнее дома трое\nсорванцов.',
    'Shiny counter.\nAs it should.': 'Стойка блестит.\nВ гостинице так\nи должно быть!',
    'Sit here and\nmy butt gets\nwet.': 'Сяду тут — попу\nпромочу. Хотя\nфонтан сухой.',
    'Some kind of\nbox...': 'Какая-то\nкоробка...',
    "Some kind of\nstatue.\nGods aren't my": 'Статуя бога. Я\nв богах не\nразбираюсь.',
    "Someone's bound\nto trip on that\nstep.": 'Кто-то точно\nспоткнётся на\nэтой ступеньке!',
    'Stand on that,\nand you could\nclimb inside.': 'Встанешь сюда —\nи прямо в окно!\nкак вор.',
    'Still, twenty\npeople walking\nside by side': 'Идти толпой в\nдвадцать рядов\n— жутко было б.',
    "Stone floors\ndon't keep the\ntables fixed.": 'На камне столы\nкачаются, не\nтерплю такое!',
    'Suede boots.\nSuede is tanned\nleather.': 'Сапожки из\nзамши. А ведь\nзамша — кожа.',
    "Talk to them\nand I'm either\nignored, or": 'Заговоришь —\nили прогонят,\nили заболтают.',
    "That elf looks\nabout Gourry's\nage, but who": 'С виду ровесник\nГаури, а на\nделе кто знает?',
    'That flowerpot\ncould block you\ncoming down the': 'Спускаясь вниз,\nоб этот горшок\nлегко упасть.',
    "That house must\nsit higher up.\nI can't see": 'Дом на холме: и\nствола дерева\nне разглядеть.',
    'That old lady\nreally narrows\nmy view.': 'Из-за старухи\nмне пол-улицы\nне видать!',
    'That roof is\neasy to see\nfrom here. Not': 'Крыши отлично\nвидны, а толку\nсмотреть нет.',
    'That upper\nwindow is open.\nToss in a rock?': 'Вон то окно\nоткрыто. Кинуть\nтуда камешек?',
    "That window's\nlight gives the\nchurch a dreamy": 'Свет из окон\nсоздает в храме\nсказочный уют.',
    "That's one big\ndoor. Do elves\ngrow huge with": 'Огромная дверь!\nОни к старости\nрастут, что ли?',
    'The Royal\nLibrary has a\nlarge garden.': 'Сад библиотеки:\nи просторный, и\nочень красивый.',
    'The road by the\nchurch is\nspotless.': 'У церкви дорога\nпрямо до блеска\nвылизана!',
    'The sky looks\nso wide.': 'Небо отсюда\nкажется совсем\nбескрайним.',
    'The wall is\ncrumbling here\nand there.': 'Штукатурка со\nстены кое-где\nосыпалась.',
    "There's another\nmountain far\noff.": 'Вон там еще\nгора виднеется,\nдалеко-далеко.',
    "There's so much\nstuff, I can't\nwalk through": 'Столько хлама,\nчто без света и\nшею свернешь!',
    'These stairs\nlead into the\nhouse on the': 'По ступенькам\nвойдешь в дом\nсправа.',
    'These streets\nare so wide,\ntwenty people': 'Улица широкая:\nдвадцать людей\nв ряд пройдут.',
    "These streets\ncan't be old.\nThey're still": 'Улицы совсем\nновые: недавно\nпостроили.',
    'They could at\nleast clean.\nEven I wash my': 'Прибрались бы!\nЯ и то стираю в\nночлежках вещи.',
    "This junk is\nwhy the shop's\nso cramped.": 'Из-за хлама в\nэтой лавке и не\nразвернуться!',
    'Touch the rust:\nyour hand turns\nred. Know that?': 'От ржавчины вся\nрука порыжеет.\nЗнаешь об этом?',
    "Turn this rock\nover and you'll\nfind tiny bugs.": 'Сдвинь камень —\nтам наверняка\nкуча букашек!',
    "Ugh, it's made\nof wood...": 'Фу, она ещё и\nдеревянная...',
    'Up these stairs\nis the second\nfloor.': 'По лестнице\nподнимешься на\nвторой этаж.',
    'Watch this box.\nWith all this\nstuff lying': 'Осторожнее с\nэтой коробкой —\nшею свернешь!',
    "What's that?\nNot a\nchimney...": 'А это что? На\nтрубу совсем не\nпохоже...',
    'Why is she\nwearing boots?\nThick legs,': 'Чего в сапогах?\nНожки толстые,\nчто ли?',
    'Why not put the\ndoor and sign\non the square?': 'Вход и вывеску\nмогли вывести к\nсамой площади!',
    'With a window\nhere, passersby\ncould see in.': 'С улицы в такое\nокно всё видно\nкак на ладони!',
    "With long hair,\nit's hard to\ntell male and": 'С косами и не\nпоймешь: парень\nили девица.',
}


def validate_inspection_text(
    key: str, text: str, has_eng_dots: bool, charmap: dict[str, int]
) -> list[str]:
    """Validate a Russian string against all PS1 constraints."""
    errors = []
    normalized = unicodedata.normalize("NFC", text)
    if text != normalized:
        errors.append("Not in NFC Unicode normalization")

    lines = text.split("\n")
    if not (1 <= len(lines) <= 3):
        errors.append(f"Line count {len(lines)} not in 1..3")

    for idx, line in enumerate(lines, 1):
        if len(line) > 15:
            errors.append(f"Line {idx} exceeds 15 characters ({len(line)} chars: {line!r})")
        for ch in line:
            if ch not in charmap and ch not in ("\n", "\r"):
                errors.append(f"Unsupported character {ch!r} ({ord(ch):#06x}) in line {idx}")

    if not has_eng_dots and text.rstrip().endswith("..."):
        errors.append("Unintended trailing '...' found")

    wrapped = wrap_dialogue(
        text,
        allow_continuation=False,
        max_chars_per_line=15,
        max_lines_per_page=3,
    )
    if wrapped != text:
        errors.append(
            f"Wrapper stability failure:\nExpected:\n{text}\nGot:\n{wrapped}"
        )

    return errors


def update_build_translations_source(
    build_py_path: Path, mappings: dict[str, str], dry_run: bool = False
) -> int:
    """Update RAW_INSPECTION_TRANSLATIONS in build_inspection_translations.py to keep pipeline idempotent."""
    content = build_py_path.read_text(encoding="utf-8")
    
    # Import RAW_INSPECTION_TRANSLATIONS dictionary from build_inspection_translations
    from tools.build_inspection_translations import RAW_INSPECTION_TRANSLATIONS
    
    updated_raw = dict(RAW_INSPECTION_TRANSLATIONS)
    for k, v in mappings.items():
        updated_raw[k] = v
        
    # Reformat RAW_INSPECTION_TRANSLATIONS definition
    dict_lines = ["RAW_INSPECTION_TRANSLATIONS: dict[str, str] = {"]
    first = True
    for k, v in updated_raw.items():
        prefix = " " if not first else ""
        dict_lines.append(f"{prefix}{repr(k)}: {repr(v)},")
        first = False
    dict_lines[-1] = dict_lines[-1].rstrip(",") + "}"
    new_dict_code = "\n".join(dict_lines)
    
    pattern = re.compile(
        r"RAW_INSPECTION_TRANSLATIONS: dict\[str, str\] = \{.*?\n(?=def wrap_inspection_string)",
        re.DOTALL,
    )
    
    match = pattern.search(content)
    if not match:
        raise ValueError("Could not find RAW_INSPECTION_TRANSLATIONS block in build_inspection_translations.py")
        
    new_content = content[:match.start()] + new_dict_code + "\n\n\n" + content[match.end():]
    
    if not dry_run:
        build_py_path.write_text(new_content, encoding="utf-8")
    return len(mappings)


def unabridge_catalog(
    catalog_path: Path = CATALOG_PATH,
    build_py_path: Path = BUILD_TRANSLATIONS_PATH,
    dry_run: bool = False,
    verbose: bool = True,
) -> tuple[int, int]:
    """Apply unabridged translations to catalog and build source, returning (updated_count, total_count)."""
    catalog: dict[str, dict[str, Any]] = json.loads(
        catalog_path.read_text(encoding="utf-8")
    )
    
    # Pre-validation of all 143 mappings
    all_errors = {}
    for eng_text, unabridged_ru in UNABRIDGED_MAPPINGS.items():
        if eng_text not in catalog:
            all_errors[eng_text] = [f"Key not found in catalog: {eng_text!r}"]
            continue
        has_eng_dots = "..." in eng_text
        errs = validate_inspection_text(eng_text, unabridged_ru, has_eng_dots, DEFAULT_CHARMAP)
        if errs:
            all_errors[eng_text] = errs
            
    if all_errors:
        err_msg = [f"Validation failed for {len(all_errors)} unabridged entries:"]
        for k, errs in all_errors.items():
            err_msg.append(f"  {k!r}: " + "; ".join(errs))
        raise ValueError("\n".join(err_msg))

    updated_count = 0
    for eng_text, unabridged_ru in UNABRIDGED_MAPPINGS.items():
        catalog[eng_text]["russian"] = unabridged_ru
        updated_count += 1

    # Post-validation across entire catalog (all 734 entries)
    catalog_errors = []
    line_counts = {}
    max_line_len = 0
    mechanical_dots_count = 0

    for eng_text, entry in catalog.items():
        ru = entry.get("russian", "")
        has_eng_dots = "..." in eng_text
        errs = validate_inspection_text(eng_text, ru, has_eng_dots, DEFAULT_CHARMAP)
        if errs:
            catalog_errors.append(f"{eng_text!r}: " + "; ".join(errs))
        
        lines = ru.split("\n")
        line_counts[len(lines)] = line_counts.get(len(lines), 0) + 1
        for line in lines:
            max_line_len = max(max_line_len, len(line))
            if not has_eng_dots and line.endswith("..."):
                mechanical_dots_count += 1

    if catalog_errors:
        raise ValueError(
            f"Catalog integrity errors in {len(catalog_errors)} entries:\n"
            + "\n".join(catalog_errors[:10])
        )

    if verbose:
        print(f"Successfully re-authored {updated_count} truncated inspection strings.")
        print(f"Entire catalog ({len(catalog)} entries) verified:")
        print(f"  - 0 lines > 15 characters (max line length: {max_line_len})")
        print(f"  - 0 strings with line count outside 1..3: {sorted(line_counts.items())}")
        print(f"  - 0 mechanical trailing ellipses (found: {mechanical_dots_count})")
        print(f"  - 100% Cyrillic charmap validity")

    if not dry_run:
        catalog_path.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        update_build_translations_source(build_py_path, UNABRIDGED_MAPPINGS, dry_run=False)
        if verbose:
            print(f"Saved updated catalog to {catalog_path}")
            print(f"Updated build source at {build_py_path}")

    return updated_count, len(catalog)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unabridge all truncated room inspection strings into complete sentences."
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=CATALOG_PATH,
        help="Path to room_inspection_ru.json",
    )
    parser.add_argument(
        "--build-py",
        type=Path,
        default=BUILD_TRANSLATIONS_PATH,
        help="Path to build_inspection_translations.py",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without modifying files on disk",
    )
    args = parser.parse_args()

    unabridge_catalog(
        catalog_path=args.catalog,
        build_py_path=args.build_py,
        dry_run=args.dry_run,
        verbose=True,
    )


if __name__ == "__main__":
    main()
