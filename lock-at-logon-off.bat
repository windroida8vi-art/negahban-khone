@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
schtasks /Delete /TN "LockAtLogon" /F
echo.
echo Lock-after-login removed.
pause
