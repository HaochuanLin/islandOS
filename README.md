# Nan’ao-type scenario — IslandOS｜Schneider Go Green 2026 Top-12 Finalist

> **Scenario-based simulation assumption, not measured real-world data.**
>
> This branch documents a synthetic Nan’ao-type scenario for Schneider Go Green 2026 review. It is not based on a measured Nan’ao curtailment time series, is not a grid power-flow model, and does not establish field performance or site feasibility.

## Scenario at a glance

The script estimates annual theoretical water yield from assumed export-limitation events that could supply surplus energy to a proposed **50 kW reverse-osmosis (RO) unit**. It runs 1,000 Monte Carlo scenario years with fixed seed `20261021`.

These are assumption-driven scenario outputs—not measured water production, a validated forecast, or evidence that the modeled events occurred on Nan’ao.

## Reproduce the results

Use Python 3.10 or later. The scenario script uses only the Python standard library.

```bash
python nan_ao_scenario.py --runs 1000 --seed 20261021 --output-dir outputs/nan_ao
```

The seeded run reports the following annual-yield percentiles:

| Metric | Result |
|---|---:|
| P5 | 237.6 m³/year |
| Median | 442.7 m³/year |
| P95 | 693.2 m³/year |

All values above are **synthetic scenario simulation results, not measured real-world data**. They depend on the explicit assumptions described in [the scenario protocol](docs/NAN_AO_SCENARIO.md). Re-running with the same script, Python version, run count and seed is intended to reproduce the same results.

The command writes the annual run log, percentile summary, assumptions/limitations JSON, sensitivity grid, and illustrative capital-only screen to `outputs/nan_ao/`. The output directory is generated locally and does not need to be committed.

## Model assumptions and limitations

The model uses assumed distributions for annual event count, event duration, available surplus power and RO availability. It caps usable power at the proposed 50 kW RO rating and converts usable energy to theoretical water volume using an assumed specific energy consumption of 4.0 kWh/m³.

This is an **annual event-energy abstraction**, not a grid power-flow/network-congestion model. No measured Nan’ao renewable-generation, demand, export-limitation or curtailment time series is used. The model does not verify equipment availability, water quality, permits, site feasibility, savings, ROI, emissions reductions or avoided outages.

See [docs/NAN_AO_SCENARIO.md](docs/NAN_AO_SCENARIO.md) for the full assumptions, sensitivity analysis, equipment boundary, and evidence needed before any real-world deployment claim.

## Keep the two IslandOS demos separate

| Branch / scenario | Purpose | Parameters |
|---|---|---|
| `nan-ao-scenario-pilot` (this branch) | Schneider Go Green 2026 Nan’ao-type case | 50 kW RO; 4.0 kWh/m³; event-energy model; 1,000 Monte Carlo runs; seed `20261021` |
| `main` | General-purpose IslandOS prototype and generic isolated-island demo | 400 kW; 3.5 kWh/m³; synthetic 24-hour demo |

**Do not mix results from these two scenarios.** This branch is dedicated to the Go Green review case. For the general-purpose IslandOS project and other competitions, switch to the [main branch](https://github.com/HaochuanLin/islandOS/tree/main).

The repository-level [requirements.txt](requirements.txt) lists dependencies for the broader IslandOS project. The standalone Nan’ao scenario script itself requires only the Python standard library.
