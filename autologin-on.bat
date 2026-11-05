@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell -NoProfile -Command "$u=Read-Host 'Windows username'; $p=Read-Host 'Windows password'; $k='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'; Set-ItemProperty $k AutoAdminLogon '1'; Set-ItemProperty $k DefaultUserName $u; Set-ItemProperty $k DefaultPassword $p; Set-ItemProperty $k DefaultDomainName $env:COMPUTERNAME"
echo.
echo Done. Windows will log in automatically after the next restart.
echo (The password is stored in the registry as plain text. Use only on a PC at home.)
pause
