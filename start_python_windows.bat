@echo off
setlocal
cd /d "%~dp0"
echo.
echo ==========================================
echo  Speakly v2 - IELTS Speaking + Groq API
 echo ==========================================
echo.
if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
)
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating virtual environment...
  py -m venv .venv
  if errorlevel 1 (
    echo ERROR: Python 3.10+ is required. Install Python and enable py launcher.
    pause
    exit /b 1
  )
)
echo [2/3] Installing or checking dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Could not install dependencies. Check Internet and Python version.
  pause
  exit /b 1
)
echo.
echo [3/3] Starting Speakly on http://127.0.0.1:8000
 echo IMPORTANT: Put your Groq key in .env and restart this window.
 echo You can still use manual practice without a key.
echo.
start "" "http://127.0.0.1:8000"
".venv\Scripts\python.exe" run.py
pause
