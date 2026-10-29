@echo off
chcp 65001 > nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
setlocal enabledelayedexpansion

title Slayers Royal (PS1) - Мастер-лаунчер проекта и агентов
cd /d "%~dp0"

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

echo ==================================================================
echo    Slayers Royal (PS1) — Среда разработки, ромхакинга и агентов   
echo ==================================================================
echo.

:: 1. Поиск интерпретатора Python 3
set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py -3"
if not defined PY_CMD where python >nul 2>&1 && set "PY_CMD=python"
if not defined PY_CMD where python3 >nul 2>&1 && set "PY_CMD=python3"

if not defined PY_CMD (
    echo [ОШИБКА] Интерпретатор Python 3 не найден в PATH!
    echo Скачайте и установите Python 3 с https://www.python.org/
    echo Обязательно отметьте "Add Python to PATH" при установке.
    pause
    exit /b 1
)

echo [*] Python найден: %PY_CMD%

:: 2. Проверка библиотек Python
%PY_CMD% -c "import PIL, pytest, yaml, numpy" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Устанавливаем недостающие библиотеки из requirements.txt...
    %PY_CMD% -m pip install -q -r "%SCRIPT_DIR%\requirements.txt"
) else (
    echo [✓] Зависимости Python в порядке.
)

:: 3. Подготовка upstream-тулкита (patch_repo) и образа диска
%PY_CMD% "%SCRIPT_DIR%\tools\ensure_patch_repo.py"
if %ERRORLEVEL% neq 0 (
    echo [!] Не удалось подготовить patch_repo. Сборка будет недоступна.
) else (
    %PY_CMD% "%SCRIPT_DIR%\tools\prepare_game.py"
    if %ERRORLEVEL% neq 0 (
        echo [!] Образ диска не готов. Положите sr.bin в папку downloads\ и повторите.
    )
)

:: 4. Проверка агентских настроек
set "AGENT_DIR=%USERPROFILE%\.omp\agent"
if not exist "%AGENT_DIR%" (
    echo [i] Создание каталога конфигурации агентов %AGENT_DIR%...
    mkdir "%AGENT_DIR%" 2>nul
    if not exist "%AGENT_DIR%\config.yml" copy "%SCRIPT_DIR%\agent_config\config.yml.template" "%AGENT_DIR%\config.yml" >nul
    if not exist "%AGENT_DIR%\mcp.json" copy "%SCRIPT_DIR%\agent_config\mcp.json.template" "%AGENT_DIR%\mcp.json" >nul
    if not exist "%AGENT_DIR%\models.yml" copy "%SCRIPT_DIR%\agent_config\models.yml.template" "%AGENT_DIR%\models.yml" >nul
    echo [✓] Базовые шаблоны агентов скопированы в %AGENT_DIR%.
) else (
    echo [✓] Профиль агента обнаружен в %AGENT_DIR%.
)

:: 4. Параметры командной строки
if "%~1"=="--build" (
    call "%SCRIPT_DIR%\build.bat" %2 %3 %4 %5
    exit /b %ERRORLEVEL%
)
if "%~1"=="--run" (
    call "%SCRIPT_DIR%\run_game.bat" %2 %3 %4 %5
    exit /b %ERRORLEVEL%
)
if "%~1"=="--test" (
    %PY_CMD% -m pytest "%SCRIPT_DIR%\tools" -q
    exit /b %ERRORLEVEL%
)
if "%~1"=="--validate" (
    call "%SCRIPT_DIR%\build.bat" --validate
    exit /b %ERRORLEVEL%
)

:: 5. Интерактивное меню
echo.
echo Выберите действие:
echo   1) Собрать русский образ диска (build.bat)
echo   2) Запустить игру в эмуляторе (run_game.bat)
echo   3) Быстрая сборка сюжетных диалогов (build.bat --story)
echo   4) Запустить полный набор тестов (pytest tools\)
echo   5) Комплексная валидация секторов (build.bat --validate)
echo   6) Показать роли агентов
echo   0) Выход
echo.

set /p "CHOICE=Введите номер (0-6) [1]: "
if not defined CHOICE set "CHOICE=1"

if "%CHOICE%"=="1" call "%SCRIPT_DIR%\build.bat" & exit /b %ERRORLEVEL%
if "%CHOICE%"=="2" call "%SCRIPT_DIR%\run_game.bat" & exit /b %ERRORLEVEL%
if "%CHOICE%"=="3" call "%SCRIPT_DIR%\build.bat" --story & exit /b %ERRORLEVEL%
if "%CHOICE%"=="4" %PY_CMD% -m pytest "%SCRIPT_DIR%\tools" & exit /b %ERRORLEVEL%
if "%CHOICE%"=="5" call "%SCRIPT_DIR%\build.bat" --validate & exit /b %ERRORLEVEL%
if "%CHOICE%"=="6" type "%SCRIPT_DIR%\agent_config\AGENT_ROLES.md" & pause & exit /b 0
if "%CHOICE%"=="0" exit /b 0

echo Неверный ввод.
exit /b 1
