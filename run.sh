#!/usr/bin/env bash
# Quick launcher for the Driver Drowsiness Detection Dashboard (macOS/Linux)
set -e
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

echo "Installing dependencies (first run only)..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo "Starting dashboard on http://localhost:${PORT:-5000}"
python app.py
