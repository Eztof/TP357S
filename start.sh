#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d venv ]; then
    echo "Erstelle virtuelle Umgebung..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f config.json ]; then
    echo "Keine config.json gefunden, kopiere config.example.json..."
    cp config.example.json config.json
    echo
    echo "Bitte trage in config.json die MAC-Adresse deines TP357S ein"
    echo "und starte ./start.sh danach erneut."
    exit 0
fi

python start.py
