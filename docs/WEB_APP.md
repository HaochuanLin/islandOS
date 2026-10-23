# islandOS Web App Guide

## What it is

The web interface is a local Streamlit planning prototype started with the command shown below. It is not a hosted service or a real-time microgrid controller. A public deployment URL has not been verified.

~~~bash
pip install -r requirements.txt
streamlit run app.py
~~~

Streamlit prints a local address in the terminal. Open that address in a browser on the same computer.

## Pages and features

### Overview

Explains the energy–water planning question, the current prototype boundary, and a recommended workflow. Built-in demo inputs are synthetic.

### Strategy simulator

1. Choose the synthetic demo or upload a CSV.
2. Configure RO rated power, specific energy use, tank capacity, starting inventory, minimum run time, interval length, and optional backup-energy cost.
3. Run the fixed-strategy comparison.
4. Inspect water production and service, unmet demand, energy use/cost, charts, and timestep-level operating records.
5. Download the summary and detailed hourly audit as CSV.

The app compares five transparent policies: no-RO baseline, surplus-only, off-peak-only, hybrid surplus-then-off-peak, and emergency-backup. Strategy results are conditional on the input series and simplified assumptions. Direct diesel-displacement potential is reported separately and should not be interpreted as savings caused by RO operation.

### Experimental NSGA-II optimizer

After running the strategy comparison, the app can search candidate RO schedules using NSGA-II and display feasible non-dominated candidates. The current search uses a discrete set of RO power choices and hard feasibility requirements defined in the interface. It is model-based optimization, not machine learning trained on real site data. A search can return no feasible schedule within its configured budget.

### Data guide

Lists required input columns and validation rules and provides a downloadable CSV template.

## Input data

The uploaded CSV must contain the columns expected by the strategy comparison:

| Column | Meaning |
|---|---|
| timestamp | Timestamp for each time step, strictly increasing |
| renewable_surplus_kw | Renewable power already available after essential demand and required reserves, in kW |
| diesel_displacement_potential_kw | Potential direct diesel displacement, tracked separately, in kW |
| grid_price_per_kwh | Electricity price for the interval, in currency/kWh |
| off_peak | Whether the interval is off-peak (true/false, yes/no, or 1/0) |
| grid_available | Whether grid power is available |
| water_demand_m3 | Water demand during the interval, in m³ |

Optional: backup_available_kw gives the backup capacity available to RO in each interval; omitted or blank values default to zero.

The simulator settings determine the time-step duration. Make sure the timestamp spacing and interval setting agree. Numeric values must be finite and non-negative. The app does not silently create missing measurements or replace missing hours with synthetic values.

## Important limitations

- The default example is synthetic and must not be presented as a real island's measurements.
- This app does not communicate with generators, batteries, desalination plants, pumps, or grid equipment.
- It does not provide real-time forecasting, safety interlocks, or autonomous control.
- Essential-load and reserve needs must already be accounted for in the supplied renewable-surplus series.
- Simplified RO, tank, tariff, backup, and operating assumptions may not match a particular site.
- Outputs are exploratory comparisons, not a guarantee of water supply, energy savings, economic viability, or equipment safety.

Before using local measurements, confirm units, time zones, data completeness, equipment limits, tariff rules, and the meaning of every column.
