# Continuous-state forecast-to-dispatch backtest

## Purpose

The multi-window evaluator is useful for checking whether outcomes vary across
separate periods, but each window resets the water and thermal inventories.
This experiment instead runs each policy across one complete chronological
trace. The simulated freshwater reservoir and cold-storage inventory carry
from one hour to the next within each run.

## Run

```bash
python experiments/evaluate_forecast_dispatch_continuous.py path/to/paired_hourly.csv \
  --output build/forecast-dispatch-continuous.json
```

The CSV schema and units are the same as in
[the forecast-to-dispatch guide](FORECAST_DISPATCH_EVALUATION.md).

## Fair comparison and information timing

- The supplied-forecast rolling strategy uses the supplied forecast at each
  planning step.
- The persistence rolling baseline uses the supplied first-hour forecast for
  hour 0 as a common warm-up action. Starting at hour 1, its forecast is only
  the previous hour's observed actual surplus. This avoids inventing an
  observation before the trace begins.
- Forecast MAE/RMSE are compared only on hours 2 through N, where both forecast
  methods have a defined aligned prediction. The dispatch score covers the
  full trace, including the shared warm-up hour.
- Every policy run begins with the same default initial inventory assumptions.
  Inventories are carried continuously within each run, but are not shared
  between different strategy runs.
- Fixed-priority policies use the supplied forecast for planning. The
  perfect-information policy is a hindsight-only reference, never a deployable
  control strategy.

## Output and interpretation

The JSON includes aligned forecast metrics, persistence skill, policy scores,
water/cooling deficits, remaining surplus, final water and thermal inventories,
hourly priority decisions, and constraint-violation counts. Negative
`supplied_minus_persistence_rolling_score` favors the supplied forecast on
this trace only. The normalized score has illustrative weights; inspect raw
service outcomes and inventory endpoints rather than relying on a single score.

This remains a simplified simulator. Input provenance is not independently
verified; demand is treated as known; plant interlocks, ramping, thermal
leakage, and site-specific safety limits are omitted. A continuous simulation
is a stronger state-accounting test than independent windows, but it is not
field validation and does not establish real-island benefits.
