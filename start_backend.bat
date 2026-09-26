@echo off
echo Starting SynthGen Backend...
cd /d "%~dp0backend"

echo Creating virtual environment if it doesn't exist...
if not exist ".venv\Scripts\activate.bat" (
    python -m venv .venv
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Installing/verifying dependencies...
python -m pip install -r requirements.txt --quiet
python -m pip install -r requirements-sdv.txt --quiet

echo Unblocking downloaded DLLs to bypass strict OS AppLocker restrictions...
powershell -Command "Get-ChildItem -Path .venv -Recurse -File | Unblock-File -ErrorAction SilentlyContinue"

echo Generating demo dataset...
python generate_demo_data.py

echo.
echo Starting FastAPI server on http://localhost:8000
echo NOTE: Running without --reload to ensure background generation threads are stable.
echo       Restart manually after code changes.
echo.
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
