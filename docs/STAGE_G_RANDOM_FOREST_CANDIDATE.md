# Stage G — Evidence-gated Random Forest candidate

## Decision

IslandOS already has a model-agnostic prediction engine, chronological
rolling-origin replay, baseline candidates, signal provenance, uncertainty
bands and a fail-closed forecast-bundle interface. Stage G therefore adds a
candidate to that existing engine; it does not replace the engine or remove
transparent baselines.

## Candidate

`islandos_core/random_forest_candidate.py` provides an opt-in
`RandomForestCandidate` with 100 trees by default, deterministic random
state, lag features, seasonal rolling mean and cyclic interval features.
It implements the existing `ForecastCandidate` protocol and can be registered
with `PredictionEngine.register(...)`.

The candidate imports scikit-learn lazily. Install the repository's pinned
scikit-learn version from `requirements-ci.lock` or add the same version to
the local environment before enabling it. The default runtime does not load
or require this optional candidate.

## Evaluation rules

- Keep persistence/seasonal-naive, recent-mean and linear-trend baselines.
- Compare candidates on identical chronological rolling-origin folds.
- Select Random Forest only when it is explicitly requested and passes the
  existing input/output contract; automatic selection remains based on
  measured replay error.
- Report MAE, RMSE and WAPE where defined. Do not transfer metrics from a
  different dataset or project.
- The current candidate protocol has no timestamp/calendar-feature argument.
  Its seasonal features use interval indices. A later interface revision may
  add timestamp-derived hour, weekday and month features without breaking
  existing candidates.
- This implementation is not trained on UK-DALE or Low Carbon London data.
  No original dataset or pretrained model was supplied to IslandOS.

## Reference-data provenance

A supplied project report describes 15,615 hourly observations from 139
households in the Low Carbon London dataset and a 100-tree Random Forest.
A separate message identified UK-DALE. The discrepancy is unresolved, so
neither dataset is treated as the confirmed source for the reported metrics.
The reported R² and MAE are not IslandOS results and must not appear as such.

## Validation

```bash
pytest -q tests/test_random_forest_candidate.py tests/test_prediction_engine.py tests/test_forecast_service.py
```

The tests validate candidate determinism, protocol integration, chronological
evaluation, finite output and insufficient-history rejection. They do not
establish field accuracy or customer savings.
