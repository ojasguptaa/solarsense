"""AI model 3 (fault classifier) and the daily-retraining test: saved results make sense and reach the API."""

import joblib
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from api.main import app
from engine import config
from engine.fault_classifier import CLASSES, plant_fault, window_features
from tests.conftest import log_in


def test_classifier_names_a_planted_trip():
    """Plant a trip into a healthy-looking window: the saved model should call it a trip."""
    saved = joblib.load(config.FAULT_CLASSIFIER_FILE)
    table = pd.read_parquet(config.EXPECTED_FILE)
    sunny = table[(table["expected_kw"] > 300) & ~table["is_missing"]]
    window = sunny[sunny["inverter"] == sunny["inverter"].iloc[0]].head(8)
    broken = plant_fault(window, "trip", np.random.default_rng(0))
    features = pd.DataFrame([window_features(broken)])[saved["features"]]
    assert saved["model"].predict(features)[0] == "trip"


def test_ai_models_endpoint_and_alert_diagnosis():
    """The About page endpoint returns all three models; alerts carry an AI diagnosis from the known classes."""
    with TestClient(app) as client:
        log_in(client)
        body = client.get("/api/ai_models").json()
        fc = body["fault_classifier"]
        assert fc["test_accuracy_pct"] > 80
        assert sum(map(sum, fc["confusion_matrix"]["counts"])) == fc["test_examples"]
        for plant in body["model_updates"]["by_plant"].values():
            assert len(plant["days"]) > 10 and plant["avg_error_retrained_pct"] > 0
        alerts = client.get("/api/alerts").json()["alerts"]
        diagnosed = [a for a in alerts if a.get("ai_diagnosis")]
        assert diagnosed and all(a["ai_diagnosis"] in CLASSES for a in diagnosed)
        assert all(0 <= a["ai_confidence_pct"] <= 100 for a in diagnosed)
