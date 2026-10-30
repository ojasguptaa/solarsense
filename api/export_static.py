"""Build a static copy of the dashboard for GitHub Pages (no Python server needed).

Run from the solarsense folder:   python -m api.export_static            (writes site/)
                                  python -m api.export_static OUT_FOLDER

It asks the REAL API every question the website can ask (every plant, date, inverter and alert) and saves
each answer as a JSON file, so the static copy shows exactly the same numbers as the live site.
The GitHub Action in .github/workflows/pages.yml runs this on every push and publishes the result.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from engine import config


def static_name(params):
    """File name for one request's parameters — must match staticFile() in web/js/api.js."""
    keys = sorted(params)
    return "__".join(f"{key}-{params[key]}" for key in keys) if keys else "index"


class Exporter:
    """Calls the API and saves every answer under OUT/static-api/."""

    def __init__(self, client, out):
        self.client, self.out, self.files, self.bytes = client, out, 0, 0

    def save(self, endpoint, params=None):
        """Ask the API one question (e.g. "overview", {"plant": "2"}) and save the JSON answer."""
        params = {key: str(value) for key, value in (params or {}).items()}
        response = self.client.get(f"/api/{endpoint}", params=params)
        if response.status_code != 200:
            raise RuntimeError(f"/api/{endpoint} {params} failed: {response.status_code} {response.text[:200]}")
        path = self.out / "static-api" / endpoint / f"{static_name(params)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(response.json(), ensure_ascii=False, separators=(",", ":"))
        path.write_text(text, encoding="utf-8")
        self.files += 1
        self.bytes += len(text.encode("utf-8"))
        return response.json()


def export(out):
    """Copy the website, switch it to static mode, and save every API answer it can ask for."""
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(config.WEB_DIR, out)
    (out / "js" / "mode.js").write_text(
        "// Static demo copy built by api/export_static.py — reads saved JSON files instead of the API.\n"
        "const STATIC_SITE = true;\n", encoding="utf-8")
    shutil.copytree(config.FIGURES_DIR, out / "figures")
    (out / ".nojekyll").write_text("", encoding="utf-8")   # tell GitHub Pages to serve files as they are

    # Every alert starts as "Open" in the public copy (ignore statuses changed on this laptop).
    config.ALERT_STATUS_FILE = Path(tempfile.mkdtemp()) / "alert_status.json"

    # The API needs a login: use a throwaway account in a temporary users file (never the real one).
    config.USERS_FILE = Path(tempfile.mkdtemp()) / "users.json"
    from engine.create_users import set_user
    set_user("exporter", "export-only")

    from api.main import app   # imported here so the temporary status file above is used
    with TestClient(app) as client:
        client.post("/api/login", json={"username": "exporter", "password": "export-only"})
        ex = Exporter(client, out)
        info = ex.save("plants")
        for name in ["validation", "assumptions", "settings", "ai_models"]:
            ex.save(name)
        everything = ex.save("alerts", {"sort": "severity"})          # Alerts page
        for alert in everything["alerts"]:
            ex.save(f"alerts/{alert['id']}")                           # "Why?" panel
        for plant in [p["plant"] for p in info["plants"]]:
            for name in ["losses", "plant/daily", "plant/heatmap", "weather/calendar", "weather/temperature",
                         "breakdown"]:
                ex.save(name, {"plant": plant})
            inverters = client.get("/api/plant/heatmap", params={"plant": plant}).json()["inverters"]
            for inverter in inverters:
                ex.save(f"inverter/{inverter}/sunlight")                    # power vs sunlight (all days)
            for date in info["dates"]:
                for name in ["overview", "plant/timeseries", "replay", "weather/day"]:
                    ex.save(name, {"plant": plant, "date": date})
                ex.save("inverters/status", {"plant": plant, "date": date})   # Overview 3D plant view
                ex.save("alerts", {"plant": plant, "date": date, "status": "Active", "sort": "severity",
                                   "limit": 5, "include_notices": "false"})   # Overview "Needs attention"
                for inverter in inverters:
                    ex.save(f"inverter/{inverter}", {"date": date})
    print(f"Static site written to {out}: {ex.files:,} JSON answers, {ex.bytes / 1e6:.1f} MB")


if __name__ == "__main__":
    export(Path(sys.argv[1]) if len(sys.argv) > 1 else config.PROJECT_ROOT / "site")
