// Weather & Energy page: the day's sky (read from sunlight), heat, the energy waterfall, a weather-or-plant
// verdict and a calendar of all days. Every number comes from the API — nothing is calculated here.

const WATERFALL_TIPS = {
  clear_sky_potential: "What the plant would make under a clear sky with panels at 25 °C.",
  cloud_loss: "Natural: sunlight blocked by clouds. Nobody can fix it.",
  heat_loss: "Natural: hot panels make less power. Nobody can fix the weather.",
  fault_loss: "Fixable: confirmed losses from our alerts — this is where money is saved.",
  not_measured: "Unknown: expected energy while an inverter sent no readings (fault or fine — we cannot see).",
  other: "Unknown: normal model error and problems too small for an alert (can be + or −).",
  actual: "Energy the plant really made.",
};
let weatherData = null;
let waterfallMode = "day";

async function loadWeather(state) {
  const { plant, date } = state;
  try {
    const [day, calendar, period, overview] = await Promise.all([
      fetchJSON("/api/weather/day", { plant, date }),
      fetchJSON("/api/weather/calendar", { plant }),
      fetchJSON("/api/breakdown", { plant }),
      fetchJSON("/api/overview", { plant, date }),
    ]);
    clearError();
    weatherData = { day, calendar, period, overview };
    renderWeather(weatherData);
  } catch (error) {
    showError(error.message);
  }
}

function renderWeather({ day, calendar, period, overview }) {
  document.getElementById("takeaway").textContent = day.takeaway;
  document.getElementById("hot-threshold").textContent = fmt.number(day.hot_module_temp_c);
  renderKpis(day);
  renderSkyChart(day);
  renderWaterfall(waterfallMode === "day"
    ? { ...day, steps: day.waterfall, label: fmt.date(day.date), fixable_inr: day.day.fault_loss_inr }
    : { ...period, label: "Whole period", fixable_inr: period.fixable_loss_inr });
  renderTempChart(day);
  renderVerdict(day, overview);
  renderCalendar(calendar, day.date);
}

const kwhTile = (value) => `${fmt.number(value)}<span class="unit">kWh</span>`;
const step = (steps, part) => steps.find((s) => s.part === part);

function renderKpis(data) {
  const d = data.day;
  const clouds = step(data.waterfall, "cloud_loss"), faults = step(data.waterfall, "fault_loss");
  const tile = (label, value, compare, status = "") => `<div class="card kpi ${status}">
      <div class="kpi-label">${label}</div><div class="kpi-value">${value}</div>
      <div class="kpi-compare">${compare}</div></div>`;
  document.getElementById("kpis").innerHTML = [
    tile("Sky", `${SKY[d.dominant_sky] ? SKY[d.dominant_sky].icon : ""} ${escapeHTML(d.dominant_sky || "–")}`,
      `sunshine score ${fmt.number(d.sunshine_score)}/100`),
    tile("Hottest panel", `${fmt.number(d.max_module_c)}<span class="unit">°C</span>`,
      `at ${fmt.time(d.max_module_time)} · air up to ${fmt.number(d.max_ambient_c)} °C`, d.hot_hours > 0 ? "warn" : ""),
    tile("Clouds cost", kwhTile(clouds.kwh), `${fmt.number(clouds.pct_of_potential)}% of clear-sky potential · natural`),
    tile("Heat cost", kwhTile(d.heat_loss_kwh), `${fmt.number(d.heat_loss_pct, 1)}% of 25 °C energy · natural`),
    tile("Faults cost", kwhTile(faults.kwh), `${fmt.inr(d.fault_loss_inr)} · fixable`,
      faults.kwh > 0 ? "bad" : "ok"),
  ].join("");
}

function renderSkyChart(data) {
  const points = data.points;
  document.getElementById("sky-title").textContent = data.day.summary;
  document.getElementById("sky-legend").innerHTML = Charts.skyLegend();
  const line = (label, key, color, axis, extra = {}) => Object.assign({ label, data: points.map((p) => p[key]),
    borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, tension: 0.25, yAxisID: axis }, extra);
  Charts.draw("sky-chart", {
    type: "line",
    data: {
      labels: points.map((p) => fmt.time(p.timestamp)),
      datasets: [
        line("Clear-sky sunlight", "clear_sky_irr", "#b07a00", "sun", { borderDash: [5, 4], borderWidth: 1.5 }),
        line("Actual sunlight", "irradiation", Charts.color("--chart-sun"), "sun",
          { borderWidth: 1.5, fill: { target: 0, above: "transparent", below: "rgba(122, 135, 148, 0.28)" } }),
        line("Actual power (kW)", "plant_actual_kw", Charts.color("--chart-actual"), "power"),
        line("Expected power (kW)", "plant_expected_kw", Charts.color("--chart-expected"), "power", { borderDash: [6, 4] }),
      ],
    },
    options: Charts.skyStripOptions({
      interaction: { mode: "index", intersect: false },
      scales: {
        x: Charts.axis("Time of day", { ticks: { maxTicksLimit: 10 } }),
        power: Charts.axis("Plant AC power (kW)", { position: "left", beginAtZero: true }),
        sun: Charts.axis("Sunlight (kW/m²)", { position: "right", beginAtZero: true, grid: { drawOnChartArea: false } }),
      },
      plugins: { tooltip: { callbacks: {
        label: (ctx) => (ctx.dataset.yAxisID === "sun" ? `${ctx.dataset.label}: ${fmt.number(ctx.parsed.y, 2)} kW/m²`
          : `${ctx.dataset.label.replace(" (kW)", "")}: ${fmt.number(ctx.parsed.y)} kW`),
        afterBody: (items) => { const p = points[items[0].dataIndex];
          return p.sky_label ? `Sky: ${p.sky_label} (clear-sky index ${fmt.number(p.clear_sky_index, 2)})` : ""; },
      } } },
    }),
    plugins: [Charts.skyStrip(points.map((p) => p.sky_label))],
  });
}

/** One stacked bar = the clear-sky potential, cut into where the energy went (top: losses, bottom: actual). */
function renderWaterfall({ steps, label, natural_loss_kwh: natural, fixable_loss_kwh: fixable, fixable_inr }) {
  document.getElementById("waterfall-title").textContent =
    `${label}: clouds + heat cost ${fmt.kwh(natural)} (natural), faults ${fmt.kwh(fixable)} (fixable)`;
  const potential = steps.find((s) => s.part === "clear_sky_potential");
  // "Not measured" and "Other" are both unknown: shown as one small slice. Negative "other" is left out.
  const unknown = steps.filter((s) => s.kind === "unknown" && s.kwh > 0)
    .reduce((sum, s) => ({ kwh: sum.kwh + s.kwh, pct: sum.pct + s.pct_of_potential }), { kwh: 0, pct: 0 });
  const slices = [
    ...["cloud_loss", "heat_loss", "fault_loss"].map((part) => steps.find((s) => s.part === part)),
    { part: "unknown", kwh: unknown.kwh, pct_of_potential: unknown.pct },
    steps.find((s) => s.part === "actual"),
  ].filter((s) => s && s.kwh > 0);
  const names = { cloud_loss: "Cloud cost", heat_loss: "Heat cost", fault_loss: "Fault cost",
    unknown: "Not measured / other", actual: "Actual energy generated" };
  const tips = { ...WATERFALL_TIPS, unknown: `${WATERFALL_TIPS.not_measured} ${WATERFALL_TIPS.other}` };

  const rows = slices.map((s) => {
    const share = `${fmt.number(s.pct_of_potential, 1)}%`;
    const text = s.part === "fault_loss"
      ? `<span class="ws-callout"><strong>Fixable loss: ${fmt.kwh(s.kwh)} (${fmt.inr(fixable_inr)})</strong>
         caused by faults our alerts found</span>`
      : `<span class="ws-name">${names[s.part]}:</span> ${fmt.kwh(s.kwh)} <span class="ws-pct">${share}</span>`;
    return `<div class="ws-row ws-item" data-part="${s.part}" tabindex="0" style="flex-grow: ${Math.max(s.pct_of_potential, 4)}"
        title="${escapeHTML(tips[s.part])}">
        <div class="ws-seg ws-${s.part}"></div><div class="ws-label ws-l-${s.part}"><span>${text}</span></div></div>`;
  }).join("");
  const stack = document.getElementById("waterfall-stack");
  stack.innerHTML = `
    <div class="ws-top ws-item" data-part="potential" tabindex="0" title="${escapeHTML(WATERFALL_TIPS.clear_sky_potential)}">
      <div class="ws-seg ws-potential"></div>
      <div class="ws-label ws-l-potential"><span>100% clear-sky potential (${fmt.kwh(potential.kwh)})</span></div></div>
    <div class="ws-body">${rows}</div>`;
  highlightSlice(stack, null);
}

/** Hover / tap / Tab on a slice (or its label): that slice pops out with a line to its label, the rest fade.
 *  With nothing pointed at, the fixable (red) slice stays highlighted — it is the one that matters. */
function highlightSlice(stack, item) {
  const target = item || stack.querySelector('.ws-item[data-part="fault_loss"]');
  stack.querySelectorAll(".ws-item").forEach((el) => el.classList.toggle("active", el === target));
  stack.classList.toggle("has-active", Boolean(target));
}

function initWaterfallHover() {
  const stack = document.getElementById("waterfall-stack");
  const pick = (event) => highlightSlice(stack, event.target.closest(".ws-item"));
  stack.addEventListener("pointerover", pick);
  stack.addEventListener("focusin", pick);
  stack.addEventListener("click", pick);   // phones: tap a slice to select it
  stack.addEventListener("pointerleave", (event) => { if (event.pointerType === "mouse") highlightSlice(stack, null); });
  stack.addEventListener("focusout", (event) => { if (!stack.contains(event.relatedTarget)) highlightSlice(stack, null); });
}

function renderTempChart(data) {
  const points = data.points, d = data.day;
  document.getElementById("temp-title").textContent =
    `Panels peaked at ${fmt.number(d.max_module_c)} °C — heat cost ${fmt.kwh(d.heat_loss_kwh)} (${fmt.number(d.heat_loss_pct, 1)}%)`;
  const hot = points.map((p) => p.is_hot_hour === true);
  Charts.draw("temp-chart", {
    type: "line",
    data: {
      labels: points.map((p) => fmt.time(p.timestamp)),
      datasets: [
        { label: "Panel temperature (°C)", data: points.map((p) => p.module_temp), borderColor: Charts.color("--high"),
          backgroundColor: Charts.color("--high"), borderWidth: 2, pointRadius: 0, tension: 0.25 },
        { label: "Air temperature (°C)", data: points.map((p) => p.ambient_temp), borderColor: Charts.color("--chart-sun"),
          backgroundColor: Charts.color("--chart-sun"), borderWidth: 2, pointRadius: 0, tension: 0.25 },
      ],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      scales: { x: Charts.axis("Time of day", { ticks: { maxTicksLimit: 10 } }), y: Charts.axis("Temperature (°C)") },
      plugins: { tooltip: { callbacks: {
        label: (ctx) => `${ctx.dataset.label.replace(" (°C)", "")}: ${fmt.number(ctx.parsed.y, 1)} °C`,
        afterBody: (items) => { const p = points[items[0].dataIndex];
          return p.heat_loss_kw > 0 ? `Heat cost now: ${fmt.number(p.heat_loss_kw)} kW` : ""; },
      } } },
    },
    plugins: [Charts.shade(Charts.rangesFromFlags(hot, "rgba(234, 88, 12, 0.12)"))],
  });
}

/** Verdict card: was this day's loss bad luck (clouds + heat) or something to fix (faults)? Answers in one look. */
function renderVerdict(day, overview) {
  const natural = day.natural_loss_kwh, fixable = day.fixable_loss_kwh;
  const inverters = overview.inverters_needing_attention;
  const verdict = fixable <= 0
    ? { css: "ok", title: "The weather: nothing to fix", line: "No energy was lost to faults on this day." }
    : fixable >= natural
      ? { css: "bad", title: "Mostly the plant: fix it", line: "Faults cost more than the weather did." }
      : { css: "warn", title: "Mostly the weather", line: "But part of the loss is still fixable." };
  const plural = inverters === 1 ? "inverter that needs" : "inverters that need";
  const action = inverters > 0
    ? `<a class="verdict-action" href="alerts.html?plant=${overview.plant}">See the ${fmt.number(inverters)} ${plural} attention →</a>`
    : "";
  document.getElementById("verdict").className = `card verdict ${verdict.css}`;
  document.getElementById("verdict").innerHTML = `
    <h2>Weather or the plant?</h2>
    <p class="card-sub">What caused this day's lost energy, and is any of it ours to fix?</p>
    <div class="verdict-title">${verdict.title}</div>
    <p class="verdict-line">${verdict.line}</p>
    <div class="verdict-split">
      <div><span class="kpi-label">Weather (clouds + heat)</span><strong>${fmt.kwh(natural)}</strong>
        <span class="verdict-note">natural · can't be fixed</span></div>
      <div><span class="kpi-label">Faults</span><strong class="${fixable > 0 ? "fix" : ""}">${fmt.kwh(fixable)}</strong>
        <span class="verdict-note">${fixable > 0 ? `${fmt.inr(day.day.fault_loss_inr)} · fixable` : "fixable · none today"}</span></div>
    </div>
    ${action}`;
}

function renderCalendar(calendar, selectedDate) {
  const counts = calendar.days_by_sky;
  document.getElementById("calendar-title").textContent = `Weather calendar — ${calendar.sky_labels
    .map((label) => `${counts[label]} ${label.toLowerCase()}`).join(", ")} days`;
  document.getElementById("calendar").innerHTML = calendar.days.map((d) => {
    const sky = SKY[d.dominant_sky] || { icon: "–", color: "var(--border)" };
    return `<button class="cal-tile${d.date === selectedDate ? " selected" : ""}" data-date="${d.date}"
        style="border-left-color: ${sky.color}" title="${escapeHTML(d.summary)}">
      <span class="cal-date">${fmt.date(d.date).slice(0, 6)}</span>
      <span class="cal-sky">${sky.icon} <strong>${fmt.number(d.sunshine_score)}</strong></span>
      <span class="cal-meta">${fmt.number(d.max_module_c)} °C · ${fmt.number(d.actual_kwh / 1000)} MWh</span>
    </button>`;
  }).join("");
  document.querySelectorAll(".cal-tile").forEach((tile) => tile.addEventListener("click", () => goToDate(tile.dataset.date)));
}

/** Open another day: change the shared date selector, which reloads the page data (layout.js). */
function goToDate(date) {
  const select = document.getElementById("date-select");
  select.value = date;
  select.dispatchEvent(new Event("change"));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setWaterfallMode(mode) {
  waterfallMode = mode;
  document.getElementById("wf-day").setAttribute("aria-pressed", mode === "day");
  document.getElementById("wf-period").setAttribute("aria-pressed", mode === "period");
  if (weatherData) renderWeather(weatherData);
}

initWaterfallHover();
document.getElementById("wf-day").addEventListener("click", () => setWaterfallMode("day"));
document.getElementById("wf-period").addEventListener("click", () => setWaterfallMode("period"));
window.addEventListener("themechange", () => { if (weatherData) renderWeather(weatherData); });
Layout.init("weather", loadWeather);
