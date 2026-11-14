"""Customer-facing demo of critical, semi-flexible and fully-flexible loads."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from islandos_core.energy_system import BatterySpec, DieselSpec, EnergySystemConfig, EnergySystemInputs, dispatch_energy_system
from islandos_core.flexible_tasks import DeviceTask, schedule_device_tasks
from islandos_core.flexible_task_dispatch import attach_device_task_schedule

st.set_page_config(page_title="IslandOS | Device Flexibility", page_icon="⚡", layout="wide")
st.title("Device-level load flexibility planner")
st.caption("Stage H–J demonstration: protect essential services, then schedule deferrable equipment.")

st.info(
    "Synthetic demonstration only. The power budget, tariff, load profiles and generation are illustrative; "
    "they are not measured site data, a verified tariff, a customer saving, or equipment-control commands."
)

hours = list(range(24))
prices = [0.09 if h < 6 else 0.25 if 17 <= h <= 21 else 0.16 for h in hours]
# This budget is explicitly residual capacity after the site's pre-existing fixed load.
task_power_budget = [10.0] * 24

clinic_profile = tuple([3.0] * 24)
tasks = [
    DeviceTask("clinic-critical", "Clinic essential circuits", "critical", 3.0, 72.0,
               0, 24, interruptible=False, priority=0,
               critical_power_profile_kw=clinic_profile),
    DeviceTask("ice-maker", "Ice production", "semi_flexible", 3.0, 9.0,
               8, 18, minimum_run_steps=3, interruptible=False, priority=10),
    DeviceTask("water-pump", "Water transfer pumping", "fully_flexible", 2.0, 8.0,
               0, 24, minimum_run_steps=1, interruptible=True, priority=20),
]

try:
    schedule = schedule_device_tasks(tasks, prices, task_power_budget)
except ValueError as exc:
    st.error(f"Scenario infeasible: {exc}")
    st.stop()

summary = st.columns(4)
summary[0].metric("Critical energy protected", f"{sum(schedule.critical_power_kw):.0f} kWh")
summary[1].metric("Flexible task energy", f"{sum(x.energy_kwh for x in schedule.schedules if x.load_class != 'critical'):.0f} kWh")
summary[2].metric("Scheduled energy charge", f"{schedule.total_energy_cost:.2f}")
summary[3].metric("Peak task demand", f"{max(schedule.total_power_kw):.1f} kW")

rows = []
for item in schedule.schedules:
    for hour, power in enumerate(item.power_kw):
        rows.append({
            "Hour": hour,
            "Device": item.name,
            "Class": item.load_class,
            "Power (kW)": power,
            "Tariff": prices[hour],
            "Energy charge": power * prices[hour],
        })
detail = pd.DataFrame(rows)
st.subheader("Per-device schedule")
st.dataframe(
    pd.DataFrame([{
        "Device": x.name,
        "Load class": x.load_class.replace("_", " ").title(),
        "Required energy (kWh)": x.energy_requirement_kwh,
        "Scheduled energy (kWh)": x.energy_kwh,
        "Operating intervals": ", ".join(str(v) for v in x.operating_steps),
        "Energy charge": round(x.energy_cost, 3),
    } for x in schedule.schedules]),
    use_container_width=True, hide_index=True,
)

chart = pd.DataFrame({
    "Hour": hours,
    "Critical": schedule.critical_power_kw,
    "Semi/fully flexible": [
        sum(x.power_kw[h] for x in schedule.schedules if x.load_class != "critical")
        for h in hours
    ],
    "Residual task capacity": schedule.residual_power_kw,
    "Tariff": prices,
})
st.subheader("Hourly demand and remaining task capacity")
st.line_chart(chart.set_index("Hour")[["Critical", "Semi/fully flexible", "Residual task capacity"]])
st.line_chart(chart.set_index("Hour")[["Tariff"]])

st.subheader("Shared energy-system replay")
base_load = [8.0] * 24
pv = [max(0.0, 12.0 * (1.0 - abs(h - 12) / 7.0)) for h in hours]
wind = [3.0 + 1.5 * ((h % 6) / 5.0) for h in hours]
energy_inputs = EnergySystemInputs(
    pv_generation_kw=pv,
    wind_generation_kw=wind,
    load_kw=base_load,
    grid_price_per_kwh=prices,
    grid_available=[True] * 24,
    diesel_available=[True] * 24,
)
integrated_inputs = attach_device_task_schedule(energy_inputs, schedule)
replay = dispatch_energy_system(
    integrated_inputs,
    EnergySystemConfig(
        pv_rated_kw=12.0,
        wind_rated_kw=4.5,
        grid_import_limit_kw=20.0,
        battery=BatterySpec(
            capacity_kwh=12.0, max_charge_kw=4.0, max_discharge_kw=4.0,
            initial_soc=0.60, min_soc=0.10, max_soc=0.95,
        ),
        diesel=DieselSpec(
            rated_power_kw=5.0, variable_cost_per_kwh=0.35,
            ramp_up_kw_per_hour=5.0,
        ),
    ),
)
metrics = replay["summary"]

# Like-for-like reference: same devices, required energy, windows and generation,
# but place each flexible task at its earliest feasible low-level schedule rather
# than using the time-varying tariff. This is a transparent reference, not a
# claimed real-world operating baseline.
reference_schedule = schedule_device_tasks(tasks, [1.0] * 24, task_power_budget)
reference_inputs = attach_device_task_schedule(energy_inputs, reference_schedule)
reference_replay = dispatch_energy_system(
    reference_inputs,
    EnergySystemConfig(
        pv_rated_kw=12.0,
        wind_rated_kw=4.5,
        grid_import_limit_kw=20.0,
        battery=BatterySpec(
            capacity_kwh=12.0, max_charge_kw=4.0, max_discharge_kw=4.0,
            initial_soc=0.60, min_soc=0.10, max_soc=0.95,
        ),
        diesel=DieselSpec(
            rated_power_kw=5.0, variable_cost_per_kwh=0.35,
            ramp_up_kw_per_hour=5.0,
        ),
    ),
)
reference_metrics = reference_replay["summary"]

st.subheader("Like-for-like operating comparison")
comparison = pd.DataFrame([
    {"Metric": "Grid import (kWh)", "Tariff-aware plan": metrics["grid_import_kwh"], "Earliest-feasible reference": reference_metrics["grid_import_kwh"]},
    {"Metric": "Modeled energy cost", "Tariff-aware plan": metrics["estimated_energy_cost"], "Earliest-feasible reference": reference_metrics["estimated_energy_cost"]},
    {"Metric": "Critical unmet energy (kWh)", "Tariff-aware plan": metrics["critical_unmet_load_kwh"], "Earliest-feasible reference": reference_metrics["critical_unmet_load_kwh"]},
    {"Metric": "Flexible load shed (kWh)", "Tariff-aware plan": metrics["flexible_load_shed_kwh"], "Earliest-feasible reference": reference_metrics["flexible_load_shed_kwh"]},
    {"Metric": "Peak grid import (kW)", "Tariff-aware plan": max(row["grid_import_kw"] for row in replay["rows"]), "Earliest-feasible reference": max(row["grid_import_kw"] for row in reference_replay["rows"])},
])
st.dataframe(comparison, use_container_width=True, hide_index=True)
st.caption(
    "Both cases use the same device requirements, time windows, residual task budget, PV/wind profiles and grid limits. "
    "The reference is an earliest-feasible scheduling heuristic, not historical customer operation. "
    "This is a synthetic scenario comparison, not measured savings or a global optimum."
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Grid import", f"{metrics['grid_import_kwh']:.1f} kWh")
c2.metric("Energy cost", f"{metrics['estimated_energy_cost']:.2f}")
c3.metric("Critical unmet", f"{metrics['critical_unmet_load_kwh']:.2f} kWh")
c4.metric("Flexible load shed", f"{metrics['flexible_load_shed_kwh']:.2f} kWh")
st.caption(
    "The device schedule is passed into the same chronological PV/wind/battery/grid/diesel energy accounting used by IslandOS. "
    "This example uses a transparent rule-based dispatch baseline, not a global optimum."
)

device_power = {
    item.task_id: item.power_kw for item in schedule.schedules
}
csv = pd.DataFrame({
    "hour": hours,
    "tariff_per_kwh": prices,
    "clinic_essential_kw": device_power["clinic-critical"],
    "ice_production_kw": device_power["ice-maker"],
    "water_transfer_pumping_kw": device_power["water-pump"],
    "critical_load_kw": schedule.critical_power_kw,
    "total_device_task_kw": schedule.total_power_kw,
    "residual_task_budget_kw": schedule.residual_power_kw,
    "pv_generation_kw": pv,
    "wind_generation_kw": wind,
    "grid_import_kw": [x["grid_import_kw"] for x in replay["rows"]],
    "reference_grid_import_kw": [x["grid_import_kw"] for x in reference_replay["rows"]],
    "battery_charge_kw": [x["battery_charge_kw"] for x in replay["rows"]],
    "battery_discharge_kw": [x["battery_discharge_kw"] for x in replay["rows"]],
    "diesel_generation_kw": [x["diesel_generation_kw"] for x in replay["rows"]],
    "flexible_load_shed_kw": [x["flexible_load_shed_kw"] for x in replay["rows"]],
    "reference_flexible_load_shed_kw": [x["flexible_load_shed_kw"] for x in reference_replay["rows"]],
})
st.download_button(
    "Export auditable schedule CSV",
    csv.to_csv(index=False).encode("utf-8"),
    file_name="islandos_device_flexibility_demo.csv",
    mime="text/csv",
)
