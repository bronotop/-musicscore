@echo off
setlocal
cd /d "%~dp0"
title music2score
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" %*
if errorlevel 1 (
    echo.
    echo Startup failed. See the message above.
    pause
)
endlocal
