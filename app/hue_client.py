"""Anbindung an die lokale Philips-Hue-Bridge-API (CLIP v2) - rein lokal im
Heimnetz, keine Cloud-Anbindung noetig.

Pairing: die Bridge verlangt aus Sicherheitsgruenden, dass vor dem ersten
Verbinden einer neuen Anwendung die runde Taste auf der Bridge gedrueckt
wird (30-Sekunden-Fenster danach). Das kann nicht automatisiert werden -
der Nutzer muss im Dashboard "Jetzt koppeln" klicken, NACHDEM er die Taste
gedrueckt hat.

TLS: die Bridge nutzt fuer ihre lokale HTTPS-API ein selbstsigniertes
Zertifikat (kein von einer oeffentlichen CA signiertes). Auf Nutzerwunsch
wird die Zertifikatspruefung bewusst deaktiviert (verify=False) - die
Verbindung bleibt trotzdem TLS-verschluesselt, nur die Zertifikatskette
wird nicht geprueft. Laeuft ausschliesslich im eigenen Heimnetz.

Zwei Betriebsarten:
- Einmaliger Pull: GET /clip/v2/resource liefert ALLE Ressourcen (Lichter,
  Sensoren, Raeume, Zonen, Szenen, Tasten, Geraete, ...) in einem Aufruf.
- Live: echter Server-Sent-Events-Push-Stream (/eventstream/clip/v2) statt
  Polling - die Bridge schickt Aenderungen in Echtzeit, sobald sie
  passieren."""
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

PAIR_DEVICETYPE = "tp357s_monitor#pc"
EVENT_BUFFER_SIZE = 1000
SSE_RECONNECT_DELAY_SECONDS = 5
HTTP_TIMEOUT_SECONDS = 10


class HueManager:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._lock = threading.Lock()

        self.bridge_ip: Optional[str] = None
        self.application_key: Optional[str] = None
        self.bridge_id: Optional[str] = None

        self.last_pull_at: Optional[str] = None
        self.last_pull_data: Optional[dict] = None
        self.last_pull_error: Optional[str] = None

        self.last_probe_error: Optional[str] = None
        self.last_pair_error: Optional[str] = None

        self.live_running = False
        self._live_thread: Optional[threading.Thread] = None
        self._live_generation = 0
        self.last_live_error: Optional[str] = None
        self.live_event_count = 0
        self._event_log: Deque[dict] = deque(maxlen=EVENT_BUFFER_SIZE)

        self._load()

    # -- Persistenz (hue_config.json im Projekt-Hauptordner - enthaelt den   --
    # -- application_key, daher wie firebase-service-account.json in        --
    # -- .gitignore eingetragen) ----------------------------------------------

    def _load(self) -> None:
        path = self.config_path
        if not path.exists():
            # Fallback auf den fruehreren (fehlerhaften) Speicherort
            # data/hue_config.json - wer die Datei schon dort abgelegt
            # hatte (nach einer aelteren Anleitung), soll sie nicht manuell
            # verschieben muessen.
            legacy_path = path.parent / "data" / path.name
            if legacy_path.exists():
                path = legacy_path
                logger.info("hue_config.json am alten Speicherort (%s) gefunden, lade von dort", legacy_path)
            else:
                return
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
            self.bridge_ip = raw.get("bridge_ip")
            self.application_key = raw.get("application_key")
            self.bridge_id = raw.get("bridge_id")
            if self.is_paired():
                logger.info("Hue-Kopplung geladen: bridge_ip=%s bridge_id=%s", self.bridge_ip, self.bridge_id)
        except Exception:  # noqa: BLE001
            logger.exception("Hue-Konfiguration (%s) konnte nicht geladen werden", path)

    def _save(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.config_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "bridge_ip": self.bridge_ip,
                    "application_key": self.application_key,
                    "bridge_id": self.bridge_id,
                }, f, indent=2)
            tmp.replace(self.config_path)
        except Exception:  # noqa: BLE001
            logger.exception("Hue-Konfiguration (%s) konnte nicht gespeichert werden", self.config_path)

    # -- Status ------------------------------------------------------------------

    def is_paired(self) -> bool:
        return bool(self.bridge_ip and self.application_key)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "paired": self.is_paired(),
                "bridge_ip": self.bridge_ip,
                "bridge_id": self.bridge_id,
                "last_pull_at": self.last_pull_at,
                "last_pull_error": self.last_pull_error,
                "last_pull_summary": self._summarize(self.last_pull_data) if self.last_pull_data else None,
                "live_running": self.live_running,
                "live_event_count": self.live_event_count,
                "last_live_error": self.last_live_error,
                "last_probe_error": self.last_probe_error,
                "last_pair_error": self.last_pair_error,
            }

    @staticmethod
    def _summarize(data: dict) -> dict:
        counts: Dict[str, int] = {}
        for item in (data or {}).get("data", []):
            t = item.get("type", "unbekannt")
            counts[t] = counts.get(t, 0) + 1
        return {"total": len((data or {}).get("data", [])), "by_type": counts}

    # -- Unauthentifizierter Bridge-Probe (v1-API, kein Pairing noetig) ---------

    def probe_bridge(self, ip: str) -> dict:
        """Fragt oeffentliche Bridge-Metadaten ab (Name, Bridge-ID,
        Software-Version, Modell, API-Version) - funktioniert OHNE
        application_key. Nuetzlich, um vor dem Koppeln zu pruefen, ob unter
        der eingegebenen IP ueberhaupt eine Hue-Bridge antwortet."""
        url = f"https://{ip}/api/config"
        self._append_event({"kind": "probe", "note": f"GET {url}"})
        try:
            resp = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS, verify=False)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            message = f"{type(exc).__name__}: {exc}"
            logger.exception("Hue-Bridge-Probe fehlgeschlagen (ip=%s)", ip)
            with self._lock:
                self.last_probe_error = message
            self._append_event({"kind": "probe-error", "note": message})
            raise
        with self._lock:
            self.last_probe_error = None
        self._append_event({"kind": "probe-ok", "note": json.dumps(data, ensure_ascii=False)})
        return data

    # -- Pairing -------------------------------------------------------------------

    def pair(self, ip: str) -> dict:
        """Ein Kopplungsversuch. Muss innerhalb von 30s NACH dem Druecken
        der runden Taste auf der Bridge aufgerufen werden, sonst liefert
        die Bridge Fehlercode 101 ('link button not pressed')."""
        url = f"https://{ip}/api"
        self._append_event({"kind": "pair-attempt", "note": f"POST {url} devicetype={PAIR_DEVICETYPE!r}"})
        try:
            # WICHTIG: der Request-Body ist ein einzelnes JSON-Objekt, KEIN
            # Array (nur die ANTWORT der Bridge ist ein Array) - mit einem
            # Array als Body liefert die Bridge "body contains invalid json"
            # zurueck, unabhaengig vom Tastendruck (per echtem Bridge-Test
            # reproduziert und verifiziert).
            resp = requests.post(
                url, json={"devicetype": PAIR_DEVICETYPE}, timeout=HTTP_TIMEOUT_SECONDS, verify=False
            )
            resp.raise_for_status()
            result = resp.json()
        except Exception as exc:  # noqa: BLE001
            message = f"{type(exc).__name__}: {exc}"
            logger.exception("Hue-Pairing-Anfrage fehlgeschlagen (ip=%s)", ip)
            with self._lock:
                self.last_pair_error = message
            self._append_event({"kind": "pair-error", "note": message})
            raise
        self._append_event({"kind": "pair-response", "note": json.dumps(result, ensure_ascii=False)})
        entry = result[0] if result else {}
        if "success" in entry:
            username = entry["success"]["username"]
            bridge_id = None
            try:
                bridge_id = self.probe_bridge(ip).get("bridgeid")
            except Exception:  # noqa: BLE001
                logger.exception("Bridge-Metadaten nach Pairing konnten nicht abgerufen werden")
            with self._lock:
                self.bridge_ip = ip
                self.application_key = username
                self.bridge_id = bridge_id
                self.last_pair_error = None
                self._save()
            logger.info("Hue-Bridge gekoppelt: ip=%s bridge_id=%s", ip, bridge_id)
            self._append_event({"kind": "pair-success", "note": f"application_key erhalten, bridge_id={bridge_id}"})
            return {"ok": True}
        if "error" in entry:
            message = entry["error"].get("description", "unbekannter Fehler")
            logger.warning("Hue-Pairing fehlgeschlagen: %s", message)
            with self._lock:
                self.last_pair_error = message
            self._append_event({"kind": "pair-error", "note": message})
            return {"ok": False, "error": message}
        with self._lock:
            self.last_pair_error = "Unerwartete Antwort der Bridge"
        self._append_event({"kind": "pair-error", "note": f"Unerwartete Antwort: {result}"})
        return {"ok": False, "error": "Unerwartete Antwort der Bridge"}

    def forget(self) -> None:
        self.stop_live()
        with self._lock:
            self.bridge_ip = None
            self.application_key = None
            self.bridge_id = None
            self.last_pull_data = None
            self.last_pull_at = None
            self.last_pull_error = None
            self.last_probe_error = None
            self.last_pair_error = None
            self._save()
        logger.info("Hue-Kopplung aufgehoben")
        self._append_event({"kind": "info", "note": "Kopplung aufgehoben"})

    # -- Einmaliger Pull (CLIP v2, alle Ressourcen in einem Aufruf) -------------

    def pull_now(self) -> dict:
        if not self.is_paired():
            raise RuntimeError("Nicht mit einer Hue-Bridge gekoppelt.")
        url = f"https://{self.bridge_ip}/clip/v2/resource"
        headers = {"hue-application-key": self.application_key}
        self._append_event({"kind": "pull-attempt", "note": f"GET {url}"})
        try:
            resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS, verify=False)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            message = f"{type(exc).__name__}: {exc}"
            logger.exception("Hue-Pull fehlgeschlagen (ip=%s)", self.bridge_ip)
            with self._lock:
                self.last_pull_error = message
            self._append_event({"kind": "pull-error", "note": message})
            raise
        with self._lock:
            self.last_pull_data = data
            self.last_pull_at = datetime.now(timezone.utc).isoformat()
            self.last_pull_error = None
        logger.info("Hue-Pull erfolgreich: %d Ressourcen", len(data.get("data", [])))
        self._append_event({"kind": "pull-ok", "note": f"{len(data.get('data', []))} Ressourcen"})
        return data

    def get_last_pull(self) -> Optional[dict]:
        with self._lock:
            return self.last_pull_data

    def get_fresh_pull(self, max_age_seconds: float = 15.0) -> dict:
        """Wie pull_now(), aber verzichtet auf einen neuen Bridge-Request,
        wenn der letzte Pull noch juenger als max_age_seconds ist - fuer
        Endpunkte (z.B. die Gebaeudeplan-Topologie), die bei jedem Laden der
        Seite frische Daten brauchen, aber nicht bei jedem 2s-Poll erneut
        die Bridge belasten sollen."""
        with self._lock:
            data = self.last_pull_data
            last_at = self.last_pull_at
        if data is not None and last_at is not None:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_at)).total_seconds()
            if age < max_age_seconds:
                return data
        return self.pull_now()

    # -- Lampen/Gruppen schreiben (PUT, CLIP v2) ----------------------------------

    def _put_resource(self, rtype: str, resource_id: str, body: dict) -> dict:
        if not self.is_paired():
            raise RuntimeError("Nicht mit einer Hue-Bridge gekoppelt.")
        url = f"https://{self.bridge_ip}/clip/v2/resource/{rtype}/{resource_id}"
        headers = {"hue-application-key": self.application_key}
        self._append_event({"kind": "put-attempt", "note": f"PUT {url} {json.dumps(body, ensure_ascii=False)}"})
        try:
            resp = requests.put(url, headers=headers, json=body, timeout=HTTP_TIMEOUT_SECONDS, verify=False)
            resp.raise_for_status()
            result = resp.json()
        except Exception as exc:  # noqa: BLE001
            message = f"{type(exc).__name__}: {exc}"
            logger.exception("Hue-PUT fehlgeschlagen (%s/%s)", rtype, resource_id)
            self._append_event({"kind": "put-error", "note": message})
            raise
        if result.get("errors"):
            message = "; ".join(e.get("description", str(e)) for e in result["errors"])
            logger.warning("Hue-PUT von der Bridge abgelehnt (%s/%s): %s", rtype, resource_id, message)
            self._append_event({"kind": "put-error", "note": message})
            raise RuntimeError(message)
        self._append_event({"kind": "put-ok", "note": f"{rtype}/{resource_id}: {json.dumps(body, ensure_ascii=False)}"})
        return result

    @staticmethod
    def _build_state_body(
        on: Optional[bool] = None,
        brightness: Optional[float] = None,
        xy: Optional[List[float]] = None,
        mirek: Optional[int] = None,
    ) -> dict:
        body: dict = {}
        if on is not None:
            body["on"] = {"on": bool(on)}
        if brightness is not None:
            body["dimming"] = {"brightness": max(0.0, min(100.0, float(brightness)))}
        if xy is not None:
            body["color"] = {"xy": {"x": float(xy[0]), "y": float(xy[1])}}
        if mirek is not None:
            body["color_temperature"] = {"mirek": int(mirek)}
        return body

    def set_light(
        self, light_id: str, *, on: Optional[bool] = None, brightness: Optional[float] = None,
        xy: Optional[List[float]] = None, mirek: Optional[int] = None,
    ) -> dict:
        """Setzt einzelne Lampen-Eigenschaften per PUT
        /clip/v2/resource/light/{id}. Nur uebergebene (nicht-None) Felder
        werden geaendert, alle anderen bleiben unberuehrt (Standardverhalten
        der Hue-API bei einem PUT mit Teil-Body)."""
        body = self._build_state_body(on=on, brightness=brightness, xy=xy, mirek=mirek)
        if not body:
            raise ValueError("Kein Feld zum Setzen angegeben.")
        return self._put_resource("light", light_id, body)

    def set_grouped_light(
        self, grouped_light_id: str, *, on: Optional[bool] = None, brightness: Optional[float] = None,
        xy: Optional[List[float]] = None, mirek: Optional[int] = None,
    ) -> dict:
        """Wie set_light(), aber fuer eine ganze Zone/einen ganzen Raum ueber
        dessen grouped_light-Ressource - wirkt auf alle Lampen der
        Gruppe gleichzeitig."""
        body = self._build_state_body(on=on, brightness=brightness, xy=xy, mirek=mirek)
        if not body:
            raise ValueError("Kein Feld zum Setzen angegeben.")
        return self._put_resource("grouped_light", grouped_light_id, body)

    # -- Topologie fuer den Gebaeudeplan (Lampen/Raeume/Zonen/Sensoren) -----------

    def resolve_topology(self) -> dict:
        """Baut aus dem rohen /clip/v2/resource-Pull eine fuer den
        Gebaeudeplan direkt nutzbare, verknuepfte Struktur: pro Lampe Name +
        Raum/Zone + Zustand + Faehigkeiten (dimmbar/farbig/Farbtemperatur),
        pro Raum/Zone die zugehoerige grouped_light-Ressource + Mitglieder,
        pro Bewegungs-/Helligkeits-/Temperatur-Sensor Name + aktueller Wert.

        Noetig, weil die rohe CLIP-v2-Antwort ein flaches Array typisierter
        Ressourcen ist, die nur ueber id-Referenzen verknuepft sind (ein
        'light' traegt selbst keinen Raumnamen, nur eine 'owner'-Referenz
        auf sein 'device'; welcher Raum/welche Zone dieses Device enthaelt,
        steht wiederum nur in den 'children' der room/zone-Ressourcen) -
        das im Frontend nachzubauen waere doppelte, fehleranfaellige Logik."""
        data = self.get_fresh_pull()
        by_id: Dict[str, dict] = {item["id"]: item for item in data.get("data", []) if "id" in item}

        def device_name(device_id: Optional[str]) -> str:
            device = by_id.get(device_id) if device_id else None
            if device and device.get("metadata", {}).get("name"):
                return device["metadata"]["name"]
            return "?"

        # Raum/Zone je Device-ID ermitteln (device -> room/zone, ueber deren children)
        device_to_group: Dict[str, dict] = {}
        for item in data.get("data", []):
            if item.get("type") not in ("room", "zone"):
                continue
            for child in item.get("children", []):
                if child.get("rtype") == "device":
                    device_to_group[child["rid"]] = item

        lights = []
        for item in data.get("data", []):
            if item.get("type") != "light":
                continue
            owner_id = item.get("owner", {}).get("rid")
            group = device_to_group.get(owner_id)
            name = item.get("metadata", {}).get("name") or device_name(owner_id)
            mirek_schema = (item.get("color_temperature") or {}).get("mirek_schema") or {}
            lights.append({
                "id": item["id"],
                "name": name,
                "owner_device_id": owner_id,
                "room_id": group["id"] if group and group.get("type") == "room" else None,
                "zone_id": group["id"] if group and group.get("type") == "zone" else None,
                "group_name": group.get("metadata", {}).get("name") if group else None,
                "on": (item.get("on") or {}).get("on"),
                "brightness": (item.get("dimming") or {}).get("brightness"),
                "xy": (item.get("color") or {}).get("xy"),
                "mirek": (item.get("color_temperature") or {}).get("mirek"),
                "capabilities": {
                    "dimmable": "dimming" in item,
                    "color": "color" in item,
                    "color_temperature": "color_temperature" in item,
                },
                "mirek_min": mirek_schema.get("mirek_minimum"),
                "mirek_max": mirek_schema.get("mirek_maximum"),
            })

        groups = []
        for item in data.get("data", []):
            if item.get("type") not in ("room", "zone"):
                continue
            grouped_light_id = None
            for svc in item.get("services", []):
                if svc.get("rtype") == "grouped_light":
                    grouped_light_id = svc["rid"]
                    break
            grouped_light = by_id.get(grouped_light_id) if grouped_light_id else None
            member_light_ids = [
                l["id"] for l in lights
                if (l["room_id"] == item["id"]) or (l["zone_id"] == item["id"])
            ]
            groups.append({
                "id": item["id"],
                "type": item["type"],
                "name": item.get("metadata", {}).get("name") or "?",
                "grouped_light_id": grouped_light_id,
                "on": (grouped_light or {}).get("on", {}).get("on"),
                "brightness": (grouped_light or {}).get("dimming", {}).get("brightness"),
                "light_ids": member_light_ids,
            })

        sensors = []
        for item in data.get("data", []):
            if item.get("type") not in ("motion", "light_level", "temperature"):
                continue
            owner_id = item.get("owner", {}).get("rid")
            group = device_to_group.get(owner_id)
            entry = {
                "id": item["id"],
                "type": item["type"],
                "name": device_name(owner_id),
                "owner_device_id": owner_id,
                "room_id": group["id"] if group and group.get("type") == "room" else None,
                "zone_id": group["id"] if group and group.get("type") == "zone" else None,
                "enabled": item.get("enabled"),
            }
            if item["type"] == "motion":
                entry["motion"] = (item.get("motion") or {}).get("motion")
                entry["motion_valid"] = (item.get("motion") or {}).get("motion_valid")
            elif item["type"] == "light_level":
                entry["light_level"] = (item.get("light") or {}).get("light_level")
            elif item["type"] == "temperature":
                entry["temperature"] = (item.get("temperature") or {}).get("temperature")
            sensors.append(entry)

        return {"lights": lights, "groups": groups, "sensors": sensors, "pulled_at": self.last_pull_at}

    # -- Live (Server-Sent Events, /eventstream/clip/v2) --------------------------

    def start_live(self) -> None:
        """Startet den Live-Stream in einem neuen Thread mit einer neuen
        "Generation"-Nummer statt eines wiederverwendeten threading.Event
        (siehe _is_current_generation fuer die Begruendung - ein frueherer
        Bug fuehrte zu zwei parallel laufenden Verbindungen und dadurch
        jedem Live-Ereignis doppelt im Log)."""
        if not self.is_paired():
            raise RuntimeError("Nicht mit einer Hue-Bridge gekoppelt.")
        with self._lock:
            if self.live_running:
                return
            self.live_running = True
            self.last_live_error = None
            self._live_generation += 1
            generation = self._live_generation
        self._live_thread = threading.Thread(target=self._live_loop, args=(generation,), name="hue-live", daemon=True)
        self._live_thread.start()
        logger.info("Hue-Live-Stream gestartet (generation=%d)", generation)

    def stop_live(self) -> None:
        """Setzt live_running=False UND erhoeht die Generation-Nummer.

        Ein aktuell blockierender Netzwerk-Read (resp.iter_lines()) laesst
        sich nicht sofort von aussen abbrechen - der alte Thread merkt den
        Stop-Wunsch erst beim naechsten empfangenen Byte/Timeout. Die
        Generation-Pruefung sorgt dafuer, dass er ab dann garantiert NICHTS
        mehr tut (keine weiteren Events anhaengen, keinen Reconnect
        versuchen), selbst wenn zwischenzeitlich ein neuer start_live()-
        Aufruf eine neue Generation gestartet hat. Frueher wurde dafuer ein
        einzelnes, wiederverwendetes threading.Event genutzt - dessen
        naechstes clear() (beim naechsten Start) hat einen noch nicht
        beendeten alten Thread versehentlich "reaktiviert", weil er
        dieselbe Event-Instanz beobachtet hat wie der neue Thread."""
        with self._lock:
            self.live_running = False
            self._live_generation += 1
        logger.info("Hue-Live-Stream gestoppt")

    def _is_current_generation(self, generation: int) -> bool:
        with self._lock:
            return self.live_running and self._live_generation == generation

    def _live_loop(self, generation: int) -> None:
        url = f"https://{self.bridge_ip}/eventstream/clip/v2"
        headers = {"hue-application-key": self.application_key, "Accept": "text/event-stream"}
        while self._is_current_generation(generation):
            try:
                # Endlicher Read-Timeout (statt None): sorgt dafuer, dass
                # die Schleife auch bei laengerer Funkstille der Bridge
                # regelmaessig aufwacht und die Generation neu prueft,
                # statt fuer immer in iter_lines() zu haengen.
                with requests.get(
                    url, headers=headers, stream=True, timeout=(HTTP_TIMEOUT_SECONDS, 90), verify=False
                ) as resp:
                    resp.raise_for_status()
                    logger.info("Hue-Eventstream verbunden (generation=%d)", generation)
                    self._append_event({"kind": "info", "note": f"Eventstream verbunden (Generation {generation})"})
                    data_lines: List[str] = []
                    for raw_line in resp.iter_lines(decode_unicode=True):
                        if not self._is_current_generation(generation):
                            break
                        if raw_line is None:
                            continue
                        line = raw_line.strip("\n")
                        if line.startswith(":"):
                            continue  # Kommentar/Heartbeat der Bridge, kein Ereignis
                        if line == "":
                            if data_lines:
                                self._handle_sse_payload("\n".join(data_lines))
                                data_lines = []
                            continue
                        if line.startswith("data:"):
                            data_lines.append(line[len("data:"):].strip())
            except Exception as exc:  # noqa: BLE001
                if not self._is_current_generation(generation):
                    break
                logger.warning("Hue-Eventstream-Verbindung verloren/fehlgeschlagen: %s", exc)
                with self._lock:
                    self.last_live_error = f"{type(exc).__name__}: {exc}"
                self._append_event({"kind": "error", "note": f"{type(exc).__name__}: {exc}"})
            if self._is_current_generation(generation):
                time.sleep(SSE_RECONNECT_DELAY_SECONDS)
        logger.info("Hue-Eventstream-Schleife beendet (generation=%d)", generation)

    def _handle_sse_payload(self, payload: str) -> None:
        try:
            events = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("Hue-Eventstream: Payload konnte nicht als JSON geparst werden: %s", payload[:200])
            return
        for event in events if isinstance(events, list) else [events]:
            self._append_event({"kind": "live-event", "event": event})

    def _append_event(self, entry: dict) -> None:
        entry = dict(entry)
        entry.setdefault("ts", datetime.now(timezone.utc).isoformat())
        with self._lock:
            self._event_log.append(entry)
            self.live_event_count += 1

    def get_events(self, limit: int = 200) -> List[dict]:
        with self._lock:
            items = list(self._event_log)
        return items[-limit:]
