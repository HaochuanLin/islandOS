# IslandOS competition sprint: seven-day plan

## Target

Deliver a credible, reproducible research prototype for a student innovation competition. The deliverable is a working simulator plus an evidence package—not a claim of field deployment.

## The central claim

IslandOS investigates whether flexible reverse-osmosis (RO) desalination can absorb otherwise-curtailed renewable energy while respecting simplified operating and reservoir constraints in an isolated-island energy–water scenario.

Keep this claim narrow. Do not claim that the model is an operational controller, that Nan'ao has the modeled curtailment events, or that the scenario proves cost savings, emissions reductions, or reliability improvements.

## What exists and what the sprint must prove

- Existing: Python simulation models, a priority dispatcher, RO/reservoir dynamics, weather-data utilities, scenario experiments, regression tests, and a reproducible Nan'ao assumption-based event-energy scenario.
- New competition-facing layer: an interactive Streamlit dashboard for a seeded 24-hour synthetic trace.
- Required before submission: run the full test suite; check the dashboard against several parameter extremes; capture screenshots from a real run; report limitations; and package one reproducible benchmark with assumptions and outputs.

## Seven-day sequence

### Day 1 — Freeze scope and establish a clean baseline
- Agree on the one-sentence research question and system boundary.
- Run `python -m unittest discover -s tests -v`.
- Run the Nan'ao scenario with a fixed seed and retain its CSV/JSON outputs.
- Record current failures honestly; do not hide or silently delete failing tests.

### Day 2 — Make the demo runnable
- Install dependencies with `pip install -r requirements.txt`.
- Launch `streamlit run app.py`.
- Check at least three cases: default conditions, very low renewable generation, and high renewable generation.
- Verify the UI labels every input and result as synthetic / illustrative.

### Day 3 — Validate physics and software behavior
- Check the electricity balance and water inventory logic against the implementation.
- Test minimum-run violations, reservoir upper/lower bounds, zero-surplus cases, and backup-power accounting.
- Fix bugs before styling. Never tune the model solely to create a more attractive outcome.

### Day 4 — Produce fair comparisons
- Compare the existing dispatch policy with a simple baseline on the same input trace.
- Report the same metrics for each policy: renewable surplus available, surplus absorbed, RO water output, unmet water-demand indicator, backup energy, reservoir violations, and minimum-run violations.
- Add sensitivity cases for renewable availability, RO rated power, specific energy consumption, and reservoir capacity.
- Do not compare different weather traces or different assumptions as if they were an algorithmic improvement.

### Day 5 — Reproducibility and evidence
- Rerun all tests and fixed-seed experiments.
- Export the exact configuration, CSV/JSON outputs, and metric definitions.
- Keep raw generated results; do not edit numbers manually.
- Include a small limitations section next to each headline result.

### Day 6 — Submission materials
- Prepare a concise project summary, system diagram, methods, experiment table, limitations, and next validation steps.
- Capture screenshots from the running app and provide exact run commands.
- Make the repository easy for a reviewer to reproduce from a clean environment.

### Day 7 — Final audit
- Have each teammate independently try the run instructions.
- Check that every chart has units and every result has a data-source label.
- Remove unsupported claims and unfinished features from the pitch.
- Freeze the submission version and avoid risky last-minute architecture changes.

## Team roles

- **Energy/nuclear engineering lead:** define the research question, system boundary, operating constraints, and energy/water balance checks; challenge implausible assumptions.
- **Applied chemistry teammate:** review RO specific-energy assumptions, water-quality and pretreatment limitations, membrane flushing, intake/outfall, and what cannot be concluded without water-quality testing.
- **Software engineering teammate:** reproduce the setup, review code structure, tests, dependency and deployment behavior, and check data export and error handling.
- **AI-assisted implementation:** can accelerate code and documentation, but a team member must run every command, inspect outputs, and understand the key model assumptions before presenting them.

## Minimum reviewer-ready evidence package

1. Reproducible command and environment/dependency list.
2. Explicit input provenance: synthetic, public, manually entered, or measured.
3. Baseline comparison on identical inputs.
4. Sensitivity analysis and edge-case checks.
5. Definitions and units for every reported metric.
6. Model limitations, including perfect look-ahead, simplified RO dynamics, omitted flushing/water quality, and no grid power-flow model.
7. Clear distinction between scenario outputs and field evidence.

## Go / no-go criteria

Do not present the demo as competition-ready until:
- the clean setup instructions work;
- the test suite result is recorded;
- the dashboard runs without crashing for the tested parameter range;
- outputs are reproducible for a fixed seed;
- all comparison results use identical input traces;
- no synthetic number is presented as a real-island measurement.
