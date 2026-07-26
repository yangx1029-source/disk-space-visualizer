@echo off
setlocal
cd /d "%~dp0.."

set "RELEASE_DIR=dist\windows"

echo Installing Windows packaging dependency...
py -m pip install -e ".[windows]"
if errorlevel 1 goto :error

echo Building DiskVis GUI...
py -m PyInstaller --clean --noconfirm packaging\windows\DiskSpaceVisualizer.spec --distpath "%RELEASE_DIR%" --workpath build\windows-gui
if errorlevel 1 goto :error

echo Building diskvis CLI...
py -m PyInstaller --clean --noconfirm packaging\windows\DiskVisCLI.spec --distpath "%RELEASE_DIR%" --workpath build\windows-cli
if errorlevel 1 goto :error

echo Writing usage notes...
copy /y packaging\windows\README.txt "%RELEASE_DIR%\README.txt" >nul
if errorlevel 1 goto :error

echo.
echo Build complete: %RELEASE_DIR%\DiskSpaceVisualizer.exe and %RELEASE_DIR%\diskvis.exe
exit /b 0

:error
echo Build failed.
exit /b 1
