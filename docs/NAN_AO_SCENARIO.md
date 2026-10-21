# Nan'ao Island scenario: RO as a flexible load

This is a separate, reproducible scenario for the IslandOS prototype. It does **not** replace or reinterpret the repository's original 24-hour synthetic isolated-island demo.

## Run it

```bash
python nan_ao_scenario.py --runs 1000 --seed 20261021 --output-dir outputs/nan_ao
```

The command writes:
- `nan_ao_annual_runs.csv`: one row per simulated scenario year;
- `nan_ao_percentiles.csv`: P5, median, P95 and mean scenario yield;
- `nan_ao_summary.json`: assumptions, summary and limitations.

Only the Python standard library is required. Repeating the same command with the same Python version, run count and seed is deterministic.

## What the model represents

The model draws an assumed annual count of export-limitation events, event durations, available surplus power, and RO availability. During each event, usable RO energy is the duration multiplied by the lesser of available surplus power and the proposed RO rating. Water volume is usable energy divided by the assumed specific energy consumption.

All distributions are explicit placeholders, not measurements or verified Nan'ao operating statistics. This is an annual event-energy abstraction, **not** a grid power-flow model and not a reconstruction of actual curtailment. It does not establish that any event happened on Nan'ao.

## Equipment status and deployment boundary

No publicly accessible official documentation reviewed by the team confirms an operable standby seawater RO unit on Nan'ao main island. The pilot therefore assumes a modular 50 kW RO unit would be procured, installed and owned by the local water authority, subject to site verification, approval and budget.

The scenario does not prove site feasibility or water quality, and does not estimate savings, ROI, emissions, avoided outages or measured annual water yield. Results must be described as **“Scenario-based simulation assumption, not measured real-world data.”**

## Next evidence needed

Replace the placeholder distributions with documented hourly export-limit/curtailment records, renewable output and essential load; confirm candidate installation site, seawater intake/outfall, water-quality requirements, permissions, equipment quotations and operating responsibility. Then rerun the model and update external pitch materials only from that reviewed result.
