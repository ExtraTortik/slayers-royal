#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BIN_ORIG="$SCRIPT_DIR/downloads/sr.bin"
RU_DIR="$SCRIPT_DIR/localization-output/ru"
RU_BIN="$RU_DIR/slayers_royal_ru.bin"
RU_CUE="$RU_DIR/slayers_royal_ru.cue"
INSPECTION_JSON="$SCRIPT_DIR/translations/room_inspection_ru.json"
ROOM_NAMES_JSON="$SCRIPT_DIR/translations/room_names_ru.json"
CARDS_JSON="$SCRIPT_DIR/translations/lore_cards_ru.json"
COMBAT_JSON="$SCRIPT_DIR/translations/combat_ru.json"
COMBAT_DIALOGUES_JSON="$SCRIPT_DIR/translations/combat_dialogues_ru.json"
SPELLS_JSON="$SCRIPT_DIR/translations/spells_ru.json"
MAP_JSON="$SCRIPT_DIR/translations/world_map_ru.json"
BANNERS_JSON="$SCRIPT_DIR/translations/location_banners_ru.json"
TOWN_SERVICES_JSON="$SCRIPT_DIR/translations/town_services_ru.json"
SHOP_DIALOGUES_JSON="$SCRIPT_DIR/translations/shop_dialogues_ru.json"
MINIGAMES_JSON="$SCRIPT_DIR/translations/minigames_ru.json"
MINIGAMES_MENU_JSON="$SCRIPT_DIR/translations/minigames_menu_ru.json"
STORY_JSON="$SCRIPT_DIR/translations/story_dialogues_ru.json"
BONUS_MENU_JSON="$SCRIPT_DIR/translations/bonus_menu_ru.json"
INDEX_JSON="$SCRIPT_DIR/translations/translations_index.json"
TOWN_MAPS_JSON="$SCRIPT_DIR/translations/town_maps_ru.json"
TOWN_MAPS_DIR="$SCRIPT_DIR/data/custom_town_maps"
CUSTOM_HUD_DIR="$SCRIPT_DIR/data/custom_hud_textures"
CUSTOM_SCREENS_DIR="$SCRIPT_DIR/data/custom_screens"
EXTRA_SCREENS_DIR="$SCRIPT_DIR/data/extra_screens"
PATCH_REPO_DIR="$SCRIPT_DIR/patch_repo"

echo "==========================================================="
echo "   Slayers Royal (PS1) — Сборщик локализации"
echo "==========================================================="

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    echo "Использование: ./build.sh [опция]"
    echo ""
    echo "Опции:"
    echo "  (без опций)  Полная сборка: сюжет + FMV + 149 комнат + карточки + карта + плашки + боевой режим + городские службы + мини-игры и викторина (~38 сек)"
    echo "  --quick, -q  Быстрая сборка: обновить ТОЛЬКО описания предметов из"
    echo "               translations/room_inspection_ru.json (~1.5 сек)"
    echo "  --story, --dialogues Быстрая сборка: обновить сюжетные диалоги и базовый образ (~12 сек)"
    echo "  --movies, --fmv  Внедрить видеоролики с русскими субтитрами из build/movies (~3 сек)"
    echo "  --map        Обновить ТОЛЬКО названия локаций на карте мира"
    echo "  --banners    Обновить ТОЛЬКО графические плашки-баннеры локаций"
    echo "  --status-ui, --tabs  Обновить атлас меню персонажей из data/preview_basyog_162_ru.png"
    echo "  --cards      Обновить ТОЛЬКО энциклопедические карточки персонажей"
    echo "  --combat, --combat-dialogues  Обновить боевые диалоги и заклинания"
    echo "  --spells     Внедрить заклинания и боевое меню магии (PROG.UNT 0x007, 325..443)"
    echo "  --services, --town  Обновить городские службы, магазины и меню из translations/town_services_ru.json"
    echo "  --shops, --shop-dialogues  Обновить диалоги и меню магазинов из translations/shop_dialogues_ru.json"
    echo "  --minigames, --quiz Обновить правила 5 мини-игр, викторину и меню выбора мини-игр"
    echo "  --bonus-menu, --title-menu Обновить меню бонусов (OPT.UNT 143..146) и главное меню"
    echo "  --town-maps, --maps  Обновить иллюстрации карт городов из data/custom_town_maps/"
    echo "  --hud, --e8          Обновить атлас интерфейса/HUD (PROG.UNT 0x008, 74 380) из data/custom_hud_textures/"
    echo "  --title-logo, --logo Внедрить русский логотип «РУБАКИ КОРОЛЕВСКИЕ» титульного экрана"
    echo "  --custom-screens, --screens Обновить пользовательские экраны (Game Over, Ход, Старт, Бесконечная игра) из data/custom_screens/"
    echo "  --extra-screens Внедрить 13 дополнительных экранов/текстур (OPT 137..232, OPTCINE 01, PROG 54..57)"
    echo "  --validate   Проверить каталоги диалогов, комнат, карты, плашек, служб, мини-игр, викторины и меню на ошибки"
    echo "  --help, -h   Показать эту справку"
    exit 0
fi

if [[ "$1" == "--validate" ]]; then
    echo "[*] Валидация каталога сюжетных диалогов (JSON)..."
    python3 "$SCRIPT_DIR/tools/sync_story_dialogues.py" --validate
    echo "[*] Валидация каталога диалогов..."
    python3 "$PATCH_REPO_DIR/localize.py" validate \
        --bin "$BIN_ORIG" \
        --workspace "$PATCH_REPO_DIR/localization-work/ru" \
        --locale ru
    echo "[*] Валидация каталога комнат..."
    echo "[*] Валидация каталога названий комнат и локаций..."
    python3 -m pytest tools/test_room_names.py -q
    python3 -m pytest tools/test_inspection_translations.py -q
    echo "[✓] Все файлы перевода корректны и не содержат ошибок!"
    echo "[*] Валидация боевого режима..."
    python3 "$SCRIPT_DIR/tools/combat_text.py" --verify
    echo "[*] Валидация боевых диалогов..."
    python3 "$SCRIPT_DIR/tools/patch_combat_dialogues.py" --verify --bin "$RU_BIN"
    python3 -m pytest tools/test_combat_font_and_text.py -q
    echo "[*] Валидация заклинаний и боевого меню магии (PROG.UNT 0x007, 325..443)..."
    python3 "$SCRIPT_DIR/tools/patch_spells.py" --verify --bin "$RU_BIN"
    python3 -m pytest tools/test_patch_spells.py -q
    echo "[*] Валидация названий карты мира..."
    python3 "$SCRIPT_DIR/tools/patch_world_map.py" --verify
    echo "[*] Валидация графических плашек локаций..."
    python3 "$SCRIPT_DIR/tools/patch_location_banners.py" --verify
    if [[ -f "$SCRIPT_DIR/data/preview_basyog_162_ru.png" ]]; then
        echo "[*] Валидация атласа меню персонажей..."
        python3 "$SCRIPT_DIR/tools/patch_basyog_162.py" --verify --bin "$RU_BIN"
    fi
    echo "[*] Валидация городских служб, меню и валюты..."
    python3 "$SCRIPT_DIR/tools/patch_town_services.py" --verify
    echo "[*] Валидация мини-игр и викторины..."
    python3 "$SCRIPT_DIR/tools/patch_minigames.py" --verify
    echo "[*] Валидация меню выбора мини-игр..."
    python3 "$SCRIPT_DIR/tools/patch_minigames_menu.py" --verify
    echo "[*] Валидация меню бонусов и главного меню..."
    python3 "$SCRIPT_DIR/tools/patch_bonus_menu.py" --verify --bin "$RU_BIN"
    echo "[*] Валидация карт городов..."
    python3 "$SCRIPT_DIR/tools/patch_town_maps.py" --verify --bin "$RU_BIN"
    echo "[*] Валидация логотипа титульного экрана..."
    python3 "$SCRIPT_DIR/tools/patch_title_logo.py" --verify --bin "$RU_BIN"
    echo "[*] Валидация атласа интерфейса/HUD (PROG.UNT 0x008)..."
    python3 "$SCRIPT_DIR/tools/patch_e8_textures.py" --verify --bin "$RU_BIN"
    echo "[*] Валидация пользовательских экранов (OPT 203, 221, 225; PROG 323)..."
    python3 "$SCRIPT_DIR/tools/patch_custom_screens.py" --verify --bin "$RU_BIN"
    python3 -m pytest tools/test_patch_custom_screens.py -q
    python3 -m pytest tools/test_patch_bonus_menu.py -q
    python3 -m pytest tools/test_patch_e8_textures.py -q
    echo "[*] Валидация 13 дополнительных экранов/текстур (OPT 137..232, OPTCINE 01, PROG 54..57)..."
    python3 "$SCRIPT_DIR/tools/patch_extra_screens.py" --verify --bin "$RU_BIN"
    python3 -m pytest tools/test_patch_extra_screens.py -q
    exit 0
fi

if [[ "$1" == "--story" || "$1" == "--dialogues" ]]; then
    echo "==========================================================="
    echo "[1/2] Синхронизация и сборка сюжетных диалогов..."
    echo "==========================================================="
    if [[ ! -f "$BIN_ORIG" ]]; then
        echo "Ошибка: оригинальный образ $BIN_ORIG не найден!" >&2
        exit 1
    fi
    mkdir -p "$RU_DIR"
    python3 "$SCRIPT_DIR/tools/sync_story_dialogues.py" --sync-if-newer
    python3 "$PATCH_REPO_DIR/localize.py" build \
        --bin "$BIN_ORIG" \
        --workspace "$PATCH_REPO_DIR/localization-work/ru" \
        --locale ru \
        --output-dir "$RU_DIR" \
        --force
    echo "Внедрение видеороликов с русскими субтитрами (build/movies/MOVIE.STR)..."
    python3 "$SCRIPT_DIR/tools/fmv_pipeline.py" \
        --inject-disc "$RU_BIN" \
        --movies-dir "$SCRIPT_DIR/build/movies"

    echo "==========================================================="
    echo "[2/2] Накатывание сопутствующих патчей (инспекция, карты, плашки, бой, службы, мини-игры)..."
    echo "==========================================================="
    python3 "$SCRIPT_DIR/tools/patch_inspection.py" --bin "$RU_BIN" --translations "$INSPECTION_JSON" --room-names "$ROOM_NAMES_JSON" --all-rooms
    python3 "$SCRIPT_DIR/tools/patch_lore_cards.py" --disc "$RU_BIN" --cards "$CARDS_JSON"
    python3 "$SCRIPT_DIR/tools/patch_world_map.py" --bin "$RU_BIN" --catalog "$MAP_JSON"
    python3 "$SCRIPT_DIR/tools/patch_location_banners.py" --bin "$RU_BIN" --catalog "$BANNERS_JSON"
    if [[ -f "$SCRIPT_DIR/data/preview_basyog_162_ru.png" ]]; then
        python3 "$SCRIPT_DIR/tools/patch_basyog_162.py" --bin "$RU_BIN"
    fi
    python3 "$SCRIPT_DIR/tools/patch_combat_dialogues.py" --bin "$RU_BIN" --catalog "$COMBAT_DIALOGUES_JSON"
    python3 "$SCRIPT_DIR/tools/patch_town_services.py" --bin "$RU_BIN" --catalog "$TOWN_SERVICES_JSON" --shop-catalog "$SHOP_DIALOGUES_JSON"
    python3 "$SCRIPT_DIR/tools/patch_minigames.py" --bin "$RU_BIN" --catalog "$MINIGAMES_JSON"
    python3 "$SCRIPT_DIR/tools/patch_minigames_menu.py" --bin "$RU_BIN"
    python3 "$SCRIPT_DIR/tools/patch_bonus_menu.py" --bin "$RU_BIN" --catalog "$BONUS_MENU_JSON"
    if compgen -G "$TOWN_MAPS_DIR/*.png" > /dev/null 2>&1 || compgen -G "$TOWN_MAPS_DIR/*.PNG" > /dev/null 2>&1; then
        python3 "$SCRIPT_DIR/tools/patch_town_maps.py" --bin "$RU_BIN" --maps-dir "$TOWN_MAPS_DIR"
    fi
    if [[ -d "$CUSTOM_HUD_DIR" ]] && compgen -G "$CUSTOM_HUD_DIR/*.png" > /dev/null 2>&1; then
        python3 "$SCRIPT_DIR/tools/patch_e8_textures.py" --bin "$RU_BIN"
    fi
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "==========================================================="
    echo "[✓] Сюжетные диалоги успешно обновлены в slayers_royal_ru.bin!"
    echo "    Время сборки: ~12 секунд (без перекодирования FMV)."
    echo "    Запуск игры: ./run_game.sh"
    echo "==========================================================="
    exit 0
fi

if [[ "$1" == "--quick" || "$1" == "-q" || "$1" == "--inspection" ]]; then
    echo "[1/1] Быстрое обновление описаний предметов из translations/room_inspection_ru.json..."
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_inspection.py" \
        --bin "$RU_BIN" \
        --translations "$INSPECTION_JSON" \
        --room-names "$ROOM_NAMES_JSON" \
        --all-rooms
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "==========================================================="
    echo "[✓] Описания предметов успешно обновлены в slayers_royal_ru.bin!"
    echo "    Можете запускать игру: ./run_game.sh"
    echo "==========================================================="
    exit 0
fi

if [[ "$1" == "--cards" ]]; then
    echo "[1/1] Обновление карточек персонажей из translations/lore_cards_ru.json..."
    python3 "$SCRIPT_DIR/tools/patch_lore_cards.py" \
        --disc "$RU_BIN" \
        --cards "$CARDS_JSON"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "[✓] Карточки персонажей успешно обновлены!"
    exit 0
fi
if [[ "$1" == "--map" ]]; then
    echo "[1/1] Обновление карты мира из translations/world_map_ru.json..."
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_world_map.py" \
        --bin "$RU_BIN" \
        --catalog "$MAP_JSON"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "[✓] Карта мира успешно обновлена!"
    exit 0
fi

if [[ "$1" == "--banners" ]]; then
    echo "[1/1] Обновление графических плашек локаций..."
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_location_banners.py" \
        --bin "$RU_BIN" \
        --catalog "$BANNERS_JSON"
    echo "[✓] Графические плашки локаций успешно обновлены!"
    exit 0
fi
if [[ "$1" == "--status-ui" || "$1" == "--tabs" ]]; then
    echo "==========================================================="
    echo "[1/1] Внедрение атласа меню персонажей (BASYOG.UNT 162)..."
    echo "==========================================================="
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_basyog_162.py" --bin "$RU_BIN"
    mkdir -p "$PATCH_REPO_DIR/localization-output/ru"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "==========================================================="
    echo "[✓] Атлас меню персонажей успешно обновлён!"
    echo "==========================================================="
    exit 0
fi
if [[ "$1" == "--combat" || "$1" == "--combat-dialogues" ]]; then
    echo "[1/3] Внедрение боевого шрифта и системных строк (PROG.UNT 0x142, 0x007)..."
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_combat.py" --bin "$RU_BIN"
    echo "[2/3] Обновление боевых диалогов из translations/combat_dialogues_ru.json..."
    python3 "$SCRIPT_DIR/tools/patch_combat_dialogues.py" \
        --bin "$RU_BIN" \
        --catalog "$COMBAT_DIALOGUES_JSON"
    echo "[3/3] Внедрение заклинаний и боевого меню магии (PROG.UNT 0x007, 325..443)..."
    python3 "$SCRIPT_DIR/tools/patch_spells.py" \
        --bin "$RU_BIN" \
        --catalog "$SPELLS_JSON"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "[✓] Боевые диалоги и заклинания успешно обновлены!"
    exit 0
fi
if [[ "$1" == "--spells" ]]; then
    echo "[1/1] Внедрение заклинаний и боевого меню магии (PROG.UNT 0x007, 325..443)..."
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_spells.py" \
        --bin "$RU_BIN" \
        --catalog "$SPELLS_JSON"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "[✓] Заклинания успешно обновлены!"
    exit 0
fi
if [[ "$1" == "--services" || "$1" == "--town" ]]; then
    echo "[1/1] Обновление городских служб из translations/town_services_ru.json..."
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_town_services.py" \
        --bin "$RU_BIN" \
        --catalog "$TOWN_SERVICES_JSON" \
        --shop-catalog "$SHOP_DIALOGUES_JSON"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "[✓] Городские службы успешно обновлены!"
    exit 0
fi
if [[ "$1" == "--shops" || "$1" == "--shop-dialogues" ]]; then
    echo "[1/1] Обновление диалогов и меню магазинов из translations/shop_dialogues_ru.json..."
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_town_services.py" \
        --bin "$RU_BIN" \
        --catalog "$SHOP_DIALOGUES_JSON" \
        --shops-only
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "[✓] Диалоги и меню магазинов успешно обновлены!"
    exit 0
fi
if [[ "$1" == "--minigames" || "$1" == "--quiz" ]]; then
    echo "[1/2] Обновление мини-игр и викторины из translations/minigames_ru.json..."
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_minigames.py" \
        --bin "$RU_BIN" \
        --catalog "$MINIGAMES_JSON"
    echo "[2/2] Обновление меню выбора мини-игр из translations/minigames_menu_ru.json..."
    python3 "$SCRIPT_DIR/tools/patch_minigames_menu.py" --bin "$RU_BIN"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "[✓] Мини-игры, викторина и меню успешно обновлены!"
    exit 0
fi
if [[ "$1" == "--bonus-menu" || "$1" == "--title-menu" ]]; then
    echo "==========================================================="
    echo "[1/1] Обновление меню бонусов и главного меню из translations/bonus_menu_ru.json..."
    echo "==========================================================="
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_bonus_menu.py" --bin "$RU_BIN" --catalog "$BONUS_MENU_JSON"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "==========================================================="
    echo "[✓] Меню бонусов и главное меню успешно обновлены!"
    echo "==========================================================="
    exit 0
fi
if [[ "$1" == "--town-maps" || "$1" == "--maps" ]]; then
    echo "==========================================================="
    echo "[1/1] Внедрение иллюстраций карт городов (BASYOG.UNT 467..476)..."
    echo "==========================================================="
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_town_maps.py" --bin "$RU_BIN" --maps-dir "$TOWN_MAPS_DIR"
    mkdir -p "$PATCH_REPO_DIR/localization-output/ru"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "==========================================================="
    echo "[✓] Карты городов успешно обновлены!"
    echo "==========================================================="
    exit 0
fi
if [[ "$1" == "--hud" || "$1" == "--e8" ]]; then
    echo "==========================================================="
    echo "[1/1] Внедрение атласа интерфейса/HUD (PROG.UNT 0x008, 74 380)..."
    echo "==========================================================="
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_e8_textures.py" --bin "$RU_BIN"
    mkdir -p "$PATCH_REPO_DIR/localization-output/ru"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "==========================================================="
    echo "[✓] Атлас интерфейса/HUD успешно обновлён!"
    echo "==========================================================="
    exit 0
fi
if [[ "$1" == "--title-logo" || "$1" == "--logo" ]]; then
    echo "==========================================================="
    echo "[1/1] Внедрение русского логотипа титульного экрана (PROG.UNT 314)..."
    echo "==========================================================="
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_title_logo.py" --bin "$RU_BIN"
    mkdir -p "$PATCH_REPO_DIR/localization-output/ru"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "==========================================================="
    echo "[✓] Русский логотип титульного экрана успешно внедрён!"
    echo "==========================================================="
    exit 0
fi
if [[ "$1" == "--movies" || "$1" == "--fmv" || "$1" == "--video" ]]; then
    echo "==========================================================="
    echo "[1/1] Внедрение видеороликов с русскими субтитрами в $RU_BIN..."
    echo "==========================================================="
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/fmv_pipeline.py" \
        --inject-disc "$RU_BIN" \
        --movies-dir "$SCRIPT_DIR/build/movies"
    mkdir -p "$PATCH_REPO_DIR/localization-output/ru"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "==========================================================="
    echo "[✓] Видеоролики успешно внедрены!"
    echo "==========================================================="
    exit 0
fi

if [[ "$1" == "--custom-screens" || "$1" == "--screens" ]]; then
    echo "==========================================================="
    echo "[1/1] Внедрение пользовательских экранов (OPT 203, 221, 225; PROG 323)..."
    echo "==========================================================="
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_custom_screens.py" --bin "$RU_BIN" --screens-dir "$CUSTOM_SCREENS_DIR"
    mkdir -p "$PATCH_REPO_DIR/localization-output/ru"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "==========================================================="
    echo "[✓] Пользовательские экраны успешно обновлены!"
    echo "==========================================================="
    exit 0
fi
if [[ "$1" == "--extra-screens" ]]; then
    echo "==========================================================="
    echo "[1/1] Внедрение 13 дополнительных экранов/текстур (OPT 137..232, OPTCINE 01, PROG 54..57)..."
    echo "==========================================================="
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_extra_screens.py" --bin "$RU_BIN"
    mkdir -p "$PATCH_REPO_DIR/localization-output/ru"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "==========================================================="
    echo "[✓] 13 дополнительных экранов/текстур успешно внедрены!"
    echo "==========================================================="
    exit 0
fi



# Полная сборка
if [[ ! -f "$BIN_ORIG" ]]; then
    echo "Ошибка: оригинальный образ $BIN_ORIG не найден!" >&2
    exit 1
fi

mkdir -p "$RU_DIR"

echo "[1/9] Сборка сюжетных диалогов (PROG.UNT)..."
python3 "$SCRIPT_DIR/tools/sync_story_dialogues.py" --sync-if-newer
python3 "$PATCH_REPO_DIR/localize.py" build \
    --bin "$BIN_ORIG" \
    --workspace "$PATCH_REPO_DIR/localization-work/ru" \
    --locale ru \
    --output-dir "$RU_DIR" \
    --force

echo "[2/9] Внедрение видеороликов с русскими субтитрами (build/movies/MOVIE.STR)..."
python3 "$SCRIPT_DIR/tools/fmv_pipeline.py" \
    --inject-disc "$RU_BIN" \
    --movies-dir "$SCRIPT_DIR/build/movies"

echo "[3/9] Внедрение описаний интерактивных объектов во все 149 комнат..."
python3 "$SCRIPT_DIR/tools/patch_inspection.py" \
    --bin "$RU_BIN" \
    --translations "$INSPECTION_JSON" \
    --room-names "$ROOM_NAMES_JSON" \
    --all-rooms

echo "[4/9] Внедрение энциклопедических карточек персонажей..."
python3 "$SCRIPT_DIR/tools/patch_lore_cards.py" \
    --disc "$RU_BIN" \
    --cards "$CARDS_JSON"

echo "[5/9] Внедрение названий локаций на карте мира (PROG.UNT 0x001)..."
python3 "$SCRIPT_DIR/tools/patch_world_map.py" \
    --bin "$RU_BIN" \
    --catalog "$MAP_JSON"

echo "[6/9] Внедрение графических плашек-баннеров локаций (BASYOG.UNT 466)..."
python3 "$SCRIPT_DIR/tools/patch_location_banners.py" \
    --bin "$RU_BIN" \
    --catalog "$BANNERS_JSON"

if [[ -f "$SCRIPT_DIR/data/preview_basyog_162_ru.png" ]]; then
    echo "[6.5/9] Внедрение атласа меню персонажей (BASYOG.UNT 162)..."
    python3 "$SCRIPT_DIR/tools/patch_basyog_162.py" --bin "$RU_BIN"
fi
echo "[7/9] Внедрение боевых диалогов, шрифта и заклинаний (PROG.UNT 0x007, 0x142, 325..443)..."
python3 "$SCRIPT_DIR/tools/patch_combat.py" --bin "$RU_BIN"
python3 "$SCRIPT_DIR/tools/patch_combat_dialogues.py" \
    --bin "$RU_BIN" \
    --catalog "$COMBAT_DIALOGUES_JSON"
python3 "$SCRIPT_DIR/tools/patch_spells.py" \
    --bin "$RU_BIN" \
    --catalog "$SPELLS_JSON"
echo "[8/9] Внедрение городских служб, магазинов, меню и валюты (PROG.UNT 0x003, 0x03A)..."
python3 "$SCRIPT_DIR/tools/patch_town_services.py" \
    --bin "$RU_BIN" \
    --catalog "$TOWN_SERVICES_JSON" \
    --shop-catalog "$SHOP_DIALOGUES_JSON"

echo "[9/9] Мини-игры, викторина и меню выбора мини-игр (PROG.UNT 13..17, OPT.UNT 152..168)..."
python3 "$SCRIPT_DIR/tools/patch_minigames.py" \
    --bin "$RU_BIN" \
    --catalog "$MINIGAMES_JSON"
python3 "$SCRIPT_DIR/tools/patch_minigames_menu.py" \
    --bin "$RU_BIN"
echo "[10/10] Внедрение меню бонусов и заголовков комнат (OPT.UNT 143..146)..."
python3 "$SCRIPT_DIR/tools/patch_bonus_menu.py" \
    --bin "$RU_BIN" \
    --catalog "$BONUS_MENU_JSON"
echo "[11/11] Внедрение русского логотипа титульного экрана (PROG.UNT 314)..."
python3 "$SCRIPT_DIR/tools/patch_title_logo.py" --bin "$RU_BIN"
if compgen -G "$TOWN_MAPS_DIR/*.png" > /dev/null 2>&1 || compgen -G "$TOWN_MAPS_DIR/*.PNG" > /dev/null 2>&1; then
    echo "[11/11] Внедрение пользовательских карт городов (BASYOG.UNT 467..476)..."
    python3 "$SCRIPT_DIR/tools/patch_town_maps.py" --bin "$RU_BIN" --maps-dir "$TOWN_MAPS_DIR"
fi
if [[ -d "$CUSTOM_HUD_DIR" ]] && compgen -G "$CUSTOM_HUD_DIR/*.png" > /dev/null 2>&1; then
    echo "[12/12] Внедрение атласа интерфейса/HUD (PROG.UNT 0x008)..."
    python3 "$SCRIPT_DIR/tools/patch_e8_textures.py" --bin "$RU_BIN"
fi
if [[ -d "$CUSTOM_SCREENS_DIR" ]] && compgen -G "$CUSTOM_SCREENS_DIR/*.png" > /dev/null 2>&1; then
    echo "[13/13] Внедрение пользовательских экранов (OPT 203, 221, 225; PROG 323)..."
    python3 "$SCRIPT_DIR/tools/patch_custom_screens.py" --bin "$RU_BIN" --screens-dir "$CUSTOM_SCREENS_DIR"
fi
if [[ -d "$EXTRA_SCREENS_DIR" ]] && compgen -G "$EXTRA_SCREENS_DIR/*.png" > /dev/null 2>&1 || compgen -G "$SCRIPT_DIR/еще переводы/*.png" > /dev/null 2>&1; then
    echo "[14/14] Внедрение 13 дополнительных экранов/текстур (OPT 137..232, OPTCINE 01, PROG 54..57)..."
    python3 "$SCRIPT_DIR/tools/patch_extra_screens.py" --bin "$RU_BIN"
fi
mkdir -p "$PATCH_REPO_DIR/localization-output/ru"
cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
echo "==========================================================="
echo "[✓] Полная сборка успешно завершена!"
echo "    Образ диска: $RU_BIN"
echo "    CUE-файл:    $RU_CUE"
echo ""
echo "    Для запуска игры используйте: ./run_game.sh"
echo "==========================================================="
