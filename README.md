# SolarSense — AI Solar Plant Health Monitor

Meridian hackathon, problem **DEV-P01** (Application Development track).

Solar operators often find out about broken or weak inverters only after the losses pile up.
SolarSense compares what every inverter **actually** produced with what it **should** have produced
for the weather, flags likely faults with a plain-English reason, and estimates the energy (kWh) and
money (₹) lost — shown on a web dashboard that operators can act on.

**Live demo:** https://ojasguptaa.github.io/solarsense/ — a static copy of the dashboard (no install needed).
 
## Setup in 10 steps (Windows, PowerShell)

1. **Install Python 3.12** from python.org (3.10–3.12 work; 3.13+ is too new for some libraries).
2. **Get the project:** `git clone https://github.com/ojasguptaa/solarsense.git` and `cd solarsense`.
3. **Create a virtual environment:** `py -3.12 -m venv .venv`
4. **Activate it:** `.venv\Scripts\Activate.ps1` — you should see `(.venv)` at the start of the line.
   If PowerShell says "running scripts is disabled", run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
5. **Install the libraries:** `pip install -r requirements.txt`
6. **Download the data:** on Kaggle (free account) open **"Solar Power Generation Data" by anikannal**,
   click *Download*, unzip, and put the **4 CSV files** in `data/raw/`
   (`Plant_1_Generation_Data.csv`, `Plant_1_Weather_Sensor_Data.csv`, `Plant_2_Generation_Data.csv`, `Plant_2_Weather_Sensor_Data.csv`).
7. **Build everything:** `python run_all.py` (about 3 minutes; add `--skip-validation` for a quick ~15 s rebuild).
8. **Check it works:** `pytest` — every test should pass.
9. **Start the website:** `uvicorn api.main:app --reload`
10. **Open** http://localhost:8000 in your browser (needs internet the first time, for the chart library).
    **Log in** with the demo account `operator` / `solar123` (created automatically on first start;
    add your own with `python -m engine.create_users NAME PASSWORD`).
    **Install it as an app:** click **⬇ Install app** in the top bar (Chrome/Edge, or Android), or on iPhone
    Share → "Add to Home Screen". It then opens in its own window with the SolarSense sun icon.
    Press **Ctrl+C** in the terminal to stop the server.

> macOS / Linux: use `python3.12 -m venv .venv` and `source .venv/bin/activate` in steps 3–4.
> The processed data is already in the repository, so steps 9–10 work even before step 7 — but
> step 7 is needed after changing any code or setting (and to rebuild the trained models).

## What you will see

| Page | What it shows |
|---|---|
| **Overview** | Day summary, KPI tiles, actual vs expected chart, alerts needing attention, **▶ Live replay** of the day, **Plant 3D view** (one block per inverter, coloured by status; hover for numbers, click to open) |
| **Plant** | All days: daily actual vs expected, inverter × day health map, worst inverters |
| **Weather & Energy** | The sky read from sunlight (☀️ ⛅ ☁️ 🌫️), panel heat, the energy waterfall (natural vs fixable losses), calendar of all days |
| **Inverters** | One inverter: actual vs expected vs neighbours, alert periods shaded, daily trend, its alerts |
| **Alerts** | Filter/search/sort all alerts, "Why?" panel with evidence chart, Acknowledge / Resolve, CSV export |
| **About** | How it works, data sources, assumptions, limitations, team |



## How it works (one minute)

1. **Clean** the raw data (fix Plant 1's impossible DC values, keep missing readings visible).
2. **Expected output:** a Random Forest learns how much power each inverter should make for the sunlight and
   temperature (compared against a simple physics formula). Trained on earlier days, tested on later days.
3. **Fault rules** compare actual vs expected and vs neighbouring inverters: inverter trip, underperformance,
   data gap, slow degradation, overheating, sensor/data issues — each with a reason and recommended action.
4. **Losses:** energy lost × an assumed tariff = ₹ lost.
5. **Weather intelligence:** the sky (clear → overcast) is read from the sunlight itself (no cloud sensor), the
   power lost to hot panels is measured, and a waterfall splits each day's energy into natural losses (clouds,
   heat) and fixable losses (faults). Every alert shows the sky and a confidence level.
6. **Validation:** we plant faults in healthy data and check the detector finds them (no official labels exist),
   also on cloudy days, and test whether a weather-aware rule helps (it lost real faults, so it is off).
7. The **API** serves the precomputed results; the **website** only displays them.

## Chat assistant (optional, free Google Gemini key)

The chat button (bottom right of every page) answers questions such as "weekly report" or "which inverters need
attention?". Our code computes the facts (`/api/chat/facts`); Google Gemini only turns them into sentences and is
told to use no other numbers. Without a key the chat simply says it is offline — everything else works the same.

1. Go to **aistudio.google.com**, sign in with a Google account, click **Get API key** → **Create API key**, copy it.
2. In the `solarsense` folder create a file named `.env` (no other name) containing one line:
   `GEMINI_API_KEY=paste-your-key-here`
3. Restart the server (`uvicorn api.main:app --reload`), log in, click the chat button.

`.env` is ignored by git — never commit it or share the key. The free tier has daily limits, so the chat allows
20 messages per minute per user. On the GitHub Pages copy the chat is switched off (a website without a server
cannot keep a key secret).

## Project layout

```
engine/   the AI pipeline (load, clean, model, weather, detect, losses, waterfall, validate) — settings in engine/config.py
api/      FastAPI app: JSON endpoints + serves the website
web/      the dashboard (HTML, CSS, JavaScript, Chart.js, Three.js for the 3D plant view)
reports/  metrics.json (every number shown), data_quality.md, model_card.md, assumptions.md, figures/
tests/    pytest checks
data/     raw/ (Kaggle CSVs, not in git) and processed/ (pipeline outputs)
```

## The online demo (GitHub Pages)

https://ojasguptaa.github.io/solarsense/ is rebuilt automatically on every push to `main`
(`.github/workflows/pages.yml`). GitHub Pages cannot run Python, so `python -m api.export_static` saves every
answer the API can give (every plant, date, inverter and alert) as JSON files, and the website reads those
instead — the numbers are identical to the live API. Differences: Acknowledge / Resolve are saved only in your
own browser, and the data is the version committed to the repository (re-run `python run_all.py` and push to update).

## Troubleshooting

- **"Raw data not found"** → the 4 CSVs are not in `data/raw/` (step 6).
- **"Engine offline" on the website** → the server is not running (step 9).
- **Charts are empty** → no internet; Chart.js loads from a CDN.
- **"3D view not available on this device"** → Three.js (CDN) could not load or the browser has no WebGL 2; the rest of the page still works.
- **Port 8000 already in use** → `uvicorn api.main:app --reload --port 8001` and open http://localhost:8001.

## Data, assumptions and honesty

- Data: Kaggle "Solar Power Generation Data" by anikannal (two plants in India, 34 days in May–June 2020).
  The raw files are not stored in this repository. Plant locations (GPS) are not in the dataset.
- Every assumption (e.g. the ₹/kWh tariff — **still to be sourced by the team**) is listed in
  `reports/assumptions.md` and on the About page.
- Results are reproducible: everything uses a fixed random seed (42).
