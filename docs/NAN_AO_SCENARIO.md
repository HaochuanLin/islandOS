# IslandOS Nan'ao hybrid simulation

This is a single-scenario simulation: `IslandOS_hybrid_clean_energy`.

## System setup and calculation

Two local standby 50 kW skid-mounted RO units are coordinated in parallel (total rated power 100 kW). The competition submission documents multiple existing small-scale RO desalination units across Nan'ao island; this solution aggregates distributed emergency assets under the scheduling platform. The exact hardware inventory will be confirmed during on-site pilot investigation. All RO assets are pre-existing, so no new-equipment CAPEX is included.

Fixed parameters:

- Specific energy: 4.0 kWh/m³
- Daily valley window: 8.0 h
- Availability factor: 0.925
- Total RO rated power: 100 kW (two 50 kW units)

Valley water is calculated, not hardcoded:

`m3_per_hour = 100 / 4.0`

`valley_annual_water = m3_per_hour * 8.0 * 365 * 0.925 = 67,525 m³/year`

Wind-curtailment water uses 1,000 Monte Carlo runs by default. Each run samples event count (rounded triangular distribution), event duration (lognormal, clipped to 2–24 h), and surplus power (triangular distribution, 5–100 kW with mode 50 kW). The availability factor is 0.925. Total annual wind-curtailment hours are computed from simulated event durations and reported as output statistics; they are not preset inputs.

Total annual water = calculated valley annual water + median simulated annual wind-curtailment water.

Unit operating-cost bounds = (valley electricity cost + annual chemical-reagent/routine-O&M cost bound) / total hybrid water. Annual non-electric OPEX of RMB 8,000–18,000 and valley electricity price RMB 0.272/kWh are screening assumptions, not site-verified costs. Wind-surplus marginal electricity cost is assumed zero. No equipment CAPEX is included.

## Reproducible run

```bash
python islandos_nanao_hybrid.py
python -m unittest discover -s tests -p 'test_nan_ao_hybrid.py' -v
```

The script writes `outputs/scenario_result.csv` with exactly one data row for `IslandOS_hybrid_clean_energy`, and `outputs/sim_meta.json` with the seed, run count, all model parameters, calculation notes, simulated water/hour statistics, and limitations. Console output contains only the hybrid result. Default seed: `20261028`.

## Limitations

This is a simulation-only result, not field-calibrated or a validated forecast. Event distributions are assumptions, not measured Nan'ao curtailment records. Exact installed hardware inventory and availability require on-site confirmation. The 50 L/person/day population figure is a theoretical annual supply equivalent and does not establish water quality, storage, distribution, or continuous access.
