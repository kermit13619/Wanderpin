@echo off
setlocal
title Uninstall Wanderpin
choice /M "Remove Wanderpin and its saved spots from this PC"
if errorlevel 2 goto end
del /Q "%USERPROFILE%\Desktop\Wanderpin.lnk" 2>nul
powershell -NoProfile -Command "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { Remove-Item -LiteralPath (Join-Path $d 'Wanderpin.lnk') -ErrorAction SilentlyContinue }"
rem Run the folder removal from TEMP, since this script lives inside it.
cd /d "%TEMP%"
start "" /min cmd /c "timeout /t 2 >nul & rmdir /S /Q "%LOCALAPPDATA%\Wanderpin""
echo Wanderpin removed.
timeout /t 2 >nul
:end
endlocal
