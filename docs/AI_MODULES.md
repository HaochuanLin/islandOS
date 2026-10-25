# Experimental AI modules

These experiments are isolated from the submitted Nan'ao case and are not a deployed control system. They use synthetic / scenario assumption, not measured real-world data. No experiment writes to a PLC, actuator, or live plant. The modules are advisory research and do not change the existing rule-based safety boundaries.

## Install

The normal installation remains unchanged. To run the optional scikit-learn models:

```bash
python -m pip install -r requirements-ai.txt
```

The repository's base requirements already include NumPy and Matplotlib. The scikit-learn dependency is optional at runtime: the renewable forecast experiment still evaluates persistence and seasonal-naive baselines if scikit-learn is unavailable, and the telemetry experiment still evaluates the rolling median/MAD detector. For the complete requested comparisons, install `requirements-ai.txt`.

## 1. Renewable-surplus forecast experiment

Run:

```bash
python experiments/renewable_surplus_forecast_experiment.py --output-dir build/ai-renewable-forecast
```

The default run evaluates ten fixed seeds (`20261021`–`20261030\)). For each seed it generates 21 days of synthetic hourly surplus and water demand, uses the first 14 days as the initial training window, and evaluates the following seven days with expanding-window daily refits and one-step-ahead predictions. The forecast features use prior realized surplus values and calendar cycles. Candidates are persistence, 24-hour seasonal naive, and (when scikit-learn is installed) `HistGradientBoostingRegressor`.

Outputs include per-seed forecast metrics (MAE, RMSE, bias), bootstrap intervals for the mean across selected synthetic seeds, dispatch comparison CSV, paired input CSVs, simulator hourly CSV/JSON reports, a forecast plot, and a SHA-256 manifest. Forecasts are passed into the existing `evaluate_forecast_driven_ro_sim` function rather than reimplementing the RO simulator.

**Important isolation assumption:** to isolate surplus-forecast effects, the generated paired dispatch input reuses the synthetic realized water demand as its demand forecast. This is an oracle-like assumption, not a deployable demand forecast. The simulator's perfect-foresight reference is also an optimistic reference, not an achievable policy. Bootstrap intervals describe variation across selected synthetic seeds, not site-level confidence intervals. Do not infer model superiority from the existence of the report; compare the emitted metrics and raw dispatch outcomes.

## 2. Telemetry anomaly-detection experiment

Run:

```bash
python experiments/telemetry_anomaly_experiment.py --output-dir build/ai-telemetry-anomaly --seed 20261021
```

The script generates 720 synthetic hourly rows and injects missing values, spikes, stuck readings, and drift into meter/reservoir telemetry. It compares a rolling median/MAD detector with an optional `IsolationForest` model trained on an initial clean synthetic window. The report includes precision, recall, false-positive rate, injected-fault count, a CSV of row-level flags and review status, a plot, and a SHA-256 manifest.

Any missing value or configured detector flag routes the affected row to the exact status `HOLD: data quality check failed`. This is a conservative review gate, not a validated fault classifier. A flag is not a diagnosis, and a row without a flag is not proof that data are valid. Metrics quantify detection of this script's injected labels only.

## 3. Structured recommendation explanations

Run the deterministic demonstration:

```bash
python experiments/structured_recommendation_explanations.py
```

Or pass a JSON file containing boolean `telemetry_quality_passed` and `hard_constraints_passed`, plus non-negative numeric `available_surplus_kw`, `required_power_kw`, `water_inventory_m3`, and `target_water_inventory_m3` fields:

```bash
python experiments/structured_recommendation_explanations.py input.json --output build/recommendation.json
```

The module applies a small explicit rule set and returns a stable reason code, an English template, the input evidence, and advisory-mode flags. It does not call an LLM, invent a rationale, invoke the existing scheduler, or send commands to equipment. The `START_ELIGIBLE_FOR_OPERATOR_REVIEW` result is not an instruction to start equipment; operator confirmation and site-specific safety review remain required.

## Tests and reproducibility

Run the focused tests:

```bash
python -m pytest -q tests/test_ai_experiments.py
```

Each generated dataset is synthetic and seeded. CSV/report artifacts include or accompany a SHA-256 manifest. A digest establishes artifact identity, not data authenticity. For broader regression checks run `python -m pytest -q` in an environment with the repository's CI dependencies installed.

## Scope boundaries

- No external LLM API or runtime data download is used.
- PyTorch and TensorFlow are not required.
- Models are advisory; existing hard constraints and operator approval are not bypassed.
- No real-site accuracy, physical fidelity, safety certification, or operational benefit is claimed.
- The experiment modules do not produce or modify the submitted Nan'ao numbers.
