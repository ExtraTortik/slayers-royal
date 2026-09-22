@echo off
chcp 65001 > nul
title Slayers Royal Translation Studio (PS1)
cd /d "%~dp0"

echo ===================================================================
echo   Slayers Royal (PS1) — Редактор локализации и аппаратных лимитов
echo ===================================================================
echo.
echo [*] Запуск локального сервера редактора...

where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    start "" http://127.0.0.1:8765/
    py tools\web_translation_editor.py --host 127.0.0.1 --port 8765
    goto :eof
)

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    start "" http://127.0.0.1:8765/
    python tools\web_translation_editor.py --host 127.0.0.1 --port 8765
    goto :eof
)

where python3 >nul 2>&1
if %ERRORLEVEL% equ 0 (
    start "" http://127.0.0.1:8765/
    python3 tools\web_translation_editor.py --host 127.0.0.1 --port 8765
    goto :eof
)

echo [ОШИБКА] Python не найден в системе!
echo Пожалуйста, установите Python 3 с официального сайта: https://www.python.org/
echo При установке обязательно отметьте галочку "Add Python to PATH".
echo.
pause
