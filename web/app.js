// NetBalance Minimal Vanilla JavaScript Dashboard Client

const POLL_INTERVAL_MS = 1000;
const API_URL = "/api/metrics";
const ALGORITHM_URL = "/api/algorithm";
const WEIGHTS_URL = "/api/weights";
const RESET_URL = "/api/reset";

let isFetching = false;
let notificationTimeout = null;

function showNotification(message, isSuccess = true) {
  const box = document.getElementById("control-notification");
  if (!box) return;
  if (notificationTimeout) {
    clearTimeout(notificationTimeout);
    notificationTimeout = null;
  }
  box.textContent = message;
  box.className = isSuccess ? "notification-box notification-success" : "notification-box notification-error";
  box.style.display = "block";
  notificationTimeout = setTimeout(() => {
    box.style.display = "none";
  }, 5000);
}

function updateElementText(id, text) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = text !== null && text !== undefined ? String(text) : "--";
  }
}

function formatLatency(val) {
  if (val === null || val === undefined) return "--";
  return typeof val === "number" ? val.toFixed(2) : String(val);
}

function createHealthBadge(health) {
  const h = String(health || "unknown").toLowerCase();
  const span = document.createElement("span");
  const cls = h === "healthy" ? "health-healthy" : h === "unhealthy" ? "health-unhealthy" : "health-unknown";
  span.className = `health-pill ${cls}`;
  span.textContent = h;
  return span;
}

function syncControlInputs(data) {
  // Sync algorithm select if user hasn't focused it
  const selectAlgo = document.getElementById("select-algorithm");
  if (selectAlgo && document.activeElement !== selectAlgo && data.algorithm) {
    selectAlgo.value = String(data.algorithm).toLowerCase();
  }

  // Sync weight inputs if container exists and user hasn't focused them
  if (data.backends && Array.isArray(data.backends)) {
    data.backends.forEach(b => {
      if (!b.id) return;
      const input = document.getElementById(`weight-${b.id}`);
      if (input && document.activeElement !== input && b.weight !== undefined) {
        input.value = String(b.weight);
      }
    });
  }
}

function renderBackends(backends) {
  const tbody = document.getElementById("backends-tbody");
  if (!tbody) return;

  // Clear existing rows safely
  tbody.replaceChildren();

  if (!backends || backends.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 10;
    td.className = "empty-state";
    td.textContent = "No backends configured";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  backends.forEach(b => {
    const tr = document.createElement("tr");

    // ID
    const tdId = document.createElement("td");
    const strongId = document.createElement("strong");
    strongId.textContent = b.id != null ? String(b.id) : "--";
    tdId.appendChild(strongId);
    tr.appendChild(tdId);

    // Endpoint
    const tdEndpoint = document.createElement("td");
    tdEndpoint.textContent = `${b.host ?? "--"}:${b.port ?? "--"}`;
    tr.appendChild(tdEndpoint);

    // Weight
    const tdWeight = document.createElement("td");
    tdWeight.textContent = b.weight != null ? String(b.weight) : "--";
    tr.appendChild(tdWeight);

    // Health
    const tdHealth = document.createElement("td");
    tdHealth.appendChild(createHealthBadge(b.health));
    tr.appendChild(tdHealth);

    // Active
    const tdActive = document.createElement("td");
    tdActive.textContent = String(b.active ?? 0);
    tr.appendChild(tdActive);

    // Assignments
    const tdAssignments = document.createElement("td");
    tdAssignments.textContent = String(b.assignments ?? 0);
    tr.appendChild(tdAssignments);

    // Successes
    const tdSuccesses = document.createElement("td");
    tdSuccesses.textContent = String(b.successes ?? 0);
    tr.appendChild(tdSuccesses);

    // Failures
    const tdFailures = document.createElement("td");
    tdFailures.textContent = String(b.failures ?? 0);
    tr.appendChild(tdFailures);

    // Streaks
    const tdStreaks = document.createElement("td");
    tdStreaks.textContent = `${b.consecutive_probe_successes ?? 0} / ${b.consecutive_probe_failures ?? 0}`;
    tr.appendChild(tdStreaks);

    // Last Transition
    const tdLastTrans = document.createElement("td");
    if (b.last_transition_at) {
      const date = new Date(b.last_transition_at);
      tdLastTrans.textContent = isNaN(date.getTime()) ? String(b.last_transition_at) : date.toLocaleTimeString();
    } else {
      tdLastTrans.textContent = "--";
    }
    tr.appendChild(tdLastTrans);

    tbody.appendChild(tr);
  });
}

function renderEvents(events) {
  const tbody = document.getElementById("events-tbody");
  if (!tbody) return;

  tbody.replaceChildren();

  if (!events || events.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 7;
    td.className = "empty-state";
    td.textContent = "No recent events recorded";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  // Display most recent first (up to last 20 in UI table)
  const displayEvents = events.slice(-20).reverse();

  displayEvents.forEach(e => {
    const tr = document.createElement("tr");

    // Timestamp
    const tdTs = document.createElement("td");
    if (e.timestamp) {
      const date = new Date(e.timestamp);
      tdTs.textContent = isNaN(date.getTime()) ? String(e.timestamp) : date.toLocaleTimeString();
    } else {
      tdTs.textContent = "--";
    }
    tr.appendChild(tdTs);

    // Action
    const tdAction = document.createElement("td");
    const strongAction = document.createElement("strong");
    strongAction.textContent = e.action != null ? String(e.action) : "--";
    tdAction.appendChild(strongAction);
    tr.appendChild(tdAction);

    // Request ID
    const tdReqId = document.createElement("td");
    tdReqId.textContent = e.request_id != null ? String(e.request_id) : "--";
    tr.appendChild(tdReqId);

    // Backend ID
    const tdBId = document.createElement("td");
    tdBId.textContent = e.backend_id != null ? String(e.backend_id) : "--";
    tr.appendChild(tdBId);

    // Outcome
    const tdOutcome = document.createElement("td");
    tdOutcome.textContent = e.outcome != null ? String(e.outcome) : "--";
    tr.appendChild(tdOutcome);

    // Error Code
    const tdErrCode = document.createElement("td");
    tdErrCode.textContent = e.error_code != null ? String(e.error_code) : "--";
    tr.appendChild(tdErrCode);

    // Latency
    const tdLat = document.createElement("td");
    tdLat.textContent = formatLatency(e.latency_ms);
    tr.appendChild(tdLat);

    tbody.appendChild(tr);
  });
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
  updateElementText("stat-policy", data.algorithm ? String(data.algorithm).toUpperCase() : "--");
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

  // Sync inputs with live config
  syncControlInputs(data);

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
  if (isFetching) return;
  isFetching = true;
  try {
    const res = await fetch(API_URL, { cache: "no-store" });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    renderDashboard(data, false);
  } catch (err) {
    renderDisconnected(err.message || "Fetch Failed");
  } finally {
    isFetching = false;
  }
}

async function handleAlgorithmSubmit(e) {
  e.preventDefault();
  const select = document.getElementById("select-algorithm");
  const btn = document.getElementById("btn-algorithm");
  if (!select || !btn) return;

  const algorithm = select.value;
  btn.disabled = true;

  try {
    const res = await fetch(ALGORITHM_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ algorithm }),
    });

    if (res.ok) {
      const data = await res.json();
      showNotification(`Policy successfully changed to ${data.algorithm} (rev ${data.config_revision})`, true);
      await fetchMetrics();
    } else {
      let detail = `HTTP ${res.status}`;
      try {
        const errJson = await res.json();
        if (errJson.detail) detail += `: ${JSON.stringify(errJson.detail)}`;
      } catch (_) {}
      showNotification(`Failed to change policy: ${detail}`, false);
      await fetchMetrics();
    }
  } catch (err) {
    showNotification(`Network error changing policy: ${err.message || "API Unavailable"}`, false);
  } finally {
    btn.disabled = false;
  }
}

async function handleWeightsSubmit(e) {
  e.preventDefault();
  const btn = document.getElementById("btn-weights");
  const inputs = document.querySelectorAll("#weights-inputs-container input[type='number']");
  if (!btn) return;

  const weights = {};
  let valid = true;

  inputs.forEach(input => {
    const backendId = input.name;
    const val = parseInt(input.value, 10);
    if (isNaN(val) || val < 1 || val > 100) {
      valid = false;
    } else {
      weights[backendId] = val;
    }
  });

  if (!valid || Object.keys(weights).length === 0) {
    showNotification("Weights must be integers between 1 and 100 for all backends.", false);
    return;
  }

  btn.disabled = true;

  try {
    const res = await fetch(WEIGHTS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ weights }),
    });

    if (res.ok) {
      const data = await res.json();
      showNotification(`Weights updated successfully (rev ${data.config_revision})`, true);
      await fetchMetrics();
    } else {
      let detail = `HTTP ${res.status}`;
      try {
        const errJson = await res.json();
        if (errJson.detail) detail += `: ${JSON.stringify(errJson.detail)}`;
      } catch (_) {}
      showNotification(`Failed to update weights: ${detail}`, false);
      await fetchMetrics();
    }
  } catch (err) {
    showNotification(`Network error updating weights: ${err.message || "API Unavailable"}`, false);
  } finally {
    btn.disabled = false;
  }
}

async function handleResetSubmit(e) {
  e.preventDefault();
  const btn = document.getElementById("btn-reset");
  if (!btn) return;

  btn.disabled = true;

  try {
    const res = await fetch(RESET_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });

    if (res.ok) {
      const data = await res.json();
      showNotification(`Telemetry reset successfully (epoch ${data.metrics_epoch})`, true);
      await fetchMetrics();
    } else if (res.status === 409) {
      let detail = "Reset rejected: active work in progress (HTTP 409 Busy)";
      try {
        const errJson = await res.json();
        if (errJson.detail) detail = `Reset rejected: ${errJson.detail} (HTTP 409)`;
      } catch (_) {}
      showNotification(detail, false);
      await fetchMetrics();
    } else {
      let detail = `HTTP ${res.status}`;
      try {
        const errJson = await res.json();
        if (errJson.detail) detail += `: ${JSON.stringify(errJson.detail)}`;
      } catch (_) {}
      showNotification(`Failed to reset metrics: ${detail}`, false);
      await fetchMetrics();
    }
  } catch (err) {
    showNotification(`Network error resetting metrics: ${err.message || "API Unavailable"}`, false);
  } finally {
    btn.disabled = false;
  }
}

// Initial fetch and setup
document.addEventListener("DOMContentLoaded", () => {
  const formAlgo = document.getElementById("form-algorithm");
  if (formAlgo) formAlgo.addEventListener("submit", handleAlgorithmSubmit);

  const formWeights = document.getElementById("form-weights");
  if (formWeights) formWeights.addEventListener("submit", handleWeightsSubmit);

  const formReset = document.getElementById("form-reset");
  if (formReset) formReset.addEventListener("submit", handleResetSubmit);

  fetchMetrics();
  setInterval(fetchMetrics, POLL_INTERVAL_MS);
});
