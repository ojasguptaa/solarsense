"""Self-updating model test: does retraining on new days ("fine-tuning") keep the model accurate?

Run from the solarsense folder with:   python -m engine.model_updates
Real plants change over time (dust builds up, panels age, the season moves on). We replay the 34 days
as if they arrive one by one and compare two expected-output models on each NEXT day:
  - "trained once":     Random Forest trained on the first UPDATES_FIRST_TRAIN_DAYS days, never updated
  - "retrained daily":  the same model, retrained every night on ALL days seen so far
Both are always scored on a day they have never seen (honest walk-forward test).
"""

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

from engine import config
from engine.expected_model import RF_FEATURES, is_obvious_outage, load_daylight_rows
from engine.metrics import save_metrics_section


def train(rows):
    """A Random Forest expected-output model (same features as the main model, smaller forest)."""
    model = RandomForestRegressor(n_estimators=config.UPDATES_N_ESTIMATORS, max_depth=config.RF_MAX_DEPTH,
                                  min_samples_leaf=config.RF_MIN_SAMPLES_LEAF, random_state=config.RANDOM_SEED,
                                  n_jobs=-1)
    model.fit(rows[RF_FEATURES], rows["ac_kw"])
    return model


def error_pct(model, rows):
    """Average error as % of average output (lower = better), on healthy readings only."""
    predicted = model.predict(rows[RF_FEATURES]).clip(0)
    return round(100 * mean_absolute_error(rows["ac_kw"], predicted) / rows["ac_kw"].mean(), 2), \
        round(float(r2_score(rows["ac_kw"], predicted)), 4)


def walk_forward(plant_rows):
    """Score both models on every day after the first training days; one row per day."""
    usable = plant_rows[~plant_rows["is_missing"] & ~is_obvious_outage(plant_rows)]
    days = sorted(usable["date"].unique())
    first = days[:config.UPDATES_FIRST_TRAIN_DAYS]
    fixed = train(usable[usable["date"].isin(first)])
    results = []
    for index in range(config.UPDATES_FIRST_TRAIN_DAYS, len(days)):
        today = usable[usable["date"] == days[index]]
        retrained = train(usable[usable["date"].isin(days[:index])])   # everything up to yesterday
        fixed_err, fixed_r2 = error_pct(fixed, today)
        new_err, new_r2 = error_pct(retrained, today)
        results.append({"date": days[index], "days_of_training": index,
                        "trained_once_error_pct": fixed_err, "retrained_error_pct": new_err,
                        "trained_once_r2": fixed_r2, "retrained_r2": new_r2})
    return pd.DataFrame(results)


def run_model_updates():
    """Walk forward for each plant and save the daily comparison to metrics.json."""
    rows = load_daylight_rows()
    output = {"method": f"Both models start from the first {config.UPDATES_FIRST_TRAIN_DAYS} days. Each later day "
                        "is predicted before the model sees it; the retrained model then learns that day too.",
              "by_plant": {}}
    for plant in config.PLANTS:
        plant_rows = rows[rows["plant"] == plant].copy()
        codes = {inv: code for code, inv in enumerate(sorted(plant_rows["inverter"].unique()))}
        plant_rows["inverter_code"] = plant_rows["inverter"].map(codes)
        daily = walk_forward(plant_rows)
        once, again = daily["trained_once_error_pct"].mean(), daily["retrained_error_pct"].mean()
        last_week = daily.tail(7)
        output["by_plant"][f"plant_{plant}"] = {
            "avg_error_trained_once_pct": round(float(once), 2), "avg_error_retrained_pct": round(float(again), 2),
            "error_reduction_pct": round(float(100 * (once - again) / once), 1),
            "last_7_days_error_trained_once_pct": round(float(last_week["trained_once_error_pct"].mean()), 2),
            "last_7_days_error_retrained_pct": round(float(last_week["retrained_error_pct"].mean()), 2),
            "days": daily.to_dict(orient="records")}
    save_metrics_section("model_updates", output)
    return output


if __name__ == "__main__":
    result = run_model_updates()
    for plant, info in result["by_plant"].items():
        print(f"{plant}: error trained once {info['avg_error_trained_once_pct']}% vs retrained daily "
              f"{info['avg_error_retrained_pct']}% ({info['error_reduction_pct']}% better); last 7 days "
              f"{info['last_7_days_error_trained_once_pct']}% vs {info['last_7_days_error_retrained_pct']}%")
