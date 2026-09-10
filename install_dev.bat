@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv || goto :fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip || goto :fail
python -m pip install -r requirements.txt || goto :fail
python -m pip check || goto :fail
python -m compileall -q app.py recorder ui platform_tools || goto :fail
echo.
echo Installed and validated. Run run.bat to start ResiliCapture.
pause
exit /b 0
:fail
echo Installation failed.
pause
exit /b 1
