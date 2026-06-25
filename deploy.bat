@echo off
title ACCCE - Hot Deploy to dist
echo =======================================================================
echo   ACCCE: Hot-deploying source files to dist\ACCCE\_internal\
echo   (No rebuild required - gui_backend.py is loaded from filesystem)
echo =======================================================================
echo.

set DEST=dist\ACCCE\_internal

if not exist "%DEST%" (
    echo [ERROR] dist\ACCCE\_internal not found. Run build_exe.bat first.
    pause
    exit /b 1
)

copy /Y "gui_frontend.html"  "%DEST%\gui_frontend.html"  >nul && echo [OK] gui_frontend.html
copy /Y "gui_backend.py"     "%DEST%\gui_backend.py"     >nul && echo [OK] gui_backend.py
copy /Y "main.py"            "%DEST%\main.py"            >nul && echo [OK] main.py
copy /Y "gui_app.py"         "%DEST%\gui_app.py"         >nul && echo [OK] gui_app.py

echo.
echo [DONE] All files deployed. Restart ACCCE.exe to see changes.
echo =======================================================================
echo.
