"""Customer-facing, forecast-led decision dashboard for the generic IslandOS platform.

The default scenario is synthetic. Results are offline planning estimates, not
measured customer savings, a site-validated forecast, or equipment commands.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import asdict
import hashlib
import json
import math

import pandas as pd
import streamlit as st
from islandos_ui.upload_guard import reject_upload
from islandos_ui.page_header import render_page_header
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
from islandos_core.demo_site_history import demo_anchor_for_hour
from islandos_core.canonical_run import create_run_manifest, deterministic_run_id
from islandos_core.session_dataset import clear_session_dataset, get_session_dataset
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

st.title("Customer decision dashboard")
st.caption("Forecast → compare operating policies → review cost and reliability trade-offs")

render_page_header(
    question="Given a site's history, what does the forecast imply for the cost and reliability trade-off?",
    data="A synthetic default history, or your uploaded CSV/XLSX (session-only, with a recorded hash).",
    conclusions="Which operating policy is worth comparing next, and how much of the gap is forecast-driven.",
    limits="Offline planning estimates, not measured customer savings or a site-validated forecast.",
)

st.info(
    "Demonstration mode: all default inputs are synthetic. Replace them with "
    "validated site data before using the results in a customer decision. "
    "This page performs offline screening only; it does not control equipment. "
    "Uploaded CSV files are processed by the hosted app server: upload only data "
    "you are authorized to share, and use redacted or non-sensitive exports."
)

now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

with st.sidebar:
    st.subheader("Scenario assumptions")
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
    shared_dataset = get_session_dataset(st.session_state)
    if shared_dataset is not None:
        st.caption(f"Session dataset available: {shared_dataset['file_name']} · SHA-256 {shared_dataset['sha256'][:12]}…")
        if st.button("Clear session dataset", key="clear_shared_dataset_dashboard"):
            clear_session_dataset(st.session_state)
            st.rerun()
    if site_csv is not None:
        st.caption("The page-specific upload takes priority over the shared session dataset.")
    st.divider()
    st.subheader("Demo clock")
    demo_date = st.date_input(
        "Demo date (UTC)", value=now.date(), key="demo_date_dashboard",
        help=(
            "The date the synthetic window ends on. Defaults to today. The load "
            "formula carries a weekday term, so the date matters here as well as the hour."
        ),
    )
    demo_hour = st.slider(
        "Demo clock (UTC hour)", 0, 23, now.hour, key="demo_clock_hour_dashboard",
        help=(
            "Pins the synthetic default history to this UTC hour so a recorded cost "
            "can be reproduced. It has no effect on an uploaded CSV."
        ),
    )
    st.caption("Synthetic default only; an uploaded CSV carries its own timestamps.")
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
        prefix = "User-uploaded" if site_csv is not None else "Session-shared"
        source_label = f"{prefix}: {uploaded.source_name} (not independently verified)"
    except ValueError as exc:
        reject_upload("Site history CSV", exc)
        st.stop()
else:
    history_stamps = [demo_anchor - timedelta(hours=168 - index) for index in range(168)]
    for index, stamp in enumerate(history_stamps):
        hour = stamp.hour
        day = stamp.weekday()
        solar = max(0.0, 34.0 * math.sin(math.pi * (hour - 6) / 12.0))
        pv = solar * (0.82 + 0.12 * math.sin(index * 0.31))
        wind = 7.0 + 3.0 * (0.5 + 0.5 * math.sin(index * 0.23 + 0.8))
        load = (21.0 + 4.0 * (hour in range(17, 23)) + 2.0 * (hour in range(7, 10))
                + 1.2 * (day < 5)) * demand_scale
        tariff = (0.09 if hour < 6 else 0.29 if hour in range(17, 22) else 0.17)
        tariff *= tariff_scale * (1.0 + 0.04 * math.sin(index * 0.11))
        history["pv_power"].append(round(max(0.0, pv), 3))
        history["wind_power"].append(round(max(0.0, wind), 3))
        history["essential_load"].append(round(load, 3))
        history["electricity_price"].append(round(tariff, 4))

demo_note = f" · Demo clock pin {int(demo_hour):02d}:00 UTC" if shared_payload is None else ""
st.caption(
    f"History window: {history_stamps[0].isoformat()} → {history_stamps[-1].isoformat()} "
    f"({len(history_stamps)} hourly rows){demo_note}"
)
st.caption(f"Input provenance: {source_label}")

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
    selected = candidates[recommended]["summary"]
    baseline = candidates["grid_first"]["summary"]
    service_equal = economics["service_equivalent"]
    result_view = build_run_result_summary(
        page="customer_dashboard", result=result, economics=economics, currency=currency,
    )

    st.subheader("Decision snapshot")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Recommended policy", result_view["recommended_policy_label"])
    m2.metric(
        "Estimated 24h energy cost",
        f"{result_view['estimated_24h_energy_cost']:,.2f} {result_view['currency'] or currency}",
    )
    m3.metric("Unmet energy", f"{result_view['unmet_load_kwh']:,.2f} kWh")
    if result_view["service_equivalent"] and result_view["cost_comparison_valid"]:
        saving = result_view["cost_reduction_vs_grid_first"]
        m4.metric("Modeled cost difference vs grid-first",
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
        st.line_chart(energy_forecast, use_container_width=True)
    with chart_right:
        st.caption(f"Electricity price ({currency}/kWh)")
        st.line_chart(tariff_forecast, use_container_width=True)
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
    comparison = []
    for policy, item in candidates.items():
        summary = item["summary"]
        comparison.append({
            "Policy": policy.replace("_", " ").title(),
            "Estimated cost": summary["estimated_energy_cost"],
            "Grid import (kWh)": summary["grid_import_kwh"],
            "Unmet load (kWh)": summary["unmet_load_kwh"],
            "Renewable curtailed (kWh)": summary["renewable_curtailed_kwh"],
            "Physical audit": "Passed" if item["audit"]["passed"] else "Failed",
        })
    st.dataframe(pd.DataFrame(comparison), use_container_width=True, hide_index=True)
    st.caption(
        "The optimizer compares two explicit dispatch priorities using the shared "
        "physical simulator. It is a bounded policy comparison, not global hourly set-point optimization."
    )

    st.subheader("Paired customer-impact evidence")
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
    st.dataframe(
        pd.DataFrame([
            {"Measure": "Estimated energy cost", "Grid-first baseline": impact_baseline["estimated_energy_cost"], "Battery-first candidate": impact_candidate["estimated_energy_cost"]},
            {"Measure": "Grid import (kWh)", "Grid-first baseline": impact_baseline["grid_import_kwh"], "Battery-first candidate": impact_candidate["grid_import_kwh"]},
            {"Measure": "Diesel generation (kWh)", "Grid-first baseline": impact_baseline["diesel_generation_kwh"], "Battery-first candidate": impact_candidate["diesel_generation_kwh"]},
            {"Measure": "Renewable curtailment (kWh)", "Grid-first baseline": impact_baseline["renewable_curtailed_kwh"], "Battery-first candidate": impact_candidate["renewable_curtailed_kwh"]},
            {"Measure": "Critical unmet load (kWh)", "Grid-first baseline": impact_baseline["critical_unmet_load_kwh"], "Battery-first candidate": impact_candidate["critical_unmet_load_kwh"]},
            {"Measure": "Flexible load shed (kWh)", "Grid-first baseline": impact_baseline["flexible_load_shed_kwh"], "Battery-first candidate": impact_candidate["flexible_load_shed_kwh"]},
        ]),
        use_container_width=True,
        hide_index=True,
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
    st.dataframe(pd.DataFrame(stress_rows), use_container_width=True, hide_index=True)
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
        annual_dataset_digest = source_sha256 or hashlib.sha256(
            json.dumps(
                {
                    "timestamps_utc": [stamp.isoformat() for stamp in history_stamps],
                    "signals": history,
                    "units": units,
                },
                sort_keys=True, separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
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
            created_at_utc=datetime.now(timezone.utc).isoformat(),
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
        render_annual_economics_basis(economics_binding)
        st.caption(
            "The metrics below are a screening result under the assumptions printed with them; "
            "they are not a procurement guarantee."
        )
        if investment.decision == "blocked":
            st.warning(investment.reasons[0])
        else:
            i1, i2, i3, i4 = st.columns(4)
            i1.metric("Net present value", f"{investment.net_present_value:,.0f} {currency}")
            i2.metric("Simple payback", f"{investment.simple_payback_years:.1f} years" if investment.simple_payback_years is not None else "Not achieved")
            i3.metric("Discounted payback", f"{investment.discounted_payback_years:.1f} years" if investment.discounted_payback_years is not None else "Not achieved")
            i4.metric("Break-even annual energy saving", f"{investment.break_even_annual_energy_saving:,.0f} {currency}")
            st.write({
                "Screen result": investment.decision.replace("_", " ").title(),
                "Annual energy-bill difference": investment.annual_energy_cost_saving,
                "Annual net operating benefit after incremental O&M": investment.annual_net_operating_benefit,
                "Reasons / review notes": investment.reasons,
            })
            sensitivity_frame = pd.DataFrame([
                {"Case": label.replace("_", " ").title(), "NPV": value}
                for label, value in investment.sensitivity_npv.items()
            ]).set_index("Case")
            st.caption("Sensitivity varies year-one energy-bill saving by ±20%; all other assumptions and escalation rates remain fixed.")
            st.bar_chart(sensitivity_frame)
            st.subheader("Annual investment cashflow")
            cashflow_frame = pd.DataFrame(investment.annual_cashflows)
            st.dataframe(cashflow_frame, use_container_width=True, hide_index=True)
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
    selected_candidate = candidates[recommended]
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
        f"Integrity verified · SHA-256 {operator_record['record_sha256']} · "
        "human approval pending · device writes disabled"
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
except (ValueError, KeyError, TypeError) as exc:
    st.error(f"Could not build the decision dashboard: {exc}")
    st.caption("Check the scenario assumptions and the forecast/optimizer input contracts.")
