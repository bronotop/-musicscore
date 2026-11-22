@echo off
setlocal
cd /d "%~dp0"
if not defined MUSIC2SCORE_HOME set "MUSIC2SCORE_HOME=%~dp0runtime"
title music2score - MuScriptor models
if not exist ".venv\Scripts\python.exe" (
    echo Please run the main launcher first to install the environment.
    pause
    exit /b 1
)
echo Downloading MuScriptor weights (~1.2 GB, CC BY-NC 4.0, non-commercial only)...
".venv\Scripts\python.exe" scripts\fetch_muscriptor_mirror.py
echo.
echo Done. MuScriptor weights are for non-commercial use only.
pause
endlocal
