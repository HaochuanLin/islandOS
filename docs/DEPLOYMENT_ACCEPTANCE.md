# Deployment acceptance and pilot-readiness template

Status: **planning template only**. This document does not authorize deployment, establish a site-specific business case, or qualify IslandOS for closed-loop control. A site owner and qualified engineering/safety reviewers must complete and approve the blank acceptance criteria before any field trial.

## 1. Intended deployment boundary

The current application is a research and planning prototype. It may support offline analysis and, after a separate site review, shadow-mode evaluation. It is not a PLC/SCADA interface, does not issue actuator commands, and is not safety-certified.

- Keep the demo bound to loopback unless an approved deployment architecture adds authentication, authorization, TLS, network segmentation, logging, and an explicit data-retention policy.
- Do not upload confidential or critical-infrastructure data until the data owner approves access, processing, retention, and incident handling.
- Pin the exact Git commit and runtime environment for every shared result.
- Treat data adapters and forecast plug-ins as trusted code; do not install or import third-party plug-ins without code review.
- Keep operator authorization, independent interlocks, plant protection systems, and emergency procedures outside the model.

## 2. Economic model: inputs, equations, and limitations

Use site-approved inputs and record their units, source, date, and uncertainty. Do not fill missing inputs with guessed values.

### Required inputs

| Input | Unit | Source / owner |
|---|---|---|
| Delivered water and unmet demand | m³ per hour/day | Metered flow and demand definition |
| RO specific energy consumption | kWh/m³ | Vendor curve or site measurement at stated salinity, temperature, and recovery |
| Energy by source | kWh, separated into renewable surplus, grid, and backup/diesel | Meter/dispatch record and tariff/fuel data |
| Grid tariff and demand charges | currency/kWh and currency/month | Applicable utility tariff |
| Backup variable cost | currency/kWh or currency/fuel unit | Site fuel and maintenance records |
| CAPEX, lifetime, discount rate | currency, years, fraction/year | Vendor quotation and finance owner |
| Fixed and variable O&M, consumables, membrane replacement | currency/year and currency/m³ | Vendor/site records |
| Availability, utilization, downtime | fraction or hours/year | Site history or explicitly labeled scenario |
| Baseline water cost and service level | currency/m³ and unmet m³ | Existing supply chain and owner-defined service requirement |

### Transparent screening equations

For each scenario and strategy, calculate annualized costs using a declared time basis:

- Annualized capital cost: CAPEX × CRF, where CRF = r(1+r)^n / ((1+r)^n − 1) for discount rate r > 0 and lifetime n; when r = 0, CRF = 1/n.
- Energy cost: sum over sources of energy_kWh[source] × marginal_cost_per_kWh[source]. Set the opportunity cost of otherwise-curtailed renewable energy explicitly; do not silently assume it is zero.
- Total annual cost: annualized capital + fixed O&M + energy + consumables + variable O&M + other included costs.
- Levelized delivered-water cost: total annual cost divided by **delivered** water volume over the same annual period, not nominal RO production capacity.
- Incremental value: baseline cost avoided minus incremental project cost, while reporting unmet demand and reliability separately. Never hide water shortfall inside a single monetary score.

These are accounting definitions, not a claim that IslandOS already estimates every cost item. State which values are measured, quoted, assumed, excluded, or unavailable. Avoid double-counting electricity already included in a vendor water-cost quote.

### Sensitivity analysis

At minimum, rerun a low/reference/high case for:
1. electricity tariff and renewable-curtailment opportunity cost;
2. RO specific energy consumption;
3. annual utilization / downtime;
4. CAPEX and financing rate;
5. consumables and maintenance;
6. delivered-water demand and unmet-service penalty, if the site owner can defend a monetary value.

Use site-approved bounds rather than arbitrary universal ranges. Report the break-even values, scenario table, and one-at-a-time sensitivity ranking; add joint scenarios where inputs are correlated. Do not present probabilistic confidence intervals unless distributions and their evidence are documented.

## 3. Pilot stages and stop conditions

| Stage | Required evidence | Exit / stop rule |
|---|---|---|
| 0. Data governance | Owner, license/permission, data dictionary, units, time zone, retention, access controls | Stop if data rights or data handling are unresolved |
| 1. Retrospective baseline | Missingness/quality report, timestamp alignment, measured baseline, naive strategy baseline, chronological holdout | Stop if baseline or input provenance cannot be reproduced |
| 2. Offline scenario review | Feasibility constraints, water-service metrics, energy-source accounting, sensitivity analysis, model limitations | Stop if results are not reproducible or critical constraints are violated |
| 3. Shadow mode | Time-synchronized read-only data, independent comparison with operators/plant logs, drift and alert review | Stop on unsafe recommendation, unexplained data drift, or failed data feed; no commands to equipment |
| 4. Supervised trial (separate authorization) | Written site risk assessment, independent interlocks, operator approval, rollback plan, emergency contacts, acceptance signatures | No trial until the site owner and qualified safety/engineering authority approve it |

## 4. Site acceptance criteria — must be filled in by the site owner

Do not substitute generic thresholds for site requirements.

- Required delivered-water service and allowable unmet demand: **TBD / owner approval required**
- Minimum essential-electricity reserve and prohibited operating states: **TBD / electrical engineer approval required**
- RO operating envelope, water quality, salinity/recovery limits, and equipment protection: **TBD / vendor and process engineer approval required**
- Data completeness, timestamp skew, sensor plausibility, and feed-loss behavior: **TBD / instrument owner approval required**
- Economic hurdle rate, currency/base year, cost boundary, and sensitivity ranges: **TBD / finance owner approval required**
- Shadow-mode duration and comparison method: **TBD / operations owner approval required**
- Stop-work authority, incident notification, and rollback criteria: **TBD / site safety authority approval required**

A missing or unsigned criterion is a **no-go**, not an implicit pass.

## 5. Evidence bundle for each reviewed run

Retain together: Git SHA, runtime lock/version, source-data provenance and hash, schema/unit/time-zone audit, configuration, model and policy identifiers, assumptions/exclusions, exported CSV/JSON reports, logs, sensitivity inputs/results, reviewer, and decision record. Synthetic runs may test software behavior but must not be used as measured site evidence.

## 6. Current readiness decision

- Repeatable local research-demo deployment: documented in docs/DEMO_DEPLOYMENT.md and guarded by deployment-contract tests.
- Production security review, authenticated multi-user deployment, site-specific economics, owner-approved acceptance thresholds, and field/pilot authorization: **not established**.
- Decision: **offline research/demo only; no operational control authorization**.
