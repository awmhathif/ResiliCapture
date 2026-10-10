@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
rem Public packages never include arbitrary locally installed FFmpeg binaries.
set RESILICAPTURE_BUNDLE_FFMPEG=0

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

echo [4/7] Checking architecture...
python -c "import struct; assert struct.calcsize('P') == 8, 'Use 64-bit Python for the Windows release'" || goto :fail

echo [5/7] Building ResiliCapture...
python -m PyInstaller --noconfirm --clean ResiliCapture.spec || goto :fail

echo [6/7] Packaging complete app and testing extracted executable...
python scripts\package_windows.py || goto :fail
echo [7/7] ZIP and SHA-256 checksum ready.

echo.
echo Build complete:
echo   dist\ResiliCapture\ResiliCapture.exe
echo   dist\ResiliCapture-*-Windows.zip
echo   dist\ResiliCapture-*-Windows.zip.sha256
echo Upload the ZIP and checksum together. Never upload only ResiliCapture.exe.
pause
exit /b 0

:fail
echo.
echo Build failed. Read the error above.
pause
exit /b 1
