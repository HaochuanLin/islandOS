# Repository Map

This page explains where to find the main parts of IslandOS. The repository contains the user-facing prototype, a substantial research/engineering workspace, and a small historical archive; not every experiment is part of the hosted app.

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
├── app.py                  # Streamlit research/demo entry point
├── islandos_service_api.py # Loopback-only local reference API
├── frontend/               # React + TypeScript customer-console foundation
├── islandos_core/          # Shared simulation, forecasting, decision, audit and safety logic
├── optimization/           # Optimization algorithms
├── islandos_sensors/       # Sensor contracts and mock sources
├── data/                   # Example datasets and input templates
├── config/                 # Example site/device configuration
├── configs/                # Additional example mappings
├── tools/                  # User-facing CLI utilities, validation and local demo deployment
├── experiments/            # Research experiments and benchmark scripts
├── examples/               # Minimal integration examples
├── tests/                  # Automated tests
├── docs/                   # Architecture, assumptions, runbooks and evidence
├── pages/                  # Additional Streamlit pages
├── assets/                 # Screenshots and static assets
├── outputs/                # Selected generated example outputs; verify provenance before reuse
├── archive/                # Historical scenario artifacts retained for traceability
├── packaging/              # Packaging and local launch helpers
└── .github/workflows/      # CI, regression and deployment checks
```

## Why are there Python files in the repository root?

A number of root-level Python files are retained as compatibility entry points for the existing app, CLI workflows, tests, and documented commands. Moving them wholesale would risk breaking imports, deployment commands, and reproducibility. New reusable domain logic should generally live in `islandos_core/`; optimization algorithms in `optimization/`; experiments in `experiments/`; and operator-facing utilities in `tools/`.

## Important maturity boundary

- The Streamlit application is an interactive, simulation-first research prototype. The React frontend and Python reference API are a separate local customer-console foundation; the deployment helper currently packages only the existing Streamlit Compose demo.
- Synthetic examples are illustrative and are not measured site data.
- Experimental scripts and optional integrations are not automatically part of the hosted app.
- The repository does not claim autonomous control of physical equipment.

For the current feature and maturity status, use the main [README](../README.md) and the relevant design/acceptance documents rather than inferring maturity from a filename.


## Historical artifacts and Nan'ao

The Nan'ao emergency desalination work is a bounded historical pilot scenario, not the generic IslandOS product definition. Historical seed-20261021 percentile and summary outputs are retained under `archive/nan-ao/` for traceability only; they are superseded and must not be presented as current model outputs, measured site data, forecasts, or customer economics. The active `islandos_nanao_hybrid.py`, its regression test, and its CI workflow remain in their existing locations because they are still used for reproducibility and automated regression. Their continued presence does not make Nan'ao the default product scenario.
