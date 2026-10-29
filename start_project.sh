#!/usr/bin/env bash
# ==============================================================================
# Slayers Royal (PS1) — Главный мастер-лаунчер проекта и окружения агентов
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================================="
echo "   Slayers Royal (PS1) — Среда разработки, ромхакинга и агентов   "
echo "=================================================================="
echo ""

# 1. Проверка Python 3
if ! command -v python3 &>/dev/null; then
    echo "[ОШИБКА] python3 не найден в системе. Установите Python 3.10+." >&2
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[*] Python версия: $PY_VER (обнаружен $(which python3))"

# 2. Проверка / установка зависимостей
echo "[*] Проверка зависимостей (Pillow, pytest, pyyaml, numpy)..."
if ! python3 -c "import PIL, pytest, yaml, numpy" &>/dev/null; then
    echo "[!] Некоторые библиотеки отсутствуют. Устанавливаем из requirements.txt..."
    python3 -m pip install -q -r "$SCRIPT_DIR/requirements.txt" || {
        echo "[!] Предупреждение: pip install завершился с предупреждением. Проверьте права доступа."
    }
else
    echo "[✓] Все базовые зависимости Python установлены."
fi

# 3. Подготовка upstream-тулкита (patch_repo) и образа диска
if ! python3 "$SCRIPT_DIR/tools/ensure_patch_repo.py"; then
    echo "[!] Не удалось подготовить patch_repo. Сборка будет недоступна." >&2
elif ! python3 "$SCRIPT_DIR/tools/prepare_game.py"; then
    echo "[!] Образ диска не готов: положите sr.bin в downloads/ и повторите запуск." >&2
fi

# 4. Проверка и подключение конфигурации агентов
OMP_USER_DIR="$HOME/.omp/agent"
AGENT_TEMPLATES_DIR="$SCRIPT_DIR/agent_config"

echo "[*] Проверка настроек агентского харнеса..."
if [[ -d "$OMP_USER_DIR" ]]; then
    echo "[✓] Обнаружен профиль агента в $OMP_USER_DIR"
else
    echo "[i] Локальный профиль ~/.omp/agent не обнаружен."
    echo "    Создаём структуру и разворачиваем шаблоны конфигурации..."
    mkdir -p "$OMP_USER_DIR"
    cp -n "$AGENT_TEMPLATES_DIR/config.yml.template" "$OMP_USER_DIR/config.yml" 2>/dev/null || true
    cp -n "$AGENT_TEMPLATES_DIR/mcp.json.template" "$OMP_USER_DIR/mcp.json" 2>/dev/null || true
    cp -n "$AGENT_TEMPLATES_DIR/models.yml.template" "$OMP_USER_DIR/models.yml" 2>/dev/null || true
    echo "[✓] Шаблоны агентов успешно развёрнуты в ~/.omp/agent/"
fi

# 4. Проверка целостности проекта
echo "[*] Проверка структуры проекта..."
ERRORS=0

if [[ ! -f "$SCRIPT_DIR/downloads/sr.bin" ]]; then
    echo "[!] ВНИМАНИЕ: Оригинальный дамп downloads/sr.bin отсутствует."
    echo "    Он будет автоматически загружен или скопирован при первом запуске build.sh."
fi

if [[ ! -d "$SCRIPT_DIR/translations" ]]; then
    echo "[ОШИБКА] Каталог translations/ отсутствует!" >&2
    ERRORS=$((ERRORS + 1))
fi

if [[ ! -f "$SCRIPT_DIR/build.sh" ]]; then
    echo "[ОШИБКА] Скрипт сборщика build.sh отсутствует!" >&2
    ERRORS=$((ERRORS + 1))
fi

chmod +x "$SCRIPT_DIR/build.sh" "$SCRIPT_DIR/run_game.sh" 2>/dev/null || true

if [[ $ERRORS -gt 0 ]]; then
    echo "[ОШИБКА] Обнаружены критические ошибки структуры проекта ($ERRORS)." >&2
    exit 1
fi
echo "[✓] Структура тулчейна целостна."
echo ""

# 5. Диспетчер командной строки (если передан аргумент)
if [[ "$1" == "--build" ]]; then
    exec "$SCRIPT_DIR/build.sh" "${@:2}"
elif [[ "$1" == "--run" ]]; then
    exec "$SCRIPT_DIR/run_game.sh" "${@:2}"
elif [[ "$1" == "--test" ]]; then
    echo "[*] Запуск набора тестов pytest..."
    exec python3 -m pytest "$SCRIPT_DIR/tools" -q
elif [[ "$1" == "--validate" ]]; then
    exec "$SCRIPT_DIR/build.sh" --validate
elif [[ "$1" == "--agent-info" ]]; then
    echo "=== Конфигурация агентов ==="
    cat "$SCRIPT_DIR/agent_config/AGENT_ROLES.md"
    exit 0
fi

# 6. Интерактивное меню (при запуске без аргументов)
echo "Выберите действие:"
echo "  1) Собрать русский образ диска (build.sh)"
echo "  2) Запустить игру в эмуляторе (run_game.sh)"
echo "  3) Запустить быстрый тест диалогов (build.sh --story)"
echo "  4) Запустить полный набор тестов (pytest tools/)"
echo "  5) Комплексная валидация всех секторов (build.sh --validate)"
echo "  6) Показать роли и настройки агентов"
echo "  0) Выход"
echo ""
read -rp "Введите номер (0-6) [1]: " CHOICE
CHOICE="${CHOICE:-1}"

case "$CHOICE" in
    1)
        exec "$SCRIPT_DIR/build.sh"
        ;;
    2)
        exec "$SCRIPT_DIR/run_game.sh"
        ;;
    3)
        exec "$SCRIPT_DIR/build.sh" --story
        ;;
    4)
        exec python3 -m pytest "$SCRIPT_DIR/tools"
        ;;
    5)
        exec "$SCRIPT_DIR/build.sh" --validate
        ;;
    6)
        cat "$SCRIPT_DIR/agent_config/AGENT_ROLES.md"
        ;;
    0)
        echo "Завершение работы."
        exit 0
        ;;
    *)
        echo "Неверный выбор."
        exit 1
        ;;
esac
