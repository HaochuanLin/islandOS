"""Customer-facing, forecast-led decision dashboard for the generic IslandOS platform.

The default scenario is synthetic. Results are offline planning estimates, not
measured customer savings, a site-validated forecast, or equipment commands.
"""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict
import hashlib
import html
import json

import pandas as pd
import streamlit as st
import altair as alt
from islandos_ui.upload_guard import reject_upload
from islandos_ui.upload_recovery import offer_schema_conformant_csv
from islandos_ui.page_header import render_page_header, render_page_title
from islandos_ui.project_context_selector import render_optional_project_selector
from islandos_ui.streamlit_theme import apply_theme
from islandos_ui.table import render_table
from islandos_ui.customer_workflow import (
    build_input_fingerprint,
    render_customer_workflow,
    render_page_upload_handoff,
)
from islandos_ui.annual_economics_panel import (
    DEMONSTRATION_VALUES,
    annual_inputs_supplied,
    annual_source_for,
    render_annual_economics_basis,
)

from islandos_core.site_inputs import (
    BATTERY_INITIAL_SOC,
    BATTERY_MAX_SOC,
    BATTERY_MIN_SOC,
    SiteAssumptions,
)
from islandos_core.app_view_models import build_run_request, build_run_result_summary
from islandos_core.customer_dashboard import parse_customer_history_csv
from islandos_core.demo_site_history import (
    build_customer_site_history,
    canonical_history_sha256,
    demo_anchor_for_hour,
)
from islandos_core.demo_clock_defaults import DEMO_CLOCK_DEFAULT_DATE, DEMO_CLOCK_DEFAULT_HOUR
from islandos_core.canonical_run import create_run_manifest, deterministic_run_id
from islandos_core.session_dataset import clear_session_dataset, read_session_dataset
from islandos_core.forecast_engine import forecast_signals
from islandos_core.investment_economics import (
    bind_annual_economics_to_run,
    evaluate_investment_economics,
    verify_investment_economics_binding,
)
from islandos_core.run_orchestration import run_customer_dashboard
from islandos_core.operator_decision import (
    build_operator_decision_record,
    verify_operator_decision_record,
)

st.set_page_config(
    page_title="IslandOS | Customer Decision Dashboard",
    page_icon="⚡",
    layout="wide",
)

apply_theme()
render_page_title(
    "",
    "Decision dashboard",
    "Forecast → compare operating policies → review cost and reliability trade-offs.",
    compact=True,
)

now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

with st.sidebar:
    st.subheader("Inputs and assumptions")
    render_optional_project_selector(
        st.session_state, widget_key="project_context_dashboard",
    )
    currency = st.text_input("Currency label", value="USD").strip() or "currency"
    demand_scale = st.slider("Essential load level", 0.6, 1.6, 1.0, 0.05)
    tariff_scale = st.slider("Electricity tariff level", 0.5, 2.0, 1.0, 0.05)
    battery_capacity = st.slider("Battery capacity (kWh)", 0, 240, 80, 10)
    battery_power = st.slider("Battery charge/discharge limit (kW)", 0, 60, 20, 5)
    cost_priority = st.slider("Cost priority", 0.0, 1.0, 0.7, 0.05)
    st.caption("The remaining objective weight is assigned to reliability.")
    pv_capacity = st.number_input("Installed PV capacity (kW)", min_value=0.0, value=40.0, step=1.0)
    wind_capacity = st.number_input("Installed wind capacity (kW)", min_value=0.0, value=20.0, step=1.0)
    grid_limit = st.number_input("Grid import limit (kW)", min_value=0.0, value=100.0, step=5.0)
    site_csv = st.file_uploader("Hourly site history CSV (optional)", type=["csv"])
    st.caption(
        "Uploads are processed by the hosted app server. Share only data you are "
        "authorized to share, and redact sensitive exports."
    )
    shared_dataset, dataset_error = read_session_dataset(st.session_state)
    if dataset_error:
        st.warning(
            "The shared session dataset was discarded: "
            f"{dataset_error}. Upload the file again on this page or use the shared "
            "upload control if you still need it."
        )
    if shared_dataset is not None:
        st.caption(f"Session dataset available: {shared_dataset['file_name']}")
        if st.button("Clear session dataset", key="clear_shared_dataset_dashboard"):
            clear_session_dataset(st.session_state)
            st.rerun()
    if site_csv is not None:
        st.caption("The page-specific upload takes priority over the shared session dataset.")
    st.divider()
    st.subheader("Demo clock")
    demo_date = st.date_input(
        "Demo date (UTC)", value=DEMO_CLOCK_DEFAULT_DATE, key="demo_date_dashboard",
        help=(
            "The date the synthetic window ends on. Defaults to 2026-11-22, frozen so "
            "the default screen is reproducible; the load formula carries a weekday "
            "term, so the date matters here as well as the hour."
        ),
    )
    demo_hour = st.slider(
        "Demo clock (UTC hour)", 0, 23, DEMO_CLOCK_DEFAULT_HOUR, key="demo_clock_hour_dashboard",
        help=(
            "Pins the synthetic default history to this UTC hour so a recorded cost "
            "can be reproduced. It has no effect on an uploaded CSV."
        ),
    )
    st.caption(
        "Synthetic default only, frozen at 2026-11-22 14:00 UTC; move either control "
        "to reproduce another hour. An uploaded CSV carries its own timestamps."
    )
    st.divider()
    st.subheader("Investment assumptions")
    st.caption(
        "A demonstration set of annual bills, O&M and CAPEX is pre-filled so the screen is "
        "readable on first open. Every field is editable; set the baseline bill and the CAPEX "
        "to zero to see the withheld state instead."
    )
    baseline_annual_bill = st.number_input(
        "Baseline annual energy bill", min_value=0.0,
        value=DEMONSTRATION_VALUES["baseline_annual_bill"], step=1000.0,
    )
    proposed_annual_bill = st.number_input(
        "Proposed annual energy bill", min_value=0.0,
        value=DEMONSTRATION_VALUES["proposed_annual_bill"], step=1000.0,
    )
    incremental_om = st.number_input(
        "Annual incremental O&M cost (+ cost / − saving)", min_value=-10000000.0, max_value=10000000.0,
        value=DEMONSTRATION_VALUES["annual_incremental_om"], step=500.0,
    )
    upfront_capex = st.number_input(
        "Installed equipment CAPEX", min_value=0.0,
        value=DEMONSTRATION_VALUES["upfront_capex"], step=5000.0,
    )
    project_life = st.slider("Project evaluation life (years)", 1, 30, 10)
    discount_rate_pct = st.slider("Discount rate (%)", 0.0, 30.0, 8.0, 0.5)
    energy_saving_escalation_pct = st.slider("Annual energy-saving escalation (%)", -10.0, 20.0, 0.0, 0.5)
    om_escalation_pct = st.slider("Annual O&M escalation (%)", -10.0, 20.0, 0.0, 0.5)
    has_replacement = st.checkbox("Include a future equipment replacement")
    replacement_year = st.number_input("Replacement year", min_value=1, max_value=int(project_life), value=min(8, int(project_life)), step=1) if has_replacement else None
    replacement_cost = st.number_input("Replacement cost", min_value=0.0, value=0.0, step=1000.0) if has_replacement else 0.0
    residual_value = st.number_input("Residual value at end of project", min_value=0.0, value=0.0, step=1000.0)

demo_anchor = demo_anchor_for_hour(now, int(demo_hour), demo_date=demo_date)
history = {"pv_power": [], "wind_power": [], "essential_load": [], "electricity_price": []}
source_sha256 = None
history_sha256 = None
source_label = "Synthetic demonstration data"
shared_payload = None
shared_name = "session-shared CSV"
if site_csv is not None:
    shared_payload = site_csv.getvalue()
    shared_name = site_csv.name
elif shared_dataset is not None:
    shared_payload = shared_dataset["payload"]
    shared_name = shared_dataset["file_name"]
if shared_payload is not None:
    try:
        uploaded = parse_customer_history_csv(shared_payload, source_name=shared_name)
        history_stamps = list(uploaded.timestamps_utc)
        history = {name: list(values) for name, values in uploaded.signals.items()}
        source_sha256 = uploaded.source_sha256
        history_sha256 = uploaded.source_sha256
        prefix = "User-uploaded" if site_csv is not None else "Session-shared"
        source_label = f"{prefix}: {uploaded.source_name} (not independently verified)"
    except ValueError as exc:
        reject_upload("Site history CSV", exc)
        offer_schema_conformant_csv()
        st.stop()
else:
    # Same canonical generator and nominal site as page 06. The two customer
    # controls are applied after generation; at their defaults the timestamps
    # and four arrays are identical to page 06, so the history hash matches.
    synthetic = build_customer_site_history(
        demo_anchor,
        demand_scale=float(demand_scale),
        tariff_scale=float(tariff_scale),
    )
    history_stamps = list(synthetic.timestamps)
    history = {
        "pv_power": list(synthetic.pv_power_kw),
        "wind_power": list(synthetic.wind_power_kw),
        "essential_load": list(synthetic.load_kw),
        "electricity_price": list(synthetic.tariff_per_kwh),
    }
    history_sha256 = canonical_history_sha256(
        timestamps=synthetic.timestamps,
        pv_power_kw=synthetic.pv_power_kw,
        wind_power_kw=synthetic.wind_power_kw,
        load_kw=synthetic.load_kw,
        tariff_per_kwh=synthetic.tariff_per_kwh,
    )

demo_note = f" · Demo {int(demo_hour):02d}:00" if shared_payload is None else ""
summary_source = "Synthetic demo" if shared_payload is None else source_label
window_start = pd.Timestamp(history_stamps[0]).strftime("%Y-%m-%d")
window_end = pd.Timestamp(history_stamps[-1]).strftime("%Y-%m-%d")
st.caption(
    f"**Data source:** {summary_source} · **Window:** "
    f"{window_start} → {window_end} UTC · {len(history_stamps)} h · "
    f"**Currency:** {currency}{demo_note}"
)
render_page_header(
    question="Given a site's history, what does the forecast imply for the cost and reliability trade-off?",
    data="A synthetic default history, or your uploaded CSV/XLSX (session-only).",
    conclusions="Which operating policy is worth comparing next, and how much of the gap is forecast-driven.",
    limits="Offline planning estimates, not measured customer savings or a site-validated forecast.",
    collapsible=True,
)
if site_csv is not None:
    render_page_upload_handoff(
        page_key="decision_dashboard",
        file_name=site_csv.name,
        payload=site_csv.getvalue(),
    )

units = {
    "pv_power": "kW",
    "wind_power": "kW",
    "essential_load": "kW",
    "electricity_price": f"{currency}/kWh",
}

try:
    site_assumptions = SiteAssumptions(
        pv_rated_kw=float(pv_capacity),
        wind_rated_kw=float(wind_capacity),
        grid_import_limit_kw=float(grid_limit),
        battery_capacity_kwh=float(battery_capacity),
        battery_power_kw=float(battery_power),
        battery_initial_soc=BATTERY_INITIAL_SOC,
        battery_min_soc=BATTERY_MIN_SOC,
        battery_max_soc=BATTERY_MAX_SOC,
        diesel_rated_kw=0.0,
        diesel_variable_cost_per_kwh=0.0,
    )
    fingerprint = build_input_fingerprint(
        page="decision_dashboard",
        history_sha256=history_sha256,
        site_digest=site_assumptions.digest(),
        units=units,
        hour_count=len(history_stamps),
        currency=currency,
        page_settings={
            "demand_scale": float(demand_scale),
            "tariff_scale": float(tariff_scale),
            "cost_priority": float(cost_priority),
        },
    )
    render_customer_workflow(
        active_page="decision_dashboard",
        history_sha256=history_sha256,
        source_label=source_label,
        fingerprint=fingerprint,
    )
    config = site_assumptions.to_energy_system_config()
    # The request this page acts on, in the shared application-facing shape: the site,
    # the history with its units and provenance, this page's own simulation knobs and the
    # entered investment assumptions. Built once, before the calculation, so what the
    # page asked for is a recorded object rather than an implicit consequence of the code
    # path below.
    run_request_view = build_run_request(
        page="customer_dashboard",
        site=site_assumptions,
        timestamps=history_stamps,
        history=history,
        units=units,
        page_settings={
            "demand_scale": float(demand_scale),
            "tariff_scale": float(tariff_scale),
            "cost_priority": float(cost_priority),
        },
        run_settings={
            "currency": currency,
            "investment": {
                "baseline_annual_energy_cost": float(baseline_annual_bill),
                "proposed_annual_energy_cost": float(proposed_annual_bill),
                "annual_incremental_om_cost": float(incremental_om),
                "upfront_capex": float(upfront_capex),
                "project_life_years": int(project_life),
                "discount_rate": float(discount_rate_pct) / 100.0,
                "annual_energy_saving_escalation_rate": float(energy_saving_escalation_pct) / 100.0,
                "annual_om_escalation_rate": float(om_escalation_pct) / 100.0,
            },
        },
        provenance=source_label,
        source_sha256=source_sha256,
    )
    # The whole sequence lives in islandos_core.run_orchestration: forecast → coordination
    # inputs → objective weights → optimize → service-equivalent economics → stress →
    # paired impact. The page keeps the objects it renders and nothing about the order.
    run_outputs = run_customer_dashboard(
        history_stamps=history_stamps,
        history=history,
        units=units,
        site=site_assumptions,
        currency=currency,
        cost_priority=float(cost_priority),
        provenance=source_label,
    )
    bundle = run_outputs["bundle"]
    coordinated = run_outputs["coordinated"]
    weights = run_outputs["weights"]
    result = run_outputs["result"]
    economics = run_outputs["economics"]
    stress = run_outputs["stress"]
    paired_impact = run_outputs["paired_impact"]

    recommended = result["recommendation"]["policy"]
    candidates = {row["policy"]: row for row in result["candidates"]}
    # Kept next to the candidate map so the assumption summary and the dispatch
    # section can both read the stored result; no second simulation is run.
    selected_candidate = candidates[recommended]
    selected = candidates[recommended]["summary"]
    baseline = candidates["grid_first"]["summary"]
    service_equal = economics["service_equivalent"]
    result_view = build_run_result_summary(
        page="customer_dashboard", result=result, economics=economics, currency=currency,
    )

    st.subheader("Decision snapshot")
    with st.container(key="decision-snapshot-metrics"):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Recommended policy", result_view["recommended_policy_label"])
        m2.metric(
            "Estimated 24h energy cost",
            f"{result_view['estimated_24h_energy_cost']:,.2f} {result_view['currency'] or currency}",
        )
        m3.metric("Unmet energy", f"{result_view['unmet_load_kwh']:,.2f} kWh")
        if result_view["service_equivalent"] and result_view["cost_comparison_valid"]:
            saving = result_view["cost_reduction_vs_grid_first"]
            # U+2011 is a non-breaking hyphen: it renders like "-" but keeps
            # "grid-first" together when the four-up metric row narrows to two
            # columns on phones, instead of leaving a bare "GRID-" line.
            m4.metric("Modeled cost difference vs grid\u2011first",
                      f"{saving:,.2f} {result_view['currency'] or currency}" if saving is not None else "Not available")
        else:
            m4.metric("Customer savings claim", "Withheld")
    if not result_view["service_equivalent"]:
        st.warning(
            "The recommended policy does not deliver service equivalent to the grid-first "
            "reference. A cost reduction is therefore not presented as customer savings."
        )
    else:
        st.caption(
            "The cost difference is a modeled estimate under identical service in this "
            "scenario, not a measured or guaranteed customer saving."
        )
    recommended_label = recommended.replace("_", " ").title()
    cost_gap = baseline["estimated_energy_cost"] - selected["estimated_energy_cost"]
    grid_gap = baseline["grid_import_kwh"] - selected["grid_import_kwh"]
    curtail_gap = baseline["renewable_curtailed_kwh"] - selected["renewable_curtailed_kwh"]
    if service_equal and cost_gap > 0:
        st.caption(
            f"**Why {recommended_label}:** it serves the same load with "
            f"{cost_gap:,.2f} {currency} less modeled 24-hour energy cost, "
            f"{grid_gap:,.2f} kWh less grid import, and "
            f"{curtail_gap:,.2f} kWh less renewable curtailment."
        )
    elif service_equal:
        st.caption(
            f"**Why {recommended_label}:** it is the lowest modeled-cost policy that "
            "still serves the same load in this scenario."
        )
    else:
        st.caption(
            f"**Why {recommended_label}:** it is the lowest modeled-cost policy in this "
            "comparison, but its service differs from the grid-first reference."
        )

    st.subheader("Forecast: next 24 hours")
    forecast_rows = []
    for signal_name in ("pv_power", "wind_power", "essential_load", "electricity_price"):
        forecast = bundle.forecasts[signal_name]
        for point in forecast.points:
            forecast_rows.append({
                "Timestamp (UTC)": point.timestamp,
                "Signal": signal_name,
                "Forecast": point.predicted,
                "Lower planning bound": point.lower_bound,
                "Upper planning bound": point.upper_bound,
            })
    forecast_frame = pd.DataFrame(forecast_rows)
    energy_forecast = forecast_frame[
        forecast_frame["Signal"].isin(("pv_power", "wind_power", "essential_load"))
    ].pivot(index="Timestamp (UTC)", columns="Signal", values="Forecast")
    tariff_forecast = forecast_frame[
        forecast_frame["Signal"] == "electricity_price"
    ].set_index("Timestamp (UTC)")[["Forecast"]]
    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.caption("Generation and essential load (kW)")
        st.line_chart(energy_forecast, width="stretch", height=220)
    with chart_right:
        st.caption(f"Electricity price ({currency}/kWh)")
        st.line_chart(tariff_forecast, width="stretch", height=220)
    with st.expander("Forecast model quality and provenance"):
        st.write(f"Forecast history SHA-256: `{bundle.input_history_sha256}`")
        st.write(f"Uploaded file SHA-256: {source_sha256 or 'not applicable — synthetic data'}")
        for name, forecast in bundle.forecasts.items():
            st.write({
                "signal": name,
                "model": forecast.model_id,
                "holdout_MAE": round(forecast.holdout_metrics.mae, 4),
                "holdout_RMSE": round(forecast.holdout_metrics.rmse, 4),
                "selected_model_beats_baseline": forecast.selected_model_beats_baseline,
                "unit": forecast.unit,
            })
        st.caption(
            "Holdout scores describe this synthetic history only. The P90 absolute "
            "holdout error is a planning envelope, not a calibrated joint confidence interval."
        )

    st.subheader("Operating policy comparison")
    policy_labels = [policy.replace("_", " ").title() for policy in candidates]
    other_labels = [label for label in policy_labels if label != recommended_label]
    recommended_summary = candidates[recommended]["summary"]
    st.markdown(
        f"**Recommended: {recommended_label}** — "
        f"{recommended_summary['estimated_energy_cost']:,.2f} {currency} 24h cost · "
        f"{recommended_summary['grid_import_kwh']:,.2f} kWh grid import · "
        f"{recommended_summary['unmet_load_kwh']:,.2f} kWh unmet · "
        f"{recommended_summary['renewable_curtailed_kwh']:,.2f} kWh curtailed."
    )
    st.caption(
        "The optimizer compares two explicit dispatch priorities using the shared "
        "physical simulator. It is a bounded policy comparison, not global hourly set-point optimization."
    )
    measures = [
        (f"24h energy cost ({currency})", "estimated_energy_cost"),
        ("Grid import (kWh)", "grid_import_kwh"),
        ("Unmet load (kWh)", "unmet_load_kwh"),
        ("Renewable curtailed (kWh)", "renewable_curtailed_kwh"),
    ]
    comparison = []
    for measure, key in measures:
        row = {"Measure": measure}
        for label, item in zip(policy_labels, candidates.values()):
            row[label] = f"{item['summary'][key]:,.2f}"
        comparison.append(row)
    audit_row = {"Measure": "Physical audit"}
    for label, item in zip(policy_labels, candidates.values()):
        audit_row[label] = "Passed" if item["audit"]["passed"] else "Failed"
    comparison.append(audit_row)
    compare_label = f"Compare {recommended_label} with {', '.join(other_labels)}"
    with st.expander(compare_label, expanded=False):
        render_table(pd.DataFrame(comparison))

    st.subheader("Hourly dispatch for the recommended policy")
    dispatch_rows = [dict(row) for row in selected_candidate["dispatch"].get("rows") or []]
    st.caption(
        f"Offline dispatch for **{recommended.replace('_', ' ').title()}**, read from the same "
        "simulation that produced the policy comparison above. It is not an equipment command, "
        "not real-time control, and not a proof that this schedule is globally optimal."
    )
    if not dispatch_rows:
        st.info("Hourly dispatch is not available in this run: the stored dispatch contains no rows.")
    else:
        dispatch_frame = pd.DataFrame(dispatch_rows).reset_index(drop=True)
        if "timestep" in dispatch_frame.columns:
            hours = dispatch_frame["timestep"].astype(int) + 1
        else:
            hours = pd.Series(range(1, len(dispatch_frame) + 1))
        dispatch_frame.index = pd.Index(hours, name="Hour")

        flow_columns = {
            "Grid import": "grid_import_kw",
            "Battery charge": "battery_charge_kw",
            "Battery discharge": "battery_discharge_kw",
        }
        available_flows = {
            label: dispatch_frame[field].astype(float)
            for label, field in flow_columns.items()
            if field in dispatch_frame.columns
        }
        diesel_note = None
        if "diesel_generation_kw" in dispatch_frame.columns:
            diesel_series = dispatch_frame["diesel_generation_kw"].astype(float)
            if float(site_assumptions.diesel_rated_kw) > 0.0 or float(diesel_series.max()) > 0.0:
                available_flows["Diesel generation (kW)"] = diesel_series
            else:
                diesel_note = (
                    "Diesel generation is not part of this run: the generator is not configured "
                    "(rated 0 kW), so the dispatch carries no diesel output to plot."
                )
        else:
            diesel_note = (
                "Diesel generation is not available in this run: the dispatch rows carry no "
                "diesel column."
            )
        if available_flows:
            st.caption("Grid import and battery flows (kW)")
            st.line_chart(pd.DataFrame(available_flows), width="stretch", height=240)
        else:
            st.info(
                "Hourly power flows are not available in this run: the dispatch rows carry none "
                "of the grid-import or battery columns."
            )
        if diesel_note:
            st.caption(diesel_note)

        if "battery_soc" in dispatch_frame.columns and dispatch_frame["battery_soc"].notna().any():
            soc_frame = pd.DataFrame({
                "Battery SOC (%)": dispatch_frame["battery_soc"].astype(float) * 100.0,
            })
            st.caption("Battery state of charge (%)")
            st.line_chart(soc_frame, width="stretch", height=240)
        else:
            st.info(
                "Battery state of charge is not available in this run: the dispatch rows carry "
                "no SOC column."
            )

        detail_columns = {
            "Grid import (kW)": "grid_import_kw",
            "Diesel generation (kW)": "diesel_generation_kw",
            "Battery charge (kW)": "battery_charge_kw",
            "Battery discharge (kW)": "battery_discharge_kw",
            "Battery SOC (%)": "battery_soc",
            "Load served (kW)": "load_served_kw",
            "Unmet load (kW)": "unmet_load_kw",
            "Renewable curtailed (kW)": "renewable_curtailed_kw",
        }
        detail_frame = pd.DataFrame({"Hour": list(dispatch_frame.index)})
        for label, field in detail_columns.items():
            if field in dispatch_frame.columns:
                column = dispatch_frame[field].astype(float)
                if field == "battery_soc":
                    column = column * 100.0
                detail_frame[label] = column.to_numpy()
        with st.expander("Hourly dispatch detail (hourly rows)"):
            render_table(detail_frame)

    with st.expander("Paired policy replay (independent evidence)", expanded=False):
        impact_baseline = paired_impact["baseline_metrics"]
        impact_candidate = paired_impact["candidate_metrics"]
        impact_benefit = paired_impact["gross_operating_benefit"]
        impact_audit = paired_impact["equipment_constraint_audit"]
        impact_service = paired_impact["service_equivalence"]
        impact_cols = st.columns(4)
        impact_cols[0].metric(
            "Paired-policy gross difference",
            (
                f"{impact_benefit['value']:,.2f} {currency}"
                if impact_benefit["value"] is not None else "Withheld"
            ),
        )
        impact_cols[1].metric(
            "Service equivalence",
            "Passed" if impact_service["passed"] else "Failed",
        )
        impact_cols[2].metric(
            "Independent dispatch audit",
            "Passed" if impact_audit["passed"] else "Failed",
        )
        impact_cols[3].metric("Net customer value", "Not calculated")
        render_table(
            pd.DataFrame([
                {"Measure": "Estimated energy cost", "Grid-first baseline": impact_baseline["estimated_energy_cost"], "Battery-first candidate": impact_candidate["estimated_energy_cost"]},
                {"Measure": "Grid import (kWh)", "Grid-first baseline": impact_baseline["grid_import_kwh"], "Battery-first candidate": impact_candidate["grid_import_kwh"]},
                {"Measure": "Diesel generation (kWh)", "Grid-first baseline": impact_baseline["diesel_generation_kwh"], "Battery-first candidate": impact_candidate["diesel_generation_kwh"]},
                {"Measure": "Renewable curtailment (kWh)", "Grid-first baseline": impact_baseline["renewable_curtailed_kwh"], "Battery-first candidate": impact_candidate["renewable_curtailed_kwh"]},
                {"Measure": "Critical unmet load (kWh)", "Grid-first baseline": impact_baseline["critical_unmet_load_kwh"], "Battery-first candidate": impact_candidate["critical_unmet_load_kwh"]},
                {"Measure": "Flexible load shed (kWh)", "Grid-first baseline": impact_baseline["flexible_load_shed_kwh"], "Battery-first candidate": impact_candidate["flexible_load_shed_kwh"]},
            ]),
        )
        st.caption(
            "This is a separate, same-input 24-hour grid-first vs battery-first evidence comparison. "
            "It is not the optimizer's recommended policy, not annual savings, and not a water-service assessment. "
            "Net customer value is withheld because software, integration, maintenance and training costs "
            "have not been supplied on this same 24-hour basis."
        )
        with st.expander("Paired impact audit details"):
            st.json(paired_impact)

    st.subheader("Reliability and stress review")
    stress_rows = []
    for policy, item in stress["policy_results"].items():
        for scenario, scenario_result in item["scenario_results"].items():
            summary = scenario_result["summary"]
            stress_rows.append({
                "Policy": policy.replace("_", " ").title(),
                "Scenario": scenario.replace("_", " ").title(),
                "Unmet load (kWh)": summary["unmet_load_kwh"],
                "Critical unmet load (kWh)": summary["critical_unmet_load_kwh"],
                "Estimated cost": summary["estimated_energy_cost"],
                "Audit": "Passed" if scenario_result["audit"]["passed"] else "Failed",
            })
    stress_frame = pd.DataFrame(stress_rows)
    stress_cards = []
    for policy in stress_frame["Policy"].unique():
        subset = stress_frame[stress_frame["Policy"] == policy]
        stress_cards.append(
            '<section class="ios-stress-policy">'
            f"<h3>{policy}</h3>"
            "<dl>"
            f"<div><dt>Worst unmet (kWh)</dt><dd>{subset['Unmet load (kWh)'].max():,.2f}</dd></div>"
            f"<div><dt>Worst critical (kWh)</dt><dd>{subset['Critical unmet load (kWh)'].max():,.2f}</dd></div>"
            f"<div><dt>Highest 24h cost ({currency})</dt><dd>{subset['Estimated cost'].max():,.2f}</dd></div>"
            f"<div><dt>Physical audit</dt><dd>{'Passed' if subset['Audit'].eq('Passed').all() else 'Review'}</dd></div>"
            "</dl></section>"
        )
    st.html(f'<div class="ios-stress-grid">{"".join(stress_cards)}</div>')
    st.caption(
        "Worst case per policy across four forecast-envelope and grid-outage replays, "
        "not the base-case dispatch shown above."
    )
    with st.expander("Stress replay detail", expanded=False):
        render_table(stress_frame)
        st.caption(
            "Stress cases are deterministic forecast-envelope and grid-outage replays. "
            "No scenario probabilities or joint confidence coverage are assigned."
        )

    st.subheader("Equipment investment screen")
    economics_binding = None
    annual_inputs_entered = annual_inputs_supplied(
        baseline_annual_bill=baseline_annual_bill,
        proposed_annual_bill=proposed_annual_bill,
        upfront_capex=upfront_capex,
    )
    if annual_inputs_entered:
        investment = evaluate_investment_economics(
            baseline_annual_energy_cost=float(baseline_annual_bill),
            proposed_annual_energy_cost=float(proposed_annual_bill),
            annual_incremental_om_cost=float(incremental_om),
            upfront_capex=float(upfront_capex),
            project_life_years=int(project_life),
            discount_rate=float(discount_rate_pct) / 100.0,
            annual_energy_saving_escalation_rate=float(energy_saving_escalation_pct) / 100.0,
            annual_om_escalation_rate=float(om_escalation_pct) / 100.0,
            replacement_year=int(replacement_year) if replacement_year is not None else None,
            replacement_cost=float(replacement_cost),
            residual_value=float(residual_value),
            service_equivalent=bool(service_equal and economics.get("cost_comparison_valid")),
        )
        # The annual figures cite this run; they are never derived from it. Build the
        # manifest from the same inputs the screen was computed on, then bind.
        annual_dataset_digest = history_sha256
        annual_config_digest = hashlib.sha256(
            json.dumps(asdict(config), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        annual_run_id = deterministic_run_id(
            "run-dashboard",
            {
                "dataset_sha256": annual_dataset_digest,
                "site_configuration_sha256": annual_config_digest,
                "history_sha256": bundle.input_history_sha256,
                "recommended_policy": recommended,
                "weights": {
                    "cost": float(weights.cost),
                    "reliability": float(weights.reliability),
                    "curtailment": float(weights.curtailment),
                    "battery_wear": float(weights.battery_wear),
                },
                "project_life_years": int(project_life),
                "currency": currency,
            },
        )
        annual_run_manifest = create_run_manifest(
            project_id="streamlit-customer-decision-dashboard",
            run_id=annual_run_id,
            site_ref="customer-uploaded-site" if shared_payload is not None else "synthetic-demo-site",
            # The annual binding cites a run, so its identity must come from the
            # window the run speaks for, not from the moment the page was opened:
            # otherwise two renders of the same inputs produce different manifest
            # and binding digests and a reader cannot tell they are the same record.
            created_at_utc=(
                demo_anchor if shared_payload is None else history_stamps[-1]
            ).isoformat(),
            dataset_sha256=annual_dataset_digest,
            dataset_schema_version="canonical-hourly-signals-v1",
            source_type="customer_provided" if shared_payload is not None else "synthetic",
            site_configuration_version="1",
            site_configuration_sha256=annual_config_digest,
            required_signals=units,
            forecast_horizon_hours=24,
            optimizer_id="prediction_resource_dispatch",
            optimizer_version="1",
            optimizer_settings={
                "cost": float(weights.cost),
                "reliability": float(weights.reliability),
                "curtailment": float(weights.curtailment),
                "battery_wear": float(weights.battery_wear),
            },
            scenario_assumptions={
                "grid_available": [True] * 24,
                "battery_configured": config.battery is not None,
                "horizon_hours": 24,
                "currency": currency,
            },
            forecast_settings={"backtest_horizon": 24, "season_length": 24, "confidence_level": 0.90},
        ).to_dict()
        economics_binding = bind_annual_economics_to_run(
            investment,
            annual_run_manifest,
            annual_bill_source=annual_source_for(
                baseline_annual_bill=baseline_annual_bill,
                proposed_annual_bill=proposed_annual_bill,
                annual_incremental_om=incremental_om,
                upfront_capex=upfront_capex,
            ),
        )
        binding_verification = verify_investment_economics_binding(economics_binding)
        if not binding_verification["valid"]:
            st.error(
                "Annual economics binding integrity check failed: "
                + "; ".join(binding_verification["errors"])
            )
            st.stop()
        with st.expander("Annual-screen assumptions and provenance", expanded=False):
            render_annual_economics_basis(economics_binding, include_hashes=False)
        st.caption(
            "The metrics below are a screening result under the assumptions in the expander above; "
            "they are not a procurement guarantee."
        )
        if investment.decision == "blocked":
            st.warning(investment.reasons[0])
        else:
            with st.container(key="investment-metrics"):
                i1, i2, i3, i4 = st.columns(4)
                i1.metric("Net present value", f"{investment.net_present_value:,.0f} {currency}")
                i2.metric("Simple payback", f"{investment.simple_payback_years:.1f} years" if investment.simple_payback_years is not None else "Not achieved")
                i3.metric("Discounted payback", f"{investment.discounted_payback_years:.1f} years" if investment.discounted_payback_years is not None else "Not achieved")
                i4.metric("Break-even annual energy saving", f"{investment.break_even_annual_energy_saving:,.0f} {currency}")
            st.caption(
                f"Screen result: {investment.decision.replace('_', ' ').title()}. "
                f"Annual energy-bill difference: {investment.annual_energy_cost_saving:,.0f} {currency}; "
                f"annual net operating benefit after incremental O&M: "
                f"{investment.annual_net_operating_benefit:,.0f} {currency}."
            )
            if investment.reasons:
                st.caption(" ".join(investment.reasons))
            case_labels = {
                "base": "Base case",
                "high_20pct_energy_saving": "Energy saving +20%",
                "low_20pct_energy_saving": "Energy saving -20%",
            }
            sensitivity_frame = pd.DataFrame([
                {"Case": case_labels.get(label, label.replace("_", " ").title()), "NPV": float(value)}
                for label, value in investment.sensitivity_npv.items()
            ])
            case_order = [
                name for name in ("Base case", "Energy saving -20%", "Energy saving +20%")
                if name in set(sensitivity_frame["Case"])
            ]
            base_rows = sensitivity_frame[sensitivity_frame["Case"] == "Base case"]
            base_npv = (
                float(base_rows["NPV"].iloc[0])
                if not base_rows.empty
                else float(investment.net_present_value)
            )
            sensitivity_frame["Change vs base"] = sensitivity_frame["NPV"] - base_npv
            sensitivity_frame["NPV label"] = sensitivity_frame["NPV"].map(lambda value: f"{value:,.0f}")
            sensitivity_frame["Change label"] = sensitivity_frame["Change vs base"].map(
                lambda value: f"{value:+,.0f} vs base"
            )
            base_rows = sensitivity_frame[sensitivity_frame["Case"] == "Base case"]
            downside = sensitivity_frame[sensitivity_frame["Case"] == "Energy saving -20%"]
            upside = sensitivity_frame[sensitivity_frame["Case"] == "Energy saving +20%"]
            low = min(0.0, float(sensitivity_frame["NPV"].min()))
            high = max(0.0, float(sensitivity_frame["NPV"].max()))
            value_span = max(high - low, 1.0)
            domain_pad = max(value_span * 0.12, abs(base_npv) * 0.05, 1000.0)
            y_domain = [low - domain_pad, high + domain_pad]

            bars = (
                alt.Chart(sensitivity_frame)
                .mark_bar(cornerRadius=4, opacity=0.94)
                .encode(
                    x=alt.X(
                        "Case:N",
                        sort=case_order,
                        scale=alt.Scale(domain=case_order),
                        title=None,
                        axis=alt.Axis(
                            labelAngle=0,
                            labelLimit=0,
                            labelOverlap=False,
                            labelPadding=10,
                            labelColor="#5d6e66",
                            labelFontSize=15,
                            tickSize=0,
                            domain=False,
                        ),
                    ),
                    y=alt.Y(
                        "NPV:Q",
                        title=f"NPV ({currency})",
                        scale=alt.Scale(domain=y_domain, zero=True, nice=False),
                        axis=alt.Axis(
                            format=",.0f",
                            labelAngle=0,
                            labelColor="#5d6e66",
                            labelFontSize=14,
                            titleColor="#3d5149",
                            titleFontSize=13,
                            gridColor="#e8e1d2",
                            gridOpacity=0.8,
                            domain=False,
                            ticks=False,
                            tickCount=5,
                        ),
                    ),
                    color=alt.Color(
                        "Case:N",
                        scale=alt.Scale(
                            domain=["Base case", "Energy saving -20%", "Energy saving +20%"],
                            range=["#a9793f", "#9f4b3b", "#2f6f6a"],
                        ),
                        legend=None,
                    ),
                    tooltip=[
                        alt.Tooltip("Case:N", title="Case"),
                        alt.Tooltip("NPV:Q", title=f"NPV ({currency})", format=",.0f"),
                        alt.Tooltip(
                            "Change vs base:Q",
                            title=f"Change vs base ({currency})",
                            format="+,.0f",
                        ),
                    ],
                )
            )

            zero_rule = (
                alt.Chart(pd.DataFrame({"y": [0.0]}))
                .mark_rule(color="#8f9187", strokeWidth=1)
                .encode(y="y:Q")
            )
            base_rule = (
                alt.Chart(pd.DataFrame({"y": [base_npv]}))
                .mark_rule(color="#a9793f", strokeDash=[6, 4], strokeWidth=1.4)
                .encode(y="y:Q")
            )

            base_value_label = (
                alt.Chart(base_rows)
                .mark_text(
                    align="center",
                    baseline="top",
                    dy=13,
                    color="#fffcf4",
                    fontSize=17,
                    fontWeight=700,
                )
                .encode(x="Case:N", y="NPV:Q", text=alt.Text("NPV label:N"))
            )
            positive_value_label = (
                alt.Chart(
                    sensitivity_frame[
                        (sensitivity_frame["Case"] != "Base case") & (sensitivity_frame["NPV"] >= 0)
                    ]
                )
                .mark_text(
                    align="center",
                    baseline="top",
                    dy=13,
                    color="#fffcf4",
                    fontSize=17,
                    fontWeight=700,
                )
                .encode(x="Case:N", y="NPV:Q", text=alt.Text("NPV label:N"))
            )
            negative_value_label = (
                alt.Chart(
                    sensitivity_frame[
                        (sensitivity_frame["Case"] != "Base case") & (sensitivity_frame["NPV"] < 0)
                    ]
                )
                .mark_text(
                    align="center",
                    baseline="bottom",
                    dy=-13,
                    color="#fffcf4",
                    fontSize=17,
                    fontWeight=700,
                )
                .encode(x="Case:N", y="NPV:Q", text=alt.Text("NPV label:N"))
            )

            delta_layers = []
            if not upside.empty:
                delta_layers.append(
                    alt.Chart(upside)
                    .mark_text(
                        align="center",
                        baseline="bottom",
                        dy=-12,
                        color="#2f6f6a",
                        fontSize=14,
                        fontWeight=700,
                    )
                    .encode(x="Case:N", y="NPV:Q", text=alt.Text("Change label:N"))
                )
            if not downside.empty:
                delta_layers.append(
                    alt.Chart(downside)
                    .mark_text(
                        align="center",
                        baseline="top",
                        dy=12,
                        color="#9f4b3b",
                        fontSize=14,
                        fontWeight=700,
                    )
                    .encode(x="Case:N", y="NPV:Q", text=alt.Text("Change label:N"))
                )

            sensitivity_chart = (
                alt.layer(
                    zero_rule,
                    base_rule,
                    bars,
                    base_value_label,
                    positive_value_label,
                    negative_value_label,
                    *delta_layers,
                )
                .properties(height=340, padding={"top": 30, "bottom": 24, "left": 6, "right": 14})
                .configure_view(stroke=None)
            )
            with st.expander("Investment details: sensitivity and annual cashflow", expanded=False):
                st.caption(
                    "Sensitivity: year-one energy-bill saving ±20%, every other assumption fixed. "
                    "The gold line is the base case; labels show change from it."
                )
                st.altair_chart(sensitivity_chart, width="stretch")
                cashflow_frame = pd.DataFrame(investment.annual_cashflows)
                render_table(cashflow_frame)
        investment_report = investment.to_dict()

    else:
        # A zero bill is what an unfilled field looks like, not a customer figure.
        # Screening it produces a confident "negative" verdict that describes
        # nothing the customer said, so every metric is withheld instead.
        st.warning(
            "Withheld - the baseline annual bill and the installed CAPEX have not both been "
            "entered. Those fields default to zero, and zero is what an empty field looks like, "
            "not a customer figure, so there is no screen to show here. Enter the baseline and "
            "proposed annual bills plus a supplier CAPEX quote in the sidebar; the screen, its "
            "run citation and the cashflow table then appear together."
        )
        investment_report = {
            "status": "withheld_inputs_not_entered",
            "reason": (
                "the baseline annual bill and installed CAPEX were not both entered; "
                "the remaining placeholders are zero, not a customer figure"
            ),
            "metrics_withheld": [
                "net_present_value",
                "simple_payback_years",
                "discounted_payback_years",
                "break_even_annual_energy_saving",
                "sensitivity_npv",
                "annual_cashflows",
            ],
            "inputs_as_entered": {
                "baseline_annual_energy_cost": float(baseline_annual_bill),
                "proposed_annual_energy_cost": float(proposed_annual_bill),
                "annual_incremental_om_cost": float(incremental_om),
                "upfront_capex": float(upfront_capex),
            },
        }
        st.caption(
            "Nothing is bound to a run while the inputs are missing: a binding would have to "
            "describe bills nobody entered."
        )
    operator_result = dict(result)
    operator_result.update({
        "algorithm": "bounded_two_policy_pareto_screening",
        "dispatch": selected_candidate["dispatch"],
        "physical_audit": selected_candidate["audit"],
        "dispatch_rows": [
            dict(row) for row in selected_candidate["dispatch"]["rows"]
        ],
        "baseline_comparison": {
            policy: item["summary"] for policy, item in candidates.items()
        },
        "customer_impact_assessment": paired_impact,
        "grid_import_model_kw": [
            float(row["grid_import_kw"])
            for row in selected_candidate["dispatch"]["rows"]
        ],
        "diesel_commitment_schedule": [
            bool(row.get("diesel_committed", False))
            for row in selected_candidate["dispatch"]["rows"]
        ],
        "diesel_power_setpoint_kw": [
            float(row["diesel_generation_kw"])
            for row in selected_candidate["dispatch"]["rows"]
        ],
    })
    operator_record = build_operator_decision_record(
        operator_result,
        site_ref="unregistered-dashboard-session",
        recommendation_id=(
            f"dashboard-{bundle.input_history_sha256[:12]}-{recommended}"
        ),
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        data_provenance=source_label,
        input_refs=[
            f"history-sha256:{bundle.input_history_sha256}",
            *([f"source-file-sha256:{source_sha256}"] if source_sha256 else []),
        ],
        objective_weights={
            "cost": float(weights.cost),
            "reliability": float(weights.reliability),
            "curtailment": float(weights.curtailment),
            "battery_wear": float(weights.battery_wear),
        },
        operating_constraints={
            "pv_rated_kw": float(config.pv_rated_kw),
            "wind_rated_kw": float(config.wind_rated_kw),
            "grid_import_limit_kw": float(config.grid_import_limit_kw),
            "battery_configured": config.battery is not None,
            "battery_capacity_kwh": (
                float(config.battery.capacity_kwh) if config.battery is not None else None
            ),
            "device_write_authorized": False,
        },
    )
    operator_record_verification = verify_operator_decision_record(operator_record)
    if not operator_record_verification["valid"]:
        st.error(
            "Operator decision record integrity check failed: "
            + "; ".join(operator_record_verification["errors"])
        )
        st.stop()
    st.subheader("Operator decision record")
    st.caption(
        "Integrity verified · human approval pending · device writes disabled. "
        "The record hash is in the technical appendix."
    )
    investment_report["assumptions"] = {
        "baseline_annual_energy_cost": baseline_annual_bill,
        "proposed_annual_energy_cost": proposed_annual_bill,
        "annual_incremental_om_cost": incremental_om,
        "upfront_capex": upfront_capex,
        "project_life_years": project_life,
        "discount_rate": discount_rate_pct / 100.0,
        "annual_energy_saving_escalation_rate": energy_saving_escalation_pct / 100.0,
        "annual_om_escalation_rate": om_escalation_pct / 100.0,
        "replacement_year": replacement_year,
        "replacement_cost": replacement_cost,
        "residual_value": residual_value,
        "currency": currency,
        "service_equivalence_gate_passed": bool(service_equal and economics.get("cost_comparison_valid")),
        "input_status": "customer-entered; not independently verified",
    }

    report = {
        "recommended_policy": recommended,
        "currency": currency,
        "history_sha256": bundle.input_history_sha256,
        "source_file_sha256": source_sha256,
        "input_provenance": source_label,
        "history_rows": len(history_stamps),
        "assumptions": {
            "pv_capacity_kw": pv_capacity,
            "wind_capacity_kw": wind_capacity,
            "grid_import_limit_kw": grid_limit,
            "battery_capacity_kwh": battery_capacity,
            "battery_power_limit_kw": battery_power,
            "cost_priority": cost_priority,
            "demand_scale_applied_to_demo_only": demand_scale if site_csv is None else None,
            "tariff_scale_applied_to_demo_only": tariff_scale if site_csv is None else None,
        },
        "forecast_models": {name: item.model_id for name, item in bundle.forecasts.items()},
        "service_equivalent_to_grid_first": service_equal,
        "cost_comparison_valid": economics["cost_comparison_valid"],
        "estimated_cost_reduction": economics.get("estimated_cost_reduction"),
        "recommended_summary": selected,
        "reference_summary": baseline,
        "forecast_stress_scenarios": stress_rows,
        "paired_customer_impact": paired_impact,
        "operator_decision_record": operator_record,
        "investment_economics": investment_report,
        "investment_economics_binding": economics_binding,
        # The application-facing view models, so a reader (or a non-Streamlit client) gets
        # the same validated shapes the page rendered, not a second hand-built copy.
        "application_views": {
            "request": run_request_view,
            "result": result_view,
        },
        "scope": "offline screening; not measured savings or equipment control",
    }
    summary_npv = investment_report.get("net_present_value")
    summary_simple = investment_report.get("simple_payback_years")
    summary_discounted = investment_report.get("discounted_payback_years")
    summary_annual_bill = investment_report.get("annual_energy_cost_saving")
    summary_net_benefit = investment_report.get("annual_net_operating_benefit")
    summary_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>IslandOS customer decision summary</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1d2420; max-width: 820px; margin: 40px auto; line-height: 1.55; }}
h1 {{ font-size: 26px; margin-bottom: 4px; }}
h2 {{ font-size: 16px; margin-top: 28px; border-bottom: 1px solid #d9d2c5; padding-bottom: 6px; }}
.meta {{ color: #5b625d; font-size: 13px; margin-bottom: 24px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
td {{ padding: 7px 8px; border-bottom: 1px solid #eee7da; vertical-align: top; }}
td:first-child {{ color: #5b625d; width: 45%; }}
.note {{ color: #5b625d; font-size: 12px; margin-top: 26px; }}
</style>
</head>
<body>
<h1>IslandOS customer decision summary</h1>
<p class="meta">{html.escape(source_label)} · {history_stamps[0]:%Y-%m-%d %H:%M} → {history_stamps[-1]:%Y-%m-%d %H:%M} UTC · {len(history_stamps)} h · {html.escape(currency)}</p>
<h2>Recommendation</h2>
<table>
<tr><td>Recommended policy</td><td><strong>{html.escape(recommended_label)}</strong></td></tr>
<tr><td>Modeled 24-hour energy cost</td><td>{selected['estimated_energy_cost']:,.2f} {html.escape(currency)}</td></tr>
<tr><td>Modeled difference vs grid-first</td><td>{f"{cost_gap:,.2f} {currency}" if service_equal else "Withheld — service differs"}</td></tr>
<tr><td>Grid import</td><td>{selected['grid_import_kwh']:,.2f} kWh</td></tr>
<tr><td>Renewable curtailment</td><td>{selected['renewable_curtailed_kwh']:,.2f} kWh</td></tr>
<tr><td>Unmet load</td><td>{selected['unmet_load_kwh']:,.2f} kWh</td></tr>
</table>
<h2>Investment screen</h2>
<table>
<tr><td>Net present value</td><td>{f"{summary_npv:,.0f} {currency}" if summary_npv is not None else "Withheld — inputs not entered"}</td></tr>
<tr><td>Simple payback</td><td>{f"{summary_simple:.1f} years" if summary_simple is not None else "Not achieved"}</td></tr>
<tr><td>Discounted payback</td><td>{f"{summary_discounted:.1f} years" if summary_discounted is not None else "Not achieved"}</td></tr>
<tr><td>Annual energy-bill difference</td><td>{f"{summary_annual_bill:,.0f} {currency}" if summary_annual_bill is not None else "Withheld"}</td></tr>
<tr><td>Annual net operating benefit</td><td>{f"{summary_net_benefit:,.0f} {currency}" if summary_net_benefit is not None else "Withheld"}</td></tr>
</table>
<p class="note">Offline screening based on the inputs in this run. Results are modeled estimates, not measured customer savings, a validated forecast, or equipment commands. Human review remains required.</p>
</body>
</html>"""
    st.download_button(
        "Download customer summary (HTML)",
        data=summary_html.encode("utf-8"),
        file_name="islandos_customer_summary.html",
        mime="text/html",
    )

    with st.expander("Technical appendix (audit identifiers)"):
        st.caption(
            "Offline screening; synthetic defaults unless a CSV is uploaded; "
            "not measured customer savings."
        )
        st.caption(f"Shared history SHA-256: {history_sha256}")
        st.caption(f"Input fingerprint: {fingerprint['fingerprint_sha256']}")
        st.caption(f"Local request SHA-256: {run_request_view['request_sha256']} — this page's own request, not a cross-page run identity")
        st.caption(f"Decision record SHA-256: {operator_record['record_sha256']}")
        if economics_binding:
            st.caption(
                f"Manifest SHA-256: {economics_binding.get('manifest_sha256', 'missing')} · "
                f"Binding SHA-256: {economics_binding.get('binding_sha256', 'missing')}"
            )
        if source_sha256:
            st.caption(f"Uploaded file SHA-256: {source_sha256}")

        st.download_button(
            "Download human-review decision record (JSON)",
            data=json.dumps(operator_record, indent=2, default=str).encode("utf-8"),
            file_name="islandos_operator_decision_record.json",
            mime="application/json",
        )
        st.caption(
            "The decision record preserves the selected offline dispatch, supported physical audit, "
            "paired customer-impact evidence and input hashes. It is advisory-only and requires human review."
        )
        st.download_button(
            "Download decision report (JSON)",
            data=json.dumps(report, indent=2, default=str).encode("utf-8"),
            file_name="islandos_customer_decision_report.json",
            mime="application/json",
        )
except (ValueError, KeyError, TypeError, ArithmeticError, IndexError) as exc:
    st.error(f"Could not build the decision dashboard: {exc}")
    st.caption("Check the scenario assumptions and the forecast/optimizer input contracts.")
    st.caption("No partial decision result is shown; nothing is written to equipment.")
    st.stop()
