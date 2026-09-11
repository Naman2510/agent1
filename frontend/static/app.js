const REFRESH_MS = 5000;

async function getJSON(path, opts) {
  const resp = await fetch(path, opts);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = new Error(body.error || `HTTP ${resp.status}`);
    err.body = body;
    throw err;
  }
  return body;
}

function setConn(ok) {
  const dot = document.getElementById("conn-dot");
  const label = document.getElementById("conn-label");
  dot.className = "dot " + (ok ? "dot-ok" : "dot-bad");
  label.textContent = ok ? "connected" : "backend unreachable";
}

function fmtTime(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleTimeString();
}

async function refreshOverview() {
  const el = {
    power: document.getElementById("power-state"),
    powerDetail: document.getElementById("power-detail"),
    raid: document.getElementById("raid-state"),
    raidDetail: document.getElementById("raid-detail"),
    thermalMax: document.getElementById("thermal-max"),
    thermalDetail: document.getElementById("thermal-detail"),
    faults: document.getElementById("fault-count"),
  };
  const data = await getJSON("/api/overview");

  el.power.textContent = data.power_state || "unknown";
  el.powerDetail.textContent = data.power_error
    ? `Redfish error: ${data.power_error}`
    : "via Redfish";

  if (!data.raid_available) {
    el.raid.textContent = "n/a";
    el.raidDetail.textContent = "no /proc/mdstat on this host";
  } else if (data.raid_degraded_count > 0) {
    el.raid.textContent = "DEGRADED";
    el.raidDetail.textContent = `${data.raid_degraded_count} array(s) need attention`;
  } else {
    el.raid.textContent = "healthy";
    el.raidDetail.textContent = "all arrays [UU]";
  }

  el.faults.textContent = data.hardware_faults_total ?? "—";

  return data;
}

async function refreshStorage() {
  const data = await getJSON("/api/storage");
  const mdBody = document.getElementById("mdstat-body");
  const md = data.mdstat;
  if (!md.available) {
    mdBody.textContent = md.reason;
  } else if (!md.arrays.length) {
    mdBody.textContent = "no md arrays found";
  } else {
    mdBody.textContent = md.arrays
      .map(a => `${a.device}  ${a.level}  ${a.state}  sync=${a.sync_status || "?"}${a.recovery_progress ? "  recovery=" + a.recovery_progress : ""}`)
      .join("\n");
  }

  const tbody = document.querySelector("#smart-table tbody");
  tbody.innerHTML = "";
  const smart = data.smart;
  if (smart.available) {
    for (const [disk, attrs] of Object.entries(smart.disks)) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${disk}</td><td>${attrs.reallocated_sector_count ?? "—"}</td>` +
        `<td>${attrs.current_pending_sector_count ?? "—"}</td>` +
        `<td>${attrs.offline_uncorrectable_sector_count ?? "—"}</td>`;
      tbody.appendChild(tr);
    }
  } else {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="4" class="muted">${smart.reason || "no data"}</td>`;
    tbody.appendChild(tr);
  }
}

async function refreshTelemetry(overviewEl) {
  const data = await getJSON("/api/telemetry");
  const tbody = document.querySelector("#thermal-table tbody");
  tbody.innerHTML = "";
  const thermalMaxEl = document.getElementById("thermal-max");
  const thermalDetailEl = document.getElementById("thermal-detail");

  if (!data.available) {
    thermalMaxEl.textContent = "n/a";
    thermalDetailEl.textContent = data.reason;
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="2" class="muted">${data.reason}</td>`;
    tbody.appendChild(tr);
    return;
  }

  const zones = data.metrics["telemetryd_thermal_celsius"] || [];
  let max = null;
  for (const z of zones) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${z.labels.zone}</td><td>${z.value.toFixed(1)}</td>`;
    tbody.appendChild(tr);
    if (max === null || z.value > max) max = z.value;
  }
  thermalMaxEl.textContent = max !== null ? `${max.toFixed(1)}°C` : "—";
  thermalDetailEl.textContent = `${zones.length} zone(s), updated ${fmtTime(data.mtime)}`;
}

async function refreshNetwork() {
  const data = await getJSON("/api/network");
  const body = document.getElementById("network-body");
  if (data.live) {
    const ifaceNames = (data.interfaces || []).map(i => i.ifname).join(", ");
    body.textContent = `live host data\ninterfaces: ${ifaceNames}\n\n` +
      `listening sockets:\n${(data.listening_sockets || []).join("\n")}`;
  } else {
    body.textContent = `${data.note}\n\n--- phase2-networking/netplan/01-netcfg.yaml ---\n${data.static_config || "(not found)"}`;
  }
}

async function refreshAlerts() {
  const data = await getJSON("/api/alerts");
  const list = document.getElementById("alerts-list");
  list.innerHTML = "";
  if (!data.alerts.length) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "no alerts received yet";
    list.appendChild(li);
    return;
  }
  for (const a of data.alerts.slice(0, 30)) {
    const li = document.createElement("li");
    const summary = a.message || [a.disk, a.zone, a.attribute].filter(Boolean).join(" / ") || JSON.stringify(a);
    li.innerHTML = `<span class="alert-type">${a.type || "alert"}</span> — ${summary} ` +
      `<div class="alert-time">${fmtTime(a.received_at)}</div>`;
    list.appendChild(li);
  }
}

async function refreshAll() {
  try {
    await Promise.all([refreshOverview(), refreshStorage(), refreshTelemetry(), refreshNetwork(), refreshAlerts()]);
    setConn(true);
  } catch (err) {
    console.error(err);
    setConn(false);
  }
}

function wireOobControls() {
  const output = document.getElementById("oob-output");

  document.getElementById("btn-power-cycle").addEventListener("click", async () => {
    const reset_type = document.getElementById("reset-type").value;
    output.textContent = "sending reset...";
    try {
      const result = await getJSON("/api/oob/power-cycle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reset_type }),
      });
      output.textContent = JSON.stringify(result, null, 2);
    } catch (err) {
      output.textContent = `error: ${err.message}`;
    }
  });

  document.getElementById("btn-boot-override").addEventListener("click", async () => {
    const target = document.getElementById("boot-target").value;
    output.textContent = "setting boot override...";
    try {
      const result = await getJSON("/api/oob/boot-override", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target }),
      });
      output.textContent = JSON.stringify(result, null, 2);
    } catch (err) {
      output.textContent = `error: ${err.message}`;
    }
  });

  document.getElementById("btn-set-led").addEventListener("click", async () => {
    const drive = document.getElementById("led-drive").value;
    const state = document.getElementById("led-state").value;
    output.textContent = "setting LED...";
    try {
      const result = await getJSON("/api/oob/set-led", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ drive, state }),
      });
      output.textContent = JSON.stringify(result, null, 2);
    } catch (err) {
      output.textContent = `error: ${err.message}`;
    }
  });

  document.getElementById("btn-run-drill").addEventListener("click", async () => {
    const failed_part = document.getElementById("drill-part").value;
    const drive_id = document.getElementById("drill-drive").value;
    const drillOutput = document.getElementById("drill-output");
    drillOutput.textContent = "running simulated drill...";
    try {
      const result = await getJSON("/api/drill/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ failed_part, drive_id }),
      });
      drillOutput.textContent = result.output;
    } catch (err) {
      drillOutput.textContent = `error: ${err.message}`;
    }
  });
}

wireOobControls();
refreshAll();
setInterval(refreshAll, REFRESH_MS);
