@echo off
setlocal
cd /d "%~dp0"
echo Stopping Speakly containers (your data/ folder is preserved)...
docker compose down
if errorlevel 1 (
  echo ERROR: Could not stop Docker Compose. Is Docker Desktop running?
  pause
  exit /b 1
)
echo Speakly stopped. Your practice history remains in the data folder.
pause
