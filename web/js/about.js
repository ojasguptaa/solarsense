// About page: fills in the live assumptions list and the number of days from the API.

async function loadAbout(state) {
  try {
    const [assumptions, settings] = await Promise.all([fetchJSON("/api/assumptions"), fetchJSON("/api/settings")]);
    clearError();
    document.getElementById("assumptions").innerHTML = assumptions.map((a) => `
      <tr>
        <td><strong>${escapeHTML(a.title)}</strong></td>
        <td style="white-space: nowrap">${escapeHTML(a.value)} ${escapeHTML(a.unit)}</td>
        <td>${escapeHTML(a.why)}</td>
        <td class="muted">${escapeHTML(a.source)}</td>
      </tr>`).join("");
    document.getElementById("lim-small").textContent =
      `Small underperformance (output dropping by less than ${fmt.number(settings.underperformance_drop_pct)}% ` +
      "below expected) is usually not caught, by design, to avoid false alarms.";
    if (state) {
      document.getElementById("lim-days").textContent =
        `Only ${state.dates.length} days of data (${fmt.date(state.dates[0])} – ${fmt.date(state.dates[state.dates.length - 1])}), ` +
        "all in one season; accuracy in winter or monsoon is unknown.";
    }
  } catch (error) {
    showError(error.message);
  }
}

/** Headline numbers at the top: every one comes from the computed results (losses, alerts, validation). */
async function loadHeadline(state) {
  try {
    // Per-plant losses are added up here because the static demo copy saves them per plant.
    const [validation, alerts, ...losses] = await Promise.all([
      fetchJSON("/api/validation"), fetchJSON("/api/alerts", { sort: "severity" }),
      ...state.plants.map((plant) => fetchJSON("/api/losses", { plant }))]);
    const sum = (key) => losses.reduce((total, plant) => total + plant.total[key], 0);
    const set = (id, html) => { document.getElementById(id).innerHTML = html; };

    set("stat-loss", `${fmt.number(sum("fault_loss_kwh"))}<span class="unit">kWh</span>`);
    set("stat-loss-inr", `≈ ${fmt.inr(sum("fault_loss_inr"))} in ${losses[0].days} days`);
    const critical = alerts.alerts.filter((a) => a.severity === "Critical").length;
    set("stat-alerts", fmt.number(alerts.count));
    set("stat-alerts-sub", `${fmt.number(critical)} of them critical`);
    set("stat-year", fmt.inr(sum("projected_annual_fault_loss_inr")));

    const trip = validation.by_fault && validation.by_fault.trip;
    if (trip) {
      set("stat-trip", `${fmt.number(trip.recall_pct)}<span class="unit">%</span>`);
      set("stat-trip-sub", `of ${trip.injections} planted · ${trip.false_alarms} false alarms · ~${fmt.number(trip.avg_delay_minutes)} min to alert`);
    }
    set("stat-note", `Measured on ${state.plants.length} real Indian solar plants (Kaggle "Solar Power Generation Data"). ` +
      `${escapeHTML(losses[0].tariff_note)}`);
  } catch (error) {
    showError(error.message);
  }
}

Layout.init("about").then((state) => Promise.all([loadAbout(state), loadHeadline(state)]));
