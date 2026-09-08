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
PATCH_REPO_DIR="$SCRIPT_DIR/patch_repo"

echo "==========================================================="
echo "   Slayers Royal (PS1) — Сборщик локализации"
echo "==========================================================="

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    echo "Использование: ./build.sh [опция]"
    echo ""
    echo "Опции:"
    echo "  (без опций)  Полная сборка: сюжетные диалоги + все 149 комнат + карточки (~20 сек)"
    echo "  --quick, -q  Быстрая сборка: обновить ТОЛЬКО описания предметов из"
    echo "               translations/room_inspection_ru.json (~1.5 сек)"
    echo "  --cards      Обновить ТОЛЬКО энциклопедические карточки персонажей"
    echo "  --validate   Только проверить каталог диалогов на ошибки"
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

# Полная сборка
if [[ ! -f "$BIN_ORIG" ]]; then
    echo "Ошибка: оригинальный образ $BIN_ORIG не найден!" >&2
    exit 1
fi

mkdir -p "$RU_DIR"

echo "[1/3] Сборка сюжетных диалогов (PROG.UNT)..."
python3 "$PATCH_REPO_DIR/localize.py" build \
    --bin "$BIN_ORIG" \
    --workspace "$PATCH_REPO_DIR/localization-work/ru" \
    --locale ru \
    --output-dir "$RU_DIR" \
    --force

echo "[2/3] Внедрение описаний интерактивных объектов во все 149 комнат..."
python3 "$SCRIPT_DIR/tools/patch_inspection.py" \
    --bin "$RU_BIN" \
    --translations "$INSPECTION_JSON" \
    --all-rooms

echo "[3/3] Внедрение энциклопедических карточек персонажей..."
python3 "$SCRIPT_DIR/tools/patch_lore_cards.py" \
    --disc "$RU_BIN" \
    --cards "$CARDS_JSON"

cp -a "$RU_DIR/." "$PATCH_REPO_DIR/localization-output/ru/"

echo "==========================================================="
echo "[✓] Полная сборка успешно завершена!"
echo "    Образ диска: $RU_BIN"
echo "    CUE-файл:    $RU_CUE"
echo ""
echo "    Для запуска игры используйте: ./run_game.sh"
echo "==========================================================="
