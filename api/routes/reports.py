"""Endpoints for losses, validation results and assumptions."""

from typing import Optional

from fastapi import APIRouter

from api.data_store import get_store, to_records
from api.schemas import Assumption, LossesResponse
from engine import config

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/losses", response_model=LossesResponse)
def losses(plant: Optional[int] = None):
    """Losses by fault type, top inverters, daily trend and projected annual loss (one plant or all)."""
    store = get_store()
    metrics = store.metrics["losses"]
    alerts, daily, inverters = store.alerts, store.daily_plant, store.daily_inverter
    if plant is not None:
        plant = store.check_plant(plant)
        alerts = alerts[alerts["plant"] == plant]
        daily = daily[daily["plant"] == plant]
        inverters = inverters[inverters["plant"] == plant]
        total = metrics["by_plant"][f"plant_{plant}"]
    else:
        total = metrics["total"]

    by_type = alerts.groupby("fault_type").agg(
        alerts=("id", "count"), fault_loss_kwh=("energy_loss_kwh", "sum"), fault_loss_inr=("money_loss_inr", "sum"),
        at_risk_kwh=("energy_at_risk_kwh", "sum"), at_risk_inr=("money_at_risk_inr", "sum")).round(1).reset_index()

    worst = (inverters.groupby(["plant", "inverter"])[["fault_loss_kwh", "fault_loss_inr"]].sum()
             .nlargest(config.TOP_N_INVERTERS, "fault_loss_kwh").round(1).reset_index())
    worst["alerts"] = [int(((alerts["plant"] == p) & (alerts["inverter"] == i)).sum())
                       for p, i in zip(worst["plant"], worst["inverter"])]

    trend = daily.groupby("date")[["fault_loss_kwh", "fault_loss_inr", "at_risk_kwh"]].sum().round(1).reset_index()
    keep = ["fault_loss_kwh", "fault_loss_inr", "at_risk_kwh", "at_risk_inr",
            "projected_annual_fault_loss_kwh", "projected_annual_fault_loss_inr"]
    return {"plant": plant, "days": metrics["days"], "total": {k: float(total[k]) for k in keep},
            "by_fault_type": to_records(by_type.sort_values("fault_loss_kwh", ascending=False)),
            "top_inverters": to_records(worst), "daily_trend": to_records(trend),
            "projection_note": metrics["projection_note"], "tariff_note": metrics["tariff_note"]}


@router.get("/validation")
def validation():
    """Injected-fault test results: recall, false alarms, delay, loss error, threshold trade-off."""
    return get_store().metrics.get("validation", {})


@router.get("/ai_models")
def ai_models():
    """Results of our trained models: expected output, fault classifier and the daily-retraining test."""
    metrics = get_store().metrics
    return {"expected_model": metrics.get("expected_model", {}), "fault_classifier": metrics.get("fault_classifier"),
            "model_updates": metrics.get("model_updates")}


@router.get("/assumptions", response_model=list[Assumption])
def assumptions():
    """Every assumption we made, with its value, reason and source."""
    return get_store().metrics.get("assumptions", [])


@router.get("/settings")
def settings():
    """Key detector thresholds from engine/config.py, so the website never repeats them as typed text."""
    return {
        "underperformance_drop_pct": -config.UNDER_RESIDUAL_PCT_MAX,
        "underperformance_min_hours": config.UNDER_MIN_INTERVALS * config.INTERVAL_HOURS,
        "trip_min_hours": config.TRIP_MIN_INTERVALS * config.INTERVAL_HOURS,
        "data_gap_min_hours": config.GAP_MIN_INTERVALS * config.INTERVAL_HOURS,
        "degradation_slope_pct_per_day": -config.DEGRADATION_SLOPE_MAX_PCT,
        "tariff_inr_per_kwh": config.TARIFF_INR_PER_KWH,
        "interval_minutes": int(config.INTERVAL_HOURS * 60),
    }
