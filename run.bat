@echo off
REM Quick launcher for the Driver Drowsiness Detection Dashboard (Windows)
cd /d "%~dp0"

if not exist venv (
  echo Creating virtual environment...
  python -m venv venv
)
call venv\Scripts\activate.bat

echo Installing dependencies (first run only)...
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo Starting dashboard on http://localhost:5000
python app.py
pause
