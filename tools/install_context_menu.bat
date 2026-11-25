@echo off
rem ============================================================
rem  Universal Player - context menu installer (ASCII only)
rem  Run as the user (no admin needed): registers to HKCU.
rem  Usage: place this file next to the EXE, then double click.
rem ============================================================
setlocal
set "EXE=%~dp0UniversalPlayer.exe"
if not exist "%EXE%" set "EXE=%~dp0%\UniversalPlayer.exe"

echo This script registers "Open with Universal Player" to the right-click menu.
echo It assumes the player EXE is named: UniversalPlayer.exe
echo.

if not exist "%EXE%" (
  echo [WARN] EXE not found next to this script: %EXE%
  echo [WARN] Registry will still be written, but update the path later.
)

reg add "HKCU\Software\Classes\Applications\UniversalPlayer.exe" /v "FriendlyAppName" /t REG_SZ /d "Universal Player" /f >nul
reg add "HKCU\Software\Classes\Applications\UniversalPlayer.exe\shell\open\command" /ve /t REG_SZ /d "\"%EXE%\" \"%%1\"" /f >nul
reg add "HKCU\Software\Classes\Applications\UniversalPlayer.exe\DefaultIcon" /ve /t REG_SZ /d "\"%EXE%\",0" /f >nul

rem Right-click entry for all files
reg add "HKCU\Software\Classes\*\shell\UniversalPlayer" /ve /t REG_SZ /d "Play with Universal Player" /f >nul
reg add "HKCU\Software\Classes\*\shell\UniversalPlayer" /v "Icon" /t REG_SZ /d "\"%EXE%\",0" /f >nul
reg add "HKCU\Software\Classes\*\shell\UniversalPlayer\command" /ve /t REG_SZ /d "\"%EXE%\" \"%%1\"" /f >nul

rem Common media extensions: direct entry on top level menu
for %%E in (.mp4 .mkv .avi .mov .wmv .flv .ts .m4v .rmvb .rm .mpg .mpeg .webm .m2ts .mp3 .wav .flac .m4a .aac) do (
  reg add "HKCU\Software\Classes\SystemFileAssociations\%%E\shell\UniversalPlayer" /ve /t REG_SZ /d "Play with Universal Player" /f >nul
  reg add "HKCU\Software\Classes\SystemFileAssociations\%%E\shell\UniversalPlayer" /v "Icon" /t REG_SZ /d "\"%EXE%\",0" /f >nul
  reg add "HKCU\Software\Classes\SystemFileAssociations\%%E\shell\UniversalPlayer\command" /ve /t REG_SZ /d "\"%EXE%\" \"%%1\"" /f >nul
)

echo [OK] Registered. Right-click a video file and you should see the entry.
echo [OK] If it does not show, log off / reboot once (Windows shell cache).
pause
endlocal
