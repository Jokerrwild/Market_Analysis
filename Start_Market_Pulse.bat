@echo off
setlocal
cd /d "%~dp0"
title Market Pulse Dashboard

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on PATH.
  echo Install Python or add it to PATH, then run this launcher again.
  pause
  exit /b 1
)

echo Starting Market Pulse dashboard...
echo Browser URL: http://127.0.0.1:8765/
echo.
echo Use the Exit button in the dashboard to stop the application.
echo.
echo Performing an initial market collection...
python -m market_pulse run
if errorlevel 1 (
  echo.
  echo Initial collection failed. Starting the dashboard with stored database data.
  echo You can press Refresh in the dashboard to try again.
)

start "" powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8765/'"
python -m market_pulse dashboard --host 127.0.0.1 --port 8765

echo.
echo Market Pulse dashboard stopped.
timeout /t 2 >nul
endlocal
