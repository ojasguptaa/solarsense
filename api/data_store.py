"""Loads the precomputed pipeline files ONCE and offers small lookup helpers for the API.

The API never trains or runs a model — it only reads files the pipeline already made.
"""

import json
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import HTTPException

from engine import config
from engine.energy_breakdown import power_per_sunlight_at_25c
from engine.metrics import load_metrics

STATUSES = ["Open", "Acknowledged", "Resolved"]
SEVERITY_RANK = {level: rank for rank, level in enumerate(config.SEVERITY_LEVELS)}
REQUIRED_FILES = [config.EXPECTED_FILE, config.ALERTS_FILE, config.DAILY_PLANT_FILE,
                  config.DAILY_INVERTER_FILE, config.METRICS_FILE]


class DataStore:
    """Everything the API serves, kept in memory for fast answers."""

    def __init__(self):
        """Read every file once; stop with a friendly message if the pipeline has not run."""
        missing = [path.name for path in REQUIRED_FILES if not path.exists()]
        if missing:
            raise RuntimeError(f"Missing pipeline outputs: {', '.join(missing)}. "
                               "Run the pipeline first (python run_all.py).")
        self.expected = pd.read_parquet(config.EXPECTED_FILE)
        self.alerts = pd.read_parquet(config.ALERTS_FILE)
        self.alerts["evidence"] = self.alerts["evidence"].map(json.loads)
        self.daily_plant = pd.read_parquet(config.DAILY_PLANT_FILE)
        self.daily_inverter = pd.read_parquet(config.DAILY_INVERTER_FILE)
        self.anomaly = (pd.read_parquet(config.ANOMALY_DAYS_FILE) if config.ANOMALY_DAYS_FILE.exists()
                        else pd.DataFrame(columns=["plant", "inverter", "date", "anomaly_score", "is_unusual"]))
        self.metrics = load_metrics()
        self.dates = sorted(self.daily_plant["date"].unique())
        self.plants = sorted(int(p) for p in self.daily_plant["plant"].unique())
        self.inverter_plant = dict(self.daily_inverter[["inverter", "plant"]].drop_duplicates().values)
        self.load_weather()

    def load_weather(self):
        """Weather & energy files (Phases W1–W3). Optional: without them the rest of the site still works."""
        files = [config.WEATHER_15MIN_FILE, config.WEATHER_DAILY_FILE, config.ENERGY_BREAKDOWN_FILE,
                 config.TEMPERATURE_POINTS_FILE]
        self.weather_ready = all(path.exists() for path in files) and "breakdown" in self.metrics
        if not self.weather_ready:
            self.weather_15min = pd.DataFrame(columns=["plant", "timestamp", "date", "sky_label", "module_temp"])
            return
        self.weather_15min = pd.read_parquet(config.WEATHER_15MIN_FILE)
        self.weather_15min["date"] = self.weather_15min["date"].astype(str)   # same text dates as everywhere else
        # kW per unit of sunlight at 25 °C — the live replay needs it to add up cloud loss tick by tick.
        self.power_per_sunlight = power_per_sunlight_at_25c(self.weather_15min)
        self.weather_daily = pd.read_parquet(config.WEATHER_DAILY_FILE)
        self.breakdown = pd.read_parquet(config.ENERGY_BREAKDOWN_FILE)
        self.temperature_points = pd.read_parquet(config.TEMPERATURE_POINTS_FILE)

    # --- checking inputs --------------------------------------------------------
    def check_plant(self, plant):
        """Return the plant number, or a friendly 404 if it does not exist."""
        if plant not in self.plants:
            raise HTTPException(404, f"Plant {plant} not found. Available plants: {self.plants}.")
        return plant

    def check_date(self, date, plant=None):
        """Return the date, or a friendly 404 if it is outside the data.
        No date given: the plant's highest-loss day (or the latest day when no plant is known)."""
        if date is None:
            return self.worst_loss_date(plant) if plant is not None else self.dates[-1]
        if date not in self.dates:
            raise HTTPException(404, f"No data for {date} (data covers {self.dates[0]} to {self.dates[-1]}).")
        return date

    def check_inverter(self, inverter):
        """Return the plant of an inverter, or a friendly 404."""
        if inverter not in self.inverter_plant:
            raise HTTPException(404, f"Inverter {inverter} not found.")
        return int(self.inverter_plant[inverter])

    # --- alert status (small JSON file, changes while the app runs) -------------
    def load_statuses(self):
        """Statuses changed by operators: {alert_id: {"status": ..., "updated_at": ...}}."""
        path = config.ALERT_STATUS_FILE
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as file:
            return json.load(file)

    def save_status(self, alert_id, status):
        """Store a new status for one alert and return what was saved."""
        statuses = self.load_statuses()
        statuses[alert_id] = {"status": status, "updated_at": datetime.now().isoformat(timespec="seconds")}
        with open(config.ALERT_STATUS_FILE, "w", encoding="utf-8") as file:
            json.dump(statuses, file, indent=2)
        return statuses[alert_id]

    def alerts_with_status(self):
        """The alerts table with each alert's CURRENT status (Open unless an operator changed it)."""
        alerts = self.alerts.copy()
        statuses = self.load_statuses()
        alerts["status"] = [statuses.get(a, {}).get("status", "Open") for a in alerts["id"]]
        alerts["status_updated_at"] = [statuses.get(a, {}).get("updated_at") for a in alerts["id"]]
        return alerts

    @staticmethod
    def is_notice(alerts):
        """True for plant-wide data-quality notices: sensor issues with no energy lost or at risk.
        They are real issues but not urgent, so they stay out of "needs attention" counts."""
        return ((alerts["fault_type"] == "SENSOR_ISSUE") & (alerts["inverter"] == "ALL")
                & (alerts["energy_loss_kwh"] == 0) & (alerts["energy_at_risk_kwh"] == 0))

    def worst_loss_date(self, plant):
        """The day with the highest confirmed fault loss for a plant (latest day if there is no loss)."""
        days = self.daily_plant[self.daily_plant["plant"] == plant].sort_values("date")
        if days["fault_loss_kwh"].max() <= 0:
            return days["date"].iloc[-1]
        return days.loc[days["fault_loss_kwh"].idxmax(), "date"]

    def alerts_on_date(self, plant, date):
        """Alerts of a plant that were happening at any time on the given date."""
        alerts = self.alerts_with_status()
        day_start = pd.Timestamp(date)
        day_end = day_start + pd.Timedelta(days=1)
        return alerts[(alerts["plant"] == plant) & (alerts["start"] < day_end) & (alerts["end"] > day_start)]


def to_records(table):
    """Turn a table into JSON-safe rows: blanks become null, times become text, numbers rounded."""
    table = table.copy()
    for column in table.columns:
        if pd.api.types.is_datetime64_any_dtype(table[column]):
            table[column] = table[column].dt.strftime("%Y-%m-%dT%H:%M:%S")
        elif pd.api.types.is_float_dtype(table[column]):
            table[column] = table[column].round(4)
    table = table.replace({np.nan: None})
    return table.astype(object).where(table.notna(), None).to_dict(orient="records")


_store = None


def get_store():
    """The single shared DataStore (created on first use)."""
    global _store
    if _store is None:
        _store = DataStore()
    return _store
