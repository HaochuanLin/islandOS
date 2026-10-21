# Forecast-to-dispatch evaluation

This experiment provides a reproducible interface for evaluating a supplied
hourly renewable-surplus forecast inside the rolling-horizon dispatch prototype.
It does not train a power forecast or claim operational performance.

## Input schema

Create a UTF-8 CSV with one row per hour and these columns:

| Column | Unit | Meaning |
|---|---|---|
| \`timestamp_utc\` | ISO-8601 with timezone | Timestamp for the paired row |
| \`actual_surplus_kw\` | kW | Realized renewable surplus during the hour |
| \`forecast_surplus_kw\` | kW | Forecast surplus available to the controller for that hour |
| \`water_demand_m3\` | m³ per hour | Freshwater demand in the interval |
| \`cooling_demand_kw_th\` | kW thermal | Cooling demand in the interval |

Rows must be strictly ordered, exactly one hour apart, and have finite,
non-negative numeric values. The evaluator rejects gaps, missing values,
timezone-naive timestamps, and invalid numbers; it does not impute or reorder
data. Actual and forecast values must refer to the same timestamp and use the
same unit.

## Run

\`\`\`bash
python experiments/evaluate_forecast_dispatch.py path/to/paired_hourly.csv \\
  --output build/forecast-dispatch-evaluation.json
\`\`\`

The JSON report includes forecast MAE/RMSE/bias and service outcomes for:
- \`rolling\`: chooses priority using the supplied forecast and replans hourly;
- \`ro_first\`: fixed RO-first priority, using the same forecast input;
- \`ice_first\`: fixed cold-storage-first priority, using the same forecast input;
- \`perfect_information\`: non-deployable hindsight reference using realized surplus.

The comparison score is illustrative: 45% normalized unmet water demand, 45%
normalized unmet cooling demand, and 10% normalized remaining surplus. Lower is
better, but the raw deficit metrics must also be inspected. The report records
the rolling-minus-best-fixed score difference; a negative value means rolling
scored better on this specific input only.

## Persistence baseline comparison

When at least two hourly rows are supplied, the evaluator also creates a
one-step persistence forecast: the forecast for hour t is the realized surplus
from hour t-1. Both the supplied forecast and persistence baseline are scored
on rows 2 through N, excluding the first row from both methods. This avoids
giving either method a different evaluation window.

The report includes MAE/RMSE skill relative to persistence and reruns all
dispatch policies for both forecast inputs on the same aligned realized surplus,
water-demand and cooling-demand window. Each run starts from the same configured
initial inventories. A positive forecast skill means lower forecast error; a
negative rolling_score_difference_supplied_minus_persistence means rolling
dispatch with the supplied forecast scored lower on that aligned window.

This is a simple baseline, not necessarily the strongest forecast for every
location or season. The aligned dispatch comparison is a controlled window
comparison, not a continuation of the full-horizon run. If the input has only
one row, the persistence comparison is reported as unavailable.

## Interpretation boundaries

- The input file's provenance and whether it represents measured, public, or
  synthetic data are not independently verified; label it accurately.
- This experiment evaluates the dispatch interface, not forecast-model skill.
- The weather-parameter regression in IslandOS is not automatically a PV/wind
  or island-surplus forecast. A valid power forecast requires suitable paired
  generation and critical-load data.
- Water/cooling demands are treated as known in the evaluation.
- The simulator omits plant interlocks, startup/ramp dynamics, and site-specific
  safety limits. This is research software, not a field controller.
