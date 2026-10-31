"""Write presentation/key_numbers.md — every number we say on stage, straight from the pipeline files.

Run from the solarsense folder:   python presentation/make_key_numbers.py
Re-run it after `python run_all.py` (e.g. once the team has a sourced tariff) so slides never drift.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # so "engine" can be imported
from engine import config  # noqa: E402
from engine.metrics import load_metrics  # noqa: E402

OUT = Path(__file__).resolve().parent / "key_numbers.md"
M = "reports/metrics.json"


def indian(value, decimals=0):
    """Number with Indian digit grouping (1,23,45,678) — the same style as the dashboard."""
    sign = "-" if value < 0 else ""
    whole, _, frac = f"{abs(value):.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = [head[max(i - 2, 0):i] for i in range(len(head), 0, -2)][::-1]
        whole = ",".join(groups + [tail])
    return sign + whole + (f".{frac}" if frac else "")


def row(what, value, source):
    """One table row: what we say, the number, and where it comes from."""
    return f"| {what} | **{value}** | `{source}` |"


def weather_rows(m):
    """Weather intelligence (Phases W1–W4): sky days, temperature effect, waterfall, weather-aware test."""
    if "breakdown" not in m:
        return ["", "## Weather intelligence", "", "_Not built yet — run `python run_all.py`._"]
    weather, temp, breakdown, check = m["weather"], m["temperature"], m["breakdown"], m.get("validation_weather")
    lines = ["", "## Weather intelligence (natural vs fixable losses)", "",
             "| What we say | Number | Source |", "|---|---|---|"]
    for plant in config.PLANTS:
        key = f"plant_{plant}"
        sky, heat, parts = weather["by_plant"][key], temp["by_plant"][key], breakdown["by_plant"][key]
        days = sky["days_by_dominant_sky"]
        lines += [
            row(f"Plant {plant}: clear / partly cloudy / cloudy / overcast days",
                " / ".join(str(days[label]) for label in config.SKY_LABELS), M + " → weather"),
            row(f"Plant {plant}: midday clear-sky index on its 3 sunniest days (≈ 1 = method works)",
                sky["sanity"]["midday_median_csi_3_sunniest_days"], M + " → weather"),
            row(f"Plant {plant}: power lost per +1 °C of panel temperature (95% range)",
                f"{heat['coefficient_pct_per_c']} %/°C ({heat['ci95_pct_per_c'][0]} to {heat['ci95_pct_per_c'][1]})",
                M + " → temperature"),
            row(f"Plant {plant}: hottest panel", f"{heat['hottest_day']['max_module_c']} °C on {heat['hottest_day']['date']}",
                M + " → temperature"),
            row(f"Plant {plant}: energy lost to clouds / heat / faults (% of clear-sky potential)",
                " / ".join(f"{indian(parts[p])} kWh ({parts['pct_of_potential'][n]}%)" for p, n in
                           [("cloud_loss_kwh", "clouds"), ("heat_loss_kwh", "heat"), ("fault_loss_kwh", "faults")]),
                M + " → breakdown"),
            row(f"Plant {plant}: biggest fault day (waterfall)", parts["biggest_fault_loss_day"]["summary"], M + " → breakdown"),
            row(f"Plant {plant}: cloudiest day (waterfall)", parts["biggest_cloud_loss_day"]["summary"], M + " → breakdown"),
        ]
    total = breakdown["total"]
    lines += [
        row("Both plants: natural losses (clouds + heat) vs fixable (faults)",
            f"{indian(total['natural_loss_kwh'])} kWh vs {indian(total['fixable_loss_kwh'])} kWh", M + " → breakdown → total"),
        row("Both plants: actual energy as % of clear-sky potential", f"{total['pct_of_potential']['actual']}%",
            M + " → breakdown → total"),
        row("Typical silicon temperature coefficient (datasheets, for comparison)",
            f"{temp['typical_range_pct_per_c'][0]} to {temp['typical_range_pct_per_c'][1]} %/°C", M + " → temperature")]
    if check:
        by = {(r["setting"], r["version"]): r for r in check["results"]}
        lines += [
            row("Weather-aware rule: false alarms before → after (clean test days)",
                f"{check['false_alarms_before']} → {check['false_alarms_after']}", M + " → validation_weather"),
            row("… real (planted) faults it would have lost", check["injected_faults_lost"], M + " → validation_weather"),
            row("… so the rule is", "OFF (kept honest: we do not trade real faults for fewer alarms)"
                if not check["rule_enabled_in_config"] else "ON", "engine/config.py → WEATHER_AWARE_UNDER"),
            row("Trips planted on cloudy days: caught",
                f"{by[('default', 'before')]['trip_cloudy_day_caught']} of {by[('default', 'before')]['trip_cloudy_day_injected']}",
                M + " → validation_weather")]
    return lines


def main():
    """Collect the numbers and write the markdown file."""
    m = load_metrics()
    data, cleaning, model, alerts = m["data"], m["cleaning"], m["expected_model"], m["alerts"]
    losses, validation = m["losses"], m["validation"]
    daily = pd.read_parquet(config.DAILY_PLANT_FILE)
    tariff = losses["tariff_inr_per_kwh"]

    lines = ["# Key numbers — what we say, and where each number comes from", "",
             "_Generated by `python presentation/make_key_numbers.py` from the pipeline outputs. "
             "Do not edit by hand — re-run it after `python run_all.py`._", "",
             f"₹ values use the **assumed tariff of ₹{tariff}/kWh** (ASSUMPTION — between recent SECI auction prices, sources in reports/assumptions.md). "
             "Always say \"at an assumed tariff\" on stage.", "",
             "## The data", "", "| What we say | Number | Source |", "|---|---|---|"]
    p1, p2 = data["plants"]["plant_1"], data["plants"]["plant_2"]
    lines += [
        row("Solar plants / inverters per plant", f"2 / {p1['inverters']}", M + " → data"),
        row("Days of data, readings every …", f"{p1['days']} days, 15 minutes", M + " → data"),
        row("Rows in the cleaned table", indian(cleaning["total_rows"]), M + " → cleaning"),
        row("Plant 1 DC values too large by (fixed, ASSUMPTION)", f"{cleaning['dc_scale_factor']}×", M + " → cleaning"),
        row("Plant 1 AC÷DC before fix vs Plant 2", f"{p1['ac_dc_ratio_median']} vs {p2['ac_dc_ratio_median']}", M + " → data"),
        row("Readings missing: Plant 1 / Plant 2", f"{p1['missing_pct']}% / {p2['missing_pct']}%", M + " → data"),
        row("Worst Plant 2 inverters miss … of daylight readings",
            f"{p2['worst_missing_daylight'][0]['missing_daylight_pct']}%", M + " → data"),
    ]

    lines += ["", "## The AI model (expected output)", "", "| What we say | Number | Source |", "|---|---|---|"]
    for plant in config.PLANTS:
        info = model[f"plant_{plant}"]
        chosen = info["chosen_model"]
        lines += [
            row(f"Plant {plant}: train → test days", f"{info['train_dates'][0]}…{info['train_dates'][1]} → "
                f"{info['test_dates'][0]}…{info['test_dates'][1]}", M + " → expected_model"),
            row(f"Plant {plant}: chosen model", chosen.replace("_", " "), M + " → expected_model"),
            row(f"Plant {plant}: R² on test days (all / healthy rows)",
                f"{info[chosen]['test_all']['r2']} / {info[chosen]['test_without_obvious_outages']['r2']}",
                M + " → expected_model"),
            row(f"Plant {plant}: physics baseline R² (healthy rows)",
                info["physics"]["test_without_obvious_outages"]["r2"], M + " → expected_model"),
            row(f"Plant {plant}: average error (MAPE, healthy rows)",
                f"{info[chosen]['test_without_obvious_outages']['mape_pct']}%", M + " → expected_model"),
            row(f"Plant {plant}: sunlight's share of the model's decisions",
                f"{round(100 * info['rf_feature_importance']['irradiation'], 1)}%", M + " → expected_model"),
        ]

    lines += ["", "## Faults found", "", "| What we say | Number | Source |", "|---|---|---|",
              row("Alerts in total", alerts["total"], M + " → alerts")]
    lines += [row(f"… {kind.replace('_', ' ').lower()}", count, M + " → alerts") for kind, count in alerts["by_type"].items()]
    lines += [row("Critical alerts", alerts["by_severity"].get("Critical", 0), M + " → alerts"),
              row("Inverters with at least one alert: Plant 1 / Plant 2",
                  f"{alerts['inverters_with_alerts']['plant_1']} / {alerts['inverters_with_alerts']['plant_2']}", M + " → alerts")]

    total = losses["total"]
    lines += ["", "## Losses", "", "| What we say | Number | Source |", "|---|---|---|",
              row("Energy lost to detected faults (all days)", f"{indian(total['fault_loss_kwh'])} kWh", M + " → losses"),
              row(f"… in money at ₹{tariff}/kWh (assumed)", f"₹{indian(total['fault_loss_inr'])}", M + " → losses"),
              row("Energy at risk (data gaps, not confirmed)", f"{indian(total['at_risk_kwh'])} kWh", M + " → losses"),
              row("Projected per year if nothing is fixed (ESTIMATE)",
                  f"{indian(total['projected_annual_fault_loss_kwh'])} kWh ≈ ₹{indian(total['projected_annual_fault_loss_inr'])}",
                  M + " → losses")]
    for plant in config.PLANTS:
        info = losses["by_plant"][f"plant_{plant}"]
        lines.append(row(f"Plant {plant}: actual vs expected over all days / energy lost",
                         f"{round(100 * info['performance_ratio'])}% / {indian(info['fault_loss_kwh'])} kWh", M + " → losses"))
    trips = losses["by_fault_type"]["INVERTER_TRIP"]["fault_loss_kwh"]
    lines.append(row("Share of energy lost caused by inverter trips", f"{round(100 * trips / total['fault_loss_kwh'])}%",
                     M + " → losses"))
    worst = losses["top_inverters"][0]
    lines.append(row("Worst inverter (Plant, id): energy lost, alerts",
                     f"Plant {worst['plant']}, {worst['inverter']}: {indian(worst['fault_loss_kwh'])} kWh, {worst['alerts']} alerts",
                     M + " → losses"))
    for plant in config.PLANTS:
        days = daily[daily["plant"] == plant]
        day = days.loc[days["fault_loss_kwh"].idxmax()]
        lines.append(row(f"Plant {plant}: worst day (default replay date)",
                         f"{day['date']}: {indian(day['fault_loss_kwh'])} kWh, actual vs expected {round(100 * day['performance_ratio'])}%",
                         "data/processed/daily_plant.parquet"))

    lines += ["", "## Proof: planted-fault validation", "", "| What we say | Number | Source |", "|---|---|---|"]
    for fault, s in validation["by_fault"].items():
        delay = "end of period" if s["avg_delay_minutes"] is None else f"{round(s['avg_delay_minutes'])} min"
        lines.append(row(f"{fault.replace('_', ' ').capitalize()}: caught / false alarms / time to alert",
                         f"{s['recall_pct']}% of {s['injections']} / {s['false_alarms']} / {delay}", M + " → validation"))
    small = list(validation["by_fault"]["underperformance"]["recall_by_size_pct"].values())[-1]
    lines.append(row("Small underperformance (keeps ≥ 80% of output) caught", f"{small['recall_pct']}%", M + " → validation"))
    sensitive = next(t for t in validation["threshold_tradeoff"] if t["setting"] == "sensitive" and t["fault"] == "underperformance")
    lines.append(row("Most sensitive setting: caught / false alarms",
                     f"{sensitive['recall_pct']}% / {sensitive['false_alarms_on_clean_days']}", M + " → validation"))

    lines += weather_rows(m)

    lines += ["", "## External facts to cite (NOT from our data — find a source before using)", "",
              "Do **not** say any of these on stage without a cited source (title, organisation, year, link):", "",
              "- [ ] India's installed solar capacity (e.g. from MNRE or CEA) — TODO(team)",
              "- [ ] Typical energy lost to dust/soiling on Indian solar plants (%/year or %/day) — TODO(team)",
              "- [x] Tariff: ₹3/kWh sits between SECI solar + storage ₹2.86/kWh (Oct 2025) and SECI rooftop "
              "₹3.34/kWh (Dec 2025) — links in reports/assumptions.md",
              "- [ ] Typical inverter downtime / O&M cost figures, if we mention the cost of late detection — TODO(team)",
              "- [x] Licence of the Kaggle dataset: \"Data files © Original Authors\" (Kaggle dataset page)", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
