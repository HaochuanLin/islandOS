# Forecast model promotion checklist

This checklist is a human review gate for a proposed water-demand forecasting model. Passing software tests or improving one aggregate metric is not sufficient to promote a model, and this checklist does not authorize plant control.

## 1. Freeze the evaluation before running it

- [ ] Identify the exact source file and record its SHA-256 digest.
- [ ] Record the data source, license, units, timezone, temporal coverage, missingness policy, and known collection biases.
- [ ] Define the chronological holdout(s), high-demand threshold, and acceptance thresholds before inspecting holdout results.
- [ ] Ensure each forecast was issued using only information available at its forecast origin.
- [ ] Keep the final holdout out of feature selection, hyperparameter tuning, and model selection.

## 2. Compare against meaningful baselines

At minimum, compare the candidate and incumbent on the same timestamps against persistence and a relevant seasonal-naive baseline. Use repeated chronological/walk-forward windows when enough history is available.

Report, at minimum:

- MAE and RMSE with units;
- signed bias (forecast minus actual);
- high-demand MAE and underforecast rate;
- the number of evaluated rows and high-demand events;
- per-window results as well as pooled/aggregate results.

Do not rely on a percentage improvement alone: it can be unstable when the baseline metric is close to zero. Preserve raw metrics and make the denominator explicit.

## 3. Apply the existing candidate-review gate

Prepare an aligned CSV with `timestamp`, `actual_water_demand_m3`, `incumbent_forecast_m3`, and `candidate_forecast_m3`. Timestamps must be timezone-aware and strictly continuous at hourly intervals.

Example:

```bash
python experiments/evaluate_forecast_candidate.py \
  path/to/aligned-forecasts.csv \
  --high-demand-threshold-m3 40 \
  --min-mae-improvement-fraction 0.05 \
  --max-underforecast-rate-increase 0.02 \
  --min-high-demand-samples 5 \
  --output build/water-demand-forecast/candidate-review.json
```

Choose the high-demand threshold from operational requirements or training history, not from the held-out actuals. Treat `insufficient_high_demand_evidence` as inconclusive—not a pass. A `candidate_recommended_for_review` status only means the configured checks passed on this evaluation; it is not automatic promotion.

See [the candidate-review gate](WATER_DEMAND_CANDIDATE_REVIEW.md) and [the repeated chronological backtest](WATER_DEMAND_ML_COMPARISON.md) for the existing tool contracts.

## 4. Check the decision system, not just the predictor

- [ ] Confirm forecast timestamps align exactly with dispatch timestamps and no actual-demand leakage enters planning.
- [ ] Evaluate forecast errors under low-renewable, high-demand, low-storage, and equipment-capacity-boundary scenarios.
- [ ] Compare service deficits, surplus use, constraint violations, and any objective/cost metrics using paired inputs and identical assumptions.
- [ ] Verify uncertainty intervals and their coverage if the system consumes probabilistic forecasts.
- [ ] Confirm missing, stale, malformed, or out-of-range inputs fail closed with a reviewable error.
- [ ] Retain source hashes, model/version identity, configuration, random seeds, and machine-readable reports.

A better demand forecast does not guarantee a better dispatch policy: power availability, RO capacity, tank state, and equipment constraints can dominate the outcome.

## 5. Record a decision with explicit limits

Record one of: **retain incumbent**, **candidate eligible for further review**, or **inconclusive due to insufficient evidence**. Include the evaluated commit, data digest, model/version, acceptance thresholds, all relevant metrics, failed checks, reviewer, and next action.

Do not claim island-site validity from data collected elsewhere. A model intended for a particular island requires representative local measurements and a site-specific retrospective evaluation. Any operational use additionally requires authorized operator review, safety assessment, and supervised shadow-mode evidence. Model promotion must never silently enable actuator writes or live control.

## Interpretation boundary

This checklist organizes existing evaluation tools and review expectations; it is not a new benchmark result. No model-quality or maturity score should increase merely because this document exists. Scores may change only after the specified evidence is generated and reviewed for the exact code and data under assessment.
