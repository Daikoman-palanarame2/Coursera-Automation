@echo off
title ACCCE Launcher
color 0B
echo =======================================================================
echo               ACCCE: Coursera Automation Engine Launcher
echo =======================================================================
echo.

:: 1. Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 goto :NO_PYTHON

:: 2. Check if Virtual Environment exists
if not exist .venv goto :CREATE_VENV
goto :CHECK_ENV

:NO_PYTHON
color 0C
echo [ERROR] Python is not installed or not added to your system PATH!
echo.
echo Please install Python 3.10+ from: https://www.python.org/downloads/
echo Make sure to check the box "Add Python to PATH" during installation.
echo.
pause
exit /b

:CREATE_VENV
echo [SETUP] First-time setup detected. Creating virtual environment...
python -m venv .venv
if %errorlevel% neq 0 goto :VENV_ERROR
echo [SETUP] Virtual environment created successfully.
echo.
echo [SETUP] Installing dependencies (this may take a minute)...
.venv\Scripts\pip install -r requirements.txt
echo.
echo [SETUP] Installing Playwright Chromium browser...
.venv\Scripts\playwright install chromium
echo.
echo [SETUP] Setup complete!
echo =======================================================================
echo.
goto :CHECK_ENV

:VENV_ERROR
echo [ERROR] Failed to create virtual environment!
pause
exit /b

:CHECK_ENV
:: 3. Check for .env file
if not exist .env goto :NO_ENV
goto :ASK_COURSE

:NO_ENV
color 0E
echo [WARNING] Configuration file (.env) is missing!
echo.
echo Please copy '.env.example' to '.env' and paste your:
echo 1. COURSERA_ENGINE_TOKEN
echo 2. GEMINI_API_KEY
echo.
echo Opening the directory so you can edit the files...
explorer .
pause
exit /b

:ASK_COURSE
:: 4. Ask for the Course URL / ID
echo Enter the Coursera Course URL or Course ID:
set /p COURSE_INPUT="> "
if "%COURSE_INPUT%"=="" goto :COURSE_EMPTY
goto :ASK_MODE

:COURSE_EMPTY
echo [ERROR] Course URL or ID cannot be empty!
pause
exit /b

:ASK_MODE
:: 5. Ask for running mode (Headless vs Headful)
echo.
echo Running Modes:
echo [1] Headful mode (Opens a visible browser - required for first-time login)
echo [2] Headless mode (Runs invisibly in the background)
echo.
set /p MODE_INPUT="Select mode [1 or 2]: "

set FLAGS=
if "%MODE_INPUT%"=="2" set FLAGS=--headless

echo.
echo =======================================================================
echo   ACCCE Bot is now starting up... (Press Ctrl+C to close the bot)
echo =======================================================================
echo.

.venv\Scripts\python main.py --course-id "%COURSE_INPUT%" %FLAGS%

echo.
echo =======================================================================
echo   ACCCE Bot execution finished.
echo =======================================================================
pause
