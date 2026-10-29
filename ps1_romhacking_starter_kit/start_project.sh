#!/usr/bin/env bash
# ==============================================================================
# PS1 ROM Hacking Framework - Стартовый лаунчер (Linux / macOS / WSL)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================================="
echo "   PS1 ROM Hacking Framework — Среда разработки и агентов         "
echo "=================================================================="
echo ""

# 1. Проверка Python 3
if ! command -v python3 &>/dev/null; then
    echo "[ОШИБКА] python3 не найден в системе. Установите Python 3.10+." >&2
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[*] Python версия: $PY_VER"

# 2. Проверка библиотек
if ! python3 -c "import PIL, pytest, yaml" &>/dev/null; then
    echo "[!] Устанавливаем недостающие библиотеки из requirements.txt..."
    python3 -m pip install -q -r "$SCRIPT_DIR/requirements.txt" || true
else
    echo "[✓] Зависимости Python в порядке."
fi

# 3. Настройка профиля агентов
OMP_USER_DIR="$HOME/.omp/agent"
AGENT_TEMPLATES_DIR="$SCRIPT_DIR/agent_config"

if [[ ! -d "$OMP_USER_DIR" ]]; then
    mkdir -p "$OMP_USER_DIR"
    cp -n "$AGENT_TEMPLATES_DIR/config.yml.template" "$OMP_USER_DIR/config.yml" 2>/dev/null || true
    cp -n "$AGENT_TEMPLATES_DIR/mcp.json.template" "$OMP_USER_DIR/mcp.json" 2>/dev/null || true
    cp -n "$AGENT_TEMPLATES_DIR/models.yml.template" "$OMP_USER_DIR/models.yml" 2>/dev/null || true
    echo "[✓] Шаблоны агентов скопированы в $OMP_USER_DIR"
else
    echo "[✓] Профиль агента обнаружен в $OMP_USER_DIR"
fi

chmod +x "$SCRIPT_DIR/build.sh" "$SCRIPT_DIR/run_game.sh" 2>/dev/null || true

# 4. Диспетчер аргументов
if [[ "$1" == "--build" ]]; then
    exec "$SCRIPT_DIR/build.sh" "${@:2}"
elif [[ "$1" == "--run" ]]; then
    exec "$SCRIPT_DIR/run_game.sh" "${@:2}"
fi

# 5. Меню
echo ""
echo "Выберите действие:"
echo "  1) Собрать образ диска (build.sh)"
echo "  2) Запустить игру в эмуляторе (run_game.sh)"
echo "  3) Показать сейвстейты DuckStation (sync_savestates.py)"
echo "  4) Инструкция: Как начать перевод новой игры"
echo "  5) Роли и системные промпты агентов"
echo "  0) Выход"
echo ""

read -rp "Введите номер (0-5) [1]: " CHOICE
CHOICE="${CHOICE:-1}"

case "$CHOICE" in
    1) exec "$SCRIPT_DIR/build.sh" ;;
    2) exec "$SCRIPT_DIR/run_game.sh" ;;
    3) python3 "$SCRIPT_DIR/core/sync_savestates.py" --list ;;
    4) less "$SCRIPT_DIR/docs/HOW_TO_START_NEW_GAME.md" 2>/dev/null || cat "$SCRIPT_DIR/docs/HOW_TO_START_NEW_GAME.md" ;;
    5) less "$SCRIPT_DIR/agent_config/AGENT_PROMPTS_PS1.md" 2>/dev/null || cat "$SCRIPT_DIR/agent_config/AGENT_PROMPTS_PS1.md" ;;
    0) exit 0 ;;
    *) echo "Неверный выбор." ; exit 1 ;;
esac
