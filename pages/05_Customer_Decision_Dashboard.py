"""Customer-facing, forecast-led decision dashboard for the generic IslandOS platform.

The default scenario is synthetic. Results are offline planning estimates, not
measured customer savings, a site-validated forecast, or equipment commands.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math

import pandas as pd
import streamlit as st

from islandos_core.energy_system import BatterySpec, EnergySystemConfig
from islandos_core.customer_dashboard import parse_customer_history_csv
from islandos_core.forecast_engine import forecast_signals
from islandos_core.investment_economics import evaluate_investment_economics
from islandos_core.forecast_optimizer_adapter import (
    build_coordination_inputs,
    build_service_equivalent_economics,
    evaluate_forecast_stress_scenarios,
)
from optimization.energy_system_optimizer import (
    OptimizationWeights,
    optimize_energy_system,
)

st.set_page_config(
    page_title="IslandOS | Customer Decision Dashboard",
    page_icon="⚡",
    layout="wide",
)

st.title("Customer decision dashboard")
st.caption("Forecast → compare operating policies → review cost and reliability trade-offs")

st.info(
    "Demonstration mode: all default inputs are synthetic. Replace them with "
    "validated site data before using the results in a customer decision. "
    "This page performs offline screening only; it does not control equipment. "
    "Uploaded CSV files are processed by the hosted app server: upload only data "
    "you are authorized to share, and use redacted or non-sensitive exports."
)

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
    if site_csv is not None:
        st.caption("Demo load/tariff scaling sliders are ignored when a site CSV is uploaded.")
    st.divider()
    st.subheader("Investment assumptions")
    st.caption("Enter customer-confirmed annual bills and supplier quotes. Do not annualize the 24-hour simulation.")
    baseline_annual_bill = st.number_input("Baseline annual energy bill", min_value=0.0, value=0.0, step=1000.0)
    proposed_annual_bill = st.number_input("Proposed annual energy bill", min_value=0.0, value=0.0, step=1000.0)
    incremental_om = st.number_input("Annual incremental O&M cost (+ cost / − saving)", min_value=-10000000.0, max_value=10000000.0, value=0.0, step=500.0)
    upfront_capex = st.number_input("Installed equipment CAPEX", min_value=0.0, value=0.0, step=5000.0)
    project_life = st.slider("Project evaluation life (years)", 1, 30, 10)
    discount_rate_pct = st.slider("Discount rate (%)", 0.0, 30.0, 8.0, 0.5)
    has_replacement = st.checkbox("Include a future equipment replacement")
    replacement_year = st.number_input("Replacement year", min_value=1, max_value=30, value=min(8, project_life), step=1) if has_replacement else None
    replacement_cost = st.number_input("Replacement cost", min_value=0.0, value=0.0, step=1000.0) if has_replacement else 0.0
    residual_value = st.number_input("Residual value at end of project", min_value=0.0, value=0.0, step=1000.0)

now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
history = {"pv_power": [], "wind_power": [], "essential_load": [], "electricity_price": []}
source_sha256 = None
source_label = "Synthetic demonstration data"
if site_csv is not None:
    try:
        uploaded = parse_customer_history_csv(site_csv.getvalue(), source_name=site_csv.name)
        history_stamps = list(uploaded.timestamps_utc)
        history = {name: list(values) for name, values in uploaded.signals.items()}
        source_sha256 = uploaded.source_sha256
        source_label = f"User-uploaded: {uploaded.source_name} (not independently verified)"
    except ValueError as exc:
        st.error(f"Site history CSV rejected: {exc}")
        st.stop()
else:
    history_stamps = [now - timedelta(hours=168 - index) for index in range(168)]
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

st.caption(f"Input provenance: {source_label}")

units = {
    "pv_power": "kW",
    "wind_power": "kW",
    "essential_load": "kW",
    "electricity_price": f"{currency}/kWh",
}

try:
    bundle = forecast_signals(
        history_stamps,
        history,
        units,
        horizon=24,
        non_negative_signals=("pv_power", "wind_power", "essential_load"),
    )
    coordinated = build_coordination_inputs(
        bundle,
        grid_available=[True] * 24,
        price_unit=f"{currency}/kWh",
    )
    battery = None
    if battery_capacity > 0 and battery_power > 0:
        battery = BatterySpec(
            capacity_kwh=float(battery_capacity),
            max_charge_kw=float(battery_power),
            max_discharge_kw=float(battery_power),
            initial_soc=0.60,
            min_soc=0.10,
            max_soc=0.95,
        )
    config = EnergySystemConfig(
        pv_rated_kw=float(pv_capacity),
        wind_rated_kw=float(wind_capacity),
        grid_import_limit_kw=float(grid_limit),
        battery=battery,
    )
    weights = OptimizationWeights(
        cost=float(cost_priority),
        reliability=float(1.0 - cost_priority),
        curtailment=0.0,
        battery_wear=0.0,
    )
    result = optimize_energy_system(coordinated.inputs, config, weights=weights)
    economics = build_service_equivalent_economics(result)
    stress = evaluate_forecast_stress_scenarios(coordinated, config)

    recommended = result["recommendation"]["policy"]
    candidates = {row["policy"]: row for row in result["candidates"]}
    selected = candidates[recommended]["summary"]
    baseline = candidates["grid_first"]["summary"]
    service_equal = economics["service_equivalent"]

    st.subheader("Decision snapshot")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Recommended policy", recommended.replace("_", " ").title())
    m2.metric("Estimated 24h energy cost", f"{selected['estimated_energy_cost']:,.2f} {currency}")
    m3.metric("Unmet energy", f"{selected['unmet_load_kwh']:,.2f} kWh")
    if service_equal and economics.get("cost_comparison_valid"):
        saving = economics.get("estimated_cost_reduction")
        m4.metric("Modeled cost difference vs grid-first",
                  f"{saving:,.2f} {currency}" if saving is not None else "Not available")
    else:
        m4.metric("Customer savings claim", "Withheld")
    if not service_equal:
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

    investment = evaluate_investment_economics(
        baseline_annual_energy_cost=float(baseline_annual_bill),
        proposed_annual_energy_cost=float(proposed_annual_bill),
        annual_incremental_om_cost=float(incremental_om),
        upfront_capex=float(upfront_capex),
        project_life_years=int(project_life),
        discount_rate=float(discount_rate_pct) / 100.0,
        replacement_year=int(replacement_year) if replacement_year is not None else None,
        replacement_cost=float(replacement_cost),
        residual_value=float(residual_value),
        service_equivalent=bool(service_equal and economics.get("cost_comparison_valid")),
    )
    st.subheader("Equipment investment screen")
    st.caption(
        "Lifecycle results use customer-entered annual bills, supplier CAPEX, and O&M assumptions. "
        "They are not inferred from the 24-hour simulation and are not a procurement guarantee."
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
        st.caption("Sensitivity varies the entered annual energy saving by ±20%; all other assumptions remain fixed.")
        st.bar_chart(sensitivity_frame)
    investment_report = investment.to_dict()
    investment_report["assumptions"] = {
        "baseline_annual_energy_cost": baseline_annual_bill,
        "proposed_annual_energy_cost": proposed_annual_bill,
        "annual_incremental_om_cost": incremental_om,
        "upfront_capex": upfront_capex,
        "project_life_years": project_life,
        "discount_rate": discount_rate_pct / 100.0,
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
        "investment_economics": investment_report,
        "scope": "offline screening; not measured savings or equipment control",
    }
    st.download_button(
        "Download decision report (JSON)",
        data=json.dumps(report, indent=2, default=str).encode("utf-8"),
        file_name="islandos_customer_decision_report.json",
        mime="application/json",
    )
except (ValueError, KeyError, TypeError) as exc:
    st.error(f"Could not build the decision dashboard: {exc}")
    st.caption("Check the scenario assumptions and the forecast/optimizer input contracts.")
