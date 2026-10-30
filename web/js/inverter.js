// Inverter page: one inverter's day (actual vs expected vs peers, alerts shaded), a maintenance work order and its alerts.

const ALERT_SHADE = "rgba(239, 68, 68, 0.14)";
let inverterId = new URLSearchParams(window.location.search).get("id");
let lastInverterData = null;

async function loadInverterPage(state) {
  try {
    // The inverter list comes from the heatmap (all inverters of the chosen plant).
    const { inverters } = await fetchJSON("/api/plant/heatmap", { plant: state.plant });
    if (!inverters.includes(inverterId)) inverterId = inverters[0];
    const select = document.getElementById("inverter-select");
    select.innerHTML = inverters.map((id) => `<option value="${escapeHTML(id)}">${escapeHTML(id)}</option>`).join("");
    select.value = inverterId;
    select.onchange = () => { inverterId = select.value; loadInverterPage(state); };

    const detail = await fetchJSON(`/api/inverter/${encodeURIComponent(inverterId)}`, { date: state.date });
    // Keep the address bar shareable: inverter.html?id=…&date=…&plant=…
    history.replaceState(null, "", `?id=${encodeURIComponent(inverterId)}&date=${state.date}&plant=${state.plant}`);
    clearError();
    lastInverterData = detail;
    renderInverter(detail);
  } catch (error) {
    showError(error.message);
  }
}

function renderInverter(detail) {
  const today = detail.daily_history.find((d) => d.date === detail.date) || {};
  const alertsToday = detail.alerts.filter((a) => alertOverlapsDay(a, detail.date));
  const trend = detail.pr_trend;
  document.getElementById("takeaway").textContent =
    `Inverter ${detail.inverter} (Plant ${detail.plant}) on ${fmt.date(detail.date)}: made ${fmt.pct(today.performance_ratio)} ` +
    `of expected, ${alertsToday.length} alert(s) that day. Over all days its actual-vs-expected trend is ` +
    `${trend ? `${trend.slope_pct_per_day >= 0 ? "+" : ""}${fmt.number(trend.slope_pct_per_day, 2)}% per day` : "unknown"}.`;

  const band = prStatus(today.performance_ratio);
  document.getElementById("kpis").innerHTML = `
    <div class="card"><div class="kpi-label">Actual energy</div><div class="kpi-value">${fmt.number(today.actual_kwh)}<span class="unit">kWh</span></div><div class="kpi-compare">on this day</div></div>
    <div class="card"><div class="kpi-label">Expected energy</div><div class="kpi-value">${fmt.number(today.expected_kwh)}<span class="unit">kWh</span></div><div class="kpi-compare">for this day's sunlight</div></div>
    <div class="card kpi ${band === "none" ? "" : band}"><div class="kpi-label">${AVE_LABEL}${infoTip(AVE_TIP)}</div><div class="kpi-value">${fmt.pct(today.performance_ratio, 1)}</div><div class="kpi-compare">100% = as estimated</div></div>
    <div class="card kpi ${today.fault_loss_kwh > 0 ? "bad" : "ok"}"><div class="kpi-label">Energy lost</div><div class="kpi-value">${fmt.number(today.fault_loss_kwh)}<span class="unit">kWh</span></div><div class="kpi-compare">${fmt.inr(today.fault_loss_inr)} (assumed tariff — <a href="about.html">see About</a>)</div></div>`;

  renderDayChart(detail, alertsToday);
  renderJobCard(detail);
  renderAlertList(detail);
}

function renderDayChart(detail, alertsToday) {
  const series = detail.series;
  const inAlert = series.map((p) => alertsToday.some((a) => p.timestamp >= a.start && p.timestamp < a.end));
  const missing = series.filter((p) => p.is_missing).length;
  document.getElementById("day-title").textContent = alertsToday.length
    ? `${alertsToday.length} alert period(s) on this day — shaded in red`
    : missing ? `${missing} missing readings on this day` : "Inverter followed its expected output all day";
  Charts.draw("day-chart", {
    type: "line",
    data: {
      labels: series.map((p) => fmt.time(p.timestamp)),
      datasets: [
        { label: "Actual (kW)", data: series.map((p) => p.actual_kw), borderColor: Charts.color("--chart-actual"),
          backgroundColor: Charts.color("--chart-actual"), borderWidth: 2, pointRadius: 0, tension: 0.2, spanGaps: false },
        { label: "Expected (kW)", data: series.map((p) => p.expected_kw), borderColor: Charts.color("--chart-expected"),
          backgroundColor: Charts.color("--chart-expected"), borderWidth: 2, borderDash: [6, 4], pointRadius: 0, tension: 0.2 },
        { label: "Peer median (kW)", data: series.map((p) => p.peer_median_kw), borderColor: Charts.color("--chart-sun"),
          backgroundColor: Charts.color("--chart-sun"), borderWidth: 1.5, pointRadius: 0, tension: 0.2 },
      ],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      scales: { x: Charts.axis("Time of day", { ticks: { maxTicksLimit: 12 } }),
                y: Charts.axis("AC power (kW)", { beginAtZero: true }) },
      plugins: {
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label.replace(" (kW)", "")}: ${ctx.parsed.y === null ? "no reading" : `${fmt.number(ctx.parsed.y)} kW`}`,
            afterBody: (items) => (inAlert[items[0].dataIndex] ? "⚠ inside an alert period" : ""),
          },
        },
      },
    },
    plugins: [Charts.shade(Charts.rangesFromFlags(inAlert, ALERT_SHADE))],
  });
}

// ---- Maintenance work order ----

/** What a technician should check for each fault type (expands the one-line recommended action). */
const JOB_CHECKS = {
  INVERTER_TRIP: ["Read the fault code on the inverter's display or event log",
    "Check the AC breaker, isolator and grid connection", "Restart only if safe, then watch the next sunny hour"],
  UNDERPERFORMANCE: ["Measure each string's current to find failed strings",
    "Check connectors and string fuses for looseness or burn marks", "Look for new shading or heavy dirt on the panels"],
  DEGRADATION: ["Clean the panels feeding this inverter", "Re-check output after cleaning; if it stays low, test the modules for ageing"],
  OVERHEATING: ["Check ventilation around the inverter", "Run a thermal check for hotspots", "Test the cooling fans"],
  DATA_GAP: ["Check the data logger's power and status lights", "Check the network cable / SIM link to this inverter",
    "Compare with the energy meter to see if it kept producing"],
  SENSOR_ISSUE: ["Recalibrate or replace the sensor / meter", "Fix the data logging settings"],
};
const HOT_PANEL_C = 50;   // trips with panels above this: check cooling first

const median = (values) => {
  const v = values.filter((x) => x !== null && x !== undefined).sort((a, b) => a - b);
  return v.length ? v[Math.floor((v.length - 1) / 2)] : null;
};
const minutesOf = (iso) => Number(iso.slice(11, 13)) * 60 + Number(iso.slice(14, 16));
const clock = (minutes) => `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(Math.round(minutes % 60)).padStart(2, "0")}`;

/** Everything on the work order, worked out from this inverter's alerts over the whole period. */
function buildJob(detail) {
  const alerts = detail.alerts, days = detail.daily_history.length || 1;
  const open = alerts.filter((a) => a.status !== "Resolved");
  const counts = {};
  alerts.forEach((a) => { counts[a.fault_type] = (counts[a.fault_type] || 0) + 1; });
  const types = Object.keys(counts).sort((x, y) => counts[y] - counts[x]);
  const main = types[0];
  const mainAlerts = alerts.filter((a) => a.fault_type === main);
  const sameDay = mainAlerts.filter((a) => a.duration_hours <= 24);   // "usually 10:30–14:30" only makes sense within a day
  const skies = {};
  mainAlerts.forEach((a) => { if (a.sky_condition) skies[a.sky_condition] = (skies[a.sky_condition] || 0) + 1; });
  const panel = median(mainAlerts.map((a) => a.module_temp_c));
  const judged = alerts.filter((a) => a.ai_diagnosis);
  const lost = alerts.reduce((sum, a) => sum + a.money_loss_inr, 0);
  const hot = main === "INVERTER_TRIP" && panel !== null && panel >= HOT_PANEL_C;
  return {
    detail, main, mainCount: counts[main], days,
    others: types.slice(1).map((t) => `${counts[t]} × ${fmt.fault(t)}`),
    priority: SEVERITIES.find((level) => open.some((a) => a.severity === level)),
    window: sameDay.length
      ? `${clock(median(sameDay.map((a) => minutesOf(a.start))))}–${clock(median(sameDay.map((a) => minutesOf(a.end))))}` : null,
    sky: Object.keys(skies).sort((x, y) => skies[y] - skies[x])[0],
    panel,
    aiAgrees: judged.filter((a) => a.ai_agrees).length, aiJudged: judged.length,
    last: alerts.reduce((latest, a) => (a.start > latest ? a.start : latest), ""),
    checks: [...(hot ? [`Its trips happen with panels around ${fmt.number(panel)} °C: also check the cooling fans and vents`] : []),
      ...(JOB_CHECKS[main] || [])],
    perMonth: (lost / days) * 30,
  };
}

/** Plain-text version of the work order (for Copy and WhatsApp). */
function jobText(job) {
  const d = job.detail;
  const when = job.window
    ? [`When: usually ${job.window}${job.sky ? `, ${job.sky.toLowerCase()} sky` : ""}${job.panel !== null ? `, panels ~${fmt.number(job.panel)} °C` : ""}`]
    : [];
  return [`MAINTENANCE WORK ORDER · Plant ${d.plant} · Inverter ${d.inverter}`, `Priority: ${job.priority || "none (all alerts resolved)"}`,
    `Problem: ${fmt.fault(job.main)} (${job.mainCount} times in ${job.days} days)${job.others.length ? `; also ${job.others.join(", ")}` : ""}`,
    ...when, `Last seen: ${fmt.date(job.last)}`, "Checks:", ...job.checks.map((c) => `[ ] ${c}`),
    `Worth fixing: about ${fmt.inr(job.perMonth)} per month`, `Details: ${location.href}`].join("\n");
}

function renderJobCard(detail) {
  const box = document.getElementById("job-card");
  if (!detail.alerts.length) {
    box.className = "card job-card ok";
    box.innerHTML = `<div class="job-head"><h2>Maintenance Work Order</h2><span class="status Resolved">No work needed</span></div>
      <p class="job-none">No faults found on this inverter in ${fmt.number(detail.daily_history.length)} days ✔</p>`;
    return;
  }
  const job = buildJob(detail);
  box.className = `card job-card${job.priority ? "" : " ok"}`;
  box.innerHTML = `
    <div class="job-head">
      <h2>Maintenance Work Order</h2>
      ${job.priority ? `<span class="job-priority">Priority ${severityBadge(job.priority)}</span>` : `<span class="status Resolved">All alerts resolved</span>`}
    </div>
    <p class="card-sub">Issued for the field service team · covers the whole period (${fmt.number(job.days)} days)</p>
    <dl class="job-facts">
      <dt>Problem</dt><dd><strong>${fmt.fault(job.main)}</strong>: ${fmt.number(job.mainCount)} times in ${fmt.number(job.days)} days${
        job.others.length ? `<span class="muted"> · also ${job.others.join(", ")}</span>` : ""}</dd>
      ${job.window ? `<dt>When</dt><dd>Usually <strong>${job.window}</strong>${job.sky ? ` · mostly ${skyChip(job.sky)}` : ""}${
        job.panel !== null ? ` · panels ~${fmt.number(job.panel)} °C` : ""}</dd>` : ""}
      <dt>Evidence</dt><dd>${job.aiJudged ? `AI classifier agrees on <strong>${job.aiAgrees} of ${job.aiJudged}</strong> alerts · ` : ""}last seen ${fmt.date(job.last)}</dd>
    </dl>
    <div class="job-checks">
      <div class="kpi-label">Checks</div>
      ${job.checks.map((c) => `<label><input type="checkbox"> ${escapeHTML(c)}</label>`).join("")}
    </div>
    <div class="job-worth">Worth fixing: about <strong>${fmt.inr(job.perMonth)} per month</strong>
      ${infoTip(`Money this inverter lost to faults over ${job.days} days, scaled to 30 days (${TARIFF_LABEL}).`)}</div>
    <div class="job-buttons">
      <button type="button" id="job-print">Print</button>
      <button type="button" id="job-copy">Copy</button>
      <a class="btn-whatsapp" target="_blank" rel="noopener" href="https://wa.me/?text=${encodeURIComponent(jobText(job))}">Share on WhatsApp</a>
    </div>`;
  document.getElementById("job-print").onclick = () => {
    document.body.classList.add("print-job");
    window.print();
    document.body.classList.remove("print-job");
  };
  document.getElementById("job-copy").onclick = async (event) => {
    const button = event.currentTarget;
    try {
      await navigator.clipboard.writeText(jobText(job));
      button.textContent = "Copied ✔";
    } catch {
      button.textContent = "Copy failed";
    }
    setTimeout(() => { button.textContent = "Copy"; }, 2000);
  };
}

function renderAlertList(detail) {
  document.getElementById("alerts-title").textContent = `Alerts for this inverter (${detail.alerts.length})`;
  const list = document.getElementById("alert-list");
  if (!detail.alerts.length) {
    list.innerHTML = `<li class="empty">No alerts for this inverter ✔</li>`;
    return;
  }
  list.innerHTML = detail.alerts.slice().reverse().map((a) => `
    <li><a href="alerts.html?id=${encodeURIComponent(a.id)}">
      <div class="list-title">${severityBadge(a.severity)} ${fmt.fault(a.fault_type)} <span class="status ${a.status}">${a.status}</span>
        ${confidenceBadge(a.confidence)}</div>
      <div class="list-meta">${fmt.date(a.start)} ${fmt.time(a.start)}–${fmt.time(a.end)} ·
        ${a.energy_at_risk_kwh > 0 ? `${fmt.kwh(a.energy_at_risk_kwh)} at risk` : `${fmt.kwh(a.energy_loss_kwh)} lost`}
        ${a.sky_condition ? ` · ${skyChip(a.sky_condition)}` : ""}${a.module_temp_c === null || a.module_temp_c === undefined ? "" : ` · panels ${fmt.number(a.module_temp_c)} °C`}</div>
    </a></li>`).join("");
}

window.addEventListener("themechange", () => { if (lastInverterData) renderInverter(lastInverterData); });
Layout.init("inverter", loadInverterPage);
