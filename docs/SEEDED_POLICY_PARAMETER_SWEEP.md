# Seeded policy parameter sweep

IslandOS can evaluate dispatch-policy behavior without pretending synthetic inputs are site measurements. This benchmark generates a fixed baseline plus a seeded family of paired synthetic cases and runs the same four policies on each case:

- `rolling`: the existing receding-horizon prototype;
- `ro_first`: fixed RO-first priority;
- `ice_first`: fixed cold-storage-first priority;
- `perfect_information`: an offline reference that sees realized renewable surplus while planning.

## Run it

From the repository root:

```bash
python -m experiments.run_policy_parameter_sweep --hours 48 --cases 20 --seed 20261026
```

The default writes `build/policy-parameter-sweep/report.json`. For a faster smoke run:

```bash
python -m experiments.run_policy_parameter_sweep --hours 12 --cases 4 --seed 7 --output build/policy-sweep-smoke/report.json
```

The `--cases` count excludes the baseline, so the default evaluates 21 paired cases and 84 policy runs. Randomized cases scale actual surplus, forecast surplus, actual and forecast water demand, and cooling demand independently within declared bounds. The seed and factors are included in the report.

## Reading the report

- `policy_summary` reports mean, median and 95th-percentile composite score, unmet demand, remaining surplus, and number of cases with any simulated constraint-violation hour.
- `cases` keeps per-case policy scores and the rolling-minus-best-fixed delta, so a good aggregate cannot hide individual regressions.
- `failure_analysis` surfaces the largest rolling regressions and cases with the highest combined unmet water/cooling service.
- `report_sha256` is a deterministic digest of the report before the digest field is added. It supports reproducibility checks; it does not authenticate a source or validate a measurement.

The illustrative score is:

`score = 0.45 × unmet_water_fraction + 0.45 × unmet_cooling_fraction + 0.10 × remaining_surplus_fraction`

For the failure-analysis ranking, unmet water and cooling are normalized against their own total demands first, then averaged equally; the raw units (m³ and kWh_th) are never added directly.

Weights are an explicit policy preference, not a universal engineering truth. Change them only with a recorded rationale and compare results across cases. The realized-input reference is an offline comparison, not a deployable forecast policy or a guaranteed mathematical optimum.

## Limits and next evidence gate

All inputs are generated synthetic profiles and randomized scaling transforms. They are not sampled from a measured island distribution; randomization does not turn synthetic data into field data. The benchmark checks software behavior, reproducibility, trade-offs, and failure visibility only. It does not prove forecast accuracy, site performance, or physical safety. The simulator remains simplified and does not model every plant interlock or equipment dynamic. No physical writes or live control are enabled.

Before claiming site performance, preserve the same evaluation protocol and rerun it on time-aligned measured data with a documented schema, provenance, train/test separation for forecast models, site-approved physical limits, operator review, and independent safety validation.
