@echo off
rem ============================================================
rem  Universal Player - one-click launcher
rem  NOTE: keep this file ASCII-only. Chinese comments in a .bat
rem  get garbled under the default GBK codepage and break parsing.
rem ============================================================
setlocal

set "APP_DIR=%~dp0"
set "VENV_PY=C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

set "PY="
if exist "%VENV_PY%" set "PY=%VENV_PY%"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python not found.
    echo         Install Python 3.10+ and add it to PATH,
    echo         or edit VENV_PY inside this file.
    pause
    exit /b 1
)

echo [INFO] Python : %PY%
echo [INFO] AppDir  : %APP_DIR%

cd /d "%APP_DIR%"
"%PY%" main.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Exit code %errorlevel%
    echo Common cause: VLC runtime ^(libvlc^) not installed.
    echo Fix: install VLC player, or put a portable VLC
    echo      ^(with libvlc.dll^) into the "vlc" folder next to this file.
    pause
)
endlocal
