"""Rebuild EVERYTHING from the 4 raw Kaggle CSVs with one command.

Run from the solarsense folder (with the virtual environment active):
    python run_all.py                     # full rebuild, about 3 minutes
    python run_all.py --skip-validation   # quicker (~15 s): skips both injected-fault tests

Steps: data quality → clean → expected-output model → weather (sky + heat) → fault detection → unusual-day
score → losses → energy waterfall → validation → weather-aware
validation (before/after).
Each step reads the previous step's files, so the order matters: fault detection uses the sky from the
weather step, and the waterfall needs both the heat loss (weather) and the fault losses (losses).
"""

import argparse
import sys
import time

from engine import config


def check_raw_data():
    """Stop early with a friendly message if any raw CSV is missing."""
    missing = [path.name for path in config.RAW_FILES.values() if not path.exists()]
    if missing:
        sys.exit("Raw data not found: " + ", ".join(missing) +
                 "\nDownload the 4 Kaggle CSVs ('Solar Power Generation Data' by anikannal) into data/raw/ — see README.md.")


def make_folders():
    """Create the output folders (they may not exist on a fresh copy of the project)."""
    for folder in [config.PROCESSED_DIR, config.MODELS_DIR, config.REPORTS_DIR, config.FIGURES_DIR]:
        folder.mkdir(parents=True, exist_ok=True)


def pipeline_steps(skip_validation):
    """The steps in order: (name, function). Imports happen here so a broken step names itself clearly."""
    from engine.anomaly_score import run as anomaly_score
    from engine.clean_data import clean_all
    from engine.detect_faults import detect_all
    from engine.expected_model import build_expected_table
    from engine.fault_classifier import train_fault_classifier
    from engine.model_updates import run_model_updates
    from engine.explore_data import explore
    from engine.losses import compute_losses
    from engine.energy_breakdown import compute_breakdown
    from engine.validate import validate
    from engine.validate_weather import validate_weather
    from engine.weather import build_weather

    steps = [("1. Data quality report", explore),
             ("2. Clean and merge", clean_all),
             ("3. Expected-output model", build_expected_table),
             ("4. Weather: sky from sunlight + heat loss", build_weather),
             ("5. Fault detection (with the sky for every alert)", detect_all),
             ("6. Unusual-day score (optional hint)", anomaly_score),
             ("7. Energy and money losses", compute_losses),
             ("8. Energy waterfall: natural vs fixable losses", compute_breakdown),
             ("9. AI fault classifier (second opinion on every alert)", train_fault_classifier),
             ("10. Self-updating model test (retrain daily vs once)", run_model_updates)]
    if not skip_validation:
        steps += [("11. Validation with injected faults", validate),
                  ("12. Weather-aware detection: before/after test", validate_weather)]
    return steps


def print_summary():
    """Print the key numbers every judge question is about (all read from reports/metrics.json)."""
    from engine.metrics import load_metrics
    m = load_metrics()
    print("\n================ SUMMARY (from reports/metrics.json) ================")
    print(f"Clean table: {m['cleaning']['total_rows']:,} rows; Plant {config.DC_SUSPECT_PLANT} DC scaled by "
          f"{m['cleaning']['dc_scale_factor']} (ASSUMPTION)")
    for plant in config.PLANTS:
        info = m["expected_model"][f"plant_{plant}"]
        chosen = info["chosen_model"]
        print(f"Plant {plant} model: {chosen}, test R² {info[chosen]['test_all']['r2']} "
              f"({info[chosen]['test_without_obvious_outages']['r2']} without outages)")
    print(f"Alerts: {m['alerts']['total']} → {m['alerts']['by_type']}")
    total = m["losses"]["total"]
    print(f"Energy lost to faults: {total['fault_loss_kwh']:,.0f} kWh (₹{total['fault_loss_inr']:,.0f} at "
          f"₹{m['losses']['tariff_inr_per_kwh']}/kWh, assumed); at risk (data gaps): {total['at_risk_kwh']:,.0f} kWh")
    if "validation" in m:
        recall = {fault: f"{v['recall_pct']}%" for fault, v in m["validation"]["by_fault"].items()}
        print(f"Validation (planted faults caught): {recall}")
    for plant in config.PLANTS:
        sky, heat = m["weather"]["by_plant"][f"plant_{plant}"], m["temperature"]["by_plant"][f"plant_{plant}"]
        print(f"Plant {plant} sky by day {sky['days_by_dominant_sky']}; heat costs {heat['coefficient_pct_per_c']} %/°C "
              f"(95% {heat['ci95_pct_per_c']})")
    pct = m["breakdown"]["total"]["pct_of_potential"]
    print(f"Waterfall (both plants, % of clear-sky potential): clouds {pct['clouds']}%, heat {pct['heat']}%, "
          f"faults {pct['faults']}%, not measured {pct['not measured']}%, other {pct['other']}% → actual {pct['actual']}%")
    if "validation_weather" in m:
        print(f"Weather-aware rule: {m['validation_weather']['verdict']}")
    print("Next: run `pytest`, then `uvicorn api.main:app --reload` and open http://localhost:8000")


def main():
    """Run every step in order, timing each one; stop with a clear message if a step fails."""
    parser = argparse.ArgumentParser(description="Rebuild all SolarSense results from the raw data.")
    parser.add_argument("--skip-validation", action="store_true", help="skip the slow injected-fault test")
    args = parser.parse_args()

    check_raw_data()
    make_folders()
    started = time.time()
    for name, step in pipeline_steps(args.skip_validation):
        print(f"\n▶ {name} …", flush=True)
        step_started = time.time()
        try:
            step()
        except Exception as error:   # show which step broke, in plain words, then the real error
            print(f"\n✖ Step '{name}' failed: {error}")
            raise
        print(f"  ✔ done in {time.time() - step_started:.1f} s")
    print(f"\nAll steps finished in {time.time() - started:.0f} s.")
    print_summary()


if __name__ == "__main__":
    # Windows terminals sometimes cannot print ₹ or ✔; this makes printing always safe.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
