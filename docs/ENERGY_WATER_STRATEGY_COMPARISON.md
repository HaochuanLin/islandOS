# Energy-to-water strategy comparison (screening experiment)

## Purpose

This experiment compares five operating cases on the **same user-supplied time series**:

1. `no_ro_baseline`: no RO operation; reports potential direct renewable-to-diesel displacement separately.
2. `surplus_only`: run RO only on the supplied renewable-surplus series.
3. `off_peak_only`: run RO only when grid import is available and the time step is flagged off-peak.
4. `hybrid_surplus_then_off_peak`: prefer surplus renewable power; use off-peak grid electricity only when surplus is insufficient.
5. `emergency_backup`: run RO only when the supplied backup-generation capacity can support the rated load.

The comparison is intended to answer a strategy question, not to make one technology win by construction. It is a transparent screening experiment, **not a site-ready controller, dispatch optimiser, tariff forecast, lifecycle-cost model, or proof of commercial viability**.

## Inputs

Run from the repository root:

```bash
python experiments/compare_energy_water_strategies.py \
  --input path/to/site_hourly.csv \
  --output-dir build/energy-water-strategy-comparison \
  --ro-rated-power-kw 50 \
  --specific-energy-kwh-m3 4.0 \
  --tank-capacity-m3 100 \
  --initial-water-m3 20 \
  --min-run-hours 2 \
  --dt-hours 1 \
  --diesel-cost-per-kwh 0.35
```

The command-line numbers above are **illustrative example arguments only**, not recommended or validated site parameters. Supply values appropriate to the specific island and equipment. Omit `--diesel-cost-per-kwh` if no defensible local cost is available.

Required CSV columns:

| Column | Meaning / unit | Evidence requirement |
|---|---|---|
| `timestamp` | Increasing time label | Keep source timezone and interval convention documented. The script checks lexical ordering, not timezone correctness. |
| `renewable_surplus_kw` | Renewable power genuinely available to a flexible load after essential demand and applicable operating constraints | Do not equate raw wind/PV output with usable surplus. |
| `diesel_displacement_potential_kw` | Estimated renewable power that could directly displace diesel generation in that time step | Derive from a separate microgrid dispatch calculation or operator data; do not infer from surplus alone. This is reported as potential, not verified fuel savings. |
| `grid_price_per_kwh` | Applicable import tariff for the time step | Use the actual tariff and unit. |
| `off_peak` | `0/1` or `true/false` indicator for the tariff period | Reflect the site's actual tariff schedule. |
| `grid_available` | Whether grid import is available in that time step | Set false for an islanded system without a grid connection. |
| `water_demand_m3` | Water demand volume during the time step | Keep aligned to the time interval and local demand data. |
| `backup_available_kw` | Optional; spare backup-generator power available to RO, kW | If omitted, defaults to zero. Do not enter total generator nameplate rating unless that capacity is actually spare after critical loads and operating constraints. |

No missing site values are automatically imputed. The script rejects missing required columns, non-numeric or negative physical values, invalid flags, and non-increasing timestamp strings.

## Outputs

- `strategy_summary.csv`: one row per strategy, including simulated water production/service, unmet demand, spill, RO run hours, total renewable surplus available and unused, energy source split, grid energy cost, optional backup-energy cost estimate, ending water inventory, and the separate diesel-displacement-potential total.
- `timestep_audit.csv`: time-step-by-strategy source choice, RO power/energy, available and unused renewable surplus, water inventory balance, demand served/unmet, spill and tariff.

## Interpretation rules

- All results are conditional on the supplied time series and configuration. With synthetic inputs, results are synthetic demonstrations only.
- The model does not establish whether an island actually has curtailed wind, off-peak tariffs, or diesel generation that can be displaced.
- `diesel_displacement_potential_kw` is deliberately separate from RO dispatch. It is **not** counted as extra savings caused by desalination, and the script does not convert it into fuel or emissions savings.
- Renewable-surplus energy is assigned zero direct purchase cost in this screening output, but that does **not** mean it has zero opportunity cost or zero system cost.
- Grid cost includes only RO electricity imported during the simulated period. It excludes demand charges, connection upgrades, taxes/fees not represented in the input tariff, RO capital cost, pretreatment, intake/outfall, brine management, staffing, consumables, maintenance, water storage and financing.
- Backup energy is reported separately. A cost estimate is emitted only when the user supplies a site-specific `--diesel-cost-per-kwh`; this estimate is not a universal diesel cost.
- RO is represented as a fixed rated-power load with a minimum consecutive run window and a simple freshwater inventory. Startup/ramp dynamics, water-quality constraints, detailed equipment interlocks, diesel commitment, network power-flow constraints, battery state-of-charge and forecast uncertainty are not fully modelled.
- The offline start-window check assumes the supplied time series is known. It is not an operational forecast and does not prove the plant can be safely controlled in real time.
- The hybrid strategy is a simple rule (surplus first, then off-peak grid); it is not guaranteed to be economically optimal.
- Compare complete system costs and reliability constraints before making procurement decisions. If no strategy passes the site's technical, environmental and economic gates, the appropriate recommendation can be **do not procure**.

## Recommended site-readiness gates

Before interpreting results as decision evidence, obtain and document:
1. A quality-checked aligned time series of essential load, renewable generation, actual curtailment/surplus, diesel output and constraints.
2. The method used to calculate direct diesel-displacement potential, including minimum stable output, reserve requirements and any start/stop constraints.
3. The actual time-of-use tariff and whether the site can import electricity during the proposed operating periods.
4. RO vendor data for rated power, specific energy, minimum run time, ramp/start constraints, recovery rate and water quality.
5. Hourly or sub-hourly water demand, storage capacity, environmental/permit constraints, and complete installed and operating costs.
6. A comparison against the existing water-supply option and a documented go/no-go decision.

The software intentionally does not provide a fabricated sample result or claim that one strategy is universally best.
