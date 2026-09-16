// Dev-Dashboard: bewusst keine "schoene" UI, sondern maximale Informationsdichte.

const configDumpEl = document.getElementById("config-dump");
const debugDumpEl = document.getElementById("debug-dump");
const logViewEl = document.getElementById("log-view");
const logLinesInput = document.getElementById("log-lines");
const logAutoscrollInput = document.getElementById("log-autoscroll");

const scanBtn = document.getElementById("scan-btn");
const scanDurationInput = document.getElementById("scan-duration");
const scanStatusEl = document.getElementById("scan-status");
const scanBody = document.getElementById("scan-body");
const manualMacInput = document.getElementById("manual-mac");
const manualNameInput = document.getElementById("manual-name");
const manualAddBtn = document.getElementById("manual-add-btn");
const manualProbeBtn = document.getElementById("manual-probe-btn");

const deviceBody = document.getElementById("device-body");
const deviceLogsEl = document.getElementById("device-logs");

const historyDeviceSelect = document.getElementById("history-device");
const historyCountInput = document.getElementById("history-count");
const fetchHistoryBtn = document.getElementById("fetch-history-btn");
const exportLink = document.getElementById("export-link");
const historyInfoEl = document.getElementById("history-info");

const graphResolutionSelect = document.getElementById("graph-resolution");
const graphLimitInput = document.getElementById("graph-limit");
const graphInfoEl = document.getElementById("graph-info");
const graphTempSvg = document.getElementById("graph-temp");
const graphHumSvg = document.getElementById("graph-hum");
const graphZoomResetBtn = document.getElementById("graph-zoom-reset-btn");

const firebaseUploadNowBtn = document.getElementById("firebase-upload-now-btn");
const firebaseStatusEl = document.getElementById("firebase-status");
const firebaseDetailEl = document.getElementById("firebase-detail");

const hueIpInput = document.getElementById("hue-ip");
const hueProbeBtn = document.getElementById("hue-probe-btn");
const hueProbeStatusEl = document.getElementById("hue-probe-status");
const huePairBtn = document.getElementById("hue-pair-btn");
const hueForgetBtn = document.getElementById("hue-forget-btn");
const huePairStatusEl = document.getElementById("hue-pair-status");
const hueStatusDumpEl = document.getElementById("hue-status-dump");
const huePullBtn = document.getElementById("hue-pull-btn");
const huePullStatusEl = document.getElementById("hue-pull-status");
const huePullDumpEl = document.getElementById("hue-pull-dump");
const hueLiveStartBtn = document.getElementById("hue-live-start-btn");
const hueLiveStopBtn = document.getElementById("hue-live-stop-btn");
const hueLiveStatusEl = document.getElementById("hue-live-status");
const hueLiveLogEl = document.getElementById("hue-live-log");

let pairedMacs = new Set();
let selectedHistoryMac = null;
const trackedDeviceLogs = new Map(); // mac -> { el, intervalId }

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    // kein JSON, z.B. bei /api/logs (text/plain) - Aufrufer kuemmert sich selbst
  }
  if (!res.ok) {
    const message = (data && data.error) || `HTTP ${res.status}`;
    throw new Error(message);
  }
  return data;
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s == null ? "" : String(s);
  return div.innerHTML;
}

function toLocalTime(isoUtc) {
  if (!isoUtc) return "-";
  const withZone = isoUtc.endsWith("Z") || isoUtc.includes("+") ? isoUtc : isoUtc + "Z";
  return new Date(withZone).toLocaleString();
}

// -- Tabs + einklappbare Panels (Zustand serverseitig persistiert) -----------
// Server statt localStorage, weil die Anforderung war "fuer den naechsten
// Start des SERVERS gespeichert", nicht nur im selben Browser.

const uiState = { collapsed: {}, active_tab: "sensors" };
let uiStateSaveTimer = null;

function saveUiState() {
  clearTimeout(uiStateSaveTimer);
  uiStateSaveTimer = setTimeout(() => {
    fetchJSON("/api/ui-state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(uiState),
    }).catch(() => {});
  }, 150);
}

function applyPanelCollapsed(panel, collapsed) {
  panel.classList.toggle("collapsed", collapsed);
  const toggle = panel.querySelector(".panel-toggle");
  if (toggle) toggle.textContent = collapsed ? "▸" : "▾";
}

function initPanels() {
  document.querySelectorAll(".panel").forEach((panel) => {
    const id = panel.dataset.panelId;
    const header = panel.querySelector(".panel-header");
    header.addEventListener("click", () => {
      const collapsed = !panel.classList.contains("collapsed");
      applyPanelCollapsed(panel, collapsed);
      uiState.collapsed[id] = collapsed;
      saveUiState();
    });
  });
}

function setActiveTab(tab, save) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab-content").forEach((c) => c.classList.toggle("active", c.dataset.tab === tab));
  uiState.active_tab = tab;
  if (save) saveUiState();
}

function initTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => setActiveTab(btn.dataset.tab, true));
  });
}

async function loadUiState() {
  try {
    const s = await fetchJSON("/api/ui-state");
    uiState.collapsed = s.collapsed || {};
    uiState.active_tab = s.active_tab || "sensors";
  } catch (e) {
    // Server evtl. noch nicht bereit - mit Defaults weitermachen
  }
  document.querySelectorAll(".panel").forEach((panel) => {
    applyPanelCollapsed(panel, !!uiState.collapsed[panel.dataset.panelId]);
  });
  setActiveTab(uiState.active_tab, false);
}

initPanels();
initTabs();
loadUiState();

// -- Server: Config / Debug / Log --------------------------------------------

async function refreshConfig() {
  try {
    const data = await fetchJSON("/api/config");
    configDumpEl.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    configDumpEl.textContent = "Fehler: " + e.message;
  }
}

async function refreshDebug() {
  try {
    const data = await fetchJSON("/api/debug");
    debugDumpEl.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    debugDumpEl.textContent = "Fehler: " + e.message;
  }
}

async function refreshLog() {
  try {
    const lines = parseInt(logLinesInput.value, 10) || 300;
    const res = await fetch(`/api/logs?lines=${lines}`);
    const text = await res.text();
    logViewEl.textContent = text;
    if (logAutoscrollInput.checked) {
      logViewEl.scrollTop = logViewEl.scrollHeight;
    }
  } catch (e) {
    logViewEl.textContent = "Fehler beim Laden des Logs: " + e.message;
  }
}

// -- Scan ---------------------------------------------------------------------

scanBtn.addEventListener("click", async () => {
  const duration = parseInt(scanDurationInput.value, 10) || 15;
  scanBtn.disabled = true;
  try {
    await fetchJSON(`/api/scan?duration=${duration}`, { method: "POST" });
  } catch (e) {
    alert("Scan konnte nicht gestartet werden: " + e.message);
    scanBtn.disabled = false;
  }
});

manualAddBtn.addEventListener("click", () => {
  const mac = manualMacInput.value.trim();
  if (!mac) {
    alert("Bitte MAC-Adresse eintragen.");
    return;
  }
  addDevice(mac, manualNameInput.value.trim() || mac);
});

manualProbeBtn.addEventListener("click", () => {
  const mac = manualMacInput.value.trim();
  if (!mac) {
    alert("Bitte MAC-Adresse eintragen.");
    return;
  }
  startProbe(mac, manualNameInput.value.trim() || mac);
});

function fmtObj(obj) {
  if (obj == null) return "";
  const keys = Object.keys(obj);
  if (!keys.length) return "{}";
  return keys.map((k) => `${k}=${obj[k]}`).join(", ");
}

function renderScanResults(results, scanning, scanError) {
  scanStatusEl.textContent = scanning
    ? "scanne…"
    : scanError
    ? "Fehler: " + scanError
    : `${results.length} Treffer`;
  scanBtn.disabled = scanning;

  scanBody.innerHTML = "";
  results.forEach((r) => {
    const tr = document.createElement("tr");
    const already = pairedMacs.has(r.mac.toUpperCase());
    tr.innerHTML = `
      <td>${escapeHtml(r.name)}${r.local_name && r.local_name !== r.name ? " (" + escapeHtml(r.local_name) + ")" : ""}</td>
      <td class="mono">${r.mac}</td>
      <td>${r.rssi != null ? r.rssi : "-"}</td>
      <td>${r.tx_power != null ? r.tx_power : "-"}</td>
      <td class="mono small">${escapeHtml((r.service_uuids || []).join(", "))}</td>
      <td class="mono small">${escapeHtml(fmtObj(r.manufacturer_data))}</td>
      <td class="mono small">${escapeHtml(fmtObj(r.service_data))}</td>
      <td class="mono small">${escapeHtml(r.device_details)} / ${escapeHtml(r.adv_platform_data)}</td>
      <td class="actions"></td>
    `;
    const actions = tr.querySelector(".actions");
    if (already) {
      const span = document.createElement("span");
      span.textContent = "gekoppelt";
      actions.appendChild(span);
    } else {
      const addBtn = document.createElement("button");
      addBtn.textContent = "Hinzufügen";
      addBtn.addEventListener("click", () => addDevice(r.mac, r.name));
      const probeBtn = document.createElement("button");
      probeBtn.textContent = "Live-Test";
      probeBtn.addEventListener("click", () => startProbe(r.mac, r.name));
      actions.appendChild(addBtn);
      actions.appendChild(probeBtn);
    }
    scanBody.appendChild(tr);
  });
}

async function addDevice(mac, suggestedName) {
  const name = prompt("Name für diesen Sensor:", suggestedName || mac) || suggestedName || mac;
  try {
    await fetchJSON("/api/devices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mac, name }),
    });
    refreshAll();
  } catch (e) {
    alert("Sensor konnte nicht hinzugefügt werden: " + e.message);
  }
}

async function startProbe(mac, suggestedName) {
  try {
    await fetchJSON("/api/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mac, name: suggestedName || mac }),
    });
    refreshAll();
  } catch (e) {
    alert("Live-Test konnte nicht gestartet werden: " + e.message);
  }
}

async function stopProbe(mac) {
  try {
    await fetchJSON(`/api/probe/${encodeURIComponent(mac)}/stop`, { method: "POST" });
    refreshAll();
  } catch (e) {
    alert("Live-Test konnte nicht gestoppt werden: " + e.message);
  }
}

async function promoteProbe(mac, currentName) {
  const name = prompt("Name für diesen Sensor (wird dauerhaft gespeichert):", currentName) || currentName;
  try {
    await fetchJSON(`/api/probe/${encodeURIComponent(mac)}/promote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    refreshAll();
  } catch (e) {
    alert("Übernehmen fehlgeschlagen: " + e.message);
  }
}

// -- Geraete ------------------------------------------------------------------

function renderDevices(devices) {
  pairedMacs = new Set(devices.filter((d) => !d.is_probe).map((d) => d.mac.toUpperCase()));

  deviceBody.innerHTML = "";
  devices.forEach((d) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(d.name)}</td>
      <td class="mono">${d.mac}</td>
      <td>${d.is_probe ? "Live-Test" : "gekoppelt"}</td>
      <td>${escapeHtml(d.status)}</td>
      <td class="small">${toLocalTime(d.last_status_change)}</td>
      <td class="mono">${
        d.last_live
          ? `${d.last_live.temperature_c.toFixed(1)}°C ${d.last_live.humidity_pct}% @ ${toLocalTime(d.last_live_ts)}`
          : "-"
      }</td>
      <td class="error">${d.last_error ? escapeHtml(d.last_error) : ""}</td>
      <td>${d.packet_count}</td>
      <td class="actions"></td>
    `;
    const actions = tr.querySelector(".actions");
    if (d.is_probe) {
      const promoteBtn = document.createElement("button");
      promoteBtn.textContent = "Übernehmen";
      promoteBtn.addEventListener("click", () => promoteProbe(d.mac, d.name));
      const stopBtn = document.createElement("button");
      stopBtn.textContent = "Stoppen";
      stopBtn.addEventListener("click", () => stopProbe(d.mac));
      actions.appendChild(promoteBtn);
      actions.appendChild(stopBtn);
    } else {
      const renameBtn = document.createElement("button");
      renameBtn.textContent = "Umbenennen";
      renameBtn.addEventListener("click", () => renameDevice(d.mac, d.name));
      const removeBtn = document.createElement("button");
      removeBtn.textContent = "Entfernen";
      removeBtn.addEventListener("click", () => removeDevice(d.mac, d.name));
      actions.appendChild(renameBtn);
      actions.appendChild(removeBtn);
    }
    deviceBody.appendChild(tr);
  });

  updateDeviceLogPanels(devices);
  updateHistoryDeviceOptions(devices);
}

async function renameDevice(mac, currentName) {
  const name = prompt("Neuer Name:", currentName);
  if (!name || name === currentName) return;
  try {
    await fetchJSON(`/api/devices/${encodeURIComponent(mac)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    refreshAll();
  } catch (e) {
    alert("Umbenennen fehlgeschlagen: " + e.message);
  }
}

async function removeDevice(mac, name) {
  if (!confirm(`Sensor "${name}" wirklich entfernen? (Gespeicherte Messwerte bleiben erhalten)`)) return;
  try {
    await fetchJSON(`/api/devices/${encodeURIComponent(mac)}`, { method: "DELETE" });
    refreshAll();
  } catch (e) {
    alert("Entfernen fehlgeschlagen: " + e.message);
  }
}

// -- Live-Rohdaten-Feed pro Geraet (gefunden ODER gekoppelt) -----------------

function updateDeviceLogPanels(devices) {
  const currentMacs = new Set(devices.map((d) => d.mac));

  for (const [mac, entry] of trackedDeviceLogs) {
    if (!currentMacs.has(mac)) {
      clearInterval(entry.intervalId);
      entry.container.remove();
      trackedDeviceLogs.delete(mac);
    }
  }

  devices.forEach((d) => {
    let entry = trackedDeviceLogs.get(d.mac);
    if (!entry) {
      const container = document.createElement("div");
      container.className = "device-log-panel";
      const header = document.createElement("h4");
      container.appendChild(header);

      let autoSyncRow = null;
      let autoSyncEnabledInput = null;
      let autoSyncIntervalInput = null;
      let autoSyncStatusEl = null;
      if (!d.is_probe) {
        autoSyncRow = document.createElement("div");
        autoSyncRow.className = "row";
        const label = document.createElement("label");
        autoSyncEnabledInput = document.createElement("input");
        autoSyncEnabledInput.type = "checkbox";
        label.appendChild(autoSyncEnabledInput);
        label.appendChild(document.createTextNode(" Auto-Sync alle"));
        autoSyncIntervalInput = document.createElement("input");
        autoSyncIntervalInput.type = "number";
        autoSyncIntervalInput.min = "1";
        autoSyncIntervalInput.size = "4";
        autoSyncIntervalInput.value = "10";
        const applyBtn = document.createElement("button");
        applyBtn.textContent = "Übernehmen";
        applyBtn.addEventListener("click", () => applyAutoSync(d.mac, autoSyncEnabledInput, autoSyncIntervalInput));
        autoSyncStatusEl = document.createElement("span");
        autoSyncStatusEl.className = "small";
        autoSyncRow.appendChild(label);
        autoSyncRow.appendChild(autoSyncIntervalInput);
        autoSyncRow.appendChild(document.createTextNode(" Min."));
        autoSyncRow.appendChild(applyBtn);
        autoSyncRow.appendChild(autoSyncStatusEl);
        container.appendChild(autoSyncRow);
      }

      const writeRow = document.createElement("div");
      writeRow.className = "row";
      const hexInput = document.createElement("input");
      hexInput.type = "text";
      hexInput.placeholder = "Hex-Bytes, z.B. 0109190915...";
      hexInput.size = 40;
      const sendBtn = document.createElement("button");
      sendBtn.textContent = "Rohbefehl senden";
      sendBtn.addEventListener("click", () => sendRawWrite(d.mac, hexInput));
      const csBtn = document.createElement("button");
      csBtn.textContent = "+ Checksumme anhängen";
      csBtn.title = "Haengt sum(bytes) & 0xFF als letztes Byte an (siehe Verlaufs-Kommando-Checksumme)";
      csBtn.addEventListener("click", () => appendChecksum(hexInput));
      const exampleBtn = document.createElement("button");
      exampleBtn.textContent = "Beispiel einfügen (Datenanfrage)";
      exampleBtn.title = "Fügt das Datenanfrage-Kommando ein, fertig kodiert für jetzt";
      exampleBtn.addEventListener("click", () => insertExample(hexInput));
      writeRow.appendChild(hexInput);
      writeRow.appendChild(sendBtn);
      writeRow.appendChild(csBtn);
      writeRow.appendChild(exampleBtn);
      container.appendChild(writeRow);

      const candidateRow = document.createElement("div");
      candidateRow.className = "row";
      const prefixInput = document.createElement("input");
      prefixInput.type = "text";
      prefixInput.placeholder = "Praefix, z.B. 0101";
      prefixInput.size = 12;
      const candidateBtn = document.createElement("button");
      candidateBtn.textContent = "Zeit-Kandidat bauen →";
      candidateBtn.title =
        "Baut Praefix + aktuelles Datum + Checksumme (gleiches Schema wie die bekannte Datenanfrage) " +
        "und traegt es oben ins Sendefeld ein";
      candidateBtn.addEventListener("click", () => buildTimeCandidate(prefixInput, hexInput));
      candidateRow.appendChild(prefixInput);
      candidateRow.appendChild(candidateBtn);
      container.appendChild(candidateRow);

      const hint = document.createElement("p");
      hint.className = "small";
      hint.textContent =
        "Zum Debuggen: beliebige Hex-Bytes senden und die Antwort direkt im Feed unten beobachten. " +
        "\"Beispiel einfügen\" liefert das fertig kodierte Datenanfrage-Kommando. " +
        "\"Zeit-Kandidat bauen\" baut Praefix + aktuelles Datum + Checksumme fuer eigene Experimente " +
        "mit anderen Kommando-Formen.";
      container.appendChild(hint);

      const pre = document.createElement("pre");
      pre.className = "log-box small";
      container.appendChild(pre);
      deviceLogsEl.appendChild(container);

      const intervalId = setInterval(() => fetchDeviceLog(d.mac, pre), 2000);
      entry = {
        container,
        header,
        pre,
        intervalId,
        autoSyncEnabledInput,
        autoSyncIntervalInput,
        autoSyncStatusEl,
        autoSyncInitialized: false,
      };
      trackedDeviceLogs.set(d.mac, entry);
      fetchDeviceLog(d.mac, pre);
    }
    entry.header.textContent = `${d.name} (${d.mac}) — ${d.status}${d.is_probe ? " [Live-Test]" : ""} — ${d.packet_count} Pakete`;

    if (entry.autoSyncEnabledInput && entry.autoSyncIntervalInput) {
      const focused = document.activeElement;
      if (!entry.autoSyncInitialized || (focused !== entry.autoSyncEnabledInput && focused !== entry.autoSyncIntervalInput)) {
        entry.autoSyncEnabledInput.checked = !!d.auto_sync_enabled;
        entry.autoSyncIntervalInput.value = Math.round((d.auto_sync_interval_seconds || 600) / 60);
        entry.autoSyncInitialized = true;
      }
    }
    if (entry.autoSyncStatusEl) {
      entry.autoSyncStatusEl.textContent = formatAutoSyncStatus(d);
    }
  });
}

function formatAutoSyncStatus(d) {
  const parts = [];
  parts.push(d.last_synced_ts ? `synced bis ${toLocalTime(d.last_synced_ts)}` : "noch nie synchronisiert");
  if (d.last_auto_sync_result) {
    const r = d.last_auto_sync_result;
    parts.push(
      r.ok
        ? `letzter Abruf: ${r.count}/${r.requested} Datensätze (${r.clean ? "sauber" : "ABGEBROCHEN"})`
        : `letzter Abruf fehlgeschlagen: ${r.error}`
    );
  }
  if (d.last_sync_check) {
    const c = d.last_sync_check;
    parts.push(c.ok ? `Sync-Check OK (dT=${c.temp_diff} dH=${c.humidity_diff})` : `Sync-Check ABWEICHUNG (dT=${c.temp_diff} dH=${c.humidity_diff})`);
  }
  return parts.join(" · ");
}

async function applyAutoSync(mac, enabledInput, intervalInput) {
  const enabled = enabledInput.checked;
  const interval_minutes = parseFloat(intervalInput.value) || 10;
  try {
    await fetchJSON(`/api/devices/${encodeURIComponent(mac)}/auto-sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled, interval_minutes }),
    });
  } catch (e) {
    alert("Auto-Sync konnte nicht gesetzt werden: " + e.message);
  }
}

async function fetchDeviceLog(mac, pre) {
  try {
    const entries = await fetchJSON(`/api/devices/${encodeURIComponent(mac)}/log?limit=200`);
    const lines = entries.map((e) => {
      const parts = [toLocalTime(e.ts), `[${e.kind}]`];
      if (e.hex) parts.push(`hex=${e.hex}`);
      if (e.len != null) parts.push(`len=${e.len}`);
      if (e.decoded) parts.push(`decoded=${JSON.stringify(e.decoded)}`);
      if (e.note) parts.push(e.note);
      return parts.join(" ");
    });
    pre.textContent = lines.join("\n") || "(noch keine Pakete)";
    pre.scrollTop = pre.scrollHeight;
  } catch (e) {
    pre.textContent = "Fehler beim Laden: " + e.message;
  }
}

async function sendRawWrite(mac, hexInput) {
  const hex = hexInput.value.trim();
  if (!hex) {
    alert("Bitte Hex-Bytes eintragen (z.B. 0109190915...).");
    return;
  }
  try {
    await fetchJSON(`/api/devices/${encodeURIComponent(mac)}/write`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hex }),
    });
  } catch (e) {
    alert("Senden fehlgeschlagen: " + e.message);
  }
}

async function appendChecksum(hexInput) {
  const hex = hexInput.value.trim();
  if (!hex) return;
  try {
    const res = await fetchJSON(`/api/checksum?hex=${encodeURIComponent(hex)}`);
    hexInput.value = res.with_checksum_hex;
  } catch (e) {
    alert("Checksumme konnte nicht berechnet werden: " + e.message);
  }
}

async function insertExample(hexInput) {
  try {
    const res = await fetchJSON("/api/protocol/examples?count=500");
    hexInput.value = res.data_request_hex;
  } catch (e) {
    alert("Beispiel konnte nicht geladen werden: " + e.message);
  }
}

async function buildTimeCandidate(prefixInput, hexInput) {
  const prefix = prefixInput.value.trim();
  if (!prefix) {
    alert("Bitte Praefix eintragen (z.B. 0101).");
    return;
  }
  try {
    const res = await fetchJSON(`/api/protocol/time-shaped-candidate?prefix=${encodeURIComponent(prefix)}`);
    hexInput.value = res.hex;
  } catch (e) {
    alert("Kandidat konnte nicht gebaut werden: " + e.message);
  }
}

// -- Verlauf --------------------------------------------------------------------

function updateHistoryDeviceOptions(devices) {
  const previous = historyDeviceSelect.value;
  historyDeviceSelect.innerHTML = "";
  devices.forEach((d) => {
    const opt = document.createElement("option");
    opt.value = d.mac;
    opt.textContent = `${d.name} (${d.mac})`;
    historyDeviceSelect.appendChild(opt);
  });

  if (!devices.length) {
    selectedHistoryMac = null;
    historyInfoEl.textContent = "";
    exportLink.href = "/api/export.csv";
    return;
  }

  const stillExists = devices.some((d) => d.mac === previous);
  historyDeviceSelect.value = stillExists ? previous : devices[0].mac;
  const changed = historyDeviceSelect.value !== selectedHistoryMac;
  selectedHistoryMac = historyDeviceSelect.value;
  exportLink.href = `/api/export.csv?mac=${encodeURIComponent(selectedHistoryMac)}`;
  if (changed) {
    zoomRange = null;
    refreshGraph();
  }
}

historyDeviceSelect.addEventListener("change", () => {
  selectedHistoryMac = historyDeviceSelect.value;
  exportLink.href = `/api/export.csv?mac=${encodeURIComponent(selectedHistoryMac)}`;
  zoomRange = null;
  refreshGraph();
});

fetchHistoryBtn.addEventListener("click", async () => {
  if (!selectedHistoryMac) return;
  const count = parseInt(historyCountInput.value, 10) || 500;
  fetchHistoryBtn.disabled = true;
  try {
    await fetchJSON(`/api/devices/${encodeURIComponent(selectedHistoryMac)}/fetch-history?count=${count}`, {
      method: "POST",
    });
  } catch (e) {
    alert("Fehler beim Anfordern des Verlaufs: " + e.message);
  } finally {
    setTimeout(() => (fetchHistoryBtn.disabled = false), 2000);
  }
});

// -- Graph (SVG, Temperatur + Luftfeuchte, einstellbare Aufloesung) -----------

const CHART_WIDTH = 900;
const CHART_HEIGHT = 260;
const CHART_PAD = { left: 48, right: 14, top: 16, bottom: 28 };
const SVGNS = "http://www.w3.org/2000/svg";

let lastGraphPoints = [];
let lastResolutionSeconds = 0;
let zoomRange = null; // {startMs, endMs} oder null = volle Aufloesung
let gradientIdCounter = 0;

function pointTimeMs(p) {
  const iso = p.ts.endsWith("Z") || p.ts.includes("+") ? p.ts : p.ts + "Z";
  return new Date(iso).getTime();
}

function pointsInZoom(points) {
  if (!zoomRange) return points;
  return points.filter((p) => {
    const t = pointTimeMs(p);
    return t >= zoomRange.startMs && t <= zoomRange.endMs;
  });
}

function applyZoom(startMs, endMs) {
  if (endMs - startMs < 1000) return; // zu kleiner Bereich, ignorieren (z.B. reiner Klick)
  zoomRange = { startMs, endMs };
  rerenderCharts();
  updateGraphInfoText();
}

function resetZoom() {
  zoomRange = null;
  rerenderCharts();
  updateGraphInfoText();
}

function rerenderCharts() {
  const pts = pointsInZoom(lastGraphPoints);
  renderChart(graphTempSvg, pts, "temperature_c", "#2563eb");
  renderChart(graphHumSvg, pts, "humidity_pct", "#059669");
  graphZoomResetBtn.disabled = !zoomRange;
}

function updateGraphInfoText() {
  const total = lastGraphPoints.length;
  const shown = pointsInZoom(lastGraphPoints).length;
  const resolutionNote = lastResolutionSeconds ? ` (${lastResolutionSeconds}s-Buckets, gemittelt)` : " (Rohdaten)";
  graphInfoEl.textContent = `${total} Punkte${resolutionNote}` + (zoomRange ? `, ${shown} im Zoom-Bereich sichtbar` : "");
}

graphZoomResetBtn.addEventListener("click", resetZoom);

function formatChartTime(isoUtc, spanSeconds) {
  const withZone = isoUtc.endsWith("Z") || isoUtc.includes("+") ? isoUtc : isoUtc + "Z";
  const d = new Date(withZone);
  if (spanSeconds > 3 * 86400) {
    return d.toLocaleDateString();
  }
  return d.toLocaleString([], { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function svgEl(name, attrs) {
  const el = document.createElementNS(SVGNS, name);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  return el;
}

function renderChart(svg, points, valueKey, color) {
  const w = CHART_WIDTH, h = CHART_HEIGHT;
  const { left, right, top, bottom } = CHART_PAD;
  svg.innerHTML = "";
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);

  if (!points.length) {
    svg.appendChild(svgEl("text", { x: w / 2, y: h / 2, "text-anchor": "middle", class: "axis-label" })).textContent =
      "(keine Daten im gewählten Zeitraum)";
    return;
  }

  const values = points.map((p) => p[valueKey]);
  let minV = Math.min(...values);
  let maxV = Math.max(...values);
  if (minV === maxV) {
    minV -= 1;
    maxV += 1;
  }
  const vPad = (maxV - minV) * 0.1;
  minV -= vPad;
  maxV += vPad;

  const times = points.map(pointTimeMs);
  const minT = times[0];
  const maxT = times[times.length - 1];
  const spanT = Math.max(1, maxT - minT);
  const spanSeconds = spanT / 1000;

  const plotLeft = left, plotRight = w - right, plotTop = top, plotBottom = h - bottom;
  const xScale = (t) => plotLeft + ((t - minT) / spanT) * (plotRight - plotLeft);
  const yScale = (v) => plotTop + (1 - (v - minV) / (maxV - minV)) * (plotBottom - plotTop);

  // Plot-Hintergrund + abgerundeter Rahmen fuer den Datenbereich
  svg.appendChild(svgEl("rect", {
    x: plotLeft, y: plotTop, width: plotRight - plotLeft, height: plotBottom - plotTop,
    class: "chart-plot-bg", rx: 4,
  }));

  const gridCount = 4;
  for (let i = 0; i <= gridCount; i++) {
    const v = minV + ((maxV - minV) * i) / gridCount;
    const y = yScale(v);
    svg.appendChild(svgEl("line", { x1: plotLeft, x2: plotRight, y1: y, y2: y, class: "grid-line" }));
    svg.appendChild(svgEl("text", { x: plotLeft - 6, y: y + 3, "text-anchor": "end", class: "axis-label" })).textContent =
      v.toFixed(1);
  }

  [0, Math.floor(points.length / 2), points.length - 1].forEach((idx) => {
    if (idx < 0 || idx >= points.length) return;
    const x = xScale(times[idx]);
    const anchor = idx === 0 ? "start" : idx === points.length - 1 ? "end" : "middle";
    svg.appendChild(svgEl("text", { x, y: h - 8, "text-anchor": anchor, class: "axis-label" })).textContent =
      formatChartTime(points[idx].ts, spanSeconds);
  });

  let linePath = "";
  points.forEach((p, i) => {
    const x = xScale(times[i]);
    const y = yScale(p[valueKey]);
    linePath += (i === 0 ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1) + " ";
  });

  // Gradient-Flaeche unter der Linie (rein optisch, macht den Verlauf besser lesbar)
  const gradientId = `chart-grad-${++gradientIdCounter}`;
  const defs = svg.appendChild(svgEl("defs", {}));
  const gradient = defs.appendChild(svgEl("linearGradient", { id: gradientId, x1: 0, y1: 0, x2: 0, y2: 1 }));
  gradient.appendChild(svgEl("stop", { offset: "0%", "stop-color": color, "stop-opacity": 0.28 }));
  gradient.appendChild(svgEl("stop", { offset: "100%", "stop-color": color, "stop-opacity": 0.02 }));
  const areaPath = `${linePath}L${xScale(times[times.length - 1]).toFixed(1)},${plotBottom} L${xScale(times[0]).toFixed(1)},${plotBottom} Z`;
  svg.appendChild(svgEl("path", { d: areaPath, fill: `url(#${gradientId})`, stroke: "none" }));

  svg.appendChild(svgEl("path", { d: linePath.trim(), class: "series-line", stroke: color }));

  const hoverLine = svg.appendChild(
    svgEl("line", { class: "hover-line", y1: plotTop, y2: plotBottom, visibility: "hidden" })
  );
  const hoverDot = svg.appendChild(svgEl("circle", { r: 4.5, class: "hover-dot", fill: color, visibility: "hidden" }));
  const hoverBg = svg.appendChild(svgEl("rect", { class: "hover-text-bg", rx: 3, visibility: "hidden" }));
  const hoverText = svg.appendChild(svgEl("text", { class: "hover-text", visibility: "hidden" }));

  const selectionRect = svg.appendChild(
    svgEl("rect", { class: "chart-selection", y: plotTop, height: plotBottom - plotTop, visibility: "hidden" })
  );

  const overlay = svg.appendChild(
    svgEl("rect", { x: plotLeft, y: plotTop, width: plotRight - plotLeft, height: plotBottom - plotTop, fill: "transparent", cursor: "crosshair" })
  );

  function clientXToSvgX(clientX) {
    const rect = svg.getBoundingClientRect();
    return Math.min(plotRight, Math.max(plotLeft, ((clientX - rect.left) / rect.width) * w));
  }

  function nearestIndexForSvgX(svgX) {
    let nearest = 0;
    let nearestDist = Infinity;
    for (let i = 0; i < points.length; i++) {
      const dist = Math.abs(xScale(times[i]) - svgX);
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = i;
      }
    }
    return nearest;
  }

  function showHover(clientX) {
    const svgX = clientXToSvgX(clientX);
    const nearest = nearestIndexForSvgX(svgX);
    const p = points[nearest];
    const x = xScale(times[nearest]);
    const y = yScale(p[valueKey]);

    hoverLine.setAttribute("x1", x);
    hoverLine.setAttribute("x2", x);
    hoverLine.setAttribute("visibility", "visible");
    hoverDot.setAttribute("cx", x);
    hoverDot.setAttribute("cy", y);
    hoverDot.setAttribute("visibility", "visible");

    const label = `${formatChartTime(p.ts, spanSeconds)}  ${p[valueKey].toFixed(1)}`;
    hoverText.textContent = label;
    const textWidth = label.length * 6 + 10;
    let textX = x + 10;
    if (textX + textWidth > plotRight) textX = x - textWidth - 10;
    let textY = y - 12;
    if (textY < plotTop + 14) textY = y + 22;
    hoverText.setAttribute("x", textX + 5);
    hoverText.setAttribute("y", textY);
    hoverText.setAttribute("visibility", "visible");
    hoverBg.setAttribute("x", textX);
    hoverBg.setAttribute("y", textY - 12);
    hoverBg.setAttribute("width", textWidth);
    hoverBg.setAttribute("height", 17);
    hoverBg.setAttribute("visibility", "visible");
  }

  function hideHover() {
    hoverLine.setAttribute("visibility", "hidden");
    hoverDot.setAttribute("visibility", "hidden");
    hoverText.setAttribute("visibility", "hidden");
    hoverBg.setAttribute("visibility", "hidden");
  }

  // -- Ziehen zum Zoomen: Mousedown startet einen Drag (siehe der EINMALIGE
  // globale mousemove/mouseup-Handler weiter unten, der chartDragState
  // referenziert - bewusst nicht hier pro Render neu an window gebunden,
  // das wuerde bei jedem der alle 15s wiederkehrenden Chart-Redraws neue
  // Listener anhaeufen (Leak). Doppelklick setzt den Zoom zurueck.
  overlay.addEventListener("mousedown", (e) => {
    const svgX = clientXToSvgX(e.clientX);
    chartDragState = { svg, startSvgX: svgX, plotLeft, plotRight, minT, spanT, selectionRect };
    selectionRect.setAttribute("x", svgX);
    selectionRect.setAttribute("width", 0);
    selectionRect.setAttribute("visibility", "visible");
    hideHover();
  });
  overlay.addEventListener("mousemove", (e) => {
    if (!chartDragState) showHover(e.clientX);
  });
  overlay.addEventListener("mouseleave", () => {
    if (!chartDragState) hideHover();
  });
  overlay.addEventListener("dblclick", () => resetZoom());
  overlay.addEventListener("touchmove", (e) => {
    if (e.touches[0]) showHover(e.touches[0].clientX);
  });
}

// Ein EINZIGES globales Drag-Zoom-Handlerpaar fuer beide Graphen (statt pro
// renderChart()-Aufruf neu an window gebunden - siehe Kommentar oben).
let chartDragState = null;

function chartDragSvgX(state, clientX) {
  const rect = state.svg.getBoundingClientRect();
  return Math.min(state.plotRight, Math.max(state.plotLeft, ((clientX - rect.left) / rect.width) * CHART_WIDTH));
}

window.addEventListener("mousemove", (e) => {
  if (!chartDragState) return;
  const svgX = chartDragSvgX(chartDragState, e.clientX);
  const x1 = Math.min(chartDragState.startSvgX, svgX);
  const x2 = Math.max(chartDragState.startSvgX, svgX);
  chartDragState.selectionRect.setAttribute("x", x1);
  chartDragState.selectionRect.setAttribute("width", Math.max(0, x2 - x1));
});

window.addEventListener("mouseup", (e) => {
  if (!chartDragState) return;
  const state = chartDragState;
  chartDragState = null;
  state.selectionRect.setAttribute("visibility", "hidden");
  const svgX = chartDragSvgX(state, e.clientX);
  const x1 = Math.min(state.startSvgX, svgX);
  const x2 = Math.max(state.startSvgX, svgX);
  if (x2 - x1 < 4) return; // reiner Klick, kein Drag
  const startMs = state.minT + ((x1 - state.plotLeft) / (state.plotRight - state.plotLeft)) * state.spanT;
  const endMs = state.minT + ((x2 - state.plotLeft) / (state.plotRight - state.plotLeft)) * state.spanT;
  applyZoom(startMs, endMs);
});

async function refreshGraph() {
  if (!selectedHistoryMac) return;
  const resolution = graphResolutionSelect.value;
  const limit = parseInt(graphLimitInput.value, 10) || 2000;
  try {
    const res = await fetchJSON(
      `/api/devices/${encodeURIComponent(selectedHistoryMac)}/series?resolution=${resolution}&limit=${limit}`
    );
    lastGraphPoints = res.points;
    lastResolutionSeconds = res.resolution_seconds || 0;
    rerenderCharts();
    updateGraphInfoText();
  } catch (e) {
    graphInfoEl.textContent = "Fehler: " + e.message;
  }
}

graphResolutionSelect.addEventListener("change", () => {
  zoomRange = null;
  refreshGraph();
});
graphLimitInput.addEventListener("change", () => {
  zoomRange = null;
  refreshGraph();
});

// -- Status-Polling -------------------------------------------------------------

async function refreshAll() {
  try {
    const data = await fetchJSON("/api/status");
    renderScanResults(data.scan_results || [], data.scanning, data.scan_error);
    renderDevices(data.devices || []);
    const current = (data.devices || []).find((d) => d.mac === selectedHistoryMac);
    if (current && current.last_history_count != null) {
      historyInfoEl.textContent = `Letzter Abruf: ${current.last_history_count} Datensätze @ ${toLocalTime(
        current.last_history_ts
      )}`;
    }
  } catch (e) {
    scanStatusEl.textContent = "Keine Verbindung zum lokalen Server: " + e.message;
  }
}

refreshAll();
refreshConfig();
refreshDebug();
refreshLog();
refreshFirebaseStatus();

setInterval(refreshAll, 2000);
setInterval(refreshDebug, 5000);
setInterval(refreshLog, 4000);
setInterval(refreshGraph, 15000);
setInterval(refreshFirebaseStatus, 10000);

// -- Firebase-Upload -----------------------------------------------------------

async function refreshFirebaseStatus() {
  try {
    const s = await fetchJSON("/api/firebase/status");
    if (!s.enabled) {
      firebaseStatusEl.textContent = "deaktiviert (firebase_enabled=false in config.json)";
      firebaseUploadNowBtn.disabled = true;
      firebaseDetailEl.textContent = "";
      return;
    }
    firebaseUploadNowBtn.disabled = false;
    const parts = [
      `Projekt: ${s.project_id || "?"}`,
      `Collection: ${s.collection}`,
      `Intervall: ${Math.round(s.upload_interval_seconds / 60)} Min.`,
      s.last_upload_at ? `letzter Lauf: ${toLocalTime(s.last_upload_at)}` : "noch kein Lauf",
      s.last_verified_count_in_firestore !== null && s.last_verified_count_in_firestore !== undefined
        ? `in Firestore verifiziert: ${s.last_verified_count_in_firestore} Dokument(e) in der Collection`
        : (s.last_verify_error ? `Verifikation fehlgeschlagen: ${s.last_verify_error}` : "noch nicht verifiziert"),
    ];
    firebaseStatusEl.textContent = parts.join(" · ");
    firebaseDetailEl.textContent = JSON.stringify(s, null, 2);
  } catch (e) {
    firebaseStatusEl.textContent = "Fehler: " + e.message;
  }
}

firebaseUploadNowBtn.addEventListener("click", async () => {
  firebaseUploadNowBtn.disabled = true;
  try {
    await fetchJSON("/api/firebase/upload-now", { method: "POST" });
  } catch (e) {
    alert("Upload konnte nicht gestartet werden: " + e.message);
  } finally {
    setTimeout(() => {
      firebaseUploadNowBtn.disabled = false;
      refreshFirebaseStatus();
    }, 2000);
  }
});

// -- Hue-Bridge ------------------------------------------------------------

let hueIpPrefilled = false;
let hueLiveRunning = false;

async function refreshHueStatus() {
  try {
    const s = await fetchJSON("/api/hue/status");
    hueLiveRunning = !!s.live_running;
    if (!hueIpPrefilled && s.bridge_ip) {
      hueIpInput.value = s.bridge_ip;
      hueIpPrefilled = true;
    }
    if (!huePairPolling) huePairBtn.disabled = false;
    hueForgetBtn.disabled = !s.paired;
    huePullBtn.disabled = !s.paired;
    hueLiveStartBtn.disabled = !s.paired || s.live_running;
    hueLiveStopBtn.disabled = !s.live_running;

    if (!huePairPolling) {
      huePairStatusEl.textContent = s.paired
        ? `gekoppelt: ${s.bridge_ip} (bridge_id=${s.bridge_id || "?"})`
        : s.last_pair_error
        ? `nicht gekoppelt — letzter Fehler: ${s.last_pair_error}`
        : "nicht gekoppelt";
    }
    hueLiveStatusEl.textContent = s.live_running
      ? `läuft — ${s.live_event_count} Ereignis(se) empfangen`
      : s.last_live_error
      ? `gestoppt — letzter Fehler: ${s.last_live_error}`
      : "gestoppt";
    hueStatusDumpEl.textContent = JSON.stringify(s, null, 2);
  } catch (e) {
    hueStatusDumpEl.textContent = "Fehler: " + e.message;
  }
}

hueProbeBtn.addEventListener("click", async () => {
  const ip = hueIpInput.value.trim();
  if (!ip) {
    alert("Bitte Bridge-IP eintragen.");
    return;
  }
  hueProbeBtn.disabled = true;
  hueProbeStatusEl.textContent = "prüfe…";
  try {
    const res = await fetchJSON("/api/hue/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bridge_ip: ip }),
    });
    hueProbeStatusEl.textContent = res.ok
      ? `OK: ${res.info.name || "?"} (bridgeid=${res.info.bridgeid || "?"}, swversion=${res.info.swversion || "?"})`
      : "Fehler: " + res.error;
  } catch (e) {
    hueProbeStatusEl.textContent = "Fehler: " + e.message;
  } finally {
    hueProbeBtn.disabled = false;
  }
});

// Die Bridge gibt bei einer Kopplungsanfrage KEIN sichtbares Feedback (kein
// Blinken o.ae.) - sie liefert einfach still Fehler 101 ("link button not
// pressed") zurueck, wenn der Knopf nicht innerhalb der letzten 30s gedrueckt
// wurde. Statt exaktes Timing vom Nutzer zu verlangen (Knopf druecken UND
// exakt daraufhin klicken), wird hier 30s lang automatisch im Hintergrund
// weiterversucht - der Knopf kann jederzeit in diesem Fenster gedrueckt
// werden, Reihenfolge zum Klick egal.
const HUE_PAIR_WINDOW_MS = 30000;
const HUE_PAIR_RETRY_MS = 1200;
let huePairPolling = false;

async function attemptHuePair(ip) {
  return fetchJSON("/api/hue/pair", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bridge_ip: ip }),
  });
}

huePairBtn.addEventListener("click", async () => {
  const ip = hueIpInput.value.trim();
  if (!ip) {
    alert("Bitte Bridge-IP eintragen.");
    return;
  }
  if (huePairPolling) return;
  huePairPolling = true;
  huePairBtn.disabled = true;
  const deadline = Date.now() + HUE_PAIR_WINDOW_MS;
  huePairStatusEl.textContent = "Bitte jetzt die Taste auf der Bridge drücken (30s-Fenster läuft)…";
  try {
    while (Date.now() < deadline) {
      let res;
      try {
        res = await attemptHuePair(ip);
      } catch (e) {
        huePairStatusEl.textContent = "Fehler: " + e.message;
        return;
      }
      if (res.ok) {
        huePairStatusEl.textContent = "Gekoppelt!";
        return;
      }
      const buttonNotPressed = /link button/i.test(res.error || "");
      if (!buttonNotPressed) {
        huePairStatusEl.textContent = "Fehler: " + res.error;
        return;
      }
      const remaining = Math.max(0, Math.round((deadline - Date.now()) / 1000));
      huePairStatusEl.textContent = `Bitte jetzt die Taste auf der Bridge drücken – warte… (noch ${remaining}s)`;
      await new Promise((resolve) => setTimeout(resolve, HUE_PAIR_RETRY_MS));
    }
    huePairStatusEl.textContent = "Zeitfenster (30s) abgelaufen, ohne dass die Taste gedrückt wurde. Nochmal versuchen.";
  } finally {
    huePairPolling = false;
    huePairBtn.disabled = false;
    refreshHueStatus();
  }
});

hueForgetBtn.addEventListener("click", async () => {
  if (!confirm("Hue-Kopplung wirklich aufheben?")) return;
  try {
    await fetchJSON("/api/hue/forget", { method: "POST" });
  } catch (e) {
    alert("Fehler: " + e.message);
  } finally {
    refreshHueStatus();
  }
});

huePullBtn.addEventListener("click", async () => {
  huePullBtn.disabled = true;
  huePullStatusEl.textContent = "rufe ab…";
  try {
    const res = await fetchJSON("/api/hue/pull-now", { method: "POST" });
    if (res.ok) {
      const total = (res.data.data || []).length;
      huePullStatusEl.textContent = `OK: ${total} Ressourcen (${toLocalTime(new Date().toISOString())})`;
      huePullDumpEl.textContent = JSON.stringify(res.data, null, 2);
    } else {
      huePullStatusEl.textContent = "Fehler: " + res.error;
    }
  } catch (e) {
    huePullStatusEl.textContent = "Fehler: " + e.message;
  } finally {
    huePullBtn.disabled = false;
    refreshHueStatus();
  }
});

hueLiveStartBtn.addEventListener("click", async () => {
  hueLiveStartBtn.disabled = true;
  try {
    const res = await fetchJSON("/api/hue/live/start", { method: "POST" });
    if (!res.ok) alert("Live-Start fehlgeschlagen: " + res.error);
  } catch (e) {
    alert("Live-Start fehlgeschlagen: " + e.message);
  } finally {
    refreshHueStatus();
  }
});

hueLiveStopBtn.addEventListener("click", async () => {
  hueLiveStopBtn.disabled = true;
  try {
    await fetchJSON("/api/hue/live/stop", { method: "POST" });
  } catch (e) {
    alert("Fehler: " + e.message);
  } finally {
    refreshHueStatus();
  }
});

async function refreshHueEvents() {
  // Bewusst NICHT auf hueLiveRunning beschraenkt: dieses Log zeigt jetzt
  // alle Hue-Aktionen (Probe/Pairing/Pull/Live), nicht nur den SSE-Stream -
  // genau die Sichtbarkeit, die beim Debuggen fehlgeschlagener
  // Kopplungsversuche gefehlt hat.
  try {
    const entries = await fetchJSON("/api/hue/events?limit=200");
    const lines = entries.map((e) => {
      if (e.kind === "live-event") return `${toLocalTime(e.ts)} [event] ${JSON.stringify(e.event)}`;
      return `${toLocalTime(e.ts)} [${e.kind}] ${e.note || ""}`;
    });
    hueLiveLogEl.textContent = lines.join("\n") || "(noch keine Ereignisse)";
    hueLiveLogEl.scrollTop = hueLiveLogEl.scrollHeight;
  } catch (e) {
    hueLiveLogEl.textContent = "Fehler beim Laden: " + e.message;
  }
}

refreshHueStatus();
setInterval(refreshHueStatus, 3000);
setInterval(refreshHueEvents, 2000);
