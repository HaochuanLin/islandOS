"""Streamlit lab for comparing auditable multi-resource energy policies."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from islandos_core.application import run_energy_policy_comparison
from islandos_core.energy_system import (
    BatterySpec,
    DieselSpec,
    EnergySystemConfig,
    EnergySystemInputs,
)

st.set_page_config(page_title="IslandOS Energy System Lab", page_icon="⚡", layout="wide")
st.title("IslandOS · Multi-Resource Energy System Lab")
st.caption("Shared physical model · deterministic policy comparison · simulation only")

st.info(
    "Explore how renewable generation, essential load, battery storage, grid supply, "
    "and diesel backup interact over 24 hours. This page uses a synthetic scenario; "
    "it is not a site assessment, forecast, global optimizer, or equipment controller."
)

with st.sidebar:
    st.header("Scenario assumptions")
    pv_capacity = st.slider("PV rated capacity (kW)", 0, 160, 80, 5)
    wind_capacity = st.slider("Wind rated capacity (kW)", 0, 100, 40, 5)
    load_multiplier = st.slider("Essential-load multiplier", 0.5, 1.8, 1.0, 0.05)
    tariff_multiplier = st.slider("Grid tariff multiplier", 0.5, 2.0, 1.0, 0.05)
    grid_limit = st.slider("Grid import limit (kW)", 0, 150, 75, 5)

    st.subheader("Battery")
    battery_enabled = st.checkbox("Include battery", value=True)
    battery_capacity = st.slider(
        "Battery capacity (kWh)", 20, 400, 160, 10, disabled=not battery_enabled
    )
    battery_power = st.slider(
        "Battery charge/discharge limit (kW)", 5, 100, 45, 5,
        disabled=not battery_enabled,
    )
    initial_soc = st.slider(
        "Initial battery SOC", 0.1, 0.9, 0.55, 0.05, disabled=not battery_enabled
    )

    st.subheader("Diesel backup")
    diesel_enabled = st.checkbox("Include diesel generator", value=True)
    diesel_capacity = st.slider(
        "Diesel rated power (kW)", 5, 100, 50, 5, disabled=not diesel_enabled
    )
    diesel_minimum = st.slider(
        "Minimum stable output (kW)", 0, 30, 8, 1, disabled=not diesel_enabled
    )
    diesel_ramp = st.slider(
        "Ramp-up limit after startup (kW/h)", 1, 40, 12, 1,
        disabled=not diesel_enabled,
    )
    diesel_ramp_down = st.slider(
        "Ramp-down limit (kW/h)", 1, 40, 12, 1,
        disabled=not diesel_enabled,
    )
    diesel_variable_cost = st.number_input(
        "Diesel non-fuel variable cost (currency/kWh)",
        min_value=0.0, value=1.45, step=0.05, disabled=not diesel_enabled,
    )
    diesel_start_cost = st.number_input(
        "Cost per generator start (currency)", min_value=0.0, value=0.0,
        step=1.0, disabled=not diesel_enabled,
    )
    diesel_stop_cost = st.number_input(
        "Cost per generator stop (currency)", min_value=0.0, value=0.0,
        step=1.0, disabled=not diesel_enabled,
    )

# Fixed per-unit synthetic profiles; scaling is explicit and user-adjustable.
pv_shape = [
    0, 0, 0, 0, 0, .06, .23, .44, .65, .81, .90, .95,
    .93, .85, .69, .48, .25, .06, 0, 0, 0, 0, 0, 0,
]
wind_shape = [
    .45, .50, .55, .48, .43, .40, .38, .35, .40, .45, .50, .55,
    .60, .65, .63, .58, .55, .60, .68, .70, .63, .55, .50, .48,
]
load_shape = [
    42, 40, 39, 38, 38, 40, 45, 50, 54, 58, 60, 62,
    61, 60, 58, 57, 60, 66, 70, 68, 60, 52, 47, 44,
]
tariff_shape = [
    .25, .25, .25, .25, .25, .25, .45, .45, .65, .65, .65, .65,
    .65, .65, .45, .45, .65, .85, .85, .85, .65, .45, .35, .25,
]
grid_available = [
    True, True, True, True, True, True, True, True,
    True, True, True, True, True, True, True, True,
    False, False, True, True, True, True, True, True,
]

inputs = EnergySystemInputs(
    pv_generation_kw=[round(value * pv_capacity, 4) for value in pv_shape],
    wind_generation_kw=[round(value * wind_capacity, 4) for value in wind_shape],
    load_kw=[round(value * load_multiplier, 4) for value in load_shape],
    grid_price_per_kwh=[round(value * tariff_multiplier, 4) for value in tariff_shape],
    grid_available=grid_available,
    diesel_available=[True] * 24 if diesel_enabled else None,
)
battery = (
    BatterySpec(
        capacity_kwh=float(battery_capacity),
        max_charge_kw=float(battery_power),
        max_discharge_kw=float(battery_power),
        initial_soc=float(initial_soc),
        min_soc=0.1,
        max_soc=0.9,
        charge_efficiency=0.94,
        discharge_efficiency=0.94,
    )
    if battery_enabled else None
)
diesel = (
    DieselSpec(
        rated_power_kw=float(diesel_capacity),
        variable_cost_per_kwh=float(diesel_variable_cost),
        min_stable_power_kw=float(min(diesel_minimum, diesel_capacity)),
        ramp_up_kw_per_hour=float(diesel_ramp),
        ramp_down_kw_per_hour=float(diesel_ramp_down),
        start_cost_per_start=float(diesel_start_cost),
        stop_cost_per_stop=float(diesel_stop_cost),
    )
    if diesel_enabled else None
)
config = EnergySystemConfig(
    pv_rated_kw=float(pv_capacity),
    wind_rated_kw=float(wind_capacity),
    grid_import_limit_kw=float(grid_limit),
    dt_hours=1.0,
    battery=battery,
    diesel=diesel,
)

try:
    comparison = run_energy_policy_comparison(inputs, config)
except (TypeError, ValueError, RuntimeError) as exc:
    st.error(f"Scenario evaluation failed closed: {exc}")
    st.stop()

policies = [
    ("battery_first", "Battery first"),
    ("grid_first", "Grid first"),
]
summaries = {
    key: comparison[key]["summary"]
    for key, _label in policies
}

st.subheader("1 · Operating outcome")
cols = st.columns(4)
for col, (key, label) in zip(cols, policies):
    summary = summaries[key]
    col.metric(
        f"{label} · estimated energy cost",
        f"{summary['estimated_energy_cost']:,.2f}",
    )
    col.caption(
        f"Unmet load: {summary['unmet_load_kwh']:.2f} kWh · "
        f"Grid import: {summary['grid_import_kwh']:.1f} kWh"
    )

comparison_rows = []
for key, label in policies:
    summary = summaries[key]
    served = summary["load_served_kwh"]
    comparison_rows.append({
        "Policy": label,
        "Estimated energy cost": summary["estimated_energy_cost"],
        "Cost per served kWh": (
            summary["estimated_energy_cost"] / served if served > 0 else None
        ),
        "Unmet load (kWh)": summary["unmet_load_kwh"],
        "Load served (kWh)": served,
        "Grid import (kWh)": summary["grid_import_kwh"],
        "Diesel generation (kWh)": summary["diesel_generation_kwh"],
        "Diesel starts": int(summary["diesel_start_count"]),
        "Renewable curtailment (kWh)": summary["renewable_curtailed_kwh"],
    })
st.dataframe(pd.DataFrame(comparison_rows), use_container_width=True, hide_index=True)

st.caption(
    "Compare service reliability and cost together. A lower estimated bill is not "
    "automatically a better policy if it increases unmet load or equipment stress."
)

st.subheader("2 · Hourly dispatch audit")
selected_policy = st.radio(
    "Inspect policy", ["battery_first", "grid_first"],
    format_func=lambda value: dict(policies)[value], horizontal=True,
)
rows = comparison[selected_policy]["rows"]
frame = pd.DataFrame(rows)
frame.insert(0, "hour", range(24))
chart_columns = [
    "pv_generation_kw", "wind_generation_kw", "load_kw",
    "battery_charge_kw", "battery_discharge_kw",
    "grid_import_kw", "diesel_generation_kw",
]
st.line_chart(frame.set_index("hour")[chart_columns], use_container_width=True)
st.dataframe(
    frame[[
        "timestep", "load_kw", "load_served_kw", "unmet_load_kw",
        "battery_soc", "grid_import_kw", "diesel_generation_kw",
        "diesel_started", "diesel_stopped", "renewable_curtailed_kw",
        "energy_balance_residual_kw",
    ]],
    use_container_width=True,
    hide_index=True,
)

st.subheader("3 · Reproducible export")
report = {
    "data_provenance": "synthetic_demo_data_not_measured_site_data",
    "model_type": "deterministic_rule_based_offline_screening",
    "scenario_assumptions": {
        "pv_rated_kw": pv_capacity,
        "wind_rated_kw": wind_capacity,
        "load_multiplier": load_multiplier,
        "tariff_multiplier": tariff_multiplier,
        "grid_import_limit_kw": grid_limit,
        "battery_enabled": battery_enabled,
        "diesel_enabled": diesel_enabled,
    },
    "policy_summaries": summaries,
    "interpretation": comparison["interpretation"],
    "model_scope": {
        "forecasting_performed": False,
        "global_optimization_performed": False,
        "site_data_validated": False,
        "equipment_control_performed": False,
    },
}
left, right = st.columns(2)
left.download_button(
    "Download hourly audit (CSV)",
    data=frame.to_csv(index=False).encode("utf-8"),
    file_name=f"islandos_{selected_policy}_hourly_audit.csv",
    mime="text/csv",
    use_container_width=True,
)
right.download_button(
    "Download scenario report (JSON)",
    data=json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8"),
    file_name="islandos_energy_system_report.json",
    mime="application/json",
    use_container_width=True,
)

st.warning(
    "Synthetic demonstration only. Tariffs and cost inputs are illustrative currency "
    "values; no customer savings, payback, forecast accuracy, equipment certification, "
    "or operational feasibility is claimed. Real use requires verified time-series data, "
    "confirmed installed limits, site topology, and engineering review."
)
