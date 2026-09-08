#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DOWNLOADS_DIR="$SCRIPT_DIR/downloads"
BIN_ORIG="$DOWNLOADS_DIR/sr.bin"
CUE_ORIG="$DOWNLOADS_DIR/sr.cue"
EXPECTED_SHA256="89760d728f0580dba1c6176f024d3cd6f8fc105b79bd1c27a819208fa0b4d0fe"

RU_DIR="$SCRIPT_DIR/localization-output/ru"
RU_BIN="$RU_DIR/slayers_royal_ru.bin"
RU_CUE="$RU_DIR/slayers_royal_ru.cue"

TOOLS_BIN="$SCRIPT_DIR/tools/bin"
EMU_APPIMAGE="$TOOLS_BIN/DuckStation.AppImage"
RRORO_TOOLS="/home/samvel/rroro/tools/bin"

TARGET_MODE="ru"
DO_BUILD=false
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --help|-h)
            echo "Использование: $0 [--ru | --orig | --build] [--dry-run]"
            echo ""
            echo "Параметры:"
            echo "  --ru        Запустить русскую версию игры (по умолчанию)"
            echo "  --orig      Запустить оригинальную японскую версию игры"
            echo "  --build     Принудительно пересобрать русский образ перед запуском"
            echo "  --dry-run   Выполнить проверку и подготовку файлов без запуска GUI эмулятора"
            echo "  --help, -h  Показать эту справку"
            exit 0
            ;;
        --orig)
            TARGET_MODE="orig"
            ;;
        --ru)
            TARGET_MODE="ru"
            ;;
        --build)
            DO_BUILD=true
            TARGET_MODE="ru"
            ;;
        --dry-run)
            DRY_RUN=true
            ;;
        *)
            echo "Неизвестный параметр: $arg" >&2
            echo "Используйте $0 --help для справки." >&2
            exit 1
            ;;
    esac
done

echo "==========================================================="
echo "   Slayers Royal (PS1) — Автоматический лаунчер"
echo "==========================================================="

verify_sha256() {
    local file="$1"
    local expected="$2"
    if [[ ! -f "$file" ]]; then
        return 1
    fi
    local actual
    actual=$(sha256sum "$file" 2>/dev/null | awk '{print $1}')
    [[ "$actual" == "$expected" ]]
}

# 1. Проверяем / скачиваем оригинальный образ диска
mkdir -p "$DOWNLOADS_DIR"
if ! verify_sha256 "$BIN_ORIG" "$EXPECTED_SHA256"; then
    echo "[1/3] Скачиваем оригинальный образ диска Slayers Royal (Redump, ~540 МБ)..."
    if [[ ! -f "$CUE_ORIG" ]]; then
        echo "      Создание разметки CUE..."
        cat <<EOF > "$CUE_ORIG"
FILE "sr.bin" BINARY
  TRACK 01 MODE2/2352
    INDEX 01 00:00:00
EOF
    fi
    echo "      Скачивание игровых данных BIN (с индикатором прогресса и поддержкой докачки):"
    curl -L -C - --progress-bar "https://archive.org/download/slayers-royal-japan/Slayers%20Royal%20(Japan).bin" -o "$BIN_ORIG"
    echo "      Проверка контрольной суммы SHA-256..."
    if ! verify_sha256 "$BIN_ORIG" "$EXPECTED_SHA256"; then
        echo "Ошибка: контрольная сумма SHA-256 не совпадает!" >&2
        exit 1
    fi
    echo "[1/3] Образ диска успешно скачан и проверен по SHA-256."
else
    if [[ ! -f "$CUE_ORIG" ]]; then
        echo "      Создание разметки CUE..."
        cat <<EOF > "$CUE_ORIG"
FILE "sr.bin" BINARY
  TRACK 01 MODE2/2352
    INDEX 01 00:00:00
EOF
    fi
    echo "[1/3] Проверенный образ диска найден: $BIN_ORIG"
fi

# 2. Выбираем образ для запуска (модифицированный или оригинал)
TARGET_CUE="$RU_CUE"
if [[ "$TARGET_MODE" == "orig" ]]; then
    TARGET_CUE="$CUE_ORIG"
    echo "[*] Выбран оригинальный японский образ: $TARGET_CUE"
else
    mkdir -p "$RU_DIR"
    if [[ "$DO_BUILD" == "true" || ! -f "$RU_BIN" || ! -f "$RU_CUE" ]]; then
        echo "[*] Собираем русскоязычный образ диска..."
        python3 "$SCRIPT_DIR/patch_repo/localize.py" build \
            --bin "$BIN_ORIG" \
            --workspace "$SCRIPT_DIR/patch_repo/localization-work/ru" \
            --locale ru \
            --output-dir "$RU_DIR" \
            --force
        echo "[*] Внедряем описания интерактивных объектов (translations/room_inspection_ru.json)..."
        python3 "$SCRIPT_DIR/tools/patch_inspection.py" \
            --bin "$RU_BIN" \
            --translations "$SCRIPT_DIR/translations/room_inspection_ru.json" \
            --all-rooms
        echo "[*] Внедряем энциклопедические карточки персонажей (data/lore_cards_ru.json)..."
        python3 "$SCRIPT_DIR/tools/patch_lore_cards.py" \
            --disc "$RU_BIN" \
            --cards "$SCRIPT_DIR/data/lore_cards_ru.json"
        cp -a "$RU_DIR/." "$SCRIPT_DIR/patch_repo/localization-output/ru/"
        echo "[*] Сборка полностью завершена: $RU_CUE"
    else
        echo "[*] Найден готовый русскоязычный образ диска: $RU_CUE"
    fi
    TARGET_CUE="$RU_CUE"
fi

if [[ ! -f "$TARGET_CUE" ]]; then
    echo "Ошибка: целевой файл CUE не найден: $TARGET_CUE" >&2
    exit 1
fi

# 3. Проверяем наличие эмулятора (DuckStation, Mednafen, RetroArch)
EMU_CMD=""

# Проверяем и при необходимости копируем локальные DuckStation и BIOS из эталонного каталога
if [[ ! -x "$EMU_APPIMAGE" && -f "$RRORO_TOOLS/DuckStation.AppImage" ]]; then
    mkdir -p "$TOOLS_BIN"
    cp "$RRORO_TOOLS/DuckStation.AppImage" "$EMU_APPIMAGE"
    chmod +x "$EMU_APPIMAGE"
fi

if [[ ! -f "$TOOLS_BIN/bios/scph5500.bin" && -d "$RRORO_TOOLS/bios" ]]; then
    mkdir -p "$TOOLS_BIN/bios"
    cp "$RRORO_TOOLS/bios/"*.bin "$TOOLS_BIN/bios/" 2>/dev/null || true
fi

if command -v duckstation-qt &>/dev/null; then
    EMU_CMD="duckstation-qt"
elif command -v duckstation &>/dev/null; then
    EMU_CMD="duckstation"
elif command -v mednafen &>/dev/null; then
    EMU_CMD="mednafen"
elif command -v retroarch &>/dev/null; then
    EMU_CMD="retroarch -L mednafen_psx_hw_libretro.so"
elif [[ -x "$EMU_APPIMAGE" ]]; then
    EMU_CMD="$EMU_APPIMAGE"
else
    echo "[2/3] Эмулятор в системе не найден. Скачиваем официальный DuckStation AppImage (~92 МБ)..."
    mkdir -p "$TOOLS_BIN"
    curl -L --progress-bar "https://github.com/stenzek/duckstation/releases/download/latest/DuckStation-x64.AppImage" -o "$EMU_APPIMAGE"
    chmod +x "$EMU_APPIMAGE"
    EMU_CMD="$EMU_APPIMAGE"
    echo "[2/3] DuckStation готов к работе."
fi

# Проверяем и настраиваем BIOS для DuckStation
if [[ "$EMU_CMD" == *"duckstation"* || "$EMU_CMD" == *"DuckStation"* ]]; then
    DUCK_BIOS_DIR="$HOME/.local/share/duckstation/bios"
    mkdir -p "$DUCK_BIOS_DIR"
    if [[ -d "$TOOLS_BIN/bios" ]]; then
        cp -n "$TOOLS_BIN/bios/"*.bin "$DUCK_BIOS_DIR/" 2>/dev/null || true
    fi
fi

# 4. Запуск игры
if [[ "$DRY_RUN" == "true" ]]; then
    echo "[3/3] [DRY RUN] Проверка успешно пройдена."
    echo "      Команда эмулятора: $EMU_CMD"
    echo "      Файл образа (CUE): $TARGET_CUE"
    exit 0
fi

echo "[3/3] Запускаем эмулятор: $EMU_CMD '$TARGET_CUE'..."
exec $EMU_CMD "$TARGET_CUE"
