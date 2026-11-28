# IslandOS Release Hardening — 2026-11-28

Status: hardening work merged. No runtime calculation, default value, unit, protected value, or identity semantic changed.

## Baseline and result

| Item | Value |
| --- | --- |
| Audit baseline | `main = 325afda222cf08fd8cd73a8a5d3845fff267cf38` |
| Hardening merge head | `c2d0c1aad2493c08da9dc5ff0a4e25c2de2793bf` |
| Public Streamlit build reviewed | `325afda` |
| Page06 export/replay regression | PR [#386](https://github.com/HaochuanLin/islandOS/pull/386), merged `cab267a` |
| Replay/identity documentation | PR [#387](https://github.com/HaochuanLin/islandOS/pull/387), merged `c2d0c1a` |

Both PRs passed all ten CI checks (`unit-tests`, `integration-examples`, `hybrid-scenario`, `build-and-smoke-test`, `build-windows-gateway`, and the five dependency-audit jobs). The new test was also rerun on the merged main: **2 passed, 4 warnings in 8.75s**.

Because PR #386 and #387 only add a test and documentation, the public Streamlit runtime behavior remains the `325afda` behavior. The public build stamp still read `325afda (git)` during the review.

## Page06 real export → replay

PR #386 adds `tests/test_page06_export_replay.py`. It drives the real `pages/06_Forecast_Led_Joint_Resource_Optimizer.py` through `AppTest`, captures the actual **Download joint schedule audit (JSON)** bytes, parses `application_views.request`, and passes that exact object to the production `replay_run_request()` and `build_joint_optimizer_manifest()`. It does not rebuild the request by hand.

Two scenarios pass:

- the synthetic default 168-hour page;
- a shared-session uploaded 72-hour CSV.

Assertions cover:

- `request_sha256` recomputes from the exported request;
- `run_id`, `manifest_sha256`, `created_at_utc`, `summary_sha256`, `evidence_sha256`, and the full result summary agree across page export, manifest builder, and replay;
- `created_at_utc` equals the last UTC hour of the request window;
- the uploaded scenario has a non-empty `source_file_sha256` and the uploaded filename in provenance.

Recorded sample from the local synthetic page export:

| Field | Value |
| --- | --- |
| Canonical run | `run-3e93addd7661f937` |
| Manifest SHA-256 | `0ef3eb7edcf85d0404baaf637c9cc19818159055c24e9afe210b1787adf59b0e` |
| `created_at_utc` | `2026-11-22T14:00:00Z` |
| `request_sha256` | `1a372195381dca6b4a3bc118295d660be6848c1006ae9e12baa27ef8916e72c4` |
| Window | 168 hours |

The uploaded sample used 72 hours, run `run-45ad518253906489`, source `Session-shared CSV: uploaded-site.csv (not independently verified)`.

This closes the gap between “the page displays a run” and “the exported record can be replayed to the same run.” Matching displayed numbers alone is not treated as proof.

## Cross-host identity boundary

The canonical run is reproducible for the same raw input, but it is not necessarily identical across hosts for synthetic defaults. The boundary is:

- `islandos_core.demo_site_history.build_synthetic_site_history` uses `math.sin`; the last bit can differ between maths libraries on Windows and Linux.
- `canonical_history_sha256` rounds every signal to six decimals before hashing (`HISTORY_HASH_DECIMALS=6`), so the shared history SHA stays stable across those last-bit differences.
- `build_joint_optimizer_manifest` hashes the **raw** `timestamps_utc`, `signals`, and `units` when the request has no uploaded-file `source_sha256`. Its dataset digest therefore changes with the last bit, and so do `run_id` and `manifest_sha256`.
- Uploaded data uses the file-byte SHA-256 as its dataset digest, so identical uploaded bytes are stable across hosts.

One-ULP probe: changing PV's first point from `18.243354954612926` to `18.24335495461293` left the shared history hash `7012014ef720e5802d1ff9147fe439b93d52736f47c538170da46d55b6d2ed70` unchanged, but changed the dataset digest from `6a58b14c0115bc45622dd06f68c30ff90ddcc0ea261a6d92b424c6c89796813f` to `9922da3208fefd89e41ce4cfb8a7c163b0fd1eb2c2adebe465b40f9b00a907f1`, and the run from `run-eecfaee7529538d8` to `run-24e89deec12b9bd7`.

Public evidence agrees with this boundary: the `325afda` public Page06 showed shared history `7012014e…` but canonical run `run-07f602e35be903ad` (`manifest 075b0c261cfdb016…`, `evidence 24f2bcfc07ae43b2…`); the local Windows export of the same default window had the same shared history and a different canonical run.

No rounding was added to run or manifest IDs. Doing that would rewrite audit identity and could merge datasets that are genuinely distinct. The documented path is a stable recorded fixture or an explicitly canonical decimal dataset export with a migration; both need a schema/version decision before implementation.

Documentation landed in `docs/REPRODUCIBILITY.md` with the replay commands, digest meanings, `created_at` semantics, the six-decimal-versus-raw-manifest boundary, and the reasoning against rounding. `docs/J-01_RUN_IDENTITY_INTERFACE.md` now states that the `run-06-…` vector is a P1b pure-function fixture, not the current Page06 runtime canonical run.

## Public customer review

The public pages reviewed at 670×670 were the landing page, Customer Decision Dashboard, and Joint Resource Optimizer.

What held:

- the landing page identifies the prototype, limits, synthetic data, and customer-supplied uploads;
- the dashboard showed `24.52 USD`, `0.00 kWh`, and `10.55 USD`, with the modeled-not-measured qualification;
- Page06 showed `ready for human review`, `physical audit passed (4 scenarios)`, `human review required`, and `device write not authorized`;
- Page06 technical appendix distinguishes its own canonical run from a cross-page handoff ID.

Visible issue:

- At 670 px, dashboard metric labels break inside words: `RECOMMEND ED POLICY`, and `MODELED COST DIFFERENCE VS GRID-` is truncated. `35.07` is not in the visible metric row, so its public rendering was not visually confirmed. This is a narrow-width legibility issue, not a calculation issue.

Recommended minimum fix, if the team wants to take it: a narrow-width rule for metric labels that reduces uppercase label size and prevents intra-word wrapping, followed by a 390/670/desktop check. It should be a separate UI PR; this hardening pass did not change layout.

## Coverage and regression matrix

| Area | Existing evidence | Status |
| --- | --- | --- |
| CSV calculation consistency | `test_demo_csv_schema.py`, `test_validate_site_csv.py`, `test_customer_dashboard_adapter.py`, new uploaded Page06 replay | Partial: the real uploaded Page06 path is now covered; a full Page05 CSV → HTML/JSON byte comparison is not |
| Page05 HTML/JSON consistency | Source-wiring tests plus an assertion that the binding reaches the report; no test captures the actual downloads | **Gap** |
| Page06 export/replay | `test_page06_export_replay.py` (synthetic + uploaded) | Covered |
| Deterministic identity | `test_demo_site_history.py` pins the default history hash and six-decimal behavior; new test checks page/builder/replay equality | Partial: the raw-manifest one-ULP sensitivity is only manually probed, not locked by a test |
| Upload validation and provenance | `test_validate_site_csv.py`, `test_upload_guard.py`, new uploaded replay | Covered |
| Missing/malformed fields | `test_app_view_models.py`, `test_application_transport.py` | Covered |
| Time zones | `test_demo_site_history.py`, `test_application_transport.py` | Covered |
| Rounding and units | six-decimal hash tests; `24.52` and annual `7,709.55 / 5,332.57` page tests | Partial: `35.07` and `10.55` are not directly locked |
| Protected values | `24.52` and annual Page06 values are tested | **Gap**: no direct test locks `35.07`, `10.55`, `21,302`, or `6.0 years` |
| Public/private and device boundary | control-boundary tests; public labels | Covered |

The two gaps worth fixing first are the Page05 export-byte test and explicit locks for the protected commercial values. Neither requires changing the values; both make an accidental change visible.

## Limitations

- The cross-host probe used a local Windows run and the public Linux-hosted build; it did not run the same build on two controlled hosts with known libm versions.
- The public review was a 670 px browser observation, not a full desktop/mobile matrix.
- PR #386 proves export/replay identity for the tested 168-hour synthetic and 72-hour uploaded windows, not every possible upload or device configuration.
- Documentation explains the identity boundary; it does not decide whether a future canonical-decimal migration is product-acceptable.
