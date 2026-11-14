@echo off
setlocal
rem Wanderpin launcher: sets up Python packages the first time, then opens the app.
rem The Python environment lives in %LOCALAPPDATA%\Wanderpin because Python
rem refuses to create one inside a folder whose path contains ";".

set "VENV=%LOCALAPPDATA%\Wanderpin\venv"
set "PY=%VENV%\Scripts\python.exe"
set "APP=%~dp0app.py"

if exist "%PY%" goto run

where python >nul 2>nul
if errorlevel 1 goto nopython

echo First run: setting up (this takes a minute)...
python -m venv "%VENV%"
if errorlevel 1 goto failed
"%PY%" -m pip install --upgrade pip pymobiledevice3
if errorlevel 1 goto failed

:run
"%PY%" "%APP%"
goto end

:nopython
echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" in the installer), then run this again.
pause
goto end

:failed
echo Setup failed. Check your internet connection and try again.
pause

:end
endlocal
