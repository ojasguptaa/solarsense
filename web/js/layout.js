// Builds the shared top bar on every page and remembers the chosen plant, date and theme.

const PAGES = [
  { key: "overview", label: "Overview", href: "index.html" },
  { key: "plant", label: "Plant", href: "plant.html" },
  { key: "weather", label: "Weather & Energy", href: "weather.html" },
  { key: "inverter", label: "Inverters", href: "inverter.html" },
  { key: "alerts", label: "Alerts", href: "alerts.html" },
  { key: "about", label: "About", href: "about.html" },
];

const SUN_LOGO = `
  <svg viewBox="0 0 32 32" aria-hidden="true">
    <circle cx="16" cy="16" r="6.5" fill="#f59e0b"/>
    <g stroke="#f59e0b" stroke-width="2.4" stroke-linecap="round">
      <line x1="16" y1="2.5" x2="16" y2="6"/><line x1="16" y1="26" x2="16" y2="29.5"/>
      <line x1="2.5" y1="16" x2="6" y2="16"/><line x1="26" y1="16" x2="29.5" y2="16"/>
      <line x1="6.5" y1="6.5" x2="8.9" y2="8.9"/><line x1="23.1" y1="23.1" x2="25.5" y2="25.5"/>
      <line x1="6.5" y1="25.5" x2="8.9" y2="23.1"/><line x1="23.1" y1="8.9" x2="25.5" y2="6.5"/>
    </g>
  </svg>`;

// localStorage can be blocked (private windows, strict settings) — never let that break the page.
const storage = {
  get(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } },
  set(key, value) { try { window.localStorage.setItem(key, value); } catch (e) { /* not saved — fine */ } },
};
// Same idea, but forgotten when the browser tab closes (used for the replay date).
const session = {
  get(key) { try { return window.sessionStorage.getItem(key); } catch (e) { return null; } },
  set(key, value) { try { window.sessionStorage.setItem(key, value); } catch (e) { /* not saved — fine */ } },
};

function applySavedTheme() {
  const theme = storage.get("solarsense-theme");
  if (theme) document.documentElement.setAttribute("data-theme", theme);
}
applySavedTheme();   // run immediately so the page does not flash the wrong theme

// Installable app (PWA): register the service worker (web/sw.js) and remember the browser's install offer.
let installPrompt = null;
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => { /* app still works */ }));
}
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();   // show OUR "Install app" button instead of the browser's mini bar
  installPrompt = event;
  window.dispatchEvent(new Event("solarsense-can-install"));
});
window.addEventListener("appinstalled", () => {
  const button = document.getElementById("install-app");
  if (button) button.hidden = true;
});

// Static demo copy has no server to check logins, so pages check the browser tab's memory instead.
// (The live site is protected by the server: api/auth.py.) Not secure — for the demo only.
if (STATIC_SITE && !window.location.pathname.endsWith("login.html") && !session.get("solarsense-user")) {
  goToLogin();
}

const Layout = {
  state: { plant: null, date: null, plants: [], dates: [] },

  /** Draw the top bar, load plants/dates, then call onChange(state) now and whenever a selector changes. */
  async init(activePage, onChange = null) {
    const header = document.getElementById("topbar");
    header.className = "topbar";
    header.innerHTML = `
      <a class="brand" href="index.html">${SUN_LOGO}<span>SolarSense</span></a>
      <nav class="nav" aria-label="Main">
        ${PAGES.map((p) => `<a href="${p.href}" class="${p.key === activePage ? "active" : ""}">${p.label}</a>`).join("")}
      </nav>
      <div class="controls">
        <label for="plant-select">Plant</label>
        <select id="plant-select" aria-label="Plant"></select>
        <label for="date-select">Replay date</label>
        <select id="date-select" aria-label="Replay date"></select>
        <button id="theme-toggle" class="icon-btn" title="Switch light / dark theme" aria-label="Switch theme">◐</button>
        <button id="install-app" class="icon-btn install-btn" type="button" hidden>⬇ Install app</button>
        <span class="user-box"><span id="user-name"></span>
          <button id="logout" class="link-btn" type="button">Log out</button></span>
      </div>`;
    document.getElementById("theme-toggle").addEventListener("click", Layout.toggleTheme);
    document.getElementById("logout").addEventListener("click", Layout.logOut);
    Layout.showUser();
    Layout.setUpInstallButton();
    Layout.loadAssistant();

    let info;
    try {
      info = await fetchJSON("/api/plants");
    } catch (error) {
      showError(error.message);
      return null;
    }
    const state = Layout.state;
    state.plants = info.plants.map((p) => p.plant);
    state.dates = info.dates;
    // Each plant's highest-loss day is its default replay date (the most useful day to look at).
    const worstDay = Object.fromEntries(info.plants.map((p) => [p.plant, p.worst_loss_date]));

    // Plant: URL (?plant=2) → remembered → default.
    // Date: URL (?date=…) → chosen earlier in THIS browser session → the plant's highest-loss day.
    const url = new URLSearchParams(window.location.search);
    const savedPlant = Number(url.get("plant") || storage.get("solarsense-plant"));
    state.plant = state.plants.includes(savedPlant) ? savedPlant : info.default_plant;
    const savedDate = url.get("date") || session.get(`solarsense-date-${state.plant}`);
    state.date = state.dates.includes(savedDate) ? savedDate : worstDay[state.plant];
    if (url.get("date") === state.date) session.set(`solarsense-date-${state.plant}`, state.date);

    const plantSelect = document.getElementById("plant-select");
    const dateSelect = document.getElementById("date-select");
    plantSelect.innerHTML = info.plants
      .map((p) => `<option value="${p.plant}">Plant ${p.plant} (${p.inverters} inverters)</option>`).join("");
    const fillDates = () => {
      dateSelect.innerHTML = state.dates.map((d) =>
        `<option value="${d}">${fmt.date(d)}${d === worstDay[state.plant] ? " (highest loss)" : ""}</option>`).join("");
      dateSelect.value = state.date;
    };
    plantSelect.value = state.plant;
    fillDates();

    plantSelect.addEventListener("change", () => {
      state.plant = Number(plantSelect.value);
      storage.set("solarsense-plant", state.plant);
      // A new plant opens on its own highest-loss day (unless a day was already picked for it this session).
      const picked = session.get(`solarsense-date-${state.plant}`);
      state.date = state.dates.includes(picked) ? picked : worstDay[state.plant];
      fillDates();
      if (onChange) onChange(state);
    });
    dateSelect.addEventListener("change", () => {
      state.date = dateSelect.value;
      session.set(`solarsense-date-${state.plant}`, state.date);
      if (onChange) onChange(state);
    });
    if (onChange) onChange(state);
    return state;
  },

  /** "Signed in as operator" in the top bar (the static copy remembers the name in this tab only). */
  async showUser() {
    let username = STATIC_SITE ? session.get("solarsense-user") : null;
    if (!STATIC_SITE) {
      try { username = (await fetchJSON("/api/me")).username; } catch (e) { return; }
    }
    if (username) document.getElementById("user-name").textContent = `Signed in as ${username}`;
  },

  /** Forget the session (server cookie, or the static copy's tab memory) and go to the login page. */
  async logOut() {
    if (STATIC_SITE) {
      try { window.sessionStorage.removeItem("solarsense-user"); } catch (e) { /* nothing saved */ }
    } else {
      try { await fetch("api/logout", { method: "POST" }); } catch (e) { /* offline: still leave */ }
    }
    window.location.href = "login.html";
  },

  /** Show "Install app" when the browser can install SolarSense; on iPhone explain the Share menu instead. */
  setUpInstallButton() {
    const button = document.getElementById("install-app");
    const installed = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;
    if (installed) return;   // already running as an installed app
    if (installPrompt) button.hidden = false;
    window.addEventListener("solarsense-can-install", () => { button.hidden = false; });
    if (/iphone|ipad/i.test(navigator.userAgent)) {   // Safari has no install button: show a tip
      button.hidden = false;
      button.addEventListener("click", () => alert("To install: tap Share, then \"Add to Home Screen\"."));
      return;
    }
    button.addEventListener("click", async () => {
      if (!installPrompt) return;
      installPrompt.prompt();
      await installPrompt.userChoice;
      installPrompt = null;
      button.hidden = true;
    });
  },

  /** Add the chat assistant (web/js/chat.js) to every page, without editing each HTML file. */
  loadAssistant() {
    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = "css/chat.css";
    document.head.appendChild(style);
    const load = (src) => new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.onload = resolve;
      script.onerror = reject;
      document.body.appendChild(script);
    });
    load("js/chat.js").then(() => Chat.mount()).catch(() => {});
  },

  toggleTheme() {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    const next = dark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    storage.set("solarsense-theme", next);
    window.dispatchEvent(new Event("themechange"));   // charts redraw with the new colours
  },
};
