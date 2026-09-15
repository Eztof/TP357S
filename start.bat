@echo off
setlocal
cd /d "%~dp0"

if not exist venv (
    echo Erstelle virtuelle Umgebung...
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo Installation der Abhaengigkeiten fehlgeschlagen ^(siehe Fehler oben^).
    echo Bitte pruefe deine Python-Version ^(python --version^) und Internetverbindung.
    pause
    exit /b 1
)

if not exist config.json (
    echo Keine config.json gefunden, kopiere config.example.json...
    copy config.example.json config.json >nul
)

python start.py
pause
