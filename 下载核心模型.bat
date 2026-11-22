@echo off
setlocal
cd /d "%~dp0"
if not defined MUSIC2SCORE_HOME set "MUSIC2SCORE_HOME=%~dp0runtime"
title music2score - core models
if not exist ".venv\Scripts\python.exe" (
    echo Please run the main launcher first to install the environment.
    pause
    exit /b 1
)
echo Downloading core models (Demucs / GAME / Whisper small)...
".venv\Scripts\python.exe" scripts\download_demucs.py
".venv\Scripts\python.exe" scripts\download_game.py --size medium
".venv\Scripts\python.exe" scripts\download_whisper.py --size small
echo.
echo Done.
pause
endlocal
