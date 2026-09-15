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

const graphResolutionSelect = document.getElementById("graph-resolution");
const graphLimitInput = document.getElementById("graph-limit");
const graphInfoEl = document.getElementById("graph-info");
const graphTempSvg = document.getElementById("graph-temp");
const graphHumSvg = document.getElementById("graph-hum");

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
    refreshGraph();
  }
}

historyDeviceSelect.addEventListener("change", () => {
  selectedHistoryMac = historyDeviceSelect.value;
  exportLink.href = `/api/export.csv?mac=${encodeURIComponent(selectedHistoryMac)}`;
  refreshHistory();
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

// -- Graph (SVG, Temperatur + Luftfeuchte, einstellbare Aufloesung) -----------

const CHART_WIDTH = 900;
const CHART_HEIGHT = 220;
const CHART_PAD = { left: 45, right: 10, top: 10, bottom: 25 };
const SVGNS = "http://www.w3.org/2000/svg";

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
      "(keine Daten)";
    return;
  }

  const values = points.map((p) => p[valueKey]);
  let minV = Math.min(...values);
  let maxV = Math.max(...values);
  if (minV === maxV) {
    minV -= 1;
    maxV += 1;
  }
  const vPad = (maxV - minV) * 0.08;
  minV -= vPad;
  maxV += vPad;

  const times = points.map((p) => {
    const iso = p.ts.endsWith("Z") || p.ts.includes("+") ? p.ts : p.ts + "Z";
    return new Date(iso).getTime();
  });
  const minT = times[0];
  const maxT = times[times.length - 1];
  const spanT = Math.max(1, maxT - minT);
  const spanSeconds = spanT / 1000;

  const xScale = (t) => left + ((t - minT) / spanT) * (w - left - right);
  const yScale = (v) => top + (1 - (v - minV) / (maxV - minV)) * (h - top - bottom);

  const gridCount = 4;
  for (let i = 0; i <= gridCount; i++) {
    const v = minV + ((maxV - minV) * i) / gridCount;
    const y = yScale(v);
    svg.appendChild(svgEl("line", { x1: left, x2: w - right, y1: y, y2: y, class: "grid-line" }));
    svg.appendChild(svgEl("text", { x: left - 4, y: y + 3, "text-anchor": "end", class: "axis-label" })).textContent =
      v.toFixed(1);
  }

  [0, Math.floor(points.length / 2), points.length - 1].forEach((idx) => {
    if (idx < 0 || idx >= points.length) return;
    const x = xScale(times[idx]);
    const anchor = idx === 0 ? "start" : idx === points.length - 1 ? "end" : "middle";
    svg.appendChild(svgEl("text", { x, y: h - 6, "text-anchor": anchor, class: "axis-label" })).textContent =
      formatChartTime(points[idx].ts, spanSeconds);
  });

  let d = "";
  points.forEach((p, i) => {
    const x = xScale(times[i]);
    const y = yScale(p[valueKey]);
    d += (i === 0 ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1) + " ";
  });
  svg.appendChild(svgEl("path", { d: d.trim(), class: "series-line", stroke: color }));

  const hoverLine = svg.appendChild(
    svgEl("line", { class: "hover-line", y1: top, y2: h - bottom, visibility: "hidden" })
  );
  const hoverDot = svg.appendChild(svgEl("circle", { r: 4, class: "hover-dot", fill: color, visibility: "hidden" }));
  const hoverBg = svg.appendChild(svgEl("rect", { class: "hover-text-bg", visibility: "hidden" }));
  const hoverText = svg.appendChild(svgEl("text", { class: "hover-text", visibility: "hidden" }));

  const overlay = svg.appendChild(
    svgEl("rect", { x: left, y: top, width: w - left - right, height: h - top - bottom, fill: "transparent" })
  );

  function showHover(clientX) {
    const rect = svg.getBoundingClientRect();
    const svgX = ((clientX - rect.left) / rect.width) * w;
    let nearest = 0;
    let nearestDist = Infinity;
    for (let i = 0; i < points.length; i++) {
      const dist = Math.abs(xScale(times[i]) - svgX);
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = i;
      }
    }
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
    const textWidth = label.length * 6 + 8;
    let textX = x + 8;
    if (textX + textWidth > w - right) textX = x - textWidth - 8;
    let textY = y - 10;
    if (textY < top + 12) textY = y + 20;
    hoverText.setAttribute("x", textX + 4);
    hoverText.setAttribute("y", textY);
    hoverText.setAttribute("visibility", "visible");
    hoverBg.setAttribute("x", textX);
    hoverBg.setAttribute("y", textY - 11);
    hoverBg.setAttribute("width", textWidth);
    hoverBg.setAttribute("height", 15);
    hoverBg.setAttribute("visibility", "visible");
  }

  function hideHover() {
    hoverLine.setAttribute("visibility", "hidden");
    hoverDot.setAttribute("visibility", "hidden");
    hoverText.setAttribute("visibility", "hidden");
    hoverBg.setAttribute("visibility", "hidden");
  }

  overlay.addEventListener("mousemove", (e) => showHover(e.clientX));
  overlay.addEventListener("mouseleave", hideHover);
  overlay.addEventListener("touchmove", (e) => {
    if (e.touches[0]) showHover(e.touches[0].clientX);
  });
}

async function refreshGraph() {
  if (!selectedHistoryMac) return;
  const resolution = graphResolutionSelect.value;
  const limit = parseInt(graphLimitInput.value, 10) || 2000;
  try {
    const res = await fetchJSON(
      `/api/devices/${encodeURIComponent(selectedHistoryMac)}/series?resolution=${resolution}&limit=${limit}`
    );
    graphInfoEl.textContent =
      `${res.points.length} Punkte` + (res.resolution_seconds ? ` (${res.resolution_seconds}s-Buckets, gemittelt)` : " (Rohdaten)");
    renderChart(graphTempSvg, res.points, "temperature_c", "#2563eb");
    renderChart(graphHumSvg, res.points, "humidity_pct", "#059669");
  } catch (e) {
    graphInfoEl.textContent = "Fehler: " + e.message;
  }
}

graphResolutionSelect.addEventListener("change", refreshGraph);
graphLimitInput.addEventListener("change", refreshGraph);

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
setInterval(refreshGraph, 15000);
