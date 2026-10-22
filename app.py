"""Interactive research dashboard for the IslandOS synthetic 24-hour demo.

Run with: streamlit run app.py
All inputs are synthetic. This is a research visualization, not a site controller.
"""
from __future__ import annotations

import numpy as np
import streamlit as st

from island_microgrid_ro_sim import Params, load_data, simulate, check_min_run

st.set_page_config(page_title="islandOS | Energy–Water Lab", page_icon="🌊", layout="wide")

st.title("islandOS")
st.subheader("Island energy–water flexibility lab")
st.caption("Interactive 24-hour simulation • synthetic inputs • research prototype")

st.warning(
    "Evidence boundary: this dashboard uses generated example data, not measured Nan’ao or other island data. "
    "Results demonstrate model behavior under the selected assumptions; they are not field performance, "
    "validated savings, or an operational recommendation."
)

with st.sidebar:
    st.header("Scenario controls")
    seed = st.number_input("Synthetic scenario seed", min_value=0, max_value=999999, value=42, step=1)
    wind_scale = st.slider("Wind output multiplier", 0.0, 1.5, 1.0, 0.05)
    pv_scale = st.slider("Solar output multiplier", 0.0, 1.5, 1.0, 0.05)
    load_scale = st.slider("Essential electricity load multiplier", 0.5, 1.5, 1.0, 0.05)
    st.divider()
    st.subheader("RO / water system")
    ro_power = st.slider("RO rated power (kW)", 50, 500, 300, 25)
    sec = st.slider("RO specific energy (kWh/m³)", 2.0, 8.0, 3.5, 0.1)
    min_run = st.slider("Minimum continuous run (h)", 1, 4, 2)
    capacity = st.slider("Reservoir capacity (m³)", 500, 5000, 3000, 250)
    initial = st.slider("Initial stored water (m³)", 100, int(capacity), min(800, int(capacity)), 50)
    dead_storage = st.slider("Minimum reserve (m³)", 0, int(initial), min(200, int(initial)), 25)
    allow_backup = st.toggle("Allow backup power for RO", value=False)
    if allow_backup:
        st.info("Backup use is reported separately. It must not be interpreted as renewable-only water production.")

wind, pv, base_load, water_demand = load_data(hours=24, seed=int(seed))
wind = wind * wind_scale
pv = pv * pv_scale
base_load = base_load * load_scale

# Keep user-selected reservoir bounds physically consistent.
initial = min(int(initial), int(capacity))
dead_storage = min(int(dead_storage), int(initial))
params = Params(
    ro_power_kw=float(ro_power),
    ro_sec_kwh_m3=float(sec),
    min_run_hours=int(min_run),
    start_ratio=0.8,
    keep_ratio=0.5,
    allow_backup_power=bool(allow_backup),
    res_capacity_m3=float(capacity),
    res_init_m3=float(initial),
    res_min_m3=float(dead_storage),
    res_area_m2=1000.0,
)
result = simulate(wind, pv, base_load, water_demand, params)
curtail = result["curtail"]
renewable_surplus_used = result["ro_use"]
total_surplus = float(curtail.sum())
used_surplus = float(renewable_surplus_used.sum())
utilization = 100.0 * used_surplus / total_surplus if total_surplus > 0 else 0.0
water_produced = float(result["water_prod"].sum())
water_demand_total = float(water_demand.sum())
water_deficit = float(result["deficit"].sum())
backup_energy = float(result["ro_backup"].sum())
segments, min_run_ok = check_min_run(result["ro_on"], params.min_run_hours)

st.caption("Scenario identity: seed={}, wind × {:.2f}, solar × {:.2f}, essential load × {:.2f}".format(
    int(seed), wind_scale, pv_scale, load_scale
))

m1, m2, m3, m4 = st.columns(4)
m1.metric("Available surplus energy", f"{total_surplus:,.0f} kWh")
m2.metric("Surplus absorbed by RO", f"{used_surplus:,.0f} kWh", f"{utilization:.1f}% of surplus")
m3.metric("Modeled water production", f"{water_produced:,.1f} m³")
m4.metric("Unmet water demand indicator", f"{water_deficit:,.1f} m³")

if not min_run_ok:
    st.error("Minimum-run check failed in this scenario. Treat this as a model-detected constraint violation, not a successful dispatch.")
elif int(result["emergency_stop"].sum()) > 0:
    st.warning("An emergency stop occurred. Review the operating trace before interpreting this run.")
else:
    st.success("The simplified minimum-run check passed for this 24-hour trace. This does not validate real plant interlocks.")

tab1, tab2, tab3 = st.tabs(["System balance", "RO & water", "Model audit"])

with tab1:
    st.markdown("### Renewable supply versus essential load")
    st.line_chart({
        "Wind (kW)": wind,
        "Solar PV (kW)": pv,
        "Essential load (kW)": base_load,
    })
    st.markdown("### Surplus energy allocation")
    st.line_chart({
        "Available surplus (kW)": curtail,
        "Absorbed by RO (kW-equivalent)": renewable_surplus_used,
    })
    st.write(
        "In this prototype, surplus is calculated as max(0, wind + solar − essential load). "
        "Network constraints, battery dispatch, diesel commitment and power-flow physics are not modeled."
    )

with tab2:
    st.markdown("### RO operating state")
    st.line_chart({"RO on (1 = operating)": result["ro_on"]})
    st.markdown("### Reservoir inventory")
    st.line_chart({
        "Stored water (m³)": result["V"],
    })
    st.line_chart({
        "Water demand (m³/h)": water_demand,
        "Water produced (m³/h)": result["water_prod"],
        "Unmet demand indicator (m³)": result["deficit"],
    })
    c1, c2, c3 = st.columns(3)
    c1.metric("Total water demand", f"{water_demand_total:,.1f} m³")
    c2.metric("RO backup energy", f"{backup_energy:,.1f} kWh")
    c3.metric("Reservoir spill", f"{float(result['spill'].sum()):,.1f} m³")

with tab3:
    st.markdown("### Reproducibility and constraints")
    st.write({
        "synthetic_seed": int(seed),
        "time_step": "1 hour",
        "horizon": "24 hours",
        "minimum_run_hours": int(min_run),
        "minimum_run_segment_lengths": segments,
        "minimum_run_check_passed": bool(min_run_ok),
        "emergency_stop_hours": np.flatnonzero(result["emergency_stop"]).tolist(),
        "backup_energy_kwh": round(backup_energy, 3),
        "reservoir_min_m3": float(np.min(result["V"])),
        "reservoir_max_m3": float(np.max(result["V"])),
        "surplus_absorbed_fraction": round(utilization / 100.0, 4),
    })
    st.markdown("### Interpretation limits")
    st.markdown(
        "- Inputs are synthetic and should not be described as Nan’ao measurements.\n"
        "- The dispatch uses perfect look-ahead over the generated trace; real forecasts have error.\n"
        "- RO start/stop and reservoir dynamics are simplified; membrane flushing, water quality, "
        "intake/outfall constraints and plant-specific interlocks are omitted.\n"
        "- No cost, emissions, savings, reliability certification or field feasibility claim is made.\n"
        "- Use the repository regression tests and scenario documentation before relying on any output."
    )

st.divider()
st.caption("islandOS • Open research prototype • Reproducible synthetic demonstration")
