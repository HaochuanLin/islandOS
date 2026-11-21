# Rule strategies vs joint optimisation (30 synthetic weeks)

## island

Headline: diesel litres per week, adjusted for water left in the tank.

| Strategy | Mean | Change vs fixed timetable | Range across weeks | Weeks better | Water shortage (m3, all weeks) |
|---|---|---|---|---|---|
| Fixed RO timetable (07:00 to 19:00) | 318.5 | +0.0% | +0.0% to +0.0% | 0/30 | 0.0 |
| Simple surplus rule | 320.3 | +0.7% | -0.8% to +6.3% | 3/30 | 0.0 |
| Forecast-based rule (perfect forecast) | 320.7 | +0.8% | -0.9% to +5.1% | 3/30 | 0.0 |
| Forecast-based rule (20% forecast error, 3 h minimum run) | 320.8 | +0.9% | -0.8% to +5.5% | 2/30 | 0.0 |
| Just-in-time RO | 391.9 | +26.5% | +3.7% to +72.8% | 0/30 | 0.0 |
| Optimised battery, fixed RO timetable | 318.5 | +0.0% | +0.0% to +0.0% | 0/30 | 0.0 |
| Joint water-energy optimisation (MILP) | 316.7 | -0.7% | -7.6% to +0.0% | 23/30 | 0.0 |
| Joint optimisation keeping a 20 m3 tank reserve | 316.7 | -0.7% | -7.4% to +0.0% | 23/30 | 0.0 |

Every joint MILP solve proven optimal: True.

## grid_tou

Headline: energy cost (USD) per week, adjusted for water left in the tank.

| Strategy | Mean | Change vs fixed timetable | Range across weeks | Weeks better | Water shortage (m3, all weeks) |
|---|---|---|---|---|---|
| Fixed RO timetable (07:00 to 19:00) | 239.5 | +0.0% | +0.0% to +0.0% | 0/30 | 0.0 |
| Simple surplus rule | 202.4 | -15.5% | -23.1% to -9.7% | 30/30 | 0.0 |
| Forecast-based rule (perfect forecast) | 245.2 | +2.7% | -1.9% to +10.2% | 6/30 | 0.0 |
| Forecast-based rule (20% forecast error, 3 h minimum run) | 241.5 | +0.8% | -5.4% to +10.9% | 12/30 | 0.0 |
| Just-in-time RO | 233.6 | +0.7% | -18.1% to +37.6% | 16/30 | 0.0 |
| Tariff look-ahead RO | 205.0 | -10.1% | -35.0% to +33.0% | 24/30 | 0.0 |
| Optimised battery, fixed RO timetable | 225.0 | -6.4% | -12.7% to -3.3% | 30/30 | 0.0 |
| Joint water-energy optimisation (MILP) | 134.5 | -43.6% | -48.8% to -36.9% | 30/30 | 0.0 |
| Joint optimisation keeping a 20 m3 tank reserve | 134.6 | -43.6% | -48.7% to -36.9% | 30/30 | 0.0 |

Every joint MILP solve proven optimal: True.

## hybrid_tou

Headline: energy cost (USD) per week including diesel starts, adjusted for water left in the tank.

| Strategy | Mean | Change vs fixed timetable | Range across weeks | Weeks better | Water shortage (m3, all weeks) |
|---|---|---|---|---|---|
| Fixed RO timetable (07:00 to 19:00) | 250.0 | +0.0% | +0.0% to +0.0% | 0/30 | 0.0 |
| Simple surplus rule | 208.6 | -16.7% | -25.7% to -10.2% | 30/30 | 0.0 |
| Forecast-based rule (perfect forecast) | 264.6 | +6.3% | -3.7% to +19.2% | 1/30 | 0.0 |
| Forecast-based rule (20% forecast error, 3 h minimum run) | 258.9 | +3.7% | -5.2% to +16.7% | 5/30 | 0.0 |
| Just-in-time RO | 236.1 | -2.4% | -21.2% to +32.5% | 19/30 | 0.0 |
| Tariff look-ahead RO | 209.4 | -12.0% | -38.4% to +28.0% | 24/30 | 0.0 |
| Optimised battery, fixed RO timetable | 225.0 | -10.1% | -15.9% to -5.8% | 30/30 | 0.0 |
| Joint water-energy optimisation (MILP) | 134.5 | -45.9% | -51.9% to -36.9% | 30/30 | 0.0 |
| Joint optimisation keeping a 20 m3 tank reserve | 134.6 | -45.9% | -51.9% to -36.9% | 30/30 | 0.0 |

Every joint MILP solve proven optimal: True.

## Flexible load timing

One synthetic day per seed (30 days). A 40 kWh flexible load (at most 10 kW) must run inside its window; RO stays on the fixed timetable. Energy cost in USD per day.

| Case | Window | Strategy | Mean cost | Change in mean cost vs rule dispatch | Days better |
|---|---|---|---|---|---|
| island | daytime_06_22 | Rule dispatch, load run as early as allowed | 63.64 | +0.0% | 0/30 |
| island | daytime_06_22 | Optimised battery, load still run early | 63.64 | +0.0% | 0/30 |
| island | daytime_06_22 | Optimised battery and load timing | 60.87 | -4.4% | 27/30 |
| island | any_hour | Rule dispatch, load run as early as allowed | 64.28 | +0.0% | 0/30 |
| island | any_hour | Optimised battery, load still run early | 64.28 | +0.0% | 0/30 |
| island | any_hour | Optimised battery and load timing | 60.83 | -5.4% | 27/30 |
| grid_tou | daytime_06_22 | Rule dispatch, load run as early as allowed | 40.56 | +0.0% | 0/30 |
| grid_tou | daytime_06_22 | Optimised battery, load still run early | 33.52 | -17.4% | 30/30 |
| grid_tou | daytime_06_22 | Optimised battery and load timing | 32.50 | -19.9% | 30/30 |
| grid_tou | any_hour | Rule dispatch, load run as early as allowed | 38.56 | +0.0% | 0/30 |
| grid_tou | any_hour | Optimised battery, load still run early | 31.83 | -17.5% | 30/30 |
| grid_tou | any_hour | Optimised battery and load timing | 30.82 | -20.1% | 30/30 |

All numbers are simulation results on synthetic inputs, not measurements.
