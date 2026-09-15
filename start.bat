@echo off
setlocal
cd /d "%~dp0"

if not exist venv (
    echo Erstelle virtuelle Umgebung...
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -q -r requirements.txt

if not exist config.json (
    echo Keine config.json gefunden, kopiere config.example.json...
    copy config.example.json config.json >nul
    echo.
    echo Bitte trage in config.json die MAC-Adresse deines TP357S ein
    echo und starte start.bat danach erneut.
    pause
    exit /b
)

python start.py
pause
