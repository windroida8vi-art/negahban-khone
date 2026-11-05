@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
schtasks /End /TN "HomeMusicPlayer" >nul 2>&1
schtasks /Delete /TN "HomeMusicPlayer" /F
echo.
echo Autostart (HomeMusicPlayer) removed. The service (install-service.bat) is not touched.
echo To remove the service too: uninstall-service.bat
pause
