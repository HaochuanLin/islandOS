# GSC judge walkthrough (Phase 1 frontend)

Purpose: a five-minute live path through the Streamlit demo, with the exact claims to make and the
claims to refuse. This walks the **public** menu only. The local customer and site workspaces are
not part of the judged demo.

- Entry point: `https://islandos.streamlit.app/` or local `http://127.0.0.1:8611/`
- Public pages: Workspace, Decision dashboard, Joint resource optimizer, Device flexibility planner,
  Rolling horizon lab (experimental)
- Default data: synthetic and labelled as synthetic on every customer page
- Verified: 2026-11-24, local Streamlit on `127.0.0.1:8611`, browser viewport 1280×960. The three
  customer pages rendered without exceptions; the device page's application-views JSON downloaded
  as `islandos_device_flexibility_report.json` (7,429 bytes, `schema_version: 3`).

## Five-minute route

### 0:00–0:30 — Open on the Workspace

Start at the landing page, not the dashboard. Say one sentence:

> "IslandOS is an offline planning and screening prototype for energy-constrained sites. It forecasts,
> coordinates energy and water, and shows the trade-offs; it does not control equipment."

Point to the page header's four lines: **Answers**, **Data**, **You can conclude**, **Limits**. This
pre-empts the "is this a product or a demo?" question.

Do not tour all eight workspace sections. Use the page as orientation, then move.

### 0:30–1:45 — Decision dashboard

Open **Decision dashboard**. The default is synthetic; the page says so twice (banner and provenance).

Read the Decision snapshot:

- Recommended policy: **Battery First**
- Estimated 24 h energy cost: **17.93 USD**
- Unmet energy: **0.00 kWh**
- Modeled cost difference vs grid-first: **18.37 USD**

Then say:

> "This is a bounded two-policy comparison under identical service, not a global optimum and not a
> measured saving. The 18.37 USD is the modeled gap between two dispatch priorities."

Point at **Service equivalence: Passed** and **Independent dispatch audit: Passed**. Explain that the
investment screen below is a separate customer-entered annual screen, not an annualisation of this
24-hour run: NPV 21,302 USD, simple payback 6.0 years, discounted payback 8.5 years, break-even
annual energy saving 32,825 USD. The page labels those bills/O&M/CAPEX as synthetic demonstration
figures.

Do not call the NPV or payback a customer quote. Do not turn 18.37 USD into "annual savings".

### 1:45–3:00 — Joint resource optimizer

Open **Joint resource optimizer**. Read the top three identifiers before any chart:

- Canonical run id (varies per session; read it from the page)
- Manifest SHA-256
- Evidence SHA-256

Then say:

> "This is one pipeline: site history → model selection → aligned forecasts → battery/diesel schedule
> search. The run has a manifest and evidence digest, so a reviewer can tell which inputs produced it."

Point at **Status: ready for human review** and **Device write: not authorized**. The physical audit
replays four scenarios; it is not site validation or a safety certificate.

Scroll to **Annual operating basis**. Say:

> "Annual figures are withheld until an equal-days assumption is declared. One simulated day is not a
> year, and this page will not pretend otherwise."

Do not declare the annual assumption just to make a number appear. The withheld state is the honest
demo.

### 3:00–4:00 — Device flexibility planner

Open **Device flexibility planner**. The page is synthetic and says so.

Read the four summary metrics:

- Critical energy protected: **72 kWh**
- Flexible task energy: **17 kWh**
- Scheduled task energy charge: **13.77 USD**
- Peak task demand: **6.0 kW**

Then scroll to the comparison:

- Grid import: **103.2 kWh**
- Replayed system energy cost: **15.44 USD**
- Critical unmet: **0.00 kWh**
- Flexible load shed: **0.00 kWh**

Say the distinction explicitly:

> "13.77 USD is the charge for the scheduled tasks only. 15.44 USD replays the same schedule through
> the whole site, including existing load and shared PV, wind, battery, grid and diesel. The two totals
> are deliberately different; they are not a contradiction."

If asked about the benchmark, point at the caption: the reference is an earliest-feasible heuristic,
not historical operation and not a global optimum.

Optionally click **Export application views JSON**. This is the auditable artifact a reviewer can
open in the contract viewer; it is not a new calculation.

### 4:00–5:00 — Close on limits

Return to the dashboard or stay on the device page and close with three sentences:

> "Everything here is offline screening on declared assumptions. The default is synthetic; uploaded
> data is session-only and hashed, not retained as a site workspace. The next step is a written site
> data agreement and a shadow trial, not device control."

Then point to the demo and repository QR on the proposal's p5 or back cover if the judge does not want
to type the URL.

## Judge questions and short answers

**"Are these measured savings?"**
No. They are modeled screening results under declared assumptions. The dashboard's 18.37 USD is a
24-hour policy gap under identical service, not a bill or a guaranteed saving. The annual screen is
customer-entered, synthetic demonstration figures.

**"Is this a digital twin?"**
No. It is an offline planning and screening prototype. It does not connect to live telemetry, write
setpoints, dispatch equipment or certify safety.

**"Why are there two different costs on the device page?"**
13.77 USD is task-only energy charge. 15.44 USD is the whole-site replay including existing load and
shared generation/storage/grid/diesel. The page now states this; the numbers are not supposed to
match.

**"Can it run on a real site's data?"**
The page accepts a canonical hourly CSV; uploads are session-only and hashed. The default is
synthetic. Real use needs a written data agreement, column/unit validation and a shadow period before
any operational claim.

**"Why is the annual projection blank?"**
Because one simulated day is not a year. The optimizer withholds annual figures until the reader
declares an equal-days assumption. The dashboard's investment screen takes customer-entered annual
bills; it does not annualise the 24-hour run.

**"Do you have site permission or a shadow trial?"**
No. Site selection and written permission are Phase 2 gates; the shadow trial is planned, not
completed. Do not say "permission obtained" or "shadow completed".

**"What about RBAC, audit and multi-tenancy?"**
Not in this Phase 1 demo. The Streamlit app has no application-level auth/RBAC; the local reference
API is loopback-only. Production identity, retention and audit are Phase 2 gates, not claimed here.

**"What is the hardest constraint?"**
Service equivalence and critical unmet load, not cost. A cheaper schedule that fails the service gate
is not a win. The pages withhold savings when the gate fails.

**"What would you do with the next funding?"**
Site permission and data agreement, then a shadow trial with a pre-registered acceptance rule. Not
more dashboard surface area.

## Do-not-say list

- "Measured savings", "customer bill", "guaranteed payback", "site-validated forecast"
- "Digital twin", "autonomous dispatch", "device control", "production-ready"
- "Permission obtained", "shadow trial completed"
- "Global optimum" for either the two-policy comparison or the device heuristic
- "Zero unmet load proves water safety"; it is a modeled result under this scenario

## Fallback if the live page is slow

1. Stay on the page; Streamlit's first render can take a few seconds.
2. If a chart fails, do not debug it on stage. Use the downloaded JSON/CSV artifact and the page's
   metrics, and say which artifact you are showing.
3. If the network drops, use the proposal PDF and the QR; do not claim live numbers you did not see.
4. Do not run the Python test suite and the Streamlit demo at the same time on a low-memory laptop;
   the full suite can starve the browser process. Run tests before the demo, then stop them.
