@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  echo Run start.bat once first so Python and the packages get installed.
  pause
  exit /b 1
)
venv\Scripts\python.exe service_install.py install
echo.
pause
