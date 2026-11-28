@echo off
setlocal
chcp 65001 >nul
title AERIS Low-Altitude 3D Console (Shenzhen 10x + CR30)

set "ROOT=%~dp0"
set "CONSOLE=%ROOT%apps\console"

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not found. Please install Node.js 20/22+ first: https://nodejs.org/
  pause
  exit /b 1
)

if not exist "%CONSOLE%\package.json" (
  echo [ERROR] Cannot find apps\console\package.json. Please keep this script in the repo root.
  pause
  exit /b 1
)

cd /d "%CONSOLE%"

if not exist "node_modules" (
  echo [AERIS] First run detected: installing frontend dependencies (npm install)...
  call npm install
  if errorlevel 1 (
    echo [ERROR] npm install failed. Check network or Node version.
    pause
    exit /b 1
  )
)

echo.
echo ================================================================
echo   AERIS 3D Console (10x Shenzhen Bay + CR30 Exploded Backdrop)
echo   - Homepage (Hero 3D):      http://127.0.0.1:5174/
echo   - Shenzhen 3D Console:     http://127.0.0.1:5174/console
echo   - Competition Replay:      http://127.0.0.1:5174/demo
echo   - Team Workspace Login:    http://127.0.0.1:5174/login
echo ================================================================
echo.

:: Open browser automatically after 3 seconds
start "" /b powershell -NoProfile -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:5174/console'"

if exist "%ROOT%.venv\Scripts\python.exe" (
  echo [AERIS] Python .venv detected -> Starting Full Stack (Frontend :5174 + Backend :8012)...
  call npm run dev:all
) else (
  echo [AERIS] Python .venv not found -> Starting Frontend 3D Mode (Frontend :5174)...
  echo         (Homepage /, Shenzhen 3D /console, and Replay /demo all work without Python.)
  call npm run dev -- --port 5174 --strictPort
)

if errorlevel 1 (
  echo.
  echo [AERIS] Server exited with an error. Check port 5174 / 8012 or logs above.
  pause
)
endlocal
