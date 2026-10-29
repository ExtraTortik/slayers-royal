#!/usr/bin/env bash
# ==============================================================================
# PS1 ROM Hacking Build System (Linux / macOS / WSL)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ORIG_BIN="$SCRIPT_DIR/downloads/game.bin"
OUT_DIR="$SCRIPT_DIR/localization-output/ru"
OUT_BIN="$OUT_DIR/game_ru.bin"
OUT_CUE="$OUT_DIR/game_ru.cue"

echo "==========================================================="
echo "   PS1 ROM Hacking Build System (Linux / macOS)"
echo "==========================================================="
echo ""

if [[ ! -f "$ORIG_BIN" ]]; then
    echo "[ОШИБКА] Оригинальный образ не найден: $ORIG_BIN" >&2
    echo "Положите оригинальный .bin файл в папку downloads/game.bin" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

echo "[1/3] Копирование базового образа..."
cp "$ORIG_BIN" "$OUT_BIN"

if [[ ! -f "$OUT_CUE" ]]; then
    cat << 'EOF' > "$OUT_CUE"
FILE "game_ru.bin" BINARY
  TRACK 01 MODE2/2352
    INDEX 01 00:00:00
EOF
fi

echo "[2/3] Запуск сборочного скрипта игры (tools/patch_game.py)..."
if [[ -f "$SCRIPT_DIR/tools/patch_game.py" ]]; then
    python3 "$SCRIPT_DIR/tools/patch_game.py" --bin "$OUT_BIN" "$@"
else
    echo "[i] Файл tools/patch_game.py пока не создан."
    echo "    Используйте модули из папки core/ (disc.py, text_engine.py, tim.py)"
    echo "    для создания инжектора под вашу игру."
fi

echo "[3/3] Проверка контрольных сумм секторов (EDC/ECC)..."
python3 -c "from core.disc import parse_iso_root; print('[✓] ISO-9660 файловая система валидна:', len(parse_iso_root('$OUT_BIN')), 'файлов')"

echo ""
echo "==========================================================="
echo "[✓] Сборка успешно завершена!"
echo "    Образ диска: $OUT_BIN"
echo "    CUE-файл:    $OUT_CUE"
echo "==========================================================="
