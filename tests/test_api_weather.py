"""Checks the Weather & Energy API endpoints (Phase W5) and the weather fields added to old ones (W4, W6).

Run with:   pytest
"""

import pytest
from fastapi.testclient import TestClient

from engine import config
from tests.conftest import log_in
from engine.metrics import load_metrics


@pytest.fixture(scope="module")
def client():
    """A test client that starts the app (loading all data once)."""
    if not config.ENERGY_BREAKDOWN_FILE.exists():
        pytest.skip("Run the pipeline first (python run_all.py)")
    from api.main import app
    with TestClient(app) as test_client:
        log_in(test_client)   # every page and API call needs a login
        yield test_client


def test_weather_day_has_sky_temperature_and_power(client):
    """One day: 15-minute points with sky label, clear-sky curve, temperatures and power; sentences; waterfall."""
    body = client.get("/api/weather/day", params={"plant": 2, "date": "2020-06-11"}).json()
    point = body["points"][len(body["points"]) // 2]
    for key in ["irradiation", "clear_sky_irr", "sky_label", "ambient_temp", "module_temp", "plant_actual_kw",
                "plant_expected_kw", "heat_loss_kw"]:
        assert key in point
    assert point["sky_label"] in config.SKY_LABELS
    assert body["day"]["dominant_sky"] in config.SKY_LABELS
    assert "clouds cost" in body["takeaway"] and "faults cost" in body["takeaway"]
    assert sum(body["sky_share_pct"].values()) == pytest.approx(100, abs=0.5)


def test_weather_day_defaults_to_highest_loss_day(client):
    """With no date, the page opens on the plant's highest-loss day, like every other page."""
    plants = {p["plant"]: p["worst_loss_date"] for p in client.get("/api/plants").json()["plants"]}
    assert client.get("/api/weather/day", params={"plant": 1}).json()["date"] == plants[1]


def test_weather_calendar_has_every_day(client):
    """34 tiles per plant, each with a sky, sunshine score, panel temperature and energy."""
    body = client.get("/api/weather/calendar", params={"plant": 1}).json()
    assert len(body["days"]) == 34
    assert sum(body["days_by_sky"].values()) == 34
    tile = body["days"][0]
    assert {"dominant_sky", "sunshine_score", "max_module_c", "actual_kwh", "cloud_loss_kwh"} <= tile.keys()


def test_weather_temperature_matches_metrics(client):
    """Coefficient and scatter come straight from the pipeline (no maths in the API)."""
    body = client.get("/api/weather/temperature", params={"plant": 1}).json()
    stored = load_metrics()["temperature"]["by_plant"]["plant_1"]
    assert body["coefficient_pct_per_c"] == stored["coefficient_pct_per_c"] < 0
    assert len(body["points"]) == config.TEMP_WEB_SCATTER_POINTS
    assert body["fit_line"]["slope_pct_points_per_c"] < 0


@pytest.mark.parametrize("params", [{"plant": 1, "date": "2020-06-07"}, {"plant": 2}, {}])
def test_breakdown_steps_add_up(client, params):
    """Day, plant period and both-plant period: potential − losses = actual."""
    steps = client.get("/api/breakdown", params=params).json()["steps"]
    assert [s["part"] for s in steps] == ["clear_sky_potential", "cloud_loss", "heat_loss", "fault_loss",
                                          "not_measured", "other", "actual"]
    assert steps[0]["kwh"] - sum(s["kwh"] for s in steps[1:-1]) == pytest.approx(steps[-1]["kwh"], abs=1)


def test_breakdown_errors_are_friendly(client):
    """A date without a plant, or an unknown plant/date, gives a clear message."""
    assert client.get("/api/breakdown", params={"date": "2020-06-07"}).status_code == 400
    assert client.get("/api/breakdown", params={"plant": 9}).status_code == 404
    assert "No data for" in client.get("/api/weather/day", params={"plant": 1, "date": "2021-01-01"}).json()["detail"]


def test_alerts_carry_weather_fields(client):
    """Alert list and detail include confidence, sky, panel temperature and the weather sentence (W4)."""
    alert = client.get("/api/alerts", params={"type": "INVERTER_TRIP", "limit": 1}).json()["alerts"][0]
    assert alert["confidence"] in config.CONFIDENCE_LEVELS
    assert alert["weather_note"]
    detail = client.get(f"/api/alerts/{alert['id']}").json()
    assert detail["sky_condition"] in config.SKY_LABELS and detail["module_temp_c"] is not None


def test_replay_ticks_carry_sky_and_temperature(client):
    """Live replay: every tick has the sky label and panel temperature (W6)."""
    ticks = client.get("/api/replay", params={"plant": 1, "date": "2020-05-25"}).json()["ticks"]
    noon = [t for t in ticks if t["timestamp"].endswith("12:00:00")][0]
    assert noon["sky_label"] in config.SKY_LABELS and noon["module_temp_c"] > 25


def test_replay_weather_and_fault_cost_end_at_the_days_totals(client):
    """Live replay: weather cost and fault cost grow tick by tick and end on the Overview's day numbers."""
    for plant, date in [(1, "2020-06-07"), (2, "2020-05-27")]:
        ticks = client.get("/api/replay", params={"plant": plant, "date": date}).json()["ticks"]
        day = client.get("/api/weather/day", params={"plant": plant, "date": date}).json()
        natural = [t["natural_loss_kwh"] for t in ticks]
        assert natural[0] < natural[-1]
        assert natural[-1] == pytest.approx(day["natural_loss_kwh"], abs=0.2)
        assert ticks[-1]["fault_loss_kwh"] == pytest.approx(day["fixable_loss_kwh"], abs=0.2)
