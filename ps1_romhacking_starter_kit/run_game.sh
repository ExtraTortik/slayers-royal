#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CUE_RU="$SCRIPT_DIR/localization-output/ru/game_ru.cue"
CUE_ORIG="$SCRIPT_DIR/downloads/game.cue"

TARGET_CUE="$CUE_RU"
if [[ "$1" == "--orig" ]]; then
    TARGET_CUE="$CUE_ORIG"
fi

if [[ ! -f "$TARGET_CUE" ]]; then
    if [[ "$TARGET_CUE" == "$CUE_RU" ]]; then
        echo "[*] Образ не найден. Запуск сборщика build.sh..."
        "$SCRIPT_DIR/build.sh"
    else
        echo "[ОШИБКА] Файл $TARGET_CUE не найден!" >&2
        exit 1
    fi
fi

# Поиск эмулятора
EMU_CMD=""
if command -v duckstation-qt &>/dev/null; then
    EMU_CMD="duckstation-qt"
elif command -v duckstation &>/dev/null; then
    EMU_CMD="duckstation"
elif command -v mednafen &>/dev/null; then
    EMU_CMD="mednafen"
fi

if [[ -n "$EMU_CMD" ]]; then
    echo "[*] Запуск эмулятора: $EMU_CMD '$TARGET_CUE'"
    exec $EMU_CMD "$TARGET_CUE"
else
    echo "[*] Эмулятор не найден в PATH. Открытие через системную команду xdg-open..."
    xdg-open "$TARGET_CUE" 2>/dev/null || open "$TARGET_CUE" 2>/dev/null || true
fi
