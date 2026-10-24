# Site pilot acceptance template

Status: **TEMPLATE ONLY — NOT APPROVED FOR A SITE OR LIVE OPERATION**

This document is a fill-in planning artifact. It is not a safety case, procurement recommendation, deployment authorization, or permission to connect IslandOS to PLCs, actuators, or operational control paths. Do not start a pilot while required fields or approvals are blank.

## 1. Pilot identity and scope

- Pilot name / ID: `[fill in]`
- Site and system owner: `[fill in]`
- Accountable project owner: `[fill in]`
- Planned start / end dates and time zone: `[fill in]`
- IslandOS repository commit SHA and release artifact: `[fill in]`
- Deployment mode: `[offline analysis / local demo / read-only shadow only]`
- Included assets and decisions: `[fill in]`
- Explicit exclusions: live control, actuator commands, protection/interlock changes, and any unapproved use of critical or personal data.
- Intended decision this pilot can inform: `[fill in]`

## 2. Data permission, provenance, and quality

For every input, complete one row before evaluation.

| Signal / file | Source owner and permission | Source type | Units | Time zone / interval | Coverage and gaps | SHA-256 / retrieval date |
|---|---|---|---|---|---|---|
| `[name]` | `[owner, license or approval]` | `[measured / public / synthetic / forecast / manual]` | `[unit]` | `[zone, minutes]` | `[range, missingness]` | `[hash, date]` |

- Confirm data rights, retention, deletion, and access controls with the data owner.
- Record timestamp parsing, duplicate/conflicting timestamps, missing intervals, outliers, sensor outages, and unit conversions.
- Never relabel synthetic or forecast values as measured. Unknown provenance remains unknown.
- Do not upload restricted data to an environment whose handling and retention have not been approved.

## 3. Baselines and evaluation protocol

- Operational baseline / current practice: `[describe and cite evidence]`
- Simple forecasting baseline(s): `[e.g., previous-hour, previous-day, previous-week]`
- Dispatch or planning baseline: `[describe]`
- Chronological training / tuning / holdout windows: `[dates; no random future-to-past leakage]`
- Evaluation horizon and cadence: `[fill in]`
- Repetitions, seeds, model versions, and configuration hashes: `[fill in]`
- Forecast metrics, reported separately from dispatch outcomes: `[MAE/RMSE/bias/calibration as applicable]`
- Service metrics: unmet water demand, unmet cooling demand, energy use, renewable curtailment, and any relevant backup/grid use.
- Constraint checks and infeasible-run handling: `[fill in]`

Use the same evaluation windows and input availability assumptions for each baseline and candidate. Do not use perfect-foresight inputs for one method while claiming a fair real-time comparison against another. Report adverse outcomes and uncertainty, not only average improvement.

## 4. Owner-approved acceptance thresholds

No universal thresholds are supplied by this template. Each threshold must be set and approved by the responsible site owner before inspecting final holdout results.

| Metric / invariant | Baseline value and source | Acceptance threshold | Measurement window | Rationale / risk owner | Status |
|---|---|---|---|---|---|
| Water service / unmet demand | `[fill in]` | `[owner-defined]` | `[fill in]` | `[fill in]` | `NOT APPROVED` |
| Cooling service / unmet demand | `[fill in]` | `[owner-defined]` | `[fill in]` | `[fill in]` | `NOT APPROVED` |
| Energy / cost metric | `[fill in]` | `[owner-defined]` | `[fill in]` | `[fill in]` | `NOT APPROVED` |
| Data quality / completeness | `[fill in]` | `[owner-defined]` | `[fill in]` | `[fill in]` | `NOT APPROVED` |
| Constraint violations | `[fill in]` | `[owner-defined; normally zero for hard constraints]` | `[fill in]` | `[fill in]` | `NOT APPROVED` |

A metric that is not measured, not comparable, or has no owner-approved threshold is **unresolved**, not a pass.

## 5. Hard-stop and abort criteria

Define the detection method, responsible person, notification path, and action for each trigger.

- Input provenance, units, or timestamps cannot be established.
- Data become stale, missing, out of range, or internally inconsistent.
- Energy/water accounting fails or a hard equipment/operational constraint is violated.
- An output is infeasible, non-finite, or cannot be reproduced from the recorded inputs.
- The application, logging, access control, or monitoring fails.
- The site owner or designated operator requests stop.
- Any result could be interpreted as an actuator command or a substitute for an independent safety interlock.

**Default response:** stop the experiment, preserve the evidence, notify the named owner, and return to the approved baseline. Do not automatically retry, change equipment setpoints, or bypass an interlock.

## 6. Security, operations, and rollback

- Approved hosting environment, authentication/authorization, network boundaries, TLS, and named access owners: `[fill in]`
- Data retention/deletion and backup/restore owner: `[fill in]`
- Logging, monitoring, incident contact, and response time expectations: `[fill in]`
- Resource limits and availability expectations: `[fill in]`
- Read-only/shadow data path and confirmation that no actuator/control path exists: `[diagram or evidence]`
- Rollback steps, operator decision authority, and tested recovery evidence: `[fill in]`
- Cost assumptions, currency, source dates, sensitivity ranges, and excluded costs: `[fill in]`

## 7. Required review and decision

All roles below are **unapproved until a named reviewer records a decision and date**.

| Role | Reviewer | Decision (approve / reject / needs work) | Evidence reviewed | Date |
|---|---|---|---|---|
| Site / data owner | `[name]` | `NOT APPROVED` | `[fill in]` | `[date]` |
| Operations owner | `[name]` | `NOT APPROVED` | `[fill in]` | `[date]` |
| Engineering / model reviewer | `[name]` | `NOT APPROVED` | `[fill in]` | `[date]` |
| Safety reviewer | `[name]` | `NOT APPROVED` | `[fill in]` | `[date]` |
| Security / IT reviewer | `[name]` | `NOT APPROVED` | `[fill in]` | `[date]` |
| Accountable project owner | `[name]` | `NOT APPROVED` | `[fill in]` | `[date]` |

Final decision: `NO-GO UNTIL ALL REQUIRED REVIEWS ARE COMPLETE`

This template cannot authorize live control. Any future integration with operational equipment requires a separate system-specific engineering and safety case, independent safeguards, and explicit authorization from the responsible site authority.
