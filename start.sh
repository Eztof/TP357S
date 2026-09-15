#!/usr/bin/env bash
cd "$(dirname "$0")"

if [ ! -d venv ]; then
    echo "Erstelle virtuelle Umgebung..."
    python3 -m venv venv || { echo "venv-Erstellung fehlgeschlagen."; exit 1; }
fi

source venv/bin/activate
pip install -q -r requirements.txt
if [ $? -ne 0 ]; then
    echo
    echo "Installation der Abhaengigkeiten fehlgeschlagen (siehe Fehler oben)."
    echo "Bitte pruefe deine Python-Version (python3 --version) und Internetverbindung."
    exit 1
fi

if [ ! -f config.json ]; then
    echo "Keine config.json gefunden, kopiere config.example.json..."
    cp config.example.json config.json
fi

while true; do
    python start.py
    code=$?
    echo
    echo "=== TP357S-Anwendung beendet (Exitcode $code) ==="
    echo "Das kann ein normales Beenden (Strg+C) ODER ein Absturz sein"
    echo "(z.B. ein nativer Fehler im BLE-Backend - siehe data/app.log)."
    echo "Starte automatisch neu in 5 Sekunden. Strg+C zum endgueltigen Beenden."
    sleep 5
done
