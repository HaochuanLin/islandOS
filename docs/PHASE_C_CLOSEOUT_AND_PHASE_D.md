# Stage C close-out and Stage D entry

## Stage C — prediction workflow

Stage C now has three connected layers:

1. `prediction_engine.py`: candidate registration, chronological rolling-origin comparison, model selection, empirical residual bands and history hashing.
2. `prediction_adapter.py`: strict conversion from inspected CSV rows to timezone-aware `ForecastRequest` records. It requires one unambiguous canonical target mapping, explicit units, complete numeric values and regular cadence. It does not impute data.
3. Streamlit **Forecast lab**: upload a CSV, inspect import findings, select a canonical signal, run the backtest/forecast, inspect error metrics and bands, and export the forecast CSV.

Negative electricity tariffs are valid signed observations. Physical generation/load signals remain non-negative. The onboarding parser therefore permits negative values only for the tariff signal (temperature is also signed by physical definition).

### Stage C acceptance boundaries

- Built-in candidates are statistical baselines, not trained AI models.
- The forecast lab uses the supplied CSV in the current Streamlit session; it does not persist uploaded raw bytes.
- Units must be explicit in headers for the adapter to proceed. Ambiguous units are blocked rather than guessed.
- Missing values, duplicate/non-monotonic timestamps, irregular cadence and invalid numbers are not repaired.
- Empirical residual bands are historical error summaries, not guaranteed confidence intervals.
- Forecasts are advisory inputs; no equipment commands are generated.

## Stage D — resource coordination

Stage D should connect forecasts to a single, auditable multi-resource operating plan. Existing building blocks already present in the repository include the physical energy balance simulator, asset/constraint records, operational readiness checks, electrical topology validation and the forecast-to-dispatch adapter.

The work should focus on integration rather than duplicating those modules:

1. **Forecast handoff:** map the generic prediction outputs to the shared forecast bundle contract while preserving signal IDs, units, model versions, source-history hashes and bounds.
2. **Resource model:** coordinate PV, wind, grid import/export, battery, diesel and flexible loads against confirmed asset limits and operating constraints.
3. **Decision objectives:** compare energy cost, unmet critical demand, renewable curtailment, fuel use and battery degradation transparently. Customer economics must be explicit; objective weights are preferences, not probabilities.
4. **Uncertainty handling:** use forecast bounds/scenarios deliberately; do not label point forecasts as robust optimization.
5. **Audit:** show energy-balance residuals, constraint violations, provenance and why a candidate was selected.
6. **Customer-facing result:** compare baseline and recommended schedules, quantify estimated savings only against the same horizon and assumptions, and disclose missing costs/data.

### Stage D non-goals

No live device write/control, safety certification, verified site savings, automatic commissioning, or production multi-tenant service is implied. A feasible simulation is not permission to operate equipment.
