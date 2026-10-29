#!/usr/bin/env bash
# ==============================================================================
# Slayers Royal — Скрипт сборки автономного пакета для передачи на другой ПК
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BUNDLE_NAME="slayers_royal_transfer_bundle"
BUNDLE_DIR="$SCRIPT_DIR/$BUNDLE_NAME"
ARCHIVE_TAR="$SCRIPT_DIR/${BUNDLE_NAME}.tar.gz"
ARCHIVE_ZIP="$SCRIPT_DIR/${BUNDLE_NAME}.zip"

echo "=================================================================="
echo "   Подготовка чистого пакета для передачи: $BUNDLE_NAME"
echo "=================================================================="
echo ""

# 1. Очистка старой папки экспорта
rm -rf "$BUNDLE_DIR" "$ARCHIVE_TAR" "$ARCHIVE_ZIP"
mkdir -p "$BUNDLE_DIR"

echo "[1/5] Копирование документации и инструкций..."
cp "$SCRIPT_DIR/INSTRUCTIONS_FOR_NEW_MACHINE.md" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/hand_off.md" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/EMULATOR_DEBUGGING_GUIDE.md" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/PS1_ROMHACKING_GUIDE_WINDOWS.md" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/MINIGAME_LUNCH_SPEC.md" "$BUNDLE_DIR/"
cp -r "$SCRIPT_DIR/docs" "$BUNDLE_DIR/"

echo "[2/5] Копирование лаунчеров и сборочных скриптов..."
cp "$SCRIPT_DIR/start_project.sh" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/start_project.bat" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/build.sh" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/build.bat" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/run_game.sh" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/run_game.bat" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/Собрать_Перевод.bat" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/Запустить_Игру_PS1.bat" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$BUNDLE_DIR/"

echo "[3/5] Копирование конфигурации агентов..."
cp -r "$SCRIPT_DIR/agent_config" "$BUNDLE_DIR/"

echo "[4/5] Копирование исходных каталогов (translations, tools, data, fonts, patch_repo)..."
cp -r "$SCRIPT_DIR/translations" "$BUNDLE_DIR/"
cp -r "$SCRIPT_DIR/tools" "$BUNDLE_DIR/"
cp -r "$SCRIPT_DIR/data" "$BUNDLE_DIR/"
cp -r "$SCRIPT_DIR/fonts" "$BUNDLE_DIR/"

if [[ -d "$SCRIPT_DIR/patch_repo" ]]; then
    # Копируем patch_repo исключая тяжелые git-истории если они есть
    mkdir -p "$BUNDLE_DIR/patch_repo"
    rsync -a --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' "$SCRIPT_DIR/patch_repo/" "$BUNDLE_DIR/patch_repo/" 2>/dev/null || cp -r "$SCRIPT_DIR/patch_repo" "$BUNDLE_DIR/"
fi

# Очистка временных файлов и кэшей внутри бандла
echo "[*] Очистка временных кэшей (__pycache__, .pytest_cache)..."
find "$BUNDLE_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$BUNDLE_DIR" -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
find "$BUNDLE_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true

echo "[5/5] Создание сжатых архивов..."
tar -czf "$ARCHIVE_TAR" -C "$SCRIPT_DIR" "$BUNDLE_NAME"
echo "[✓] Создан tar.gz архив: $ARCHIVE_TAR ($(du -h "$ARCHIVE_TAR" | cut -f1))"

if command -v zip &>/dev/null; then
    (cd "$SCRIPT_DIR" && zip -q -r "$ARCHIVE_ZIP" "$BUNDLE_NAME")
    echo "[✓] Создан zip архив: $ARCHIVE_ZIP ($(du -h "$ARCHIVE_ZIP" | cut -f1))"
fi

echo ""
echo "=================================================================="
echo "   Пакет успешно сформирован и готов к передаче!"
echo "   Папка:   $BUNDLE_DIR"
echo "   Архивы:  $ARCHIVE_TAR"
[[ -f "$ARCHIVE_ZIP" ]] && echo "            $ARCHIVE_ZIP"
echo "=================================================================="
