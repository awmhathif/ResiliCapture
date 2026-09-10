@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set VERSION=0.7.0

echo [1/7] Creating build environment...
if not exist ".venv\Scripts\python.exe" python -m venv .venv || goto :fail
call .venv\Scripts\activate.bat

echo [2/7] Installing dependencies...
python -m pip install --upgrade pip || goto :fail
python -m pip install -r requirements-build.txt || goto :fail
python -m pip check || goto :fail

echo [3/7] Running automated tests...
python -m compileall -q app.py recorder ui platform_tools tests || goto :fail
python -m unittest discover -s tests -v || goto :fail

echo [4/7] Checking optional FFmpeg bundle...
if not exist "bin\ffmpeg.exe" echo WARNING: Put ffmpeg.exe in bin for H.264 recording, validation, and recovery.
if not exist "bin\ffprobe.exe" echo WARNING: Put ffprobe.exe in bin for full output verification.

echo [5/7] Building ResiliCapture...
python -m PyInstaller --noconfirm --clean ResiliCapture.spec || goto :fail

echo [6/7] Creating distribution ZIP...
if exist "dist\ResiliCapture-%VERSION%-Windows.zip" del /q "dist\ResiliCapture-%VERSION%-Windows.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\ResiliCapture\*' -DestinationPath 'dist\ResiliCapture-%VERSION%-Windows.zip'" || goto :fail

echo [7/7] Creating SHA-256 checksum...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$h=(Get-FileHash 'dist\ResiliCapture-%VERSION%-Windows.zip' -Algorithm SHA256).Hash.ToLower(); Set-Content -Encoding ascii 'dist\ResiliCapture-%VERSION%-Windows.zip.sha256' ($h + '  ResiliCapture-%VERSION%-Windows.zip')" || goto :fail

echo.
echo Build complete:
echo   dist\ResiliCapture\ResiliCapture.exe
echo   dist\ResiliCapture-%VERSION%-Windows.zip
echo   dist\ResiliCapture-%VERSION%-Windows.zip.sha256
pause
exit /b 0

:fail
echo.
echo Build failed. Read the error above.
pause
exit /b 1
