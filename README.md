# TP357S Monitor

Computeranwendung, die per Bluetooth LE Live-Messwerte und die gespeicherte
Historie von **ThermoPro TP357S**-Sensoren (Temperatur/Luftfeuchte)
ausliest, lokal in einer SQLite-Datenbank speichert und den Status über
`localhost` im Browser anzeigt. Sensoren werden direkt im Dashboard per
BLE-Scan gesucht, gekoppelt, umbenannt und einzeln entfernt — mehrere
Sensoren gleichzeitig, keine manuell einzutragende MAC-Adresse.

Das Dashboard ist bewusst ein reines Entwickler-Werkzeug: keine grafische
Gestaltung, sondern maximale Informationsdichte — rohe Scan-Daten (alle
Advertisement-Felder), ein Live-Rohdaten-Feed (Hex + Dekodierung) für jedes
gefundene UND jedes gekoppelte Gerät, die volle effektive Konfiguration,
ein Debug-Status (Threads/Tasks/Verbindungen) und ein live nachladendes
Logfile — alles direkt im Browser, nichts muss man sich zusammensuchen.

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
    ble_client.py          # BLE-Scan + Verbindungen (läuft im Hintergrund-Thread)
    devices.py              # Liste gekoppelter Sensoren (data/devices.json)
    storage.py                # SQLite-Speicherung (Live-Werte + Historie, je Sensor)
    state.py                   # geteilter Programmstatus (alle Sensoren, Scan, Rohdaten-Logs)
    logging_setup.py            # Logdatei + globale Crash-Hooks (Haupt-/Hintergrund-Threads, asyncio)
    server.py                     # lokaler Webserver (Flask) + JSON-API
    static/                         # Dashboard (HTML/CSS/JS, bewusst schmucklos)
  data/
    tp357s.db                        # SQLite-Datenbank (wird automatisch angelegt)
    devices.json                       # gekoppelte Sensoren (wird automatisch angelegt)
    app.log                              # Logdatei, rotierend (wird automatisch angelegt)
```

## Voraussetzungen

- Python 3.9 oder neuer
- Windows: Bluetooth LE wird über die eingebaute Windows-Bluetooth-Stack-API
  genutzt (kein zusätzlicher Treiber nötig). Linux: BlueZ. macOS: CoreBluetooth.
- Bluetooth am PC muss eingeschaltet sein; der/die TP357S muss sich in
  Reichweite befinden.

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
erzeugt. Die Standardwerte darin (Server-Port, Wiederverbindungs-Intervall,
angenommenes Aufnahmeintervall der Historie …) müssen in der Regel nicht
angepasst werden — es ist **keine MAC-Adresse mehr manuell einzutragen**.

Danach die Startdatei erneut ausführen. Es öffnet sich automatisch der
Browser mit dem Dashboard unter `http://127.0.0.1:5000/`.

## Sensoren koppeln

1. Im Dashboard unter „Sensoren suchen“ auf **Nach Sensoren suchen**
   klicken (Scan läuft standardmäßig 8 Sekunden, einstellbar). Es werden
   alle in der Nähe gefundenen BLE-Geräte mit Name, MAC-Adresse und
   Signalstärke aufgelistet.
2. Beim gewünschten Sensor auf **Hinzufügen** klicken und einen Namen
   vergeben (z. B. „Wohnzimmer“, „Keller“). Der Sensor erscheint danach
   unter „Meine Sensoren“ und die App verbindet sich automatisch (inkl.
   Wiederverbindung, falls die Verbindung abbricht).
3. Beliebig viele Sensoren parallel koppeln — jeder läuft unabhängig,
   eigener Live-Wert, eigene Historie, eigenes CSV.
4. Über die Buttons **Umbenennen** und **Entfernen** an jedem Sensor
   lässt sich der Name jederzeit ändern bzw. die Kopplung aufheben
   (gespeicherte Messwerte bleiben dabei erhalten).

Gekoppelte Sensoren werden in `data/devices.json` gespeichert und beim
nächsten Start automatisch wieder verbunden.

**Hinweis:** Der TP357S sendet in seinen BLE-Werbepaketen ggf. keinen
eindeutig erkennbaren Namen, deshalb werden beim Scan alle gefundenen
BLE-Geräte angezeigt, nicht nur ThermoPro-Sensoren. Falls unklar ist,
welcher Eintrag der richtige Sensor ist: alle anderen BLE-Geräte in der
Nähe kurz ausschalten/aus der Reichweite bringen und erneut scannen.

## Funktionsumfang

- **Scan:** `BleakScanner.discover(..., return_adv=True)` über den Button
  „Scan starten“. Die Ergebnistabelle zeigt **alle** von bleak gelieferten
  Rohdaten je Gerät: Name/local_name, MAC, RSSI, TX-Power,
  Service-UUIDs, Manufacturer-Data (roh als Hex je Company-ID),
  Service-Data (roh als Hex je UUID) sowie Backend-Rohdaten
  (`device.details` / `adv.platform_data`) — nicht gefiltert auf
  ThermoPro-Geräte, da der TP357S im Advertising ggf. keinen eindeutigen
  Namen sendet.
- **Live-Test (Probe):** Bei jedem Scan-Treffer gibt es neben „Hinzufügen“
  auch „Live-Test“ — verbindet sich sofort und zeigt den Rohdaten-Feed,
  **ohne** das Gerät dauerhaft zu koppeln (nicht in `devices.json`
  gespeichert). Über „Übernehmen“ lässt sich eine laufende Live-Test-
  Verbindung jederzeit in eine dauerhafte Kopplung umwandeln, ohne die
  Verbindung neu aufzubauen.
- **Mehrere Sensoren gleichzeitig:** jeder gekoppelte oder getestete Sensor
  läuft als eigene BLE-Verbindung mit eigener Wiederverbindungslogik,
  parallel in derselben Event-Loop.
- **Live-Rohdaten-Feed pro Gerät:** für jedes Gerät (gekoppelt oder
  Live-Test) zeigt ein eigenes Log-Panel jedes empfangene Notification-
  Paket (Hex-Dump, Länge, Dekodierungsergebnis oder „nicht dekodierbar“)
  sowie jeden gesendeten Schreibbefehl bei einem Verlaufs-Abruf — nicht
  nur der letzte Wert, sondern der volle Verlauf der letzten
  `device_log_buffer_size` Pakete (Standard: 500), abrufbar auch direkt
  über `/api/devices/<mac>/log`.
- **Live-Wert:** jeder gültige 7-Byte-Live-Wert wird dekodiert, validiert
  (−40…85 °C, 0…100 %) und in `live_readings` gespeichert (mit
  MAC-Zuordnung).
- **Historie:** Über den Button „Verlauf vom Sensor abrufen“ (Verlauf-
  Bereich, Sensor per Dropdown auswählbar) wird die interne Aufzeichnung
  abgerufen und in `history_readings` gespeichert. Da die Datensätze
  selbst keinen Zeitstempel tragen, wird er anhand von
  `history_record_interval_seconds` (Annahme über das Aufnahmeintervall
  des Geräts, Standard: 60 s) rückwärts vom Abrufzeitpunkt geschätzt.
- **Umbenennen/Entfernen:** jederzeit im Dashboard möglich.
- **CSV-Export:** `/api/export.csv?mac=<MAC>` bzw. Link im Dashboard
  (ohne `mac`-Parameter werden alle Sensoren exportiert).

## Debugging / Absturz analysieren

Alles landet in **`data/app.log`** (rotierend, Standard 5×5 MB) — auch nach
Schließen des Konsolenfensters, auch aus Hintergrund-Threads, auch aus der
asyncio-Event-Loop des BLE-Threads:

- Jede unbehandelte Exception in **jedem** Thread wird geloggt
  (`sys.excepthook` + `threading.excepthook`), nicht nur im Hauptthread.
- Jede unbehandelte Exception in der asyncio-Loop wird über einen
  eigenen `loop.set_exception_handler` geloggt statt nur nach stderr
  durchzurutschen.
- Jede Flask-Route hat einen globalen `errorhandler(Exception)`: eine
  fehlerhafte Anfrage crasht den Server nicht, sondern liefert Status 500
  mit vollem Traceback als JSON zurück UND loggt ihn.
- Jeder BLE-Verbindungsversuch, jeder Statuswechsel, jedes empfangene und
  gesendete Rohpaket wird geloggt (Level `DEBUG`).

Im Dashboard direkt einsehbar, ohne auf die Festplatte zu müssen:

- **„Server“-Bereich:** Config-Dump (`/api/config`), Debug-Dump
  (`/api/debug` — Loop-Status, lebende Threads/Tasks, verbundene Clients,
  Uptime, bleak-Version) und ein live nachladendes Log-Fenster
  (`/api/logs?lines=N`, Standard alle 2 s).
- Falls die App komplett abgestürzt ist (Prozess weg, Dashboard nicht mehr
  erreichbar): `data/app.log` direkt öffnen — der letzte Eintrag vor dem
  Abbruch zeigt in aller Regel die Ursache. `start.bat`/`start.sh` schließen
  das Konsolenfenster nicht automatisch, daher steht der Traceback i. d. R.
  auch dort.

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
