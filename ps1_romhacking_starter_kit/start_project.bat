@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

title PS1 ROM Hacking Framework Launcher
cd /d "%~dp0"

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

echo ==================================================================
echo    PS1 ROM Hacking Framework - Стартовый лаунчер (Windows)
echo ==================================================================
echo.

:: 1. Поиск Python 3
set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py -3"
if not defined PY_CMD where python >nul 2>&1 && set "PY_CMD=python"
if not defined PY_CMD where python3 >nul 2>&1 && set "PY_CMD=python3"

if not defined PY_CMD (
    echo [ОШИБКА] Интерпретатор Python 3 не найден в PATH!
    echo Установите Python 3 с https://www.python.org/
    echo Обязательно отметьте "Add Python to PATH".
    pause
    exit /b 1
)

echo [*] Python найден: %PY_CMD%

:: 2. Проверка библиотек Python
%PY_CMD% -c "import PIL, pytest, yaml" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Устанавливаем недостающие библиотеки из requirements.txt...
    %PY_CMD% -m pip install -q -r "%SCRIPT_DIR%\requirements.txt"
) else (
    echo [✓] Зависимости Python в порядке.
)

:: 3. Подключение агентских настроек
set "AGENT_DIR=%USERPROFILE%\.omp\agent"
if not exist "%AGENT_DIR%" (
    echo [i] Создание каталога конфигурации агентов %AGENT_DIR%...
    mkdir "%AGENT_DIR%" 2>nul
    if not exist "%AGENT_DIR%\config.yml" copy "%SCRIPT_DIR%\agent_config\config.yml.template" "%AGENT_DIR%\config.yml" >nul
    if not exist "%AGENT_DIR%\mcp.json" copy "%SCRIPT_DIR%\agent_config\mcp.json.template" "%AGENT_DIR%\mcp.json" >nul
    if not exist "%AGENT_DIR%\models.yml" copy "%SCRIPT_DIR%\agent_config\models.yml.template" "%AGENT_DIR%\models.yml" >nul
    echo [✓] Шаблоны агентов скопированы в %AGENT_DIR%.
) else (
    echo [✓] Профиль агента обнаружен в %AGENT_DIR%.
)

:: 4. Параметры командной строки
if "%~1"=="--build" (
    call "%SCRIPT_DIR%\build.bat" %2 %3
    exit /b %ERRORLEVEL%
)
if "%~1"=="--run" (
    call "%SCRIPT_DIR%\run_game.bat" %2 %3
    exit /b %ERRORLEVEL%
)

:: 5. Интерактивное меню
echo.
echo Выберите действие:
echo   1) Собрать образ диска (build.bat)
echo   2) Запустить игру в эмуляторе (run_game.bat)
echo   3) Запустить синхронизацию сейвстейтов DuckStation (sync_savestates.py)
echo   4) Показать инструкцию по началу работы с новой игрой
echo   5) Показать роли и промпты агентов
echo   0) Выход
echo.

set /p "CHOICE=Введите номер (0-5) [1]: "
if not defined CHOICE set "CHOICE=1"

if "%CHOICE%"=="1" call "%SCRIPT_DIR%\build.bat" & exit /b %ERRORLEVEL%
if "%CHOICE%"=="2" call "%SCRIPT_DIR%\run_game.bat" & exit /b %ERRORLEVEL%
if "%CHOICE%"=="3" %PY_CMD% "%SCRIPT_DIR%\core\sync_savestates.py" --list & pause & exit /b 0
if "%CHOICE%"=="4" type "%SCRIPT_DIR%\docs\HOW_TO_START_NEW_GAME.md" | more & pause & exit /b 0
if "%CHOICE%"=="5" type "%SCRIPT_DIR%\agent_config\AGENT_PROMPTS_PS1.md" | more & pause & exit /b 0
if "%CHOICE%"=="0" exit /b 0

echo Неверный выбор.
exit /b 1
