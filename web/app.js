// NetBalance Minimal Vanilla JavaScript Dashboard Client

const POLL_INTERVAL_MS = 1000;
const API_URL = "/api/metrics";

function updateElementText(id, text) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = text !== null && text !== undefined ? text : "--";
  }
}

function formatLatency(val) {
  if (val === null || val === undefined) return "--";
  return typeof val === "number" ? val.toFixed(2) : String(val);
}

function renderHealthBadge(health) {
  const h = String(health || "unknown").toLowerCase();
  const cls = h === "healthy" ? "health-healthy" : h === "unhealthy" ? "health-unhealthy" : "health-unknown";
  return `<span class="health-pill ${cls}">${h}</span>`;
}

function renderBackends(backends) {
  const tbody = document.getElementById("backends-tbody");
  if (!tbody) return;

  if (!backends || backends.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty-state">No backends configured</td></tr>';
    return;
  }

  tbody.innerHTML = backends
    .map(b => {
      const streaks = `${b.consecutive_probe_successes ?? 0} / ${b.consecutive_probe_failures ?? 0}`;
      const lastTrans = b.last_transition_at ? new Date(b.last_transition_at).toLocaleTimeString() : "--";
      return `
        <tr>
          <td><strong>${b.id}</strong></td>
          <td>${b.host}:${b.port}</td>
          <td>${b.weight}</td>
          <td>${renderHealthBadge(b.health)}</td>
          <td>${b.active ?? 0}</td>
          <td>${b.assignments ?? 0}</td>
          <td>${b.successes ?? 0}</td>
          <td>${b.failures ?? 0}</td>
          <td>${streaks}</td>
          <td>${lastTrans}</td>
        </tr>
      `;
    })
    .join("");
}

function renderEvents(events) {
  const tbody = document.getElementById("events-tbody");
  if (!tbody) return;

  if (!events || events.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No recent events recorded</td></tr>';
    return;
  }

  // Display most recent first (up to last 20 in UI table)
  const displayEvents = events.slice(-20).reverse();

  tbody.innerHTML = displayEvents
    .map(e => {
      const ts = e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : "--";
      const reqId = e.request_id || "--";
      const bId = e.backend_id || "--";
      const outcome = e.outcome || "--";
      const errCode = e.error_code || "--";
      const lat = formatLatency(e.latency_ms);
      return `
        <tr>
          <td>${ts}</td>
          <td><strong>${e.action || "--"}</strong></td>
          <td>${reqId}</td>
          <td>${bId}</td>
          <td>${outcome}</td>
          <td>${errCode}</td>
          <td>${lat}</td>
        </tr>
      `;
    })
    .join("");
}

function renderDashboard(data, isFixture = false) {
  const badge = document.getElementById("connection-badge");
  if (badge) {
    if (isFixture) {
      badge.textContent = "TEST FIXTURE ONLY";
      badge.className = "badge badge-fixture";
    } else {
      badge.textContent = "CONNECTED (LIVE API)";
      badge.className = "badge badge-connected";
    }
  }

  // Overview stats
  updateElementText("stat-policy", (data.algorithm || "--").toUpperCase());
  updateElementText("stat-inflight", data.inflight ?? 0);
  updateElementText("stat-epoch", data.metrics_epoch ?? 0);
  updateElementText("stat-revision", data.config_revision ?? 0);

  // Totals
  const totals = data.totals || {};
  updateElementText("stat-received", totals.received ?? 0);
  updateElementText("stat-succeeded", totals.succeeded ?? 0);
  updateElementText("stat-failed", totals.failed ?? 0);
  updateElementText("stat-rejected", totals.rejected ?? 0);
  updateElementText("stat-protocol-errors", totals.protocol_errors ?? 0);

  // Latency stats
  const lat = data.successful_proxy_latency_ms || {};
  updateElementText("lat-count", lat.count ?? 0);
  updateElementText("lat-mean", formatLatency(lat.mean));
  updateElementText("lat-p50", formatLatency(lat.p50));
  updateElementText("lat-p95", formatLatency(lat.p95));

  // Backends & Events
  renderBackends(data.backends || []);
  renderEvents(data.events || []);

  const lastUpdate = document.getElementById("last-update");
  if (lastUpdate) {
    lastUpdate.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
  }
}

function renderDisconnected(errorMessage = "Disconnected / Error") {
  const badge = document.getElementById("connection-badge");
  if (badge) {
    badge.textContent = `DISCONNECTED (${errorMessage})`;
    badge.className = "badge badge-disconnected";
  }
}

async function fetchMetrics() {
  try {
    const res = await fetch(API_URL, { cache: "no-store" });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    renderDashboard(data, false);
  } catch (err) {
    renderDisconnected(err.message || "Fetch Failed");
  }
}

// Initial fetch and interval
document.addEventListener("DOMContentLoaded", () => {
  fetchMetrics();
  setInterval(fetchMetrics, POLL_INTERVAL_MS);
});
