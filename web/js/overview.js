// Overview page: takeaway, KPI tiles, actual-vs-expected chart, alerts needing attention, plant 3D view.

let lastData = null;   // kept so charts can be redrawn when the theme changes
let plant3d = null;    // the 3D view (js/plant3d.js) once it has loaded; stays null if it cannot run

async function loadOverview(state) {
  const { plant, date } = state;
  if (typeof Replay !== "undefined") Replay.stop(false);   // a new plant/date ends any running replay
  document.getElementById("all-alerts-link").href = `alerts.html?plant=${plant}`;
  try {
    const [overview, series, attention, weather, status] = await Promise.all([
      fetchJSON("/api/overview", { plant, date }),
      fetchJSON("/api/plant/timeseries", { plant, date }),
      fetchJSON("/api/alerts", { plant, date, status: "Active", sort: "severity", limit: 5, include_notices: false }),
      fetchJSON("/api/weather/day", { plant, date }).catch(() => null),        // optional: page works without it
      fetchJSON("/api/inverters/status", { plant, date }).catch(() => null),   // optional: only the 3D view needs it
    ]);
    clearError();
    lastData = { overview, series, attention, weather, status };
    renderAll(lastData);
    plant3dReady.then((view) => view && view.show(status, { plant, date }));
  } catch (error) {
    showError(error.message);
  }
}

function renderAll({ overview, series, attention, weather, status }) {
  document.getElementById("takeaway").textContent = overview.takeaway;
  renderKpis(overview);
  renderWeatherMini(weather);
  renderDayChart(overview, series, weather);
  renderAttention(attention);
  renderPlantLegend(status);
}

function kpiTile(label, value, compare, status = "") {
  return `<div class="card kpi ${status}">
      <div class="kpi-label">${label}</div>
      <div class="kpi-value">${value}</div>
      <div class="kpi-compare">${compare}</div>
    </div>`;
}

// Big number with a small unit, e.g. 1,47,535 kWh (keeps the tile on one line).
const kwhValue = (value) => `${fmt.number(value)}<span class="unit">kWh</span>`;

function renderKpis(o) {
  const gap = o.actual_kwh - o.expected_kwh;
  const alerts = o.active_alerts_by_severity;
  const openCount = SEVERITIES.reduce((sum, level) => sum + (alerts[level] || 0), 0);
  const chips = SEVERITIES.filter((level) => alerts[level] > 0)
    .map((level) => `${severityBadge(`${alerts[level]} ${level}`)}`).join(" ");

  document.getElementById("kpis").innerHTML = [
    kpiTile("Actual energy", kwhValue(o.actual_kwh),
      `${gap >= 0 ? "+" : "−"}${fmt.kwh(Math.abs(gap))} vs expected`),
    kpiTile("Expected energy", kwhValue(o.expected_kwh), "for this day's sunlight & temperature"),
    kpiTile("Energy lost", kwhValue(o.fault_loss_kwh),
      o.at_risk_kwh > 0 ? `+ ${fmt.kwh(o.at_risk_kwh)} at risk (data gaps)` : "from detected faults",
      o.fault_loss_kwh > 0 ? "bad" : "ok"),
    kpiTile("Money lost", fmt.inr(o.fault_loss_inr),
      `at ₹${o.tariff_inr_per_kwh}/kWh`,
      o.fault_loss_inr > 0 ? "bad" : "ok"),
    kpiTile("Open alerts", fmt.number(openCount),
      openCount ? `<div class="chips">${chips}</div>` : "nothing open on this day",
      alerts.Critical > 0 ? "bad" : openCount ? "warn" : "ok"),
  ].join("");
}


/** Weather mini-card: sky, sunshine score, hottest panel, natural (weather) vs fixable (fault) losses. */
function renderWeatherMini(weather) {
  const card = document.getElementById("weather-mini");
  card.hidden = !weather;
  if (!weather) return;
  const d = weather.day;
  const sky = SKY[d.dominant_sky] || { icon: "" };
  card.innerHTML = `
    <span class="wm-icon" id="wm-icon" aria-hidden="true">${sky.icon}</span>
    <div class="wm-stat"><span class="kpi-label"><span id="wm-sky-label">Sky</span></span>
      <strong id="wm-sky">${escapeHTML(d.dominant_sky || "–")} · ${fmt.number(d.sunshine_score)}/100</strong></div>
    <div class="wm-stat"><span class="kpi-label" id="wm-temp-label">Hottest panel</span>
      <strong id="wm-temp">${fmt.number(d.max_module_c)} °C</strong></div>
    <div class="wm-stat"><span class="kpi-label" id="wm-natural-label">Weather cost (natural)</span>
      <strong id="wm-natural">${fmt.kwh(weather.natural_loss_kwh)}</strong></div>
    <div class="wm-stat"><span class="kpi-label" id="wm-fixable-label">Faults cost (fixable)</span>
      <strong id="wm-fixable">${fmt.kwh(weather.fixable_loss_kwh)}</strong></div>
    <a class="wm-link" href="weather.html">Weather & Energy →</a>`;
}

function renderDayChart(overview, series, weather = null) {
  const points = series.points;
  // Sky band above the chart: from the replay ticks themselves, or matched by time from /api/weather/day.
  const skyAt = weather ? Object.fromEntries(weather.points.map((p) => [p.timestamp, p.sky_label])) : {};
  const skyLabels = points.map((p) => (p.sky_label !== undefined ? p.sky_label : skyAt[p.timestamp] || null));
  const hasSky = skyLabels.some(Boolean);
  document.getElementById("day-chart-title").textContent = "Actual vs expected output";
  Charts.draw("day-chart", {
    type: "line",
    data: {
      labels: points.map((p) => fmt.time(p.timestamp)),
      datasets: [
        { label: "Actual (kW)", data: points.map((p) => p.actual_kw), borderColor: Charts.color("--chart-actual"),
          backgroundColor: Charts.color("--chart-actual"), borderWidth: 2, pointRadius: 0, tension: 0.25, yAxisID: "power" },
        { label: "Expected (kW)", data: points.map((p) => p.expected_kw), borderColor: Charts.color("--chart-expected"),
          backgroundColor: Charts.color("--chart-expected"), borderWidth: 2, borderDash: [6, 4], pointRadius: 0,
          tension: 0.25, yAxisID: "power" },
        { label: "Sunlight (irradiation)", data: points.map((p) => p.irradiation), borderColor: Charts.color("--chart-sun"),
          backgroundColor: "transparent", borderWidth: 1.5, pointRadius: 0, tension: 0.25, yAxisID: "sun", fill: false },
      ],
    },
    plugins: hasSky ? [Charts.skyStrip(skyLabels)] : [],
    options: (hasSky ? Charts.skyStripOptions : (o) => o)({
      interaction: { mode: "index", intersect: false },
      scales: {
        x: Charts.axis("Time of day", { ticks: { maxTicksLimit: 12 } }),
        power: Charts.axis("Plant AC power (kW)", { position: "left", beginAtZero: true }),
        sun: Charts.axis("Irradiation (kW/m²)", { position: "right", beginAtZero: true, grid: { drawOnChartArea: false } }),
      },
      plugins: {
        tooltip: {
          callbacks: {
            label: (ctx) => ctx.dataset.yAxisID === "sun"
              ? `Sunlight: ${fmt.number(ctx.parsed.y, 2)}`
              : `${ctx.dataset.label.replace(" (kW)", "")}: ${fmt.number(ctx.parsed.y)} kW`,
            afterBody: (items) => {
              const missing = points[items[0].dataIndex].missing_inverters;
              const sky = skyLabels[items[0].dataIndex];
              return [sky ? `Sky: ${sky}` : "", missing ? `${missing} inverter(s) not reporting` : ""].filter(Boolean);
            },
          },
        },
      },
    }),
  });
}

function renderAttention(attention) {
  const list = document.getElementById("attention");
  list.classList.remove("live");
  document.getElementById("attention-title").textContent = "Needs attention";   // the live replay changes these two
  document.getElementById("attention-sub").textContent = "Open alerts on this day, most severe first.";
  if (!attention.alerts.length) {
    list.innerHTML = `<li class="empty">No open alerts on this day ✔</li>`;
    return;
  }
  list.innerHTML = attention.alerts.map((a) => {
    const where = a.inverter === "ALL" ? "Whole plant" : `Inverter ${escapeHTML(a.inverter)}`;
    const impact = a.energy_at_risk_kwh > 0
      ? `${fmt.kwh(a.energy_at_risk_kwh)} at risk`
      : `${fmt.kwh(a.energy_loss_kwh)} lost · ${fmt.inr(a.money_loss_inr)}`;
    const when = a.duration_hours > 24 ? "whole period" : `${fmt.time(a.start)}–${fmt.time(a.end)}`;
    return `<li><a href="alerts.html?id=${encodeURIComponent(a.id)}">
        <div class="list-title">${severityBadge(a.severity)} ${fmt.fault(a.fault_type)}</div>
        <div class="list-meta">${where} · ${when} · ${impact}</div>
      </a></li>`;
  }).join("");
}

// ---- Plant 3D view (the 3D drawing itself lives in js/plant3d.js) ----

const PLANT_STATUS = [
  { key: "normal", label: "Normal", css: "l-ok" }, { key: "warning", label: "Warning", css: "l-warn" },
  { key: "critical", label: "Critical", css: "l-bad" }, { key: "offline", label: "Offline / data gap", css: "l-off" },
];

/** Legend under the 3D view: how many inverters are in each status (works even without 3D). */
function renderPlantLegend(status) {
  const legend = document.getElementById("plant3d-legend");
  legend.innerHTML = status
    ? PLANT_STATUS.map((s) => `<span class="${s.css}">${s.label}: <strong>${status.counts[s.key] || 0}</strong></span>`).join("")
    : "";
}

/** Tooltip for one inverter in the 3D view (numbers straight from /api/inverters/status). */
function plant3dTooltip(row) {
  const label = (PLANT_STATUS.find((s) => s.key === row.status) || { label: row.status }).label;
  const risk = row.at_risk_kwh > 0 ? ` · ${fmt.kwh(row.at_risk_kwh)} at risk (data gap)` : "";
  return `<div class="p3-head"><strong>Inverter ${escapeHTML(row.inverter)}</strong>
      <span class="p3-status p3-${row.status}">${label}</span></div>
    <div>Actual ${fmt.kwh(row.actual_kwh)} · expected ${fmt.kwh(row.expected_kwh)}</div>
    <div>Energy lost ${fmt.kwh(row.loss_kwh)} · ${fmt.inr(row.loss_inr)}${risk}</div>
    <div>Open alerts: ${row.open_alerts ?? 0}${row.main_fault ? ` · ${escapeHTML(fmt.fault(row.main_fault))}` : ""}</div>
    <div class="p3-open">${matchMedia("(pointer: coarse)").matches ? "Tap again" : "Click"} to open this inverter</div>`;
}

/** Show a message over the 3D area, e.g. while loading or when 3D cannot run on this device. */
function plant3dMessage(text) {
  const box = document.getElementById("plant3d-message");
  box.textContent = text;
  box.hidden = !text;
}

// Load Three.js + our 3D scene in the background. If the CDN is blocked, the browser is too old,
// or there is no WebGL, we show a friendly message and the rest of the page keeps working.
const plant3dReady = import("./plant3d.js")
  .then((module) => {
    module.start(document.getElementById("plant3d-view"), { describe: plant3dTooltip });
    plant3d = module;
    return module;
  })
  .catch(() => {
    plant3dMessage("3D view not available on this device");
    document.querySelector(".plant3d-buttons").hidden = true;
    return null;
  });

window.addEventListener("themechange", () => {
  if (typeof Replay !== "undefined") Replay.stop(false);
  if (lastData) renderAll(lastData);
});
Layout.init("overview", loadOverview);
