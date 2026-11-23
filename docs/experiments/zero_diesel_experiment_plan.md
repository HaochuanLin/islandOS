# Zero-Diesel Microgrid Experiment Plan

Status: design specification; no performance results or customer claims.

## 1. Research objective

Determine whether IslandOS can operate an isolated hybrid microgrid with the diesel generator reserved for emergency backup, and quantify the operational and economic trade-offs between:

- Track A — existing assets only (incremental CAPEX = 0).
- Track B — optimized investment in additional renewable generation, battery energy/power, and flexible resource capacity.

The target is not to disable or remove the diesel generator. The target is to minimize routine diesel generation while preserving critical-load reliability, water-service requirements, equipment limits, and an explicitly modelled emergency reserve.

All initial experiments must be labelled synthetic unless validated site data are supplied.

## 2. Critical definitions

Report these separately; do not collapse them into one "zero diesel" claim.

- Routine diesel: diesel energy/fuel used during normal operation.
- Emergency diesel: diesel used only after a declared contingency/emergency trigger.
- Diesel-free hours: hours with zero diesel output.
- Zero-routine-diesel case: no diesel used in the normal chronological simulation, while the generator remains available for emergency events.
- Zero-annual-diesel case: no diesel used in either normal operation or the tested emergency events. This is a stronger claim and must be explicitly evidenced.

A system is not considered reliable merely because the optimizer finds a zero-diesel schedule. It must also meet critical electrical demand, water demand/service constraints, battery SOC limits, ramp/power limits, and terminal/cyclic state requirements.

## 3. Common benchmark system

Use one common synthetic site definition for both tracks. Keep load, weather, demand, initial states, time resolution, and random seeds paired across all strategy comparisons.

Required inputs:
- Chronological hourly (or finer, where supported) PV and wind availability.
- Critical and deferrable electrical loads, with an explicit critical-load classification.
- Water demand, RO power/production limits, tank capacity and initial/terminal inventory.
- Existing PV/wind nameplate ratings.
- Battery usable energy, charge/discharge power, efficiencies, SOC bounds, degradation assumptions where supported.
- Diesel rated/minimum stable power, start/ramp/min-up/min-down constraints where supported, and a documented fuel curve.
- Component availability/outage assumptions and emergency event definitions.
- Equipment CAPEX, replacement cost, lifetime, O&M, fuel price and delivery cost assumptions, all source-labelled or clearly marked synthetic.

Do not choose the final numeric site parameters to force a desired savings result. First freeze a transparent reference site and publish its parameter manifest.

## 4. Track A — existing assets only

Hold PV, wind, battery power/energy, RO, tank, and all other hardware fixed. Incremental CAPEX is zero.

Compare at least:
1. Existing/fixed operating schedule.
2. Renewable-surplus rule.
3. Forecast-based heuristic.
4. IslandOS coordinated optimization.

The optimizer may coordinate:
- Battery charge/discharge and reserve SOC.
- Deferrable loads.
- RO production and water-tank inventory.
- Forecast-based pre-positioning for low-renewable periods.
- Diesel commitment as an emergency-only fallback, subject to reliability constraints.

Questions:
- What fraction of routine diesel can be removed using software and dispatch alone?
- Can the existing asset mix achieve zero routine diesel over the full representative year?
- Which hours/events still require emergency diesel, and why?
- Is the result robust to forecast error and low-renewable weather sequences?

## 5. Track B — investment-enabled design

Allow new capacity, but do not assume all technologies are automatically economic.

Candidate decision variables:
- Additional PV capacity (kW).
- Additional wind capacity (kW), only where resource assumptions justify it.
- Battery energy capacity (kWh).
- Battery charge/discharge power (kW).
- Optional additional flexible water storage (m3), if water storage is a valid and safe flexibility resource.

Compare:
1. Minimum-cost design meeting a stated reliability target.
2. Minimum-cost design targeting zero routine diesel.
3. Pareto alternatives trading CAPEX, lifecycle cost, routine diesel, emergency diesel, and reliability.

Include annualized CAPEX or discounted lifecycle cost, fixed/variable O&M, battery replacement/degradation, fuel and fuel logistics. Report assumptions and sensitivity ranges. Do not recommend an investment solely because it reduces diesel litres.

## 6. Reliability and stress testing

A short 7-day run is a debugging test, not evidence for zero-diesel feasibility.

Use staged evaluation:
- Smoke test: 1 seed, 1–2 days.
- Development test: paired 7-day scenarios.
- Seasonal/annual test: chronological 8,760-hour year, with defensible weather/load data or explicitly synthetic profiles.
- Robustness: multiple weather years/seeds, forecast-error cases, component outages, and prolonged low-solar/low-wind events.
- Emergency test: trigger diesel only when predeclared reserve/critical-load conditions require it.

Use terminal/cyclic battery SOC and water inventory constraints, or explicitly account for the value of ending inventory. Prevent the optimizer from borrowing initial battery energy or water inventory to create artificial savings.

Report:
- Routine diesel litres and kWh.
- Emergency diesel litres, kWh, starts and operating hours.
- Diesel-free hours and longest continuous diesel-free period.
- Critical-load unserved energy and loss-of-load hours.
- Renewable curtailment and renewable share.
- Battery throughput, SOC extrema, equivalent full cycles and degradation cost (where modelled).
- Water delivered, unmet water demand, and ending tank inventory.
- Total annual operating cost and lifecycle cost.

Reliability metrics must be visible beside diesel metrics. A low diesel number with unserved critical load is a failed result.

## 7. Fair comparison protocol

- Same chronological inputs and initial conditions for every strategy.
- Same equipment limits and service requirements within each track.
- Paired random seeds and preserved input hashes.
- No dropping failed seeds; report failures and their causes.
- Report both aggregate totals and per-seed distributions.
- Separate measured/public inputs from synthetic assumptions.
- Keep Track A and Track B results distinct.
- Compare IslandOS against the strongest simple baseline, not only a weak fixed schedule.
- Preserve complete manifests, per-seed outputs, and reproducible run commands.

## 8. Model capability audit before implementation

Inspect the current code before adding new optimization variables. Verify whether it already supports:
- Battery charge/discharge power, SOC bounds, efficiencies, terminal SOC and cyclic operation.
- Diesel commitment, minimum stable output, start/stop, ramp and fuel-curve constraints.
- RO production and tank inventory with terminal/cyclic conditions.
- Renewable curtailment and explicit critical/deferrable load separation.
- Capacity expansion variables and CAPEX/lifecycle objective terms.

Anything not supported must be listed as a model gap. Do not imply that a feature is implemented merely because it appears in this plan.

## 9. Proposed implementation sequence

1. Freeze the common reference-site assumptions and data provenance.
2. Audit current energy-balance and MILP capabilities; add unit tests for any gaps.
3. Establish a validated no-investment benchmark with reliability constraints.
4. Add zero-routine-diesel target and emergency-only diesel logic.
5. Run annual chronological Track A experiments.
6. Add investment sizing and lifecycle economics for Track B.
7. Run weather, forecast-error, outage and sensitivity stress tests.
8. Publish a comparison report with limitations and no unsupported savings claims.

## 10. Decision rule

IslandOS should recommend the lowest-lifecycle-cost design that satisfies the declared critical-load and water-service reliability target, while minimizing routine diesel. If zero routine diesel is infeasible or uneconomic, report the minimum achievable routine diesel and the binding physical constraints rather than forcing a zero result.

No numeric diesel-saving, zero-diesel, payback, or investment claim is valid until the relevant experiments complete and their assumptions, outputs, and reliability results are reviewed.


## 11. Verified current-code capability audit (2026-11-23)

Inspected `optimization/milp_dispatch_optimizer.py` and `islandos_core/energy_system.py` on `main` before proposing implementation. Current verified constraints:

- The MILP reference solver is capped at 168 timesteps; it cannot yet run an 8,760-hour annual optimization in one solve.
- It supports a minimum terminal battery SOC, battery charge/discharge power and efficiency constraints, but explicitly rejects battery configurations using cycle-life capacity-fade settings.
- It supports one aggregate flexible load with a fixed energy budget and availability window. It explicitly rejects inputs that distinguish critical and flexible load series.
- It supports joint RO production and water-tank inventory constraints, including a terminal water inventory minimum.
- The energy-system model can represent a piecewise-linear diesel fuel-rate curve, but the MILP solver explicitly rejects nonlinear diesel fuel curves. The existing diesel sweep therefore uses the simplified constant L/kWh assumption.
- The inspected MILP does not include investment/capacity-expansion decision variables or CAPEX/lifecycle-cost optimization.
- The inspected MILP does not yet implement a distinct emergency-only diesel policy/state machine; diesel is a dispatchable balancing resource subject to availability and generator constraints.

Implementation consequence: do not start the annual zero-diesel or investment optimization by simply extending the current 168-hour sweep. First modularize/validate the dispatch formulation for rolling-horizon or annual operation, add explicit critical-load and emergency-reserve semantics, and introduce capacity planning/lifecycle economics as a separate layer. Keep annual chronological simulation and investment optimization distinct if a single monolithic MILP is computationally inappropriate.
