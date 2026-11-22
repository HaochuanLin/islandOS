# INTEGRATION: prediction → optimization → economics → decision

This document is the data contract between the four stages of an IslandOS planning run. It exists so a second implementer can build a new stage, a new adapter or a new UI surface against the existing ones without guessing field names, units or failure behaviour.

It describes what the code does today. Where the code does not yet enforce something this document promises, the gap is listed in [§8 Gaps](#8-gaps-between-contract-and-code) rather than smoothed over.

Scope: offline planning only. Nothing in this chain produces a device command, and every stage is advisory. The single end-to-end composition point is `islandos_core/planning_workflow.py::run_forecast_dispatch`, which binds a run manifest to a forecast and a resource schedule; the economics and decision stages are composed separately (see §6 and §7).

---

## 1. Stage map

| Stage | Responsibility | Entry point | Produces | Consumed by |
|---|---|---|---|---|
| 0. Input & manifest | Freeze provenance, signals, units, horizon, scenario | `islandos_core/canonical_run.py::create_run_manifest` | `CanonicalRunManifest` (canonical JSON + `manifest_sha256`) | Stage 1 gate, Stage 2 horizon/settings |
| 1. Predict | Rank forecast candidates per signal, emit hourly points + bands + holdout metrics | `islandos_core/forecast_signal_catalog.py::forecast_site_signals` | `SiteForecastBundle` (`results: signal_id → PredictionResult`) | Stage 2 |
| 2. Optimize | Convert forecasts to dispatch series, search a schedule across stress scenarios | `islandos_core/prediction_dispatch_adapter.py::optimize_prediction_resource_schedule` → `forecast_optimizer_adapter.py::optimize_forecasted_resource_schedule` | Optimizer result dict (`recommendation`, `candidates`, `physical_audit`, `generic_prediction_handoff`, `robust_customer_economics`, `decision_scope`) | Stage 3, Stage 4, UI |
| 3. Economics | Cost comparison only at equivalent modeled service; annual investment metrics | `forecast_optimizer_adapter.py::build_service_equivalent_economics`, `islandos_core/investment_economics.py::evaluate_investment_economics` | Service-equivalent economics dict; `InvestmentEconomics` | Stage 4 |
| 4. Decision | Hash-addressed human-review record; read-only screening recommendation | `islandos_core/operator_decision.py::build_operator_decision_record`, `islandos_core/decision.py::recommend_ro_screening` | `offline_operator_decision_record`; `read_only_screening` payload | Human reviewer, audit log |

Provenance chain, each link a SHA-256 of the previous payload:

```
dataset_sha256 → manifest_sha256 → forecast bundle history sha256
  → optimizer evidence (manifest + bundle + selected models + recommendation)
  → operator decision record_sha256
```

Any stage may be re-run independently, but a stage's output is only valid for the digest it names. A changed input invalidates everything downstream.

---

## 2. Convenience conventions (apply to every stage)

| Topic | Rule | Enforced by |
|---|---|---|
| Timestamps | `datetime` with an explicit timezone, normalised to UTC; serialised as ISO-8601 with offset (`+00:00`), never naive, never `Z`-only | `forecast_signal_catalog._timestamps`, `canonical_run._utc_timestamp`, `operator_decision._utc` |
| Sampling | One row per hour, strictly increasing, **contiguous** — a missing hour is a contract violation, not a gap to interpolate | `forecast_signal_catalog._timestamps` |
| Units | Every signal carries an explicit unit string; `currency/kWh` or an ISO currency form (`USD/kWh`) for prices; power in `kW`, energy in `kWh`, water in `m3/h` or `m3` | `forecast_signal_catalog._validate_unit`, `prediction_dispatch_adapter` |
| Missing values | Never imputed. A gap fails the stage that needs the value | all stages |
| Numbers | Finite, JSON-serialisable; `NaN`/`Infinity` rejected before hashing | `canonical_run._json_value`, `planning_workflow._canonical_digest` |
| Failure mode | Fail closed: raise `ValueError` (or `OptimizationError`) with the specific check named; never fall back to defaults or partial data | every stage |
| Safety boundary | `device_write_authorized: false`, `command_generated: false`, `human_review_required: true` appear in every payload that could be mistaken for control | Stage 2, Stage 4 |

---

## 3. Stage 0 — input and manifest

Producer: `create_run_manifest(...)`. Consumer: `run_forecast_dispatch` (verifies before any model runs).

Required fields:

| Field | Type | Notes |
|---|---|---|
| `project_id`, `run_id`, `site_ref` | non-empty str | identity of the run |
| `created_at_utc` | ISO-8601 str with offset | normalised to UTC |
| `dataset_sha256` | 64-hex str | digest of the exact input dataset |
| `dataset_schema_version` | str | schema of the dataset, not of this document |
| `source_type` | enum | `measured`, `customer_provided`, `public_reanalysis`, `synthetic`, `forecast`, `vendor_specification`, `inferred` |
| `site_configuration_version`, `site_configuration_sha256` | str | asset/configuration identity |
| `required_signals` | `{signal_id: unit}` | non-empty; must include `tariff_per_kwh` for the current dispatch workflow |
| `forecast_horizon_hours` | int ≥ 1 | also the required length of the availability arrays |
| `optimizer_id`, `optimizer_version` | str | `optimizer_id` must be `prediction_resource_dispatch` for this workflow |
| `optimizer_settings` | mapping | whitelisted keys only, see below |
| `scenario_assumptions` | mapping | must contain the exact `grid_available` / `diesel_available` arrays used at runtime |
| `forecast_model_ids` | `{signal_id: model_id}` | optional; if present, selected models must match exactly |
| `forecast_settings` | mapping | defaults `backtest_horizon=24`, `season_length=24`, `confidence_level=0.90` |

Whitelisted `optimizer_settings`: `population_size`, `generations`, `seed`, `max_unmet_load_kwh`, `max_critical_unmet_load_kwh`, `terminal_battery_soc_min`, `water_schedule_mode`, `water_lookahead_hours`. Any other key is rejected, not ignored.

Output: canonical JSON payload plus `manifest_sha256`. Callers receive detached dicts, so mutating the returned mapping cannot change what was hashed.

---

## 4. Stage 1 — predict

```python
SiteForecastBundle = forecast_site_signals(
    timestamps, history, units,
    horizon=1..168,
    backtest_horizon=24, season_length=24, confidence_level=0.90,
)
```

Input contract:

- `timestamps: Sequence[datetime]` — at least 72, tz-aware, contiguous hourly UTC instants. Anything else raises.
- `history: {signal_id: Sequence[float]}` — every series has the same length as `timestamps`; no `None`/`NaN`; known signals are sign-checked (e.g. power signals must be non-negative).
- `units: {signal_id: str}` — exactly the same key set as `history`; unit must equal the canonical unit for a registered signal (`kW`, `%`, `currency/kWh`, `L/h`, `m3/h`, `degC`).
- Registered signals: `load_kw`, `flexible_load_kw`, `critical_load_kw`, `pv_power_kw`, `wind_power_kw`, `grid_import_kw`, `grid_export_kw`, `diesel_power_kw`, `battery_charge_kw`, `battery_discharge_kw`, `battery_soc_pct`, `tariff_per_kwh`, `diesel_fuel_lph`, `water_demand_m3_per_hour`, `temperature_c`. Custom signal IDs are allowed when given an explicit unit, without sign checks.

Output contract (`SiteForecastBundle`):

| Field | Type | Notes |
|---|---|---|
| `input_history_sha256` | 64-hex str | digest of the exact history used |
| `history_start_utc`, `history_end_utc` | `datetime` | first and last observation |
| `results` | `{signal_id: PredictionResult}` | one per input signal |
| `planning` | `PlanningForecast` | aggregate planning view + `limitations` list |

Each `PredictionResult` (`islandos_core/prediction_engine.py`) carries `signal_id`, `unit`, `model_id`, `model_version`, `input_history_sha256`, `confidence_level`, `interval_method`, `interval_calibration_samples`, `points` (`timestamp`, `predicted_value`, `lower_bound`, `upper_bound`), `backtest` (`CandidateMetrics`: `folds`, `samples`, `mae`, `rmse`, `wape_percent`, `bias_predicted_minus_actual`, `fold_metrics`), and `limitations`.

Rules:

- Points are the `horizon` hours **after** `history_end_utc`, one per hour, UTC.
- Model selection is per signal, by rolling-origin replay; a baseline that beats the candidate is selected and reported, not hidden.
- Bands are empirical residual bands, **not** calibrated prediction intervals; the optimizer's central case uses point values only, stress evaluation uses the bounds.
- No imputation, no resampling, no silent unit conversion at this stage.

---

## 5. Stage 2 — optimize

```python
result = optimize_prediction_resource_schedule(
    bundle.results, energy_system_config,
    history_start_utc=bundle.history_start_utc,
    history_end_utc=bundle.history_end_utc,
    grid_available=[bool]*horizon, diesel_available=[bool]*horizon,
    price_unit="currency/kWh",
    population_size=16, generations=8, seed=20261113,
    max_unmet_load_kwh=None, max_critical_unmet_load_kwh=None,
    terminal_battery_soc_min=None,
    water_service=WaterServiceSpec|None, water_schedule_mode="just_in_time|price_aware|auto",
    water_lookahead_hours=6,
)
```

Input conversion (the only place signal IDs are renamed):

| Forecast signal | Dispatch series |
|---|---|
| `pv_power_kw` | `pv_power` |
| `wind_power_kw` | `wind_power` |
| `load_kw` | `essential_load` |
| `tariff_per_kwh` | `electricity_price` (unit string passed through) |
| `flexible_load_kw`, `critical_load_kw` | optional, same names |

Preconditions that fail closed: `tariff_per_kwh` present with a unit; `pv_power_kw` and `load_kw` forecasts of unit `kW`; availability arrays of exactly `horizon` booleans; water mode `auto` requires a `water_demand_m3_per_hour` forecast **and** a `WaterServiceSpec`.

Output — top-level keys the next stages may rely on:

| Key | Type | Meaning |
|---|---|---|
| `recommendation` | mapping | `policy`, `weighted_score`, `weights{cost,reliability,curtailment,battery_wear}`, `objectives{estimated_energy_cost, unmet_load_kwh, renewable_curtailed_kwh, battery_throughput_kwh}`, `scenario_results{name: {summary, feasible}}` |
| `candidates` | list of mappings | every evaluated policy with its `summary` |
| `physical_audit` | mapping | `passed: bool` plus the violated constraints; a failed audit blocks the decision stage |
| `dispatch` | mapping | `rows` (per-timestep setpoints) and `summary` (totals, see below) |
| `generic_prediction_handoff` | mapping | `canonical_signal_mapping`, `source_signal_ids`, `forecast_model_versions`, `source_history_sha256`, `target_timestamps_utc`, `mode: "offline_schedule_search"`, `device_write_authorized: false` |
| `water_service` | mapping | only with water: production, inventory, `ro_power_kw_added_to_essential_load`, `service_feasible`, `production_policy`, `estimated_ro_energy_cost` |
| `robust_customer_economics` | mapping | worst-case service-equivalent economics (Stage 3) |
| `forecast_provenance` | mapping | `history_sha256`, `model_ids`, `target_timestamps_utc`, `price_unit` |
| `forecast_scenario_scope` | mapping | nominal + stress scenarios, `scenario_probabilities_assigned: false`, `same_schedule_replayed_across_all_scenarios: true` |
| `decision_scope` | str | plain-language boundary of what the result may be used for |

`dispatch.summary` keys (all floats, `kWh`/`currency`/counts as the name implies): `load_energy_kwh`, `load_served_kwh`, `unmet_load_kwh`, `critical_load_energy_kwh`, `flexible_load_energy_kwh`, `critical_unmet_load_kwh`, `flexible_load_shed_kwh`, `pv_energy_kwh`, `wind_energy_kwh`, `renewable_curtailed_kwh`, `battery_charge_input_kwh`, `battery_discharge_output_kwh`, `grid_import_kwh`, `diesel_generation_kwh`, `diesel_start_count`, `diesel_stop_count`, `diesel_start_cost`, `diesel_stop_cost`, `grid_energy_cost`, `diesel_energy_cost`, `diesel_fuel_cost`, `grid_export_energy_kwh`, `grid_export_revenue`, `peak_grid_import_kw`, `grid_demand_charge`, `battery_throughput_kwh`, `battery_degradation_cost`, `battery_capacity_fade_kwh`, `battery_equivalent_full_cycles`, `diesel_fuel_used_liters`.

Rules:

- The search is a seeded bounded heuristic over a declared model. It is not a global optimum, and `model_scope` says so.
- Every candidate is evaluated by the same physical dispatch engine on the same inputs; a candidate the engine clips is marked infeasible rather than silently repaired.
- Stress scenarios replay one schedule across deterministic envelopes; the objective is the worst case. No probabilities are assigned and the bounds are not joint confidence intervals.

---

## 6. Stage 3 — economics

Two separate contracts. Do not mix them.

### 6.1 Operating economics (per run, service-gated)

Producer: `build_service_equivalent_economics(result, tolerance=1e-6)`, or `_robust_service_equivalent_economics` for the stress-worst case.

| Field | Type | Meaning |
|---|---|---|
| `reference_policy` | str | always `grid_first` |
| `reference_is_measured_site_operation` | bool | always `false` |
| `recommended_policy` | str | policy from `recommendation` |
| `service_equivalent` | bool | all four service deltas within `tolerance` |
| `service_tolerance` | float | echo of the tolerance |
| `service_deltas_recommended_minus_reference` | `{load_served_kwh, unmet_load_kwh, critical_unmet_load_kwh, flexible_load_shed_kwh}` | rounded to 8 dp |
| `cost_components` | `{key: {reference, recommended, difference_recommended_minus_reference}}` | `estimated_energy_cost`, `gross_energy_cost`, `grid_energy_cost`, `diesel_energy_cost`, `diesel_fuel_cost`, `battery_degradation_cost`, `grid_demand_charge`, `grid_export_revenue` |
| `cost_comparison_valid` | bool | equals `service_equivalent` |
| `estimated_cost_reduction`, `estimated_cost_reduction_percent` | float or `null` | `null` unless service is equivalent |
| `interpretation` | str | the sentence to show a customer; never a claim of measured savings |

Rule: a cost difference exists only where service is equivalent. If service differs, the numbers are still reported per component but the saving is withheld (`null`), and reliability must be discussed before any economic conclusion.

### 6.2 Investment economics (annual, service-gated)

Producer: `evaluate_investment_economics(...)`. Inputs: `baseline_annual_energy_cost`, `proposed_annual_energy_cost`, `annual_incremental_om_cost`, `upfront_capex`, `project_life_years`, `discount_rate`, optional `replacement_year`, `replacement_cost`, `residual_value`, `annual_energy_saving_escalation_rate`, `annual_om_escalation_rate`, and `service_equivalent: bool`.

Output `InvestmentEconomics` (frozen dataclass, `to_dict()` for serialisation): `service_equivalent`, `annual_energy_cost_saving`, `annual_net_operating_benefit`, `simple_payback_years`, `discounted_payback_years`, `net_present_value`, `break_even_annual_energy_saving`, `sensitivity_npv`, `annual_cashflows`, `decision`, `reasons`.

Assumptions that must be recorded with any use of these numbers: energy-bill saving and incremental O&M are year-one values; escalation applies from year two; a single simulated day is never annualised; `service_equivalent=False` blocks every investment metric.

---

## 7. Stage 4 — decision

Two producers, one rule: neither can emit a command.

### 7.1 Operator decision record

`build_operator_decision_record(optimization_result, site_ref, recommendation_id, created_at_utc, data_provenance, input_refs, objective_weights, operating_constraints)`

Required top-level fields of the record: `schema_version: 1`, `record_type: "offline_operator_decision_record"`, `site_ref`, `recommendation_id`, `created_at_utc`, `data_provenance`, `input_refs` (non-empty provenance strings), `algorithm`, `solver_status`, `optimality_proven_for_declared_model`, `objective_weights`, `operating_constraints`, `recommended_schedule`, `objectives_and_outcomes`, `baseline_comparison`, `customer_impact_assessment`, `physical_audit`, `status`, `human_review_required: true`, `operator_approval: "pending"`, `model_scope`, `device_write_authorized: false`, `command_generated: false`, `record_sha256`.

`recommended_schedule` copies only these keys when present: `battery_power_setpoint_kw`, `diesel_commitment_schedule`, `diesel_power_setpoint_kw`, `grid_import_model_kw`, `water_service`, `dispatch_rows`.

Gates: `status` is `ready_for_human_review` only when `optimization_result["physical_audit"]["passed"] is True`; otherwise `blocked_pending_audit`. A customer-impact benefit may be qualified only when both `service_equivalence.passed` and `equipment_constraint_audit.passed` are true, and a numeric benefit must carry `status: "qualified"` — the builder raises rather than producing a qualified benefit behind a failed gate.

### 7.2 Screening recommendation

`recommend_ro_screening(...)` returns a `ScreeningRecommendation`, whose `to_payload()` emits `{schema_version: "1.0", recommendation{action, reason, estimated_full_load_power_kw, water_inventory_m3, target_inventory_m3, renewable_surplus_kw, assumptions}, control_command: null, mode: "read_only_screening"}`.

This is a single-timestep heuristic recommendation for a human, not a schedule and not a control command.

---

## 8. Gaps between contract and code

Recorded because a second implementer will hit them:

1. **Timestamp-length check is weaker in the composition layer than in the forecast layer.** `run_forecast_dispatch` accepts three timestamps; `forecast_site_signals` then requires 72 contiguous hourly instants. A 3-row history fails one call later with a message from the forecast stage. Fix by moving the 72-row/contiguity check into the manifest or the composition layer.
2. **The decision record is not built inside `run_forecast_dispatch`.** The canonical run returns `recommendation`, `robust_customer_economics` and `decision_scope`, but the operator record is a separate call the caller (or UI) must make. Until that is composed, a "canonical planning run" is not by itself an auditable decision.
3. **Annual investment economics is not manifest-bound.** `evaluate_investment_economics` takes annual customer-entered bills and is not fed by the operating-economics stage; nothing currently proves the annual numbers derive from a run with the same `dataset_sha256`. Treat the two economic contracts as parallel until an adapter exists.
4. **Water extension changes `essential_load` in place.** The RO electrical load is added to `essential_load` points, and the combined digest is stored in the load result. A consumer that expects `essential_load` to mean "site load excluding water" will double count; the `water_service.ro_power_kw_added_to_essential_load` array is the explicit subtraction.
5. **`generic_prediction_handoff.target_timestamps_utc` is taken from the PV forecast.** It assumes all signals share the same horizon timestamps, which the catalogue currently guarantees, but the assumption is not asserted at that line.

## 9. Implementing against this document

1. Build the dataset and `create_run_manifest` first; never hand-build the payload.
2. Feed the manifest, the tz-aware hourly timestamps, `history`, `units`, and the two availability arrays to `run_forecast_dispatch`.
3. Take economics from `robust_customer_economics` (operating) and `evaluate_investment_economics` (annual, explicit assumptions); never compute a saving yourself from `dispatch.summary` without the service gate.
4. Build the operator record with `build_operator_decision_record`, and surface `status`, `physical_audit` and `human_review_required` before any number.
5. Log `manifest_sha256`, `forecast.bundle_sha256`, `evidence_sha256` and `record_sha256` together; a record without its digest chain is not evidence.

Reference tests: `tests/test_planning_workflow.py`, `tests/test_forecast_dispatch_demo.py`, `tests/test_operator_decision.py`, `tests/test_investment_economics.py`, `tests/test_prediction_dispatch_adapter.py`.
