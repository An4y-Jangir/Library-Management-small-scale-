@echo off
title Library Management System
echo Starting Library Management System...
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Error: Failed to launch application.
    echo Please make sure Python is installed and added to PATH.
    pause
)

