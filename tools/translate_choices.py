"""Translate dialogue choices and tavern turns in dialogue.po to eliminate mojibake."""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

# Ensure patch_repo is available on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))

from localization.po import PoEntry, read_po, write_po
from localization.script import parse_target

# Map of Japanese choice menu texts to natural Russian translations
# Every option line complies with hardware layout: <= 15 chars/line, <= 3 lines total.
CHOICE_TRANSLATIONS: dict[str, str] = {
    "あたりを調べる\n1階にもどる": "Осмотреться\nНа 1-й этаж",
    "くわしい事情を聞く\n話をやめる": "Расспросить\nЗакончить",
    "くわしく聞いてみる\n話をやめる": "Расспросить\nЗакончить",
    "ことわる\nお礼だけもらう\nラ-クをひきわたす": "Отказаться\nВзять награду\nОтдать Ларка",
    "すすむ\nもどる": "Вперёд\nНазад",
    "すすむ\nもどる\n外に出る": "Вперёд\nНазад\nВыйти наружу",
    'そうだけど""\nちがうわよ.': "Да, верно.\nВовсе нет.",
    "そうだと答える.\nちがうと答える.\nなぐり倒す.": "Ответить «да»\nОтветить «нет»\nВрезать!",
    "とおまわしに聞いてみる\nストレ-トに聞いてみる": "Издалека\nСпросить прямо",
    "とりあえず行ってみる\n忘れてしまう": "Сходить туда\nЗабыть об этом",
    "ほんとにかまわない\nやっぱり返す": "Оставить себе\nВсё же вернуть",
    "みんなの言う事を聞く\nこのまま町の外へ出る": "Послушать всех\nПокинуть город",
    "もちろんネコババする\nやっぱり返す": "Присвоить!\nВернуть назад",
    "もちろん行かないつもり\n行ってみる": "Не пойду!\nСхожу проверю",
    "やってみる\nやめておく": "Сыграть\nОтказаться",
    "やめさせる.\nナ-ガをけしかける.": "Остановить.\nНатравить Нагу.",
    "イゼルセンに戻る\nフリ-グラントに行く": "В Изельсен\nВ Фригрант",
    "ガレフの事を聞いてみる\n世間話をしてみる\n話をやめる": "О Галефе\nПоболтать\nЗакончить",
    "ガレフの話を聞いてみる\n世間話をしてみる\n話をやめる": "О Галефе\nПоболтать\nЗакончить",
    "キュ-ザック方面のウワサ\nラルティ-グ方面のウワサ": "О Кьюзаке\nО Ральтиге",
    "ゴ-ストさわぎの話を聞いてみる\nガレフの話を聞いてみる\n話をやめる": "О призраках\nО Галефе\nЗакончить",
    "シルフィ-ルの説明を見る\n説明を見るのはやめる": "О Сильфиль\nНе смотреть",
    "セイル-ンに行くとこ\nセイル-ンから来たとこ": "Идём в Сейрун\nИдём из Сейруна",
    "セイル-ンへ行く\nキュ-ザックへもどる": "В Сейрун\nВ Кьюзак",
    "ゼルガディスの説明を見る\n説明は見ない": "О Зельгадисе\nНе смотреть",
    "ゼルガディスの説明を見る\n説明を見るのはやめる": "О Зельгадисе\nНе смотреть",
    "ディルブランドでふきとばす\n身ぐるみはがしてみる\nきぜつしてるやつをしばきたおす": "Дилл Бранд!\nОбобрать\nДобить!",
    "フリ-グラントへ行く\nイゼルセンへ行く": "В Фриграント\nВ Изельсен",
    "ル-ルを聞く\n勝負をはじめる\n勝負をやめる": "Правила\nНачать игру\nЗакончить",
    "レザリアムの説明を見る\n見ないなんて言わないでheart": "О Лезариуме\nНе смотреть♥",
    "世間話をしてみる\nガレフの話を聞いてみる\n話をやめる": "Поболтать\nО Галефе\nЗакончить",
    "世間話をしてみる\nゴ-ストさわぎの犯人をつきとめる\n話をやめる": "Поболтать\nО призраках\nЗакончить",
    "世間話をしてみる\n話をやめる": "Поболтать.\nЗакончить.",
    "世間話をする\nガレフの話を聞いてみる\n話をやめる": "Поболтать\nО Галефе\nЗакончить",
    "世間話をする\n盗賊の話を聞いてみる\n話をやめる": "Поболтать\nО бандитах\nЗакончить",
    "世間話をする\n話をやめる": "Поболтать\nЗакончить",
    "世間話をする\n魔道士協会の場所を聞く\n話をやめる": "Поболтать\nГильдия магов\nЗакончить",
    "中に入る\nフリ-グラントへ行く\nイゼルセンへ行く": "Войти внутрь\nВ Фриграント\nВ Изельセン -> В Изельсен",
    "中庭に行ってみる\n出口にもどる": "Во двор\nК выходу",
    "事情を説明する\n事情を説明しない": "Всё объяснить\nПромолчать",
    "他の話を聞いてみる\n話をやめる": "О другом\nЗакончить",
    "別にかまわない\nやっぱし行ってみる": "Не важно\nВсё же пойти",
    "前にすすむ\nもどる": "Вперёд\nНазад",
    "前の分かれ道までもどる\nいちど外に出る": "К развилке\nВыйти наружу",
    "勝負をはじめる\n勝負をやめる": "Начать игру\nОтказаться",
    "右に行く\n左に行く": "Направо\nНалево",
    "宿屋協会キャンペ-ンの説明を見る\n説明は見ない": "Об акции\nНе смотреть",
    "左に行く\n右に行く\nもどる": "Налево\nНаправо\nНазад",
    "広場に戻る\n村を出る": "На площадь\nПокинуть село",
    "当然,本街道よね.\nいいえ,裏街道にするわ.": "По тракту\nВ объезд",
    "持っている\n持っていない": "Есть\nНет",
    "最近かわった事がないか聞いてみる\n話をやめる": "Что нового?\nЗакончить",
    "最近変わった事がないか聞いてみる\n世間話をしてみる\n話をやめる": "Что нового?\nПоболтать\nЗакончить",
    "森の中に入る\n中に入らない": "Войти в лес\nНе входить",
    "森の入り口に行く\nキュ-ザックにもどる": "Ко входу в лес\nВ Кьюзак",
    "洞穴の中に入る\nやめる": "Войти в пещеру\nОтказаться",
    "犯人をつきとめる\n話をきいたからそれでいい": "Найти виновных\nХватит и этого",
    "理由を聞いてみる\n聞かないで帰る": "Узнать причину\nУйти",
    "町を見てまわる\nさっさと町を出る": "Осмотреть город\nПокинуть город",
    "盗賊の話をきく\n世間話をする\n話をやめる": "О бандитах\nПоболтать\nЗакончить",
    "盗賊を倒しに行く.\nそのまま寝る": "На бандитов!\nЛечь спать",
    "胸の大きくなる薬が欲しい\n胸の大きくなる薬が欲しい\n胸の大きくなる薬が欲しい": "Зелье для бюста\nЗелье для бюста\nЗелье для бюста",
    "行ってみる\nほんとに行かない": "Пойти туда\nТочно не пойду",
    "表通りに行く\n裏通りに行く": "На главную\nВ закоулки",
    "裏口のほうから出る\n出口にもどる": "Чёрный ход\nК выходу",
    "詳しく聞いてみる\n知らないと答える": "Расспросить\n«Не знаю»",
    "詳しく聞いてみる\n話をやめる": "Расспросить\nЗакончить",
    "詳しく聞いてみる.\n聞くのをやめる.": "Расспросить.\nХватит.",
    "説明を見る\n説明を見ない": "Посмотреть\nсправку\nНе смотреть",
    "進んでみる\n戻ってみる": "Вперёд\nНазад",
    "道具を買いにきた\n世間話をしにきた": "Купить вещи\nПоболтать",
    "道具屋に入る\n入らない": "В лавку\nНе входить",
    "首飾りにまつわる伝説の説明を見る\n別に見たくない.": "Легенда\nНе смотреть",
    "首飾りの説明をみる\n説明を見ない": "Об ожерелье\nНе смотреть",
    "高そうな像を見せる\nだまって話をきりあげる": "Показать статую\nПромолчать",
    "魔法で穴をあけてみる\nもどる": "Пробить магией\nНазад",
    "魔道士協会に行った後にする\n今から行く\n行かない": "После Гильдии\nПойти сейчас\nНе ходить",
    "魔道士協会の場所を聞く\n話をやめる": "Гильдия магов\nЗакончить",
    "魔道士協会の後にする\n今から行く": "После Гильдии\nПойти сейчас",
}

# Fix typo if any in CHOICE_TRANSLATIONS
CHOICE_TRANSLATIONS["中に入る\nフリ-グラントへ行く\nイゼルセンへ行く"] = "Войти внутрь\nВ Фригрант\nВ Изельсен"

# Map of context -> Russian translation for all remaining Scene 03B entries
TRANSLATIONS_03B: dict[str, str] = {
    "dialogue/03B/E01A/001": "Показать\nуправление?",
    "dialogue/03B/E01B/004": "Что нам делать\nна главной?",
    "dialogue/03B/E01B/008": "А как же демон\nна окраине?",
    "dialogue/03B/E01B/009": "Я же сказала:\nне обращай\nвнимания.",
    "dialogue/03B/E01B/011": "Э? У тебя и\nвпрямь ни гроша\nв кармане?..",
    "dialogue/03B/E01B/014": "Ну вот теперь\nмы поспим.",
    "dialogue/03B/E01B/015": "Не останемся?",
    "dialogue/03B/E01B/016": "Зачем мы здесь?",
    "dialogue/03B/E01B/022": "Идём, Гаури.",
    "dialogue/03B/E01B/023": "А, ага.",
    "dialogue/03B/E01B/032": "Надоело тут\nкруги нарезать.",
    "dialogue/03B/E01B/033": "Лина, давай уже\nрешим, что нам\nделать?",
    "dialogue/03B/E01B/034": "Д-да, пожалуй.",
    "dialogue/03B/E01B/037": "Давно хотел\nспросить...",
    "dialogue/03B/E01B/038": "О чём?",
    "dialogue/03B/E01B/039": "Зачем мы вообще\nбродим по\nгороду?",
    "dialogue/03B/E01B/040": "Да без особой\nпричины...",
    "dialogue/03B/E01B/041": "Вот как...\nЗначит, просто\nтак.",
    "dialogue/03B/E01B/048": "Мы разве не\nуходим отсюда?",
    "dialogue/03B/E01B/074": "Вон тот парень\nсказал, что\nвидел эльфа...",
    "dialogue/03B/E01B/075": "Сотни лет тут\nживу, а эльфов\nне видывал.",
    "dialogue/03B/E01B/076": "Вроде работу\nискал.",
    "dialogue/03B/E01B/077": "Есть работа?",
    "dialogue/03B/E01B/078": "На западе есть\nгород Баркленд,\nсходите туда.",
    "dialogue/03B/E01B/079": "Там город\nпокрупнее\nнашего.",
    "dialogue/03B/E01B/080": "До Баркленда на\nзапад меньше\nдня пути.",
    "dialogue/03B/E01B/081": "Больше мне\nнечего сказать.",
    "dialogue/03B/E01B/082": "Чего только не\nбывает.",
    "dialogue/03B/E01B/084": "Пошли.",
    "dialogue/03B/E01B/086": "Ясное дело, на\nокраину.",
    "dialogue/03B/E01B/087": "Зачем?",
    "dialogue/03B/E01B/088": "Поймать эльфа и\nпродать его!",
    "dialogue/03B/E01B/089": "Послушай меня,\nНага...",
    "dialogue/03B/E01B/102": "Хм, больше мне\nнечего вам\nрассказать.",
    "dialogue/03B/E01B/103": "А, добро\nпожаловать!",
    "dialogue/03B/E01B/107": "Я занят,\nзайдите позже.",
    "dialogue/03B/E01B/147": "Баркленд город\nбольшой, что-то\nтам найдётся.",
    "dialogue/03B/E01B/148": "Но у Баркленда\nбродят бандиты,\nбудьте начеку.",
    "dialogue/03B/E01B/172": "............",
    "dialogue/03B/E01B/181": "О-хо-хо-хо-хо!\nЯ думала, ты\nумнее...",
    "dialogue/03B/E01B/187": "Я-я такое\nговорила? Никто\nне помнит!",
    "dialogue/03B/E01B/189": "Ну-у, это... я\nпросто так...",
    "dialogue/03B/E01B/191": "Хе-хе, то-то!\nА теперь счёт\nза выпивку...",
    "dialogue/03B/E01B/195": "Заказал —\nплати! Я же\nучила, забыл?",
    "dialogue/03B/E01B/202": "Стресс Лины\nупал. Бодрость\nвыросла!",
    "dialogue/03B/E01B/203": "Гаури устал.\nСытость Гаури\nупала!",
    "dialogue/03B/E01B/204": "Нага устала.\nНо ничего не\nизменилось.",
    "dialogue/03B/E01B/206": "А, это вы!\nСпасибо за\nпомощь тогда.",
    "dialogue/03B/E01B/207": "Кстати, вы в\nБаркленд ещё не\nидёте?",
    "dialogue/03B/E01B/233": "В таверну?\nНочью темно,\nбудьте начеку.",
    "dialogue/03B/E01B/234": "С возвращением!\nУже поздно,\nпора спать.",
    "dialogue/03B/E01B/235": "Доброе утро!\nОтличный денёк\nвыдался.",
    "dialogue/03B/E01B/236": "Кстати, сколько\nвы пробудете\nв этом городе?",
    "dialogue/03B/E01B/237": "Хозяин, обед А\nна десятерых!",
    "dialogue/03B/E01B/238": "А мне обед Б\nна десятерых!",
    "dialogue/03B/E01B/239": "И мне тоже обед\nБ на десятерых!",
    "dialogue/03B/E01B/240": "Бодрость Лины\nвыросла!",
    "dialogue/03B/E01B/241": "Гаури наелся\nдо отвала!",
    "dialogue/03B/E01B/242": "Нага довольна.",
    "dialogue/03B/E01B/246": "Бодрость Лины\nвыросла!",
    "dialogue/03B/E01B/247": "С Гаури ничего\nне произошло.",
    "dialogue/03B/E01B/248": "С Нагой ничего\nне произошло.",
    "dialogue/03B/E01B/254": "Бодрость Лины\nвыросла!",
    "dialogue/03B/E01B/255": "Гаури наелся\nдо отвала!",
    "dialogue/03B/E01B/256": "Нага напилась.",
    "dialogue/03B/E01B/260": "Бодрость Лины\nвыросла!",
    "dialogue/03B/E01B/261": "С Гаури ничего\nне произошло.",
    "dialogue/03B/E01B/262": "Нага напилась.",
    "dialogue/03B/E01B/263": "Что ж, пора\nотдохнуть.",
    "dialogue/03B/E01B/268": "Что ж, пора\nотдохнуть.",
    "dialogue/03B/E01B/269": "Ага, доброй\nночи...",
    "dialogue/03B/E01B/270": "О-хо-хо, тогда\nдо завтра!",
    "dialogue/03B/E01B/274": "Фриз Эрроу!",
    "dialogue/03B/E01B/275": "Лина, давай уже\nрешим, что\nделать?",
    "dialogue/03B/E01B/276": "Мне-то всё\nравно.",
    "dialogue/03B/E01B/277": "Да, пора бы\nопределиться.",
    "dialogue/03B/E01B/278": "Эй, хорош уже!",
    "dialogue/03B/E01B/279": "Пф, салага!\nВ таких делах\nтащат силой!",
    "dialogue/03B/E01B/280": "В гостиницу не\nвернёмся! Пора\nвсё решить!",
    "dialogue/03B/E01B/281": "Нага, ты что,\nза нами идёшь?",
    "dialogue/03B/E01B/282": "Не смеши меня!\nКто за тобой\nидти станет!",
    "dialogue/03B/E01B/283": "Я запомню эти\nслова!",
    "dialogue/03B/E01B/284": "Ой, подумаешь,\nслово за слово!",
    "dialogue/03B/E01B/285": "Да хватит уже!",
    "dialogue/03B/E01B/286": "Пф, я вас не\nпущу!",
    "dialogue/03B/E01B/324": "Ой... Нага\nисчезла! Дурное\nпредчувствие...",
}

# Additional dialogue turns that were multiline without speaker
EXTRA_TRANSLATIONS: dict[str, str] = {
    "dialogue/03C/E079/281": "Среди бандитов\nстрого-настрого\nзапрещено...",
    "dialogue/03E/E19C/336": "Он перепугался,\nа прохожий его\nвыручил.",
    "dialogue/03E/E19C/339": "Слышал, на\nсевере орудует\nшайка бандитов.",
    "dialogue/040/U040-S223/000": "Путь в Сейрун\nлежит через\nФригрант.",
    "dialogue/040/U040-S224/000": "Ищете Галефа?\nСпросите на\nзаставе.",
    "dialogue/041/U041-S104/000": "Я присматривал,\nно Галефа не\nбыло.",
    "dialogue/042/U042-S073/000": "Нашим гостям мы\nвсегда дарим\nжетон.",
}


def normalize_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r", ""))


def translate_catalog(po_path: Path) -> tuple[int, int, int]:
    """Translate choices and 03B dialogue in the given PO catalog.

    Returns:
        (total_entries, newly_translated, remaining_untranslated)
    """
    entries = read_po(po_path)
    new_entries: list[PoEntry] = []
    translated_count = 0

    for entry in entries:
        if entry.translation:
            new_entries.append(entry)
            continue

        target_text: str | None = None
        # Priority 1: Scene 03B context mapping
        if entry.context in TRANSLATIONS_03B:
            target_text = TRANSLATIONS_03B[entry.context]
        # Priority 2: Extra context mapping
        elif entry.context in EXTRA_TRANSLATIONS:
            target_text = EXTRA_TRANSLATIONS[entry.context]
        # Priority 3: Choice source mapping across catalog
        elif entry.source in CHOICE_TRANSLATIONS:
            target_text = CHOICE_TRANSLATIONS[entry.source]

        if target_text is not None:
            # Validate layout constraints
            is_ff = any("This FF segment cannot add another page" in c for c in entry.comments)
            delimiter = 0x00FF if is_ff else 0x00FD
            target_text = normalize_nfc(target_text)
            parse_target(target_text, delimiter, entry.context)

            new_entries.append(
                PoEntry(
                    context=entry.context,
                    source=entry.source,
                    translation=target_text,
                    comments=entry.comments,
                )
            )
            translated_count += 1
        else:
            new_entries.append(entry)

    write_po(po_path, new_entries, language="ru")

    total = len(new_entries)
    remaining_untranslated = sum(1 for e in new_entries if not e.translation)
    return total, translated_count, remaining_untranslated


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate choices and tavern turns in dialogue.po.")
    parser.add_argument(
        "--po",
        type=Path,
        default=PATCH_REPO / "localization-work" / "ru" / "dialogue.po",
        help="Path to dialogue.po",
    )
    args = parser.parse_args()

    po_path = args.po.resolve()
    if not po_path.exists():
        print(f"Error: {po_path} does not exist.", file=sys.stderr)
        return 1

    print(f"Scanning and translating: {po_path}")
    total, newly_translated, remaining = translate_catalog(po_path)
    print(
        f"Done: {newly_translated} entries newly translated. "
        f"Total: {total}, Remaining untranslated: {remaining}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
