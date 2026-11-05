@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
schtasks /Create /TN "HomeMusicPlayer" /TR "\"%~dp0start.bat\"" /SC ONLOGON /RL HIGHEST /F
echo.
echo Done. The player will start automatically after Windows login.
echo To remove: schtasks /Delete /TN HomeMusicPlayer /F
pause
