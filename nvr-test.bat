@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  echo First run start.bat once so Python and packages get installed.
  pause
  exit /b 1
)
venv\Scripts\python.exe nvr_test.py
echo.
pause
