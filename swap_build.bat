@echo off
title ACCCE - Swap to New Build
echo =======================================================================
echo   ACCCE: Swapping dist\ACCCE with freshly compiled dist_new\ACCCE
echo   IMPORTANT: Make sure ACCCE.exe is CLOSED before running this!
echo =======================================================================
echo.

:: Kill ACCCE.exe if still running
taskkill /F /IM ACCCE.exe >nul 2>&1
timeout /t 2 /nobreak >nul

:: Remove old dist
if exist "dist\ACCCE" (
    rmdir /S /Q "dist\ACCCE"
    if exist "dist\ACCCE" (
        echo [ERROR] Could not remove dist\ACCCE - is ACCCE.exe still running?
        pause
        exit /b 1
    )
)

:: Move new build into place
if not exist "dist_new\ACCCE" (
    echo [ERROR] dist_new\ACCCE not found. Run the build first.
    pause
    exit /b 1
)

move "dist_new\ACCCE" "dist\ACCCE" >nul
if exist "dist_new" rmdir "dist_new" >nul 2>&1

echo [OK] Swap complete!
echo.
echo =======================================================================
echo   New ACCCE.exe is ready at: dist\ACCCE\ACCCE.exe
echo   Launching now...
echo =======================================================================
echo.
start "" "dist\ACCCE\ACCCE.exe"
