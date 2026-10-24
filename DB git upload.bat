@echo off
setlocal
chcp 65001 >nul
title Guhyatama DB Upload - GitHub LFS
echo.
echo ============================================================
echo   Guhyatama-files - DB uploader
echo   No clone / no local Git repository
echo ============================================================
echo.
if "%~1"=="" (
    set /p "GDB_SOURCE=Enter DB folder path (or drag folder onto this BAT): "
) else (
    set "GDB_SOURCE=%~1"
)
if not defined GDB_SOURCE exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo Upload finished successfully.) else (echo Upload FAILED.)
echo.
pause
exit /b %RC%
