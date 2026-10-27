# Nan'ao emergency-resilience pilot — IslandOS

> **Scenario-based Monte Carlo simulation, not field-validated performance.**

This branch contains a Nan'ao-type emergency water-resilience pilot model. It treats a reusable, pre-existing reverse-osmosis (RO) unit as a sunk asset: **RO purchase capital expenditure is RMB 0 in the primary scenario**. The operating-cost screen includes valley-price electricity where applicable and draft annual operating-cost assumptions for electricity, chemicals, membrane maintenance, and routine O&M. Those O&M assumptions must be verified against site records.

The pilot explores supplementary emergency freshwater production from otherwise-curtailed wind power and valley-price electricity. It is **not a model of full-island daily water supply**.

## Scenario files

- `nan_ao_scenario.py`: assumption-driven annual event-energy Monte Carlo simulation for potential wind-curtailment windows.
- `nan_ao_three_scenarios.py`: compares wind-only, valley-price-only, and hybrid screening cases; exports JSON.
- `docs/NAN_AO_SCENARIO.md`: assumptions, boundaries, and evidence gaps.
- `tests/test_nan_ao_scenario.py` and `tests/test_nan_ao_three_scenarios.py`: deterministic and output-contract tests.

## Reproduce

Use Python 3.10 or later; the core scenario uses the Python standard library.

```bash
python nan_ao_scenario.py --runs 1000 --output-dir build/nan_ao
python nan_ao_three_scenarios.py --output-json build/nan_ao_three_scenarios/summary.json
python -m unittest discover -s tests -p 'test_nan_ao_*.py' -v
```

The default run uses 1,000 Monte Carlo samples and a fixed seed for reproducibility. Output filenames are stable and do not encode the seed:
- `nan_ao_annual_runs.csv`
- `nan_ao_percentiles.csv`
- `nan_ao_summary.json`
- `nan_ao_sensitivity.csv`

The three-scenario report contains water-yield ranges, annual operating-cost assumptions, valley electricity cost, unit operating-cost screening ranges, and a theoretical annual-supply population equivalent at 50 L/person/day.

## Model boundary and limitations

The wind model samples assumed annual event counts, durations, available surplus power, and RO availability. It is an annual event-energy abstraction—not an hourly grid-flow model, measured curtailment reconstruction, or validated dispatch optimizer. The valley-price annual water quantity is a fixed screening assumption, not calculated from site hourly load and wind time series. The hybrid adds these quantities and assumes the operating windows do not overlap.

The model does not verify that modeled events occurred, whether the RO equipment exists or is operable, water quality, intake/outfall, storage, distribution, permits, actual O&M, cost savings, ROI, or emergency access. All yield and cost results are scenario screens only. The population figure is an annual-supply equivalent, not evidence that water can be delivered safely to that number of people.

## Keep the generic IslandOS demo separate

The public [IslandOS Streamlit demo](https://islandos.streamlit.app/) is a separate generic synthetic 24-hour energy-water demonstration. Do not treat it as a live Nan'ao dispatch controller or as validation of this annual pilot model. The generic `main` branch is outside the scope of this scenario branch.
