@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
    echo [SETUP] Creating venv and installing dependencies...
    python -m venv venv
    call venv\Scripts\pip install -r requirements.txt
    echo [OK] Ready.
    echo.
)

echo ========================================
echo   Telegram DL Guard v3.9
echo ========================================
echo.
echo   [1] Start listener (Guard mode)
echo   [2] Interactive dashboard (TUI)
echo   [3] First-run setup wizard
echo   [4] Settings menu
echo   [0] Exit
echo.
set /p choice="  Choose: "

if "%choice%"=="1" goto listen
if "%choice%"=="2" goto tui
if "%choice%"=="3" goto setup
if "%choice%"=="4" goto settings
if "%choice%"=="0" goto :eof
goto :eof

:listen
echo [Starting Listener — press Ctrl+C to stop]
set PYTHONUNBUFFERED=1
venv\Scripts\python guard.py --listen
pause
goto :eof

:tui
echo [Starting TUI — press q to quit]
set PYTHONUNBUFFERED=1
venv\Scripts\python tui.py
goto :eof

:setup
call venv\Scripts\python guard.py --setup
pause
goto :eof

:settings
call venv\Scripts\python guard.py
pause
goto :eof
