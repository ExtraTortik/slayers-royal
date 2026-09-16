#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BIN_ORIG="$SCRIPT_DIR/downloads/sr.bin"
RU_DIR="$SCRIPT_DIR/localization-output/ru"
RU_BIN="$RU_DIR/slayers_royal_ru.bin"
RU_CUE="$RU_DIR/slayers_royal_ru.cue"
INSPECTION_JSON="$SCRIPT_DIR/translations/room_inspection_ru.json"
CARDS_JSON="$SCRIPT_DIR/translations/lore_cards_ru.json"
COMBAT_JSON="$SCRIPT_DIR/translations/combat_ru.json"
COMBAT_DIALOGUES_JSON="$SCRIPT_DIR/translations/combat_dialogues_ru.json"
MAP_JSON="$SCRIPT_DIR/translations/world_map_ru.json"
BANNERS_JSON="$SCRIPT_DIR/translations/location_banners_ru.json"
TOWN_SERVICES_JSON="$SCRIPT_DIR/translations/town_services_ru.json"
SHOP_DIALOGUES_JSON="$SCRIPT_DIR/translations/shop_dialogues_ru.json"
MINIGAMES_JSON="$SCRIPT_DIR/translations/minigames_ru.json"
STORY_JSON="$SCRIPT_DIR/translations/story_dialogues_ru.json"
INDEX_JSON="$SCRIPT_DIR/translations/translations_index.json"
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
    echo "  --map        Обновить ТОЛЬКО названия локаций на карте мира"
    echo "  --banners    Обновить ТОЛЬКО графические плашки-баннеры локаций"
    echo "  --cards      Обновить ТОЛЬКО энциклопедические карточки персонажей"
    echo "  --combat, --combat-dialogues  Обновить боевые диалоги из translations/combat_dialogues_ru.json"
    echo "  --services, --town  Обновить городские службы, магазины и меню из translations/town_services_ru.json"
    echo "  --shops, --shop-dialogues  Обновить диалоги и меню магазинов из translations/shop_dialogues_ru.json"
    echo "  --minigames, --quiz Обновить правила 5 мини-игр и викторину из translations/minigames_ru.json"
    echo "  --validate   Проверить каталоги диалогов, комнат, карты, плашек, служб, мини-игр и викторины на ошибки"
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
    python3 -m pytest tools/test_inspection_translations.py -q
    echo "[✓] Все файлы перевода корректны и не содержат ошибок!"
    echo "[*] Валидация боевого режима..."
    python3 "$SCRIPT_DIR/tools/combat_text.py" --verify
    echo "[*] Валидация боевых диалогов..."
    python3 "$SCRIPT_DIR/tools/patch_combat_dialogues.py" --verify
    echo "[*] Валидация названий карты мира..."
    python3 "$SCRIPT_DIR/tools/patch_world_map.py" --verify
    echo "[*] Валидация графических плашек локаций..."
    python3 "$SCRIPT_DIR/tools/patch_location_banners.py" --verify
    echo "[*] Валидация городских служб, меню и валюты..."
    python3 "$SCRIPT_DIR/tools/patch_town_services.py" --verify
    echo "[*] Валидация мини-игр и викторины..."
    python3 "$SCRIPT_DIR/tools/patch_minigames.py" --verify
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

    echo "==========================================================="
    echo "[2/2] Накатывание сопутствующих патчей (инспекция, карты, плашки, бой, службы, мини-игры)..."
    echo "==========================================================="
    python3 "$SCRIPT_DIR/tools/patch_inspection.py" --bin "$RU_BIN" --translations "$INSPECTION_JSON" --all-rooms
    python3 "$SCRIPT_DIR/tools/patch_lore_cards.py" --disc "$RU_BIN" --cards "$CARDS_JSON"
    python3 "$SCRIPT_DIR/tools/patch_world_map.py" --bin "$RU_BIN" --catalog "$MAP_JSON"
    python3 "$SCRIPT_DIR/tools/patch_location_banners.py" --bin "$RU_BIN" --catalog "$BANNERS_JSON"
    python3 "$SCRIPT_DIR/tools/patch_combat_dialogues.py" --bin "$RU_BIN" --catalog "$COMBAT_DIALOGUES_JSON"
    python3 "$SCRIPT_DIR/tools/patch_town_services.py" --bin "$RU_BIN" --catalog "$TOWN_SERVICES_JSON" --shop-catalog "$SHOP_DIALOGUES_JSON"
    python3 "$SCRIPT_DIR/tools/patch_minigames.py" --bin "$RU_BIN" --catalog "$MINIGAMES_JSON"

    mkdir -p "$PATCH_REPO_DIR/localization-output/ru"
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
if [[ "$1" == "--combat" || "$1" == "--combat-dialogues" ]]; then
    echo "[1/1] Обновление боевых диалогов из translations/combat_dialogues_ru.json..."
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_combat_dialogues.py" \
        --bin "$RU_BIN" \
        --catalog "$COMBAT_DIALOGUES_JSON"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "[✓] Боевые диалоги успешно обновлены!"
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
    echo "[1/1] Обновление мини-игр и викторины из translations/minigames_ru.json..."
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_minigames.py" \
        --bin "$RU_BIN" \
        --catalog "$MINIGAMES_JSON"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "[✓] Мини-игры и викторина успешно обновлены!"
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

echo "[7/9] Внедрение боевых диалогов и шрифта (PROG.UNT 0x007, 0x142)..."
python3 "$SCRIPT_DIR/tools/patch_combat_dialogues.py" \
    --bin "$RU_BIN" \
    --catalog "$COMBAT_DIALOGUES_JSON"

echo "[8/9] Внедрение городских служб, магазинов, меню и валюты (PROG.UNT 0x003, 0x03A)..."
python3 "$SCRIPT_DIR/tools/patch_town_services.py" \
    --bin "$RU_BIN" \
    --catalog "$TOWN_SERVICES_JSON" \
    --shop-catalog "$SHOP_DIALOGUES_JSON"

echo "[9/9] Мини-игры и викторина (PROG.UNT 13..17)..."
python3 "$SCRIPT_DIR/tools/patch_minigames.py" \
    --bin "$RU_BIN" \
    --catalog "$MINIGAMES_JSON"
mkdir -p "$PATCH_REPO_DIR/localization-output/ru"
cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
echo "==========================================================="
echo "[✓] Полная сборка успешно завершена!"
echo "    Образ диска: $RU_BIN"
echo "    CUE-файл:    $RU_CUE"
echo ""
echo "    Для запуска игры используйте: ./run_game.sh"
echo "==========================================================="
