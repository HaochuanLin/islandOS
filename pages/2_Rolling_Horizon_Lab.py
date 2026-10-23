"""Interactive, offline rolling-horizon dispatch lab for IslandOS."""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from experiments.rolling_horizon_dispatch import (
    generate_synthetic_scenario_csv,
    parse_scenario_csv,
    simulate_rolling,
)

st.title("Rolling-horizon energy–water dispatch lab")
st.caption("Research prototype · offline scenario analysis only · no live equipment control")
st.warning(
    "The built-in example is synthetic. Uploaded CSVs are processed in this app session; "
    "missing values are not imputed. The perfect-information policy is a non-deployable "
    "reference, not a forecast-based operating recommendation."
)

source = st.radio(
    "Scenario source",
    ["Synthetic demo (illustrative)", "Upload paired hourly CSV"],
    horizontal=True,
    key="rolling_lab_source",
)
uploaded = None
if source == "Upload paired hourly CSV":
    uploaded = st.file_uploader(
        "Upload hourly dispatch CSV",
        type=["csv"],
        key="rolling_lab_upload",
        help=(
            "Required columns: timestamp_utc, actual_surplus_kw, forecast_surplus_kw, "
            "water_demand_m3, cooling_demand_kw_th. Optional: forecast_water_demand_m3."
        ),
    )
    st.download_button(
        "Download CSV template (24 synthetic hours)",
        data=generate_synthetic_scenario_csv(24).encode("utf-8"),
        file_name="islandos_rolling_dispatch_template.csv",
        mime="text/csv",
    )
    if uploaded is None:
        st.info("Upload a CSV to validate its timestamps, units, and numeric fields.")
        st.stop()
    raw = uploaded.getvalue()
    source_label = f"Uploaded file: {uploaded.name}"
    source_type = "user_uploaded_unverified"
else:
    raw = generate_synthetic_scenario_csv(24).encode("utf-8")
    source_label = "Synthetic demo (illustrative)"
    source_type = "synthetic"

input_sha256 = hashlib.sha256(raw).hexdigest()
signature = hashlib.sha256(source_label.encode("utf-8") + b"\0" + raw).hexdigest()
previous_signature = st.session_state.get("rolling_lab_signature")
if previous_signature != signature:
    st.session_state.pop("rolling_lab_results", None)
    st.session_state["rolling_lab_signature"] = signature

try:
    parsed = parse_scenario_csv(raw.decode("utf-8-sig"), name=source_label)
except (UnicodeDecodeError, ValueError) as exc:
    st.error(f"CSV validation failed: {exc}")
    st.stop()

scenario = parsed["scenario"]
timestamps = list(parsed["timestamps_utc"])
input_frame = pd.DataFrame({
    "timestamp_utc": timestamps,
    "actual_surplus_kw": list(scenario.available_surplus_kw),
    "forecast_surplus_kw": list(parsed["forecast_surplus_kw"]),
    "water_demand_m3": list(scenario.water_demand_m3_per_hour),
    "cooling_demand_kw_th": list(scenario.cooling_demand_kw_th),
})
if parsed["forecast_water_demand_m3_per_hour"] is not None:
    input_frame["forecast_water_demand_m3"] = list(parsed["forecast_water_demand_m3_per_hour"])

st.caption(f"Validated source: **{source_label}** · {len(input_frame)} continuous hourly rows")
with st.expander("Preview validated input", expanded=False):
    st.dataframe(input_frame.head(24), use_container_width=True, hide_index=True)
    chart_input = input_frame.set_index("timestamp_utc")
    st.subheader("Available surplus power (kW)")
    st.line_chart(chart_input[["actual_surplus_kw", "forecast_surplus_kw"]])
    st.subheader("Water demand (m³ per hour)")
    st.line_chart(chart_input[["water_demand_m3"]])
    st.subheader("Cooling demand (kW thermal)")
    st.line_chart(chart_input[["cooling_demand_kw_th"]])

if st.button("Run four-policy rolling comparison", type="primary", use_container_width=True):
    policies = ("rolling", "ro_first", "ice_first", "perfect_information")
    results = {}
    try:
        for policy in policies:
            results[policy] = simulate_rolling(
                scenario,
                parsed["forecast_surplus_kw"],
                policy=policy,
                forecast_water_demand_m3_per_hour=parsed["forecast_water_demand_m3_per_hour"],
            )
        st.session_state["rolling_lab_results"] = results
    except (ValueError, RuntimeError, ArithmeticError) as exc:
        st.session_state.pop("rolling_lab_results", None)
        st.error(f"Dispatch comparison failed: {exc}")

results = st.session_state.get("rolling_lab_results")
if results:
    labels = {
        "rolling": "Rolling horizon",
        "ro_first": "RO first",
        "ice_first": "Cold storage first",
        "perfect_information": "Perfect-information reference",
    }
    summary_rows = []
    for policy, result in results.items():
        summary_rows.append({
            "policy": labels[policy],
            "water_unmet_m3": result["water_unmet_m3"],
            "cooling_unmet_kwh_th": result["cooling_unmet_kwh_th"],
            "renewable_flexible_load_kwh": result["renewable_flexible_load_kwh"],
            "remaining_surplus_kwh": result["remaining_surplus_kwh"],
            "constraint_violation_hours": result["constraint_violation_hours"],
            "final_water_inventory_m3": result["final_water_inventory_m3"],
            "final_cold_inventory_kwh_th": result["final_cold_inventory_kwh_th"],
        })
    summary = pd.DataFrame(summary_rows)
    st.subheader("Policy comparison")
    st.dataframe(summary, use_container_width=True, hide_index=True)
    summary_export = summary.assign(
        source_type=source_type,
        source_label=source_label,
        input_sha256=input_sha256,
    )
    st.download_button(
        "Download policy comparison CSV (with provenance)",
        data=summary_export.to_csv(index=False).encode("utf-8"),
        file_name="islandos_rolling_policy_comparison.csv",
        mime="text/csv",
    )

    selected_label = st.selectbox(
        "Inspect hourly audit",
        [labels[key] for key in results],
        key="rolling_lab_selected_policy",
    )
    selected_policy = next(key for key, label in labels.items() if label == selected_label)
    audit = pd.DataFrame(results[selected_policy]["hourly_audit"])
    st.subheader(f"Hourly operating audit — {selected_label}")
    st.dataframe(audit, use_container_width=True, hide_index=True)
    audit_export = audit.assign(
        source_type=source_type,
        source_label=source_label,
        input_sha256=input_sha256,
    )
    st.download_button(
        "Download hourly audit CSV (with provenance)",
        data=audit_export.to_csv(index=False).encode("utf-8"),
        file_name=f"islandos_rolling_audit_{selected_policy}.csv",
        mime="text/csv",
    )
    violations = results[selected_policy]["constraint_violation_hours"]
    if violations:
        st.warning(
            f"{violations} hour(s) contain modelled constraint violations. "
            "Review the hourly audit; do not treat this schedule as field-ready."
        )
    else:
        st.info(
            "No modelled constraint-violation hours were reported for this policy. "
            "That is a simulation result, not a hardware safety certification."
        )
else:
    st.info("Run the comparison to inspect unmet demand, surplus use, inventories, and constraint audits.")
