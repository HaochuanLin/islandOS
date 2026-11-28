# IslandOS Release Hardening — 2026-11-28

Status: reconciled after the Page05 follow-up work, with implementation baseline
`4254027` (PR #393). Historical findings are retained as dated findings, not
current gaps. This document is the single hardening status record; it does not
replace `docs/REPRODUCIBILITY.md`.

## Baseline and follow-up record

| Item | Value |
| --- | --- |
| Initial audit baseline | `325afda222cf08fd8cd73a8a5d3845fff267cf38` |
| Initial hardening merge head | `c2d0c1aad2493c08da9dc5ff0a4e25c2de2793bf` |
| Public build during initial review | `325afda` |
| Page05 follow-up implementation baseline | `4254027` |
| Page05 public acceptance build (at review time) | `a04f201 (git)` |

| PR | Result | Merge commit |
| --- | --- | --- |
| [#386](https://github.com/HaochuanLin/islandOS/pull/386) | Page06 real export → replay regression | `cab267a` |
| [#387](https://github.com/HaochuanLin/islandOS/pull/387) | Replay/identity documentation | `c2d0c1a` |
| [#389](https://github.com/HaochuanLin/islandOS/pull/389) | Page05 commercial-value protection | `151289b` |
| [#390](https://github.com/HaochuanLin/islandOS/pull/390) | Page05 actual HTML/JSON export consistency | `3079fed` |
| [#391](https://github.com/HaochuanLin/islandOS/pull/391) | Narrow-screen metric-label fix | `63e0c1b` |
| [#392](https://github.com/HaochuanLin/islandOS/pull/392) | Medium-width and non-breaking-hyphen fix | `a04f201` |
| [#393](https://github.com/HaochuanLin/islandOS/pull/393) | Persistent Page05 responsive CI | `4254027` |

PR #393 passed all 11 checks on its branch, including the new `responsive` job.
The final main status is recorded in the phase hand-off report, not frozen here.

## Historical Page05 finding — resolved

The initial 670 px public review at `325afda` found labels breaking inside words
(`RECOMMEND ED POLICY`) and the `GRID-` line truncated. That finding was
historical, not a current gap.

- #391 and #392 fixed the label wrapping and the 1180/1181 typography boundary.
- Manual public acceptance at `a04f201` covered 390, 670, 1024 and 1440 px. All
  eight protected values were present, no label overflow or hyphen-ended line
  was observed, and `grid-first` stayed together.
- The manual check was performed on the public deployment, but it was not
  persistent CI coverage. #393 supplies that coverage separately.
- `35.07 USD` remains in the decision report's
  `reference_summary.estimated_energy_cost` and the paired-impact evidence. It
  is **not** part of the visible top metric row, and its public visual rendering
  has not been confirmed.

## Current automated coverage

### Page05 commercial values

`tests/test_commercial_value_protection.py` loads the real Page05 with
`AppTest`, reads the rendered metrics and parses the actual decision-report
download. It protects:

- visible `24.52 USD`, `10.55 USD`, `0.00 kWh`, `21,302 USD`, `6.0 years`;
- report `35.07 USD` in `reference_summary`, with the underlying
  `35.06733423` and `10.54503833` values;
- the demonstration assumptions and formatting boundary.

`scripts/check_page05_responsive.py` additionally locks the eight rendered
values in a real browser, including `8.5 years` and `32,825 USD`.

### Page05 actual export consistency

`tests/test_page05_export_consistency.py` captures the actual bytes emitted by
the three real Page05 download handlers: customer HTML, decision report JSON and
human-review decision record JSON. It parses each independently and asserts:

- HTML cells agree with the JSON numbers;
- the report's selected, grid-first reference and difference values agree;
- the human-review record is byte-for-byte the embedded record, with
  `ready_for_human_review`, `human_review_required: true` and
  `device_write_authorized: false`;
- the currency label propagates through all three exports for USD and EUR.

This is automated **AppTest** export evidence. It is not a fresh download from
the public deployment.

### Page05 responsive layout

`scripts/check_page05_responsive.py` runs against a locally started Streamlit
app in the dedicated `Page05 responsive layout` GitHub Actions job. It measures
the rendered DOM at **320, 390, 670, 1024, 1180, 1181 and 1440 px** and asserts:

1. all eight protected labels and values are present;
2. labels and values do not overflow their boxes;
3. no label line ends with a hyphen;
4. `grid-first` is not split at the hyphen;
5. labels and values remain inside their card;
6. card width and height remain readable;
7. the expected two-up (≤560 px) or four-up card layout is preserved.

The job passed on PR #393 in Linux Chromium at all seven widths. It uses branch
code and does not depend on the public deployment or an external service.

## Historical cross-host identity boundary

The canonical run is reproducible for the same raw input, but it is not
necessarily identical across hosts for synthetic defaults:

- `islandos_core.demo_site_history.build_synthetic_site_history` uses `math.sin`;
  the last bit can differ between maths libraries on Windows and Linux.
- `canonical_history_sha256` rounds signals to six decimals before hashing
  (`HISTORY_HASH_DECIMALS=6`), keeping the shared history SHA stable.
- `build_joint_optimizer_manifest` hashes the raw timestamps, signals and units
  when there is no uploaded-file SHA. The dataset digest, `run_id` and
  `manifest_sha256` can therefore change with that last bit.
- Uploaded data uses the file-byte SHA-256 as its dataset digest and is stable
  across hosts.

The one-ULP probe remains manual: changing PV's first point from
`18.243354954612926` to `18.24335495461293` left the shared history hash
unchanged but changed the dataset digest from
`6a58b14c0115bc45622dd06f68c30ff90ddcc0ea261a6d92b424c6c89796813f` to
`9922da3208fefd89e41ce4cfb8a7c163b0fd1eb2c2adebe465b40f9b00a907f1` and the run
from `run-eecfaee7529538d8` to `run-24e89deec12b9bd7`.

No rounding was added to run or manifest IDs. A stable recorded fixture or an
explicit canonical-decimal export still requires a schema/version decision.

## Coverage matrix

| Area | Current evidence | Status |
| --- | --- | --- |
| CSV calculation consistency | schema, validation and adapter tests; uploaded Page06 replay | Partial: no public Page05 CSV → export byte comparison |
| Page05 HTML/JSON consistency | `test_page05_export_consistency.py`, real AppTest download bytes, USD + EUR | Covered for AppTest |
| Page05 commercial values | `test_commercial_value_protection.py`, browser check at seven widths | Covered for visible values and report reference |
| Page05 responsive layout | `page05-responsive.yml`, seven Chromium widths | Covered in CI |
| Page06 export/replay | `test_page06_export_replay.py`, synthetic + uploaded | Covered for AppTest |
| Deterministic identity | default-history hash and six-decimal tests; page/builder/replay equality | Partial: raw-manifest one-ULP sensitivity is manual |
| Upload validation and provenance | validation, upload guard and uploaded replay | Covered |
| Missing/malformed fields | application view and transport tests | Covered |
| Time zones | history and transport tests | Covered |
| Rounding and units | six-decimal hash tests; formatted Page05 values | Covered |
| Public/private and device boundary | control-boundary tests; public labels | Covered |

## Remaining unverified areas

- Public Page05 HTML/JSON downloads were not freshly downloaded and parsed.
  The automated test uses `AppTest`.
- Public Page06 audit JSON was not freshly downloaded and replayed. The
  automated test uses `AppTest`.
- `35.07 USD` has not been visually confirmed on the public dashboard; it
  remains report/reference evidence.
- Browser zoom, large system fonts, Safari/iOS and physical mobile devices have
  not been tested. CI covers Linux Chromium at fixed CSS widths.
- The cross-host raw-manifest boundary was probed on one local Windows run and
  one public Linux-hosted build; it was not run on two controlled hosts with
  known libm versions.
- The responsive job is a failing PR check, but `main` has no branch-protection
  rule requiring it. Without that repository setting it is observable, not a
  hard merge block.

## Public customer review — historical

The initial 670×670 review at `325afda` also checked the landing page and Page06:
the landing page stated the prototype, synthetic-data and upload boundaries;
Page06 showed `ready for human review`, a passed physical audit, required human
review and no device-write authorization. Those findings remain historical
acceptance evidence, not a claim of field deployment.
