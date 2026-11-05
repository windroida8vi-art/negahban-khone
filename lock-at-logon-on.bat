@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
schtasks /Create /TN "LockAtLogon" /TR "rundll32.exe user32.dll,LockWorkStation" /SC ONLOGON /DELAY 0000:30 /F
echo.
echo Done. Windows will lock 30 seconds after login (the player keeps running).
pause
