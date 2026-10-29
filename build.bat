@echo off
chcp 65001 > nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
setlocal enabledelayedexpansion

title Slayers Royal (PS1) - Сборщик локализации
cd /d "%~dp0"

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "BIN_ORIG=%SCRIPT_DIR%\downloads\sr.bin"
set "RU_DIR=%SCRIPT_DIR%\localization-output\ru"
set "RU_BIN=%RU_DIR%\slayers_royal_ru.bin"
set "RU_CUE=%RU_DIR%\slayers_royal_ru.cue"
set "INSPECTION_JSON=%SCRIPT_DIR%\translations\room_inspection_ru.json"
set "ROOM_NAMES_JSON=%SCRIPT_DIR%\translations\room_names_ru.json"
set "CARDS_JSON=%SCRIPT_DIR%\translations\lore_cards_ru.json"
set "COMBAT_JSON=%SCRIPT_DIR%\translations\combat_ru.json"
set "COMBAT_DIALOGUES_JSON=%SCRIPT_DIR%\translations\combat_dialogues_ru.json"
set "SPELLS_JSON=%SCRIPT_DIR%\translations\spells_ru.json"
set "MAP_JSON=%SCRIPT_DIR%\translations\world_map_ru.json"
set "BANNERS_JSON=%SCRIPT_DIR%\translations\location_banners_ru.json"
set "TOWN_SERVICES_JSON=%SCRIPT_DIR%\translations\town_services_ru.json"
set "SHOP_DIALOGUES_JSON=%SCRIPT_DIR%\translations\shop_dialogues_ru.json"
set "MINIGAMES_JSON=%SCRIPT_DIR%\translations\minigames_ru.json"
set "MINIGAMES_MENU_JSON=%SCRIPT_DIR%\translations\minigames_menu_ru.json"
set "STORY_JSON=%SCRIPT_DIR%\translations\story_dialogues_ru.json"
set "BONUS_MENU_JSON=%SCRIPT_DIR%\translations\bonus_menu_ru.json"
set "INDEX_JSON=%SCRIPT_DIR%\translations\translations_index.json"
set "TOWN_MAPS_JSON=%SCRIPT_DIR%\translations\town_maps_ru.json"
set "TOWN_MAPS_DIR=%SCRIPT_DIR%\data\custom_town_maps"
set "CUSTOM_HUD_DIR=%SCRIPT_DIR%\data\custom_hud_textures"
set "CUSTOM_SCREENS_DIR=%SCRIPT_DIR%\data\custom_screens"
set "EXTRA_SCREENS_DIR=%SCRIPT_DIR%\data\extra_screens"
set "PATCH_REPO_DIR=%SCRIPT_DIR%\patch_repo"

:: --- Поиск интерпретатора Python 3 ---
set "PYTHON_CMD="
where py >nul 2>&1
if %ERRORLEVEL% equ 0 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD where python >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD where python3 >nul 2>&1 && set "PYTHON_CMD=python3"

if not defined PYTHON_CMD (
    echo [ОШИБКА] Интерпретатор Python 3 не найден!
    echo Установите Python 3 с официального сайта https://www.python.org/
    echo Не забудьте отметить галочку "Add Python to PATH" при установке.
    echo.
    pause
    exit /b 1
)

echo ===========================================================
echo    Slayers Royal (PS1) — Сборщик локализации (Windows)
echo ===========================================================
echo.

if "%~1"=="--help" goto :show_help
if "%~1"=="-h" goto :show_help
if "%~1"=="/?" goto :show_help

%PYTHON_CMD% "%SCRIPT_DIR%\tools\ensure_patch_repo.py"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

:: --- Диспетчеризация опций ---
if "%~1"=="--validate" goto :do_validate
if "%~1"=="--story" goto :do_story
if "%~1"=="--dialogues" goto :do_story
if "%~1"=="--quick" goto :do_quick
if "%~1"=="-q" goto :do_quick
if "%~1"=="--inspection" goto :do_quick
if "%~1"=="--cards" goto :do_cards
if "%~1"=="--map" goto :do_map
if "%~1"=="--banners" goto :do_banners
if "%~1"=="--status-ui" goto :do_status_ui
if "%~1"=="--tabs" goto :do_status_ui
if "%~1"=="--combat" goto :do_combat
if "%~1"=="--combat-dialogues" goto :do_combat
if "%~1"=="--spells" goto :do_spells
if "%~1"=="--services" goto :do_services
if "%~1"=="--town" goto :do_services
if "%~1"=="--shops" goto :do_shops
if "%~1"=="--shop-dialogues" goto :do_shops
if "%~1"=="--minigames" goto :do_minigames
if "%~1"=="--quiz" goto :do_minigames
if "%~1"=="--bonus-menu" goto :do_bonus_menu
if "%~1"=="--title-menu" goto :do_bonus_menu
if "%~1"=="--town-maps" goto :do_town_maps
if "%~1"=="--maps" goto :do_town_maps
if "%~1"=="--hud" goto :do_hud
if "%~1"=="--e8" goto :do_hud
if "%~1"=="--title-logo" goto :do_title_logo
if "%~1"=="--logo" goto :do_title_logo
if "%~1"=="--custom-screens" goto :do_custom_screens
if "%~1"=="--screens" goto :do_custom_screens
if "%~1"=="--extra-screens" goto :do_extra_screens

:: ===========================================================
:: ПОЛНАЯ СБОРКА (DEFAULT)
:: ===========================================================
echo [*] Запуск полной сборки русской версии...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\prepare_game.py"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

if not exist "%RU_DIR%" mkdir "%RU_DIR%"

echo [1/9] Синхронизация и компиляция сюжетных диалогов...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\sync_story_dialogues.py" --sync-if-newer
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

%PYTHON_CMD% "%SCRIPT_DIR%\tools\localize_ru.py" build --bin "%BIN_ORIG%" --output-dir "%RU_DIR%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

call :run_guards
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

echo [2/9] Внедрение видеороликов с русскими субтитрами...
if exist "%SCRIPT_DIR%\build\movies\MOVIE.STR" (
    %PYTHON_CMD% "%SCRIPT_DIR%\tools\fmv_pipeline.py" --inject-disc "%RU_BIN%" --movies-dir "%SCRIPT_DIR%\build\movies"
    if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
) else (
    echo     ^(build\movies отсутствует — видеоролики остаются оригинальными^)
)

echo [3/9] Патчинг описаний 149 интерактивных комнат...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_inspection.py" --bin "%RU_BIN%" --translations "%INSPECTION_JSON%" --room-names "%ROOM_NAMES_JSON%" --all-rooms
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

echo [4/9] Внедрение энциклопедических карточек персонажей...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_lore_cards.py" --disc "%RU_BIN%" --cards "%CARDS_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

echo [5/9] Патчинг названий локаций карты мира и графических плашек...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_world_map.py" --bin "%RU_BIN%" --catalog "%MAP_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_location_banners.py" --bin "%RU_BIN%" --catalog "%BANNERS_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

if exist "%SCRIPT_DIR%\data\preview_basyog_162_ru.png" (
    echo [*] Патчинг атласа меню персонажей...
    %PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_basyog_162.py" --bin "%RU_BIN%"
    if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
)

echo [6/9] Патчинг боевого режима (шрифт 0x142, UI, 114 диалогов, заклинания)...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_combat.py" --bin "%RU_BIN%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_combat_dialogues.py" --bin "%RU_BIN%" --catalog "%COMBAT_DIALOGUES_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_spells.py" --bin "%RU_BIN%" --catalog "%SPELLS_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_spell_menu_ru.py" --bin "%RU_BIN%" --catalog "%SPELLS_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

echo [7/9] Внедрение дополнительных экранов и текстур...
if exist "%TOWN_MAPS_DIR%\*.png" (
    %PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_town_maps.py" --bin "%RU_BIN%" --maps-dir "%TOWN_MAPS_DIR%"
    if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
)
if exist "%CUSTOM_HUD_DIR%\*.png" (
    %PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_e8_textures.py" --bin "%RU_BIN%"
    if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
)
if exist "%CUSTOM_SCREENS_DIR%\*.png" (
    %PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_custom_screens.py" --bin "%RU_BIN%" --screens-dir "%CUSTOM_SCREENS_DIR%"
    if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
)
if exist "%EXTRA_SCREENS_DIR%\*.png" (
    %PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_extra_screens.py" --bin "%RU_BIN%"
    if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
)
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_title_logo.py" --bin "%RU_BIN%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

echo [8/9] Патчинг городских служб, отелей, магазинов и меню...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_town_services.py" --bin "%RU_BIN%" --catalog "%TOWN_SERVICES_JSON%" --shop-catalog "%SHOP_DIALOGUES_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

echo [9/9] Патчинг мини-игр, викторины и меню бонусов...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_minigames.py" --bin "%RU_BIN%" --catalog "%MINIGAMES_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_minigames_menu.py" --bin "%RU_BIN%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_bonus_menu.py" --bin "%RU_BIN%" --catalog "%BONUS_MENU_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

call :run_guards
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!

if not exist "%PATCH_REPO_DIR%\localization-output\ru" mkdir "%PATCH_REPO_DIR%\localization-output\ru"
xcopy /E /Y /I "%RU_DIR%\*" "%PATCH_REPO_DIR%\localization-output\ru\" >nul 2>&1

echo ===========================================================
echo [✓] Полная сборка русской версии успешно завершена!
echo     Готовый образ: localization-output\ru\slayers_royal_ru.bin
echo     Для запуска:   run_game.bat
echo ===========================================================
exit /b 0

:: ===========================================================
:: ПОДПРОГРАММЫ ОПЦИЙ
:: ===========================================================

:run_guards
echo [*] Проверка карты глифов (glyph_map.json ↔ translations/glyph_map_ru.json)...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\vram_charmap.py" --check
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
echo [*] Проверка бюджета сцен PROG.UNT (<= 19 секторов на сцену)...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\verify_scene_budget.py" --bin "%RU_BIN%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
exit /b %ERRORLEVEL%

:do_validate
echo [*] Валидация сюжетных диалогов...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\sync_story_dialogues.py" --validate
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
echo [*] Валидация каталога диалогов...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\localize_ru.py" validate --bin "%BIN_ORIG%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
call :run_guards
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
echo [*] Валидация боевого режима...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_combat.py" --verify --bin "%RU_BIN%" --mode ru
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\combat_text.py" --verify
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_combat_dialogues.py" --verify --bin "%RU_BIN%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_spells.py" --verify --bin "%RU_BIN%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_spell_menu_ru.py" --verify --bin "%RU_BIN%" --catalog "%SPELLS_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
echo [*] Валидация карты и плашек...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_world_map.py" --verify
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_location_banners.py" --verify
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
echo [*] Валидация служб и мини-игр...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_town_services.py" --verify
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_minigames.py" --verify
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_minigames_menu.py" --verify
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_bonus_menu.py" --verify --bin "%RU_BIN%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
echo [✓] Комплексная валидация успешно пройдена!
exit /b 0

:do_story
echo [*] Быстрая сборка сюжетных диалогов...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\prepare_game.py"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
if not exist "%RU_DIR%" mkdir "%RU_DIR%"
%PYTHON_CMD% "%SCRIPT_DIR%\tools\localize_ru.py" build --bin "%BIN_ORIG%" --output-dir "%RU_DIR%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
call :run_guards
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
if exist "%SCRIPT_DIR%\build\movies\MOVIE.STR" (
    %PYTHON_CMD% "%SCRIPT_DIR%\tools\fmv_pipeline.py" --inject-disc "%RU_BIN%" --movies-dir "%SCRIPT_DIR%\build\movies"
) else (
    echo     ^(build\movies отсутствует — видеоролики остаются оригинальными^)
)
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_inspection.py" --bin "%RU_BIN%" --translations "%INSPECTION_JSON%" --room-names "%ROOM_NAMES_JSON%" --all-rooms
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_lore_cards.py" --disc "%RU_BIN%" --cards "%CARDS_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_world_map.py" --bin "%RU_BIN%" --catalog "%MAP_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_location_banners.py" --bin "%RU_BIN%" --catalog "%BANNERS_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_combat.py" --bin "%RU_BIN%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_combat_dialogues.py" --bin "%RU_BIN%" --catalog "%COMBAT_DIALOGUES_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_spells.py" --bin "%RU_BIN%" --catalog "%SPELLS_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_spell_menu_ru.py" --bin "%RU_BIN%" --catalog "%SPELLS_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_town_services.py" --bin "%RU_BIN%" --catalog "%TOWN_SERVICES_JSON%" --shop-catalog "%SHOP_DIALOGUES_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_minigames.py" --bin "%RU_BIN%" --catalog "%MINIGAMES_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_minigames_menu.py" --bin "%RU_BIN%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_bonus_menu.py" --bin "%RU_BIN%" --catalog "%BONUS_MENU_JSON%"
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL%
if exist "%TOWN_MAPS_DIR%\*.png" (
    echo [*] Внедрение пользовательских карт городов (BASYOG.UNT 467..476)...
    %PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_town_maps.py" --bin "%RU_BIN%" --maps-dir "%TOWN_MAPS_DIR%"
    if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
)
if exist "%CUSTOM_HUD_DIR%\*.png" (
    echo [*] Внедрение атласа интерфейса/HUD (PROG.UNT 0x008)...
    %PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_e8_textures.py" --bin "%RU_BIN%"
    if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
)
if exist "%CUSTOM_SCREENS_DIR%\*.png" (
    echo [*] Внедрение пользовательских экранов (OPT 203, 221, 225; PROG 323)...
    %PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_custom_screens.py" --bin "%RU_BIN%" --screens-dir "%CUSTOM_SCREENS_DIR%"
    if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
)
if exist "%EXTRA_SCREENS_DIR%\*.png" (
    echo [*] Внедрение дополнительных экранов и текстур...
    %PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_extra_screens.py" --bin "%RU_BIN%"
    if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
) else if exist "%SCRIPT_DIR%\еще переводы\*.png" (
    echo [*] Внедрение дополнительных экранов и текстур...
    %PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_extra_screens.py" --bin "%RU_BIN%"
    if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
)
call :run_guards
if !ERRORLEVEL! neq 0 exit /b !ERRORLEVEL!
if not exist "%PATCH_REPO_DIR%\localization-output\ru" mkdir "%PATCH_REPO_DIR%\localization-output\ru"
xcopy /E /Y /I "%RU_DIR%\*" "%PATCH_REPO_DIR%\localization-output\ru\" >nul 2>&1
echo [✓] Сюжетные диалоги успешно обновлены!
exit /b 0

:do_quick
echo [*] Быстрое обновление описаний комнат...
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_inspection.py" --bin "%RU_BIN%" --translations "%INSPECTION_JSON%" --room-names "%ROOM_NAMES_JSON%" --all-rooms
xcopy /E /Y /I "%RU_DIR%\*" "%PATCH_REPO_DIR%\localization-output\ru\" >nul 2>&1
echo [✓] Описания комнат обновлены!
exit /b 0

:do_cards
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_lore_cards.py" --disc "%RU_BIN%" --cards "%CARDS_JSON%"
xcopy /E /Y /I "%RU_DIR%\*" "%PATCH_REPO_DIR%\localization-output\ru\" >nul 2>&1
echo [✓] Карточки персонажей обновлены!
exit /b 0

:do_map
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_world_map.py" --bin "%RU_BIN%" --catalog "%MAP_JSON%"
echo [✓] Карта мира обновлена!
exit /b 0

:do_banners
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_location_banners.py" --bin "%RU_BIN%" --catalog "%BANNERS_JSON%"
echo [✓] Плашки локаций обновлены!
exit /b 0

:do_status_ui
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_basyog_162.py" --bin "%RU_BIN%"
echo [✓] Меню персонажей обновлено!
exit /b 0

:do_combat
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_combat.py" --bin "%RU_BIN%"
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_combat_dialogues.py" --bin "%RU_BIN%" --catalog "%COMBAT_DIALOGUES_JSON%"
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_spells.py" --bin "%RU_BIN%" --catalog "%SPELLS_JSON%"
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_spell_menu_ru.py" --bin "%RU_BIN%" --catalog "%SPELLS_JSON%"
xcopy /E /Y /I "%RU_DIR%\*" "%PATCH_REPO_DIR%\localization-output\ru\" >nul 2>&1
echo [✓] Боевой режим обновлен!
exit /b 0

:do_spells
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_spells.py" --bin "%RU_BIN%" --catalog "%SPELLS_JSON%"
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_spell_menu_ru.py" --bin "%RU_BIN%" --catalog "%SPELLS_JSON%"
echo [✓] Заклинания обновлены!
exit /b 0

:do_services
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_town_services.py" --bin "%RU_BIN%" --catalog "%TOWN_SERVICES_JSON%" --shop-catalog "%SHOP_DIALOGUES_JSON%"
echo [✓] Городские службы обновлены!
exit /b 0

:do_shops
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_town_services.py" --bin "%RU_BIN%" --catalog "%SHOP_DIALOGUES_JSON%" --shops-only
echo [✓] Диалоги лавок обновлены!
exit /b 0

:do_minigames
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_minigames.py" --bin "%RU_BIN%" --catalog "%MINIGAMES_JSON%"
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_minigames_menu.py" --bin "%RU_BIN%"
echo [✓] Мини-игры и меню обновлены!
exit /b 0

:do_bonus_menu
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_bonus_menu.py" --bin "%RU_BIN%" --catalog "%BONUS_MENU_JSON%"
echo [✓] Меню бонусов обновлено!
exit /b 0

:do_town_maps
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_town_maps.py" --bin "%RU_BIN%" --maps-dir "%TOWN_MAPS_DIR%"
echo [✓] Карты городов обновлены!
exit /b 0

:do_hud
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_e8_textures.py" --bin "%RU_BIN%"
echo [✓] Атлас интерфейса HUD обновлен!
exit /b 0

:do_title_logo
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_title_logo.py" --bin "%RU_BIN%"
echo [✓] Логотип титульного экрана обновлен!
exit /b 0

:do_custom_screens
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_custom_screens.py" --bin "%RU_BIN%" --screens-dir "%CUSTOM_SCREENS_DIR%"
echo [✓] Пользовательские экраны обновлены!
exit /b 0

:do_extra_screens
%PYTHON_CMD% "%SCRIPT_DIR%\tools\patch_extra_screens.py" --bin "%RU_BIN%"
echo [✓] Дополнительные экраны обновлены!
exit /b 0

:show_help
echo Использование: build.bat [опция]
echo.
echo Опции:
echo   (без опций)  Полная сборка: сюжет + FMV + 149 комнат + карточки + плашки + бой + службы + мини-игры
echo   --quick, -q  Быстрая сборка: обновить ТОЛЬКО описания предметов (~1.5 сек)
echo   --story      Быстрая сборка: обновить сюжетные диалоги и базовый образ (~12 сек)
echo   --combat     Обновить боевые диалоги и заклинания
echo   --services   Обновить городские службы, магазины и меню
echo   --minigames  Обновить правила мини-игр, викторину и меню выбора
echo   --validate   Проверить каталоги диалогов, комнат, карт, плашек и мини-игр на ошибки
echo   --help, -h   Показать эту справку
exit /b 0
