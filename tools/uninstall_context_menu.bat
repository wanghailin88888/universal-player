@echo off
rem ============================================================
rem  Universal Player - context menu uninstaller (ASCII only)
rem ============================================================
setlocal

reg delete "HKCU\Software\Classes\Applications\UniversalPlayer.exe" /f >nul 2>&1
reg delete "HKCU\Software\Classes\*\shell\UniversalPlayer" /f >nul 2>&1

for %%E in (.mp4 .mkv .avi .mov .wmv .flv .ts .m4v .rmvb .rm .mpg .mpeg .webm .m2ts .mp3 .wav .flac .m4a .aac) do (
  reg delete "HKCU\Software\Classes\SystemFileAssociations\%%E\shell\UniversalPlayer" /f >nul 2>&1
)

echo [OK] Context menu entries removed.
pause
endlocal
