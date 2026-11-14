@echo off
setlocal
title Wanderpin setup
rem Installs Wanderpin for the current user: copies the app to
rem %LOCALAPPDATA%\Wanderpin, sets up Python packages, and adds Desktop and
rem Start menu shortcuts. No admin rights needed to install.
rem   install.bat /noshortcut   - skip creating shortcuts

set "SRC=%~dp0"
set "DEST=%LOCALAPPDATA%\Wanderpin"
set "VENV=%DEST%\venv"
set "PY=%VENV%\Scripts\python.exe"
set "BASEPY="

echo.
echo  Installing Wanderpin...
echo.

rem ---- 1. Find Python 3.10+ (the Microsoft Store "python" stub doesn't count)
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "BASEPY=py -3"
if defined BASEPY goto havepython
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "BASEPY=python"
if defined BASEPY goto havepython

echo  Python 3.10 or newer was not found.
where winget >nul 2>nul
if errorlevel 1 goto nopython
choice /M " Install Python 3.12 now with winget"
if errorlevel 2 goto nopython
winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "BASEPY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined BASEPY goto nopython
set "BASEPY="%BASEPY%""

:havepython
echo  [1/4] Using Python: %BASEPY%

rem ---- 2. Copy the app
if not exist "%DEST%\app\static" mkdir "%DEST%\app\static"
copy /Y "%SRC%*.py" "%DEST%\app\" >nul || goto failed
copy /Y "%SRC%static\index.html" "%DEST%\app\static\index.html" >nul || goto failed
copy /Y "%SRC%README.md" "%DEST%\README.md" >nul
copy /Y "%SRC%uninstall.bat" "%DEST%\uninstall.bat" >nul
echo  [2/4] App copied to %DEST%

rem ---- 3. Python environment + pymobiledevice3
if not exist "%PY%" %BASEPY% -m venv "%VENV%" || goto failed
"%PY%" -m pip install --disable-pip-version-check -q --upgrade pip pymobiledevice3 || goto failed
echo  [3/4] Packages installed

rem ---- 4. Launcher + shortcuts
> "%DEST%\Wanderpin.bat" echo @echo off
>>"%DEST%\Wanderpin.bat" echo title Wanderpin - keep this window open while spoofing
>>"%DEST%\Wanderpin.bat" echo "%PY%" "%DEST%\app\app.py"
>>"%DEST%\Wanderpin.bat" echo if errorlevel 1 pause

if /I "%~1"=="/noshortcut" goto doneshortcuts
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$w = New-Object -ComObject WScript.Shell;" ^
  "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {" ^
  "  $s = $w.CreateShortcut((Join-Path $d 'Wanderpin.lnk'));" ^
  "  $s.TargetPath = Join-Path $env:LOCALAPPDATA 'Wanderpin\Wanderpin.bat';" ^
  "  $s.WorkingDirectory = Join-Path $env:LOCALAPPDATA 'Wanderpin';" ^
  "  $s.WindowStyle = 7; $s.Description = 'Set your iPhone location';" ^
  "  $s.IconLocation = 'shell32.dll,13'; $s.Save() }"
echo  [4/4] Shortcuts added (Desktop and Start menu)
:doneshortcuts

echo.
echo  Done! Open "Wanderpin" from your Desktop or Start menu.
echo  Before first use, turn on Developer Mode on the iPhone:
echo    Settings ^> Privacy ^& Security ^> Developer Mode
echo.
pause
goto end

:nopython
echo.
echo  Please install Python 3.10+ from https://www.python.org/downloads/
echo  (tick "Add python.exe to PATH"), then run this setup again.
pause
exit /b 1

:failed
echo.
echo  Setup failed. Check your internet connection and run it again.
pause
exit /b 1

:end
endlocal
