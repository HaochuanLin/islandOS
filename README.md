# islandOS

> **TL;DR:** islandOS is a Python simulation prototype (MVP) that uses curtailed wind and solar power on an isolated island to run an RO desalination plant and fill an upland reservoir. It aims to reduce reliance on chemical batteries by shifting water-production load into surplus hours. Stored freshwater is used only for water supply and is never converted back into electricity. Only this water-energy co-simulation is implemented. All results use synthetic demo data; there is no field deployment and no real measurement data.

**A software-only simulation platform for cross-resource orchestration on isolated island microgrids.**

islandOS turns curtailed wind and solar power on an island into freshwater stored in an upland reservoir, using a reverse osmosis (RO) desalination plant as a flexible load. It is a **Python simulation prototype (MVP)** with **no field deployment, no hardware and no real-world measurement data**. All numbers shown here come from **synthetic demo data**.

> **Status:** Early-stage simulation prototype. Only the water-energy co-simulation (the MVP core) is implemented. Everything else in this document is marked as *planned*.

---

## Table of Contents

1. [Overview](#overview)
2. [Concept & Paradigm](#concept--paradigm)
3. [1+N Architecture](#1n-architecture)
4. [Simulation Demo](#simulation-demo)
5. [Impact](#impact)
6. [How to Run](#how-to-run)
7. [Dependencies](#dependencies)
8. [Limitations & Project Stage](#limitations--project-stage)
9. [License](#license)

---

## Overview

Isolated islands typically depend on diesel generators, imported freshwater and, increasingly, chemical batteries. In high-salt-fog marine environments, batteries face corrosion and end-of-life pollution concerns, while wind and solar output is often curtailed when it exceeds demand.

**Mission:** decouple fluctuating wind/solar generation from island electricity demand by converting curtailed energy into storable, locally useful assets (freshwater first; cold energy, fuel and compute as future directions), reducing reliance on chemical storage and moving toward a zero-carbon circular island system.

**What the MVP does today:**

- Reads hourly wind output, PV output and base load (currently generated as synthetic demo data).
- Identifies curtailed energy: `curtail[t] = max(0, wind[t] + PV[t] - base_load[t])`.
- Dispatches an RO desalination plant as a flexible load driven by that curtailed energy.
- Enforces an industrial constraint on the RO plant: **once started, it must run for at least N consecutive hours** (default 2 h) to protect the membranes.
- Accumulates freshwater in an upland reservoir: `V[t+1] = V[t] + water_produced[t] - water_demand[t]`, with capacity and minimum-storage limits.
- Plots renewable output, curtailment, RO state and reservoir level over 24 hours.

## Concept & Paradigm

The stored freshwater is used **only for water supply**. It is **not** converted back into electricity (no reverse generation or pumped-hydro-style return). The reservoir therefore does not store *electricity*; it shifts *when* electricity is consumed, by producing water during surplus hours so that less diesel-powered or imported water supply may be needed at other times.

Three paradigm shifts underlie the project:

| Paradigm | Idea |
|---|---|
| **Storage** | Use physical storage (an upland reservoir now; ice / cold storage as a future option) instead of lithium batteries, avoiding corrosion exposure and heavy-metal pollution. |
| **Assets** | Asset-light: reuse idle or existing equipment (e.g. desalination units, tanks, reservoirs) rather than building large new infrastructure. |
| **System** | Couple the electricity and water systems so that resources are co-optimised, instead of each competing independently for diesel energy. |

> These are design principles of the project. The prototype demonstrates the water-energy coupling in simulation only; it does not yet quantify cost, emissions or battery displacement.

## 1+N Architecture

**1 = the simulation and dispatch "brain"; N = pluggable resource modules.**

### The "1": Simulation & dispatch core (implemented)

A time-series simulation engine that ingests generation and load data, identifies curtailment, dispatches flexible load, and enforces equipment protection constraints (RO minimum continuous run time).

### MVP core: water-energy co-simulation (implemented)

Curtailed energy drives RO desalination; produced freshwater is stored in an upland reservoir for load shifting and water supply.

### The "N": Extension slots (planned, NOT part of the MVP)

| Slot | Concept | Status |
|---|---|---|
| Green-hydrogen fishery cold chain | Use surplus power for hydrogen and/or cold-chain support for fisheries | Planned, not implemented |
| Flexible municipal sanitation | Shift sanitation / waste-handling loads to surplus hours | Planned, not implemented |
| Intermittent edge computing | Run deferrable compute workloads on surplus power | Planned, not implemented |

### Implementation status at a glance

| Capability | Status |
|---|---|
| Hourly time-series simulation (wind, PV, load) | Implemented (synthetic data) |
| Curtailment identification | Implemented |
| RO dispatch with minimum continuous-run constraint | Implemented |
| Upland reservoir water balance | Implemented |
| Backup-power on/off switch (`allow_backup_power`) | Implemented |
| 4-panel plot, Chinese / English labels (`use_english_labels`) | Implemented |
| Import of real terrain / weather / load datasets | Planned (current code takes arrays; no terrain model) |
| Ice / cold-storage module | Planned |
| Standardised API / hosted service ("SaaS") | Planned vision, not implemented |

## Simulation Demo

All results below use **synthetic demo data** generated in `load_data()` (24 hours, 1-hour steps). They illustrate how the model behaves and are **not** predictions for any real island.

![islandOS demo: renewable output, curtailment, RO state and reservoir level (synthetic demo data)](assets/demo_en.png)

*Figure: 24-hour simulation on synthetic demo data (backup power allowed). Panels: wind + PV vs. base load; curtailment and the part absorbed by RO; RO on/off state; reservoir level.*

**Default demo parameters (synthetic assumptions, not measured values):** RO rated power 400 kW, specific energy consumption 3.5 kWh/m³, minimum continuous run 2 h, reservoir capacity 3,000 m³ (initial 800 m³, minimum 200 m³).

| Metric (24 h, synthetic data) | Backup allowed | Backup forbidden |
|---|---|---|
| Total curtailed energy | 7,213.4 kWh | 7,213.4 kWh |
| Curtailment absorbed by RO | 4,944.4 kWh (68.5%) | 3,200.0 kWh (44.4%) |
| Backup energy needed by RO | 655.6 kWh | 0 kWh (disabled) |
| RO run segments | 5 h, 9 h | 2 h, 6 h |
| Freshwater produced | 1,600.0 m³ | 914.3 m³ |
| Reservoir storage (start → end) | 800 → 2,188 m³ | 800 → 1,502 m³ |
| Minimum-run constraint satisfied | Yes | Yes (for this demo case) |

**How RO dispatch works**

- **Start:** a stopped RO plant starts if the mean curtailment over the next `min_run_hours` hours is at least `start_ratio` (default 0.8) of rated power, and the reservoir is not full.
- **Forced run:** after starting, it keeps running until the minimum run time is reached.
- **Keep running:** afterwards it continues while curtailment stays above a threshold (`keep_ratio` of rated power when backup is allowed; full rated power when backup is forbidden).
- **Backup power switch (`allow_backup_power`):** if `True`, any shortfall during forced-run hours is booked as backup energy. If `False`, no backup is used and the plant is stopped immediately when curtailment cannot carry the rated power.

> **Important caveat:** with backup forbidden, that emergency stop can end a run before the minimum run time. The mean-based start test does not exclude this, even with perfect foresight. In a quick check over 200 random synthetic seeds, 116 produced at least one such early stop, which the built-in `check_min_run()` reports as a constraint violation. The default demo case (seed 42) does not trigger it.

## Impact

The points below are the **intended** impact of the approach. The current prototype only demonstrates the underlying mechanism on synthetic data; it has **not** quantified economic, emissions or resilience benefits.

- **Economic resilience (intended):** reduce island residents' dependence on diesel and purchased freshwater, and build a freshwater buffer that could help during typhoons and droughts.
- **Ecology (intended):** raise renewable utilisation and reduce curtailment; avoid battery-related pollution by relying on physical rather than chemical storage.
- **Replicability (design goal):** a software-only approach with low marginal cost per site and a planned standardised API, aimed at isolated islands worldwide. The API and any hosted service are not yet built.
- **Demonstrated so far:** on synthetic data, the model shows curtailed energy being absorbed by RO (68.5% in the default case) and converted into stored freshwater.

## How to Run

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/islandOS.git
cd islandOS

# 2. (Optional) create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the 24-hour synthetic demo
python island_microgrid_ro_sim.py
```

The script prints a summary to the console and saves `island_microgrid_ro.png`.

**Switches** (edit the constants in the `__main__` block of `island_microgrid_ro_sim.py`):

| Switch | Default | Effect |
|---|---|---|
| `ALLOW_BACKUP_POWER` | `True` | `False` forbids backup power; RO stops when curtailment is insufficient |
| `USE_ENGLISH_LABELS` | `False` | `True` draws all figure text in English |

**Use as a library:**

```python
import island_microgrid_ro_sim as m

p = m.Params(allow_backup_power=False, min_run_hours=2)
wind, pv, load, water_demand = m.load_data(24)   # replace with your own hourly arrays
res = m.simulate(wind, pv, load, water_demand, p)
runs, ok = m.check_min_run(res["ro_on"], p.min_run_hours)
m.plot(wind, pv, load, res, p, use_english_labels=True)
```

To use your own data, pass equal-length arrays: `wind`, `pv`, `load` (kW) and `water_demand` (m³/h).

## Dependencies

- Python 3.8 or newer
- `numpy >= 1.21`
- `matplotlib >= 3.5`

Install with `pip install -r requirements.txt`. For Chinese figure labels (the default), a CJK-capable font such as SimHei, Microsoft YaHei, PingFang SC or Noto Sans CJK must be installed; use `USE_ENGLISH_LABELS = True` otherwise.

## Limitations & Project Stage

**Stage:** simulation-only MVP. No field engineering, pilot site, hardware or real measurements exist.

**Known limitations of the current prototype**

- **Synthetic data only.** Wind, PV, load and water demand are generated by simple formulas; results are illustrative.
- **Perfect foresight.** The RO start decision reads the actual future curtailment of the next `min_run_hours` hours. Real deployment would need weather, renewable-output and load forecasts, and forecast errors would affect results; the prototype is therefore optimistic.
- **No post-shutdown RO flushing.** Real RO plants usually flush membranes after shutdown (extra energy, water and time). This is not modelled.
- **Simplified RO model.** Fixed rated power and flow when on; no variable-load operation, minimum load ratio, recovery rate, fouling or membrane ageing.
- **Simplified reservoir.** A single lumped water balance with fixed area; no evaporation, leakage, pumping head or water quality.
- **Simplified grid.** Backup power is a generic energy shortfall term; diesel generators, batteries, network constraints and dispatch economics are not modelled.
- **Short horizon.** The demo covers 24 hours; seasonal behaviour and long-term statistics are not studied.
- **No terrain or weather import yet.** The current code takes ready-made time-series arrays.
- **No cost, emissions or resilience quantification** yet, so the impact statements above are intentions, not results.
- **N extension modules, ice/cold storage, the standardised API and the SaaS model are not implemented.**

**Planned next steps (not committed):** real-data import (weather, load, terrain), forecast-error scenarios, variable-load RO, ice/cold-storage module, and the first N extension slot.

## License

Released under the **MIT License**. See the `LICENSE` file for details.
