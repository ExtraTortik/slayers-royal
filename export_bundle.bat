@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

title Сборка пакета для передачи на другой компьютер
cd /d "%~dp0"

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "BUNDLE_NAME=slayers_royal_transfer_bundle"
set "BUNDLE_DIR=%SCRIPT_DIR%\%BUNDLE_NAME%"
set "ARCHIVE_ZIP=%SCRIPT_DIR%\%BUNDLE_NAME%.zip"

echo ==================================================================
echo    Подготовка чистого пакета для передачи: %BUNDLE_NAME%
echo ==================================================================
echo.

if exist "%BUNDLE_DIR%" rmdir /s /q "%BUNDLE_DIR%"
if exist "%ARCHIVE_ZIP%" del /q "%ARCHIVE_ZIP%"
mkdir "%BUNDLE_DIR%"

echo [1/5] Копирование документации и инструкций...
copy "%SCRIPT_DIR%\INSTRUCTIONS_FOR_NEW_MACHINE.md" "%BUNDLE_DIR%\" >nul
copy "%SCRIPT_DIR%\hand_off.md" "%BUNDLE_DIR%\" >nul
copy "%SCRIPT_DIR%\EMULATOR_DEBUGGING_GUIDE.md" "%BUNDLE_DIR%\" >nul
copy "%SCRIPT_DIR%\PS1_ROMHACKING_GUIDE_WINDOWS.md" "%BUNDLE_DIR%\" >nul
copy "%SCRIPT_DIR%\MINIGAME_LUNCH_SPEC.md" "%BUNDLE_DIR%\" >nul
xcopy /E /I /Q /Y "%SCRIPT_DIR%\docs" "%BUNDLE_DIR%\docs" >nul 2>&1

echo [2/5] Копирование лаунчеров и сборочных скриптов...
copy "%SCRIPT_DIR%\start_project.sh" "%BUNDLE_DIR%\" >nul
copy "%SCRIPT_DIR%\start_project.bat" "%BUNDLE_DIR%\" >nul
copy "%SCRIPT_DIR%\build.sh" "%BUNDLE_DIR%\" >nul
copy "%SCRIPT_DIR%\build.bat" "%BUNDLE_DIR%\" >nul
copy "%SCRIPT_DIR%\run_game.sh" "%BUNDLE_DIR%\" >nul
copy "%SCRIPT_DIR%\run_game.bat" "%BUNDLE_DIR%\" >nul
copy "%SCRIPT_DIR%\Собрать_Перевод.bat" "%BUNDLE_DIR%\" >nul
copy "%SCRIPT_DIR%\Запустить_Игру_PS1.bat" "%BUNDLE_DIR%\" >nul
copy "%SCRIPT_DIR%\requirements.txt" "%BUNDLE_DIR%\" >nul

echo [3/5] Копирование конфигурации агентов...
xcopy /E /I /Q /Y "%SCRIPT_DIR%\agent_config" "%BUNDLE_DIR%\agent_config" >nul

echo [4/5] Копирование каталогов (translations, tools, data, fonts, patch_repo)...
xcopy /E /I /Q /Y "%SCRIPT_DIR%\translations" "%BUNDLE_DIR%\translations" >nul
xcopy /E /I /Q /Y "%SCRIPT_DIR%\tools" "%BUNDLE_DIR%\tools" >nul
xcopy /E /I /Q /Y "%SCRIPT_DIR%\data" "%BUNDLE_DIR%\data" >nul
xcopy /E /I /Q /Y "%SCRIPT_DIR%\fonts" "%BUNDLE_DIR%\fonts" >nul
if exist "%SCRIPT_DIR%\patch_repo" (
    xcopy /E /I /Q /Y "%SCRIPT_DIR%\patch_repo" "%BUNDLE_DIR%\patch_repo" >nul
)

echo [*] Очистка временных файлов кэша...
for /d /r "%BUNDLE_DIR%" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" >nul 2>&1
for /d /r "%BUNDLE_DIR%" %%d in (.pytest_cache) do @if exist "%%d" rd /s /q "%%d" >nul 2>&1
del /s /q "%BUNDLE_DIR%\*.pyc" >nul 2>&1

echo [5/5] Создание ZIP-архива через PowerShell...
powershell -Command "Compress-Archive -Path '%BUNDLE_DIR%' -DestinationPath '%ARCHIVE_ZIP%' -Force"

echo.
echo ==================================================================
echo    Пакет успешно сформирован и готов к передаче!
echo    Папка:  %BUNDLE_DIR%
echo    Архив:  %ARCHIVE_ZIP%
echo ==================================================================
pause
