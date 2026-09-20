@echo off
REM Sets up the host dashboard on a Windows PC. Run from repo root.
setlocal

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install Python 3.9+ from python.org first, then re-run this.
    exit /b 1
)

if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate.bat

python -m pip install --upgrade pip
python -m pip install -r host\requirements.txt
if errorlevel 1 (
    echo.
    echo Normal dlib install failed - common on Windows without build tools.
    echo Retrying with a prebuilt dlib wheel instead...
    python -m pip install dlib-binary
    python -m pip install flask pyserial opencv-python imutils scipy
)

echo.
echo Done. Before running:
echo   1. Edit COM port in host\controller_link.py (CONTROLLER_SERIAL_PORT)
echo   2. venv\Scripts\python host\app.py
echo   3. Open http://localhost:5000
endlocal
