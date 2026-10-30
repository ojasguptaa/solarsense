// Live replay on the Overview page: plays the chosen day in 15-minute ticks so the demo feels like
// real-time monitoring. Every number comes precomputed from /api/replay — nothing is added up here.

const FINISH_HOLD_SECONDS = 3;   // after the last tick, the live fault list stays this long before the normal list returns

const Replay = {
  data: null, tick: 0, timer: null, active: false,

  async start() {
    const { plant, date } = Layout.state;
    try {
      Replay.data = await fetchJSON("/api/replay", { plant, date });
    } catch (error) {
      showError(error.message);
      return;
    }
    Replay.active = true;
    Replay.tick = 0;
    Replay.setButtons(true);
    Replay.clearAttention();
    // Draw the full-day chart frame once, then reveal it tick by tick.
    renderDayChart({ performance_ratio: null }, { points: Replay.data.ticks });
    Replay.play();
  },

  play() {
    clearInterval(Replay.timer);
    const speed = Number(document.getElementById("replay-speed").value);
    Replay.timer = setInterval(Replay.step, 1000 / speed);
    document.getElementById("replay-pause").textContent = "Pause";
  },

  togglePause() {
    if (Replay.timer) {
      clearInterval(Replay.timer);
      Replay.timer = null;
      document.getElementById("replay-pause").textContent = "Resume";
    } else {
      Replay.play();
    }
  },

  /** Stop the replay. restore = true puts the normal full-day view back. */
  stop(restore = true) {
    clearInterval(Replay.timer);
    Replay.timer = null;
    if (!Replay.active) return;
    Replay.active = false;
    Replay.setButtons(false);
    if (plant3d) plant3d.resetSun();
    if (restore && lastData) renderAll(lastData);
  },

  step() {
    const ticks = Replay.data.ticks;
    if (Replay.tick >= ticks.length) {
      clearInterval(Replay.timer);
      Replay.timer = null;
      document.getElementById("replay-pause").hidden = true;
      document.getElementById("takeaway").textContent += " — replay finished.";
      // Hold the live fault list a moment, then put the normal "Needs attention" list back.
      const finished = Replay.data;
      setTimeout(() => {
        if (Replay.data === finished && !Replay.timer && lastData) renderAttention(lastData.attention);
      }, FINISH_HOLD_SECONDS * 1000);
      return;
    }
    Replay.show(Replay.tick);
    Replay.data.events.filter((e) => e.tick === Replay.tick).forEach(Replay.addAttention);
    Replay.tick += 1;
  },

  /** "Needs attention" during replay: starts empty, and each fault appears at the moment it starts. */
  clearAttention() {
    document.getElementById("attention-title").textContent = "Live: faults so far";
    document.getElementById("attention-sub").textContent = "Each fault appears here the moment it starts in the replay, newest first.";
    const list = document.getElementById("attention");
    list.classList.add("live");
    list.innerHTML = `<li class="empty">No faults yet — watching the plant…</li>`;
  },

  addAttention(event) {
    const list = document.getElementById("attention");
    list.querySelector(".empty")?.remove();
    const where = event.inverter === "ALL" ? "Whole plant" : `Inverter ${escapeHTML(event.inverter)}`;
    const item = document.createElement("li");
    item.className = "live-new";
    item.innerHTML = `<a href="alerts.html?id=${encodeURIComponent(event.id)}">
        <div class="list-title">${severityBadge(event.severity)} ${fmt.fault(event.fault_type)}</div>
        <div class="list-meta">${where} · started ${fmt.time(event.start)}</div></a>`;
    list.prepend(item);
  },

  show(i) {
    const { ticks, tariff_inr_per_kwh, tariff_note } = Replay.data;
    const t = ticks[i];
    renderKpis({ ...t, tariff_inr_per_kwh, tariff_note });
    const sky = t.sky_label && SKY[t.sky_label] ? `${SKY[t.sky_label].icon} ${t.sky_label.toLowerCase()}` : "";
    const panel = t.module_temp_c === null || t.module_temp_c === undefined ? "" : `panels ${fmt.number(t.module_temp_c)} °C`;
    const weatherNow = [sky, panel].filter(Boolean).join(", ");
    document.getElementById("takeaway").innerHTML =
      `<span class="live-dot"></span>Live replay · ${fmt.time(t.timestamp)}${weatherNow ? ` · ${weatherNow}` : ""} — plant ` +
      `has made ${fmt.kwh(t.actual_kwh)} so far; ${fmt.kwh(t.fault_loss_kwh)} lost to faults so far.`;
    Replay.showWeather(t);
    if (plant3d) plant3d.setSun(t.timestamp, t.irradiation);   // the 3D sun moves with the replay clock
    const chart = Charts.instances["day-chart"];
    const upTo = (key) => ticks.map((p, j) => (j <= i ? p[key] : null));
    chart.data.datasets[0].data = upTo("actual_kw");
    chart.data.datasets[1].data = upTo("expected_kw");
    chart.data.datasets[2].data = upTo("irradiation");
    chart.update("none");
    document.getElementById("day-chart-title").textContent = `Live: ${fmt.time(t.timestamp)} — ${fmt.number(t.actual_kw)} kW now (expected ${fmt.number(t.expected_kw)} kW)`;
  },

  /** Weather mini-card during replay: the sky icon and panel temperature change every tick. */
  showWeather(t) {
    const icon = document.getElementById("wm-icon");
    if (!icon) return;   // no weather data for this plant/day
    icon.textContent = t.sky_label && SKY[t.sky_label] ? SKY[t.sky_label].icon : "🌙";
    document.getElementById("wm-sky-label").textContent = "Sky now";
    document.getElementById("wm-sky").textContent = t.sky_label || "too dark to judge";
    document.getElementById("wm-temp-label").textContent = "Panel temperature now";
    document.getElementById("wm-temp").textContent = t.module_temp_c === null ? "–" : `${fmt.number(t.module_temp_c)} °C`;
    // Weather vs fault cost grow with the graph; at the last tick they equal the day's totals.
    if (t.natural_loss_kwh !== null && t.natural_loss_kwh !== undefined) {
      document.getElementById("wm-natural-label").textContent = "Weather cost so far (natural)";
      document.getElementById("wm-natural").textContent = fmt.kwh(t.natural_loss_kwh);
    }
    document.getElementById("wm-fixable-label").textContent = "Faults cost so far (fixable)";
    document.getElementById("wm-fixable").textContent = fmt.kwh(t.fault_loss_kwh);
  },

  setButtons(playing) {
    document.getElementById("replay-start").hidden = playing;
    ["replay-pause", "replay-speed", "replay-stop"].forEach((id) => { document.getElementById(id).hidden = !playing; });
  },
};

document.getElementById("replay-start").addEventListener("click", Replay.start);
document.getElementById("replay-pause").addEventListener("click", Replay.togglePause);
document.getElementById("replay-stop").addEventListener("click", () => Replay.stop(true));
document.getElementById("replay-speed").addEventListener("change", () => { if (Replay.timer) Replay.play(); });
