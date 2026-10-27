# IslandOS Nan'ao emergency resilience pilot

**Single-scenario hybrid simulation only.** The script combines a fixed valley-power annual water yield with the median wind-curtailment water yield from a 1,000-run Monte Carlo simulation. The pre-existing 50 kW RO unit is treated as a sunk asset; RO purchase CAPEX is zero.

## Run

```bash
python islandos_nanao_hybrid.py
python -m unittest discover -s tests -p 'test_nan_ao_*.py' -v
```

Optional parameters: `--runs`, `--seed`, and `--output-dir`. Defaults are 1,000 runs, seed `20261027`, and output directory `outputs/`.

The script writes exactly two output files:
- `outputs/scenario_result.csv`: header plus exactly one row, `IslandOS_hybrid_clean_energy`.
- `outputs/sim_meta.json`: seed, run count, assumptions, simulated wind-yield summary, and limitations.

The result reports total annual hybrid water, minimum/maximum unit operating-cost estimates, and annual-supply population equivalent at 50 L/person/day. Unit-cost bounds include valley electricity cost plus assumed chemical-reagent and routine O&M costs. Curtailed wind is assigned zero marginal electricity cost. The non-electric annual cost range of RMB 8,000–18,000 is an unverified screening assumption.

## Limitations

This is a simulation-only result, not field-calibrated. Wind event frequency, duration, surplus power, RO availability, and operating costs are assumptions rather than measured Nan'ao data. Valley-power production is fixed at 33,650 m³/year and is not computed from hourly dispatch. The population metric is an annual water-volume equivalent, not proof of safe water quality, storage, distribution, or continuous emergency access.
