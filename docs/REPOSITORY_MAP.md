# Repository Map

This page explains where to find the main parts of IslandOS. The repository contains both the user-facing prototype and a substantial research/engineering workspace; not every experiment is part of the hosted app.

## Start here

| If you want to... | Open |
|---|---|
| Understand the project and run the app | [README](../README.md) and [app.py](../app.py) |
| Explore the core simulation and decision workflow | [islandos_core/](../islandos_core/) |
| Find optimization algorithms | [optimization/](../optimization/) |
| Run reproducible experiments and benchmarks | [experiments/](../experiments/) |
| Run command-line demos and validation tools | [tools/](../tools/) |
| Read technical design, assumptions, and validation notes | [docs/](./) |
| Inspect regression tests | [tests/](../tests/) |
| Use sample inputs and templates | [data/](../data/) |
| Review example configurations | [config/](../config/) and [configs/](../configs/) |
| Inspect optional sensor/telemetry interfaces | [islandos_sensors/](../islandos_sensors/) |
| Inspect the optional Windows packaging prototype | [packaging/windows/](../packaging/windows/) |

## Main repository layout

```text
islandOS/
├── app.py                  # Streamlit entry point
├── islandos_core/          # Shared simulation, forecasting, decision and audit logic
├── optimization/           # Optimization algorithms
├── islandos_sensors/       # Sensor contracts and mock sources
├── data/                   # Example datasets and input templates
├── config/                 # Example site/device configuration
├── configs/                # Additional example mappings
├── tools/                  # User-facing CLI utilities and validation tools
├── experiments/            # Research experiments and benchmark scripts
├── examples/               # Minimal integration examples
├── tests/                  # Automated tests
├── docs/                   # Architecture, assumptions, runbooks and evidence
├── pages/                  # Additional Streamlit pages
├── assets/                 # Screenshots and static assets
├── outputs/                # Selected generated example outputs
├── packaging/              # Packaging and local launch helpers
└── .github/workflows/      # CI, regression and deployment checks
```

## Why are there Python files in the repository root?

A number of root-level Python files are retained as compatibility entry points for the existing app, CLI workflows, tests, and documented commands. Moving them wholesale would risk breaking imports, deployment commands, and reproducibility. New reusable domain logic should generally live in `islandos_core/`; optimization algorithms in `optimization/`; experiments in `experiments/`; and operator-facing utilities in `tools/`.

## Important maturity boundary

- The Streamlit application is an interactive, simulation-first research prototype.
- Synthetic examples are illustrative and are not measured site data.
- Experimental scripts and optional integrations are not automatically part of the hosted app.
- The repository does not claim autonomous control of physical equipment.

For the current feature and maturity status, use the main [README](../README.md) and the relevant design/acceptance documents rather than inferring maturity from a filename.
