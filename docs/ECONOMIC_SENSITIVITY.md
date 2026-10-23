# Economic sensitivity analysis

This experiment quantifies how the modeled annualized lifecycle cost of an already-evaluated Pareto candidate set changes when one economic assumption is varied at a time. It is intended to expose cost assumptions that materially affect comparisons before a site-specific techno-economic review.

## Preconditions

1. Prepare a valid, complete calendar-year hourly CSV (8,760 rows, or 8,784 in a leap year) using the schema in [parameter configuration](PARAMETER_CONFIGURATION.md).
2. Fill every required economic field in the JSON configuration: electricity opportunity price, RO/chiller capital costs, fixed O&M, RO variable O&M per cubic metre, analysis lifetime, and discount rate. Unknown values must remain null; the cost objective will then be disabled.
3. Keep RO backup power disabled until a documented backup-generation cost model exists.
4. Preserve provenance for each economic assumption, including currency, source, retrieval date, uncertainty range, and whether the value is a quote or an illustrative assumption.

## Run

```bash
python experiments/run_nsga2_from_csv.py path/to/full_year_hourly.csv \
  --config config/site_parameters.example.json \
  --source-type measured \
  --output-dir build/site-optimization

python experiments/economic_sensitivity.py build/site-optimization/nsga2_results.json \
  --relative-change 0.2 \
  --output build/economic-sensitivity.json
```

The example config contains null economic values and illustrative equipment assumptions; replace them with documented values before the cost objective can run. The sensitivity command defaults to ±20% one-factor-at-a-time perturbations and writes JSON containing the baseline cost range, each varied value, candidate-level annualized costs, cost deltas, and any skipped zero-baseline parameter.

## Reading the JSON report

The output file is designed for audit and downstream analysis. Important fields are:

- `source_type`, `input_summary`, and `data_quality_report`: provenance label, input time coverage/units, and the base optimizer's data-quality assessment.
- `baseline_optimizer`: algorithm, seed, population size, generation count, and search-size metadata copied from the original optimization report.
- `base_economic_assumptions` and `relative_change_requested`: the exact values used for the baseline and the requested proportional perturbation.
- `baseline_annual_cost`: minimum, median, and maximum annualized cost across the baseline Pareto candidates, in the declared currency per year.
- `scenarios[]`: one tested parameter/value/direction per entry, with the annual cost range, percentage deltas from each candidate's baseline, and each candidate's resulting cost.
- `skipped_scenarios[]`: zero-baseline or rounded/clamped perturbations that cannot produce a meaningful distinct scenario.
- `interpretation_limits[]`: limitations that should be retained when sharing or comparing the report.

A percentage delta is defined only when that candidate's baseline annualized cost is greater than zero. If a baseline candidate costs zero, its relative percentage change is mathematically undefined, so the report records a null summary when no deltas are defined and counts the undefined baselines. Do not read null as zero change.

## Reproducibility checklist

Before circulating a result, archive the original CSV and its SHA-256 hash, the exact configuration file and its hash, the optimizer JSON, the generated sensitivity JSON, the Git commit, Python/dependency environment, and the source/provenance evidence for each economic input. Confirm the source label reflects the actual data (measured, public, synthetic, or forecast); never label a synthetic fixture as measured.

## Interpretation limits

- This is a **fixed-candidate-set re-pricing** analysis. It does not rerun NSGA-II, so a candidate that becomes non-dominated under a changed cost assumption but was absent from the baseline Pareto front will not appear.
- The result is conditional on the selected full-year input, the optimizer's baseline Pareto candidates, and the simplified cost formula.
- The current cost objective excludes replacements, taxes, financing, backup generation, demand charges, emissions, and unmet-service penalties. The supplied year is assumed representative of every analysis year.
- A ±20% range is a stress test, not a probability distribution, confidence interval, vendor quote, or prediction of future prices.
- This report is not a bankable financial assessment or a claim of cost-optimal design. A qualified project team must validate assumptions and acceptance criteria before procurement.