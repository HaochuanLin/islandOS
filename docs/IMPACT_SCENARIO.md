# Synthetic impact scenario: fixed timetable vs coordinated RO

## What question this answers

If a small off-grid island already has solar, wind, a battery, a diesel generator and an RO desalination unit, does timing RO around spare renewable power use less diesel than a fixed operator timetable, without hurting water service?

This runs on **synthetic data**. It describes how our model behaves, not what a real island would save.

## Short answer

On this synthetic island, no. Once both strategies are judged fairly (charging each one for any water it leaves out of the tank at the end of the week), the simple coordinated rule used about the same diesel as the fixed timetable: +0.7% on average, between -0.8% and +6.3% across 30 weeks. The island has very little spare renewable power to shift (about 46 kWh curtailed per week), and a daytime shift already lines RO up with solar output fairly well.

An earlier version of this experiment reported about 16% less diesel. That came from a bug: daily water demand was spread over the whole week, so the island needed far less water than intended. The bug is fixed and a test now checks it.

## How to run it

```bash
python experiments/run_impact_scenario.py --seeds 30 --days 7 --sensitivity --output-dir results/impact_scenario
```

## The two strategies

| | Fixed timetable (baseline) | Coordinated |
|---|---|---|
| When RO runs | During a staffed shift (07:00 to 19:00) whenever the tank is below 95% full | Any hour with enough renewable power left over after essential load, as long as the tank has room |
| What powers RO | A firm load: renewables first, then battery, then diesel | Only leftover renewables |
| Safety net | Not needed, the shift keeps the tank high | If the tank falls below 25% it switches to firm RO |

RO never runs below 6 kW (40% of its rating), in either strategy. Both use `simulate_microgrid` from `islandos_core/microgrid_model.py` one hour at a time.

## Default island (illustrative, not a real site)

60 kW solar, 40 kW wind, 120 kWh battery, 80 kW diesel, 15 kW RO at 4 kWh per m3 with 45% recovery, an 80 m3 tank starting half full, about 30 kW essential load, 40 m3 of water a day for 150 households, no grid. Diesel at 0.35 USD per kWh, 0.30 litres per kWh and 2.68 kg CO2 per litre.

## Results (30 synthetic weeks)

| Per week, mean of 30 weeks | Fixed timetable | Coordinated | Change |
|---|---|---|---|
| Diesel, adjusted for water left in tank (litres) | 318.5 | 320.3 | +1.8 |
| CO2, adjusted for water left in tank (kg) | 853.5 | 858.4 | +4.9 |
| Diesel used, unadjusted (litres) | 351.7 | 300.5 | -51.2 |
| Generator running hours | 109.7 | 83.3 | -26.4 |
| Renewable energy curtailed (kWh) | 46.1 | 47.1 | +1.1 |
| Water demand served (%) | 100.0 | 100.0 | +0.0 |
| Water per household per day (litres) | 266.4 | 266.4 | +0.0 |
| Brine discharged (m3, rough estimate) | 375.7 | 321.6 | -54.1 |
| RO start-ups | 8.1 | 21.0 | +12.9 |
| Water in tank at end of week (m3) | 67.7 | 23.5 | -44.2 |

The unadjusted diesel figure looks better for coordination only because it ends the week with much less water in the tank. Refilling that water would need roughly the diesel it appeared to save.

## Sensitivity (adjusted diesel)

| Case | Mean change | Range across weeks | Weeks with less diesel |
|---|---|---|---|
| default | +0.7% | -0.8% to +6.3% | 3/30 |
| baseline shift 06-18 | -0.2% | -2.5% to +3.2% | 17/30 |
| baseline shift 08-20 | +0.9% | -0.8% to +4.0% | 2/30 |
| baseline shift 09-17 | +13.7% | +7.5% to +18.8% | 0/30 |
| battery 60 kWh | +0.3% | -0.8% to +1.4% | 5/30 |
| battery 240 kWh | +0.9% | +0.0% to +11.0% | 0/30 |
| solar 30 kW | +0.2% | +0.1% to +0.3% | 0/30 |
| solar 90 kW | +2.1% | -2.1% to +9.9% | 6/30 |
| water demand 60 m3/day | +20.5% | +14.1% to +31.3% | 0/30 |
| tank 40 m3 | -0.2% | -2.0% to +1.4% | 13/30 |

None of the tested variations gives a clear benefit, and in two cases (a 09:00 to 17:00 shift, or 60 m3 of demand a day) coordination is clearly worse because the 25% safety net forces RO to run at night on diesel. We also tried a version that tops the tank up during the day; it did not change the conclusion.

## What this means for islandOS

Scheduling flexible loads only helps when a site really has surplus renewable power that is being wasted, or tariffs that change during the day. That has to be checked with real site data before claiming any saving, which is what the pilot gates in the proposal are for.

## Reproducibility

`manifest.json` records the git commit, the command, Python and NumPy versions, every assumption, the seeds and a SHA-256 hash of each week's inputs. `hourly_seed0.csv` has the hour-by-hour audit for seed 0 and `impact_seed0.png` plots it.

## Limits

One-hour steps and the simplifications of `microgrid_model.py`: no diesel minimum load or start-up fuel, no battery ageing, no RO minimum run time, no grid. Weather, load and water demand are generated, and the brine figure uses a fixed recovery ratio. The coordinated rule is deliberately simple; a forecast-based rule could do better or worse.
