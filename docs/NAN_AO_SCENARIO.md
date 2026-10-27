# IslandOS Nan'ao hybrid simulation

This pilot intentionally contains one scenario only: `IslandOS_hybrid_clean_energy`.

## Calculation contract

- Fixed valley-power annual water yield: 33,650 m³.
- Wind-curtailment yield: median annual water volume from 1,000 Monte Carlo runs by default.
- Total annual water: fixed valley yield + simulated wind-curtailment median.
- RO asset: pre-existing 50 kW unit, treated as sunk; purchase CAPEX = RMB 0.
- Unit operating cost: (valley electricity cost + non-electric operating costs) / total hybrid annual water.
- Supported population equivalent: total annual water / (0.05 m³/person/day × 365 days).

Wind simulation assumptions: annual event count rounded from triangular(4, 12, mode 8); event duration lognormal with median 8 hours and sigma 0.5 clipped to 2–24 hours; surplus power triangular from 5–50 kW with mode 25 kW; RO availability uniform from 0.85–1.00; specific energy 4.0 kWh/m³. Default seed: 20261027.

Valley electricity price is assumed to be RMB 0.272/kWh. Chemical reagents and routine O&M are represented by a combined annual non-electric operating-cost range of RMB 8,000–18,000. These are unverified screening assumptions. No capital expenditure is included.

## Outputs

Run `python islandos_nanao_hybrid.py`. It writes `outputs/scenario_result.csv` with one data row and `outputs/sim_meta.json` with seed, run count, assumptions, simulated wind-yield summary, and limitations. Console output contains only the hybrid result.

## Limitations

Simulation-only, not field-calibrated. The model does not use measured Nan'ao hourly generation, load, curtailment, water demand, or operating records; fixed valley-water yield is not an hourly dispatch calculation. The population equivalent does not demonstrate water quality, storage, distribution, or real emergency access.
