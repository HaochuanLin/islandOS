# End-to-end forecast-to-dispatch benchmark protocol

## Purpose

This benchmark checks the software path from a fixed, timestamped input series through forecast evaluation and dispatch-policy comparison. It is an integration and reproducibility test, not a field-performance study.

## Input and provenance

- Input: `data/examples/synthetic_dispatch_benchmark.csv`
- Generator: `experiments/generate_synthetic_dispatch_benchmark.py`
- Horizon: 168 consecutive hourly rows beginning at 2026-01-01 00:00 UTC.
- Data status: deterministic synthetic values only; no measurements from a named island are represented.
- Integrity check: `python experiments/generate_synthetic_dispatch_benchmark.py --check`

The committed CSV is the exact benchmark input. The generator exists so changes to formulas, timestamps, row counts, or formatting can be detected in CI.

## Run

```bash
python experiments/generate_synthetic_dispatch_benchmark.py --check
python experiments/evaluate_forecast_dispatch.py \
  data/examples/synthetic_dispatch_benchmark.csv \
  --output build/forecast-dispatch-benchmark/results.json
```

GitHub Actions runs these commands and publishes the JSON as the `islandos-forecast-dispatch-benchmark` artifact. The artifact is retained for 30 days by the current workflow configuration.

## Comparisons

The evaluator reports:

- Forecast MAE, RMSE, and bias for the supplied forecast.
- One-step persistence forecast metrics on an aligned window that excludes the first row.
- Rolling dispatch using the supplied forecast.
- Fixed RO-first and ice-first policies.
- A perfect-information reference that sees realized surplus; this is a hindsight lower-bound-style comparator, not a deployable policy.
- Raw service outcomes, remaining surplus, and the illustrative normalized score.

The illustrative score is:

`0.45 × normalized unmet water + 0.45 × normalized unmet cooling + 0.10 × normalized remaining surplus`.

Lower is better for this chosen score, but the raw unmet-water and unmet-cooling results must always be inspected alongside it. The weights are a design choice, not a validated social-welfare or reliability objective.

Constraint feasibility is evaluated separately from that score. The rolling planner
selects a priority with fewer forecast-horizon constraint-violation hours first,
then uses the illustrative score to break ties. The report's best fixed-priority
reference follows the same ordering; a separate score-only ranking is retained.
A policy with any constraint-violation hour is marked infeasible, even if its
normalized score is lower. Violation hours count distinct hours with one or more
flags, while violation count sums the flags.

At execution, a new RO start is deferred when realized power remaining after
higher-priority loads is below the RO rated power. The hourly audit records this
decision and the remaining power estimate. This guard prevents avoidable new
commitments under a known current-hour shortfall; it cannot guarantee that a
future committed hour will have enough power, so violations in already-started
cycles must still be reported.

## What constitutes success

The software benchmark is considered technically successful when:

1. The committed fixture matches the deterministic generator.
2. The evaluator completes without schema, timestamp, or numeric-validation errors.
3. The JSON report is generated and uploaded by CI.
4. The report identifies the input as user-supplied synthetic data and records its interpretation limits.
5. The test suite and existing Pareto benchmark pass on the same commit.

A successful run does **not** require rolling dispatch to beat every fixed policy. That would encourage overfitting the software's success criteria to one synthetic trace. Instead, report the result honestly and use the trace to catch regressions.

## Limitations and next scientific step

This benchmark does not validate forecast skill on real data, physical fidelity, full energy balance across a real microgrid, equipment safety, or the project's benefit at a particular site. It assumes water and cooling demand are known, uses simplified flexible-load models, and does not include battery state of charge, inverter limits, grid frequency/voltage, diesel commitment, or plant-specific RO interlocks.

The next evidence-building step is a documented real or public site dataset with provenance, a baseline chosen before running the comparison, multiple chronological periods, and sensitivity tests for uncertain demand, equipment parameters, and forecast errors. Keep synthetic regression results separate from site-study results.
