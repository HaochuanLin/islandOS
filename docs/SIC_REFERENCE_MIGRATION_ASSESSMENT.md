# SIC reference repositories: IslandOS migration assessment

## Purpose

This document records what was assessed from the SIC_backend and SIC_Frontend
reference repositories, what has been adopted as an independent IslandOS
implementation, and what should deliberately not be migrated.

The goal is to improve customer-relevant forecasting, operating economics,
resource coordination, and product usability without replacing working IslandOS
modules or importing an unverified third-party codebase.

## Executive decision

- **Do not fork or wholesale-copy either repository.**
- **Do not replace Streamlit with React at this stage.**
- **Do not replace IslandOS forecasting interfaces with the SIC Random Forest.**
- Adopt the narrow tariff-aware flexible-load scheduling pattern as an
  independently implemented, tested IslandOS module.
- Add a branch-only Streamlit page for editable, equal-energy tariff scenarios;
  do not claim it is live in the hosted app before merge and redeployment.
- Reassess dashboard and service architecture only after the decision core has
  stable, customer-relevant outputs and a defined multi-site deployment need.

The SIC repositories did not expose a confirmed root license during the review.
No third-party source files have been copied into IslandOS. Confirm licensing or
obtain permission before considering any literal code reuse.

## Component-by-component assessment

| SIC area | What it provides | IslandOS comparison | Decision |
|---|---|---|---|
| Demand-response optimizer | Shifts flexible electrical demand toward lower-price periods with power constraints | IslandOS already has flexible-load simulation and multi-objective dispatch experiments, but a small standalone tariff-only LP is a useful complementary primitive | **Adopted independently** in `optimization/price_aware_load_optimizer.py` |
| Forecasting / Random Forest | 24-hour load forecast using calendar and weather features | IslandOS already has a forecast plug-in contract, provenance hashing, model identity checks, baseline experiments, forecast evaluation, uncertainty analysis, and dispatch backtests | **Do not migrate model code**; benchmark candidate models against IslandOS gates if useful |
| Dashboard KPI and charts | Consumption, forecast, cost, alerts, and user overview | IslandOS already has a public Streamlit application and audit charts; SIC frontend data inspected was mock/demo data rather than proof of a live integrated API | **Borrow UX patterns later**, not frontend source |
| Mock frontend data | Deterministic synthetic load, forecast, alert, and summary values | IslandOS already labels synthetic inputs and maintains data-provenance boundaries | Do not copy; retain IslandOS provenance conventions |
| Django REST API | Separate backend endpoints for authentication, forecasting, demand response, and analytics | Not required for the current single-app public prototype and decision-core development | Defer until multi-user/multi-site API requirements are real |
| User authentication and roles | Admin/staff/user access patterns | Not central to current single-user demo or optimizer correctness | Defer until a defined customer deployment model exists |
| Notifications | Alert and notification structures | IslandOS can later add alert severity, acknowledgement, and traceable event records | Design from IslandOS signal and audit contracts when needed |

## What was implemented in this assessment cycle

### Price-aware continuous flexible-load optimizer

File: `optimization/price_aware_load_optimizer.py`

- Minimizes tariff cost while delivering an exact requested energy quantity.
- Uses kW power limits and kWh energy accounting with configurable interval
  duration.
- Supports a per-interval power budget and a boolean operating-availability
  window.
- Reports infeasible requirements explicitly instead of silently relaxing
  required service.
- Rejects non-finite, malformed, boolean, and dimensionally inconsistent inputs.
- Returns an auditable schedule, total energy, optimized cost, solver status,
  and explicit model-scope limitations.
- Optionally compares against a baseline profile with the same total energy,
  respecting the load rating and operating window; reports absolute and
  percentage cost differences when mathematically meaningful.

This is a continuous linear program, not a complete equipment scheduler. It
does not model startup costs, minimum on/off times, discrete operating states,
ramp rates, thermal/process dynamics, network power flow, or equipment
protection. A later mixed-integer model must be justified by an actual device
use case and separately tested.

### Transparent tariff forecast baseline

File: `islandos_core/tariff_forecasting.py`

- Repeats the most recent 24-hour tariff profile for the requested forecast
  horizon; preserves negative prices.
- Requires timezone-aware, strictly ordered hourly observations.
- Records a SHA-256 digest of the supplied history and explicit future
  timestamps.
- Evaluates MAE, RMSE, and signed bias through contiguous rolling-origin
  replay, using only data available before each forecast block.

This is a seasonal-naive benchmark, **not a trained AI model, a market-price
prediction claim, or evidence of forecast skill**. More advanced forecasting
methods should be compared against this baseline using representative,
chronological holdouts before promotion.

### Interactive cost-comparison workflow

The feature branch adds a Streamlit page for editable or uploaded scenario
profiles and optional historical tariff CSV input. It connects the tariff
baseline to the optimizer, presents an equal-energy cost comparison, shows
the schedule and row-level audit, and exports provenance metadata.

The default profile is synthetic. User-uploaded data is not independently
verified. The current calculation covers energy charges only; it does not
include demand charges, taxes, fixed fees, or whole-bill validation. The page
is not part of the public hosted app until the feature is merged and redeployed.

## Delivery status and next migration stages

### Stage A — Tariff baseline and narrow optimizer

- Implemented the continuous-load LP and seasonal-naive hourly tariff baseline.
- Added malformed-input, infeasibility, negative-price, equal-energy comparison,
  timestamp, metric, and rolling-origin replay tests.
- Connected forecast output to the optimizer in the feature-branch app.
- All seven PR workflows passed on head
  `08537f0ad743353c5b4974dd5cd7b7b289076e26`.

**Status:** implementation and automated validation are complete on the
feature branch. Human review is still outstanding; the PR remains a draft and
has not been merged. Passing CI does not establish field performance.

### Stage B — Strengthen customer economics

- The optimizer supports a like-for-like baseline profile with equal total
  energy, and tests both the cost difference and invalid baseline rejection.
- The experimental page records the tariff source, forecast method, input
  digest, display-only currency label, interval duration, power budget, and
  baseline load.
- It presents energy-charge comparisons, the schedule, and a CSV audit.
- Remaining work: define billing-period metadata and a defensible treatment of
  demand charges, fixed fees, taxes, and tariff-specific billing rules before
  claiming whole-bill savings.
- Keep scenario differences explicitly separate from verified customer savings.

**Exit:** a reviewer can trace the cost difference to the tariff source,
currency, interval, billing assumptions, energy requirement, power limits,
baseline profile, and schedule.

### Stage C — Extend equipment constraints only when justified

- Add minimum-run and startup constraints for equipment that needs them.
- Consider mixed-integer optimization only when the operating model requires
  discrete on/off decisions.
- Preserve service reliability and equipment constraints as hard constraints.

**Exit:** each new constraint has a real equipment interpretation and tests.

### Stage D — Improve multi-signal forecasting through IslandOS interfaces

- Keep the existing IslandOS forecast plug-in contract and provenance controls.
- Compare candidate algorithms against transparent baselines and time-aware
  backtests.
- Add new forecast targets through explicit, unit-aware contracts rather than
  copying the SIC single-load model.

**Exit:** a candidate is promoted only with reproducible out-of-sample evidence.

### Stage E — Improve customer presentation and deployment

- Borrow proven dashboard information architecture, not mock data or unneeded
  frontend infrastructure.
- Continue using Streamlit while the product is a research and demonstration
  prototype.
- Consider React/Django only when multi-user, multi-site, API, and operational
  deployment requirements justify the additional service boundary.

**Exit:** the architecture responds to a demonstrated customer workflow rather
than technology fashion.

## Product and safety boundaries

- Synthetic examples are not measured site data.
- Cost comparisons are not guaranteed savings.
- A feasible mathematical schedule is not proof of plant feasibility.
- This module does not send commands to devices.
- Recommendations remain advisory and subject to site-specific engineering
  review and equipment-native protection.
