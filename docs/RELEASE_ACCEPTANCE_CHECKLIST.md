# Release and deployment acceptance checklist

Use this checklist for a tagged release or a deployment change. A successful code workflow is not proof that a hosted demo is reachable, that a model is physically accurate, or that a site is safe to operate.

## 1. Identify the exact source

- [ ] Record repository, branch, full commit SHA, and intended version.
- [ ] Confirm the release commit is on the intended product history; do not merge unrelated pilot/scenario history merely to collect files.
- [ ] Review the complete diff from the previous release.
- [ ] Confirm no credentials, private site records, or unlicensed datasets are included.

## 2. Verify software

- [ ] Required GitHub Actions checks completed successfully for the exact release SHA.
- [ ] Record the test command and CI run URL.
- [ ] Re-run the documented core test command in a clean environment when preparing a consequential release.
- [ ] Exercise representative valid, malformed, missing, non-finite, and infeasible inputs.
- [ ] Parse generated JSON/CSV outputs and verify their schema, units, time alignment, and provenance.
- [ ] Confirm deterministic fixtures remain reproducible where determinism is expected.

## 3. Verify data and scientific claims

- [ ] Label every input as measured, public reanalysis, modeled, or synthetic as appropriate.
- [ ] Record data source, source version, retrieval time, licence, units, timezone, frequency, coverage, and missingness.
- [ ] Use chronological holdout or rolling evaluation for forecasting; do not randomly shuffle time series.
- [ ] Compare forecast candidates against simple persistence/seasonal baselines.
- [ ] Report raw service metrics and limitations, including negative or inconclusive results.
- [ ] Do not describe synthetic benchmark success as field validation or proof of real-world benefit.

## 4. Deploy and recover

- [ ] Follow the documented clean-install/deployment instructions.
- [ ] Check hosted-service availability separately from GitHub CI.
- [ ] Confirm health checks and user-facing failure messages work.
- [ ] Verify configuration and secrets are supplied through the hosting platform, not committed to Git.
- [ ] Document the previous known-good version and rollback procedure.
- [ ] Record deployment time, operator, version, health result, and any incident.

## 5. Site or physical-operation gate

This section is mandatory before any field-operation claim and cannot be satisfied by code-only tests.

- [ ] Site owner/operator authorization is documented.
- [ ] Qualified engineering review covers equipment limits, energy/water balance, sensor units, stale/missing data, and failure modes.
- [ ] Recommendations are tested in read-only shadow mode against actual operation before considering control integration.
- [ ] Independent safety/cybersecurity review and operator sign-off are recorded.
- [ ] No PLC/actuator writes are enabled without a separately approved change and site-specific safety process.

## 6. Publish the evidence

- [ ] Tag/release notes identify the commit, tests, known limitations, and breaking changes.
- [ ] Link the CI run and relevant experiment reports.
- [ ] Update the engineering maturity roadmap only where new evidence satisfies a stated acceptance criterion.
- [ ] If a gate is blocked by site data, credentials, access, or operator approval, record the dependency rather than inventing evidence.

## Release record

- Version:
- Commit SHA:
- CI run URL:
- Deployment environment:
- Test/report links:
- Known limitations:
- Rollback version/procedure:
- Site approval (if applicable):
