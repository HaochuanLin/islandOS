# Phase 4 — Customer decision dashboard

## Purpose

Translate validated inputs, baseline-gated forecasts, and offline resource-dispatch comparisons into a customer-readable decision view. The dashboard answers five practical questions: what is the modeled energy cost, what conditions are forecast, which dispatch policy is recommended, whether the comparison preserves equivalent service, and how the policies behave under deterministic stress cases.

## Current increment

The Streamlit multipage dashboard at `pages/05_Customer_Decision_Dashboard.py`:
- builds a reproducible synthetic 168-hour input history and forecasts a 24-hour horizon with the Phase 2 baseline-gated engine;
- passes aligned, unit-labelled forecasts through the Phase 3 forecast-to-energy adapter;
- compares the two existing physical dispatch priorities with the shared energy-system simulator;
- gates modeled cost differences on service equivalence against the grid-first reference;
- replays both policies across forecast-envelope and grid-outage stress cases;
- exposes forecast model IDs, holdout metrics, input-history SHA-256, and a downloadable JSON decision report;
- provides a separate lifecycle investment screen using customer-entered annual bills, CAPEX, O&M, replacement, residual value, and discount-rate assumptions.

## Customer-facing decision logic

- **Cost:** modeled energy cost and grid-import energy are displayed with the currency label supplied by the user.
- **Forecast:** PV, wind, essential load, and tariff point forecasts are shown for the next 24 hours.
- **Recommendation:** the selected policy and objective weights are disclosed.
- **Savings:** a modeled cost difference is shown only if service is equivalent; otherwise the dashboard withholds the savings figure.
- **Reliability:** unmet load, critical unmet load, and physical-audit status are shown for each deterministic stress replay.
- **Investment:** NPV, simple/discounted payback, break-even annual saving, and ±20% annual energy-saving sensitivity are shown only when service equivalence passes.

## Evidence and limitations

The default scenario is synthetic. The 24-hour forecast is generated from 168 synthetic hourly observations, so its holdout metrics do not establish site forecast accuracy. The optimizer evaluates two explicit dispatch priorities, not a global search over hourly setpoints. Stress envelopes are deterministic and have no assigned probabilities or calibrated joint coverage. The model does not perform AC power flow, protection, voltage/frequency, equipment certification, or safety approval. The dashboard is offline decision support only: it has no live telemetry, device write path, verified customer savings, or automatic control.

## Exit gates for the remaining Phase 4 work

- Replace synthetic-only defaults with a clearly provenance-labelled site-data workflow.
- Expand the current simplified investment screen to include validated fuel, demand-charge, escalation, degradation, financing, tax, and lifecycle assumptions where relevant.
- Add a comparison export that includes all assumptions, source hashes, model versions, and service-equivalence checks.
- Conduct usability review with non-technical users and verify that risk and uncertainty labels are understood.


## Customer-supplied history

The follow-up CSV onboarding increment is documented in [Phase 4 — Customer data onboarding](PHASE4_CUSTOMER_DATA_ONBOARDING.md). It adds a strict hourly input adapter while retaining the synthetic example as the default; see the linked document for the schema and privacy boundary.


## Investment economics

See [Phase 4 — Customer investment economics](PHASE4_CUSTOMER_INVESTMENT_ECONOMICS.md) for formulas, required inputs, service-equivalence gate, sensitivity assumptions, and limitations. The investment screen does not annualize a 24-hour dispatch result; it requires explicit annual customer bills and supplier/customer cost assumptions.
