@echo off
setlocal
cd /d "%~dp0"
echo Downloading FFmpeg from gyan.dev for this copy of ResiliCapture.
echo This enables H.264 recording, MP4 verification, and recovery.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_ffmpeg.ps1"
if errorlevel 1 (
  echo Setup failed. See the error above and START-HERE.txt.
  pause
  exit /b 1
)
echo Setup complete. Restart ResiliCapture if it is already running.
pause
