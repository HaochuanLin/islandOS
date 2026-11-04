# Changelog

Notable project changes are recorded here. This is a research prototype; versioned releases are verification bundles, not site-operation approvals.

## Unreleased

- Added an integrated deterministic microgrid energy–water model covering PV, wind, essential demand, battery SOC, grid imports, diesel backup, renewable-only scheduled RO consumption, curtailment, water production, tank inventory, and explicit unmet-service metrics. Added regression tests for energy/water conservation and operating limits.
- Added a seeded synthetic benchmark CLI that compares no-RO and renewable-only RO policies on paired inputs and exports provenance-labelled JSON and hourly CSV evidence.
- Refocused the README on IslandOS as a generic predictive multi-resource decision platform; Nan’ao is described only as an experimental pilot scenario.

- Added a dependency-free forecast plug-in contract with strict hourly timestamp and numeric-value validation.
- Added a rolling-origin backtest harness for trusted third-party forecast plugins and a dispatch-compatible JSON report.
- Added an optional PyTorch LSTM experiment and multi-series comparison against gradient boosting and seasonal baselines.
- Added pinned Docker runtime dependencies and release-candidate verification with test, dependency-audit, container-smoke, checksum, and provenance-manifest steps.
- Kept live plant control, automatic model promotion, and site-readiness certification out of scope.
