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

if "%~1"=="1" goto listen
if "%~1"=="2" goto tui
if "%~1"=="3" goto setup
if "%~1"=="4" goto guard
goto menu

:menu
echo ========================================
echo   Telegram DL Guard
echo ========================================
echo   1 — Start listener
echo   2 — Interactive TUI
echo   3 — Setup wizard
echo   4 — Settings
echo   0 — Exit
echo ========================================
set /p c="> "
if "%c%"=="1" goto listen
if "%c%"=="2" goto tui
if "%c%"=="3" goto setup
if "%c%"=="4" goto guard
if "%c%"=="0" exit /b
goto menu

:listen
set PYTHONUNBUFFERED=1
venv\Scripts\python guard.py --listen
pause
goto menu

:tui
set PYTHONUNBUFFERED=1
venv\Scripts\python tui.py
goto menu

:setup
venv\Scripts\python guard.py --setup
pause
goto menu

:guard
venv\Scripts\python guard.py
pause
goto menu
