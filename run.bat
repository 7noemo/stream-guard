@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Stream Guard
python app.py
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to start. Install dependencies first:
  echo   python -m pip install -r requirements-windows.txt
  pause
)
