# Stage K — release verification and 2–3 minute demo runbook

## Release boundary

The Stage G–J changes are a simulation-first planning prototype. They do not
establish field validation, verified customer savings, a production SaaS
deployment, live SCADA/PLC writes, autonomous operation, or universal
plug-and-play compatibility.

Before recording or submitting:
- Confirm the latest default-branch commit and pull-request merge state.
- Confirm all required CI checks pass on that exact commit.
- Open the public Streamlit app in a clean browser session.
- Confirm synthetic-data labels remain visible.
- Run the device flexibility page and the forecast-led joint-resource page.
- Export a CSV and verify that its assumptions and outputs are traceable.
- Capture the GitHub commit/PR and the running public app as separate evidence.

## Suggested 2–3 minute video

**0:00–0:20 — Customer problem**
"Remote and energy-constrained sites often have variable renewable generation,
high or volatile electricity costs, and equipment with different service
priorities. IslandOS helps operators compare operating decisions before acting."

**0:20–0:40 — Site data and assumptions**
Show the site workspace or forecast-led page. Point out the synthetic-data
label and explain that a real deployment would use authorized site history,
asset ratings and tariff data.

**0:40–1:05 — Forecast**
Show the selected forecast model, chronological backtest metrics and the
forecast horizon. Explain that candidates are compared against statistical
baselines and that the demo is not a site-calibrated accuracy claim.

**1:05–1:35 — Device flexibility**
Open the device-level planner. Show critical circuits reserved first, the
semi-flexible ice-making block and the fully-flexible pumping intervals.
Point out the operating windows, priority order and infeasibility rejection.

**1:35–2:05 — Multi-resource decision**
Show the like-for-like tariff-aware versus earliest-feasible comparison.
Point out grid import, modeled cost, peak import, critical unmet energy and
flexible load shedding. Explain that both plans use the same device service
requirements and the same physical energy accounting.

**2:05–2:30 — Audit and limits**
Export the per-device hourly CSV, including the reference replay series. Close with: "This is an auditable planning prototype using
synthetic demonstration inputs. It does not send commands to equipment, and
the displayed cost is not measured customer savings. The next validation step
is a supervised pilot using authorized site data and engineering review."

## Claim checklist

Safe claims when the relevant code is present on the demonstrated commit:
- optional Random Forest forecasting candidate with automated tests;
- equipment-aware critical/semi-flexible/fully-flexible task representation;
- deterministic tariff-aware scheduling under declared windows and power limits;
- critical-load protection and explicit infeasibility handling in the task scheduler;
- task schedules passed into the shared PV/wind/grid energy accounting;
- offline scenario comparison and CSV audit export.

Do not claim:
- the previous teammate experiment's R²/MAE as IslandOS metrics;
- validated field forecast accuracy or measured customer savings;
- globally optimal schedules;
- live telemetry integration or device actuation;
- safety certification or autonomous operation;
- production-ready deployment at arbitrary sites.

## Final checks

Run the repository's complete CI suite on the exact release commit. The CI
workflows also compile Python sources, execute integration examples, build the
container smoke test and package the Windows gateway. A passing CI suite proves
the tested software checks passed; it is not a substitute for site acceptance.
