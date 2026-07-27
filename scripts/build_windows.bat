@echo off
setlocal
cd /d "%~dp0.."

set "RELEASE_DIR=dist\windows"
for /f "delims=" %%V in ('py -c "from diskvis import __version__; print(__version__)"') do set "VERSION=%%V"
if not defined VERSION goto :error

echo Building Disk Space Visualizer v%VERSION%

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

if not exist dist mkdir dist
if exist "dist\DiskSpaceVisualizer-v%VERSION%-Windows.zip" del /q "dist\DiskSpaceVisualizer-v%VERSION%-Windows.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%RELEASE_DIR%\*' -DestinationPath 'dist\DiskSpaceVisualizer-v%VERSION%-Windows.zip' -Force"
if errorlevel 1 goto :error

echo.
echo Build complete: %RELEASE_DIR%\DiskSpaceVisualizer.exe and %RELEASE_DIR%\diskvis.exe
echo Portable ZIP: dist\DiskSpaceVisualizer-v%VERSION%-Windows.zip
exit /b 0

:error
echo Build failed.
exit /b 1
