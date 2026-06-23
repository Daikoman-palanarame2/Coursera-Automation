@echo off
title ACCCE - Build Executable
color 0B
echo =======================================================================
echo              ACCCE: Building Desktop Application (.exe)
echo =======================================================================
echo.

:: Check for virtual environment
if not exist .venv (
    echo [ERROR] Virtual environment not found! Run start.bat first.
    pause
    exit /b
)

:: Ensure pyinstaller is installed
.venv\Scripts\pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [SETUP] Installing PyInstaller...
    .venv\Scripts\pip install pyinstaller
)

echo [BUILD] Starting PyInstaller build...
echo.

.venv\Scripts\pyinstaller ^
    --noconfirm ^
    --onedir ^
    --windowed ^
    --name "ACCCE" ^
    --add-data "gui_frontend.html;." ^
    --add-data "project_accce;project_accce" ^
    --add-data "main.py;." ^
    --add-data "requirements.txt;." ^
    --hidden-import "clr_loader" ^
    --hidden-import "pythonnet" ^
    --hidden-import "webview" ^
    --hidden-import "pystray" ^
    --hidden-import "PIL" ^
    gui_app.py

if %errorlevel% neq 0 (
    color 0C
    echo.
    echo [ERROR] Build failed! Check the output above for errors.
    pause
    exit /b
)

echo.
echo =======================================================================
echo   BUILD COMPLETE!
echo   Your executable is in: dist\ACCCE\ACCCE.exe
echo =======================================================================
echo.
pause
