@echo off
chcp 65001 >nul
title Stream Guard - Build
cd /d "%~dp0"

echo ==========================================
echo   Stream Guard - Windows EXE Builder
echo ==========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.11 64-bit first.
  pause
  exit /b 1
)

echo [1/3] Installing dependencies ...
python -m pip install --upgrade pip
python -m pip install -r requirements-windows.txt
if errorlevel 1 (
  echo [ERROR] Dependency installation failed.
  pause
  exit /b 1
)

echo [2/3] Building executable ...
python -m PyInstaller stream-guard.spec --noconfirm --clean
if errorlevel 1 (
  echo [ERROR] Build failed.
  pause
  exit /b 1
)

echo [3/3] Copying config ...
copy /Y config.json dist\config.json >nul

echo.
echo ==========================================
echo   BUILD DONE
echo   File: dist\StreamGuard.exe
echo   Keep config.json next to the exe.
echo ==========================================
pause
