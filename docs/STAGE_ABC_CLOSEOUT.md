# Current six-stage acceptance ledger

**Baseline:** `main` at the 2026-11-13 repository review.  
**Purpose:** This ledger uses the user's current six-stage definitions. It deliberately distinguishes code completion from site validation and production deployment.

## Stage A — Code consolidation and architecture convergence

**Status: core exit criteria met; historical branch-ref pruning remains.**

- Main is the only integration baseline; old pull requests were triaged and superseded changes were closed rather than copied wholesale.
- The forecasting path has one canonical new-work entry point: `forecast_signal_catalog.py` → `prediction_engine.py`; legacy forecast modules are compatibility or specialist paths.
- Shared asset, site-readiness, forecast contract, optimizer, economics, and telemetry boundaries are documented.
- The latest open PR review found only an unrelated Dependabot dependency PR.
- The connected GitHub interface does not expose branch deletion. Historical feature/draft refs therefore remain visible; they do not change mainline behavior, but final repository hygiene requires deleting obsolete refs through GitHub's branch settings/API.

**Acceptance:** mainline architecture and PR triage are complete. Do not claim every old branch has been deleted.

## Stage B — Generic data onboarding and site workspace

**Status: local-first workspace foundation complete; portable project packages and raw-file retention remain future work.**

Implemented:
- CSV/XLSX onboarding and data-quality checks.
- Versioned asset records, provenance-bearing parameters, and readiness checks.
- SQLite project persistence, import metadata, SHA-256 source fingerprints, immutable run manifests, and append-only tamper-evident audit history.
- New atomic whole-workspace backup and restore functions. Both validate SQLite integrity and the audit chain; backup returns a SHA-256 digest; overwriting an existing destination requires explicit opt-in.

Boundaries:
- Original uploaded CSV/XLSX bytes remain outside the workspace database; the store records metadata and hashes only.
- Backup/restore covers the whole SQLite workspace, not an individual portable project package.
- No cloud sync, encryption-at-rest, retention scheduler, secure deletion, or multi-user collaboration is implied.

## Stage C — Unified AI forecasting engine

**Status: implementation exit criteria met; site-specific model validation remains.**

Implemented:
- Canonical signal vocabulary spans energy supply, energy demand, storage, electricity price, water demand/fuel demand, and environment.
- Known signal IDs enforce canonical units and physical sign semantics; custom signals require explicit units.
- A single pluggable prediction engine ranks replaceable candidates with chronological rolling-origin replay.
- Candidate model identity/version, per-signal metrics, source-history SHA-256, forecast timestamps, and empirical error bands are carried into forecast results.
- Added an explicit regression test requiring multiple chronological folds and deterministic ranking.

Boundaries:
- The built-in candidates are transparent statistical baselines, not a claim of advanced trained AI.
- Error bands are empirical historical-error bands, not guaranteed calibrated prediction intervals.
- Synthetic tests establish software behavior only. Accuracy at a named customer site requires measured data and separate acceptance.

## Current hand-off to D–F

| Stage | Next delivery focus |
|---|---|
| D — Multi-resource coordination | Bring water inventory/RO production and flexible loads into the same forecast-to-physics-to-optimizer path; preserve hard service and equipment constraints. |
| E — Customer product and identity | Complete organization/member lifecycle, permissions, notifications, full decision reports, and customer-grade lifecycle economics. |
| F — Real deployment and field validation | Production database/security/monitoring/backup, vendor protocol adapters, read-only shadow operation, site-engineer review, and signed pilot acceptance. |

No stage claims production control. All physical-device actuation remains disabled pending separate safety, authorization, and engineering acceptance.
