@echo off
echo Starting SynthGen Frontend...
cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo Installing npm dependencies...
    call npm install
)

echo Starting Vite dev server on http://localhost:5173
call npm run dev
