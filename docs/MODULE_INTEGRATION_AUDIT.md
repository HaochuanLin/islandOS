# IslandOS module integration audit

- **Date:** 2026-11-24
- **Baseline:** `origin/main` at `d4a6139e0614a5344bf9ac3ef8418eb43684eed2` (`Merge pull request #330 from HaochuanLin/docs/overlap-check-in-pr-template`)
- **Branch:** `audit/module-integration`
- **Mode:** read-only code trace; no application code was changed, no PR was opened
- **Scope:** `app.py`, `pages/05_Customer_Decision_Dashboard.py`, `pages/06_Forecast_Led_Joint_Resource_Optimizer.py`, `pages/09_Device_Flexibility_Planner.py`, `pages/2_Rolling_Horizon_Lab.py`, and the relevant sections of `islandos_ui/workspace.py`. Local-only pages `07`/`08` are out of scope because they are not registered unless a local deployment flag is set (`app.py:103-117`).
- **What “integrated” means here:** the output of one stage is passed as an input to the next stage **inside one actual application run**, and the resulting object is rendered or exported by that surface. A Python file, an import, or a unit test alone is not integration evidence.

## Executive verdict

There is **no single six-stage pipeline** in the current application. There are several real chains with different depth:

| Surface | INPUT | FORECAST | SIMULATION | OPTIMISATION | ECONOMIC EVALUATION | RESULTS | Verdict |
|---|---|---|---|---|---|---|---|
| 05 Customer Decision Dashboard | Y | Y | P (inside optimizer + stress/paired replay) | Y (bounded two-policy comparison) | Y (24 h service-equivalent + customer-entered annual investment) | Y (JSON report + operator record) | Strongest end-to-end customer story, but annual investment is detached from run replay |
| 06 Forecast-Led Joint Resource Optimizer | Y | Y | P (inside candidate search) | Y (seeded mixed search) | Y (24 h robust economics + optional equal-day annual projection) | Y (JSON audit) | Strongest forecast-to-schedule chain; annual is optional and replay returns `annual: null` |
| 09 Device Flexibility Planner | Y (fixed demo inputs) | N | Y (schedule replay + earliest-feasible reference) | P (rule-based scheduler, not an optimizer) | P (24 h energy cost only) | Y (CSV + JSON) | A deliberate isolated device demo, not a continuation of 05/06 |
| Workspace: Microgrid screening | Y (numeric controls) | Y (seasonal-naive baseline) | Y | Y (coordinate search) | P (per-m³ operating indicators, no CAPEX/payback) | Y (several CSVs) | The only one-button surface that touches all six stages, but it is synthetic, has no input fingerprint, and its copy calls the result “not a forecast” while it does forecast |
| Workspace: Forecast lab | Y | Y | N | N | N | P (CSV only) | Forecast output is exported, then not consumed by any optimizer |
| Workspace: Strategy simulator | Y | N | Y | Y (NSGA-II after the five-policy comparison) | Y (24 h RO operating cost) | Y (CSV) | Simulation/optimization are connected, but there is no forecast stage |
| Workspace: Flexible-load optimizer | Y | P (tariff only) | Y | Y (LP dispatch) | Y (24 h cost) | Y (CSV) | A real tariff-forecast-to-dispatch chain, but not the site forecast chain |
| Rolling Horizon Lab | Y | P (forecast is an input column) | Y | N | N | Y (CSV) | Policy simulation only; no optimizer or economic evaluation |
| Workspace: Historical RO baseline | Y | N | N | N | Y (historical cost reconstruction) | Y (CSV) | Cost baseline only; no forecast, simulation, or optimization |

Legend: **Y** = actually connected and rendered/exported; **P** = partial or conditional; **N** = not present.

The shortest accurate description is: **05 and 06 are two separate forecast→dispatch→economics chains; 09 is a separate device-replay chain; Workspace contains additional partial chains, including one synthetic six-stage chain.** The module inventory is broad, but the application does not compose it into one pipeline with one run identity and one result envelope.

## Stage-by-stage trace

### 1. INPUT

| Path | Existing input format | Existing output format | Actual caller | Displayed? | Exportable? | Error handling | Verdict |
|---|---|---|---|---|---|---|---|
| 05 Customer Dashboard | CSV with exact headers `timestamp_utc`, `pv_power_kw`, `wind_power_kw`, `essential_load_kw`, `electricity_price_per_kwh`; UTC ISO-8601; at least 72 contiguous hourly rows. Page upload wins over a session-shared dataset. Without a file, an inline 168-hour synthetic history is generated. | `CustomerHistory` from `parse_customer_history_csv` (`timestamps_utc`, canonical `signals`, `source_sha256`); synthetic path yields aligned timestamp/signal lists. | `parse_customer_history_csv` and inline generation in `pages/05_Customer_Decision_Dashboard.py:161-193`; `run_customer_dashboard` receives the resulting history at `05:258-273`. | History window and provenance captions; input series are then charted through the forecast display. | Report carries `history_sha256` and `history_rows`, but not the raw history rows (`05:688-723`). | `ValueError` → `reject_upload` + `st.stop`; outer run catches `ValueError, KeyError, TypeError` (`05:740-742`). | Y for parsing/handoff; P for raw-data export. |
| 06 Joint Optimizer | Same five-column CSV parser, same UTC/hourly rules; or the shared synthetic builder. No XLSX path. | History dict with page keys `pv_power_kw`, `wind_power_kw`, `load_kw`, `tariff_per_kwh`; source hash when uploaded. | Page builds `signal_history`/`signal_units` at `06:148-164`; the run manifest is created at `06:243-270`; `run_joint_optimizer` is called at `06:274-282`. | History window and provenance captions; no raw input table. | Report carries `input_provenance` and `source_file_sha256`, not the raw series (`06:497-503`). | Upload `ValueError` → `reject_upload`; run errors caught at `06:534-536`. | Y for parsing; P for raw-data export. |
| 09 Device Planner | No file upload and no site-history parser. Fixed 24 h price/profile/task constants and a residual task budget (`09:36-82`). | `DeviceTask` objects and aligned PV/wind/base-load/tariff arrays; `build_run_request` includes `page_inputs.tasks`. | `09:42-91`. | Scenario assumptions are implicit in page copy; schedule and replay are shown later. | The JSON report includes the full request (`09:216-225`), so the input arrays are exportable. | Setup and schedule errors are caught as `ValueError` only (`09:52-94`). | Y, but fixed synthetic input only. |
| Workspace: Microgrid | Numeric scenario controls only (horizon, PV peak, wind mean, essential load, water demand, RO rating, specific energy, tank/inventory), no CSV. | 168 h synthetic `history`; dict of forecast series; `MicrogridInputs`, `MicrogridConfig`. | `islandos_ui/workspace.py:1180-1234`. | Controls plus a “Baseline forecast used by the scheduler” chart (`workspace.py:1275-1283`). | Candidate/search/stress CSVs, but no input control hash and no forecast CSV (`workspace.py:1360-1448`). | `ValueError`/`TypeError` around screening/search/robustness (`workspace.py:1246-1249`); initial inventory check stops at `1194-1196`. | P: synthetic input is real, but it is not traceable from export to controls. |
| Workspace: Forecast lab | CSV with inspected canonical header/unit; or built-in 168 h synthetic CSV. | `PredictionRequest`/history and an import report; not the same `ForecastBundle` used by 05/06. | `workspace.py:1757-1805`. | Import status, issues table, signal selector, forecast chart. | Forecast CSV (`workspace.py:1824`). | Broad `Exception` around inspection and forecast (`workspace.py:1825-1828`). | Y for standalone forecast input; N for feeding 05/06. |
| Workspace: Data onboarding | CSV or XLSX; optional provenance and expected interval. | Inspection report, readiness gate, and session-only dataset (`store_session_dataset`). | `workspace.py:1616-1708`. | Quality status, mappings, issues, preview. | Inspection JSON; session handoff is not a file. | Broad `Exception` for inspection; `ValueError` for CSV compatibility/handoff (`workspace.py:1632-1700`). | Y as the only cross-page input handoff; XLSX stops at inspection because 05/06 only parse CSV. |

**Input gap:** the application has two different synthetic histories for 05 and 06. 05 builds its own 168 h series with inline PV/wind/load/tariff formulas (`05:179-193`); 06 calls `build_synthetic_site_history` (`06:61-125`). Different coefficients and different demand/tariff scaling mean the same “demo site” does not produce the same input hash across the two customer surfaces. There is also no single raw-data export: 05/06 export hashes and row counts, not the history they actually used.

### 2. FORECAST

| Path | Existing input format | Existing output format | Actual caller | Displayed? | Exportable? | Error handling | Verdict |
|---|---|---|---|---|---|---|---|
| 05 Customer Dashboard | Aligned 168 h history with canonical signal names and units; `SiteAssumptions`. | `ForecastBundle` with four 24-point forecasts (`pv_power`, `wind_power`, `essential_load`, `electricity_price`), model IDs, holdout MAE/RMSE, P90 planning bounds, `input_history_sha256`. | `run_customer_dashboard` → `forecast_signals` (`islandos_core/run_orchestration.py:61-78`). | Forecast charts plus “Forecast model quality and provenance” expander (`05:309-350`). | Report contains only `forecast_models` model IDs (`05:705`); no forecast point CSV. | Forecast `ValueError` is caught by the page-level handler (`05:740`). | Y consumed by the optimizer; P export. |
| 06 Joint Optimizer | Canonical 168 h history with units; run manifest declares signals, horizon, backtest settings, confidence. | `predictions`: mapping of canonical signal → `PredictionResult` (24 points, model/version, backtest, bounds, history digest). | `run_joint_optimizer` → `run_forecast_dispatch` → `forecast_site_signals` (`run_orchestration.py:118-129`; `planning_workflow.py:40-144`). | Only a “Prediction engine” table with model/MAE/RMSE/band samples (`06:290-302`); raw forecast values are not rendered. | Report contains model IDs and metrics (`06:499-503`); no forecast point CSV. | Outer `(ValueError, KeyError, TypeError)` handler (`06:534`). | Y consumed; P display/export. |
| 09 Device Planner | None. | None. | None. | None. | None. | None. | N. |
| Workspace: Microgrid | 168 h synthetic generation/load/water history. | Dict of forecast lists `pv_kw`, `wind_kw`, `essential_load_kw`, `water_demand_m3`; no model metadata is returned by the forecast function. | `forecast_microgrid_signals` at `workspace.py:1211`. | Baseline forecast chart at `workspace.py:1275-1283`. | Not included in the candidate, search, or stress CSVs. | `ValueError`/`TypeError` in the surrounding scenario block. | P: forecast is real and consumed, but not exportable as a forecast artifact. |
| Workspace: Forecast lab | Inspected CSV signal or built-in synthetic history. | `PredictionResult` from `PredictionEngine.forecast` with selected model, backtest, empirical bounds, points, `input_history_sha256`. | `workspace.py:1799-1824`. | Forecast chart and model metrics. | Forecast CSV (`workspace.py:1824`). | Broad `Exception` blocks both inspection and forecast. | Y standalone; X for the optimizer chain because no downstream call exists. |

**Forecast gap:** three forecast implementations exist (05 `forecast_signals`, 06 `forecast_site_signals`, Workspace `PredictionEngine`/`forecast_microgrid_signals`). Only 05/06 feed an optimizer. Forecast lab can export a forecast CSV, but no page imports that result; it is a dead end. Within 05/06 the forecast values are plotted or summarized, but the exact 24-point series is not exported, so an auditor cannot reconstruct the optimizer input from the JSON alone.

### 3. SIMULATION

| Path | Existing input format | Existing output format | Actual caller | Displayed? | Exportable? | Error handling | Verdict |
|---|---|---|---|---|---|---|---|
| 05 Customer Dashboard | `EnergySystemInputs` from coordinated forecasts; `EnergySystemConfig`; two explicit policies. | Per-candidate `dispatch_energy_system` dict (`rows`, `summary`, audit); stress scenario results; paired grid-first/battery-first impact. | `optimize_energy_system` internally calls `dispatch_energy_system` (`optimization/energy_system_optimizer.py:136-152`); `evaluate_forecast_stress_scenarios` and `assess_energy_policy_impact` in `run_orchestration.py:79-98`. | Policy comparison table, stress table, paired impact table (`05:352-431`). The selected hourly dispatch is not charted. | Full selected dispatch rows and setpoints are inside the operator JSON/report (`05:608-627`, `688-739`). | `OptimizationError`/`EnergyModelError` are `ValueError` subclasses; caught by `05:740`. | P: real simulation, but embedded and under-displayed. |
| 06 Joint Optimizer | Forecast `PredictionResult` map, config, manifest optimizer settings, availability flags. | Candidate results with dispatch rows, summaries, physical audits, recommendation/objectives. | `optimize_prediction_resource_schedule` → `optimize_forecasted_resource_schedule` → `optimize_battery_and_diesel_schedule` (`prediction_dispatch_adapter.py` and `energy_system_optimizer.py:657-689`). | Candidate comparison table and recommended setpoints (`06:304-357`); per-scenario detail is not separately rendered. | Recommendation/candidates in the audit JSON (`06:504-527`). | `(ValueError, KeyError, TypeError)` around the whole run (`06:534`). | P: simulation is inside the optimizer, not a first-class stage. |
| 09 Device Planner | Tasks, 24 h prices, residual power budget, PV/wind/base load, site config. | `DeviceSchedule`; `replay` and `reference_replay` from the shared simulator. | `run_device_planner`: `schedule_device_tasks` → `dispatch_energy_system` twice (`run_orchestration.py:261-300`). | Per-device schedule, hourly chart, like-for-like comparison (`09:101-164`). | Auditable schedule CSV (`09:203-208`); application-view JSON (`09:216-225`). | Only `ValueError` at setup/schedule (`09:52-94`). | Y: an explicit, visible simulation with a reference case. |
| Workspace: Microgrid | `MicrogridInputs`, `MicrogridConfig`, forecast series. | Ranked candidates, coordinate-search result, robustness results. | `screen_renewable_surplus_candidates`, `search_ro_schedule`, `evaluate_schedule_robustness` (`workspace.py:1235-1245`). | Ranked table, search chart, stress table, economics table (`workspace.py:1313-1448`). | Search schedule CSV, stress audit CSV, candidate comparison CSV. | `ValueError`/`TypeError` around the block; `st.stop` on failure. | Y for simulation visibility; P for provenance. |
| Rolling Horizon Lab | Scenario CSV with actual and forecast surplus, water/cooling demand; or built-in synthetic scenario. | Four policy results (`rolling`, `ro_first`, `ice_first`, `perfect_information`) with hourly audit and unmet/constraint metrics. | `simulate_rolling` for four policies (`pages/2_Rolling_Horizon_Lab.py:116-130`). | Policy comparison and selected hourly audit (`2_Rolling...:152-197`). | Summary and audit CSVs with source hash (`2_Rolling...:160-186`). | `(ValueError, RuntimeError, ArithmeticError)` and clears stale results (`2_Rolling...:128-130`). | Y as a simulation lab; N for optimization/economics. |

**Simulation gap:** the shared physical simulator (`dispatch_energy_system`) is real and reused, but the application does not expose a common “simulation result” stage. 05/06 hide it inside optimization; 09 and microgrid expose it; Rolling Horizon uses a separate `experiments.rolling_horizon_dispatch` simulator. A reader cannot compare “same input, same simulation, different optimizer” across surfaces because the scenario identities and result schemas differ.

### 4. OPTIMISATION

| Path | Existing input format | Existing output format | Actual caller | Displayed? | Exportable? | Error handling | Verdict |
|---|---|---|---|---|---|---|---|
| 05 Customer Dashboard | `EnergySystemInputs` from coordinated forecasts; `OptimizationWeights` (cost/reliability/curtailment/battery wear). | `result` with `recommendation`, `candidates`, `objectives`; each candidate carries dispatch and audit. | `optimize_energy_system` (`run_orchestration.py:79`). This evaluates two explicit policies; it is not global hourly set-point optimization. | Policy comparison and snapshot (`05:284-368`). | Full report/operator JSON (`05:688-739`). | Weight validation errors and `OptimizationError` are `ValueError` subclasses → page handler. | Y for bounded policy optimization. |
| 06 Joint Optimizer | Forecast results, config, optimizer settings from manifest (`population_size`, `generations`, `seed`), availability. | `result` with candidates, recommendation, dispatch rows, robust economics, handoff. | `optimize_prediction_resource_schedule`; the wrapper calls `optimize_forecasted_resource_schedule`; the search is `optimize_battery_and_diesel_schedule` with warm start and repairs. | Candidate table, recommended policy, setpoint table/JSON (`06:304-357`, `490-527`). | Joint schedule audit JSON. | Expected validation errors caught; annual/integrity failures stop. | Y for the search; no independent optimizer result schema. |
| 09 Device Planner | Tasks, prices, residual budget. | `DeviceSchedule` with per-task operating steps, power, cost. | `schedule_device_tasks` (`run_orchestration.py:278`). This is a rule-based tariff scheduler, not an optimization search. | Per-device schedule and cost. | CSV/JSON. | `ValueError` only. | P: scheduling exists, but it is not an optimizer. |
| Workspace: Microgrid | Scenario and config; candidate RO requests. | Ranked candidates and `SearchResult` (best schedule, evaluations, convergence, passes). | `screen_renewable_surplus_candidates`, `search_ro_schedule` (`workspace.py:1235-1238`). | Ranked table, search metrics, selected schedule chart. | Candidate CSV and searched-schedule CSV. | `ValueError`/`TypeError` block; no per-run error object. | Y for a bounded coordinate search. |
| Workspace: Flexible-load | Scenario profile and optional tariff forecast. | `optimize_flexible_load` result: baseline/optimized cost, schedule, cost difference. | `workspace.py:31` import; actual call is in the flexible-load section, export at `workspace.py:648`. | Cost comparison and schedule. | CSV (`workspace.py:648-654`). | Upload errors stop; run errors use page handlers. | Y for its own LP chain; X from site forecast. |
| Workspace: Strategy simulator | Uploaded/synthetic RO CSV + config. | Five-policy comparison, then NSGA-II Pareto summaries/details. | `run_uploaded_strategy_comparison` at `workspace.py:743`; `optimize_dispatch` at `workspace.py:1043`. | Five-policy result and Pareto output. | CSVs at `workspace.py:888`, `990`, `998`, `1151`. | Broad `Exception` with `st.error`/`st.stop`. | Y within the section; no forecast and no annual economics. |

**Optimization gap:** there are at least four optimization/scheduling implementations: 05 bounded two-policy comparison, 06 seeded joint schedule search, 09 tariff heuristic, Workspace LP/NSGA-II/coordinate search. They share inputs and sometimes the simulator, but not a result contract. “OPTIMISATION” is therefore a family of methods, not one integrated module boundary.

### 5. ECONOMIC EVALUATION

| Path | Existing input format | Existing output format | Actual caller | Displayed? | Exportable? | Error handling | Verdict |
|---|---|---|---|---|---|---|---|
| 05 Customer Dashboard | 24 h result/economics + customer-entered baseline/proposed annual bills, incremental O&M, CAPEX, life, discount rate, escalation, replacement/residual. | `build_service_equivalent_economics` dict; `InvestmentEconomics` dataclass with annual cashflows, NPV, simple/discounted payback, break-even saving, sensitivity; `economics_binding` record. | `build_service_equivalent_economics` (`run_orchestration.py:80`); `evaluate_investment_economics` and `bind_annual_economics_to_run` in `05:433-538`. | Service-equivalent savings gate, investment metrics, annual cashflow table (`05:433-582`). | Report top-level `investment_economics` and `investment_economics_binding` (`05:714-715`). | Service gate withholds savings; annual binding integrity failure stops (`05:534-538`). | Y in the page; P in `application_views` and replay (see gaps). |
| 06 Joint Optimizer | 24 h recommendation summary/dispatch; optional `days_equivalent_per_year`; currency. | `robust_customer_economics`; `annual_record` (`AnnualOperatingBasis`); `annual_view` with figures/basis/hashes. | `build_run_result_summary`; `_robust_service_equivalent_economics`; `annualise_run_summary`/`build_annual_projection` at `06:364-452`. | 24 h cost-reduction metric; annual four metrics only when the checkbox is selected (`06:397-452`). | Annual block and report JSON only when selected; `application_views.annual` is null otherwise (`06:511-515`). | Annual verification failure stops (`06:418-424`); outer run handler catches expected errors. | P: derived economics exists but is optional, and the project does not replay it. |
| 09 Device Planner | Replay summary for the tariff-aware plan and earliest-feasible reference. | `device_flexibility_summary` with energy charge, estimated cost, savings vs reference, summary hash. | `build_device_flexibility_summary` (`09:210-215`). | Four metrics and comparison table (`09:100-179`). | CSV + application-view JSON. | No separate economics error path; schedule `ValueError` covers setup. | P: 24 h energy cost only; no annual/NPV/payback. |
| Workspace: Microgrid | Ranked candidate results. | Per-m³ whole-system operating cost and incremental cost vs no-RO. | Page arithmetic after `item.to_dict()` (`workspace.py:1250-1269`). | Customer economics table (`workspace.py:1425-1441`). | Candidate CSV (`workspace.py:1442-1448`). | No separate economics validation; division-by-zero returns `None`. | P: accounting indicators, not investment economics. |
| Workspace: Historical RO baseline | Historical RO CSV plus chemical/variable O&M/maintenance/start/fixed O&M rates. | `reconstruct_historical_ro_cost` report: total cost, cost/m³, water, energy, runtime, start events, breakdown. | `reconstruct_historical_ro_cost` at `workspace.py:1542-1549`. | Metrics and cost breakdown (`workspace.py:1560-1572`). | CSV (`workspace.py:1590-1596`). | `ValueError`/`TypeError`/`UnicodeDecodeError` (`workspace.py:1605`). | Y as a historical baseline; X from forecast/dispatch. |

**Economics gap:** there are four incompatible economic definitions: 05 customer-entered annual investment, 06 equal-day annual operating projection, 09 24 h energy cost, and microgrid per-m³ operating indicators. They cannot be compared without a service-boundary and period adapter. After the T7+ follow-up, `replay_run_request` returns the investment screen for the eight fields already carried by `run_settings.investment`; replacement year, replacement cost and residual value remain page-only because the v3 request does not carry them.

### 6. RESULTS

| Path | Existing input format | Existing output format | Actual caller | Displayed? | Exportable? | Error handling | Verdict |
|---|---|---|---|---|---|---|---|
| 05 Customer Dashboard | `result`, `economics`, `stress`, `paired_impact`, `investment`, `operator_record`; application views. | Metrics; policy/stress/impact tables; annual cashflow; two JSON downloads. | Page rendering and `report` assembly at `05:284-739`. | Yes, but the selected hourly dispatch is not charted; only the operator JSON contains it. | `islandos_customer_decision_report.json` and `islandos_operator_decision_record.json`; raw forecast points absent. | Report assembly failures caught by outer handler. | Y for full report; P for canonical non-Streamlit view because `application_views` is summary-only. |
| 06 Joint Optimizer | `planning_run`, `predictions`, `result`, `economics`, `annual`. | Metrics, candidate table, schedule table, annual metrics; one JSON audit. | `06:283-533`. | Yes; forecast point series is not rendered, only model quality. | `islandos_joint_resource_schedule.json`; annual conditional. | Annual verification stop; run handler. | Y, with conditional annual and no raw forecast export. |
| 09 Device Planner | `schedule`, `replay`, `reference_replay`, summary. | Metrics, per-device schedule, hourly chart, comparison; CSV + JSON. | `09:96-225`. | Yes. | CSV and application-view JSON. | Setup handler. | Y as an isolated result. |
| Workspace: Microgrid | Ranked/search/robustness frames. | Tables/charts; candidate, search, stress CSVs. | `workspace.py:1313-1448`. | Yes. | CSVs; no single run report or input hash. | Block handler. | P: results are visible, but not wrapped as one auditable result envelope. |

**Results gap:** the page-level report objects are richer than the shared `application_views`. 05’s `application_views` contains only a request and a result summary (`05:718-721`), while the page report contains stress, paired impact, investment, and the operator record. 06 includes an annual view only when selected. A non-Streamlit client using `POST /run` gets summaries, not the full page report.

## Integration gaps, ranked

### G1 (High) No single replayable end-to-end chain

**Status after T7+:** deferred by the Phase 1 boundary. A shared chain would require a new orchestration
that composes the three pages and changes the model composition; the branch is explicitly read-only
and does not change model assumptions. The three page chains remain separate and are not described as
one pipeline.

`run_customer_dashboard` (`run_orchestration.py:56-98`), `run_joint_optimizer` (`run_orchestration.py:102-136`), and `run_device_planner` (`run_orchestration.py:261-300`) are three different compositions. No shared `run_id` or manifest spans them. 09 has no forecast/optimizer stage at all. Workspace chains bypass `run_orchestration` entirely. Therefore “INPUT → FORECAST → SIMULATION → OPTIMISATION → ECONOMIC EVALUATION → RESULTS” describes a conceptual sequence, not one implemented pipeline.

### G2 (High) The replay contract promises annual evidence but returns `annual: None`

**Status after T7+:** the false promise is removed. `islandos_core/transport.py` now says annual
evidence is not replayed; `annual: None` is the stated contract, not an omission. Annual projection
remains a page/06 checkbox outcome and is not part of `POST /run`.

`islandos_core/transport.py:6` described `POST /run` as returning “its summary (+ annual)”. Yet `replay_run_request` returns `{"page": page, "result": summary, "annual": None}` for all three pages (`run_orchestration.py:335`, `361`, `383`). Existing transport tests assert this null behavior (`tests/test_application_transport.py:153-156`, `202-205`, `265-271`). This is not an integration of the annual stage; it is an explicit omission.

### G3 (High) 05 investment inputs are carried by the request but discarded on replay

**Status after T7+:** fixed for the eight fields carried by the v3 request. `replay_run_request` calls
the existing `evaluate_investment_economics` with the same service-equivalence gate and returns an
`investment` block; `tests/test_application_transport.py` checks it equals the page evaluator.
Replacement year, replacement cost and residual value are still page-only because they are not in the
v3 request.

`run_orchestration.py:320-335` only passed `cost_priority` and never called `evaluate_investment_economics` (`05:239-251`, `app_view_models.py:135-144`).

### G4 (High) 05 and 06 build different synthetic inputs for the same “demo site”

**Status after G4 fix:** fixed at the input layer. 05 now calls
`build_customer_site_history`, which starts from 06's `build_synthetic_site_history` at 40 kW PV /
20 kW wind and then applies 05's `demand_scale` and `tariff_scale`. At `1.0/1.0` the timestamp list and
four signal arrays are identical, and both pages print the same `Shared history SHA-256`. 05's pinned
24-hour cost moves from 17.93 to 24.52 USD (the old inline generator is gone); 06's `7,709.55 USD/year`
and `186,150 kWh` are unchanged. This is one input generator and one history hash, not a cross-page
execution chain.

05 no longer has its own 168 h loop. It uses the 06 builder plus the two customer scales; 06 uses the
builder directly. The two surfaces now have the same history hash at the nominal site, and an uploaded
CSV still goes through the one `parse_customer_history_csv` adapter.

### G5 (Medium) Forecast results are consumed but not fully exported

05 renders four 24 h forecast charts and model quality (`05:309-350`), but the report exports only model IDs (`05:705`). 06 renders only a model-quality table (`06:290-302`) and exports only model IDs/metrics (`06:499-503`). A reader cannot reconstruct the exact forecast series that drove the optimizer from the JSON. Forecast lab does export a forecast CSV (`workspace.py:1824`), but nothing consumes it.

### G6 (Medium) `SIMULATION` is not a first-class stage

05 and 06 have no `simulation` result block; the shared simulator is called inside the optimizer. 05 does not chart the selected hourly dispatch, although the operator JSON contains it (`05:608-627`). 06 shows candidate summaries and setpoints but not a separate per-scenario simulation table (`06:304-357`). 09 and microgrid expose replay/search results much more directly. The same word “simulation” therefore names different levels of evidence on different pages.

### G7 (Medium) 09 is an isolated product, not a continuation

09 starts from fixed constants, not from a site history (`09:36-82`); it has no forecast and no economic evaluation beyond 24 h energy charge. Its `build_device_flexibility_summary` result (`09:210-215`) is not the same shape as 05/06 `result`. Treating 09 as the “device stage” of the 05/06 chain would overstate integration.

### G8 (Medium) Multiple economic evaluators and no common result schema

05 uses `build_service_equivalent_economics` + `evaluate_investment_economics`; 06 uses robust service-equivalent economics + equal-day annualization; 09 uses a 24 h energy-cost summary; microgrid uses per-m³ arithmetic. There is no shared `EconomicResult` object, and no common rule for whether savings are withheld. 05’s annual figures are customer-entered and cite a run but are not derived from it (`05:455-538`); 06’s annual figures are derived from one simulated day and only when selected (`06:395-452`).

### G9 (Medium) Error handling is not uniform

- 05/06 catch `(ValueError, KeyError, TypeError)` at the page boundary and stop on integrity failures (`05:740`, `06:534`, `06:418-424`).
- 09 catches only `ValueError` (`09:92-94`); a `RuntimeError`/`KeyError` would escape to Streamlit’s default exception page.
- Microgrid catches `ValueError`/`TypeError` (`workspace.py:1246-1249`) but not `KeyError`.
- Forecast lab and Strategy simulator catch broad `Exception` (`workspace.py:752-754`, `1825-1828`), which prevents a traceback but also hides programming errors.
- `transport.py` maps `ValueError`/`KeyError`/`TypeError` to HTTP 400 (`transport.py:151-157`); other exceptions are not converted to a JSON error envelope.

Expected domain errors are generally surfaced, but there is no single error taxonomy or consistent “stale result cleared” rule.

### G10 (Low) Microgrid copy and provenance are inconsistent

The page warns “not measured site data, a forecast, a global optimizer” (`workspace.py:1176-1179`), then displays a “Baseline forecast used by the scheduler” from `forecast_microgrid_signals` (`workspace.py:1211`, `1275`). The forecast is real within the toy model; the warning is stale. Neither the candidate CSV nor the stress CSV carries the input controls or a scenario hash, so a downloaded file cannot be tied back to the exact synthetic scenario.

## Smallest existing interface or adapter recommendations

These recommendations deliberately reuse existing functions and objects. They are audit recommendations, not application-code changes.

| Priority | Gap | Smallest existing interface / adapter | Why it is minimal | Acceptance check |
|---|---|---|---|---|
| 1 | 05/06 synthetic input mismatch | `islandos_core.demo_site_history.build_synthetic_site_history` plus a thin wrapper that applies 05’s `demand_scale`/`tariff_scale` after generation; keep `parse_customer_history_csv` as the only CSV→`CustomerHistory` adapter. | No new generator or schema. One builder, one parser, one history hash. | Same demo date/hour and nominal site produce the same timestamp list and history SHA-256 on 05 and 06; a single provenance caption. |
| 2 | 05 investment is lost on replay | Reuse the existing `run_settings.investment` block and the existing `evaluate_investment_economics`; have `replay_run_request` call it and return the existing `InvestmentEconomics` dict under a new optional `investment` key. | The request already validates all eight investment fields; the evaluator already exists. No new endpoint or calculation. | A 05 request with investment inputs replays to the same NPV/payback/withheld state as the page report. |
| 3 | 06 annual is not replayable | Carry an optional `annual_days_equivalent_per_year` in the existing `run_settings` (or a versioned extension of it), and have `replay_run_request` call the existing `annualise_run_summary` + `build_annual_projection` when present. | Reuses the page’s existing annual functions and the existing annual view schema; the default remains “not projected.” | 06 page and replay produce the same `annual_view` for the same request, including basis and projection hashes. |
| 4 | Forecast lab is a dead end | Use the existing `islandos_core.prediction_dispatch_adapter.build_dispatch_forecast_bundle` to convert `PredictionResult` into the `ForecastBundle` consumed by `optimize_forecasted_resource_schedule`; pass the bundle through the existing `run_forecast_dispatch`/optimizer path. | The conversion adapter and optimizer wrapper already exist; no new model or forecast engine. | A Forecast lab result can be fed to the joint optimizer without re-forecasting, and the history hash is the same in both reports. |
| 5 | No common simulation result | Use the existing `dispatch_energy_system` return dict as the simulation payload; expose it as a `simulation` block in the existing page report rather than creating a new simulation module. | The simulator already returns rows, summary, and policy schedule; 09 and 05/06 already call it. | 05/06/09 reports contain the same core keys (`policy`, `time_steps`, `rows`, `summary`) for the same scenario. |
| 6 | `application_views` is narrower than the page report | Use the existing report object as the canonical full artifact; expose `application_views` as the summary view and add an optional `investment_economics` passthrough in the same report envelope. Do not create a second transport endpoint. | `investment_economics` already exists at `05:714`; `application_views` already exists at `05:718-721`. | A non-Streamlit reader can load the page report and see investment, stress, impact, and annual blocks with hashes, without recomputing them. |
| 7 | Forecast points are not exportable in 05/06 | Add the existing `ForecastBundle`/`predictions` points to the page report as a CSV/JSON artifact; no new calculation. | The points already exist in the run outputs; this is serialization only. | Report JSON or accompanying CSV contains all 24 points per signal, with timestamp, prediction, lower/upper bound, model, and history hash. |
| 8 | 09 is not part of the site chain | Keep 09 as an explicit isolated surface, or adapt it through the existing `run_device_planner` + `build_device_flexibility_summary` interfaces only. Do not claim it covers forecast/optimization/economics. | Avoids inventing a cross-product pipeline that the device model does not support. | Product documentation labels 09 “device replay demo,” not “stage of the customer decision chain.” |
| 9 | Uneven error handling | Normalize expected validation failures to the existing `ValueError` family (`OptimizationError`, `EnergyModelError`) and catch the same set at page and replay boundaries; add `KeyError` to the microgrid boundary. | No new exception hierarchy; the subclasses already exist. | Every expected bad input produces a user-readable message and a 4xx JSON error on `/run`; unexpected programming errors are not silently swallowed. |

## What is actually integrated, in one sentence per chain

- **05:** a real CSV/synthetic → forecast → coordinated inputs → bounded two-policy optimization → service-equivalent economics + stress/paired replay → report/operator JSON chain. It is the strongest customer decision chain; its eight-field annual investment screen is replayable, while replacement year, replacement cost and residual value remain page-only.
- **06:** a real CSV/synthetic → manifest-bound forecast → seeded joint schedule search → robust 24 h economics → optional equal-day annual projection → JSON audit chain. It is the strongest forecast-to-schedule chain, but annual is checkbox-conditional and `replay_run_request` returns `annual: null`.
- **09:** a fixed synthetic input → device schedule → shared-simulator replay + reference → 24 h cost summary → CSV/JSON chain. It is fully visible but intentionally isolated; it has no forecast, no real optimizer, and no annual economics.
- **Workspace Microgrid:** a synthetic 168 h scenario → seasonal-naive forecast → ranked candidates + coordinate search + robustness → per-m³ indicators → CSV chain. It touches all six stages, but it is a toy screening surface without a run manifest or input hash.
- **Workspace Forecast lab:** a real CSV/synthetic → `PredictionEngine` forecast → chart + CSV. It is a terminal branch, not an input to 05/06.
- **Workspace Strategy simulator / Flexible-load / Historical baseline / Rolling Horizon:** additional partial chains. They prove the underlying modules work, but they do not create one integrated pipeline.

## Evidence index

Primary call sites and exports used for this audit:

- `app.py:68-117` — registered surfaces.
- `pages/05_Customer_Decision_Dashboard.py:161-193` — input parsing/synthetic generation; `258-273` — `run_customer_dashboard`; `309-350` — forecast display; `352-431` — policy/stress/impact; `433-538` — investment/binding; `688-739` — report and downloads; `740-742` — page error boundary.
- `pages/06_Forecast_Led_Joint_Resource_Optimizer.py:148-164` — signal history; `243-282` — manifest and `run_joint_optimizer`; `290-302` — forecast model table; `304-357` — candidates/schedule; `364-452` — annual projection; `490-533` — report/download; `534-536` — error boundary.
- `pages/09_Device_Flexibility_Planner.py:36-94` — fixed inputs and `run_device_planner`; `96-179` — schedule/replay display; `203-225` — CSV/JSON exports and summary view.
- `islandos_ui/workspace.py:1180-1249` — microgrid controls/forecast/simulation; `1275-1448` — forecast, ranking, search, stress, economics and CSV exports; `1757-1828` — Forecast lab; `1616-1708` — onboarding/handoff.
- `islandos_core/run_orchestration.py:56-98` — 05 composition; `102-136` — 06 composition; `261-300` — 09 composition; `303-388` — replay and its `annual: None` returns.
- `islandos_core/app_view_models.py:69-106` — result/annual field lists; `130-146` — per-page settings and investment keys; `344-430` — `build_run_request` validation.
- `islandos_core/transport.py:5-13` — `POST /run` contract claim; `126-157` — replay/error handling.
- `islandos_core/contract_schemas.py:201-211`, `519-524` — result and annual contracts.
- `islandos_core/prediction_dispatch_adapter.py:25-31` — `build_dispatch_forecast_bundle`, the existing forecast-result adapter.
- `islandos_core/planning_workflow.py:40-166` — manifest-bound forecast→dispatch workflow.
- `optimization/energy_system_optimizer.py:136-152` — 05 two-policy optimizer; `657-689` — 06 joint schedule search.
- `islandos_core/schedule_evaluator.py:201-303` — microgrid robustness and stress scenarios.
- `pages/2_Rolling_Horizon_Lab.py:116-197` — four-policy simulation and export.

No application code was modified; this document is the only file added on `audit/module-integration`.
