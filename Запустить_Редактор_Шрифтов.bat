@echo off
chcp 65001 > nul
title Slayers Royal Редактор Шрифтов (PS1)
cd /d "%~dp0"

echo ===================================================================
echo   Slayers Royal (PS1) — Редактор пиксельных шрифтов (16x16)
echo ===================================================================
echo.
echo [*] Запуск локального сервера редактора шрифтов...

where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    start "" http://127.0.0.1:8766/
    py tools\font_pixel_editor.py --host 127.0.0.1 --port 8766
    goto :eof
)

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    start "" http://127.0.0.1:8766/
    python tools\font_pixel_editor.py --host 127.0.0.1 --port 8766
    goto :eof
)

where python3 >nul 2>&1
if %ERRORLEVEL% equ 0 (
    start "" http://127.0.0.1:8766/
    python3 tools\font_pixel_editor.py --host 127.0.0.1 --port 8766
    goto :eof
)

echo [ОШИБКА] Python не найден в системе!
echo Пожалуйста, установите Python 3 с официального сайта: https://www.python.org/
echo При установке обязательно отметьте галочку "Add Python to PATH".
echo.
pause
