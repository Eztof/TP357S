# TP357S Monitor

Kleine Computeranwendung, die per Bluetooth LE Live-Messwerte und die
gespeicherte Historie eines **ThermoPro TP357S** (Temperatur/Luftfeuchte-
Sensor) ausliest, lokal in einer SQLite-Datenbank speichert und den Status
als Dashboard über `localhost` im Browser anzeigt.

## Ordnerstruktur

```
TP357S/
  start.py            # Startanwendung (BLE + Webserver, öffnet Browser)
  start.bat            # Doppelklick-Starter für Windows
  start.sh               # Starter für Linux/macOS
  requirements.txt
  config.example.json     # Vorlage, wird beim ersten Start zu config.json kopiert
  app/
    protocol.py           # Dekodierung/Kodierung des TP357S-Bluetooth-Protokolls
    ble_client.py          # BLE-Verbindung (läuft im Hintergrund-Thread)
    storage.py              # SQLite-Speicherung (Live-Werte + Historie)
    state.py                 # geteilter Programmstatus
    server.py                 # lokaler Webserver (Flask) + JSON-API
    static/                     # Dashboard (HTML/CSS/JS)
  data/
    tp357s.db                    # SQLite-Datenbank (wird automatisch angelegt)
```

## Voraussetzungen

- Python 3.9 oder neuer
- Windows: Bluetooth LE wird über die eingebaute Windows-Bluetooth-Stack-API
  genutzt (kein zusätzlicher Treiber nötig). Linux: BlueZ. macOS: CoreBluetooth.
- Die MAC-Adresse (bzw. unter macOS die BLE-UUID) deines TP357S.

## Start

**Windows:** Doppelklick auf `start.bat`.
**Linux/macOS:** `./start.sh` im Terminal ausführen.

`start.py` selbst bitte nicht direkt per Doppelklick starten — es enthält
keine Installationslogik und benötigt die vorher von `start.bat`/`start.sh`
angelegte virtuelle Umgebung mit installierten Abhängigkeiten.
`start.sh` ist ein Bash-Skript und funktioniert unter Windows nicht (kein
Fehler, es passiert dort einfach nichts).

Falls `start.bat` beim ersten Versuch mit einem Fehler bei der Installation
von `bleak` abbricht: erst den (dann unvollständigen) `venv`-Ordner löschen
und `start.bat` erneut ausführen — das Fehlschlagen der Installation wird
jetzt außerdem klar erkannt und die App startet nicht mehr mit fehlenden
Abhängigkeiten.

Beim ersten Start wird automatisch eine virtuelle Umgebung angelegt, die
Abhängigkeiten installiert und `config.json` aus `config.example.json`
erzeugt. Trage dort die MAC-Adresse deines Sensors ein:

```json
{
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "device_name": "TP357S",
  "history_record_interval_seconds": 60,
  "reconnect_delay_seconds": 10,
  "web_host": "127.0.0.1",
  "web_port": 5000,
  "db_path": "data/tp357s.db"
}
```

Danach die Startdatei erneut ausführen. Es öffnet sich automatisch der
Browser mit dem Dashboard unter `http://127.0.0.1:5000/`, das den
Verbindungsstatus, den aktuellen Live-Messwert sowie die gespeicherte
Historie anzeigt.

Die MAC-Adresse findest du z. B. mit einem BLE-Scanner
(z. B. `bluetoothctl scan on` unter Linux, oder einer BLE-Scanner-App
auf dem Smartphone während der Sensor in der Nähe ist).

## Funktionsumfang

- **Live-Wert:** Verbindet sich automatisch (mit Wiederverbindungslogik)
  und abonniert Notifications; jeder eingehende 7-Byte-Live-Wert wird
  dekodiert, validiert (−40…85 °C, 0…100 %) und in `live_readings`
  gespeichert.
- **Historie:** Über den Button „Verlauf vom Sensor abrufen“ im Dashboard
  wird die interne Aufzeichnung des Sensors abgerufen und in
  `history_readings` gespeichert. Da die Datensätze selbst keinen
  Zeitstempel tragen, wird er anhand von `history_record_interval_seconds`
  (Annahme über das Aufnahmeintervall des Geräts, Standard: 60 s)
  rückwärts vom Abrufzeitpunkt geschätzt.
- **CSV-Export:** `/api/export.csv` bzw. Link im Dashboard.

## ⚠️ Wichtiger Hinweis zum Verlaufs-Abruf

Die Spezifikation, nach der diese Anwendung gebaut wurde, beschreibt für
den Verlaufs-Abruf vier zu sendende Kommandos (a–d). Für Kommando d
(Datenanfrage) war der Byte-Präfix eindeutig angegeben (`01 09 ...`) und ist
in `app/protocol.py` (`DATA_REQUEST_OPCODE`) bereits fest hinterlegt. Für
die drei anderen Kommandos – **a) Uhrzeit-Sync**, **b) Session-Init**,
**c) Offset-Kommando** – waren in der Vorlage nur die *Feldbedeutungen*
beschrieben, nicht die tatsächlichen festen Byte-Werte (vermutlich beim
Kopieren verloren gegangen).

Diese drei Konstanten sind in `app/protocol.py` als Platzhalter markiert:

```python
TIME_SYNC_OPCODE: Optional[bytes] = None       # z. B. bytes([0x01, 0x01])
SESSION_INIT_COMMAND: Optional[bytes] = None
OFFSET_COMMAND: Optional[bytes] = None
```

**Der Live-Wert funktioniert bereits vollständig ohne weitere Änderungen.**
Für den Verlaufs-Abruf müssen diese drei Byte-Sequenzen einmalig eingetragen
werden (z. B. durch einen BLE-Sniff der offiziellen ThermoPro-App mit
nRF Connect / Wireshark, oder falls du die vollständige Original-Spezifikation
noch hast). Solange sie `None` sind, gibt das Dashboard beim Versuch, die
Historie abzurufen, eine klare Fehlermeldung aus statt stillschweigend
falsche Daten zu senden.

## Datenschutz / Speicherort

Alle Daten bleiben lokal auf dem PC in `data/tp357s.db` (SQLite). Es gibt
keine Cloud-Anbindung; der Webserver lauscht standardmäßig nur auf
`127.0.0.1` (nicht im Netzwerk erreichbar).
