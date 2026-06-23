@echo off
title ACCCE Desktop
cd /d "%~dp0"

:: Quick check for venv
if not exist .venv\Scripts\python.exe (
    echo [ERROR] Virtual environment not found!
    echo Please run 'start.bat' first to set up the environment.
    pause
    exit /b
)

:: Launch the GUI
.venv\Scripts\python gui_app.py
