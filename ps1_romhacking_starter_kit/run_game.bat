@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

title PS1 Emulator Launcher
cd /d "%~dp0"

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "CUE_RU=%SCRIPT_DIR%\localization-output\ru\game_ru.cue"
set "CUE_ORIG=%SCRIPT_DIR%\downloads\game.cue"

set "TARGET_CUE=%CUE_RU%"
if "%~1"=="--orig" set "TARGET_CUE=%CUE_ORIG%"

if not exist "%TARGET_CUE%" (
    if "%TARGET_CUE%"=="%CUE_RU%" (
        echo [*] Локализованный образ не найден. Запуск сборки build.bat...
        call "%SCRIPT_DIR%\build.bat"
    ) else (
        echo [ОШИБКА] Образ %TARGET_CUE% не найден!
        pause
        exit /b 1
    )
)

:: Поиск DuckStation
set "EMU="
if exist "%LOCALAPPDATA%\DuckStation\duckstation-qt-x64-ReleaseLTCG.exe" (
    set "EMU="%LOCALAPPDATA%\DuckStation\duckstation-qt-x64-ReleaseLTCG.exe""
)
if not defined EMU if exist "%ProgramFiles%\DuckStation\duckstation-qt.exe" (
    set "EMU="%ProgramFiles%\DuckStation\duckstation-qt.exe""
)
if not defined EMU (
    where duckstation-qt >nul 2>&1 && set "EMU=duckstation-qt"
)

if defined EMU (
    echo [*] Запуск DuckStation: !EMU! "%TARGET_CUE%"
    start "" !EMU! "%TARGET_CUE%"
) else (
    echo [*] DuckStation не найден. Запуск через системную ассоциацию...
    start "" "%TARGET_CUE%"
)
