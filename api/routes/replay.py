"""Live-replay endpoint: one day of the plant, tick by tick (15 min), with running totals precomputed.

The website just plays these ticks back — it never adds anything up itself.
"""

from typing import Optional

import pandas as pd
from fastapi import APIRouter

from api.data_store import get_store
from engine import config
from engine.energy_breakdown import cloud_loss_per_reading

router = APIRouter(prefix="/api", tags=["replay"])


def _spread_alert_losses(alerts, ticks, date):
    """Share each alert's loss (for this day) evenly over the day's ticks inside the alert window.

    Uses the same per-day split as engine/losses.py, so the last tick equals the day's loss exactly.
    """
    loss = pd.Series(0.0, index=ticks)
    risk = pd.Series(0.0, index=ticks)
    day = pd.Timestamp(date)
    for alert in alerts.itertuples():
        days = len(pd.date_range(alert.start.normalize(), (alert.end - pd.Timedelta(minutes=1)).normalize()))
        inside = ticks[(ticks >= max(alert.start, day)) & (ticks < min(alert.end, day + pd.Timedelta(days=1)))]
        if len(inside) == 0:
            continue
        loss[inside] += alert.energy_loss_kwh / days / len(inside)
        risk[inside] += alert.energy_at_risk_kwh / days / len(inside)
    return loss, risk


def _natural_loss_so_far(store, plant, date, ticks):
    """Weather cost (clouds + heat, kWh) added up to each tick — same sums as engine/energy_breakdown.py.

    The last tick gets the whole day's total (dusk readings after it included), so it matches the day exactly.
    Returns None when the weather steps have not been run.
    """
    if not store.weather_ready:
        return None
    day = store.weather_15min[(store.weather_15min["plant"] == plant) & (store.weather_15min["date"] == date)]
    if day.empty:
        return None
    day = day.sort_values("timestamp")
    per_reading = (cloud_loss_per_reading(day, store.power_per_sunlight) + day["heat_loss_kw"].fillna(0)) \
        * config.INTERVAL_HOURS
    so_far = pd.Series(per_reading.cumsum().values, index=pd.DatetimeIndex(day["timestamp"]))
    at_ticks = so_far.reindex(ticks, method="ffill").fillna(0)
    at_ticks.iloc[-1] = so_far.iloc[-1]
    return at_ticks


@router.get("/replay")
def replay(plant: int = 1, date: Optional[str] = None):
    """Every 15-minute tick of one day with power, running energy totals, active alerts and new-alert events."""
    store = get_store()
    plant = store.check_plant(plant)
    date = store.check_date(date, plant)
    rows = store.expected[(store.expected["plant"] == plant) & (store.expected["date"] == date)]
    present = rows[~rows["is_missing"]]
    ticks = pd.DatetimeIndex(sorted(rows["timestamp"].unique()))
    actual_kw = present.groupby("timestamp")["ac_kw"].sum().reindex(ticks, fill_value=0)
    expected_kw = present.groupby("timestamp")["expected_kw"].sum().reindex(ticks, fill_value=0)
    irradiation = rows.groupby("timestamp")["irradiation"].first().reindex(ticks)
    # Phase W6: the sky and panel temperature at each tick (blank if the weather steps have not been run).
    weather = store.weather_15min[(store.weather_15min["plant"] == plant) & (store.weather_15min["date"] == date)]
    weather = weather.set_index("timestamp").reindex(ticks)

    alerts = store.alerts_on_date(plant, date)
    alerts = alerts[~store.is_notice(alerts)]   # data-quality notices are not counted as alerts to act on
    loss, risk = _spread_alert_losses(alerts, ticks, date)
    cum_actual = (actual_kw * config.INTERVAL_HOURS).cumsum()
    cum_expected = (expected_kw * config.INTERVAL_HOURS).cumsum()
    cum_loss, cum_risk = loss.cumsum(), risk.cumsum()
    cum_natural = _natural_loss_so_far(store, plant, date, ticks)

    out = []
    for i, ts in enumerate(ticks):
        started = alerts[(alerts["start"] <= ts) & (alerts["status"] != "Resolved")]
        out.append({
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
            "actual_kw": round(float(actual_kw.iloc[i]), 2), "expected_kw": round(float(expected_kw.iloc[i]), 2),
            "irradiation": None if pd.isna(irradiation.iloc[i]) else round(float(irradiation.iloc[i]), 4),
            "actual_kwh": round(float(cum_actual.iloc[i]), 1), "expected_kwh": round(float(cum_expected.iloc[i]), 1),
            "performance_ratio": round(float(cum_actual.iloc[i] / cum_expected.iloc[i]), 4) if cum_expected.iloc[i] > 0 else None,
            "fault_loss_kwh": round(float(cum_loss.iloc[i]), 1), "at_risk_kwh": round(float(cum_risk.iloc[i]), 1),
            "fault_loss_inr": round(float(cum_loss.iloc[i] * config.TARIFF_INR_PER_KWH), 0),
            "at_risk_inr": round(float(cum_risk.iloc[i] * config.TARIFF_INR_PER_KWH), 0),
            "natural_loss_kwh": None if cum_natural is None else round(float(cum_natural.iloc[i]), 1),
            "active_alerts_by_severity": {lvl: int((started["severity"] == lvl).sum()) for lvl in config.SEVERITY_LEVELS},
            "sky_label": None if pd.isna(weather["sky_label"].iloc[i]) else weather["sky_label"].iloc[i],
            "module_temp_c": None if pd.isna(weather["module_temp"].iloc[i]) else round(float(weather["module_temp"].iloc[i]), 1),
        })

    # Each alert joins the Overview's live "Needs attention" list at the first tick at or after it starts
    # (alerts that began on an earlier day are skipped).
    events = []
    day_alerts = alerts[alerts["start"] >= pd.Timestamp(date)].sort_values("start")
    for alert in day_alerts.itertuples():
        tick = int((ticks >= alert.start).argmax()) if (ticks >= alert.start).any() else None
        if tick is not None:
            events.append({"tick": tick, "id": alert.id, "severity": alert.severity, "fault_type": alert.fault_type,
                           "inverter": alert.inverter, "reason": alert.reason,
                           "start": alert.start.strftime("%Y-%m-%dT%H:%M:%S")})
    losses = store.metrics["losses"]
    return {"plant": plant, "date": date, "ticks": out, "events": events,
            "tariff_inr_per_kwh": losses["tariff_inr_per_kwh"], "tariff_note": losses["tariff_note"]}
