"""Central settings for SolarSense: file paths and important constants.

Every other file imports its settings from here, so a number only ever
needs to be changed in one place. Fault-detection thresholds are added in Phase 4.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Folders (built from this file's location, so they work on any laptop)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"              # the 4 Kaggle CSVs — never edited
PROCESSED_DIR = DATA_DIR / "processed"  # files our pipeline creates
MODELS_DIR = PROJECT_ROOT / "models"
REPORTS_DIR = PROJECT_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
WEB_DIR = PROJECT_ROOT / "web"

# ---------------------------------------------------------------------------
# Raw input files (Kaggle "Solar Power Generation Data" by anikannal)
# ---------------------------------------------------------------------------
RAW_FILES = {
    "plant_1_generation": RAW_DIR / "Plant_1_Generation_Data.csv",
    "plant_1_weather": RAW_DIR / "Plant_1_Weather_Sensor_Data.csv",
    "plant_2_generation": RAW_DIR / "Plant_2_Generation_Data.csv",
    "plant_2_weather": RAW_DIR / "Plant_2_Weather_Sensor_Data.csv",
}

# The files do NOT all use the same date format, so we state each one
# explicitly instead of letting pandas guess (guessing can swap day/month).
DATE_FORMATS = {
    "plant_1_generation": "%d-%m-%Y %H:%M",       # e.g. 15-05-2020 00:00
    "plant_1_weather": "%Y-%m-%d %H:%M:%S",       # e.g. 2020-05-15 00:00:00
    "plant_2_generation": "%Y-%m-%d %H:%M:%S",
    "plant_2_weather": "%Y-%m-%d %H:%M:%S",
}

PLANTS = [1, 2]

# ---------------------------------------------------------------------------
# Output files (created by later phases)
# ---------------------------------------------------------------------------
CLEAN_FILE = PROCESSED_DIR / "clean.parquet"
EXPECTED_FILE = PROCESSED_DIR / "expected.parquet"
ALERTS_FILE = PROCESSED_DIR / "alerts.parquet"
ALERT_STATUS_FILE = PROCESSED_DIR / "alert_status.json"
METRICS_FILE = REPORTS_DIR / "metrics.json"
DATA_QUALITY_REPORT = REPORTS_DIR / "data_quality.md"
MODEL_CARD = REPORTS_DIR / "model_card.md"
ASSUMPTIONS_REPORT = REPORTS_DIR / "assumptions.md"

# ---------------------------------------------------------------------------
# General constants
# ---------------------------------------------------------------------------
# Fixed random seed so every run gives the same results (reproducible).
RANDOM_SEED = 42

# The data has one reading every 15 minutes = 0.25 hours.
# Energy (kWh) = power (kW) x time (hours), so we multiply by this.
INTERVAL_HOURS = 0.25

# Readings per day: 24 hours x 4 readings per hour.
READINGS_PER_DAY = 96

# A 15-minute slot counts as "daylight" when the weather sensor's irradiation
# is above this value. Small but above zero, so sensor noise at dawn/dusk
# does not count as sunshine. (Irradiation units in this dataset: ~kW/m².)
DAYLIGHT_IRRADIATION_THRESHOLD = 0.02

# Hours we treat as "definitely night" for sanity checks (20:00 to 04:59).
NIGHT_HOURS = [20, 21, 22, 23, 0, 1, 2, 3, 4]

# ASSUMPTION: electricity value used to convert lost energy (kWh) into rupees.
# This is only a placeholder. Set it to a sourced value (e.g. a recent Indian
# solar tariff) and record the source in reports/assumptions.md.
# TODO(team): find and cite a source for this number.
TARIFF_INR_PER_KWH = 3.0

# ---------------------------------------------------------------------------
# Phase 2 — cleaning
# ---------------------------------------------------------------------------
# Plant 1 DC is fixed by a factor COMPUTED from the data (see clean_data.py):
# we use Plant 2 (whose DC looks normal) as the reference plant.
DC_REFERENCE_PLANT = 2
DC_SUSPECT_PLANT = 1

# ---------------------------------------------------------------------------
# Phase 3 — expected-output model
# ---------------------------------------------------------------------------
# First 70% of days train the model, the last 30% test it (time split, never random).
TRAIN_FRACTION = 0.7

# "Obvious outage" (removed from TRAINING only so the model learns healthy
# behaviour): sunlight is clearly strong but the inverter gives almost nothing.
OUTAGE_IRRADIATION_MIN = 0.3   # strong sunlight (noon is ~1.0)
OUTAGE_AC_MAX_KW = 1.0         # inverters make ~1,300 kW per unit of irradiation

# MAPE (average % error) is only measured on rows with meaningful power,
# because a % error on a tiny number (e.g. 2 kW at dawn) is huge and misleading.
MAPE_MIN_ACTUAL_KW = 100.0

# Ratios like actual ÷ expected are only computed when expected is above this,
# to avoid dividing by almost zero at dawn and dusk.
MIN_EXPECTED_KW_FOR_RATIO = 50.0

# Random Forest settings: small enough to train in seconds on a laptop.
RF_N_ESTIMATORS = 100
RF_MAX_DEPTH = 14
RF_MIN_SAMPLES_LEAF = 5

# Model files
MODEL_FILE_TEMPLATE = "plant_{plant}_{model}.joblib"

# ---------------------------------------------------------------------------
# Phase 4 — fault detection (all thresholds in one place)
# ---------------------------------------------------------------------------
# Two flagged readings separated by at most this many un-flagged readings still
# count as ONE event (so one noisy 15-minute reading does not split an alert).
MERGE_GAP_INTERVALS = 1

# INVERTER_TRIP: strong sunlight but (almost) no output.
TRIP_IRRADIATION_MIN = 0.25    # sunlight clearly strong enough to produce power
TRIP_AC_MAX_KW = 1.0           # "almost zero" output
TRIP_MIN_INTERVALS = 2         # at least 30 minutes

# UNDERPERFORMANCE: clearly below expected AND below neighbours (so not a cloud).
UNDER_RESIDUAL_PCT_MAX = -20.0  # actual at least 20% below expected
UNDER_PEER_RATIO_MAX = 0.8      # and at least 20% below the plant median
UNDER_MIN_INTERVALS = 4         # at least 1 hour

# DEGRADATION / SOILING: slow, steady decline of daily performance vs peers.
DEGRADATION_MIN_DAYS = 10            # need enough days for a trend
DEGRADATION_SLOPE_MAX_PCT = -0.3     # falling by at least 0.3% per day...
DEGRADATION_MIN_TOTAL_DECLINE_PCT = 5.0  # ...and at least 5% in total

# DATA_GAP: inverter silent during daylight.
GAP_MIN_INTERVALS = 2          # at least 30 minutes

# OVERHEATING (plant-level: there is only ONE panel-temperature sensor per plant).
OVERHEAT_DELTA_MIN_C = 28.0    # panels this much hotter than the air (top ~1% of readings)
OVERHEAT_PLANT_RATIO_MAX = 0.9 # and the whole plant below 90% of expected
OVERHEAT_MIN_INTERVALS = 2

# SEVERITY: decided by energy lost (kWh) — one inverter makes ~1,000 kWh in a sunny hour.
SEVERITY_LOSS_KWH = [(2000, "Critical"), (500, "High"), (100, "Medium"), (0, "Low")]
# Data gaps have no confirmed loss, so they are rated by daylight hours silent,
# and never above "High" (we cannot prove energy was lost, only that we can't see it).
SEVERITY_GAP_HOURS = [(4, "High"), (1, "Medium"), (0, "Low")]
# An event lasting this long is raised one severity level (long problems matter more).
SEVERITY_LONG_EVENT_HOURS = 4.0
SEVERITY_LEVELS = ["Low", "Medium", "High", "Critical"]

# ---------------------------------------------------------------------------
# Phase 5 — optional "unusual day" score (Isolation Forest)
# ---------------------------------------------------------------------------
# ASSUMPTION: share of inverter-days we expect to be unusual. Isolation Forest
# needs this to decide where "odd" starts; there are no labels to measure it.
ANOMALY_CONTAMINATION = 0.05
ANOMALY_N_ESTIMATORS = 200
ANOMALY_DAYS_FILE = PROCESSED_DIR / "anomaly_days.parquet"

# ---------------------------------------------------------------------------
# Phase 6 — energy and money loss
# ---------------------------------------------------------------------------
DAILY_PLANT_FILE = PROCESSED_DIR / "daily_plant.parquet"
DAILY_INVERTER_FILE = PROCESSED_DIR / "daily_inverter.parquet"
TOP_N_INVERTERS = 5
# ASSUMPTION (estimate): "projected annual loss" scales the observed period to
# a full year, as if every day were like the May–June days in the data.
DAYS_PER_YEAR = 365

# ---------------------------------------------------------------------------
# Phase 7 — validation with injected (synthetic) faults
# ---------------------------------------------------------------------------
VALIDATION_RUNS = 5            # repeats with different seeds (more samples)
VALIDATION_SOILING_RUNS = 10   # soiling runs (2 inverters each)
VALIDATION_INJECTIONS_FILE = PROCESSED_DIR / "validation_injections.parquet"
VALIDATION_TRADEOFF_FILE = PROCESSED_DIR / "validation_tradeoff.parquet"
# Three threshold settings for the sensitivity trade-off test.
VALIDATION_THRESHOLD_SETTINGS = {
    "sensitive": {"UNDER_RESIDUAL_PCT_MAX": -10.0, "UNDER_PEER_RATIO_MAX": 0.9,
                  "UNDER_MIN_INTERVALS": 2, "TRIP_MIN_INTERVALS": 1},
    "default": {},
    "strict": {"UNDER_RESIDUAL_PCT_MAX": -30.0, "UNDER_PEER_RATIO_MAX": 0.7,
               "UNDER_MIN_INTERVALS": 8, "TRIP_MIN_INTERVALS": 4},
}
# Size of each planted fault: (smallest, largest). Durations are picked in 15-minute steps.
VALIDATION_FAULT_SIZES = {
    "trip_hours": (1.0, 4.0),                    # output set to 0 around midday
    "trip_centre_hour": 12,                      # trips are centred on noon (± 1 hour)
    "underperformance_hours": (2.0, 6.0),
    "underperformance_output_kept": (0.6, 0.85), # output multiplied by this
    "data_gap_hours": (1.0, 3.0),                # readings removed
    "soiling_pct_per_day": (0.3, 1.0),           # gradual decline over the test days
    "window_hours": (7, 17),                     # underperformance / gaps happen between 07:00 and 17:00
}
# Groups used to show "what is easy vs hard to catch" (edges of each size group).
VALIDATION_SIZE_BUCKETS = {
    "trip": ("hours", [1, 2, 3, 4.01]),
    "underperformance": ("output kept", [0.6, 0.7, 0.8, 0.851]),
    "data_gap": ("hours", [1, 1.75, 2.5, 3.01]),
    "soiling": ("% per day", [0.3, 0.5, 0.75, 1.01]),
}

# Charts: how many test points to draw in the predicted-vs-actual scatter (keeps the PNG readable).
SCATTER_SAMPLE_POINTS = 5000

# ---------------------------------------------------------------------------
# Phase W1 — sky condition from sunlight (engine/weather.py)
# ---------------------------------------------------------------------------
# The dataset has no cloud sensor, so we read the sky from the sunlight itself.
WEATHER_15MIN_FILE = PROCESSED_DIR / "weather_15min.parquet"
WEATHER_DAILY_FILE = PROCESSED_DIR / "weather_daily.parquet"

# ASSUMPTION: "clear-sky sunlight" at a time of day = this percentile of all 34 days
# at that time. Not the maximum, so one odd spike (e.g. sunlight reflected off a
# cloud edge) cannot set the reference. With 34 days, 95% ≈ the 2nd-highest day.
CLEAR_SKY_PERCENTILE = 95
# The percentile curve is a little bumpy, so we smooth it with a centred rolling
# mean of this many 15-minute slots (5 = 1¼ hours) to get a clean bell curve.
CLEAR_SKY_SMOOTH_SLOTS = 5

# We only judge the sky when a clear sky would give at least this much sunlight.
# At dawn/dusk the sunlight is tiny, so actual ÷ clear-sky becomes random noise.
SKY_MIN_CLEAR_SKY_IRR = 0.1
# Clear-sky index (CSI) = actual ÷ clear-sky sunlight, clipped to this range
# (a little above 1 is real: sunlight can bounce off cloud edges).
CSI_CLIP = (0.0, 1.2)
# Variability = how much the CSI jumps between readings (std of its change),
# measured over this many changes, centred on the reading (4 changes = 1 hour).
VARIABILITY_WINDOW_SLOTS = 4

# Sky labels for each 15-minute reading (CSI = clear-sky index):
CSI_CLEAR_MIN = 0.8            # CSI ≥ 0.8 → Clear (if the sunlight is also steady)
CSI_PARTLY_MIN = 0.5           # 0.5 – 0.8 → Partly cloudy
CSI_CLOUDY_MIN = 0.3           # 0.3 – 0.5 → Cloudy;  below 0.3 → Overcast
# A "clear" reading whose sunlight jumps more than this is really passing clouds
# → Partly cloudy. (Steady clear sky changes by only a few % between readings.)
VARIABILITY_CLEAR_MAX = 0.1
SKY_LABELS = ["Clear", "Partly cloudy", "Cloudy", "Overcast"]

# The day's sentence says "clouds after 2 PM" only if the part after the change
# lasts at least this many readings (6 = 1½ hours), so the last dim hour before
# sunset does not become "clouds after 5 PM" on an otherwise clear day.
SKY_CHANGE_MIN_SLOTS = 6
# Sanity check: on the sunniest days, the clear-sky index between these hours
# (10:00 to 13:59, sun high, no dawn/dusk effects) should be close to 1.
SANITY_MIDDAY_HOURS = (10, 14)
# On a mostly clear day, "clouds after 3 PM" is only said if at least this share
# of the readings after 3 PM really are not clear.
LATE_CLOUDS_MIN_SHARE = 0.75
# A day with a sunshine score at or above this is "about as sunny as a clear day"
# (the clear-sky curve is itself a percentile, so even the best day is ~95, not 100).
SUNSHINE_AS_CLEAR_MIN = 95
# Days whose weather sensor missed more than this share of sky readings get a warning.
SKY_MIN_COVERAGE_PCT = 80

# ---------------------------------------------------------------------------
# Phase W2 — temperature effect on power (engine/weather_temperature.py)
# ---------------------------------------------------------------------------
# Panel ratings are measured at 25 °C ("standard test conditions"); hotter = less power.
REFERENCE_PANEL_TEMP_C = 25.0
# Rows used to MEASURE the temperature coefficient: good sunlight (efficiency is
# noisy in weak light) and a healthy inverter. "Healthy" does not use alerts,
# because the weather step runs BEFORE fault detection (fault detection uses the sky).
TEMP_FIT_MIN_IRRADIATION = 0.3
TEMP_FIT_PEER_TOLERANCE = 0.1     # inverter within ±10% of its neighbours at that moment
# 95% confidence range: refit this many times on days drawn at random (with
# replacement). Whole days, because readings within one day are not independent.
TEMP_FIT_BOOTSTRAP_RUNS = 500
# Robustness check: the same fit inside narrow sunlight bands (kW/m² edges).
TEMP_FIT_IRRADIATION_BANDS = [0.3, 0.5, 0.7, 0.9, 1.3]
# Typical crystalline-silicon panel coefficient (%/°C), from panel datasheets.
TYPICAL_TEMP_COEF_RANGE = (-0.5, -0.3)
# ASSUMPTION fallback: if a plant's fitted coefficient falls outside this wider
# "believable" range, heat loss uses the typical middle value instead.
BELIEVABLE_TEMP_COEF_RANGE = (-0.8, -0.15)
FALLBACK_TEMP_COEF_PCT = -0.4
# "Hot hour": panel temperature at or above this. At −0.4 %/°C, 50 °C already
# costs ~10% of the power a 25 °C panel would make.
HOT_MODULE_TEMP_C = 50.0
# Chart: average efficiency per this many °C, drawn as dots over the scatter
# (bins with fewer readings than TEMP_CHART_MIN_BIN_READINGS are skipped as untrustworthy).
TEMP_CHART_BIN_C = 2
TEMP_CHART_MIN_BIN_READINGS = 30
# The website's scatter shows a random sample of this many healthy readings per plant.
TEMPERATURE_POINTS_FILE = PROCESSED_DIR / "temperature_points.parquet"
TEMP_WEB_SCATTER_POINTS = 2000

# ---------------------------------------------------------------------------
# Phase W3 — energy waterfall: where did the energy go? (engine/energy_breakdown.py)
# ---------------------------------------------------------------------------
ENERGY_BREAKDOWN_FILE = PROCESSED_DIR / "energy_breakdown.parquet"
# The plant's "power at 25 °C per unit of sunlight" is measured on readings with
# at least this much sunlight (weak light is noisy). Used to price blocked sunlight.
BREAKDOWN_FIT_MIN_IRRADIATION = 0.3
# Waterfall parts in the order they are subtracted, and whether anyone can fix them.
BREAKDOWN_PARTS = {"cloud_loss_kwh": "natural", "heat_loss_kwh": "natural", "fault_loss_kwh": "fixable",
                   "not_measured_kwh": "unknown", "other_kwh": "unknown"}

# ---------------------------------------------------------------------------
# Phase W4 — weather-aware fault detection (engine/alert_weather.py)
# ---------------------------------------------------------------------------
# "Difficult sky" for judging output: Overcast, or sunlight jumping around a lot
# (variability at/above this ≈ the most changeable quarter of daylight readings).
# Then one sunlight sensor cannot describe the whole plant: a cloud shadow can
# cover some inverters and not others, so % deviations get noisy.
SKY_HIGH_VARIABILITY = 0.2
# Weather-aware underperformance rule — switched OFF on purpose. The before/after
# test (python -m engine.validate_weather, "validation_weather" in metrics.json)
# showed it cuts false alarms by ~40% at sensitive thresholds BUT loses some real
# injected faults (short, partial ones under a changing sky). Our rule was: keep it
# only if nothing real is lost — so it stays off. Alerts still get the sky, a
# confidence level and a weather sentence (those never change what is detected).
WEATHER_AWARE_UNDER = False
# An underperformance event counts as "under a difficult sky" when at least this
# share of its flagged readings were difficult-sky readings...
UNDER_DIFFICULT_SKY_SHARE = 0.5
# ...and then it needs STRONGER evidence: last at least this many readings (6 = 1½ h,
# longer than a passing cloud shadow) OR be far below its neighbours (output at or
# below this share of the peer median, i.e. at least 50% lower).
UNDER_DIFFICULT_MIN_INTERVALS = 6
UNDER_STRONG_PEER_RATIO = 0.5
# Alert confidence levels (lowest first). Underperformance under a strong peer gap
# (UNDER_STRONG_PEER_RATIO) is raised one level.
CONFIDENCE_LEVELS = ["Low", "Medium", "High"]
# Validation on cloudy days: a day counts as "cloudy" below this sunshine score (W1).
VALIDATION_CLOUDY_DAY_MAX_SUNSHINE = 70
VALIDATION_WEATHER_FILE = PROCESSED_DIR / "validation_weather.parquet"
# Heading of the model-card section validate_weather.py writes (the Phase 3 rebuild keeps it).
MODEL_CARD_WEATHER_MARKER = "## Weather-aware fault detection (Phase W4)"


# ---------------------------------------------------------------------------
# Login (api/auth.py, engine/create_users.py)
# ---------------------------------------------------------------------------
# Accounts live in a local file (never committed). Passwords are stored only as a salted
# PBKDF2 hash — the real password is never saved anywhere.
USERS_FILE = DATA_DIR / "users.json"
PASSWORD_ITERATIONS = 200_000       # more = slower to guess, still fast for one login
SESSION_COOKIE = "solarsense_session"
SESSION_HOURS = 8                   # one working shift, then log in again
FAILED_LOGIN_DELAY_S = 0.5          # small pause after a wrong password slows down guessing
# DEMO accounts so judges can try the login (shown on the login page). Created automatically
# if users.json does not exist. Change them with: python -m engine.create_users NAME PASSWORD
DEMO_USERS = {"operator": "solar123", "engineer": "solar123"}

# ---------------------------------------------------------------------------
# AI model 3: fault-type classifier (engine/fault_classifier.py)
# ---------------------------------------------------------------------------
# A Random Forest that learns what each fault LOOKS like from thousands of examples we plant ourselves
# (trained on early days, tested on later days), then gives every real alert a second opinion.
FAULT_CLASSIFIER_FILE = MODELS_DIR / "fault_classifier.joblib"
CLASSIFIER_N_ESTIMATORS = 200
CLASSIFIER_SAMPLES_PER_DAY = 2      # examples of EACH fault type planted per healthy inverter-day
CLASSIFIER_WINDOW_HOURS = (1, 5)    # length of a planted fault (hours)
CLASSIFIER_FAULT_SIZES = {          # how strong each planted fault is (fraction of output KEPT)
    "underperformance_kept": (0.3, 0.8),
    "soiling_kept": (0.85, 0.96),               # dust: a small loss over most of the day
    "overheating_kept": (0.75, 0.92), "overheating_extra_temp_c": (12, 25),
}
# Our alert types -> the classifier's names (SENSOR_ISSUE is plant-wide, so no per-inverter shape)
CLASSIFIER_TYPE_FOR_ALERT = {"INVERTER_TRIP": "trip", "UNDERPERFORMANCE": "underperformance",
                             "DATA_GAP": "data_gap", "DEGRADATION": "soiling", "OVERHEATING": "overheating"}

# ---------------------------------------------------------------------------
# Self-updating model test (engine/model_updates.py)
# ---------------------------------------------------------------------------
# Real plants change (dust, ageing, season). We compare a model trained ONCE on the first days with one
# RETRAINED every day on everything seen so far ("fine-tuned" on new data), each predicting the next day.
UPDATES_FIRST_TRAIN_DAYS = 10       # both models start from the same first 10 days
UPDATES_N_ESTIMATORS = 60           # smaller forest: it is retrained ~24 times per plant

# ---------------------------------------------------------------------------
# Chat assistant (engine/assistant.py) — Google Gemini, free tier
# ---------------------------------------------------------------------------
# The Gemini key is a SECRET (anyone with it can use our free quota), so it is never written in code.
# Get one free at aistudio.google.com ("Get API key"), then create a file called .env in the
# solarsense folder (ignored by git) with this one line:
#     GEMINI_API_KEY=your-key-here
# No key = the chat says the assistant is offline; the rest of the dashboard works the same.
def _read_env_file(name):
    """Read one NAME=value line from the local .env file (no extra library needed)."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip()
    return ""


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or _read_env_file("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"   # fast, generous free tier; change here if Google renames it
CHAT_TIMEOUT_SECONDS = 25           # the AI can take a few seconds; never hang the page longer than this
CHAT_MAX_PER_MINUTE = 20            # per browser session — protects the free quota during testing
