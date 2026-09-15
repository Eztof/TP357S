const statusEl = document.getElementById("status");
const errorEl = document.getElementById("error");
const tempEl = document.getElementById("temp");
const humEl = document.getElementById("hum");
const battEl = document.getElementById("batt");
const liveTsEl = document.getElementById("live-ts");
const historyBody = document.getElementById("history-body");
const historyInfoEl = document.getElementById("history-info");
const fetchBtn = document.getElementById("fetch-history-btn");
const countInput = document.getElementById("history-count");
const canvas = document.getElementById("chart");
const ctx = canvas.getContext("2d");

const STATUS_LABELS = {
  starting: "Startet…",
  connecting: "Verbinde…",
  connected: "Verbunden",
  disconnected: "Getrennt",
  fetching_history: "Lade Verlauf…",
  unconfigured: "Keine MAC-Adresse konfiguriert",
  error: "Fehler",
};

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

function fmt(n, digits = 1) {
  return typeof n === "number" ? n.toFixed(digits) : "–";
}

function toLocalTime(isoUtc) {
  if (!isoUtc) return "–";
  const withZone = isoUtc.endsWith("Z") || isoUtc.includes("+") ? isoUtc : isoUtc + "Z";
  return new Date(withZone).toLocaleString();
}

async function refreshStatus() {
  try {
    const data = await fetchJSON("/api/status");
    statusEl.textContent = STATUS_LABELS[data.status] || data.status;
    statusEl.className =
      "badge " + (data.status === "connected" ? "ok" : data.status === "error" ? "err" : "warn");
    errorEl.textContent = data.last_error || "";

    if (data.last_live) {
      tempEl.textContent = fmt(data.last_live.temperature_c) + " °C";
      humEl.textContent = fmt(data.last_live.humidity_pct, 0) + " %";
      battEl.textContent = data.last_live.battery_pct != null ? data.last_live.battery_pct + " %" : "–";
      liveTsEl.textContent = toLocalTime(data.last_live_ts);
    }

    if (data.last_history_count != null) {
      historyInfoEl.textContent = `Letzter Abruf: ${data.last_history_count} Datensätze (${toLocalTime(
        data.last_history_ts
      )})`;
    }
  } catch (e) {
    statusEl.textContent = "Keine Verbindung zum lokalen Server";
    statusEl.className = "badge err";
  }
}

async function refreshHistory() {
  try {
    const rows = await fetchJSON("/api/history?limit=200");
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
    // Verlauf ist optional beim ersten Laden; stiller Fehlschlag ist ok.
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

fetchBtn.addEventListener("click", async () => {
  const count = parseInt(countInput.value, 10) || 500;
  fetchBtn.disabled = true;
  try {
    const res = await fetchJSON(`/api/fetch-history?count=${count}`, { method: "POST" });
    if (!res.ok) {
      alert("Fehler: " + res.error);
    }
  } catch (e) {
    alert("Fehler beim Anfordern des Verlaufs: " + e.message);
  } finally {
    setTimeout(() => (fetchBtn.disabled = false), 2000);
  }
});

refreshStatus();
refreshHistory();
setInterval(refreshStatus, 3000);
setInterval(refreshHistory, 15000);
