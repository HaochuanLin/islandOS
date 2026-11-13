# Phase A — Architecture Consolidation and Repository Hygiene

**Review date:** 2026-11-13  
**Status:** Core architecture and integration governance are closed on main; dormant branch-ref cleanup remains an operational repository-hygiene item because the connected GitHub interface does not expose branch deletion.  
**Scope:** Generic, reusable IslandOS platform. Nan'ao/competition-specific experiments are not product architecture.

## 1. Current baseline

- `main` is the only integration baseline. The Phase A governance PR #207 was squash-merged as `c8d20426318395480a3c2d4e6767c5788e6d8497`.
- Do not treat open PRs, feature branches, Streamlit screenshots, or README claims as merged product capabilities.
- The repository already contains substantial simulation, forecasting, rolling-dispatch, asset/readiness, data-quality, economics, telemetry-contract, and dashboard research code. The next architecture step is integration and operational productization, not rewriting these domains from scratch.
- Keep one canonical implementation for each domain. Do not reintroduce duplicate lifecycle/economics modules from historical branches.

## 2. Historical PR triage

| PR | Scope and evidence | Decision |
|---|---|---|
| #207 | Architecture rules and stale-PR triage; documentation-only; six associated CI workflow runs passed on exact head before merge. | **Merged** to main. |
| #206 | Generic CSV/XLSX onboarding, local SQLite workspace, run manifests, audit chain, governance docs. All eight changed files were verified to have identical Git blob SHAs on current main. | **Closed as superseded without merge** on 2026-11-13; no code was discarded because all eight files already exist byte-for-byte on main. |
| #189 | Rolling-lab forecast/objective-weight controls; 3 commits ahead and 130 behind at review; confined to one old Streamlit page and test. | Closed without merge. Re-port only if the current forecast-led dashboard demonstrably lacks the same operator workflow. |
| #182 | Dispatch accounting invariant stress suite; 6 commits ahead and 136 behind at review; useful seeded accounting tests bundled with unrelated workflow/README/roadmap edits. | Closed without merge. Retain the test ideas as a targeted test gap; do not import the stale branch wholesale. |
| #190 | Large Nan'ao scenario-pilot branch; 121 commits ahead and 584 behind at review; bundled generic work with Nan'ao-specific scenario code and replaced generic README narrative. | Closed without merge. Nan'ao scripts and competition material stay out of generic main. Recover generic code only if a per-file comparison proves a concrete gap. |
| #188 | Nan'ao wind + valley economic comparison; targeted the separate Nan'ao pilot branch, not main. | Closed without merge; scenario-specific research only. |

## 3. Canonical module inventory

This is a product-boundary inventory, not a claim that every module is production-ready.

| Domain | Canonical responsibility on main | Boundary / recovery decision |
|---|---|---|
| Site, assets, topology, readiness | Shared site and asset models plus readiness checks | Do not copy duplicate asset/topology implementations from old branches. |
| Data quality and provenance | Typed source classes, validation, time-series quality checks, source disclosures | Keep measured, customer-provided, public, synthetic, forecast, inferred, and vendor-spec data distinguishable. |
| Forecasting | New canonical site path: `forecast_signal_catalog.py` (signal semantics + multi-domain orchestration) → `prediction_engine.py` (pluggable candidates, chronological replay, selection, error bands). `forecast_contract.py` remains the validated forecast-to-planning boundary. | New work uses this path. `forecast_engine.py`, `multisignal_forecasting.py`, `forecasting.py`, `tariff_forecasting.py`, and `scenario_forecasting.py` remain compatibility/specialist surfaces; do not add new competing registries. Migrate consumers only with parity tests. No site-accuracy claim without site-specific backtests. |
| Dispatch and optimization | Resource coordination, tariff-aware flexible-load optimization, constraints and audit outputs | Re-port #182's useful accounting invariants as focused tests only after comparing against existing tests; never bring its old workflow edits wholesale. |
| Economics | Canonical investment economics and customer-entered assumptions | Keep one lifecycle/investment economics service; do not restore duplicate historical economics modules. |
| Telemetry and device boundary | Telemetry contracts and gateway scaffolding | Contracts/mock sources are not production device connectivity. No write/control path is implied. |
| Customer decision experience | Streamlit customer dashboard, scenario comparison, audit and export | Current pages are prototype UX; no multi-tenant user system or production service is implied. |
| Customer data onboarding and workspace | `islandos_core/onboarding.py`, `islandos_core/workspace_store.py`, asset records and onboarding tests | Integrated local-first Stage B foundation. Single-user/local prototype; not encrypted multi-tenant storage, authentication, backup/restore, or secure deletion. |

## 4. Mainline architecture rules

1. `main` is the only integration baseline. Feature branches must be refreshed against current main before review.
2. No wholesale merges from branches with large divergence or destructive README replacement.
3. Keep one canonical implementation for site/assets/topology, forecasting interfaces, dispatch/optimization, investment economics, telemetry contracts, and customer workspace.
4. Keep experiments and competition/site-specific case studies under clearly named experiments or examples; they must not redefine the generic product identity.
5. Preserve provenance and units; never silently infer ambiguous units, fill missing measurements, or disguise synthetic data as measured data.
6. Simulation/optimization outputs remain decision support. No live control writes or claims of site validation without explicit engineering and field evidence.
7. A feature is complete only when implementation, tests, documentation, integration path, and exact-head CI evidence agree.

## 5. CI evidence and limits

- PR #207's exact head `520bde3cf3f6a0b406c8ef5b9413ff00035a593f` had six associated GitHub Actions workflow runs, all completed successfully, before squash merge. The PR changed documentation only.
- PR #206 was closed as superseded after all eight changed files were compared against `main` and found to have identical Git blob SHAs. Its earlier CI evidence is historical only; no merge was needed.
- The available connector did not expose a post-merge push-run record for the squash commit. Therefore this records the PR integration gate, not a claim that a separate post-merge main workflow ran.
- Passing synthetic tests establishes tested software invariants only; it does not certify physical fidelity, forecast accuracy, site safety, or savings.

## 6. Known boundaries that must not be misrepresented

- The local SQLite workspace on `main` is a single-user prototype, not a multi-tenant database, encrypted vault, authentication/authorization system, backup/restore service, or secure deletion system.
- Existing sensor/telemetry contracts and mock sources do not establish production device connectivity.
- Dashboard pages and example datasets do not prove real customer data integration.
- The public Streamlit demo is not a customer data room; confidential site telemetry must not be uploaded without explicit approval and an appropriate environment.

## 7. Phase A exit criteria

- [x] Current main identified as the only integration baseline.
- [x] Historical PRs compared by divergence and scope; stale whole-branch merge paths closed or rejected.
- [x] Canonical module responsibilities and historical recovery decisions inventoried.
- [x] Architecture rules, data provenance, and product maturity boundaries documented.
- [x] Exact-head integration CI evidence recorded, including the limitation that no separate post-merge push run was exposed.
- [x] Stage B implementation verified on `main`; stale duplicate PR #206 closed without discarding code.
- [ ] Repository branch cleanup: more than 200 branch refs were observed across the first two API pages; retain branches with unresolved unique work and prune merged/stale refs in a reviewed batch. The available GitHub action interface does not expose branch deletion, so this item remains open.

**Phase A has a canonical forward architecture and PR governance, but repository hygiene is not fully closed while the large dormant branch set remains.** Main is the sole integration baseline; PR #206 is superseded. New forecasting work has one designated canonical path. Branch pruning remains an explicit cleanup item rather than silently claiming that dormant refs were removed.
