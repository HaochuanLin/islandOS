"""Streamlit experiment for the UI-independent IslandOS onboarding service."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from islandos_core.onboarding import (
    CANONICAL_UNITS,
    evaluate_task_readiness,
    inspect_csv_bytes,
)

st.set_page_config(page_title="IslandOS Data Onboarding Lab", page_icon="🧭", layout="wide")
st.title("IslandOS · Data Onboarding Lab")
st.caption("Streamlit product laboratory · shared core service · offline import only")

st.info(
    "This page tests the future desktop onboarding workflow. Files are processed in this "
    "app session and are not saved as a customer project. Automatic column recognition is "
    "a suggestion, not proof of measurement accuracy. No missing values are filled."
)

uploaded = st.file_uploader(
    "Upload an existing energy-data CSV",
    type=["csv"],
    help="UTF-8 CSV with one timestamp column and one or more supported energy signals.",
)
source_type = st.selectbox(
    "What kind of data is this?",
    ["customer_provided", "measured", "public_reanalysis", "synthetic", "forecast", "vendor_specification", "inferred"],
    format_func=lambda value: {
        "customer_provided": "Customer-provided (source not independently verified)",
        "measured": "Measured / telemetry export",
        "public_reanalysis": "Public / reanalysis dataset",
        "synthetic": "Synthetic demonstration data",
        "forecast": "Forecast output",
        "vendor_specification": "Vendor specification",
        "inferred": "Inferred / estimated",
    }[value],
)
interval_choice = st.selectbox(
    "Expected sampling interval",
    ["Do not enforce", "5 minutes", "15 minutes", "30 minutes", "60 minutes", "1440 minutes"],
    index=4,
)
interval_minutes = None if interval_choice == "Do not enforce" else int(interval_choice.split()[0])

if uploaded is None:
    st.markdown(
        """
        **What IslandOS attempts to recognize automatically**
        - Load, PV, wind, grid import/export and diesel generation
        - Battery charge, discharge and state of charge
        - Electricity tariff, fuel consumption and ambient temperature
        - Timestamp, time zone, sampling interval and missing values
        """
    )
    st.stop()

raw = uploaded.getvalue()
try:
    initial = inspect_csv_bytes(
        raw,
        source_type=source_type,
        expected_interval_minutes=interval_minutes,
        now=datetime.now(timezone.utc),
    )
except (TypeError, ValueError) as exc:
    st.error(f"Could not inspect this file: {exc}")
    st.stop()

st.subheader("1 · Automatic recognition")
left, right, third = st.columns(3)
left.metric("Rows detected", initial["row_count"])
right.metric("Signals recognized", initial["recognized_signal_count"])
third.metric("File SHA-256", initial["artifact"]["sha256"][:12] + "…")
st.caption(
    f"Initial result: **{initial['status']}** · "
    f"{initial['error_count']} errors · {initial['warning_count']} review items"
)

canonical_fields = list(CANONICAL_UNITS)
unit_choices = {
    "load_kw": ["kW", "W", "MW"],
    "pv_power_kw": ["kW", "W", "MW"],
    "wind_power_kw": ["kW", "W", "MW"],
    "grid_import_kw": ["kW", "W", "MW"],
    "grid_export_kw": ["kW", "W", "MW"],
    "battery_charge_kw": ["kW", "W", "MW"],
    "battery_discharge_kw": ["kW", "W", "MW"],
    "battery_soc_pct": ["%"],
    "tariff_per_kwh": ["currency/kWh"],
    "diesel_power_kw": ["kW", "W", "MW"],
    "diesel_fuel_lph": ["L/h"],
    "temperature_c": ["degC"],
}

unmapped_columns = [
    issue["column"] for issue in initial["issues"]
    if issue["code"] == "unrecognized_column" and issue.get("column")
]
column_overrides = {}
source_unit_overrides = {}

if unmapped_columns:
    st.subheader("2 · Confirm unrecognized columns")
    st.caption("IslandOS will not guess these fields. Choose a meaning only when you know what the source column represents.")
    for index, column in enumerate(unmapped_columns):
        selected = st.selectbox(
            f"Map source column: {column}",
            ["Do not import"] + canonical_fields,
            format_func=lambda value: "Do not import" if value == "Do not import" else f"{value} ({CANONICAL_UNITS[value]})",
            key=f"onboarding_map_{index}_{column}",
        )
        if selected != "Do not import":
            column_overrides[column] = selected
            unit = st.selectbox(
                f"Confirm source unit: {column}",
                unit_choices[selected],
                key=f"onboarding_unit_unmapped_{index}_{column}",
            )
            source_unit_overrides[column] = unit

auto_mappings = initial["column_mappings"]
needs_unit = [
    item for item in auto_mappings
    if item["detected_source_unit"] is None
]
if needs_unit:
    st.subheader("3 · Confirm missing units")
    st.caption("A familiar column name is not enough to establish its unit. Confirm the unit used by the source file.")
    for index, item in enumerate(needs_unit):
        field = item["canonical_field"]
        unit = st.selectbox(
            f"Source unit for {item['source_column']} → {field}",
            unit_choices[field],
            key=f"onboarding_unit_auto_{index}_{item['source_column']}",
        )
        source_unit_overrides[item["source_column"]] = unit

if column_overrides or source_unit_overrides:
    try:
        report = inspect_csv_bytes(
            raw,
            source_type=source_type,
            column_overrides=column_overrides,
            source_unit_overrides=source_unit_overrides,
            expected_interval_minutes=interval_minutes,
            now=datetime.now(timezone.utc),
        )
    except (TypeError, ValueError) as exc:
        st.error(f"Mapping review failed: {exc}")
        st.stop()
else:
    report = initial

st.subheader("4 · Data quality review")
if report["status"] == "valid":
    st.success("Import structure passed automatic checks. This does not certify sensor accuracy or site suitability.")
elif report["status"] == "needs_review":
    st.warning("Import can be inspected, but one or more fields need review before downstream use.")
else:
    st.error("Import is blocked. Correct the errors before using this dataset.")

if report["issues"]:
    issue_frame = pd.DataFrame(report["issues"])
    st.dataframe(issue_frame, use_container_width=True, hide_index=True)
else:
    st.write("No structural issues detected.")

if report["column_mappings"]:
    st.markdown("**Canonical field mapping**")
    st.dataframe(pd.DataFrame(report["column_mappings"]), use_container_width=True, hide_index=True)
if report["preview"]:
    st.markdown("**Normalized preview (first 10 rows)**")
    preview_rows = [
        {"timestamp_utc": row["timestamp_utc"], **row["values"]}
        for row in report["preview"]
    ]
    st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

st.subheader("5 · Task-specific model readiness")
task = st.selectbox(
    "What do you want to do with this data?",
    ["exploration", "forecasting", "dispatch_optimization"],
    format_func=lambda value: {
        "exploration": "Explore and inspect data",
        "forecasting": "Run a forecasting baseline screen",
        "dispatch_optimization": "Screen dispatch optimization readiness",
    }[value],
)
confirmed_constraints = {}
if task == "dispatch_optimization":
    st.caption("Optimization screening requires explicit confirmation of site operating limits; these confirmations are not a safety certification.")
    confirmed_constraints["asset_limits"] = st.checkbox("I have confirmed installed asset operating limits")
    confirmed_constraints["critical_load_policy"] = st.checkbox("I have confirmed critical-load / load-shedding policy")
    confirmed_constraints["grid_import_limit"] = st.checkbox("I have confirmed grid import limits and interconnection constraints")
readiness = evaluate_task_readiness(
    report,
    task,
    confirmed_constraints=confirmed_constraints,
)
if readiness["can_run"]:
    st.success(f"Ready for {task.replace('_', ' ')} screening")
else:
    st.error("This task is blocked until its required inputs and confirmations are available.")
for blocker in readiness.get("blockers", []):
    st.write(f"- **Blocker:** {blocker}")
for warning in readiness.get("warnings", []):
    st.write(f"- **Warning:** {warning}")

st.subheader("6 · Export the review record")
st.caption("The report records the exact input file hash, source label, mappings, issues and preview. The original file is not modified.")
st.download_button(
    "Download onboarding report (JSON)",
    data=json.dumps({"import_report": report, "task_readiness": readiness}, indent=2, ensure_ascii=False).encode("utf-8"),
    file_name="islandos_onboarding_report.json",
    mime="application/json",
    use_container_width=True,
)
