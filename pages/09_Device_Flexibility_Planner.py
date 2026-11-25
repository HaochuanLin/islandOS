"""Customer-facing demo of critical, semi-flexible and fully-flexible loads."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pandas as pd
import streamlit as st
from islandos_ui.page_header import render_page_header

from islandos_core.app_view_models import (
    PAGE_DEVICE_PLANNER,
    build_device_flexibility_summary,
    build_run_request,
)
from islandos_core.flexible_tasks import DeviceTask
from islandos_core.run_orchestration import device_task_payload, run_device_planner
from islandos_core.site_inputs import device_planner_demo_site

st.set_page_config(page_title="IslandOS | Device Flexibility", page_icon="⚡", layout="wide")
st.title("Device-level load flexibility planner")
st.caption("Demonstration: protect essential services first, then schedule deferrable equipment around the tariff.")

render_page_header(
    question="Which loads can move without breaking essential service?",
    data="An illustrative power budget, tariff and load profiles built into this page.",
    conclusions="How much flexibility exists, and what it costs to use it.",
    limits="A synthetic demonstration: the tariff and profiles are not measured site data.",
)

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

NO_PARTIAL_OUTPUT = (
    "No partial schedule is shown; nothing is written to equipment."
)


def _stop_with_reason(headline: str, exc: BaseException, hint: str) -> None:
    """Turn a planner failure into a readable page error, then stop the page."""
    st.error(f"{headline}: {exc}. {hint}")
    st.caption(NO_PARTIAL_OUTPUT)
    st.stop()


# Two boundaries, because the two failure families deserve different advice.
# (1) The scenario itself cannot be evaluated: task constraints, windows, budgets
#     or tariff/power-profile shapes do not line up. DeviceTask and the scheduler
#     raise ValueError; horizon mismatches can surface as ArithmeticError or
#     IndexError, and malformed page values as TypeError.
try:
    base_load = [8.0] * 24
    pv = [max(0.0, 12.0 * (1.0 - abs(h - 12) / 7.0)) for h in hours]
    wind = [3.0 + 1.5 * ((h % 6) / 5.0) for h in hours]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(hours=h) for h in hours]
    site_assumptions = device_planner_demo_site()
    run_request_view = build_run_request(
        page=PAGE_DEVICE_PLANNER,
        site=site_assumptions,
        timestamps=timestamps,
        history={
            "pv_generation_kw": pv,
            "wind_generation_kw": wind,
            "load_kw": base_load,
            "tariff_per_kwh": prices,
        },
        units={
            "pv_generation_kw": "kW",
            "wind_generation_kw": "kW",
            "load_kw": "kW",
            "tariff_per_kwh": "USD/kWh",
        },
        page_settings={},
        run_settings={"currency": "USD"},
        page_inputs={
            "task_power_budget_kw": task_power_budget,
            "tasks": [device_task_payload(task) for task in tasks],
        },
        provenance="Synthetic demonstration data",
    )
    outputs = run_device_planner(
        tasks=tasks,
        prices=prices,
        task_power_budget_kw=task_power_budget,
        pv_generation_kw=pv,
        wind_generation_kw=wind,
        base_load_kw=base_load,
        site=site_assumptions,
    )
except (ValueError, TypeError, ArithmeticError, IndexError) as exc:
    _stop_with_reason(
        "Device scenario could not be evaluated",
        exc,
        "Adjust the task window, power budget or tariff and rerun.",
    )

# (2) Planning finished but the result does not carry what this page renders:
#     a missing key or an unexpected result shape. Never render a partial view
#     from a half-formed planner result.
try:
    schedule = outputs["schedule"]
    metrics = outputs["replay"]["summary"]
    reference_metrics = outputs["reference_replay"]["summary"]
except (KeyError, TypeError, ArithmeticError, IndexError) as exc:
    _stop_with_reason(
        "Device planner returned an incomplete schedule",
        exc,
        "No partial schedule is shown.",
    )

summary = st.columns(4)
summary[0].metric("Critical energy protected", f"{sum(schedule.critical_power_kw):.0f} kWh")
summary[1].metric("Flexible task energy", f"{sum(x.energy_kwh for x in schedule.schedules if x.load_class != 'critical'):.0f} kWh")
summary[2].metric("Scheduled task energy charge", f"{schedule.total_energy_cost:.2f} USD")
summary[3].metric("Peak task demand", f"{max(schedule.total_power_kw):.1f} kW")

rows = []
for item in schedule.schedules:
    for hour, power in enumerate(item.power_kw):
        rows.append({
            "Hour": hour,
            "Device": item.name,
            "Class": item.load_class,
            "Power (kW)": power,
            "Tariff (USD/kWh)": prices[hour],
            "Energy charge (USD)": power * prices[hour],
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
        "Energy charge (USD)": round(x.energy_cost, 3),
    } for x in schedule.schedules]),
    width="stretch", hide_index=True,
)

chart = pd.DataFrame({
    "Hour": hours,
    "Critical": schedule.critical_power_kw,
    "Semi/fully flexible": [
        sum(x.power_kw[h] for x in schedule.schedules if x.load_class != "critical")
        for h in hours
    ],
    "Residual task capacity": schedule.residual_power_kw,
    "Tariff (USD/kWh)": prices,
})
st.subheader("Hourly demand and remaining task capacity")
st.line_chart(chart.set_index("Hour")[["Critical", "Semi/fully flexible", "Residual task capacity"]])
st.line_chart(chart.set_index("Hour")[["Tariff (USD/kWh)"]])

st.subheader("Shared energy-system replay: like-for-like operating comparison")
# Like-for-like reference: same devices, required energy, windows and generation,
# but place each flexible task at its earliest feasible low-level schedule rather
# than using the time-varying tariff. This is a transparent reference, not a
# claimed real-world operating baseline.
replay = outputs["replay"]
reference_replay = outputs["reference_replay"]

comparison = pd.DataFrame([
    {"Metric": "Grid import (kWh)", "Tariff-aware plan": metrics["grid_import_kwh"], "Earliest-feasible reference": reference_metrics["grid_import_kwh"]},
    {"Metric": "Modeled energy cost", "Tariff-aware plan": metrics["estimated_energy_cost"], "Earliest-feasible reference": reference_metrics["estimated_energy_cost"]},
    {"Metric": "Diesel generation (kWh)", "Tariff-aware plan": metrics["diesel_generation_kwh"], "Earliest-feasible reference": reference_metrics["diesel_generation_kwh"]},
    {"Metric": "Renewable curtailment (kWh)", "Tariff-aware plan": metrics["renewable_curtailed_kwh"], "Earliest-feasible reference": reference_metrics["renewable_curtailed_kwh"]},
    {"Metric": "Battery throughput (kWh)", "Tariff-aware plan": metrics["battery_throughput_kwh"], "Earliest-feasible reference": reference_metrics["battery_throughput_kwh"]},
    {"Metric": "Critical unmet energy (kWh)", "Tariff-aware plan": metrics["critical_unmet_load_kwh"], "Earliest-feasible reference": reference_metrics["critical_unmet_load_kwh"]},
    {"Metric": "Flexible load shed (kWh)", "Tariff-aware plan": metrics["flexible_load_shed_kwh"], "Earliest-feasible reference": reference_metrics["flexible_load_shed_kwh"]},
    {"Metric": "Peak grid import (kW)", "Tariff-aware plan": metrics["peak_grid_import_kw"], "Earliest-feasible reference": reference_metrics["peak_grid_import_kw"]},
])
st.dataframe(comparison, width="stretch", hide_index=True)
st.caption(
    "Both cases use the same device requirements, time windows, residual task budget, PV/wind profiles and grid limits. "
    "The reference is an earliest-feasible scheduling heuristic, not historical customer operation. "
    "This is a synthetic scenario comparison, not measured savings or a global optimum."
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Grid import", f"{metrics['grid_import_kwh']:.1f} kWh")
c2.metric("Replayed system energy cost", f"{metrics['estimated_energy_cost']:.2f} USD")
c3.metric("Critical unmet", f"{metrics['critical_unmet_load_kwh']:.2f} kWh")
c4.metric("Flexible load shed", f"{metrics['flexible_load_shed_kwh']:.2f} kWh")
st.caption(
    "The scheduled-task energy charge above covers only the energy used by the scheduled tasks. "
    "The replayed system cost here also includes the site's existing load and the shared "
    "PV/wind/battery/grid/diesel dispatch, so the two totals are deliberately different "
    "and are not expected to match."
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

device_result_view = build_device_flexibility_summary(
    result=schedule.to_dict(),
    metrics=metrics,
    reference_metrics=reference_metrics,
    currency="USD",
)
report = {
    "page": "device_flexibility_planner",
    "application_views": {"request": run_request_view, "result": device_result_view, "annual": None},
}
st.download_button(
    "Export application views JSON",
    json.dumps(report, indent=2, sort_keys=True, allow_nan=False).encode("utf-8"),
    file_name="islandos_device_flexibility_report.json",
    mime="application/json",
)
