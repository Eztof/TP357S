const scanBtn = document.getElementById("scan-btn");
const scanDurationInput = document.getElementById("scan-duration");
const scanStatusEl = document.getElementById("scan-status");
const scanResultsEl = document.getElementById("scan-results");

const deviceListEl = document.getElementById("device-list");
const noDevicesEl = document.getElementById("no-devices");

const historyDeviceSelect = document.getElementById("history-device");
const historyCountInput = document.getElementById("history-count");
const fetchHistoryBtn = document.getElementById("fetch-history-btn");
const exportLink = document.getElementById("export-link");
const historyInfoEl = document.getElementById("history-info");
const historyBody = document.getElementById("history-body");
const canvas = document.getElementById("chart");
const ctx = canvas.getContext("2d");

const STATUS_LABELS = {
  connecting: "Verbinde…",
  connected: "Verbunden",
  disconnected: "Getrennt",
  fetching_history: "Lade Verlauf…",
  error: "Fehler",
};

let knownDevices = [];
let selectedHistoryMac = null;
let pairedMacs = new Set();

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const message = (data && data.error) || `HTTP ${res.status}`;
    throw new Error(message);
  }
  return data;
}

function fmt(n, digits = 1) {
  return typeof n === "number" ? n.toFixed(digits) : "–";
}

function toLocalTime(isoUtc) {
  if (!isoUtc) return "–";
  const withZone = isoUtc.endsWith("Z") || isoUtc.includes("+") ? isoUtc : isoUtc + "Z";
  return new Date(withZone).toLocaleString();
}

function statusBadgeClass(status) {
  if (status === "connected") return "ok";
  if (status === "error") return "err";
  return "warn";
}

// -- Scan -------------------------------------------------------------------

scanBtn.addEventListener("click", async () => {
  const duration = parseInt(scanDurationInput.value, 10) || 8;
  scanBtn.disabled = true;
  try {
    await fetchJSON(`/api/scan?duration=${duration}`, { method: "POST" });
  } catch (e) {
    alert("Scan konnte nicht gestartet werden: " + e.message);
    scanBtn.disabled = false;
  }
});

function renderScanResults(results, scanning) {
  scanStatusEl.textContent = scanning ? "Scanne…" : results.length ? "" : "Noch keine Suche gestartet.";
  scanBtn.disabled = scanning;

  scanResultsEl.innerHTML = "";
  results.forEach((r) => {
    const li = document.createElement("li");
    li.className = "device-item";
    const already = pairedMacs.has(r.mac.toUpperCase());
    li.innerHTML = `
      <div class="device-main">
        <span class="device-name">${escapeHtml(r.name)}</span>
        <span class="device-mac">${r.mac}${r.rssi != null ? " · " + r.rssi + " dBm" : ""}</span>
      </div>
      <div class="device-actions"></div>
    `;
    const actions = li.querySelector(".device-actions");
    if (already) {
      const span = document.createElement("span");
      span.className = "muted";
      span.textContent = "bereits gekoppelt";
      actions.appendChild(span);
    } else {
      const btn = document.createElement("button");
      btn.textContent = "Hinzufügen";
      btn.addEventListener("click", () => addDevice(r.mac, r.name));
      actions.appendChild(btn);
    }
    scanResultsEl.appendChild(li);
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
    refreshStatus();
  } catch (e) {
    alert("Sensor konnte nicht hinzugefügt werden: " + e.message);
  }
}

// -- Gekoppelte Geraete ------------------------------------------------------

function renderDevices(devices) {
  pairedMacs = new Set(devices.map((d) => d.mac.toUpperCase()));
  noDevicesEl.style.display = devices.length ? "none" : "block";

  deviceListEl.innerHTML = "";
  devices.forEach((d) => {
    const li = document.createElement("li");
    li.className = "device-item";
    li.innerHTML = `
      <div class="device-main">
        <span class="device-name">${escapeHtml(d.name)}</span>
        <span class="badge ${statusBadgeClass(d.status)}">${STATUS_LABELS[d.status] || d.status}</span>
        <span class="device-mac">${d.mac}</span>
        ${d.last_error ? `<span class="error">${escapeHtml(d.last_error)}</span>` : ""}
        <div class="live-inline">
          ${d.last_live
            ? `${fmt(d.last_live.temperature_c)} °C · ${fmt(d.last_live.humidity_pct, 0)} % ` +
              `${d.last_live.battery_pct != null ? "· 🔋" + d.last_live.battery_pct + "%" : ""} ` +
              `<span class="muted">(${toLocalTime(d.last_live_ts)})</span>`
            : '<span class="muted">noch kein Messwert</span>'}
        </div>
      </div>
      <div class="device-actions">
        <button data-action="rename">Umbenennen</button>
        <button data-action="remove" class="danger">Entfernen</button>
      </div>
    `;
    li.querySelector('[data-action="rename"]').addEventListener("click", () => renameDevice(d.mac, d.name));
    li.querySelector('[data-action="remove"]').addEventListener("click", () => removeDevice(d.mac, d.name));
    deviceListEl.appendChild(li);
  });

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
    refreshStatus();
  } catch (e) {
    alert("Umbenennen fehlgeschlagen: " + e.message);
  }
}

async function removeDevice(mac, name) {
  if (!confirm(`Sensor "${name}" wirklich entfernen? (Gespeicherte Messwerte bleiben erhalten)`)) return;
  try {
    await fetchJSON(`/api/devices/${encodeURIComponent(mac)}`, { method: "DELETE" });
    refreshStatus();
  } catch (e) {
    alert("Entfernen fehlgeschlagen: " + e.message);
  }
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s == null ? "" : String(s);
  return div.innerHTML;
}

// -- Verlauf ------------------------------------------------------------------

function updateHistoryDeviceOptions(devices) {
  const previous = historyDeviceSelect.value;
  historyDeviceSelect.innerHTML = "";
  devices.forEach((d) => {
    const opt = document.createElement("option");
    opt.value = d.mac;
    opt.textContent = d.name;
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
    rows.slice(0, 50).forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${toLocalTime(r.ts)}</td><td>${fmt(r.temperature_c)}</td><td>${fmt(
        r.humidity_pct,
        0
      )}</td>`;
      historyBody.appendChild(tr);
    });
    drawChart(rows.slice().reverse());
  } catch (e) {
    // stiller Fehlschlag ist ok, z.B. wenn gerade kein Sensor ausgewaehlt ist
  }
}

function drawChart(rows) {
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!rows.length) return;

  const temps = rows.map((r) => r.temperature_c);
  const min = Math.min(...temps);
  const max = Math.max(...temps);
  const pad = 10;
  const scaleX = (w - 2 * pad) / Math.max(1, rows.length - 1);
  const scaleY = max === min ? 0 : (h - 2 * pad) / (max - min);

  ctx.strokeStyle = "#2563eb";
  ctx.lineWidth = 2;
  ctx.beginPath();
  rows.forEach((r, i) => {
    const x = pad + i * scaleX;
    const y = h - pad - (r.temperature_c - min) * scaleY;
    if (i === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();
}

// -- Status-Polling -----------------------------------------------------------

async function refreshStatus() {
  try {
    const data = await fetchJSON("/api/status");
    renderScanResults(data.scan_results || [], data.scanning);
    renderDevices(data.devices || []);
    if (data.devices && data.devices.length) {
      const current = data.devices.find((d) => d.mac === selectedHistoryMac);
      if (current && current.last_history_count != null) {
        historyInfoEl.textContent = `Letzter Abruf: ${current.last_history_count} Datensätze (${toLocalTime(
          current.last_history_ts
        )})`;
      }
    }
  } catch (e) {
    scanStatusEl.textContent = "Keine Verbindung zum lokalen Server";
  }
}

refreshStatus();
setInterval(refreshStatus, 3000);
setInterval(refreshHistory, 15000);
