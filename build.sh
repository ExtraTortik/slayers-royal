#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BIN_ORIG="$SCRIPT_DIR/downloads/sr.bin"
RU_DIR="$SCRIPT_DIR/localization-output/ru"
RU_BIN="$RU_DIR/slayers_royal_ru.bin"
RU_CUE="$RU_DIR/slayers_royal_ru.cue"
INSPECTION_JSON="$SCRIPT_DIR/translations/room_inspection_ru.json"
CARDS_JSON="$SCRIPT_DIR/data/lore_cards_ru.json"
COMBAT_JSON="$SCRIPT_DIR/translations/combat_ru.json"
MAP_JSON="$SCRIPT_DIR/translations/world_map_ru.json"
BANNERS_JSON="$SCRIPT_DIR/translations/location_banners_ru.json"
PATCH_REPO_DIR="$SCRIPT_DIR/patch_repo"

echo "==========================================================="
echo "   Slayers Royal (PS1) — Сборщик локализации"
echo "==========================================================="

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    echo "Использование: ./build.sh [опция]"
    echo ""
    echo "Опции:"
    echo "  (без опций)  Полная сборка: сюжет + FMV + 149 комнат + карточки + карта + плашки (~35 сек)"
    echo "  --quick, -q  Быстрая сборка: обновить ТОЛЬКО описания предметов из"
    echo "               translations/room_inspection_ru.json (~1.5 сек)"
    echo "  --map        Обновить ТОЛЬКО названия локаций на карте мира"
    echo "  --banners    Обновить ТОЛЬКО графические плашки-баннеры локаций"
    echo "  --cards      Обновить ТОЛЬКО энциклопедические карточки персонажей"
    echo "  --combat     (Опционально) Экспериментальный перевод боевого режима"
    echo "  --validate   Проверить каталоги диалогов, комнат, карты и плашек на ошибки"
    echo "  --help, -h   Показать эту справку"
    exit 0
fi

if [[ "$1" == "--validate" ]]; then
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
    echo "[*] Валидация названий карты мира..."
    python3 "$SCRIPT_DIR/tools/patch_world_map.py" --verify
    echo "[*] Валидация графических плашек локаций..."
    python3 "$SCRIPT_DIR/tools/patch_location_banners.py" --verify
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
    echo "[1/1] Обновление карточек персонажей из data/lore_cards_ru.json..."
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
if [[ "$1" == "--combat" ]]; then
    echo "[1/1] Обновление боевого режима из translations/combat_ru.json..."
    if [[ ! -f "$RU_BIN" ]]; then
        echo "Ошибка: базовый образ $RU_BIN не найден. Запустите сначала полную сборку ./build.sh" >&2
        exit 1
    fi
    python3 "$SCRIPT_DIR/tools/patch_combat.py" \
        --bin "$RU_BIN" \
        --catalog "$COMBAT_JSON"
    cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"
    echo "[✓] Боевой режим успешно обновлен!"
    exit 0
fi


# Полная сборка
if [[ ! -f "$BIN_ORIG" ]]; then
    echo "Ошибка: оригинальный образ $BIN_ORIG не найден!" >&2
    exit 1
fi

mkdir -p "$RU_DIR"

echo "[1/6] Сборка сюжетных диалогов (PROG.UNT)..."
python3 "$PATCH_REPO_DIR/localize.py" build \
    --bin "$BIN_ORIG" \
    --workspace "$PATCH_REPO_DIR/localization-work/ru" \
    --locale ru \
    --output-dir "$RU_DIR" \
    --force

echo "[2/6] Внедрение видеороликов с русскими субтитрами (build/movies/MOVIE.STR)..."
python3 "$SCRIPT_DIR/tools/fmv_pipeline.py" \
    --inject-disc "$RU_BIN" \
    --movies-dir "$SCRIPT_DIR/build/movies"

echo "[3/6] Внедрение описаний интерактивных объектов во все 149 комнат..."
python3 "$SCRIPT_DIR/tools/patch_inspection.py" \
    --bin "$RU_BIN" \
    --translations "$INSPECTION_JSON" \
    --all-rooms

echo "[4/6] Внедрение энциклопедических карточек персонажей..."
python3 "$SCRIPT_DIR/tools/patch_lore_cards.py" \
    --disc "$RU_BIN" \
    --cards "$CARDS_JSON"

echo "[5/6] Внедрение названий локаций на карте мира (PROG.UNT 0x001)..."
python3 "$SCRIPT_DIR/tools/patch_world_map.py" \
    --bin "$RU_BIN" \
    --catalog "$MAP_JSON"

echo "[6/6] Внедрение графических плашек-баннеров локаций (BASYOG.UNT 466)..."
python3 "$SCRIPT_DIR/tools/patch_location_banners.py" \
    --bin "$RU_BIN" \
    --catalog "$BANNERS_JSON"

echo "==========================================================="
echo "[✓] Полная сборка успешно завершена!"
echo "    Образ диска: $RU_BIN"
echo "    CUE-файл:    $RU_CUE"
echo ""
echo "    Для запуска игры используйте: ./run_game.sh"
echo "==========================================================="
