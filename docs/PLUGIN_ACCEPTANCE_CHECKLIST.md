# Plug-in acceptance checklist

This checklist defines when a new site adapter, forecast model, or dispatch policy can be described as plug-in compatible. It is an engineering gate, not a claim that a site is safe to operate.

## Product promise

A user with no measured data must be able to install IslandOS, run a deterministic synthetic example, understand every assumption, and export a reproducible report. A site with real data must be able to connect it through a documented adapter without editing the dispatch engine. Neither workflow may silently turn synthetic inputs into field evidence.

## Acceptance gates

### 1. Install and first run
- [ ] A clean environment can install the documented dependencies from the repository root.
- [ ] The documented synthetic demo runs from a clean checkout with one copy-paste command.
- [ ] The command exits non-zero on invalid arguments or failed output writes.
- [ ] Output directories are created deliberately; existing user data is not overwritten without an explicit policy.
- [ ] The report identifies itself as synthetic when generated from synthetic inputs.

### 2. Data contract
- [ ] Every required column, unit, timezone assumption, and valid range is documented.
- [ ] Timestamps are parseable, ordered, and duplicate handling is explicit.
- [ ] Missing, non-finite, and physically impossible values are rejected or reported with row/column context.
- [ ] No silent interpolation, unit conversion, or imputation occurs without an explicit, auditable option.
- [ ] Input provenance distinguishes measured, user-supplied, public, and synthetic data.
- [ ] A content hash is described only as an identity/integrity check, never as proof that measurements are authentic.

### 3. Plug-in compatibility
- [ ] The plug-in boundary is documented with a minimal working example.
- [ ] Invalid plug-ins fail with actionable errors and do not crash unrelated reporting.
- [ ] Inputs and outputs are validated at the boundary, including timestamps, dimensions, units, and finite numeric values.
- [ ] The core simulation can run with the built-in implementation and with a replacement plug-in without source edits.
- [ ] Plug-in identity, version, configuration, and input provenance appear in the run manifest.
- [ ] Only trusted Python plug-in code is loaded; importing a plug-in is treated as code execution.

### 4. Simulation correctness and reproducibility
- [ ] A fixed seed produces repeatable synthetic inputs and repeatable outputs where determinism is promised.
- [ ] Energy and water balances are checked within documented numerical tolerances.
- [ ] Equipment power, storage capacity, inventory bounds, and minimum operating constraints are enforced.
- [ ] Infeasible actions are rejected or explicitly reported rather than silently clipped without an audit trail.
- [ ] Baselines include simple policies; perfect-foresight results are labeled as an optimistic reference, not a deployable forecast.
- [ ] Reports expose unmet demand and constraint violations, not only favorable aggregate scores.

### 5. Forecast evaluation
- [ ] Evaluation uses chronological rolling-origin splits; future observations never leak into training or feature construction.
- [ ] Baselines are evaluated on the same timestamps and input availability as candidate models.
- [ ] Metrics are reported by target and horizon, with sample counts and missing-data coverage.
- [ ] Candidate improvements are compared against a baseline on held-out periods.
- [ ] A trained model is not automatically promoted to operational use merely because an offline metric improves.
- [ ] Forecast uncertainty or limitations are made visible to downstream dispatch.

### 6. Readiness and safety boundaries
- [ ] Missing required site configuration, stale telemetry, invalid units, or failed quality checks cause a fail-closed result.
- [ ] Input completeness, model quality, engineering approval, and field commissioning are separate statuses.
- [ ] A simulation or recommendation is never represented as a PLC write or actuator command.
- [ ] No actuator writes are enabled by this acceptance checklist.
- [ ] Field use requires independent engineering review, site-specific safety limits, and validation against measured operation.

### 7. Release evidence
- [ ] Unit and regression tests pass in CI.
- [ ] A clean synthetic end-to-end run is exercised in CI or a documented reproducible release check.
- [ ] The report includes input manifest, configuration, random seed (if applicable), software revision, and output summary.
- [ ] Known limitations and unsupported operating conditions are documented.
- [ ] Release notes distinguish code changes from newly acquired real-world evidence.

## Suggested evidence bundle

For each candidate release, retain:
1. Test and CI result links.
2. The exact command and software revision used.
3. A synthetic run report and its manifest.
4. Data-contract validation output for any supplied real dataset.
5. Baseline-versus-candidate forecast and dispatch metrics.
6. A list of unresolved safety, data-quality, and deployment gaps.

## Status vocabulary

Use these terms precisely:
- **Demonstrated:** the documented example ran under the stated conditions.
- **Tested:** an automated or manual test exercised the named behavior.
- **Backtested:** a model was evaluated on historical data with documented split rules.
- **Site-validated:** the behavior was checked against appropriate measured site evidence and reviewed by qualified engineers.
- **Operationally commissioned:** the site owner and responsible engineers approved the complete deployment process.

Passing synthetic tests alone does not establish site validation or operational commissioning.
