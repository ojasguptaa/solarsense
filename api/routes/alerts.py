"""Endpoints for alerts: list with filters, full detail with evidence, and status updates."""

from typing import Literal, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException

from api.data_store import SEVERITY_RANK, get_store, to_records
from api.schemas import AlertDetail, AlertsResponse, StatusResponse, StatusUpdate

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

ALERT_FIELDS = ["id", "plant", "inverter", "fault_type", "start", "end", "duration_hours", "severity",
                "energy_loss_kwh", "energy_at_risk_kwh", "money_loss_inr", "money_at_risk_inr", "reason",
                "recommended_action", "status", "status_updated_at",
                "confidence", "sky_condition", "avg_csi", "module_temp_c", "weather_note",   # Phase W4
                "ai_diagnosis", "ai_confidence_pct", "ai_agrees"]                     # AI model 3
EVIDENCE_MARGIN = pd.Timedelta(hours=1)   # show a bit of normal behaviour before/after the fault


@router.get("", response_model=AlertsResponse)
def list_alerts(plant: Optional[int] = None, severity: Optional[str] = None, type: Optional[str] = None,
                status: Optional[str] = None, date: Optional[str] = None,
                sort: Literal["loss", "time", "severity"] = "severity", limit: Optional[int] = None,
                include_notices: bool = True):
    """Alert list. Filters are optional; status "Active" means Open or Acknowledged;
    date keeps alerts that were happening at any time on that day;
    include_notices=false hides plant-wide data-quality notices (sensor issues with no energy lost)."""
    store = get_store()
    alerts = store.alerts_with_status()
    if not include_notices:
        alerts = alerts[~store.is_notice(alerts)]
    if plant is not None:
        alerts = alerts[alerts["plant"] == store.check_plant(plant)]
    if date is not None:
        day_start = pd.Timestamp(store.check_date(date))
        alerts = alerts[(alerts["start"] < day_start + pd.Timedelta(days=1)) & (alerts["end"] > day_start)]
    if severity:
        alerts = alerts[alerts["severity"] == severity]
    if type:
        alerts = alerts[alerts["fault_type"] == type]
    if status == "Active":
        alerts = alerts[alerts["status"] != "Resolved"]
    elif status:
        alerts = alerts[alerts["status"] == status]

    # Sorting: biggest energy loss, newest first, or most severe (then biggest loss).
    alerts = alerts.assign(rank=alerts["severity"].map(SEVERITY_RANK),
                           impact=alerts["energy_loss_kwh"] + alerts["energy_at_risk_kwh"])
    if sort == "loss":   # confirmed loss first; at-risk energy (data gaps) only breaks ties
        alerts = alerts.sort_values(["energy_loss_kwh", "energy_at_risk_kwh"], ascending=False)
    elif sort == "time":
        alerts = alerts.sort_values("start", ascending=False)
    else:
        alerts = alerts.sort_values(["rank", "impact"], ascending=False)
    if limit:
        alerts = alerts.head(limit)
    return {"count": int(len(alerts)), "alerts": to_records(alerts[ALERT_FIELDS])}


def _find_alert(alert_id):
    """One alert (with current status) or a friendly 404."""
    alerts = get_store().alerts_with_status()
    match = alerts[alerts["id"] == alert_id]
    if match.empty:
        raise HTTPException(404, f"Alert {alert_id} not found.")
    return match.iloc[0]


def _evidence_series(store, alert):
    """The data behind the 'Why?' chart: what happened around the alert."""
    if alert["fault_type"] == "SENSOR_ISSUE":
        return "none", []
    if alert["fault_type"] == "DEGRADATION":
        days = store.daily_inverter[(store.daily_inverter["inverter"] == alert["inverter"])]
        return "daily", to_records(days[["date", "actual_kwh", "expected_kwh", "performance_ratio"]])
    window = ((store.expected["plant"] == alert["plant"])
              & (store.expected["timestamp"] >= alert["start"] - EVIDENCE_MARGIN)
              & (store.expected["timestamp"] < alert["end"] + EVIDENCE_MARGIN))
    rows = store.expected[window]
    if alert["inverter"] == "ALL":   # plant-wide alert: show plant totals
        series = rows.groupby("timestamp").agg(actual_kw=("ac_kw", "sum"), expected_kw=("expected_kw", "sum"),
                                               irradiation=("irradiation", "first")).reset_index()
    else:
        series = rows[rows["inverter"] == alert["inverter"]][
            ["timestamp", "ac_kw", "expected_kw", "peer_median_kw", "is_missing", "irradiation"]]
        series = series.rename(columns={"ac_kw": "actual_kw"})
    series = series.sort_values("timestamp")
    series["in_alert"] = (series["timestamp"] >= alert["start"]) & (series["timestamp"] < alert["end"])
    return "intervals", to_records(series)


@router.get("/{alert_id}", response_model=AlertDetail)
def alert_detail(alert_id: str):
    """Everything about one alert, including the evidence series for the 'Why?' chart."""
    store = get_store()
    alert = _find_alert(alert_id)
    kind, series = _evidence_series(store, alert)
    summary = to_records(pd.DataFrame([alert[ALERT_FIELDS]]))[0]
    return {**summary, "evidence": alert["evidence"], "series_kind": kind, "series": series,
            "tariff_note": store.metrics["losses"]["tariff_note"]}


@router.post("/{alert_id}/status", response_model=StatusResponse)
def set_alert_status(alert_id: str, update: StatusUpdate):
    """Mark an alert Open, Acknowledged or Resolved (saved in data/processed/alert_status.json)."""
    _find_alert(alert_id)
    saved = get_store().save_status(alert_id, update.status)
    return {"id": alert_id, **saved}
