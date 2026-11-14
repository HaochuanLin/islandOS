# IslandOS next delivery cycle — stages G to K

**Integration baseline:** `main`, after the numbered engineering stages 1–10 foundation.
**Purpose:** turn the existing software foundation into a concise, evidence-backed customer demonstration. These stages extend existing modules; they do not restart the earlier A–F or numbered 1–10 workstreams.

## What is already present and must not be rebuilt

- Stage 2 data onboarding, site workspace, asset records and provenance.
- Stage 3 model-agnostic multi-signal forecast bundles, chronological replay, metrics and empirical uncertainty bands. Built-in candidates are statistical baselines.
- Stage 4 forecast-led battery/diesel/grid coordination, optional flexible-load coupling, RO demand coupling and service-equivalence checks. The search is bounded and is not a global optimum.
- Stage 5 customer-entered economics screening.
- Stage 6 React + TypeScript console foundation; this is not yet a complete customer decision workflow.
- Independent continuous flexible-load tariff LP and seasonal-naive tariff baseline from the SIC reference assessment.

## Stage G — Evidence-gated ML forecasting

**Objective:** add and benchmark optional ML candidates without removing transparent baselines.

- Add a Random Forest candidate behind the existing `ForecastCandidate` interface.
- Keep persistence/seasonal-naive, recent-mean and linear-trend candidates.
- Use identical chronological rolling-origin folds and report MAE, RMSE and WAPE where defined.
- Promote a candidate only when it passes the same input/output contract and demonstrates lower error on the same held-out folds.
- Keep model/data provenance and the no-site-validation boundary explicit.

**Exit gate:** automated tests pass; the model can be explicitly selected and compared; the public demo does not imply that it was trained on UK-DALE or LCL unless the exact dataset is obtained, licensed/verified and reproducibly processed.

## Stage H — Device-level load flexibility

**Objective:** move beyond aggregate flexible kW toward equipment-aware tasks.

- Define critical, semi-flexible and fully flexible load classes.
- Model device identity, rated/min/max power, required energy or duration, earliest start, latest finish, minimum run, interruptibility, priority and availability.
- Protect critical loads as hard constraints.
- Enforce each flexible task's energy, time window and run constraints; reject infeasible schedules rather than silently shedding required service.
- Keep the existing continuous tariff LP as a simple mode; use a mixed-integer formulation only where discrete device operation requires it.

**Exit gate:** unit tests prove task energy conservation, time-window compliance, power bounds, critical-load protection and explicit infeasibility. Any aggregate approximation is labelled as such.

## Stage I — Multi-resource coordination quality

**Objective:** strengthen the existing forecast-to-dispatch path, not replace it.

- Feed selected forecast candidates and uncertainty envelopes into the current shared energy accounting and optimizer.
- Connect device-level flexible tasks to battery, diesel, grid import/export, PV/wind and optional RO demand.
- Add common baseline-vs-optimized comparisons with equal service, explicit unmet demand, peak import, fuel use, renewable curtailment and operating cost.
- Add stress cases for forecast error, grid outage, low renewable output, demand spikes and equipment derating.
- Add tariff and demand-charge assumptions only when their billing basis is explicit.

**Exit gate:** all candidate schedules are replayed through the same physical accounting; service constraints are visible; economic comparisons are like-for-like; deterministic regression tests pass. Do not describe a bounded heuristic as globally optimal.

## Stage J — Customer decision workflow and demo

**Objective:** make one coherent journey understandable to a non-technical customer and judge.

- Prioritize the public Streamlit path rather than replacing the application with a new frontend.
- Provide one guided flow: import/inspect data → configure site/assets → forecast → compare operating strategies → review economics → export an auditable report.
- Show model identity, backtest metrics, assumptions, constraints, feasibility, baseline and recommendation rationale.
- Keep React as a foundation until a full-stack deployment is justified and testable.
- Use a clearly labelled synthetic demonstration scenario if no authorized site data is available.

**Exit gate:** a fresh user can complete the demo without developer intervention; every displayed result can be traced to inputs and assumptions; synthetic data is visibly labelled.

## Stage K — Verification, release, PDF and video

**Objective:** freeze a credible submission/demo baseline quickly.

- Run the full CI suite, local quick-start and public demo smoke test.
- Verify README, docs, screenshots, app labels and PDF claims against the merged default branch.
- Capture evidence for implemented, experimental and planned features separately.
- Prepare a 2–3 minute video: customer problem, data input, forecast, constraints, strategy comparison, economics, audit/export, honest limitations.
- Keep field validation, customer savings, production deployment, universal plug-and-play and autonomous control as non-claims unless independently evidenced.

**Exit gate:** clean mainline, passing CI, working public demo, consistent PDF, reproducible video scenario and no unsupported performance claims.

## Fast-track order

1. Finish Stage G candidate tests and merge only after CI passes.
2. Implement Stage H's minimal but correct device task model and tests.
3. Connect H to the existing Stage I dispatch path; add only the highest-value stress/economic checks.
4. Polish the Streamlit customer journey and capture the video scenario.
5. Freeze the PDF after the actual mainline merge state is verified.

The five stages are deliberately scoped for a demonstrable research prototype. They do not authorize live equipment control or replace site engineering and safety acceptance.
