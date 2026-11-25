# B-02 Annual Projection Persistence Audit

- Status: implementation audit; no production changes.
- Baseline: `main` at `9615d8238d1d569666d0693d7c3c57ddbbd480b9`; run-record storage reviewed on PR #359 head `94388ed`.
- Scope: Page 06 annual operating-basis projection, its request inputs, and the immutable local Workspace run-record contract.
- Boundary: this document does not claim that a projection is a bill, measured annual operation, or site-validated evidence.

## 1. Existing annual projection contract

Page 06 already offers an optional annual projection behind an explicit checkbox and a declared `days_equivalent_per_year` value (1–366). It projects the recommended schedule's own nominal dispatch summary, which is also the dispatch behind the hourly setpoint rows. It does not annualise scenario replays or the worst-case scenario.

The existing `annualise_run_summary` record contains:
- `run_id`, `manifest_sha256`, `data_provenance`, and `summary_source`;
- simulated hours and the declared equal-days basis;
- six annual figures and their definitions;
- `derived_from_run=true`, `site_validated=false`, `measured=false`, and `bill=false`;
- an `annualisation_sha256` digest.

`verify_annual_operating_basis` checks the digest, key scope flags, the day-count range, the named summary source, required figures, and that no device command is authorised or generated. Existing tests cover arithmetic, assumptions, tamper detection, render order, and the selected-dispatch source.

## 2. Persistence capability already present in PR #359

The proposed `record_run_record` API accepts a JSON-object `result`, serialises it, stores a SHA-256 digest, and verifies that digest when reading. It does not impose a fixed schema on nested result keys. Therefore an annual projection can be retained inside the run result without a new SQL table or annual-specific database column.

The same record can retain:
- sanitised request metadata by default;
- the full validated request only after a separate explicit opt-in;
- an optional canonical manifest and model/software versions.

A metadata-only record is viewable but not replayable. A full-request record is marked replayable, subject to compatible software/model versions. The record writer also requires an already-registered Workspace `project_id` and explicit result-storage consent.

## 3. Integration gap

The current Page 06 flow calculates and verifies `annual_record` / `annual_view` for display and report output, but does not write that result to the local Workspace run-record store. Page 06 currently creates its manifest with the fixed label `streamlit-joint-resource-workspace`; this is not evidence of a registered Workspace project.

The local Workspace is opt-in and initialised through Page 08. The hosted Streamlit demo is a separate surface and must not be described as connected to a user's local Workspace database.

## 4. Recommended B-02 shape

1. Keep annual projection generation optional and unchanged: no declared assumption means no annual projection object.
2. When a projection exists, include the exact verified projection object under a clearly named result key, e.g. `annual_operating_basis_projection`. Do not reconstruct it from rounded display metrics.
3. Keep the annualisation basis in the retained request/run settings, including `days_equivalent_per_year`; a retained result alone is evidence of what was produced, not enough to reproduce it.
4. On read/replay, verify the outer run-record result digest first, then run `verify_annual_operating_basis` on the nested projection before displaying or exporting it.
5. Treat a missing annual projection as a valid non-annualised run, not as a zero-valued annual result.
6. Preserve the existing scope flags and labels. Never map the projection into customer-entered annual bills or Page 05 investment inputs.
7. Require a real selected local Workspace project and explicit result-storage consent before persistence. Full request/history retention remains a separate opt-in.
8. Do not silently overwrite an existing immutable record. Duplicate/idempotent behaviour must follow the agreed B-01 / PR #359 contract.

## 5. Dependencies and decisions still open

- **B-01 project binding:** Page 06 needs an explicit route from its simulation session to a registered local Workspace project. The fixed manifest label cannot be used as a database project ID.
- **Run identity:** the final run identity contract must define how the annualisation day-count setting participates in run identity. Changing 200 to 365 days changes the annual projection even if the underlying 24-hour dispatch is unchanged. It must not be silently treated as the same complete run definition.
- **PR #359 API:** the current PR has no `input_group_id` field, no idempotent duplicate path, and no failure-attempt API in its run-record implementation. B-02 should not invent a competing storage API.
- **Replay:** the request schema/replay path must carry the optional annual day-count assumption and reproduce the same selected dispatch summary. The existing annual projection function alone does not provide a full replay workflow.
- **Retention:** metadata-only persistence cannot promise replay. UI copy must distinguish “saved result” from “replayable run”.

## 6. Minimum acceptance tests for implementation

- No annual checkbox / no day-count assumption: result contains no annual projection; ordinary run remains usable.
- Annual projection enabled: the persisted result contains the exact verified projection and its digest.
- Tampered nested projection: outer result integrity or annual projection verification fails closed.
- A changed day-count assumption produces a different run identity or a clearly versioned distinct projection identity, per the signed B-01 contract.
- Metadata-only record can be read and displayed but is never presented as replayable.
- Full-request retention remains impossible without its separate consent.
- Missing or unregistered project, or missing result-storage consent: no run record is written; simulation itself remains available.
- Existing Page 06 annual projection tests and run-record integrity tests continue to pass.

## 7. Non-goals

- No new annual database table or schema column is proposed by this audit.
- No automatic 365-day assumption.
- No use of projected annual figures to fill or validate customer bills.
- No conversion of the projection into measured customer savings.
- No cloud sync, hosted-demo persistence, device command, or closed-loop control.
- No changes to PR #359 or PR #362 branches.

## Conclusion

B-02 appears implementable as an integration of an already-existing, integrity-checked annual projection into the generic immutable run-result JSON. The principal blockers are not annual arithmetic or database schema: they are B-01's real project binding, the signed run-identity contract (including the annualisation assumption), and the final PR #359 persistence semantics. Implementing B-02 before those contracts are settled risks saving a result under the wrong project or an identity that does not distinguish different annual assumptions.
