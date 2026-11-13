# Phase A — Architecture Consolidation and Repository Hygiene

**Review date:** 2026-11-13  
**Status:** In progress; this document records verified repository evidence and merge decisions.  
**Scope:** Generic, reusable IslandOS platform. Nan'ao/competition-specific experiments are not product architecture.

## 1. Current baseline

- The authoritative integration branch is `main`, at the reviewed baseline commit recorded during this audit.
- Do not treat open PRs, feature branches, Streamlit screenshots, or README claims as merged product capabilities.
- The repository already contains substantial simulation, forecasting, rolling-dispatch, asset/readiness, data-quality, economics, telemetry-contract, and dashboard research code. The next architecture step is integration and operational productization, not rewriting these domains from scratch.
- Keep the current single canonical implementations for asset/topology/energy models and investment economics. Do not reintroduce duplicate lifecycle/economics modules from historical branches.

## 2. Open pull-request triage

| PR | Scope | Evidence against current main | Decision |
|---|---|---|---|
| #206 | Generic CSV/XLSX onboarding, local SQLite workspace, run manifests, audit chain, governance docs | Based directly on current main; 8 commits ahead, 0 behind; 10 named CI checks completed successfully on its exact head; still Draft | **Keep as the next product-foundation candidate.** It is primarily Stage B, not a reason to call Stage A complete. Review integration and security limitations before merge. |
| #189 | Rolling-lab forecast/objective-weight controls | Diverged; 3 commits ahead and 130 behind current main. Changes are confined to one Streamlit page and its test. | **Do not merge as-is.** Re-port the small UI behavior onto current main after confirming the current page contract; then run fresh CI. |
| #182 | Dispatch accounting invariant stress suite | Diverged; 6 commits ahead and 136 behind current main. Adds a useful generic seeded accounting test, but also changes workflow/README/roadmap. | **Do not merge as-is.** Selectively re-port the test module, tests, docs and workflow integration onto current main; verify workflow compatibility and exact-head CI. |
| #190 | Large Nan'ao scenario-pilot branch | Diverged; 121 commits ahead and 584 behind current main. Its README replaces the generic platform README with a Nan'ao-specific narrative; branch also bundles generic telemetry/readiness/dispatch work with competition-specific scenario code. | **Never merge wholesale.** Preserve the branch as historical source material; selectively recover generic reusable components only after per-file comparison with current main. Keep Nan'ao scenario material outside the generic product core. |
| #188 | Nan'ao wind + valley economic comparison | Targets the separate `nan-ao-scenario-pilot` branch, not main; Draft and not mergeable. Changes are limited to Nan'ao scenario code/tests. | **Keep out of the generic mainline.** It may remain an isolated research branch; no product merge. |

## 3. Mainline architecture rules

1. `main` is the only integration baseline. Feature branches must be refreshed against current main before review.
2. No wholesale merges from branches with large divergence or destructive README replacement.
3. Keep one canonical implementation for each domain: site/assets/topology, forecasting interfaces, dispatch/optimization, investment economics, telemetry contracts, and customer workspace.
4. Keep experiments and competition/site-specific case studies under clearly named experiments or examples; they must not redefine the generic product identity.
5. Separate measured, customer-provided, synthetic, forecast, inferred, and vendor-specification data in schemas and reports.
6. Simulation/optimization outputs remain decision support. No live control writes or claims of site validation without explicit engineering and field evidence.
7. A feature is complete only when implementation, tests, documentation, integration path, and exact-head CI evidence agree.

## 4. Known boundaries that must not be misrepresented

- The local SQLite workspace in PR #206 is a single-user prototype. It is not a multi-tenant database, encrypted vault, authentication/authorization system, backup/restore service, or secure deletion system.
- Existing sensor/telemetry contracts and mock sources do not establish production device connectivity.
- Dashboard pages and example datasets do not prove real customer data integration.
- Passing synthetic tests establishes tested software invariants only; it does not certify physical fidelity, forecast accuracy, site safety, or savings.

## 5. Recommended sequence after Phase A

- First, complete a clean integration review of #206 and merge only after its exact-head checks remain green and the draft is explicitly ready.
- Re-port the useful, small changes from #189 and #182 on fresh branches from current main rather than merging their divergent histories.
- Extract generic reusable pieces from #190 one module at a time; reject Nan'ao-only scripts and competition material from the product core.
- Then freeze the canonical module boundaries and proceed to customer/site data onboarding, service integration, identity/access, and deployment work.

## 6. Phase A exit criteria

- [x] Current main identified as the integration baseline.
- [x] Open PRs compared against current main by commit divergence and changed-file scope.
- [x] Destructive/obsolete whole-branch merge paths identified and explicitly rejected.
- [x] Generic product architecture rules and evidence boundaries documented.
- [ ] Stale PR queue closed or converted into fresh, current-main-based work.
- [ ] Generic components worth recovering from historical branches inventoried per module.
- [ ] Exact-main CI and smoke-test baseline recorded after consolidation.

Phase A is **not complete** until the remaining unchecked items are verified.
