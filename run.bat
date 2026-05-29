@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Telegram DL Guard

if not exist venv\Scripts\python.exe (
    echo [SETUP] Creating venv...
    python -m venv venv
    call venv\Scripts\pip install -r requirements.txt
    echo [OK]
    goto menu
)
if "%~1"=="" goto menu

if "%~1"=="1" goto tui
if "%~1"=="2" goto setup
if "%~1"=="3" goto listen
if "%~1"=="4" goto update
goto menu

:menu
echo ========================================
echo   Telegram DL Guard v3.9
echo ========================================
echo   1 — Run DL Guard (Interactive TUI)
echo   2 — Setup Wizard (Initial Login)
echo   3 — Start Headless Daemon
echo   4 — Update/Verify Dependencies
echo   0 — Exit
echo ========================================
set /p c="> "
if "%c%"=="1" goto tui
if "%c%"=="2" goto setup
if "%c%"=="3" goto listen
if "%c%"=="4" goto update
if "%c%"=="0" exit /b
goto menu

:tui
set PYTHONUNBUFFERED=1
venv\Scripts\python tui.py
goto menu

:setup
venv\Scripts\python guard.py --setup
pause
goto menu

:listen
set PYTHONUNBUFFERED=1
venv\Scripts\python guard.py --listen
pause
goto menu

:update
venv\Scripts\python run.py 4
pause
goto menu
