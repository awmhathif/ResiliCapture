@echo off
setlocal
cd /d "%~dp0"
if not exist bin mkdir bin
where ffmpeg >nul 2>nul || (
  echo FFmpeg was not found on PATH.
  echo Download a trusted Windows FFmpeg build, then place ffmpeg.exe and ffprobe.exe inside the bin folder.
  pause
  exit /b 1
)
for /f "delims=" %%F in ('where ffmpeg') do (
  copy /y "%%F" "bin\ffmpeg.exe" >nul
  goto :ffmpeg_done
)
:ffmpeg_done
where ffprobe >nul 2>nul && for /f "delims=" %%F in ('where ffprobe') do (
  copy /y "%%F" "bin\ffprobe.exe" >nul
  goto :ffprobe_done
)
:ffprobe_done
echo FFmpeg tools copied into bin.
pause
