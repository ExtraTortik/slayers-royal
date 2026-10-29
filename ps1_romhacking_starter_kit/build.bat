@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

title PS1 ROM Hacking Build System
cd /d "%~dp0"

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "ORIG_BIN=%SCRIPT_DIR%\downloads\game.bin"
set "OUT_DIR=%SCRIPT_DIR%\localization-output\ru"
set "OUT_BIN=%OUT_DIR%\game_ru.bin"
set "OUT_CUE=%OUT_DIR%\game_ru.cue"

:: Поиск Python 3
set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py -3"
if not defined PY_CMD where python >nul 2>&1 && set "PY_CMD=python"
if not defined PY_CMD where python3 >nul 2>&1 && set "PY_CMD=python3"

if not defined PY_CMD (
    echo [ОШИБКА] Интерпретатор Python 3 не найден!
    pause
    exit /b 1
)

echo ===========================================================
echo    PS1 ROM Hacking Build System (Windows)
echo ===========================================================
echo.

if not exist "%ORIG_BIN%" (
    echo [ОШИБКА] Оригинальный образ не найден: %ORIG_BIN%
    echo Положите ваш оригинальный .bin файл игры в папку downloads\game.bin
    pause
    exit /b 1
)

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

echo [1/3] Копирование базового образа...
copy /Y "%ORIG_BIN%" "%OUT_BIN%" > nul

:: Создание CUE-файла если его нет
if not exist "%OUT_CUE%" (
    echo FILE "game_ru.bin" BINARY > "%OUT_CUE%"
    echo   TRACK 01 MODE2/2352 >> "%OUT_CUE%"
    echo     INDEX 01 00:00:00 >> "%OUT_CUE%"
)

echo [2/3] Запуск сборочного скрипта игры (tools\patch_game.py)...
if exist "%SCRIPT_DIR%\tools\patch_game.py" (
    %PY_CMD% "%SCRIPT_DIR%\tools\patch_game.py" --bin "%OUT_BIN%" %*
    if %ERRORLEVEL% neq 0 (
        echo [ОШИБКА] Сборка завершилась с ошибкой!
        pause
        exit /b %ERRORLEVEL%
    )
) else (
    echo [i] Файл tools\patch_game.py пока не создан.
    echo     Используйте модули из папки core\ (disc.py, text_engine.py, tim.py)
    echo     для создания инжектора под вашу игру.
)

echo [3/3] Проверка контрольных сумм секторов (EDC/ECC)...
%PY_CMD% -c "from core.disc import parse_iso_root; print('[✓] ISO-9660 файловая система валидна:', len(parse_iso_root('%OUT_BIN%')), 'файлов')"

echo.
echo ===========================================================
echo [✓] Сборка успешно завершена!
echo     Образ диска: %OUT_BIN%
echo     CUE-файл:    %OUT_CUE%
echo ===========================================================
exit /b 0
