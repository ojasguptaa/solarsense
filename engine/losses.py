"""Turn detected faults into energy (kWh) and money (₹) losses (Phase 6).

Run from the solarsense folder with:   python -m engine.losses
- Adds ₹ columns to data/processed/alerts.parquet
- Writes daily tables per plant and per inverter
- Saves totals under "losses" in reports/metrics.json

Two kinds of energy are NEVER mixed:
  confirmed loss  = expected − actual during a fault, on readings we really have
  at-risk energy  = expected energy during a data gap (we cannot see what happened)
"""

import pandas as pd

from engine import config
from engine.assumptions import record_assumption
from engine.metrics import save_metrics_section

TARIFF_NOTE = ("₹ values use an assumed tariff (ASSUMPTION — see About) chosen between recent SECI auction "
               "prices, configurable in engine/config.py.")


def add_money_to_alerts(alerts):
    """Money = energy × tariff, kept separately for confirmed loss and at-risk energy."""
    alerts["money_loss_inr"] = (alerts["energy_loss_kwh"] * config.TARIFF_INR_PER_KWH).round(0)
    alerts["money_at_risk_inr"] = (alerts["energy_at_risk_kwh"] * config.TARIFF_INR_PER_KWH).round(0)
    return alerts


def alert_losses_per_day(alerts):
    """Spread each alert's loss over the calendar days it covers (most alerts cover one day)."""
    rows = []
    for alert in alerts.itertuples():
        days = pd.date_range(alert.start.normalize(), (alert.end - pd.Timedelta(minutes=1)).normalize())
        for day in days:
            rows.append({"plant": alert.plant, "inverter": alert.inverter, "date": str(day.date()),
                         "fault_loss_kwh": alert.energy_loss_kwh / len(days),
                         "at_risk_kwh": alert.energy_at_risk_kwh / len(days)})
    return pd.DataFrame(rows).groupby(["plant", "inverter", "date"], as_index=False).sum()


def finish_daily_table(daily):
    """Add performance ratio, net shortfall and ₹ columns to a daily table."""
    daily["performance_ratio"] = (daily["actual_kwh"] / daily["expected_kwh"].where(daily["expected_kwh"] > 0)).round(4)
    # Net shortfall includes normal model error, so it is shown for context only.
    daily["net_shortfall_kwh"] = daily["expected_kwh"] - daily["actual_kwh"]
    daily["fault_loss_inr"] = daily["fault_loss_kwh"] * config.TARIFF_INR_PER_KWH
    daily["at_risk_inr"] = daily["at_risk_kwh"] * config.TARIFF_INR_PER_KWH
    return daily.round(2)


def build_daily_tables(expected, alerts):
    """Daily actual / expected / loss per inverter and per plant."""
    present = expected[~expected["is_missing"]]
    keys = ["plant", "inverter", "date"]
    # Start from ALL inverter-days, so a day with no readings still appears (with 0 actual).
    inverter_daily = expected[keys].drop_duplicates().merge(
        present.groupby(keys).agg(actual_kwh=("ac_kw", "sum"), expected_kwh=("expected_kw", "sum"))
        * config.INTERVAL_HOURS, on=keys, how="left").fillna({"actual_kwh": 0, "expected_kwh": 0})

    per_day = alert_losses_per_day(alerts)
    inverter_daily = inverter_daily.merge(per_day, on=keys, how="left").fillna({"fault_loss_kwh": 0, "at_risk_kwh": 0})

    plant_daily = inverter_daily.groupby(["plant", "date"], as_index=False)[
        ["actual_kwh", "expected_kwh", "fault_loss_kwh", "at_risk_kwh"]].sum()
    # Plant-wide alerts (inverter "ALL", e.g. overheating) count at plant level only.
    plant_wide = per_day[per_day["inverter"] == "ALL"].drop(columns="inverter")
    if not plant_wide.empty:
        plant_daily = plant_daily.merge(plant_wide, on=["plant", "date"], how="left", suffixes=("", "_plant"))
        for column in ["fault_loss_kwh", "at_risk_kwh"]:
            plant_daily[column] += plant_daily.pop(f"{column}_plant").fillna(0)
    return finish_daily_table(inverter_daily), finish_daily_table(plant_daily)


def summarise(alerts, inverter_daily, plant_daily):
    """Totals by fault type, plant, top inverters and whole period, plus a yearly projection."""
    n_days = plant_daily["date"].nunique()
    to_year = config.DAYS_PER_YEAR / n_days

    by_type = alerts.groupby("fault_type").agg(
        alerts=("id", "count"), fault_loss_kwh=("energy_loss_kwh", "sum"), fault_loss_inr=("money_loss_inr", "sum"),
        at_risk_kwh=("energy_at_risk_kwh", "sum"), at_risk_inr=("money_at_risk_inr", "sum"))

    by_plant = {}
    for plant, days in plant_daily.groupby("plant"):
        totals = days[["actual_kwh", "expected_kwh", "fault_loss_kwh", "at_risk_kwh", "net_shortfall_kwh"]].sum()
        by_plant[f"plant_{plant}"] = {
            **{k: round(float(v), 1) for k, v in totals.items()},
            "performance_ratio": round(float(totals["actual_kwh"] / totals["expected_kwh"]), 4),
            "fault_loss_inr": round(float(totals["fault_loss_kwh"] * config.TARIFF_INR_PER_KWH), 0),
            "at_risk_inr": round(float(totals["at_risk_kwh"] * config.TARIFF_INR_PER_KWH), 0),
            "projected_annual_fault_loss_kwh": round(float(totals["fault_loss_kwh"] * to_year), 0),
            "projected_annual_fault_loss_inr": round(float(totals["fault_loss_kwh"] * to_year
                                                           * config.TARIFF_INR_PER_KWH), 0)}

    inverter_alerts = alerts[alerts["inverter"] != "ALL"]
    worst = inverter_daily.groupby(["plant", "inverter"])["fault_loss_kwh"].sum().nlargest(config.TOP_N_INVERTERS)
    top_inverters = []
    for (plant, inverter), loss in worst.items():
        own = inverter_alerts[(inverter_alerts["plant"] == plant) & (inverter_alerts["inverter"] == inverter)]
        top_inverters.append({
            "plant": int(plant), "inverter": inverter, "fault_loss_kwh": round(float(loss), 1),
            "fault_loss_inr": round(float(loss * config.TARIFF_INR_PER_KWH), 0), "alerts": int(len(own)),
            "main_fault_type": own.groupby("fault_type")["energy_loss_kwh"].sum().idxmax()})

    total_loss = float(alerts["energy_loss_kwh"].sum())
    total_risk = float(alerts["energy_at_risk_kwh"].sum())
    return {
        "tariff_inr_per_kwh": config.TARIFF_INR_PER_KWH, "tariff_note": TARIFF_NOTE, "days": int(n_days),
        "total": {"fault_loss_kwh": round(total_loss, 1),
                  "fault_loss_inr": round(total_loss * config.TARIFF_INR_PER_KWH, 0),
                  "at_risk_kwh": round(total_risk, 1),
                  "at_risk_inr": round(total_risk * config.TARIFF_INR_PER_KWH, 0),
                  "projected_annual_fault_loss_kwh": round(total_loss * to_year, 0),
                  "projected_annual_fault_loss_inr": round(total_loss * to_year * config.TARIFF_INR_PER_KWH, 0)},
        "by_fault_type": {t: {k: round(float(v), 1) for k, v in row.items()} for t, row in by_type.iterrows()},
        "by_plant": by_plant, "top_inverters": top_inverters,
        "projection_note": f"Estimate: {n_days}-day loss scaled to {config.DAYS_PER_YEAR} days, "
                           "assuming the rest of the year behaves like May–June and nothing is fixed."}


def compute_losses():
    """Run the whole loss step and save every output."""
    for path in [config.EXPECTED_FILE, config.ALERTS_FILE]:
        if not path.exists():
            raise FileNotFoundError(f"{path.name} not found — run the earlier pipeline steps first.")
    expected = pd.read_parquet(config.EXPECTED_FILE)
    alerts = add_money_to_alerts(pd.read_parquet(config.ALERTS_FILE))
    alerts.to_parquet(config.ALERTS_FILE, index=False)

    inverter_daily, plant_daily = build_daily_tables(expected, alerts)
    inverter_daily.to_parquet(config.DAILY_INVERTER_FILE, index=False)
    plant_daily.to_parquet(config.DAILY_PLANT_FILE, index=False)

    summary = summarise(alerts, inverter_daily, plant_daily)
    save_metrics_section("losses", summary)
    record_assumption(
        key="projected_annual_loss", title="Projected annual loss if faults are not fixed",
        value=config.DAYS_PER_YEAR, unit="days scaled from the observed period",
        why=summary["projection_note"] + " Real yearly sunlight and fault patterns will differ.",
        source="Simple extrapolation (engine/losses.py)")
    return summary


if __name__ == "__main__":
    result = compute_losses()
    total = result["total"]
    print(f"Whole period ({result['days']} days): confirmed fault loss {total['fault_loss_kwh']:,.0f} kWh "
          f"= ₹{total['fault_loss_inr']:,.0f}; at risk (data gaps) {total['at_risk_kwh']:,.0f} kWh")
    print(f"Projected per year if not fixed: {total['projected_annual_fault_loss_kwh']:,.0f} kWh "
          f"= ₹{total['projected_annual_fault_loss_inr']:,.0f}  ({result['tariff_note']})")
    for plant, info in result["by_plant"].items():
        print(f"{plant}: actual {info['actual_kwh']:,.0f} kWh, expected {info['expected_kwh']:,.0f} kWh, "
              f"PR {info['performance_ratio']}, fault loss {info['fault_loss_kwh']:,.0f} kWh, "
              f"net shortfall {info['net_shortfall_kwh']:,.0f} kWh")
    for fault, info in result["by_fault_type"].items():
        print(f"  {fault:17s} {info['alerts']:5.0f} alerts  loss {info['fault_loss_kwh']:>11,.0f} kWh  "
              f"at risk {info['at_risk_kwh']:>9,.0f} kWh")
    for row in result["top_inverters"]:
        print(f"  top: Plant {row['plant']} {row['inverter']} {row['fault_loss_kwh']:,.0f} kWh "
              f"({row['alerts']} alerts, mostly {row['main_fault_type']})")
