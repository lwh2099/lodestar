@echo off
rem ============================================================
rem  Lodestar launcher
rem  First run: creates a virtual environment and installs
rem  dependencies (takes a few minutes). After that: instant.
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [Lodestar] First run: creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [Lodestar] ERROR: Python 3.11+ not found. Install it from python.org and retry.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo [Lodestar] Installing dependencies ^(one-time, a few minutes^)...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [Lodestar] ERROR: dependency install failed. Check your connection and retry.
        pause
        exit /b 1
    )
)

echo [Lodestar] Starting... the dashboard will open in your browser.
echo [Lodestar] Keep this window open while using the app. Close it to stop.
".venv\Scripts\python.exe" -m streamlit run app.py

pause
