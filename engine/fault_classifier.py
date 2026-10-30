"""AI model 3: a fault-type classifier — "what kind of fault does this look like?"

Run from the solarsense folder with:   python -m engine.fault_classifier
We have no labelled faults, so we make our own training examples: take healthy inverter-days, plant a
known fault (trip, underperformance, data gap, soiling, overheating) or leave them healthy, describe each
window with 11 simple numbers, and train a Random Forest classifier.
Honest test: trained on EARLY days, scored on LATER days it never saw. Then every real alert gets a
second opinion ("AI diagnosis") with a confidence %. The rules still raise the alerts; the AI only advises.
"""

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix

from engine import config
from engine.metrics import save_metrics_section

CLASSES = ["healthy", "trip", "underperformance", "data_gap", "soiling", "overheating"]
FEATURES = ["duration_hours", "mean_ratio", "min_ratio", "ratio_spread", "zero_share", "missing_share",
            "peer_ratio", "plant_ratio", "temp_rise_c", "mean_sun", "start_hour"]


def window_features(rows):
    """Describe one inverter's time window with 11 numbers (what an engineer would look at)."""
    usable = (~rows["is_missing"]) & (rows["expected_kw"] >= config.MIN_EXPECTED_KW_FOR_RATIO)
    ratio = (rows["ac_kw"] / rows["expected_kw"])[usable]                 # actual ÷ expected
    peers = (ratio / rows["peer_median_ratio"][usable]).replace([np.inf, -np.inf], np.nan)
    first = rows["timestamp"].min()
    value = lambda x: float(x) if pd.notna(x) else -1.0                   # "no data" is its own signal
    return {"duration_hours": len(rows) * config.INTERVAL_HOURS,
            "mean_ratio": value(ratio.mean()), "min_ratio": value(ratio.min()), "ratio_spread": value(ratio.std()),
            "zero_share": float((ratio < 0.05).mean()) if len(ratio) else -1.0,
            "missing_share": float(rows["is_missing"].mean()),
            "peer_ratio": value(peers.mean()), "plant_ratio": value(rows["peer_median_ratio"].mean()),
            "temp_rise_c": value((rows["module_temp"] - rows["ambient_temp"]).mean()),
            "mean_sun": value(rows["irradiation"].mean()), "start_hour": first.hour + first.minute / 60}


def plant_fault(rows, label, rng):
    """Return a copy of the window with one fault planted in it (or untouched for "healthy")."""
    rows, sizes = rows.copy(), config.CLASSIFIER_FAULT_SIZES
    if label == "trip":
        rows["ac_kw"] = 0.0
    elif label == "data_gap":
        rows["ac_kw"], rows["is_missing"] = np.nan, True
    elif label in ("underperformance", "soiling"):
        rows["ac_kw"] *= rng.uniform(*sizes[f"{label}_kept"])
    elif label == "overheating":
        rows["module_temp"] += rng.uniform(*sizes["overheating_extra_temp_c"])
        rows["ac_kw"] *= rng.uniform(*sizes["overheating_kept"])
    return rows


def pick_window(day_rows, label, rng):
    """A random stretch of daylight; soiling covers most of the day (dust does not come and go)."""
    sunny = day_rows[day_rows["expected_kw"] >= config.MIN_EXPECTED_KW_FOR_RATIO]
    if label == "soiling":
        return sunny
    if label == "overheating":   # heat problems show up in the hot middle of the day
        sunny = sunny[sunny["timestamp"].dt.hour.between(10, 15)]
    length = int(rng.uniform(*config.CLASSIFIER_WINDOW_HOURS) / config.INTERVAL_HOURS)
    if len(sunny) <= length:
        return sunny
    start = int(rng.integers(len(sunny) - length))
    return sunny.iloc[start:start + length]


def healthy_days(table):
    """Inverter-days with no alert of any kind (so the "healthy" examples really are healthy)."""
    alerts = pd.read_parquet(config.ALERTS_FILE)
    busy = set()
    for a in alerts[alerts["inverter"] != "ALL"].itertuples():
        for day in pd.date_range(a.start.normalize(), (a.end - pd.Timedelta(minutes=1)).normalize()):
            busy.add((a.plant, a.inverter, str(day.date())))
    return {key: rows for key, rows in table.groupby(["plant", "inverter", "date"]) if key not in busy}


def make_examples(days, rng):
    """Plant every fault type CLASSIFIER_SAMPLES_PER_DAY times on every healthy day → labelled table."""
    examples = []
    for (plant, _, date), day_rows in days.items():
        for label in CLASSES:
            for _ in range(config.CLASSIFIER_SAMPLES_PER_DAY):
                window = pick_window(day_rows, label, rng)
                if len(window) >= 2:
                    examples.append({**window_features(plant_fault(window, label, rng)),
                                     "label": label, "plant": plant, "date": date})
    return pd.DataFrame(examples)


def per_class_scores(truth, predicted):
    """Recall (planted faults named correctly) and precision (AI's answers that were right) per class."""
    scores = {}
    for label in CLASSES:
        named = predicted == label
        actual = truth == label
        scores[label] = {"examples": int(actual.sum()),
                         "recall_pct": round(100 * float((named & actual).sum()) / max(int(actual.sum()), 1), 1),
                         "precision_pct": round(100 * float((named & actual).sum()) / max(int(named.sum()), 1), 1)}
    return scores


def diagnose_alerts(model, table):
    """Give every real per-inverter alert an AI diagnosis + confidence, and say if it agrees with the rules."""
    alerts = pd.read_parquet(config.ALERTS_FILE)
    by_inverter = {key: rows for key, rows in table.groupby(["plant", "inverter"])}
    diagnosis, confidence = [], []
    for a in alerts.itertuples():
        rows = by_inverter.get((a.plant, a.inverter))
        rows = None if rows is None else rows[(rows["timestamp"] >= a.start) & (rows["timestamp"] < a.end)]
        if rows is None or len(rows) == 0 or a.fault_type not in config.CLASSIFIER_TYPE_FOR_ALERT:
            diagnosis.append(None), confidence.append(np.nan)
            continue
        probabilities = model.predict_proba(pd.DataFrame([window_features(rows)])[FEATURES])[0]
        best = int(np.argmax(probabilities))
        diagnosis.append(model.classes_[best]), confidence.append(round(100 * float(probabilities[best]), 1))
    alerts["ai_diagnosis"], alerts["ai_confidence_pct"] = diagnosis, confidence
    expected = alerts["fault_type"].map(config.CLASSIFIER_TYPE_FOR_ALERT)
    alerts["ai_agrees"] = np.where(alerts["ai_diagnosis"].isna(), None, alerts["ai_diagnosis"] == expected)
    alerts.to_parquet(config.ALERTS_FILE, index=False)
    checked = alerts[alerts["ai_diagnosis"].notna()]
    return {"alerts_checked": int(len(checked)),
            "agree_pct": round(100 * float(checked["ai_agrees"].astype(bool).mean()), 1) if len(checked) else None,
            "agree_pct_by_type": {t: round(100 * float(g["ai_agrees"].astype(bool).mean()), 1)
                                  for t, g in checked.groupby("fault_type")}}


def train_fault_classifier():
    """Make examples, train on early days, test on later days, save the model and diagnose real alerts."""
    rng = np.random.default_rng(config.RANDOM_SEED)
    table = pd.read_parquet(config.EXPECTED_FILE)
    examples = make_examples(healthy_days(table), rng)
    train, test = examples[examples["date"].isin(set(table.loc[table["split"] == "train", "date"]))], \
        examples[examples["date"].isin(set(table.loc[table["split"] == "test", "date"]))]

    model = RandomForestClassifier(n_estimators=config.CLASSIFIER_N_ESTIMATORS, min_samples_leaf=2,
                                   random_state=config.RANDOM_SEED, n_jobs=-1)
    model.fit(train[FEATURES], train["label"])
    predicted = model.predict(test[FEATURES])
    joblib.dump({"model": model, "features": FEATURES, "classes": CLASSES}, config.FAULT_CLASSIFIER_FILE)

    results = {
        "method": "Random Forest classifier trained on faults we planted into healthy inverter-days "
                  "(early days), tested on planted faults from later days it never saw.",
        "classes": CLASSES, "train_examples": int(len(train)), "test_examples": int(len(test)),
        "test_accuracy_pct": round(100 * accuracy_score(test["label"], predicted), 1),
        "by_class": per_class_scores(test["label"].to_numpy(), predicted),
        "confusion_matrix": {"rows_are": "planted fault", "columns_are": "AI said", "labels": CLASSES,
                             "counts": confusion_matrix(test["label"], predicted, labels=CLASSES).tolist()},
        "feature_importance": dict(sorted(((f, round(float(v), 3)) for f, v in
                                           zip(FEATURES, model.feature_importances_)), key=lambda x: -x[1])),
        "real_alerts": diagnose_alerts(model, table),
        "caveat": "Trained and tested on planted faults: real faults can look messier. The AI diagnosis is a "
                  "second opinion; the rule-based detector still decides which alerts are raised.",
    }
    save_metrics_section("fault_classifier", results)
    return results


if __name__ == "__main__":
    out = train_fault_classifier()
    print(f"Examples: {out['train_examples']} train / {out['test_examples']} test | "
          f"test accuracy {out['test_accuracy_pct']}%")
    for label, s in out["by_class"].items():
        print(f"  {label:17s} recall {s['recall_pct']:5.1f}%  precision {s['precision_pct']:5.1f}%  ({s['examples']})")
    print("Top features:", list(out["feature_importance"].items())[:4])
    print("Real alerts:", out["real_alerts"])
