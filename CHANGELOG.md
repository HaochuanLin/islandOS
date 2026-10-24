# Changelog

Notable project changes are recorded here. This is a research prototype; versioned releases are verification bundles, not site-operation approvals.

## Unreleased

- Added a dependency-free forecast plug-in contract with strict hourly timestamp and numeric-value validation.
- Added a rolling-origin backtest harness for trusted third-party forecast plugins and a dispatch-compatible JSON report.
- Added an optional PyTorch LSTM experiment and multi-series comparison against gradient boosting and seasonal baselines.
- Added pinned Docker runtime dependencies and release-candidate verification with test, dependency-audit, container-smoke, checksum, and provenance-manifest steps.
- Kept live plant control, automatic model promotion, and site-readiness certification out of scope.
