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
Jedes Log-/Dump-Fenster hat einen „In Zwischenablage kopieren“-Button
direkt darüber.

Oben im Dashboard gibt es Reiter: „Sensoren“ (die komplette TP357S-
Anbindung), „Hue“ (rohe Anbindung an die Philips-Hue-Bridge, siehe unten),
„Gebäudeplan“ (Lampen auf einem eigenen Grundriss-Bild platzieren und
steuern, siehe unten) und „Alarm“ (Vollbild-Warnung bei Bewegungsmelder-
Auslösung, siehe unten). Jeder Themenblock innerhalb eines Reiters ist
einzeln einklappbar (Klick auf die Kopfzeile). Welche Bereiche eingeklappt
sind und welcher Reiter zuletzt aktiv war, wird **serverseitig** in
`data/ui_state.json` gespeichert (`GET`/`POST /api/ui-state`) — bleibt
also auch nach einem Neustart des Servers erhalten, nicht nur im selben
Browser.

Oben rechts schaltet „🌙 Dark“/„☀️ Hell“ zwischen hellem und dunklem
Design um — rein optisch (CSS-Variablen in `style.css`, per
`data-theme`-Attribut auf `<html>`), keine Funktion ändert sich. Die
Wahl wird genauso wie die Reiter/Panels serverseitig in `ui_state.json`
gespeichert und bleibt daher auch nach einem Neustart erhalten. Die
Alarm-Vollbildwarnung bleibt bewusst in beiden Designs gleich grell rot.

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
    ble_client.py          # BleManager: startet/überwacht den BLE-Worker-Kindprozess, Auto-Sync-Scheduler
    ble_worker.py            # läuft im isolierten Kindprozess: die eigentliche bleak-Kommunikation
    devices.py              # Liste gekoppelter Sensoren (data/devices.json)
    storage.py                # SQLite-Speicherung (Live-Werte + Historie, je Sensor)
    state.py                   # geteilter Programmstatus (alle Sensoren, Scan, Rohdaten-Logs)
    logging_setup.py            # Logdatei + globale Crash-Hooks (Haupt-/Hintergrund-Threads, asyncio)
    ui_state.py                   # persistiert Tab/Panel-Zustand des Dashboards (data/ui_state.json)
    hue_client.py                   # Anbindung an die lokale Philips-Hue-Bridge (CLIP v2)
    hue_layout.py                     # Grundriss-Bild + Lampen-/Sensor-Positionen (data/hue_layout/)
    server.py                           # lokaler Webserver (Flask) + JSON-API
    static/                             # Dashboard (HTML/CSS/JS, bewusst schmucklos)
  data/
    tp357s.db                        # SQLite-Datenbank (wird automatisch angelegt)
    devices.json                       # gekoppelte Sensoren (wird automatisch angelegt)
    app.log                              # Logdatei, rotierend (wird automatisch angelegt)
    hue_layout/                          # Grundriss-Bild + layout.json (wird automatisch angelegt)
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
  hundert Datensätze intern vorhalten). Auf die Antwort wird **Idle-basiert**
  gewartet: solange neue Pakete reinkommen, wartet die App weiter; erst wenn
  20s lang nichts mehr kam (oder eine großzügige, nach Anzahl gestaffelte
  Gesamt-Obergrenze von 2–30 Minuten erreicht ist), wird abgebrochen. Ein
  fester Timeout war bei größeren Abrufen über eine reale, ggf. schwache
  BLE-Verbindung unzuverlässig — die Übertragungsrate ist nicht konstant.
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
  Rohpunkte vor der Aggregation geladen werden. Horizontal ziehen zoomt in
  einen Zeitbereich hinein (wirkt auf beide Charts gleichzeitig), Doppelklick
  oder „Zoom zurücksetzen“ stellt die volle Ansicht wieder her. Die separate
  Rohdaten-Tabelle unterhalb der Graphen wurde entfernt (redundant zum
  Graphen + CSV-Export, unnötiger Platzverbrauch).
- **Auto-Sync (pro Gerät):** Checkbox + Intervall (Minuten) im Rohdaten-Panel
  jedes gekoppelten Geräts. Eingeschaltet ruft die App automatisch im
  eingestellten Takt den Verlauf ab — siehe „Auto-Sync“ unten für die
  genaue Funktionsweise (Lücken-Erkennung, Live-Abgleich).

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
  (`/api/debug` — Worker-PID, Worker-Status/Exitcode, Anzahl automatischer
  Neustarts, verbundene Clients, laufende Verlaufsabrufe, Uptime) und ein
  live nachladendes Log-Fenster (`/api/logs?lines=N`, Standard alle 2 s).
- Falls die App komplett abgestürzt ist (Prozess weg, Dashboard nicht mehr
  erreichbar): `data/app.log` direkt öffnen — der letzte Eintrag vor dem
  Abbruch zeigt in aller Regel die Ursache. `start.bat`/`start.sh` schließen
  das Konsolenfenster nicht automatisch, daher steht der Traceback i. d. R.
  auch dort.

Kein Auto-Neustart der **gesamten App** bei Absturz — bewusst nicht:
`start.bat`/`start.sh` starten die App genau einmal, das Konsolenfenster
bleibt danach offen stehen (`pause`), damit ein Absturz-Traceback (falls
vorhanden) sichtbar bleibt statt weggescrollt zu werden. Der isolierte
BLE-Worker-Prozess (siehe unten) wird davon unabhängig automatisch
neugestartet — das betrifft nur den BLE-Teil, nicht den Webserver/das
Dashboard selbst.

### Architektur: BLE läuft in einem isolierten, überwachten Kindprozess

**Hintergrund:** `bleak`s WinRT-Backend stürzt auf Windows/Python 3.14
reproduzierbar mit einer **nativen Access Violation** ab (kein Python-
Traceback, kein `sys.excepthook`, kein `threading.excepthook`, kein
asyncio-Exception-Handler kann das abfangen — der Prozess stirbt sofort,
mitten im Aufruf). Mehrere reine Softwarefixes wurden ausprobiert
(`use_cached_services=False`, expliziter Pre-Connect-Scan) — der Cache-Fix
ist ein echter, dokumentierter Workaround und bleibt aktiv, hat den Absturz
aber nicht vollständig behoben; der Pre-Connect-Scan wurde nach echten
Log-Auswertungen wieder entfernt, weil er den Absturz nachweislich
*häufiger* statt seltener gemacht hat (mehr WinRT-Scanner-Objekt-Zyklen).

Statt weiter reine Softwarefixes zu suchen, läuft die komplette
`bleak`-Kommunikation seitdem in einem **eigenen Kindprozess**
(`app/ble_worker.py`, gestartet über Pythons `multiprocessing`, spawn-
Methode). Stirbt dieser Prozess — aus welchem Grund auch immer, inklusive
eines nativen Absturzes ganz ohne Traceback — bemerkt der Elternprozess
(`BleManager` in `app/ble_client.py`) das über einen Supervisor-Thread
(`proc.is_alive()`/`proc.exitcode`, Poll-Intervall 2 s) und startet
automatisch einen neuen Worker-Prozess, der sich wieder mit allen bekannten
Geräten verbindet. Webserver, Dashboard, SQLite-Datenbank und der Firebase-
Upload laufen im Elternprozess weiter und sind von einem Worker-Absturz
nicht betroffen — nur die betroffenen Geräte zeigen kurzzeitig den Status
`error` mit einer entsprechenden Meldung, bis der neue Worker wieder
verbunden hat.

Kommunikation zwischen Eltern- und Worker-Prozess läuft ausschließlich über
zwei `multiprocessing.Queue` (Kommandos raus, Ereignisse rein) — der Worker
hält selbst keinerlei überlebenswichtigen Zustand (kein SQLite, kein
AppState); jedes empfangene Rohpaket, jeder Statuswechsel und jeder Fehler
wird als Ereignis an den Elternprozess gemeldet, der die Persistenz
übernimmt. Das Worker-eigene Logging läuft über eine dritte Queue
(`logging.handlers.QueueHandler`/`QueueListener`) in dieselbe `data/app.log`
wie der Rest der App — zwei Prozesse dürfen nicht gleichzeitig in denselben
`RotatingFileHandler` schreiben, das wäre nicht prozesssicher.

**Wichtige Falle, die dabei gefunden und behoben wurde:** Stirbt ein
Kindprozess, während sein Lese-Thread in `Queue.get()` blockiert war, hält
er dabei intern einen prozessübergreifenden Lock (POSIX-Semaphore) — ein
harter Abbruch (`os._exit()`/eine native Access Violation, kein normales
`Queue.close()`) gibt diesen Lock **nie wieder frei**. Ein neuer Prozess,
der dieselbe Queue weiterverwendet, würde dann selbst bei seinem allerersten
`get()` für immer blockieren, ohne je wieder auf Kommandos zu reagieren —
genau das wurde beim Testen mit einem simulierten Absturz reproduziert (der
Worker wurde sauber neugestartet, hat aber nie wieder verbunden). Die
Lösung: bei jedem (Neu-)Start werden **frische** Queues (Kommando, Ereignis,
Log) samt frischem Event-Reader-Thread erstellt, nie die alten
wiederverwendet.

Falls der native Absturz trotzdem weiterhin auftritt (auf **Python 3.14**
ist das nicht ausgeschlossen — die `winrt`-Bindungen sind dafür noch
vergleichsweise neu): das ist jetzt kein Blocker mehr für die App als
Ganzes, nur noch eine kurze Verbindungsunterbrechung pro Vorfall
(Neustart-Backoff: 5 Sekunden). Zusätzlich weiterhin hilfreich:

- `pip install --upgrade bleak` in der `venv` (neuere `winrt`-Unterpakete
  können Bugfixes enthalten, die `requirements.txt` nicht automatisch zieht).
- Prüfen, ob Windows-Update / aktuelle Bluetooth-Treiber verfügbar sind.
- Den Sensor einmal reproduzierbar über die Windows-Bluetooth-Einstellungen
  koppeln/entkoppeln, bevor er hier hinzugefügt wird.

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

**Wichtige Erkenntnis aus echten Log-Daten:** Ob ein empfangenes Paket ein
Historie-Header ist, entscheidet `_handle_history_or_end`
(`app/ble_client.py`) **immer** anhand seines Inhalts
(`protocol.is_history_header`), niemals anhand der Paketposition
("erstes Paket = automatisch Historie" war ein Bug, siehe Auto-Sync unten).
Ein normaler Live-Push kann real beobachtet als allererste Antwort auf eine
Datenanfrage reinkommen — das ist laut Spezifikation ohnehin das implizite
Ende-Kriterium, kein Sonderfall.

## Auto-Sync

Periodischer, automatischer Verlaufs-Abruf mit Lücken-Erkennung (`app/ble_client.py`,
`BleManager._auto_sync_loop`/`_run_auto_sync_for_device`/`_check_sync`). Pro Gerät
im Dashboard ein- und ausschaltbar, Einstellung + Fortschritt (`last_synced_ts`)
überleben einen Neustart (gespeichert in `data/devices.json`).

**Ablauf bei jedem Tick** (Scheduler prüft alle 30s, ob ein Gerät fällig ist):

1. **Lücke berechnen:** `jetzt − last_synced_ts` (beim allerersten Mal: das
   eingestellte Intervall). Daraus wird über `history_record_interval_seconds`
   die Anzahl benötigter Datensätze geschätzt, plus eine kleine Sicherheitsmarge
   (`AUTO_SYNC_GAP_MARGIN_RECORDS = 10`). War die letzte Synchronisation vor
   10 Minuten erfolgreich und ist seitdem nichts schiefgegangen, werden also
   nur die letzten ~10 Minuten angefragt. Ist die letzte erfolgreiche Sync
   schon 40 Minuten her (z. B. weil der Sensor zwischenzeitlich außer
   Reichweite war), wird automatisch eine entsprechend größere Menge
   angefragt — die Lücke schließt sich von selbst, ohne dass verlorene
   Zeiträume dauerhaft fehlen.
2. **Abrufen** wie beim manuellen „Verlauf abrufen“ (alle vier Kommandos,
   Idle-Timeout-basiertes Warten auf die Antwort, siehe oben).
3. **`last_synced_ts` nur bei sauberem Abschluss vorrücken:** Kam die Antwort
   sauber terminiert zurück (`clean=True`, siehe Verlaufs-Protokoll-Abschnitt),
   wird `last_synced_ts` auf den aktuellen Zeitpunkt gesetzt — beim nächsten
   Tick wird dann wieder nur das normale Intervall angefragt. Brach die
   Übertragung ab (Idle-/Gesamt-Timeout, `clean=False`), bleibt
   `last_synced_ts` unverändert, sodass der **nächste** Versuch automatisch
   eine größere, die Lücke einschließende Menge anfragt statt den fehlenden
   Zeitraum stillschweigend zu verlieren.
4. **Sync-Check:** Nach einem sauberen Abruf wird der neueste (per Zeitstempel-
   Schätzung) Verlaufs-Datensatz mit dem aktuellen Live-Wert verglichen
   (Toleranz: 1,0 °C / 6 % Feuchte, `SYNC_CHECK_*_TOLERANCE` in
   `app/ble_client.py`). Passen beide zusammen, ist das ein Indiz, dass die
   angenommene `history_record_interval_seconds` einigermaßen stimmt — reine
   Plausibilitätsprüfung, **keine** automatische Korrektur des Intervalls.
   Ergebnis (`last_sync_check`) steht im Dashboard und in `/api/devices`.

## Firebase-Upload (Firestore)

Optionaler periodischer Upload aller neuen Live-/Verlaufs-Messwerte nach
Firestore (`app/firebase_sync.py`). Standardmäßig **deaktiviert**
(`firebase_enabled: false`).

**Warum Firestore und nicht Realtime Database oder Storage:** Firestore ist
für strukturierte, abfragbare Zeitreihen-Daten mit moderater Schreibrate
gemacht — genau der Fall hier (kleine Batches alle paar Minuten, später
z. B. nach Sensor/Zeitraum abfragbar). Realtime Database ist auf sehr
hochfrequente, kleine Live-Sync-Updates ausgelegt und Abfragen über
Zeiträume sind dort deutlich umständlicher. Cloud Storage ist Datei-Ablage
(Objekte), keine strukturierten Einzel-Datensätze — ungeeignet hier.

**Security Rules sind irrelevant:** Der Upload läuft über einen
Service-Account (Firebase Admin SDK) direkt vom eigenen Rechner aus.
Admin-Zugriff umgeht Firestore-Security-Rules grundsätzlich — die gelten
nur für Client-SDKs (Browser-/App-Code), nie für serverseitigen
Admin-Zugriff. Es muss und wird nichts an den Rules des Projekts verändert.

### Einrichtung

1. Firebase Console → Projekteinstellungen → Dienstkonten → „Neuen privaten
   Schlüssel generieren“ → die heruntergeladene JSON-Datei als
   `firebase-service-account.json` in den Projektordner legen (neben
   `start.bat`). Die Datei ist in `.gitignore` eingetragen — landet nicht
   im Repo, aber lokal ist keine Verschlüsselung o. Ä. vorgesehen: sie
   liegt als Klartext-Datei auf der Platte, wie jede lokale Credential-Datei.
2. In `config.json`: `"firebase_enabled": true` setzen. Optional
   anpassen: `firebase_collection` (Standard: `"readings"`),
   `firebase_upload_interval_seconds` (Standard: 600 = 10 Min.),
   `firebase_upload_initial_delay_seconds` (Standard: 300 = 5 Min. Versatz
   zum Start, damit der Auto-Sync-Mechanismus vor dem ersten Upload schon
   mindestens einmal gelaufen ist).
3. App neu starten. Im Dashboard unter „Firebase-Upload“: Status, letzter
   Lauf, Ergebnis pro Sensor — sowie ein „Jetzt hochladen“-Button für einen
   sofortigen Testlauf statt auf den nächsten Tick zu warten.

### Datenmodell

**Eine flache Collection** (alle Sensoren zusammen, Standardname
`readings`) statt einer Unter-Collection pro Sensor — einfacher zu pflegen
und für Firestore-Abfragen genauso leistungsfähig.

**Wichtig (Kosten):** Firestore berechnet pro **Schreiboperation**, nicht
pro Byte. Ein Dokument je Einzelmesswert würde bei jedem 10-Minuten-Tick
pro Sensor mehrere Writes erzeugen — unnötig teuer bei vielen Sensoren
und/oder häufigen Messungen. Stattdessen wird **pro Sensor pro
Upload-Durchlauf genau EIN Dokument** geschrieben, das alle seit dem
letzten Durchlauf neuen Messwerte als Array enthält:

```json
{
  "mac": "AA:BB:CC:DD:EE:FF",
  "name": "Wohnzimmer",
  "synced_at": "2026-09-15T21:05:03+00:00",
  "count": 3,
  "readings": [
    { "ts": "2026-09-15T20:55:00+00:00", "temperature_c": 21.4, "humidity_pct": 54, "source": "history" },
    { "ts": "2026-09-15T21:00:00+00:00", "temperature_c": 21.5, "humidity_pct": 55, "source": "live" },
    { "ts": "2026-09-15T21:04:12+00:00", "temperature_c": 21.5, "humidity_pct": 55, "source": "live" }
  ]
}
```

Ergebnis: bei z. B. 3 Sensoren und 10-Minuten-Intervall sind das nur noch
**ca. 432 Schreiboperationen/Tag** insgesamt (statt potenziell tausenden
bei einem Dokument je Messwert) — unabhängig davon, wie viele Messwerte in
so einem Zeitraum tatsächlich angefallen sind. Einzige Ausnahme: enthält
ein einzelner Durchlauf sehr viele neue Messwerte (z. B. der allererste
volle Verlaufsabruf eines neuen Sensors mit mehreren tausend Datensätzen),
wird auf mehrere Dokumente aufgeteilt (`FIRESTORE_MAX_READINGS_PER_DOC` =
5000 in `app/firebase_sync.py`), um Firestores 1-MiB-Dokumentlimit sicher
einzuhalten — auch dann bleibt die Anzahl der Schreiboperationen weit unter
„ein Write pro Messwert“.

`source` in jedem Array-Eintrag ist `"live"` oder `"history"`. Für Abfragen
nach Sensor + Zeitraum lohnt sich ein zusammengesetzter Index auf
`(mac, synced_at)` in der Firestore-Konsole, falls Firestore danach fragt.
Da die Messwerte pro Dokument in einem Array liegen, sind serverseitige
Abfragen nach einzelnen Messwert-Zeitstempeln (nicht `synced_at` des ganzen
Batches) mit reinen Firestore-Queries nicht direkt möglich — dafür müsste
man die `readings`-Arrays client-seitig nach dem Laden filtern. Für den
Anwendungsfall hier (Rohdaten-Backup + gelegentliche Auswertung) ist das
ein bewusster Kompromiss zugunsten deutlich niedrigerer Kosten.

**Fortschritt wird lokal verfolgt**, nicht in Firestore: SQLite-Tabelle
`firebase_sync_state` merkt sich je Sensor die zuletzt hochgeladene
`id` aus `live_readings`/`history_readings`. Jeder Tick lädt nur, was seit
dem letzten Mal neu dazugekommen ist — kein Firestore-Read nötig, um das
herauszufinden (spart Kosten/Latenz), funktioniert auch über
Neustarts hinweg weiter.

**Hinweis zu bereits hochgeladenen Altdaten:** Vor dieser Umstellung wurde
kurzzeitig ein Dokument je Einzelmesswert geschrieben. Diese alten
Dokumente wurden bewusst NICHT gelöscht/migriert (kein zusätzliches
Lösch-/Migrationsrisiko) und stehen einfach neben den neuen, gebündelten
Dokumenten in derselben Collection — beide Formate sind an der Anzahl der
Felder (`readings`-Array vorhanden oder nicht) unterscheidbar, falls das
für eine spätere Auswertung relevant wird.

## Hue-Bridge (Reiter „Hue“, `app/hue_client.py`)

Rein lokale Anbindung an eine Philips-Hue-Bridge im selben Heimnetz (kein
Cloud-Zugriff) über deren moderne **CLIP-v2-API**. Aktuell rein
datensammelnd/roh — was daraus gebaut wird, ist ein späterer Schritt.

### Verbinden

1. Im Reiter „Hue“ → „Hue-Bridge: Verbindung“: Bridge-IP eintragen (im
   Heimnetzwerk-Router oder in der offiziellen Hue-App nachzuschauen).
   „Bridge prüfen“ ruft `GET https://<ip>/api/config` auf — funktioniert
   OHNE Kopplung, zeigt Name/Bridge-ID/Software-Version zur Bestätigung,
   dass unter der IP wirklich eine Hue-Bridge antwortet.
2. Auf **„Jetzt koppeln“** klicken — das öffnet ein 30-Sekunden-Fenster, in
   dem `app/hue_client.py` automatisch alle ~1,2s einen neuen
   Kopplungsversuch startet (`app.js`, `attemptHuePair`-Schleife). Irgendwann
   *innerhalb* dieses Fensters die **runde Taste auf der Bridge drücken** —
   Reihenfolge zum Klick egal. Das ist ein Sicherheitsmechanismus der
   Bridge selbst (verhindert, dass sich fremde Geräte im Netz automatisch
   koppeln) und kann nicht abgekürzt werden; die Bridge gibt dabei bewusst
   **kein sichtbares Feedback** (kein Blinken o. Ä.) — sie liefert bei jedem
   Versuch vor dem Tastendruck einfach still Fehler „link button not
   pressed“ zurück, das ist normal und kein Fehlerfall. Andere bereits
   gekoppelte Apps (offizielle Hue-App, HomeKit, Home Assistant, ...) sind
   von einer neuen Kopplung nicht betroffen — jede App bekommt einen
   eigenen, unabhängigen `application_key`, keine ersetzt eine andere.
3. Nach erfolgreicher Kopplung wird der `application_key` (Zugangs-Token)
   zusammen mit Bridge-IP und Bridge-ID lokal in `hue_config.json` im
   Projekt-Hauptordner gespeichert (**neben `start.bat`, NICHT in `data/`**
   — wie die Firebase-Zugangsdaten in `.gitignore` eingetragen, landet
   nicht im Repo). „Kopplung aufheben“ löscht diese lokal wieder.

**Kopplung auf einem anderen Rechner/nach frischem Download wiederverwenden:**
`hue_config.json` lässt sich 1:1 in einen neu heruntergeladenen/entpackten
Projektordner kopieren — bereits VOR dem ersten Start, direkt neben
`start.bat` (der Ordner `data/` existiert zu diesem Zeitpunkt noch nicht,
er wird erst beim ersten Start automatisch angelegt). Die App ist dann
beim ersten Start bereits gekoppelt, ganz ohne erneuten Tastendruck an der
Bridge.

### Einmaliger Abruf

„Jetzt einmalig abrufen“ ruft `GET /clip/v2/resource` auf — liefert IN
EINEM Aufruf ALLE Ressourcen, die die Bridge kennt (Lichter, Sensoren,
Räume, Zonen, Szenen, Tasten, Geräte, Bewegungsmelder, Helligkeit,
Temperatur, Stromverbrauch, Software-Update-Status, ...) als rohes JSON.
Wird komplett im Dashboard angezeigt (keine Vorverarbeitung/Filterung).

### Live

„Live starten“ öffnet einen echten **Server-Sent-Events-Push-Stream**
(`GET /eventstream/clip/v2`, dauerhafte HTTPS-Verbindung) statt zu pollen -
die Bridge schickt Änderungen (Lampe an/aus, Sensor ausgelöst, Helligkeit
geändert, ...) in Echtzeit, sobald sie passieren. Jedes empfangene Ereignis
landet roh im Live-Log; bricht die Verbindung ab, wird automatisch nach 5s
neu verbunden (`SSE_RECONNECT_DELAY_SECONDS` in `app/hue_client.py`).
„Live stoppen“ beendet den Stream sauber.

### TLS-Zertifikat

Die Bridge nutzt für ihre lokale HTTPS-API ein selbstsigniertes Zertifikat
(keine öffentliche CA). Auf Nutzerwunsch wird die Zertifikatsprüfung
bewusst deaktiviert (`verify=False` bei allen Aufrufen) — die Verbindung
bleibt trotzdem TLS-verschlüsselt, nur die Zertifikatskette wird nicht
geprüft. Bewusster Kompromiss fürs eigene Heimnetz, analog zur bereits
beim Firebase-Upload besprochenen Haltung („Sicherheit spielt hier eine
untergeordnete Rolle“).

## Gebäudeplan (Reiter „Gebäudeplan“, `app/hue_layout.py`)

Lesen **und** Schreiben der Hue-Lampen, verortet auf einem selbst
hochgeladenen Grundriss-Bild — eigener Reiter, unabhängig vom rohen
Hue-Datenstrom im Hue-Reiter.

- **Grundriss-Bild:** eigenes Foto/Scan/Screenshot hochladen (PNG/JPG/GIF/
  WEBP, max. 20 MiB). Liegt in `data/hue_layout/floorplan.<ext>`, Metadaten
  (Dateiname + Positionen) in `data/hue_layout/layout.json` — beides kein
  Credential, daher in `data/` statt im Hauptordner (anders als
  `hue_config.json`).
- **Platzieren per Drag&Drop:** Lampen und Sensoren (Bewegung, Helligkeit,
  Temperatur), die noch keine Position haben, erscheinen in der Seitenleiste
  „Nicht platziert“ und lassen sich auf den Grundriss ziehen (natives
  HTML5-Drag&Drop, keine eigene Maus-Tracking-Logik nötig). Position wird
  als Bruchteil (0..1) der Bildgröße gespeichert — bleibt bei jeder
  Bildschirmgröße korrekt. Das ×-Icon an einem platzierten Icon entfernt es
  wieder von der Karte (Position, nicht das Gerät selbst).
- **Lampen-Steuerung:** Klick auf ein platziertes Lampen-Icon öffnet das
  Steuerpanel — An/Aus, Helligkeit (falls dimmbar), Farbe (falls farbfähig,
  `<input type=color>` mit Standard-Philips-Formel nach CIE-xy umgerechnet),
  Farbtemperatur warm↔kalt (falls unterstützt, Mirek-Bereich direkt aus den
  Lampen-Fähigkeiten der Bridge gelesen). Jede Änderung sendet sofort (bei
  Reglern debounced, 250 ms) ein `PUT /clip/v2/resource/light/<id>` mit nur
  den geänderten Feldern.
- **Räume/Zonen:** eigenes Panel mit einer Zeile je Hue-Raum/-Zone —
  An/Aus + Helligkeit wirken über `PUT /clip/v2/resource/grouped_light/<id>`
  auf alle Lampen der Gruppe gleichzeitig.
- **Bewegungsmelder — live:** großes Banner, das bei einem `motion`-Ereignis
  aus dem SSE-Live-Stream (siehe Hue-Reiter, `/eventstream/clip/v2`) sofort
  umschaltet (inkl. Puls-Animation) und wieder zurück, sobald die Bewegung
  endet — plus eine laufende Tabelle der letzten Bewegungsereignisse mit
  Zeitstempel. Braucht den laufenden Live-Stream (Hinweis + Direkt-Start-
  Button erscheinen, falls der noch nicht läuft).
- **Datenherkunft:** Lampen/Räume/Zonen/Sensoren werden aus dem rohen
  `/clip/v2/resource`-Pull zu einer direkt nutzbaren Struktur verknüpft
  (`HueManager.resolve_topology()` in `app/hue_client.py`) — eine Lampe
  trägt selbst keinen Raumnamen, nur eine Geräte-Referenz; welcher Raum sie
  enthält, steht wiederum nur in den `children` der Raum-Ressource. Diese
  Verknüpfung läuft serverseitig, nicht im Browser.

## Alarm (Reiter „Alarm“)

Eigener Reiter nur für eine sehr auffällige Vollbild-Warnung, wenn der
Bewegungsmelder auslöst — gedacht zum Offenlassen auf einem Zweitbildschirm
oder Tablet.

- **Anzeige:** Löst der Bewegungsmelder aus (aus demselben SSE-Live-Stream,
  der auch das Bewegungs-Banner im Gebäudeplan speist — kein doppeltes
  Polling), blitzt der gesamte Bildschirm für die eingestellte Dauer
  (Standard 5 s, einstellbar) rot/dunkelrot im Wechsel auf, mit großem Text
  „BEWEGUNG ERKANNT“. Die Auslösung selbst wird immer erkannt (Reiter-
  unabhängig, solange der Live-Stream läuft) — sichtbar wird die Warnung
  aber nur, während der Alarm-Reiter tatsächlich geöffnet ist (genau dafür
  ist der Reiter da).
- **Status & Verlauf:** Statuszeile zeigt den zuletzt auslösenden Sensor mit
  Zeitstempel, eine Tabelle darunter führt die letzten 100 Auslösungen.
  „Jetzt testen“-Button löst die Warnung manuell aus, ohne auf eine echte
  Bewegung zu warten.
- Das Overlay blockiert bewusst keine Klicks (`pointer-events: none`) — die
  Tab-Leiste bleibt auch während des Aufblitzens bedienbar.

## Datenschutz / Speicherort

Alle Daten bleiben lokal auf dem PC in `data/tp357s.db` (SQLite) — außer,
Firebase-Upload ist aktiviert (siehe oben), dann werden alle neuen
Live-/Verlaufs-Messwerte zusätzlich in dein eigenes Firestore-Projekt
hochgeladen. Ohne Firebase-Upload gibt es keine Cloud-Anbindung; der
Webserver lauscht standardmäßig nur auf `127.0.0.1` (nicht im Netzwerk
erreichbar). Die Hue-Bridge-Anbindung bleibt vollständig im lokalen
Heimnetz (kein Cloud-Zugriff auf die Bridge); der `application_key`
liegt lokal in `hue_config.json` (Projekt-Hauptordner, neben `start.bat`), wie die Firebase-Zugangsdaten
nicht im Repo.
