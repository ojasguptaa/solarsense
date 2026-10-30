// Plant page: daily actual vs expected over the whole period, inverter health heatmap, worst inverters.

let lastPlantData = null;   // kept so the chart can be redrawn when the theme changes

async function loadPlant(state) {
  try {
    const [daily, heatmap, losses] = await Promise.all([
      fetchJSON("/api/plant/daily", { plant: state.plant }),
      fetchJSON("/api/plant/heatmap", { plant: state.plant }),
      fetchJSON("/api/losses", { plant: state.plant }),
    ]);
    clearError();
    lastPlantData = { state, daily, heatmap, losses };
    renderPlant(lastPlantData);
  } catch (error) {
    showError(error.message);
  }
}

function renderPlant({ state, daily, heatmap, losses }) {
  const pr = daily.period_performance_ratio;
  const worstDay = daily.days.reduce((a, b) => (b.performance_ratio < a.performance_ratio ? b : a));
  document.getElementById("takeaway").textContent =
    `Plant ${state.plant}, actual vs expected over ${daily.days.length} days: ${fmt.pct(pr)}. ` +
    `Lowest day: ${fmt.date(worstDay.date)} (${fmt.pct(worstDay.performance_ratio)} of expected).`;
  renderDailyChart(daily);
  renderHeatmap(state, heatmap);
  renderWorst(state, losses);
}

function renderDailyChart(daily) {
  const days = daily.days;
  document.getElementById("daily-title").textContent =
    `${days.filter((d) => prStatus(d.performance_ratio) === "bad").length} of ${days.length} days below ${fmt.pct(PR_WARN)} of expected`;
  Charts.draw("daily-chart", {
    data: {
      labels: days.map((d) => fmt.date(d.date).slice(0, 6)),
      datasets: [
        { type: "line", label: "Actual vs expected (%)", data: days.map((d) => d.performance_ratio * 100),
          borderColor: Charts.color("--text"), backgroundColor: Charts.color("--text"), borderWidth: 2,
          pointRadius: 2, yAxisID: "pr" },
        { type: "bar", label: "Expected (kWh)", data: days.map((d) => d.expected_kwh),
          backgroundColor: Charts.color("--chart-expected"), yAxisID: "energy" },
        { type: "bar", label: "Actual (kWh)", data: days.map((d) => d.actual_kwh),
          backgroundColor: Charts.color("--chart-actual"), yAxisID: "energy" },
      ],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      scales: {
        x: Charts.axis("Day"),
        energy: Charts.axis("Energy per day (kWh)", { position: "left", beginAtZero: true }),
        pr: Charts.axis("Actual vs expected (%)", { position: "right", min: 0, max: 120, grid: { drawOnChartArea: false } }),
      },
      plugins: {
        tooltip: {
          callbacks: {
            label: (ctx) => ctx.dataset.yAxisID === "pr"
              ? `Actual vs expected: ${fmt.number(ctx.parsed.y, 1)}%`
              : `${ctx.dataset.label.replace(" (kWh)", "")}: ${fmt.kwh(ctx.parsed.y)}`,
            afterBody: (items) => {
              const loss = days[items[0].dataIndex].fault_loss_kwh;
              return loss > 0 ? `Lost to faults: ${fmt.kwh(loss)}` : "";
            },
          },
        },
      },
    },
  });
}

function renderHeatmap(state, heatmap) {
  const grid = document.getElementById("heatmap");
  grid.style.gridTemplateColumns = `130px repeat(${heatmap.dates.length}, minmax(14px, 1fr))`;
  const unhealthy = heatmap.inverters.filter((_, row) =>
    heatmap.performance_ratio[row].some((pr) => prStatus(pr) === "bad")).length;
  document.getElementById("heatmap-title").textContent =
    `${unhealthy} of ${heatmap.inverters.length} inverters had at least one problem day (< ${fmt.pct(PR_WARN)})`;

  const header = [`<div></div>`].concat(heatmap.dates.map((d, i) =>
    `<div class="hm-head">${i % 5 === 0 ? escapeHTML(fmt.date(d).slice(0, 6)) : ""}</div>`));
  const rows = heatmap.inverters.map((inverter, row) => {
    const cells = heatmap.dates.map((date, col) => {
      const pr = heatmap.performance_ratio[row][col];
      const loss = heatmap.fault_loss_kwh[row][col];
      const tip = `${inverter} · ${fmt.date(date)} · actual vs expected ${fmt.pct(pr)}${loss > 0 ? ` · lost ${fmt.kwh(loss)}` : ""}`;
      const selected = date === state.date ? " selected-day" : "";
      const href = `inverter.html?id=${encodeURIComponent(inverter)}&date=${date}&plant=${state.plant}`;
      return `<a class="hm-cell hm-${prStatus(pr)}${selected}" href="${href}" title="${escapeHTML(tip)}" aria-label="${escapeHTML(tip)}"></a>`;
    });
    return `<div class="hm-label" title="${escapeHTML(inverter)}">${escapeHTML(inverter)}</div>${cells.join("")}`;
  });
  grid.innerHTML = header.join("") + rows.join("");
  document.getElementById("hm-legend-ok").textContent = `≥ ${fmt.pct(PR_GOOD)} healthy`;
  document.getElementById("hm-legend-warn").textContent = `${fmt.pct(PR_WARN)}–${fmt.pct(PR_GOOD)} watch`;
  document.getElementById("hm-legend-bad").textContent = `< ${fmt.pct(PR_WARN)} problem`;
}

function renderWorst(state, losses) {
  document.getElementById("worst-title").textContent =
    `Top ${losses.top_inverters.length} inverters by energy lost (whole period)`;
  document.getElementById("worst").innerHTML = losses.top_inverters.map((row, i) => `
    <tr>
      <td>${i + 1}</td>
      <td><a href="inverter.html?id=${encodeURIComponent(row.inverter)}&plant=${state.plant}">${escapeHTML(row.inverter)}</a></td>
      <td class="num">${fmt.kwh(row.fault_loss_kwh)}</td>
      <td class="num">${fmt.inr(row.fault_loss_inr)}</td>
      <td class="num">${row.alerts}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="empty">No losses recorded</td></tr>`;
}

window.addEventListener("themechange", () => { if (lastPlantData) renderPlant(lastPlantData); });
Layout.init("plant", loadPlant);
