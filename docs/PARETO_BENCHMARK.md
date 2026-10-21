# Benchmarking NSGA-II against exact Pareto search

## Purpose

The NSGA-II implementation searches a finite, discrete policy space. It should be measured against an exact reference instead of assuming an evolutionary method is better. This benchmark enumerates every effective configured genome, filters it through the same independent feasibility audit, and computes the exact Pareto front using the optimizer's dominance rule.

## Run

From the repository root:

```bash
python experiments/benchmark_nsga2_vs_exhaustive.py --scenario steady_surplus --output build/pareto-benchmark.json
```

Run all bundled synthetic scenarios by omitting `--scenario`. Adjust `--population-size`, `--generations`, `--seed`, or `--config` to compare budgets/configurations. Exact enumeration is capped at 100,000 candidates by default. Use `--max-candidates` to change the limit only when the run is understood to be computationally manageable.

## Metrics

- **Exact-front recall**: exact Pareto genomes found in the NSGA-II returned front divided by the number of exact Pareto genomes.
- **NSGA-II-front precision**: returned NSGA-II front genomes that belong to the exact front divided by the size of the NSGA-II front.
- **Candidate counts**: total decision-space size and number evaluated by each method.
- **Exact reference genomes**: enables direct inspection and reproducible comparison.

A genome is compared by its discrete policy parameters, not by rounded objective values. Timing is included as diagnostic metadata but varies by machine and should not be treated as a portable performance claim.

## Interpretation limits

Both methods call the same simplified simulator and feasibility audit. A high recall means NSGA-II recovered much of the exact front **for that configured finite search space and scenario**; it does not show that the physics are accurate, that the parameters represent installed equipment, or that the result generalizes to real islands. A low recall means the chosen NSGA-II budget or evolutionary search missed exact candidates and should be investigated. If exhaustive search is cheap and exact, prefer it for that finite problem rather than using NSGA-II merely because it is more sophisticated.

When backup power is disabled, the benchmark collapses the RO start-ratio gene because the current model does not use that parameter in this mode. This mirrors the optimizer's effective decision space. If the optimizer's genome logic changes, keep this benchmark helper and its tests aligned.
