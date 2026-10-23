# Supervised site-pilot acceptance plan

Status: **planning template only — not an approved site procedure**.

This plan defines evidence gates for a future read-only, shadow-mode island pilot. It does not authorize physical control, commissioning, procurement, or bypassing local safety procedures. Site operators and qualified electrical/water engineers must approve site-specific thresholds before any pilot begins.

## 1. Non-negotiable operating boundary

- Start in retrospective analysis, then read-only shadow mode. Do not send actuator, PLC, pump, RO, battery, generator, or valve commands from this prototype.
- Preserve operator authority and existing protection/interlock systems. A model recommendation never overrides a site safety procedure.
- Fail closed on missing, stale, unauthenticated, out-of-range, or unit-ambiguous telemetry. Do not silently impute missing measurements.
- Keep the public demo, synthetic examples, public research datasets, and site measurements explicitly separated.
- The current simulator assumes simplified dynamics and perfect foresight in some dispatch decisions; RO membrane flushing, forecast error, hardware interlocks, and several backup-generation details are not fully modeled.

## 2. Required site data package

Before a retrospective result can be called site-specific, assemble a versioned manifest containing:

- At least one full seasonal cycle of hourly data (preferably 12 consecutive months) for renewable generation, critical electrical load, water demand, cooling demand where relevant, storage inventories, RO state/power/production, and backup energy.
- UTC-normalized timestamps, source timezone, interval convention, units, sensor IDs, calibration dates, quality flags, and data-owner contact.
- A source/permission statement, raw-file SHA-256 hashes, extraction timestamp, schema version, and a record of every exclusion or correction.
- Coverage and missingness by field, duplicate timestamp counts, invalid/non-finite values, outliers, time gaps, and known outages. No interpolation in the acceptance dataset unless a separately approved method is evaluated and reported.
- Site-approved engineering parameters: RO specific energy and flow, minimum run/stop constraints, flushing requirements, reservoir capacity/dead storage, storage efficiency, and protection limits. Unknown parameters remain unknown; do not substitute generic values without labeling them.

## 3. Validation sequence

### Gate A — data and model readiness

1. Validate schema, units, time alignment, freshness, non-negative/finite values, and reservoir/equipment bounds.
2. Reproduce water and energy balances from raw measurements within tolerances approved by the site engineer.
3. Compare forecasts with persistence and seasonal-naive baselines using chronological walk-forward splits; report MAE, RMSE, bias, interval coverage, and high-demand underforecast rate.
4. Test peak and stress periods separately: tourism peaks, dry periods, low-renewable periods, sensor gaps, high reservoir level, and low storage.
5. Run seeded randomized physical-invariant tests and publish exact commit/config/data hashes.

### Gate B — read-only shadow mode

- Minimum duration: 30 consecutive days, extended if the period does not include meaningful high-demand and low-renewable conditions.
- Availability target: at least 95% valid observations for every field required by the recommendation; any gap that invalidates a decision must suppress that recommendation.
- Generate recommendations on a fixed schedule, record the forecast vintage and all inputs, and compare them with actual operator actions and measured outcomes.
- No automatic actuation. Operators may ignore recommendations without penalty; record reason codes and incidents.
- Review daily during the first week and at least weekly thereafter with the site operator and engineering owners.

### Gate C — decision review

Proceed only if the site owner, water/RO engineer, electrical engineer, data steward, and cybersecurity reviewer sign the evidence package. A later advisory trial or any physical-control proposal requires a separate risk assessment, commissioning plan, and explicit authorization outside this repository.

## 4. Proposed metrics and provisional thresholds

The values below are **starting proposals for stakeholder review**, not approved acceptance criteria. Replace them with signed site-specific thresholds before Gate B.

| Measure | Proposed starting gate | Required reporting |
|---|---|---|
| Required-field data coverage | ≥95% over the shadow period | Per-field coverage and all excluded intervals |
| Water/energy balance | Within site-engineer-approved meter and model tolerances | Hourly residuals, cumulative residuals, worst cases |
| Forecast performance | Compare with persistence and seasonal-naive baselines on ≥4 chronological folds; do not accept a model that is materially worse without an approved reason | MAE, RMSE, bias, interval coverage, per-season results |
| High-demand risk | Set an operator-approved limit on high-demand underforecast rate and deficit magnitude; report the 90th/95th-percentile demand subset separately | Sample count, threshold derived from training data only, underforecast rate, worst shortfall |
| Dispatch constraints | Zero unreviewed hard-constraint violations in accepted scenarios | Every violation, emergency stop, unmet water/cooling, storage bound, backup use |
| Operational usefulness | Operator review of recommendation quality and reason codes; target ≥4/5 only if the site team adopts this scale | Signed feedback, ignored recommendations, reason codes |
| Economic robustness | Show results under at least ±20% changes to major documented cost assumptions | Currency, quote/source, lifetime, discount rate, cost range, break-even conditions |

The public SOWEKI example on 2026-10-23 improved overall seasonal-naive MAE versus persistence but had an approximately 83.5% underforecast rate in the selected high-demand subset. This is a warning that average error alone is insufficient; site-specific peak-risk criteria must be approved before use.

## 5. Immediate stop / no-go conditions

- Missing, stale, unauthenticated, or unit-ambiguous data affect a required decision input.
- Critical electrical load is short, water storage violates an approved bound, or the model reports an unreviewed hard-constraint violation.
- Measured water/energy balance residuals exceed the approved tolerance or sensor calibration status is unknown.
- The recommendation relies on perfect foresight, an unvalidated forecast, or a parameter with no approved source.
- A cybersecurity, privacy, or access-control incident occurs, or the system attempts any unauthorized physical write.
- The operator cannot explain the recommendation or cannot safely return to the existing operating procedure.

On a no-go, stop issuing recommendations, preserve logs and raw evidence, notify the named site owner, and resume only after documented review. Never conceal a failure by dropping the period without recording it.

## 6. Evidence packet and sign-off

Each gate review must archive:

- Exact repository commit and workflow run IDs.
- Data manifest, raw-file hashes, schema/config versions, timezone/unit map, quality report, and exclusions.
- Reproducible commands, environment/dependency lock, model assumptions, random seeds, and output hashes.
- Baseline and model metrics, high-demand/stress-case results, balance residuals, constraint violations, and sensitivity outputs.
- Operator feedback, incident/stop logs, unresolved risks, and the decision with named approvers and date.

### Required sign-offs before any site pilot

- Site owner / operations lead: ____________________ Date: __________
- Electrical engineer: _____________________________ Date: __________
- Water / RO engineer: ____________________________ Date: __________
- Data steward: ___________________________________ Date: __________
- Cybersecurity reviewer: _________________________ Date: __________
- Independent reviewer (if required): ______________ Date: __________

Until real site measurements and a supervised shadow-mode evidence packet exist, the real-world operational-validation score must not be increased. Public datasets and synthetic tests are useful engineering evidence but are not substitutes for island field validation.