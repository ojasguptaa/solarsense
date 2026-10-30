// Service worker: what makes SolarSense an installable app (PWA).
// It keeps a copy of the app's screens (HTML, CSS, JS, icons) so the app opens quickly.
// Plant data (/api/... and the static copy's static-api/...) is NEVER stored here: always fresh from the server.
// Change CACHE_VERSION after editing the website so installed apps pick up the new files.

const CACHE_VERSION = "solarsense-v15";
const APP_SHELL = [
  "index.html", "plant.html", "weather.html", "inverter.html", "alerts.html", "about.html", "login.html",
  "css/style.css", "css/about.css", "css/chat.css", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png",
  "js/mode.js", "js/api.js", "js/layout.js", "js/charts.js", "js/chat.js",
  "js/plant3d.js", "js/plant3d_models.js", "js/plant3d_shapes.js", "js/plant3d_camera.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_VERSION).then((cache) => cache.addAll(APP_SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {   // delete copies from older versions
  event.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.includes("/api/") || url.pathname.includes("static-api/")) {
    return;   // data and logins: straight to the network, never cached
  }
  // Network first (always the newest screen); the saved copy is only used when the network fails.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok && !response.redirected && url.origin === location.origin) {
          const copy = response.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request)));
});
