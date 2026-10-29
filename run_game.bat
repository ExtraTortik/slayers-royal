@echo off
chcp 65001 > nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
setlocal enabledelayedexpansion

title Slayers Royal (PS1) - Автоматический лаунчер
cd /d "%~dp0"

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "DOWNLOADS_DIR=%SCRIPT_DIR%\downloads"
set "BIN_ORIG=%DOWNLOADS_DIR%\sr.bin"
set "CUE_ORIG=%DOWNLOADS_DIR%\sr.cue"

set "RU_DIR=%SCRIPT_DIR%\localization-output\ru"
set "RU_BIN=%RU_DIR%\slayers_royal_ru.bin"
set "RU_CUE=%RU_DIR%\slayers_royal_ru.cue"

set "TARGET_MODE=ru"
set "DO_BUILD=false"

:parse_args
if "%~1"=="" goto :args_done
if "%~1"=="--orig" set "TARGET_MODE=orig"
if "%~1"=="--build" set "DO_BUILD=true"
if "%~1"=="--help" goto :show_help
if "%~1"=="-h" goto :show_help
shift
goto :parse_args

:show_help
echo Использование: run_game.bat [опции]
echo.
echo Опции:
echo   (без опций) Запустить русскую версию (slayers_royal_ru.cue)
echo   --orig      Запустить оригинальную японскую версию (sr.cue)
echo   --build     Собрать русскую версию перед запуском
echo   --help, -h  Показать эту справку
exit /b 0

:args_done

:: 0. Поиск Python (нужен для проверки образа и подготовки CUE)
set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD where python >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD where python3 >nul 2>&1 && set "PYTHON_CMD=python3"

echo ===========================================================
echo    Slayers Royal (PS1) — Автоматический лаунчер (Windows)
echo ===========================================================
echo.

:: 1. Проверяем / собираем образ при необходимости
if "%DO_BUILD%"=="true" (
    echo [*] Выполняется сборка русской версии...
    call "%SCRIPT_DIR%\build.bat" --story
    if %ERRORLEVEL% neq 0 (
        echo [ОШИБКА] Сборка завершилась с ошибкой.
        pause
        exit /b %ERRORLEVEL%
    )
)

:: 2. Выбираем целевой образ
set "TARGET_CUE=%RU_CUE%"
if "%TARGET_MODE%"=="orig" (
    set "TARGET_CUE=%CUE_ORIG%"
    if not exist "%CUE_ORIG%" (
        %PYTHON_CMD% "%SCRIPT_DIR%\tools\prepare_game.py" --bin "%BIN_ORIG%" --cue "%CUE_ORIG%"
        if !ERRORLEVEL! neq 0 (
            pause
            exit /b !ERRORLEVEL!
        )
    )
)

if not exist "%TARGET_CUE%" (
    if "%TARGET_MODE%"=="ru" (
        echo [*] Образ slayers_royal_ru.cue не найден. Запускаем быструю сборку...
        call "%SCRIPT_DIR%\build.bat" --story
        if %ERRORLEVEL% neq 0 (
            echo [ОШИБКА] Не удалось собрать образ диска.
            pause
            exit /b 1
        )
    ) else (
        echo [ОШИБКА] Файл %TARGET_CUE% не найден в папке downloads!
        pause
        exit /b 1
    )
)

:: 3. Поиск эмулятора PS1 в Windows
set "EMU_CMD="

:: Проверяем DuckStation в стандартных путях
for %%D in (
    "%LOCALAPPDATA%\DuckStation"
    "%APPDATA%\DuckStation"
    "%LOCALAPPDATA%\Programs\DuckStation"
    "%ProgramFiles%\DuckStation"
    "%ProgramFiles(x86)%\DuckStation"
    "%SCRIPT_DIR%\tools\bin\duckstation"
) do (
    if not defined EMU_CMD if exist "%%~D\duckstation-qt-x64-ReleaseLTCG.exe" (
        set "EMU_CMD="%%~D\duckstation-qt-x64-ReleaseLTCG.exe""
    )
    if not defined EMU_CMD if exist "%%~D\duckstation-qt.exe" (
        set "EMU_CMD="%%~D\duckstation-qt.exe""
    )
)
if not defined EMU_CMD (
    where duckstation-qt >nul 2>&1
    if %ERRORLEVEL% equ 0 set "EMU_CMD=duckstation-qt"
)
if not defined EMU_CMD (
    where duckstation >nul 2>&1
    if %ERRORLEVEL% equ 0 set "EMU_CMD=duckstation"
)

:: Проверяем Mednafen
if not defined EMU_CMD (
    where mednafen >nul 2>&1
    if %ERRORLEVEL% equ 0 set "EMU_CMD=mednafen"
)

:: Проверяем RetroArch
if not defined EMU_CMD (
    where retroarch >nul 2>&1
    if %ERRORLEVEL% equ 0 set "EMU_CMD=retroarch -L mednafen_psx_hw_libretro.dll"
)

:: 4. Запуск
if defined EMU_CMD (
    echo [*] Запуск эмулятора: !EMU_CMD! "%TARGET_CUE%"
    start "" !EMU_CMD! "%TARGET_CUE%"
) else (
    echo [!] Эмулятор PlayStation не найден.
    echo     Установите DuckStation: https://www.duckstation.org/
    echo     или распакуйте portable-сборку в: "%SCRIPT_DIR%\tools\bin\duckstation\"
    echo     Затем повторите: run_game.bat
    echo.
    echo [*] Пробуем открыть CUE системной ассоциацией Windows...
    start "" "%TARGET_CUE%"
)

echo [✓] Команда запуска выполнена успешно.
exit /b 0
