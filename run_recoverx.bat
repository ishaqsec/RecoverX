@echo off
title RecoverX — Advanced Data Recovery Tool
cd /d "%~dp0"

:: Request Administrator privileges automatically so raw NTFS/FAT32/exFAT sector scanning works on C:/D:
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [RecoverX] Requesting Administrator privileges for low-level read-only disk access...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" >nul 2>&1
    if %ERRORLEVEL% EQU 0 exit /b
)

if not exist ".venv" (
    echo [RecoverX] Creating Python virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate
echo [RecoverX] Verifying dependencies...
pip install --quiet --disable-pip-version-check -r requirements.txt

echo [RecoverX] Launching RecoverX GUI...
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [RecoverX] Process exited with code %ERRORLEVEL%.
    pause
)
