@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
    echo Installing...
    python -m venv venv
    call venv\Scripts\pip install -r requirements.txt
)

echo.
echo   [1] Start listening
echo   [2] Settings menu
echo.
set /p choice="  Choose: "
if "%choice%"=="1" goto listen
if "%choice%"=="2" goto settings
goto :eof

:listen
set PYTHONUNBUFFERED=1
venv\Scripts\python guard.py --listen
pause
goto :eof

:settings
venv\Scripts\python guard.py
pause
goto :eof
