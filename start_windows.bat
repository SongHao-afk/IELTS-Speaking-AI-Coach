@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo =============================================
echo   Speakly v2.1 - Groq + Docker Compose
echo =============================================
echo.

if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
)
if not exist "data" mkdir "data"

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker CLI not found.
  echo Install Docker Desktop for Windows and reopen this file.
  echo Or run start_python_windows.bat to use Python without Docker.
  pause
  exit /b 1
)

docker compose version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Compose V2 is unavailable.
  echo Install or update Docker Desktop and enable Docker Compose V2.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Engine is not running.
  echo Start Docker Desktop and wait until the engine is ready, then retry.
  pause
  exit /b 1
)

echo [1/2] Building image and installing requirements inside Docker...
docker compose up --build -d --wait --wait-timeout 120
if errorlevel 1 (
  echo ERROR: Docker Compose could not start Speakly.
  echo See logs with: docker compose logs --tail=100 speakly
  echo If port 8000 is busy, stop the other server first.
  pause
  exit /b 1
)

echo [2/2] Speakly is running at http://127.0.0.1:8000
echo.
echo Edit GROQ_API_KEY in .env before using the cloud AI features.
echo After changing .env, run: docker compose up -d --force-recreate
echo.
docker compose ps
start "" "http://127.0.0.1:8000"
echo.
echo To stop Speakly: docker compose down
pause
