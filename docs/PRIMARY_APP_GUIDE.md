# Primary Streamlit app guide

## Scope

This guide covers the main `app.py` Streamlit interface: the generic energy–water strategy simulator, its CSV upload contract, and its downloadable reports. It is a research and screening interface, not a live microgrid controller. The app does not forecast equipment telemetry or issue commands to physical systems.

**Important:** the interactive app CSV schema documented here differs from the command-line strategy experiment schema in [Energy–water strategy comparison](ENERGY_WATER_STRATEGY_COMPARISON.md). Do not interchange the two formats without an explicit, reviewed conversion.

## Start locally

From the repository root, use the [local deployment runbook](DEMO_DEPLOYMENT.md). Record `git rev-parse HEAD` with any report you share. The bundled demonstration input is synthetic and must not be described as measured island data.

## Interactive app CSV contract

Upload one row per simulation interval, with timestamps in strictly increasing order. Required columns:

| Column | Unit / meaning | Validation and interpretation |
|---|---|---|
| `timestamp` | Timestamp text | Must be non-empty and strictly increasing. The app's strategy parser checks ordering, not whether the timestamp timezone or interval is physically correct. |
| `renewable_surplus_kw` | kW | Surplus available to flexible loads after essential demand and operating reserves. Do not enter raw renewable generation as surplus without accounting for essential loads. |
| `diesel_displacement_potential_kw` | kW | Separate estimate of potential direct diesel displacement. It is not a measured fuel saving and is not attributed to RO operation. |
| `grid_price_per_kwh` | Currency/kWh | Supply a site-appropriate price and document the currency and tariff convention. |
| `off_peak` | Boolean flag | Accepts `true/false`, `yes/no`, or `1/0`; reflect the actual tariff schedule. |
| `grid_available` | Boolean flag | Accepts `true/false`, `yes/no`, or `1/0`; set consistently with the site's operating mode. |
| `water_demand_m3` | m³ per interval | Demand volume for the same time interval represented by the row. |

Optional `backup_available_kw` is the spare backup-generation power available to the RO load, in kW. If it is omitted or blank, the app treats it as zero. Do not enter generator nameplate capacity unless it is actually spare after critical loads and operating constraints.

Numeric values must be finite and non-negative. Missing values are not imputed. The selected `dt_hours` setting must match the uploaded interval; the app does not infer a trustworthy physical interval from timestamp text alone. If validation or simulation fails, fix the source data or assumptions rather than filling or clipping values silently.

## What the app exports

When a strategy comparison completes, the app offers:

- **Strategy summary CSV:** aggregate water service, energy use/cost, RO runtime, spill, ending inventory, and related strategy metrics.
- **Timestep audit CSV:** per-interval strategy decisions and water/energy accounting.
- **NSGA-II Pareto CSV:** feasible candidate schedules returned by the optimizer, if the configured search finds any.

The strategy summary, timestep audit, and NSGA-II Pareto exports include provenance and run-configuration columns:

- `source_type`: `synthetic` for the built-in demonstration or `user_uploaded_unverified` for uploaded input.
- `source_label`: the displayed input label; for uploads it includes the uploaded filename.
- `input_sha256`: SHA-256 of the exact input bytes used by the app.
- `run_signature`: a deterministic SHA-256 signature over the exact input hash and the settings relevant to that report. For strategy CSVs this is the strategy run signature; for Pareto CSVs it is the optimizer run signature.
- Strategy configuration columns include `ro_rated_power_kw`, `specific_energy_kwh_m3`, `tank_capacity_m3`, `initial_water_m3`, `min_run_hours`, `input_interval_hours`, and `backup_energy_cost_per_kwh`.
- Pareto exports also include `optimizer_population_size`, `optimizer_generations`, `optimizer_seed`, and `optimizer_build`.

The input hash helps identify whether two reports used identical input bytes. The run signature helps identify whether reports were generated from the same input and relevant settings. **Neither proves the source is authentic, data are measured, units are correct, the dataset is complete, the data are licensed for use, or the measurements are accurate.** Keep the original input, its external source/licence record, app commit SHA, model assumptions, and exported files together for reproducibility.

If input bytes or model settings change while results remain in the Streamlit session, the app clears stale strategy and optimizer results rather than showing or exporting a report computed from a different configuration. Changing optimizer budget/build settings also invalidates the cached Pareto result. Run the relevant comparison or optimizer again to generate a result for the current configuration.

## Interpretation and limits

- A result is conditional on the uploaded series and the chosen configuration; it is not a prediction of realized plant performance.
- The rule-based strategies and NSGA-II search are not a trained ML forecast. The optimizer searches a bounded set of candidate schedules and can fail to find a feasible schedule within its search budget.
- Zero unmet demand in a simulation is a model result, not proof of real-world water security or equipment feasibility.
- The model does not replace detailed power-flow analysis, water-quality checks, environmental permits, full lifecycle costing, equipment interlocks, cybersecurity review, or operator approval.
- Do not connect this UI directly to PLCs or actuators. Keep deployment loopback-only unless an approved security architecture is implemented and reviewed.
- Do not upload confidential or restricted site data unless the data owner has approved the environment, access, retention, and handling arrangements.

## Verification

The primary app has Streamlit AppTests for visible source provenance and run signatures, and regression coverage that strategy and optimizer output is discarded when the input or run configuration no longer matches. Pull-request CI also exercises the full pytest suite, scenario validation, container startup, Windows packaging, and hosted-app health diagnostic. A passing health diagnostic does not mean the external hosted app is publicly accessible, and a passing software test does not validate physical model fidelity.
