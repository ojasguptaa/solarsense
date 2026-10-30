// Alerts page: filterable, sortable, searchable alert table with CSV export.
// Clicking a row opens the detail panel (alert_panel.js).

const PAGE_SIZE = 50;
const SEVERITY_ORDER = { Critical: 3, High: 2, Medium: 1, Low: 0 };
const page = { all: [], shown: PAGE_SIZE, sort: "severity", state: null };
const urlParams = new URLSearchParams(window.location.search);

const $ = (id) => document.getElementById(id);

async function loadAlerts(state) {
  page.state = state;
  try {
    const body = await fetchJSON("/api/alerts", { sort: "severity" });
    clearError();
    page.all = body.alerts;
    fillFilterOptions();
    render();
  } catch (error) {
    showError(error.message);
  }
}

function fillFilterOptions() {
  if ($("f-severity").options.length > 1) return;   // only once
  $("f-severity").innerHTML += SEVERITIES.map((s) => `<option>${s}</option>`).join("");
  const types = [...new Set(page.all.map((a) => a.fault_type))].sort();
  $("f-type").innerHTML += types.map((t) => `<option value="${t}">${fmt.fault(t)}</option>`).join("");
  $("f-plant").innerHTML += page.state.plants.map((p) => `<option value="${p}">Plant ${p}</option>`).join("");
  if (urlParams.get("plant")) $("f-plant").value = urlParams.get("plant");
  // Custom dates: limited to the days we have data for, starting as the whole period.
  const dates = page.state.dates;
  ["f-from", "f-to"].forEach((id) => { $(id).min = dates[0]; $(id).max = dates[dates.length - 1]; });
  $("f-from").value = dates[0];
  $("f-to").value = dates[dates.length - 1];
  fillInverterOptions();
  if (urlParams.get("inverter")) $("f-inverter").value = urlParams.get("inverter");
}

/** Inverter dropdown: only the inverters of the chosen plant (all plants: every inverter, with its plant). */
function fillInverterOptions() {
  const plant = $("f-plant").value, keep = $("f-inverter").value;
  const seen = new Map();
  page.all.filter((a) => !plant || String(a.plant) === plant)
    .forEach((a) => seen.set(`${a.plant}|${a.inverter}`, a));
  const options = [...seen.values()]
    .sort((x, y) => x.plant - y.plant || (x.inverter === "ALL") - (y.inverter === "ALL") || x.inverter.localeCompare(y.inverter))
    .map((a) => {
      const name = a.inverter === "ALL" ? "Whole plant" : a.inverter;
      return `<option value="${escapeHTML(a.inverter)}">${plant ? "" : `Plant ${a.plant} · `}${escapeHTML(name)}</option>`;
    });
  $("f-inverter").innerHTML = `<option value="">All inverters</option>${options.join("")}`;
  $("f-inverter").value = [...$("f-inverter").options].some((o) => o.value === keep) ? keep : "";
}

/** The day after a YYYY-MM-DD date (ranges include the whole "To" day). */
function nextDay(day) {
  const next = new Date(`${day}T00:00:00Z`);
  next.setUTCDate(next.getUTCDate() + 1);
  return next.toISOString().slice(0, 10);
}

/** Does the alert fall inside the chosen dates? (any overlap counts) */
function inChosenDates(a) {
  const when = $("f-when").value;
  if (when === "day") return alertOverlapsDay(a, page.state.date);
  if (when !== "custom") return true;
  let from = $("f-from").value || page.state.dates[0], to = $("f-to").value || page.state.dates[page.state.dates.length - 1];
  if (from > to) [from, to] = [to, from];   // picked backwards: still works
  return a.start < `${nextDay(to)}T00:00:00` && a.end > `${from}T00:00:00`;
}

/** Apply every filter, the search box and the chosen sort order. */
function filteredAlerts() {
  const plant = $("f-plant").value, severity = $("f-severity").value, type = $("f-type").value;
  const status = $("f-status").value, inverter = $("f-inverter").value;
  const search = $("f-search").value.trim().toLowerCase();
  const rows = page.all.filter((a) =>
    (!plant || String(a.plant) === plant) && (!severity || a.severity === severity) && (!type || a.fault_type === type)
    && (!status || (status === "Active" ? a.status !== "Resolved" : a.status === status))
    && (!inverter || a.inverter === inverter) && inChosenDates(a)
    && (!search || `${a.id} ${a.inverter} ${a.reason}`.toLowerCase().includes(search)));
  const impact = (a) => a.energy_loss_kwh + a.energy_at_risk_kwh;
  const sorters = {
    severity: (a, b) => SEVERITY_ORDER[b.severity] - SEVERITY_ORDER[a.severity] || impact(b) - impact(a),
    loss: (a, b) => b.energy_loss_kwh - a.energy_loss_kwh || b.energy_at_risk_kwh - a.energy_at_risk_kwh,
    time: (a, b) => (a.start < b.start ? 1 : -1),
  };
  return rows.sort(sorters[page.sort]);
}

function render() {
  const rows = filteredAlerts();
  const lost = rows.reduce((sum, a) => sum + a.energy_loss_kwh, 0);
  const money = rows.reduce((sum, a) => sum + a.money_loss_inr, 0);
  const critical = rows.filter((a) => a.severity === "Critical").length;
  $("takeaway").textContent = `${rows.length} alerts match — ${critical} critical, ${fmt.kwh(lost)} lost (${fmt.inr(money)}, ${TARIFF_LABEL}).`;

  $("alert-rows").innerHTML = rows.slice(0, page.shown).map((a) => `
    <tr class="clickable" data-id="${escapeHTML(a.id)}" tabindex="0">
      <td>${severityBadge(a.severity)}</td>
      <td><strong>${fmt.fault(a.fault_type)}</strong><div class="muted">${escapeHTML(a.id)}</div></td>
      <td>Plant ${a.plant}<div class="muted">${a.inverter === "ALL" ? "whole plant" : escapeHTML(a.inverter)}</div></td>
      <td>${fmt.date(a.start)}<div class="muted">${fmt.time(a.start)}</div></td>
      <td class="num">${a.duration_hours > 24 ? "whole period" : `${fmt.number(a.duration_hours, 2)} h`}</td>
      <td class="num">${a.energy_at_risk_kwh > 0 ? `<span class="muted">${fmt.kwh(a.energy_at_risk_kwh)} at risk</span>` : fmt.kwh(a.energy_loss_kwh)}</td>
      <td class="num">${fmt.inr(a.money_loss_inr)}</td>
      <td><span class="status ${a.status}">${a.status}</span></td>
    </tr>`).join("") || `<tr><td colspan="8" class="empty">No alerts match these filters.</td></tr>`;

  $("show-more").hidden = rows.length <= page.shown;
  $("row-count").textContent = `Showing ${Math.min(page.shown, rows.length)} of ${rows.length}`;
}

/** Download the filtered alerts as a CSV file (opens in Excel). */
function exportCsv() {
  const columns = ["id", "plant", "inverter", "fault_type", "severity", "status", "start", "end", "duration_hours",
                   "energy_loss_kwh", "energy_at_risk_kwh", "money_loss_inr", "money_at_risk_inr", "reason", "recommended_action"];
  const quote = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const lines = [columns.join(",")].concat(filteredAlerts().map((a) => columns.map((c) => quote(a[c])).join(",")));
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });   // BOM so Excel shows ₹
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "solarsense_alerts.csv";
  link.click();
  URL.revokeObjectURL(link.href);
}

/** Called by the panel after Acknowledge / Resolve, so the table updates without reloading. */
function onStatusChanged(id, status) {
  const alert = page.all.find((a) => a.id === id);
  if (alert) alert.status = status;
  render();
}

// ---------- Wire up the controls ----------
["f-plant", "f-severity", "f-type", "f-status", "f-inverter", "f-when", "f-from", "f-to"].forEach((id) =>
  $(id).addEventListener("change", () => {
    if (id === "f-plant") fillInverterOptions();   // new plant: its own inverters first, then filter
    page.shown = PAGE_SIZE;
    render();
  }));
$("f-when").addEventListener("change", () => { $("f-range").hidden = $("f-when").value !== "custom"; });
["f-from", "f-to"].forEach((id) => $(id).addEventListener("change", () => {   // dates picked backwards: swap the boxes
  if ($("f-from").value && $("f-to").value && $("f-from").value > $("f-to").value) {
    [$("f-from").value, $("f-to").value] = [$("f-to").value, $("f-from").value];
  }
}, { capture: true }));
$("f-search").addEventListener("input", () => { page.shown = PAGE_SIZE; render(); });
$("show-more").addEventListener("click", () => { page.shown += PAGE_SIZE; render(); });
$("export-csv").addEventListener("click", exportCsv);
document.querySelectorAll("th.sortable").forEach((th) =>
  th.addEventListener("click", () => { page.sort = th.dataset.sort; render(); }));
$("alert-rows").addEventListener("click", (event) => {
  const row = event.target.closest("tr[data-id]");
  if (row) AlertPanel.open(row.dataset.id, onStatusChanged);
});
$("alert-rows").addEventListener("keydown", (event) => {
  const row = event.target.closest("tr[data-id]");
  if (row && event.key === "Enter") AlertPanel.open(row.dataset.id, onStatusChanged);
});

Layout.init("alerts", (state) => {
  if (page.all.length) {   // top-bar plant/date changed: follow the plant, then re-filter
    if (state.plant !== page.lastPlant) { $("f-plant").value = String(state.plant); fillInverterOptions(); }
    page.lastPlant = state.plant;
    render();
    return;
  }
  page.lastPlant = state.plant;
  loadAlerts(state).then(() => {
    if (urlParams.get("id")) AlertPanel.open(urlParams.get("id"), onStatusChanged);   // deep link from Overview
  });
});
