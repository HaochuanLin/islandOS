# Stress tests (10 synthetic weeks per case)

## 1. Does the optimizer change its schedule under forecast stress?

Mean over weeks. RO energy moved is half the total absolute change in hourly RO power versus the central plan.

| Case | Scenario | Weeks where schedule changed | RO energy moved (kWh) | RO hours changed | Planned cost change |
|---|---|---|---|---|---|
| island | renewable_low_demand_high | 10/10 | 461 | 104 | +273% |
| island | cost_high | 0/10 | 0 | 0 | +0% |
| island | combined_stress | 10/10 | 461 | 104 | +273% |
| grid_tou | renewable_low_demand_high | 10/10 | 551 | 86 | +443% |
| grid_tou | cost_high | 10/10 | 86 | 19 | +25% |
| grid_tou | combined_stress | 10/10 | 551 | 86 | +579% |

## 2. What happens when the plan was made on the wrong forecast?

Each plan's RO schedule is held; the battery-first controller runs the electricity live. Headline is tank-adjusted diesel litres (island) or tank-adjusted cost in USD (grid_tou). Water shortage is the total over all weeks. A lower headline next to a shortage is not a saving: that plan simply delivered less water.

| Case | Plan made on | Realised scenario | Mean headline | Water shortage (m3) |
|---|---|---|---|---|
| island | central | central | 283.4 | 0.0 |
| island | central | renewable_low_demand_high | 966.7 | 335.0 |
| island | central | cost_high | 283.4 | 0.0 |
| island | central | combined_stress | 966.7 | 335.0 |
| island | combined_stress | central | 327.8 | 0.0 |
| island | combined_stress | renewable_low_demand_high | 1006.9 | 0.0 |
| island | combined_stress | cost_high | 327.8 | 0.0 |
| island | combined_stress | combined_stress | 1006.9 | 0.0 |
| grid_tou | central | central | 126.0 | 0.0 |
| grid_tou | central | renewable_low_demand_high | 670.9 | 201.1 |
| grid_tou | central | cost_high | 157.5 | 0.0 |
| grid_tou | central | combined_stress | 834.1 | 201.1 |
| grid_tou | combined_stress | central | 191.5 | 0.0 |
| grid_tou | combined_stress | renewable_low_demand_high | 637.3 | 0.0 |
| grid_tou | combined_stress | cost_high | 246.0 | 0.0 |
| grid_tou | combined_stress | combined_stress | 796.6 | 0.0 |

## 3. Water-shortage stress events

Water shortage and lowest tank level are totals and minimums over all weeks. Headline as above, mean per week; again, a lower headline with a shortage means less water was delivered.

| Case | Event | Strategy | Weeks with shortage | Water shortage (m3) | Lowest tank (m3) | Mean headline |
|---|---|---|---|---|---|---|
| island | low_renewable_week | Fixed RO timetable | 0/10 | 0.0 | 29.2 | 1204.5 |
| island | low_renewable_week | Surplus rule | 0/10 | 0.0 | 17.1 | 1204.5 |
| island | low_renewable_week | Forecast-based rule | 0/10 | 0.0 | 20.9 | 1204.6 |
| island | low_renewable_week | Joint MILP, planned on normal forecast | 0/10 | 0.0 | 0.0 | 1204.5 |
| island | low_renewable_week | Joint MILP with 20 m3 reserve, normal forecast | 0/10 | 0.0 | 20.0 | 1204.5 |
| island | low_renewable_week | Joint MILP, event forecast in advance | 0/10 | 0.0 | 0.0 | 1204.5 |
| island | water_demand_spike | Fixed RO timetable | 1/10 | 0.2 | 0.0 | 341.0 |
| island | water_demand_spike | Surplus rule | 0/10 | 0.0 | 15.0 | 344.5 |
| island | water_demand_spike | Forecast-based rule | 0/10 | 0.0 | 20.0 | 345.2 |
| island | water_demand_spike | Joint MILP, planned on normal forecast | 10/10 | 477.1 | 0.0 | 283.4 |
| island | water_demand_spike | Joint MILP with 20 m3 reserve, normal forecast | 10/10 | 277.5 | 0.0 | 307.4 |
| island | water_demand_spike | Joint MILP, event forecast in advance | 0/10 | 0.0 | 0.0 | 340.7 |
| island | low_renewable_and_spike | Fixed RO timetable | 1/10 | 0.2 | 0.0 | 1261.7 |
| island | low_renewable_and_spike | Surplus rule | 0/10 | 0.0 | 15.5 | 1261.8 |
| island | low_renewable_and_spike | Forecast-based rule | 0/10 | 0.0 | 20.2 | 1261.8 |
| island | low_renewable_and_spike | Joint MILP, planned on normal forecast | 10/10 | 477.1 | 0.0 | 1204.5 |
| island | low_renewable_and_spike | Joint MILP with 20 m3 reserve, normal forecast | 10/10 | 277.5 | 0.0 | 1228.5 |
| island | low_renewable_and_spike | Joint MILP, event forecast in advance | 0/10 | 0.0 | 0.0 | 1261.8 |
| grid_tou | low_renewable_week | Fixed RO timetable | 0/10 | 0.0 | 29.2 | 889.7 |
| grid_tou | low_renewable_week | Surplus rule | 0/10 | 0.0 | 17.1 | 879.0 |
| grid_tou | low_renewable_week | Forecast-based rule | 0/10 | 0.0 | 20.9 | 867.4 |
| grid_tou | low_renewable_week | Joint MILP, planned on normal forecast | 0/10 | 0.0 | 0.0 | 816.6 |
| grid_tou | low_renewable_week | Joint MILP with 20 m3 reserve, normal forecast | 0/10 | 0.0 | 20.0 | 816.3 |
| grid_tou | low_renewable_week | Joint MILP, event forecast in advance | 0/10 | 0.0 | 0.0 | 790.3 |
| grid_tou | water_demand_spike | Fixed RO timetable | 1/10 | 0.2 | 0.0 | 250.8 |
| grid_tou | water_demand_spike | Surplus rule | 0/10 | 0.0 | 15.0 | 217.0 |
| grid_tou | water_demand_spike | Forecast-based rule | 0/10 | 0.0 | 20.0 | 262.2 |
| grid_tou | water_demand_spike | Joint MILP, planned on normal forecast | 10/10 | 369.8 | 0.0 | 134.8 |
| grid_tou | water_demand_spike | Joint MILP with 20 m3 reserve, normal forecast | 10/10 | 243.8 | 0.0 | 145.2 |
| grid_tou | water_demand_spike | Joint MILP, event forecast in advance | 0/10 | 0.0 | 0.0 | 151.7 |
| grid_tou | low_renewable_and_spike | Fixed RO timetable | 1/10 | 0.2 | 0.0 | 933.6 |
| grid_tou | low_renewable_and_spike | Surplus rule | 0/10 | 0.0 | 15.5 | 920.6 |
| grid_tou | low_renewable_and_spike | Forecast-based rule | 0/10 | 0.0 | 20.2 | 907.9 |
| grid_tou | low_renewable_and_spike | Joint MILP, planned on normal forecast | 10/10 | 369.8 | 0.0 | 825.4 |
| grid_tou | low_renewable_and_spike | Joint MILP with 20 m3 reserve, normal forecast | 10/10 | 243.8 | 0.0 | 835.3 |
| grid_tou | low_renewable_and_spike | Joint MILP, event forecast in advance | 0/10 | 0.0 | 0.0 | 828.5 |

All numbers are simulation results on synthetic inputs, not measurements.
