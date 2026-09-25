@echo off
chcp 65001 > nul
title Slayers Royal Font Pixel Editor (PS1)
cd /d "%~dp0"

echo ===================================================================
echo   Slayers Royal (PS1) - Compact Font Pixel Editor (16x16 Canvas)
echo ===================================================================
echo.
echo [*] Starting local font editor server...

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

echo [ERROR] Python was not found!
echo Please install Python 3 from https://www.python.org/
echo Make sure to check "Add Python to PATH" during installation.
echo.
pause
