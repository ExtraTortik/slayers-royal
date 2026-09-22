@echo off
chcp 65001 > nul
title Slayers Royal Translation Studio (PS1)
cd /d "%~dp0"

echo ===================================================================
echo   Slayers Royal (PS1) - Translation Studio & Hardware Limits Engine
echo ===================================================================
echo.
echo [*] Starting local editor server...

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

echo [ERROR] Python was not found!
echo Please install Python 3 from https://www.python.org/
echo Make sure to check "Add Python to PATH" during installation.
echo.
pause
