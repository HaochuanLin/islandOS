# islandOS competition demo runbook

## Purpose and guardrails

This is a reproducible software demonstration of an early-stage energy–water planning prototype. The bundled demo inputs are synthetic. Do not describe the outputs as measured island performance, forecast accuracy on a real island, validated savings, or an operational control recommendation.

## Before the session

From the repository root, use Python 3.11 or another version supported by the project dependencies:

```bash
python -m venv .venv
# Windows PowerShell
.venv\\Scripts\\Activate.ps1
# macOS / Linux
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m unittest discover -s tests -v
streamlit run app.py
```

The Streamlit application runs locally and opens in a browser. Confirm that the regression suite finishes successfully before a judged demonstration. If dependency installation or tests fail, do not present the run as verified; use the command-line reports as a fallback and disclose the issue.

## Five-minute walkthrough

1. **Establish the boundary.** On Overview, point out that this is a research prototype, not a live controller, and that the built-in profile is synthetic.
2. **Run the baseline comparison.** Open Strategy simulator, select “Synthetic demo (illustrative),” keep the initial settings for the first run, and click “Run strategy comparison.”
3. **Open the rolling-dispatch lab.** Run the 48-case experiment, review rolling-vs-fixed counts and weight sensitivity, then inspect an hourly audit and download the JSON evidence.
4. **Compare the service outcomes.** Review water produced, water served, unmet demand, and grid energy cost. Explain that the values follow the declared input profile and simplified assumptions.
5. **Inspect one hourly audit.** Select a strategy and inspect its timestep rows and inventory chart. Use the downloaded summary and audit CSVs to show the outputs are inspectable, not just a single headline score.
6. **Optionally show optimization.** Run NSGA-II only if time permits. Explain that it searches feasible candidate schedules under the current model and constraints; it is not a trained AI model. The search may return no feasible candidate for some inputs, which is a legitimate result rather than something to conceal.
7. **Close with validation gaps.** Explain that local measured data, site calibration, complete system constraints, equipment interlocks, and field trials remain future work.

## What to point judges to

- `experiments/compare_dispatch_policies.py`: transparent fixed-policy baseline comparison.
- `Rolling dispatch lab` in the app: 48 synthetic rolling-horizon runs, case-matched policy comparisons, objective-weight sensitivity, and downloadable hourly audits.
- `Custom dispatch CSV` in the app: upload paired hourly actual/forecast surplus, water demand, and cooling demand to compare rolling, fixed-priority, and hindsight-reference policies with a row-level audit.
- `experiments/rolling_horizon_dispatch.py --json`: command-line output for the reproducible synthetic benchmark.
- `experiments/generate_dispatch_report.py --output-dir build/dispatch-report`: CSV/JSON results, an SVG comparison chart, a Markdown report, and timestep physical audits.
- `docs/EXPERIMENTS_AND_WORKFLOWS.md`: commands for the wider forecasting, dispatch, and optimization experiments.
- GitHub Actions: automated regression checks and downloadable experiment artifacts when the latest workflow completes successfully.

## Input and result freshness

The app fingerprints the current input bytes, source label, and model settings. If any of these change after a run, previously displayed strategy and optimizer results are cleared and the comparison must be run again. This avoids presenting a result calculated for a different set of inputs.

For the fixed-strategy page, use the columns and units described in the app's Data guide. The Custom dispatch CSV page uses `timestamp_utc`, `actual_surplus_kw`, `forecast_surplus_kw`, `water_demand_m3`, and `cooling_demand_kw_th`, with optional `forecast_water_demand_m3`. Check timezone consistency, interval spacing, missing values, and whether renewable surplus has already accounted for essential loads and reserves. The app does not silently fill missing measurements or establish that an uploaded dataset represents a particular island.

## Claims checklist

Safe claims:

- The code compares declared strategies on the supplied data.
- Hourly audits expose selected energy, demand, inventory, and constraint accounting.
- Synthetic fixtures exercise reproducible software behavior in CI.

Do not claim without additional evidence:

- Real-island forecasting skill or operational performance.
- Guaranteed water security, resilience, fuel savings, or emissions reductions.
- Safety certification, a validated digital twin, or autonomous plant control.
- That the optimizer's preferred schedule is globally optimal outside the configured search and model assumptions.
