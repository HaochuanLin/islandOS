# IslandOS stages G–K — implementation closeout and remaining gates

**Integration baseline:** `main`  
**Purpose:** record what the G–K delivery cycle added, what remains experimental, and what must be validated next. This document is no longer a forward-looking instruction to rebuild G–K.

## Status summary

The current mainline README and implementation record identify the following G–K outcomes. These are software-foundation outcomes, not field acceptance or production readiness.

| Stage | Scope | Current mainline status | Remaining gate |
|---|---|---|---|
| G | Evidence-gated ML forecasting | Optional Random Forest candidate exists behind the prediction engine and can be evaluated with chronological backtesting. It is not exposed as a selector in the public Streamlit workflow. | Verify identical folds and baselines, data provenance, model eligibility and reproducible benchmark evidence; no site-validated accuracy claim. |
| H | Device-level load flexibility | Device-level planner represents critical, semi-flexible and fully-flexible tasks with selected power, energy, timing, run and priority constraints. | Broaden asset classes and prove edge cases across realistic site configurations; synthetic schedules are not measured savings. |
| I | Multi-resource coordination | Device task schedules can be replayed through shared PV/wind/grid/battery/diesel accounting and compared with an earliest-feasible reference under equal service requirements. | Broader uncertainty propagation, additional asset models, stress tests and real-site engineering review remain. A bounded search is not a global optimum. |
| J | Customer decision workflow and demo | Public Streamlit workflow includes selected forecast-led decision, flexible-load planning, strategy comparison and economics screening paths. | Validate fresh-user completion, consistency across modules, traceability and customer usability; React/API remain a separate foundation. |
| K | Verification, release and demo evidence | CI workflows, runbooks, synthetic demo guidance and release/video documentation are present. | Re-run current default-branch CI, public demo smoke test and all submission artifact checks at release freeze. |

## Existing foundations that must not be rebuilt

- Stage 2 data onboarding, site workspace, asset records and provenance.
- Stage 3 multi-signal forecast catalog, replaceable candidates, chronological replay and per-signal metrics.
- Stage 4 forecast-led battery/diesel/grid coordination, selected flexible-load coupling, RO demand coupling and service-equivalence checks.
- Stage 5 customer-entered economics screening.
- Stage 6 React + TypeScript console foundation; this is not a complete production customer workflow.
- Stage 7 tenant membership and owner-managed workflow foundations; not production identity infrastructure.
- Stage 8 local Streamlit Compose deployment helper; not a full-stack installer.
- Stage 9 local read-only Shadow Mode evidence ledger and verification.
- Stage 10 fail-closed supervised-trial review-package gate; it does not grant operational authority.

## Required next work

1. **Integration audit:** trace which forecast, coordination and comparison modules are actually called by the public app; distinguish integrated paths from standalone experiments.
2. **Forecast evidence:** retain persistence/seasonal baselines, verify chronological splits and data provenance, and evaluate candidates on identical folds.
3. **Device/asset constraints:** test infeasibility, energy conservation, availability, minimum run, time windows and critical-load protection across edge cases.
4. **Common comparison:** replay baseline and candidate schedules through the same accounting model and disclose any omitted physics or service.
5. **Customer validation:** conduct authorized stakeholder discovery and obtain permission before using measured site data; do not invent willingness to pay or savings.
6. **Release freeze:** run current CI, local quick start, hosted demo smoke test, documentation/link checks and submission PDF verification.

## Evidence boundaries

- Random Forest availability does not mean it is the public app's default or that it has site-validated accuracy.
- Device flexibility comparisons are synthetic planning evidence, not measured savings.
- Forecast-to-dispatch integration is limited to supported signal and asset contracts.
- React frontend and local API foundations are separate from the hosted Streamlit deployment.
- Shadow Mode is read-only; no device writes or operational approval are enabled.
- Field validation, production deployment, universal plug-and-play, autonomous control and bankable ROI remain non-claims.

## Release checklist

- [ ] Confirm all relevant changes are merged to `main`.
- [ ] Run Python unit tests, dependency audit, container smoke test, RO tests, Nan'ao regression and Windows gateway build.
- [ ] Verify Streamlit public demo availability and synthetic-data labels.
- [ ] Check README, product blueprint, AI architecture, repository map and screenshots against actual mainline behavior.
- [ ] Check all links and ensure no obsolete workflow diagram is presented as current.
- [ ] Freeze application PDF only after code and claims are reconciled.
- [ ] Preserve test logs, commit SHA, scenario seed and input provenance for the frozen release.

## Historical relationship

G–K follows the numbered engineering stages 1–10 and the earlier A–F workstream. These stage labels represent different historical delivery plans; they must not be treated as one continuous sequence of product workflow steps. See [Engineering Stages 1–10 Closeout](ENGINEERING_STAGES_1_10_CLOSEOUT.md) and [Stage A–F Closeout](STAGE_ABC_CLOSEOUT.md).
