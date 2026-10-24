# Plug-and-play energy decision platform roadmap

## Product direction

IslandOS is being developed toward a modular energy-and-water decision platform that can be demonstrated in a browser and, later, installed on a local/on-premises computer. The browser demo is a presentation and review interface; the decision core should be independently runnable. The system should accept normalized live or recorded signals from instrument adapters, accept operator-entered planning assumptions, and produce explainable recommendations.

This is a software roadmap, not a claim that IslandOS is already ready for plant deployment. Current site measurements and physical equipment are not available. Do not block software engineering progress on obtaining them, and do not describe synthetic tests as field validation.

## Target architecture

1. **Presentation layer** — Streamlit demo, scenario setup, charts, decision explanation, CSV/report export.
2. **Decision core** — deterministic simulation and dispatch/recommendation logic with explicit inputs and outputs; no dependency on Streamlit UI state.
3. **Signal contract** — a documented, versioned normalized schema for timestamp, value, unit, quality/status, source, and freshness. Support simulated signals first, then recorded files and adapters.
4. **Site configuration** — validated configuration for equipment ratings, water demand/storage, energy/cost assumptions, operating limits, and enabled capabilities. Separate user-entered assumptions from measured signals.
5. **Adapters** — isolated connectors that translate a device/protocol payload into the normalized signal contract. Keep vendor/protocol code out of the decision core.
6. **Recommendation and audit layer** — recommended action, rationale, binding constraints, input/configuration snapshot, timestamp, and decision status.
7. **Deployment boundary** — repeatable local installation, health checks, logging, and clear offline behavior. The hosted website is not a dependency for local operation.

## Safety and operating boundary

- Default to **read-only recommendations**. Do not write to PLCs, switch equipment, or bypass native interlocks.
- Reject or flag missing, stale, malformed, out-of-range, or unit-ambiguous signals; fail closed instead of silently inventing values.
- Keep software recommendations separate from operator approval and equipment-level protection.
- Any future actuation requires separate site authorization, controls engineering, cybersecurity review, hardware-in-the-loop testing, and supervised commissioning. Passing software tests alone is insufficient.

## Delivery stages and acceptance criteria

### Stage 1 — Establish a trustworthy baseline
- Run the required workflows against the exact main commit.
- Keep the generic demo separate from scenario-specific research fixtures.
- Maintain reproducible test commands and explicit limitations.

**Exit:** current main checks pass; core tests are reproducible.

### Stage 2 — Make the decision core independently callable
- Identify the smallest stable input/output boundary around the existing simulation/dispatch logic.
- Add tests that call the core without importing or launching Streamlit.
- Preserve current app behavior while routing it through the same core functions.

**Exit:** core behavior can be tested and invoked independently of the web UI.

### Stage 3 — Define signals and configuration
- Document a versioned normalized signal schema with units, quality, timestamps, and freshness.
- Add validated example configuration for equipment and manually entered assumptions.
- Provide a simulator/fixture that emits virtual instrument readings.
- Add tests for stale data, missing fields, invalid units, and out-of-range values.

**Exit:** a simulated instrument and a manually configured site can pass through the same validated interface.

### Stage 4 — Explainable recommendation workflow
- Return recommendations with rationale, constraints, input/configuration identifiers, and a clear recommendation-only status.
- Make invalid/infeasible scenarios visible instead of displaying an apparently safe recommendation.
- Test the input → validation → decision → audit/export path end to end.

**Exit:** a user can trace each displayed recommendation back to the inputs and assumptions used.

### Stage 5 — Local/on-premises packaging
- Provide a clean installation path, sample configuration, health check, logging, and shutdown procedure.
- Verify the app and decision core work without relying on the hosted Streamlit site.
- Document OS/runtime requirements and the read-only boundary.

**Exit:** a clean-machine deployment can be repeated from the documented instructions.

### Stage 6 — Optional protocol adapters
- Add adapters only when a protocol/device use case is defined; keep each adapter independently testable.
- Begin with replayed/synthetic payloads and test disconnects, stale values, malformed messages, and recovery.
- Do not require physical site access to finish the software contract and simulator.

**Exit:** adapter tests prove correct normalization and failure handling. They do not prove physical sensor accuracy.

## Scorecard policy

Track separately:
- Core simulation and dispatch quality.
- Test coverage and reproducibility.
- Website usability and demo reliability.
- Signal schema and simulated adapter quality.
- Configuration and modularity.
- Local/offline deployment readiness.
- Decision explainability, auditability, and fail-closed behavior.
- Release engineering and documentation.
- Real-world operational validation.

The first eight dimensions can improve through code, simulated signals, and reproducible tests. Real-world operational validation remains explicitly **blocked / unverified** until authorized measured data or a supervised pilot exists; it is not a required deliverable for the software roadmap. Do not award field-validation credit for synthetic data.

## Immediate next implementation steps

1. Map the current `app.py` call path and identify existing reusable simulation/dispatch modules before refactoring.
2. Add a small core-level test that runs without the Streamlit interface.
3. Define the initial normalized signal model and virtual-instrument fixture.
4. Add validated configuration for operator-entered assumptions.
5. Add recommendation rationale and traceable audit output.
6. Add local deployment verification and adapter failure tests.

Prefer small pull requests with regression checks. Avoid a large rewrite or splitting files solely for appearance.


## No-real-data onboarding path

A user must be able to evaluate the software before receiving site measurements. The repository therefore provides a clearly labelled, deterministic synthetic bootstrap fixture:

```bash
python tools/generate_synthetic_site_csv.py --output build/synthetic_site_hourly.csv --hours 168 --seed 20261023
streamlit run app.py
```

Upload the generated CSV in the interactive app. It follows the app's hourly input schema and is useful for exercising upload validation, strategy comparison, and report export. The values are deliberately synthetic assumptions, not a site forecast, calibration data, or operational recommendation. A seed makes the generated fixture repeatable. The start timestamp is a naive local label; users must document the intended site timezone and interval semantics separately.

**Plug-and-play acceptance boundary:** no site data should be required to install the package, launch the demo, or test the workflow. Site-specific recommendations must still be blocked or clearly labelled as assumption-driven until equipment ratings, interval semantics, source provenance, units, operational limits, and site-approved safety constraints have been supplied and reviewed. Synthetic mode is for onboarding and software tests only.
