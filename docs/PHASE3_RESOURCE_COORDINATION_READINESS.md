# Phase 3 — Device and energy-resource coordination readiness

## Purpose

Phase 3 turns forecasts and a verified equipment inventory into an auditable operating plan. Its customer-facing question is:

> Given the equipment actually installed, its confirmed operating limits, energy prices, resource availability, and service priorities, which feasible operating schedule offers the best cost–reliability trade-off?

This is offline decision support. A recommendation is not an equipment command, safety approval, or proof of customer savings.

## Existing reusable foundation in this branch

The current product-foundation branch already contains most of the generic building blocks needed for this phase. Avoid rebuilding these as parallel subsystems.

| Layer | Existing implementation | What it contributes |
|---|---|---|
| Equipment registry | \`islandos_core/assets.py\` | Versioned PV, wind, battery, diesel, grid and flexible-load records; separates vendor ratings from installed configuration; parameter provenance |
| Constraint governance | \`islandos_core/assets.py\`, \`docs/ASSET_CONSTRAINT_REGISTRY.md\` | Hard, operational and soft limits; confirmation and source references; fail-closed readiness checks |
| Site structure | \`islandos_core/electrical_topology.py\` | Buses, branches and confirmed asset-port connectivity metadata |
| Availability and state | \`islandos_core/operational_state.py\` | Timestamped operating observations; explicit grid/diesel availability; ambiguous newest state blocks screening |
| Asset conversion | \`islandos_core/asset_energy_adapter.py\` | Converts confirmed installed parameters and constraints into physical-model configuration |
| Physical accounting | \`islandos_core/energy_system.py\`, \`islandos_core/energy_balance.py\` | Shared timestep energy balance across renewable generation, load, battery, grid, diesel and curtailment |
| Coordination search | \`optimization/energy_system_optimizer.py\` | Policy comparison and seeded schedule search for battery power, diesel commitment/output, flexible load and export caps |
| Reproducibility | \`islandos_core/workspace_store.py\`, \`islandos_core/application.py\` | Run manifests, source/configuration hashes and append-only audit history |

The optimizer currently exposes separate entry points for battery, diesel, flexible-load and joint schedules, plus a common-schedule multi-scenario replay report. It is a bounded heuristic over the implemented decision variables, not a guaranteed global optimum.

## Required end-to-end flow

1. **Register assets:** capture asset type, rated and installed capacity, units, source references and confirmation state.
2. **Validate operating envelope:** require confirmed hard limits and reject contradictory or incomplete configurations.
3. **Resolve current availability:** use timestamp-aligned grid, diesel and asset-state inputs. Missing critical availability must not be assumed available.
4. **Prepare forecasts and prices:** align every input to the same UTC horizon and cadence; retain units, model identity and source-history provenance.
5. **Build physical configuration:** convert only validated asset records and confirmed constraints into the shared energy model.
6. **Generate candidate schedules:** coordinate the resources supported by the selected optimizer entry point.
7. **Simulate and audit:** run every candidate through the same physical dispatch engine; reject energy-balance failures and report service shortfalls separately.
8. **Compare customer outcomes:** show baseline versus recommendation for estimated energy cost, critical unmet energy, flexible-load shedding, renewable curtailment, fuel use, battery throughput/wear proxy and relevant export revenue.
9. **Preserve evidence:** store input hashes, assumptions, model/software versions, optimization seed, objective weights, selected schedule and human-review status.

## Important integration seam with the current Phase 2 forecast PR

There are currently two forecast-facing data shapes in active development:

- The Phase 2 PR #200 API returns \`ForecastBundle\` / \`ForecastPoint\` objects and carries an input-history SHA-256 digest.
- This branch's optimizer adapter currently accepts \`SignalForecastResult\` objects from \`islandos_core/multisignal_forecasting.py\`.

These are not interchangeable types. Before connecting the new Phase 2 engine to this optimizer, add one explicit, tested adapter at the boundary. It must validate signal identity, units, identical UTC target timestamps, cadence, finite values and provenance. It must not silently rename signals, convert units, or infer grid/diesel availability from forecasts. Tariff and availability series remain separately declared planning inputs.

Do not solve this by maintaining two competing forecasting engines or by copying forecast code into the optimizer.

## Known gaps to close before calling Phase 3 complete

### 1. Constraint coverage must match the optimizer decision variables

The current joint optimizer explicitly rejects diesel ramp-down search and minimum up/down-time search where those constraints are not implemented. Keep these constraints unavailable in the optimizer readiness gate until a correct formulation and regression suite exist. Never accept a hard constraint and then silently ignore it.

### 2. Physical model scope must remain explicit

The energy balance is not an electrical power-flow solver. The topology records declared connectivity but does not calculate voltage, frequency, fault current, protection coordination, thermal loading or transient stability. Do not present topology validation as electrical safety validation.

### 3. Robustness is not yet probabilistic optimization

The multi-scenario evaluator replays one common schedule against caller-supplied scenarios and reports worst-case and mean outcomes. It does not assign scenario probabilities, optimize a stochastic policy, or guarantee robustness outside the supplied cases.

### 4. Customer economics need comparable denominators

Every baseline and candidate must deliver the same declared service requirement or report the difference explicitly. Separate energy charges, fuel expenditure, variable O&M, battery wear proxy and any demand/export terms. Do not describe a lower cost accompanied by more unmet critical load as an unconditional saving.

### 5. Operational authorization remains outside the product

No output from this phase authorizes device writes. Real operation requires qualified site review, validated interconnection and protection studies, cyber/security review, and a separately approved control integration.

## Phase 3 exit gates

Phase 3 is ready for a stable product increment only when all of the following are demonstrated on the exact reviewed commit:

- [ ] Every supported asset type has a versioned schema, explicit units and provenance rules.
- [ ] Missing, unconfirmed or contradictory hard limits fail closed.
- [ ] Asset availability and all forecast/price inputs share a validated UTC planning horizon.
- [ ] The Phase 2 forecast output reaches the physical model through one tested adapter; no duplicate forecast implementation remains.
- [ ] Every optimizer decision variable is bounded by the corresponding implemented physical constraints.
- [ ] Unsupported hard constraints are rejected before optimization, not ignored.
- [ ] Candidate schedules pass independent energy-balance and accounting invariants.
- [ ] Critical service, flexible service and their shortfalls are reported separately.
- [ ] Baseline and recommendation comparisons use equivalent service and expose all modeled cost components.
- [ ] Seeded synthetic regression cases cover normal operation, grid outage, renewable shortfall, fuel scarcity, battery reserve and infeasible critical service.
- [ ] Public-data or site-data evaluation is labelled accurately; synthetic tests are not presented as field evidence.
- [ ] Full CI passes on the exact commit and the limitations above remain visible in user-facing documentation.

## Recommended sequence

1. Reconcile the Phase 2 \`ForecastBundle\` contract with the optimizer's existing forecast adapter.
2. Build a single reusable planning-input object containing forecasts, tariffs, availability and provenance.
3. Add readiness checks that map every configured hard constraint to a supported optimizer decision variable.
4. Close the diesel ramp and commitment-constraint gaps only if required by the target customer use case; otherwise reject those configurations explicitly.
5. Add fair baseline-versus-recommendation economics and stress-case reports.
6. Complete CI and independent review before treating this phase as stable.

The priority is a trustworthy, economically interpretable schedule—not adding more optimizer algorithms for their own sake.
