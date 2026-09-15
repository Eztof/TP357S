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

python -c "import sys; sys.exit(1 if sys.version_info >= (3, 14) else 0)"
if errorlevel 1 (
    echo.
    echo WARNUNG: Du verwendest Python 3.14 oder neuer.
    echo Bekanntes Problem: das Windows-Bluetooth-Backend ^(bleak/winrt^) kann
    echo damit beim Verbinden zu einem Geraet mit einem nativen Absturz
    echo ^(kompletter Prozessabsturz ohne Python-Fehlermeldung^) enden.
    echo Falls das passiert: Python 3.11 oder 3.12 installieren, den venv-
    echo Ordner loeschen und start.bat erneut ausfuehren. Details siehe README.
    echo.
)

:run
python start.py
set "EXITCODE=%ERRORLEVEL%"
echo.
echo === TP357S-Anwendung beendet (Exitcode %EXITCODE%) ===
echo Das kann ein normales Beenden ^(Strg+C^) ODER ein Absturz sein
echo ^(z.B. ein nativer Fehler im Windows-Bluetooth-Backend - siehe data\app.log^).
echo.
echo Starte automatisch neu in 5 Sekunden. Zum endgueltigen Beenden jetzt
echo dieses Fenster schliessen oder Strg+C druecken.
timeout /t 5
goto run
