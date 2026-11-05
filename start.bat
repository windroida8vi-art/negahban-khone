@echo off
chcp 65001 >nul
title Home Music Player

rem ===== Ask for administrator access (needed for full desktop control + firewall) =====
net session >nul 2>&1
if errorlevel 1 (
  echo Requesting administrator access...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"

rem ===== Settings (remove "rem" to change) =====
rem set MUSIC_DIR=D:\Music
rem set PLAYER_USER=admin          (login username; default: admin)
rem Password: leave empty. First run creates a random one and shows it ONCE (change later with set-password.bat).
rem set PLAYER_PASSWORD=your-strong-password-min-10-chars
rem set CAMERA_INDEX=0
rem ---- NVR camera (RTSP, auto-detects the stream URL). Remove these 4 lines to use the PC webcam instead ----
rem >>> CHANGE THESE 3 LINES to your NVR's address / username / password (see README: "Connect your NVR")
set "NVR_IP=192.168.1.10"
set "NVR_USER=admin"
set "NVR_PASS=admin"
set NVR_CHANNEL=1
rem NVR channels to show/watch (people detection runs on all of them):
set NVR_CHANNELS=1,2
rem NVR live view runs at the NVR's own frame rate. If your internet upload is slow, lower these:
rem set NVR_STREAM_FPS=10
rem set NVR_STREAM_WIDTH=640
rem set NVR_STREAM_QUALITY=60
rem set NVR_DECODE_FPS=10
rem set NVR_ENHANCE_FPS=15   (max live fps while the Enhance button is on)
rem set CAMERA_URL=rtsp://user:pass@192.168.1.10:554/...   (full URL if you know it; overrides auto-detect)
rem set NVR_RTSP_PORT=554
rem ---- Phone alerts that work even when the web page is closed (pick one or both) ----
rem set NTFY_TOPIC=put-a-long-random-name-here   (install the free "ntfy" app, subscribe to the same name)
rem set ALERT_TOKEN=bot-token
rem set ALERT_CHAT_ID=your-chat-id
rem set ALERT_API=https://tapi.bale.ai   (only for Bale; remove for Telegram)
if exist telegram-alerts.bat call telegram-alerts.bat
rem set DAILY_REPORT_HOUR=21   (daily status message; -1 = off)
rem ---- Other ----
rem set IDLE_LOGOUT_MIN=30      (auto logout after N idle minutes)
rem ---- Access from outside the house (router port-forward -> this PC, port %PLAYER_PORT%) ----
rem Outside logins need only the password (2FA is optional: run setup-2fa.bat if you want it).
rem Default: home network (and Tailscale) only. Set to 1 ONLY if you port-forward AND use a strong password.
set ALLOW_INTERNET=0
rem set PUBLIC_HOST=your.public.static.ip   (so the HTTPS certificate matches your public address)
rem set REGEN_CERT=1   (only once, if you REALLY want a brand new HTTPS certificate; the phone will need to re-trust it)
if not defined PLAYER_PORT set PLAYER_PORT=8080
set PLAYER_HTTPS=1
rem =============================================

rem ===== Find Python (3.12 / 3.13 preferred) =====
set PY=
py -3.12 --version >nul 2>nul
if not errorlevel 1 set PY=py -3.12
if not defined PY (
  py -3.13 --version >nul 2>nul
  if not errorlevel 1 set PY=py -3.13
)
if not defined PY (
  py -3 --version >nul 2>nul
  if not errorlevel 1 set PY=py -3
)
if not defined PY (
  python --version >nul 2>nul
  if not errorlevel 1 set PY=python
)
if not defined PY (
  echo Python not found. Installing Python 3.12 with winget...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo Python installed. Close this window and run start.bat again.
  pause
  exit /b
)

if not exist venv\Scripts\python.exe (
  echo Creating virtual environment...
  %PY% -m venv venv
  if errorlevel 1 (
    echo Failed to create venv.
    pause
    exit /b 1
  )
)

fc /b requirements.txt venv\req.txt >nul 2>&1
if errorlevel 1 (
  echo Installing requirements, this may take a few minutes...
  venv\Scripts\python.exe -m pip install --upgrade pip
  venv\Scripts\python.exe -m pip install --prefer-binary -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Install failed. Check your internet connection and run again.
    pause
    exit /b 1
  )
  copy /y requirements.txt venv\req.txt >nul
)

rem ===== Firewall rule so your phone can connect =====
netsh advfirewall firewall delete rule name="HomeMusicPlayer" >nul 2>&1
if defined ALLOW_INTERNET (
  netsh advfirewall firewall add rule name="HomeMusicPlayer" dir=in action=allow protocol=TCP localport=%PLAYER_PORT% >nul
) else (
  netsh advfirewall firewall add rule name="HomeMusicPlayer" dir=in action=allow protocol=TCP localport=%PLAYER_PORT% remoteip=LocalSubnet,100.64.0.0/10 >nul
)

:run
echo.
echo Starting server... LAN addresses (192.168.x.x) are printed below
venv\Scripts\python.exe app.py
echo.
echo Server stopped. Restarting in 5 seconds (close this window to quit)...
timeout /t 5 >nul
goto run
