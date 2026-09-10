@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  call .venv\Scripts\activate.bat
)
python -m compileall -q app.py recorder ui platform_tools tests || goto :fail
python -m unittest discover -s tests -v || goto :fail
python -m pip check || goto :fail
echo.
echo All ResiliCapture tests passed.
exit /b 0
:fail
echo.
echo ResiliCapture validation failed.
exit /b 1
