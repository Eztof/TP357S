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
const historyBody = document.getElementById("history-body");

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
          ? `${d.last_live.temperature_c.toFixed(1)}°C ${d.last_live.humidity_pct}% byte6(vermutl. Batt.)=${d.last_live.battery_pct}` +
            ` @ ${toLocalTime(d.last_live_ts)}`
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
      entry = { container, header, pre, intervalId };
      trackedDeviceLogs.set(d.mac, entry);
      fetchDeviceLog(d.mac, pre);
    }
    entry.header.textContent = `${d.name} (${d.mac}) — ${d.status}${d.is_probe ? " [Live-Test]" : ""} — ${d.packet_count} Pakete`;
  });
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
    historyBody.innerHTML = "";
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
    refreshHistory();
  }
}

historyDeviceSelect.addEventListener("change", () => {
  selectedHistoryMac = historyDeviceSelect.value;
  exportLink.href = `/api/export.csv?mac=${encodeURIComponent(selectedHistoryMac)}`;
  refreshHistory();
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

async function refreshHistory() {
  if (!selectedHistoryMac) return;
  try {
    const rows = await fetchJSON(`/api/devices/${encodeURIComponent(selectedHistoryMac)}/history?limit=200`);
    historyBody.innerHTML = "";
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${toLocalTime(r.ts)}</td><td>${r.temperature_c.toFixed(1)}</td><td>${r.humidity_pct}</td>`;
      historyBody.appendChild(tr);
    });
  } catch (e) {
    historyInfoEl.textContent = "Fehler beim Laden des Verlaufs: " + e.message;
  }
}

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

setInterval(refreshAll, 2000);
setInterval(refreshDebug, 5000);
setInterval(refreshLog, 4000);
setInterval(refreshHistory, 15000);
