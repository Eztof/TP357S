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

Ein einziger Durchlauf genügt: venv anlegen (falls nötig), Abhängigkeiten
installieren, `config.json` aus `config.example.json` erzeugen (falls
nötig) und direkt die App starten — kein manuelles Eintragen einer
MAC-Adresse mehr nötig, also auch kein zweiter Durchlauf.

`start.py` selbst bitte nicht direkt per Doppelklick starten — es enthält
keine Installationslogik und benötigt die vorher von `start.bat`/`start.sh`
angelegte virtuelle Umgebung mit installierten Abhängigkeiten. `start.sh`
ist ein Bash-Skript und funktioniert unter Windows nicht (kein Fehler, es
passiert dort einfach nichts).

Falls `start.bat` mit einem Fehler bei der Installation von `bleak`
abbricht: erst den (dann unvollständigen) `venv`-Ordner löschen und
`start.bat` erneut ausführen — Installationsfehler werden erkannt und die
App startet dann nicht mit fehlenden Abhängigkeiten.

Es öffnet sich automatisch der Browser mit dem Dashboard unter
`http://127.0.0.1:5000/`.

## Sensoren koppeln

1. Im Dashboard unter „BLE-Scan“ auf **Scan starten** klicken (Standard:
   15 Sekunden, einstellbar). Die Ergebnistabelle zeigt alle gefundenen
   BLE-Geräte mit sämtlichen Rohdaten aus dem Advertisement.
2. Beim gewünschten Sensor auf **Hinzufügen** klicken und einen Namen
   vergeben. Der Sensor erscheint danach unter „Geräte“ und die App
   verbindet sich automatisch (inkl. Wiederverbindung, falls die
   Verbindung abbricht). Mit **Live-Test** lässt sich stattdessen erst
   nur reinschauen, ohne dauerhaft zu koppeln (siehe unten).
3. **Findet der Scan den Sensor nicht** (BLE-Advertising ist unzuverlässig
   — Geräte senden nicht immer durchgehend, manche Stacks verpassen
   Pakete): im Feld „MAC direkt“ die MAC-Adresse von Hand eintragen (z. B.
   aus den Windows-Bluetooth-Einstellungen, einer Scanner-App wie nRF
   Connect auf dem Smartphone, oder `bluetoothctl scan on` unter Linux)
   und direkt **Hinzufügen** bzw. **Live-Test** klicken — der Scan ist
   damit nur eine Komfortfunktion, keine Voraussetzung fürs Koppeln.
4. Beliebig viele Sensoren parallel koppeln — jeder läuft unabhängig,
   eigener Live-Wert, eigene Historie, eigenes CSV, eigener Rohdaten-Feed.
5. Über die Buttons **Umbenennen** und **Entfernen** an jedem Sensor
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
  Bereich, Sensor per Dropdown auswählbar) sendet die App die vier
  Vorbereitungs-/Anfrage-Kommandos (Uhrzeit-Sync, Session-Init, Offset,
  Datenanfrage — alle vollständig implementiert, siehe `app/protocol.py`)
  und speichert die zurückkommenden Datensätze in `history_readings`. Da
  die Datensätze selbst keinen Zeitstempel tragen, wird er anhand von
  `history_record_interval_seconds` (Annahme über das Aufnahmeintervall
  des Geräts, Standard: 60 s) rückwärts vom Abrufzeitpunkt geschätzt.
  „Anzahl Datensätze“ geht bis **65535** (NL/NH im Datenanfrage-Kommando
  sind 16-bit, das ist die tatsächliche Protokoll-Obergrenze, nicht
  willkürlich gesetzt — manche Sensoren können deutlich mehr als ein paar
  hundert Datensätze intern vorhalten). Das Warte-Timeout auf die Antwort
  skaliert automatisch mit der angefragten Anzahl (bis zu 10 Minuten bei
  sehr großen Anfragen) statt fix bei 30s zu liegen.
  ⚠️ Wiederholtes Abrufen großer Verläufe kann zu Dopplungen in
  `history_readings` führen: die geschätzten Zeitstempel werden bei jedem
  Abruf neu rückwärts vom jeweils aktuellen Zeitpunkt berechnet, verschieben
  sich also zwischen zwei Abrufen leicht — die `UNIQUE`-Dedupe in der
  Datenbank (siehe `app/storage.py`) greift dadurch nicht zuverlässig bei
  sich überlappenden Abrufen desselben Zeitraums.
- **Umbenennen/Entfernen:** jederzeit im Dashboard möglich.
- **CSV-Export:** `/api/export.csv?mac=<MAC>` bzw. Link im Dashboard
  (ohne `mac`-Parameter werden alle Sensoren exportiert).
- **Rohbefehl-Konsole (pro Gerät):** direkt unter dem Rohdaten-Feed jedes
  Geräts lassen sich beliebige Hex-Bytes über die Write-Characteristic
  (`…2b11`) an den Sensor senden (`POST /api/devices/<mac>/write`), die
  Antwort erscheint wie jedes andere empfangene Paket live im Feed. Der
  Button „+ Checksumme anhängen“ ruft `GET /api/checksum?hex=...` auf und
  hängt `sum(bytes) & 0xFF` als letztes Byte an. Nützlich zum Debuggen
  bzw. Experimentieren mit dem Protokoll direkt am echten Gerät, unabhängig
  vom normalen „Verlauf abrufen“-Ablauf.
- **Graph (Verlauf-Bereich):** zwei SVG-Charts (Temperatur, Luftfeuchte —
  bewusst getrennte Achsen statt einer gemeinsamen Dual-Achse), gespeist aus
  Live- **und** Verlaufsdaten zusammengeführt und chronologisch sortiert
  (`GET /api/devices/<mac>/series`). Auflösung einstellbar: Rohdaten,
  5-/15-Minuten-, Stunden- oder Tages-Mittel (serverseitig in
  `app/storage.py::aggregate_points` gebildet, nicht im Browser — bleibt
  auch bei vielen Punkten schnell). Hover zeigt Zeitpunkt + Wert des
  nächstgelegenen Punkts inkl. Fadenkreuz. „Punkte max.“ begrenzt, wie viele
  Rohpunkte vor der Aggregation geladen werden.

## ⚠️ Batterie-Byte (Byte 6) ist unverifiziert

Byte 6 des Live-Pakets wird als `battery_pct` dekodiert, weil die
Original-Spezifikation es so beschrieb — allerdings selbst nur mit
„vermutlich Batteriestand“. In echten Tests zeigten zwei unterschiedlich
alte TP357S-Sensoren beide durchgehend denselben Wert (44), was gegen eine
simple 0–100-%-Angabe spricht (entweder eine sehr grobe Stufeneinteilung
statt echter Prozentzahl, oder das Byte bedeutet etwas anderes). Ohne
Vergleichsdaten (z. B. den in der offiziellen ThermoPro-App angezeigten
Batteriestand zum selben Zeitpunkt) lässt sich das nicht verlässlich
korrigieren — im Zweifel dem Wert nicht vertrauen. Mit der Rohbefehl-
Konsole bzw. durch Beobachtung des Rohdaten-Feeds über einen längeren
Zeitraum (`hex=...` in `/api/devices/<mac>/log`) lässt sich das bei Bedarf
selbst weiter eingrenzen. In der normalen Live-Wert-Anzeige (Geräte-Tabelle)
wird der Wert deshalb gar nicht mehr angezeigt — nur noch im Rohdaten-Feed
als Teil des dekodierten JSON, wo er als Rohwert klar erkennbar bleibt.

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
Kein Auto-Neustart bei Absturz — bewusst nicht: `start.bat`/`start.sh`
starten die App genau einmal, das Konsolenfenster bleibt danach offen
stehen (`pause`), damit ein Absturz-Traceback (falls vorhanden) sichtbar
bleibt statt weggescrollt zu werden.

### Bekanntes Problem: Prozess stirbt beim Verbinden, ganz ohne Traceback

Falls im Log (oder in der Konsole) **kein** Python-Traceback erscheint,
sondern der Prozess beim Verbinden zu einem Sensor (`Verbinde zu ...`)
einfach komplett verschwindet: Das ist **kein** normaler Python-Fehler —
sonst hätten ihn die Crash-Hooks oben zuverlässig geloggt. Es handelt sich
um einen **nativen Absturz** (Access Violation) im Windows-Bluetooth-
Backend, auf das `bleak` unter Windows zwingend angewiesen ist (die
`winrt-*`-Pakete). Ein solcher Absturz reißt den kompletten Python-Prozess
sofort runter, bevor überhaupt eine Python-Exception geworfen werden kann
— dagegen kann kein Try/Except und kein Logging von innen etwas ausrichten.
Im Rohdaten-Feed des Geräts (`/api/devices/<mac>/log`) steht trotzdem der
letzte erreichte Schritt (`rufe client.connect() auf` vs. `client.connect()
zurueckgekehrt` vs. `aktiviere Notify`), das grenzt zumindest ein, in
welchem Aufruf es gestorben ist.

Angewendete Mitigationen (`app/ble_client.py`):

1. **`_resolve_device()`:** Vor jedem Verbindungsaufbau wird das Gerät erst
   gezielt per `BleakScanner.find_device_by_address(mac, timeout=12.0)`
   gesucht. Übergibt man `BleakClient` nur die MAC-Adresse als String,
   macht bleak/winrt intern selbst einen undurchsichtigen, oft zu kurzen
   Scan zur Auflösung — bei einem Gerät, das (wie der TP357S offenbar)
   nicht durchgehend wirbt, kommt dann `BleakDeviceNotFoundError`, obwohl
   das Gerät da ist (genau das Verhalten, das den ersten Verbindungsversuch
   im Testlauf zuverlässig als sauber geloggte Exception statt als
   Absturz beendet hat). Wird das `BLEDevice`-Objekt gefunden, wird es
   direkt an `BleakClient` übergeben statt nur der Adresse.
2. **`_build_client()`:** `winrt=dict(use_cached_services=False)` schaltet
   den WinRT-GATT-Geräte-Cache ab (verifiziert gegen `bleak`s
   `WinRTClientArgs`/`BleakClientWinRT`: steuert
   `BluetoothCacheMode.Uncached` vs. `Cached` bei der Service-Discovery).
   Ein korrupter Geräte-Cache im Windows-Bluetooth-Stack ist eine bekannte
   Ursache für genau so einen Absturz. Zusätzlich ein expliziter
   `timeout=20.0` statt bleaks Default.
3. Jeder Schritt (Suche, Connect-Aufruf, Notify aktivieren) wird einzeln
   in den Rohdaten-Feed des Geräts geloggt — falls es doch wieder
   abstürzt, zeigt `/api/devices/<mac>/log`, wie weit es diesmal kam.

Falls der Absturz trotzdem wieder auftritt (auf **Python 3.14** ist das
nicht ausgeschlossen — die `winrt`-Bindungen sind dafür noch vergleichsweise
neu und ihr Kompatibilitätsstand kann sich mit jedem Patch-Release ändern):

- `pip install --upgrade bleak` in der `venv` (neuere `winrt`-Unterpakete
  können Bugfixes enthalten, die `requirements.txt` nicht automatisch zieht).
- Prüfen, ob Windows-Update / aktuelle Bluetooth-Treiber verfügbar sind —
  einige dieser WinRT-Abstürze sind tatsächlich Treiberbugs, die nur über
  die WinRT-API sichtbar werden.
- Den Sensor einmal reproduzierbar über die Windows-Bluetooth-Einstellungen
  koppeln/entkoppeln, bevor er hier hinzugefügt wird — das kann einen
  hängengebliebenen internen Windows-Geräte-Cache zurücksetzen, unabhängig
  von `use_cached_services`.
- Als letzter Ausweg (nicht erforderlich, nur falls nichts davon hilft):
  Python 3.11/3.12 sind für `bleak`/`winrt` unter Windows am längsten im
  Einsatz und am besten getestet.

## Verlaufs-Protokoll (`app/protocol.py`)

Alle vier Verlaufs-Kommandos sind implementiert und gegen ein unabhängiges,
gegen echte Sensor-Antworten verifiziertes Referenzprojekt (pytp357s)
abgeglichen:

```python
TIME_SYNC_OPCODE      = bytes([0xA5])                                            # a) A5 YY MM DD HH MM SS DOW CS
SESSION_INIT_COMMAND  = bytes([0xCC,0xCC,0x02,0x01,0x00,0x00,0x01,0x04,0x66,0x66])  # b) fest
OFFSET_COMMAND        = bytes([0xCC,0xCC,0x04,0x00,0x00,0x00,0x00,0x04,0x66,0x66])  # c) fest
DATA_REQUEST_OPCODE   = bytes([0x01, 0x09])                                       # d) CC CC 01 09 00 00 00 YY MM DD HH MM SS NL NH CS 66 66
```

Details und Reihenfolge stehen als Kommentar am Anfang von
`app/protocol.py`. Wichtigste Stolperfalle, falls das Protokoll mal
angepasst werden muss: bei d) enthält der Datumsteil **kein**
Wochentags-Byte (anders als bei a) — nur `YY MM DD HH MM SS`, 6 statt
7 Bytes — und die Checksumme läuft nur über `01 09 00 00 00 <Datum> NL NH`,
nicht über die äußeren `CC CC`/`66 66`-Rahmen-Bytes.

## Datenschutz / Speicherort

Alle Daten bleiben lokal auf dem PC in `data/tp357s.db` (SQLite). Es gibt
keine Cloud-Anbindung; der Webserver lauscht standardmäßig nur auf
`127.0.0.1` (nicht im Netzwerk erreichbar).
