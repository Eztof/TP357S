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
  Bereich, Sensor per Dropdown auswählbar) wird die interne Aufzeichnung
  abgerufen und in `history_readings` gespeichert. Da die Datensätze
  selbst keinen Zeitstempel tragen, wird er anhand von
  `history_record_interval_seconds` (Annahme über das Aufnahmeintervall
  des Geräts, Standard: 60 s) rückwärts vom Abrufzeitpunkt geschätzt.
- **Umbenennen/Entfernen:** jederzeit im Dashboard möglich.
- **CSV-Export:** `/api/export.csv?mac=<MAC>` bzw. Link im Dashboard
  (ohne `mac`-Parameter werden alle Sensoren exportiert).
- **Rohbefehl-Konsole (pro Gerät):** direkt unter dem Rohdaten-Feed jedes
  Geräts lassen sich beliebige Hex-Bytes über die Write-Characteristic
  (`…2b11`) an den Sensor senden (`POST /api/devices/<mac>/write`), die
  Antwort erscheint wie jedes andere empfangene Paket live im Feed. Der
  Button „+ Checksumme anhängen“ ruft `GET /api/checksum?hex=...` auf und
  hängt `sum(bytes) & 0xFF` als letztes Byte an (dieselbe Checksumme, die
  auch die Verlaufs-Kommandos verwenden). Gedacht zum Ausprobieren der drei
  fehlenden Verlaufs-Kommandos (siehe Hinweis unten) direkt am echten Gerät.
  Der Button „Beispiel einfügen (Datenanfrage)“ füllt das Eingabefeld mit
  dem einzigen vollständig bekannten und funktionierenden Kommando
  (`01 09 ...`, fertig kodiert mit aktueller Uhrzeit und Anzahl 500) —
  praktisch für einen ersten Test ganz ohne eigenes Wissen über das
  Protokoll: Button klicken, „Rohbefehl senden“ klicken, im Feed direkt
  darunter beobachten, ob eine Antwort kommt.
- **Zeit-Kandidat bauen (pro Gerät):** eigenes Eingabefeld unterhalb der
  Rohbefehl-Konsole. Praefix eintragen (z. B. `0101`), Button klicken —
  baut `Praefix + aktuelles Datum (YY MM DD HH MM SS DOW) + Checksumme`
  (`GET /api/protocol/time-shaped-candidate?prefix=...`, gleiches Schema
  wie das bekannte Datenanfrage-Kommando) und trägt das Ergebnis direkt ins
  Sendefeld ein. Erspart das manuelle Ausrechnen von Datum und Checksumme
  bei jedem Testversuch.

## Wie komme ich an die drei fehlenden Verlaufs-Kommandos?

Reines Ausprobieren zufälliger Bytes bringt bei den drei unbekannten
Kommandos (Uhrzeit-Sync, Session-Init, Offset) wenig — der Byte-Raum ist
zu groß. Drei sinnvolle Wege, der Reihe nach:

**1. Erst mal testen, ob sie überhaupt nötig sind.** Manche Sensoren
akzeptieren eine Datenanfrage auch ohne die vorgeschalteten
„Vorbereitungs“-Kommandos. Im Dashboard bei einem verbundenen Gerät:
„Beispiel einfügen (Datenanfrage)“ → „Rohbefehl senden“ → Feed beobachten.
Kommt danach eine Antwort mit dem Header `CC CC 01 ...`, war das schon die
ganze Lösung (dann bitte melden, dann trage ich es direkt als
Sonderfall in `app/protocol.py` ein). Kommt nichts oder eine Fehlerantwort,
sind die drei Kommandos vermutlich wirklich nötig.

**2. Begründet raten mit „Zeit-Kandidat bauen“.** Da das bekannte
Datenanfrage-Kommando `01 09` heißt, ist es plausibel, dass Uhrzeit-Sync
ein Geschwister-Kommando mit demselben `01`-Präfix ist. Präfixe `0101`
bis `0108` der Reihe nach durchprobieren (jeweils: Präfix eintragen →
„Zeit-Kandidat bauen“ → „Rohbefehl senden“ → Feed beobachten, ob eine
Reaktion kommt). Das ist ein informierter Versuch, keine Garantie — aber
kostenlos und schnell durchprobiert.

**Wichtig zu wissen: Bluetooth lässt sich nicht wie WLAN „nebenbei“
mitschneiden.** Koppelt man das Handy separat mit dem PC, sieht der PC
dadurch **nicht** die andere Bluetooth-Verbindung zwischen Handy und
Sensor — jede Bluetooth-Verbindung ist paarweise, kein gemeinsames Medium
wie offenes WLAN. Um wirklich zu sehen, was die ThermoPro-App an den
Sensor sendet, bleiben nur zwei Wege: das interne Bluetooth-Log des
Handys (nächster Punkt) oder ein dedizierter BLE-Sniffer als separates
drittes Gerät (Hardware wie ein Nordic-nRF52840-Dongle mit
Sniffer-Firmware + Wireshark, zeichnet die Funkpakete zwischen Handy und
Sensor unabhängig von beiden auf).

**3. BLE-Sniff der offiziellen ThermoPro-App** (zuverlässigster Weg, wenn
1./2. nicht reichen) — auf Android, ohne Root:

1. Einstellungen → Über das Telefon → 7× auf „Build-Nummer“ tippen
   (aktiviert Entwickleroptionen), falls noch nicht aktiv.
2. Einstellungen → Entwickleroptionen → „Bluetooth-HCI-Snoop-Log“
   aktivieren.
3. Bluetooth kurz aus- und wieder einschalten (damit die Aufzeichnung
   sauber neu startet).
4. Offizielle ThermoPro-App öffnen, mit demselben Sensor verbinden und
   den Verlauf abrufen (genau die Aktion, deren Bytes wir sehen wollen).
5. Entwickleroptionen → „Bluetooth-HCI-Snoop-Log“ wieder ausschalten.
6. Die Log-Datei holen: entweder per USB-Debugging mit
   `adb bugreport` (enthält u. a. `FS/bt_stack.log_snoop` bzw.
   `btsnoop_hci.log`), oder falls im Hersteller-Dateisystem sichtbar
   direkt unter `/sdcard/btsnoop_hci.log` bzw. im internen Speicher unter
   „Android/data“ — je nach Android-Version leicht unterschiedlich.
7. Die Datei in **Wireshark** öffnen und nach
   `btatt.opcode == 0x52 || btatt.opcode == 0x12` filtern (Write
   Request/Command) auf dem Handle der Write-Characteristic
   (`00010203-0405-0607-0809-0a0b0c0d2b11`). Die dort sichtbaren
   „Value“-Bytes sind die gesuchten Kommandos — in der Reihenfolge, in der
   die App sie sendet, entsprechen sie a) Uhrzeit-Sync, b) Session-Init,
   c) Offset, d) Datenanfrage.
8. Die gefundenen Bytes in `app/protocol.py` eintragen
   (`TIME_SYNC_OPCODE`, `SESSION_INIT_COMMAND`, `OFFSET_COMMAND` — bei
   a) nur den festen Präfix vor den Datumsfeldern notieren, bei b)/c)
   die komplette feste Byte-Folge). Vorher unbedingt mit der Rohbefehl-
   Konsole am eigenen Gerät gegentesten, dass es funktioniert.

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
selbst weiter eingrenzen.

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
werden — siehe „Wie komme ich an die drei fehlenden Verlaufs-Kommandos?“
oben für die konkrete Vorgehensweise (erst per Rohbefehl-Konsole testen, ob
sie überhaupt nötig sind, sonst per BLE-Sniff der offiziellen App ermitteln).

Solange die drei Konstanten `None` sind, gibt das Dashboard beim Versuch,
die Historie abzurufen, eine klare Fehlermeldung aus statt stillschweigend
falsche Daten zu senden.

## Datenschutz / Speicherort

Alle Daten bleiben lokal auf dem PC in `data/tp357s.db` (SQLite). Es gibt
keine Cloud-Anbindung; der Webserver lauscht standardmäßig nur auf
`127.0.0.1` (nicht im Netzwerk erreichbar).
