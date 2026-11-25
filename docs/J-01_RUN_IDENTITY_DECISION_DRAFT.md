# J-01 — Cross-page Run Identity Decision Draft

**Status:** Draft for product and technical review; not an approved contract  
**Date:** 2026-11-25  
**Scope:** Pages 05, 06 and 09; downstream B-01 Run Envelope; compatibility with persistent run records in PR #359.

## 1. Executive finding

The proposed distinction between a page-level `run_id` and a shared `input_group_id` is directionally sound, but the current implementation does not yet consistently mean “one independent execution”.

The most important finding is that pages 05 and 06 currently derive `run_id` deterministically from run-defining inputs. Repeating an identical configuration can therefore produce the same identifier. That is useful as a reproducibility/fingerprint mechanism, but it is not the same as a unique execution-instance identifier.

**Recommendation for team decision:** separate execution identity from reproducibility identity. Do not silently redefine existing IDs in place.

## 2. Evidence from the current code

The following observations were checked against the repository `main` branch at base commit `9615d8238d1d569666d0693d7c3c57ddbbd480b9`.

### Page 05

`pages/05_Customer_Decision_Dashboard.py` calls `deterministic_run_id("run-dashboard", ...)`. Its payload includes dataset SHA-256, site configuration SHA-256, input history SHA-256, recommended policy, optimisation weights, project life and currency. The page then creates a canonical run manifest using that ID.

### Page 06

`pages/06_Forecast_Led_Joint_Resource_Optimizer.py` calls `deterministic_run_id("run", ...)`. Its payload includes dataset SHA-256, site configuration SHA-256, window end, currency, optimizer settings and availability settings. It then creates a canonical manifest using that ID.

### Canonical manifest

`islandos_core/canonical_run.py` defines `deterministic_run_id(prefix, payload)` as a stable hash-derived identifier. The canonical manifest includes `project_id` and `run_id`, dataset digest, site configuration digest, forecast settings, optimizer settings and scenario assumptions. It currently has no `input_group_id` field.

### Run orchestration

`islandos_core/run_orchestration.py` reconstructs the joint-optimizer manifest from a request. Its replay path can pin a run ID and timestamp; the ordinary page path can generate a UUID when no run ID is supplied. This means execution identity behaviour differs between ordinary page execution and deterministic IDs generated in the page itself. The comment describing a fresh UUID is not sufficient to make the page's deterministic ID a unique execution instance.

### View models

`islandos_core/app_view_models.py` includes `run_id` in the joint-optimizer result summary. The customer dashboard summary path currently sets `run_id`, `manifest_sha256` and `evidence_sha256` to null. The summary schema is therefore not yet a fully unified cross-page run envelope.

### Persistence

At the inspected `main` base commit, `workspace_store.py` reports `SCHEMA_VERSION = "1.0"`. PR #359 is still an open, unmerged pull request and proposes persistent run records keyed by `(project_id, run_id)`. Its latest observed commit is `94388ed821ad2763cd7452d530c7c2756dd4e218`; all six workflow checks for that commit completed successfully, including Python unit tests. The PR must still be reviewed and merged separately.

The current persistence key is compatible with unique execution IDs within a project. It is not compatible with trying to insert multiple distinct executions under the same deterministic fingerprint unless the storage key or run-ID semantics change.

### Page 09

`pages/09_Device_Flexibility_Planner.py` builds a typed request view with `build_run_request` and calls `run_device_planner`. Its visible report includes request/result application views, but the page itself does not currently expose a canonical `run_id` or canonical run manifest in the inspected code. It is a synthetic demonstration with fixed in-page inputs. Therefore Page 09 needs an explicit identity lifecycle decision; do not assume its current request view already supplies one.

## 3. Proposed identity model (for approval)

| Field | Proposed meaning | Stability |
|---|---|---|
| `run_id` | Unique identifier for one execution attempt, including a deliberate rerun of identical inputs and settings | New for each execution attempt |
| `run_fingerprint` | Deterministic fingerprint of the canonical run-defining request and relevant model/config versions | Same when canonical run-defining content is identical |
| `input_group_id` | Identifier for a reusable, canonicalised input package shared by different runs/pages | Stable only while the canonical input package and its transformation contract are unchanged |

This separates three questions:
- Which execution attempt is this? `run_id`
- Would the same canonical request reproduce the same defined computation? `run_fingerprint`
- Which canonical input package did this run consume? `input_group_id`

Do not use `input_group_id` as a substitute for dataset provenance, source-file identity, project identity or run identity.

## 4. Input-group rules proposed for review

1. The group should be based on a canonical input package, not merely the uploaded filename or raw file SHA-256.
2. The package fingerprint should include the canonicalised data content, schema/units, selected time window, selected signals and the version/hash of any preprocessing or resampling contract that changes the effective model input.
3. Model/optimizer parameters that are specific to a page run should not be included in `input_group_id`; they belong in the run request/fingerprint.
4. Two pages may share an `input_group_id` only when they consume the same canonical input package under the same input transformation contract.
5. Same raw CSV with different time windows, selected columns, unit conversions or preprocessing should normally produce different input groups.
6. Re-uploading byte-identical data may resolve to the same content-derived input group if canonicalisation and transformation contract are also identical. A separate upload/asset event may still have its own provenance ID.
7. Missing/unavailable input grouping must be represented as `null` with an explicit unlinked status/reason; never fabricate a group ID.

The exact canonicalisation boundary must be confirmed with the data/model owners, especially Ilaha and the owner of Page 09.

## 5. Example envelope fragment

Illustrative only; field names and requiredness are not yet an approved B-01 schema.

```json
{
  "schema_version": "draft-1",
  "project_id": "project-001",
  "page": "06",
  "run_id": "run-execution-uuid",
  "run_fingerprint": "sha256:...",
  "input_group_id": "input-group-sha256:...",
  "identity_status": "linked",
  "created_at_utc": "2026-11-25T08:00:00Z"
}
```

A run with no reliable shared input package should use `input_group_id: null` and a documented status such as `unlinked`; the final enum must be agreed in B-01.

## 6. Lifecycle rules proposed for review

- **Successful run:** mint a new execution `run_id`; retain the canonical request fingerprint and input group.
- **Intentional rerun with identical inputs/settings:** mint a new `run_id`; the `run_fingerprint` may remain identical.
- **Changed model/optimizer settings:** new `run_id` and normally a new `run_fingerprint`; input group can remain the same.
- **Changed input window/schema/units/preprocessing:** new input group and new run fingerprint.
- **Failed execution:** if the system creates a durable run record for attempts, mint a new `run_id` and record a terminal failure status. Whether failed attempts are persisted is a B-01/product decision; do not save a success-shaped result for a failure.
- **Replay:** distinguish a replay of a historical execution from a new execution. A replay may preserve the original run identity as a reference, but a newly executed replay attempt should have its own execution ID and an explicit `replay_of_run_id`.
- **Missing input link:** preserve the run record and mark it unlinked; do not infer a relationship from matching filenames or approximate timestamps.

## 7. Compatibility with PR #359

PR #359's proposed `(project_id, run_id)` primary key is appropriate if `run_id` is unique per execution within a project. It should not be changed to `input_group_id`, because multiple runs are expected to share one input group.

Before merging/integrating, the team must decide how to handle existing deterministic page IDs:
- preserve them as legacy identifiers and add a separate execution ID; or
- migrate the public meaning of `run_id` to execution identity while retaining the old deterministic value as `run_fingerprint`.

The second option is conceptually cleaner but requires careful compatibility work for existing exports, manifests, citations and tests. Do not implement either migration until approved.

The persistent record should store the identity fields as explicit, validated metadata. The run manifest hash and result hash remain integrity evidence; neither should be conflated with `input_group_id`.

## 8. B-01 requirements implied by this draft

B-01 should eventually define a versioned envelope with, at minimum:
- `schema_version`
- `project_id`
- `page` / `run_type`
- `run_id`
- `run_fingerprint`
- nullable `input_group_id`
- `identity_status` and, where unlinked, a reason
- `created_at_utc`
- request/manifest reference and digest
- result status and result reference/digest
- software/model versions
- human-review and no-device-write safety flags where applicable

The envelope must not force Pages 05, 06 and 09 to share model-specific result fields. Common identity/provenance belongs in the envelope; page-specific payloads remain typed and separate.

## 9. Front-end rules implied by this draft

- Display the page/run type and its own execution ID.
- Show a shared-input relationship only when a validated `input_group_id` is present.
- Never merge two runs because their input groups match.
- If no group exists, show a clear unlinked state (the proposed wording is “Unlinked local run”; confirm final UX).
- Do not calculate fingerprints or infer identity in the browser.
- Keep page-specific results and economic comparability separate from identity linkage.

## 10. Decisions still required

1. Approve the semantic distinction between execution `run_id`, deterministic `run_fingerprint` and `input_group_id`.
2. Decide whether failed attempts receive durable run records.
3. Confirm the canonical input package boundary and preprocessing/version fields with data/model owners.
4. Confirm Page 09's actual run lifecycle and responsible module owner.
5. Decide the migration strategy for existing deterministic IDs.
6. Confirm the replay identity semantics and `replay_of_run_id` behaviour.

**No production code has been changed by this document.** This draft is a review artefact, not an approved product contract or a B-01 implementation specification.
