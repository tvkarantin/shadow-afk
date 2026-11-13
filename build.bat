@echo off
setlocal
cd /d "%~dp0"
if not defined BUILD_PYTHON set "BUILD_PYTHON=python"
if not defined ISCC set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
"%BUILD_PYTHON%" -X utf8 -m pip --disable-pip-version-check install --progress-bar off -r requirements-build.txt || exit /b 1
"%BUILD_PYTHON%" -m pytest -q || exit /b 1
"%BUILD_PYTHON%" -m PyInstaller --noconfirm --clean --windowed --onedir --noupx --name ShadowAFK --icon shadowafk/ui/shadow.ico --add-data "shadowafk/ui:shadowafk/ui" --hidden-import PySide6.QtQuick --hidden-import PySide6.QtQuickControls2 run.py || exit /b 1
start "" /wait dist\ShadowAFK\ShadowAFK.exe --smoke
if errorlevel 1 exit /b 1
if not exist release mkdir release
"%ISCC%" installer.iss || exit /b 1
