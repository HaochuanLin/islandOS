# Water-demand candidate review gate

This experiment compares an existing forecast ("incumbent") with a proposed
forecast ("candidate") on the **same already-issued, out-of-sample hourly
observations**. It is a guardrail before a person considers changing models; it
does not train, deploy, or automatically replace a model.

## Input

Create a UTF-8 CSV with these columns:

| Column | Meaning |
|---|---|
| `timestamp` | ISO-8601 timestamp including a timezone offset |
| `actual_water_demand_m3` | Measured demand for that hour, in m³ |
| `incumbent_forecast_m3` | Existing model's forecast issued before the actual was known |
| `candidate_forecast_m3` | Candidate model's forecast for the same hour, also issued before the actual was known |

The rows must be strictly ordered and continuous at one-hour intervals. The
tool rejects missing hours, invalid timestamps, negative values, and non-finite
values rather than silently filling them.

## Run it

Choose a high-demand threshold from operational requirements or training
history **before inspecting the evaluation window**. The threshold defines
which observed hours count as high demand for the risk check.

```bash
python experiments/evaluate_forecast_candidate.py \
  path/to/aligned-forecasts.csv \
  --high-demand-threshold-m3 40 \
  --min-mae-improvement-fraction 0.05 \
  --max-underforecast-rate-increase 0.02 \
  --min-high-demand-samples 5 \
  --output build/water-demand-forecast/candidate-review.json
```

The example requires at least a 5% overall MAE improvement. The default risk
guardrail permits no more than a 2 percentage-point increase in the rate of
underforecasting during high-demand hours, and also requires high-demand MAE
not to get worse. By default, at least five high-demand observations are also
required before a candidate can be recommended. If fewer are available, the
report says `insufficient_high_demand_evidence` instead of treating a tiny peak
sample as adequate evidence. You can change this with `--min-high-demand-samples`.
If the candidate has enough peak observations but fails the overall MAE or
high-demand risk check, the report says `keep_incumbent_for_now`.

## Interpret the result carefully

- `candidate_recommended_for_review` means only that the candidate passed
  these configured checks on this particular holdout. A human still needs to
  inspect data quality, multiple chronological windows, model stability, and
  operational constraints before adopting it.
- `keep_incumbent_for_now` means the candidate failed at least one check.
- The high-demand threshold should come from operational or training context,
  not be tuned against the held-out actual values.
- Forecasts must have been issued before their matching actual values were
  observed; otherwise the comparison is invalid.
- Synthetic examples validate code behavior only. They do not establish
  forecasting accuracy for an island or any other real site.
- Better water-demand prediction does not by itself guarantee better dispatch:
  production is still limited by energy availability, desalination capacity,
  storage, and operating constraints.
