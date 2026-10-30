// About page, "Our AI models": headline numbers, the classifier's confusion table and the retraining chart.

const AI_LABELS = { healthy: "Healthy", trip: "Trip", underperformance: "Under-perf.", data_gap: "Data gap",
  soiling: "Soiling", overheating: "Overheating" };

/** Planted fault (rows) vs AI answer (columns); the diagonal = correct answers. */
function confusionTable(matrix) {
  const head = `<tr><th>Planted ↓ / AI said →</th>${matrix.labels.map((l) => `<th>${AI_LABELS[l]}</th>`).join("")}</tr>`;
  const rows = matrix.counts.map((row, i) => `<tr><th>${AI_LABELS[matrix.labels[i]]}</th>${row.map((n, j) =>
    `<td style="${i === j ? "font-weight:700;color:var(--ok, #16a34a)" : n ? "color:var(--bad, #dc2626)" : "opacity:.4"}">${fmt.number(n)}</td>`).join("")}</tr>`);
  return `<thead>${head}</thead><tbody>${rows.join("")}</tbody>`;
}

async function loadAIModels() {
  try {
    const ai = await fetchJSON("/api/ai_models");
    const set = (id, html) => { document.getElementById(id).innerHTML = html; };
    const p1 = ai.expected_model.plant_1;
    if (p1) set("ai-r2", fmt.number(p1[p1.chosen_model].test_all.r2, 2));

    const fc = ai.fault_classifier;
    if (fc) {
      set("ai-acc", `${fmt.number(fc.test_accuracy_pct, 1)}<span class="unit">%</span>`);
      set("ai-acc-sub", `${fmt.number(fc.test_examples)} planted faults from later days, ${fc.classes.length} types`);
      set("ai-confusion", confusionTable(fc.confusion_matrix));
      set("ai-real", `On the ${fmt.number(fc.real_alerts.alerts_checked)} real alerts, the AI agrees with the rule-based fault type ` +
        `${fmt.number(fc.real_alerts.agree_pct, 1)}% of the time; where it disagrees, the alert shows "worth a closer look". ` +
        escapeHTML(fc.caveat));
    }

    const mu = ai.model_updates;
    if (mu) {
      const plant = mu.by_plant.plant_1;
      set("ai-upd", `${fmt.number(plant.error_reduction_pct, 1)}<span class="unit">%</span>`);
      set("ai-upd-sub", `Plant 1: error ${fmt.number(plant.avg_error_trained_once_pct, 1)}% → ${fmt.number(plant.avg_error_retrained_pct, 1)}% ` +
        `(Plant 2: ${fmt.number(mu.by_plant.plant_2.error_reduction_pct, 1)}% better)`);
      set("ai-caveat", escapeHTML(mu.method));
      new Chart(document.getElementById("ai-updates-chart"), {
        type: "line",
        data: { labels: plant.days.map((d) => fmt.date(d.date)), datasets: [
          { label: "Trained once (first days only)", data: plant.days.map((d) => d.trained_once_error_pct), borderColor: "#94a3b8", tension: 0.3 },
          { label: "Retrained every day", data: plant.days.map((d) => d.retrained_error_pct), borderColor: "#f59e0b", tension: 0.3 }] },
        options: { maintainAspectRatio: false, plugins: { title: { display: true, text: "Plant 1: prediction error on each new day (lower is better)" },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y}%` } } },
          scales: { y: { title: { display: true, text: "Error (% of average output)" } }, x: { title: { display: true, text: "Day predicted" } } } },
      });
    }
  } catch (error) {
    showError(error.message);
  }
}
