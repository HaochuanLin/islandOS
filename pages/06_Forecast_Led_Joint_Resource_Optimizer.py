"""Generic canonical-catalog prediction-to-joint-resource decision page (Stage F).

Synthetic inputs are used by default. Uploaded site history is not independently
verified. Outputs are offline schedule-search estimates, never device commands.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from islandos_core.customer_dashboard import parse_customer_history_csv
from islandos_core.session_dataset import clear_session_dataset, get_session_dataset
from islandos_core.energy_system import BatterySpec, DieselSpec, EnergySystemConfig
from islandos_core.prediction_dispatch_adapter import optimize_prediction_resource_schedule
from islandos_core.forecast_signal_catalog import forecast_site_signals


st.set_page_config(page_title="IslandOS | Joint Resource Optimizer", page_icon="⚡", layout="wide")
st.title("Forecast-led joint resource optimizer")
st.caption("One pipeline: site history → model selection → aligned forecasts → battery/diesel schedule search")

st.info(
    "Default inputs are synthetic. Uploaded CSV values are customer-supplied and not independently verified. "
    "This page performs offline planning only: it does not connect to live telemetry or write commands to equipment."
)

with st.sidebar:
    st.subheader("Site and asset assumptions")
    currency = st.text_input("Tariff currency", "USD").strip() or "currency"
    upload = st.file_uploader("Hourly site history CSV (optional)", type=["csv"])
    shared_dataset = get_session_dataset(st.session_state)
    if shared_dataset is not None:
        st.caption(f"Session dataset available: {shared_dataset['file_name']} · SHA-256 {shared_dataset['sha256'][:12]}…")
        if st.button("Clear session dataset", key="clear_shared_dataset_joint_optimizer"):
            clear_session_dataset(st.session_state)
            st.rerun()
    pv_capacity = st.number_input("PV rated power (kW)", min_value=0.0, value=40.0, step=1.0)
    wind_capacity = st.number_input("Wind rated power (kW)", min_value=0.0, value=20.0, step=1.0)
    grid_limit = st.number_input("Grid import limit (kW)", min_value=0.0, value=100.0, step=5.0)
    battery_capacity = st.number_input("Battery capacity (kWh)", min_value=1.0, value=80.0, step=5.0)
    battery_power = st.number_input("Battery power limit (kW)", min_value=1.0, value=20.0, step=1.0)
    diesel_capacity = st.number_input("Diesel rated power (kW)", min_value=1.0, value=30.0, step=1.0)
    diesel_cost = st.number_input(f"Diesel variable cost ({currency}/kWh)", min_value=0.0, value=0.32, step=0.01)
    population = st.slider("Search population", 4, 40, 12, 4)
    generations = st.slider("Search generations", 1, 20, 5)
    seed = st.number_input("Reproducible search seed", min_value=0, value=20261113, step=1)

now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
source = "Synthetic demonstration data"
shared_payload = None
shared_name = "session-shared CSV"
if upload is not None:
    shared_payload = upload.getvalue()
    shared_name = upload.name
elif shared_dataset is not None:
    shared_payload = shared_dataset["payload"]
    shared_name = shared_dataset["file_name"]
if shared_payload is not None:
    try:
        site = parse_customer_history_csv(shared_payload, source_name=shared_name)
    except ValueError as exc:
        st.error(f"CSV rejected: {exc}")
        st.stop()
    timestamps = list(site.timestamps_utc)
    values = {name: list(series) for name, series in site.signals.items()}
    prefix = "Customer-uploaded" if upload is not None else "Session-shared"
    source = f"{prefix} CSV: {site.source_name} (not independently verified)"
    source_hash = site.source_sha256
else:
    timestamps = [now - timedelta(hours=167 - i) for i in range(168)]
    values = {"pv_power": [], "wind_power": [], "essential_load": [], "electricity_price": []}
    for i, stamp in enumerate(timestamps):
        hour = stamp.hour
        solar = max(0.0, 30.0 * math.sin(math.pi * (hour - 6) / 12.0))
        values["pv_power"].append(min(pv_capacity, solar * (0.86 + 0.08 * math.sin(i * 0.17))))
        values["wind_power"].append(min(wind_capacity, 8.0 + 3.0 * math.sin(i * 0.21 + 0.7)))
        values["essential_load"].append(20.0 + 4.0 * (hour in range(17, 23)) + 2.0 * (hour in range(7, 10)))
        values["electricity_price"].append(0.08 if hour < 6 else 0.27 if hour in range(17, 22) else 0.16)
    source_hash = None

st.caption(f"Data provenance: {source}")
st.caption(f"History window: {timestamps[0].isoformat()} → {timestamps[-1].isoformat()} ({len(timestamps)} hourly rows)")

signal_history = {
    "pv_power_kw": values["pv_power"],
    "wind_power_kw": values["wind_power"],
    "load_kw": values["essential_load"],
    "tariff_per_kwh": values["electricity_price"],
}
signal_units = {
    "pv_power_kw": "kW",
    "wind_power_kw": "kW",
    "load_kw": "kW",
    "tariff_per_kwh": f"{currency}/kWh",
}
predictions = {}
try:
    # The UI now uses the same canonical signal catalog as customer onboarding.
    forecast_bundle = forecast_site_signals(
        timestamps,
        signal_history,
        signal_units,
        horizon=24,
        backtest_horizon=24,
        season_length=24,
        confidence_level=0.90,
    )
    predictions = dict(forecast_bundle.results)
    target_timestamps = tuple(
        point.timestamp for point in predictions["pv_power_kw"].points
    )

    config = EnergySystemConfig(
        pv_rated_kw=float(pv_capacity),
        wind_rated_kw=float(wind_capacity),
        grid_import_limit_kw=float(grid_limit),
        battery=BatterySpec(
            capacity_kwh=float(battery_capacity),
            max_charge_kw=float(battery_power),
            max_discharge_kw=float(battery_power),
            initial_soc=0.60,
            min_soc=0.10,
            max_soc=0.95,
        ),
        diesel=DieselSpec(
            rated_power_kw=float(diesel_capacity),
            variable_cost_per_kwh=float(diesel_cost),
            ramp_up_kw_per_hour=float(diesel_capacity),
        ),
    )
    with st.spinner("Running the joint battery/diesel schedule search…"):
        result = optimize_prediction_resource_schedule(
            predictions,
            config,
            history_start_utc=timestamps[0],
            history_end_utc=timestamps[-1],
            grid_available=[True] * 24,
            diesel_available=[True] * 24,
            price_unit=f"{currency}/kWh",
            population_size=int(population),
            generations=int(generations),
            seed=int(seed),
        )

    handoff = result["generic_prediction_handoff"]
    st.subheader("Prediction engine")
    model_rows = []
    for canonical_id, forecast in predictions.items():
        model_rows.append({
            "Signal": canonical_id,
            "Selected model": f"{forecast.model_id}@{forecast.model_version}",
            "Rolling-origin MAE": forecast.backtest.mae,
            "Rolling-origin RMSE": forecast.backtest.rmse,
            "Error-band samples": forecast.interval_calibration_samples,
            "Unit": forecast.unit,
        })
    st.dataframe(pd.DataFrame(model_rows), use_container_width=True, hide_index=True)
    st.caption("Built-in candidates are statistical baselines. Backtest scores describe only the supplied history.")

    st.subheader("Recommended joint schedule")
    recommendation = result["recommendation"]
    recommended_policy = recommendation.get("policy", "optimizer recommendation")
    st.metric("Selected policy", str(recommended_policy).replace("_", " ").title())
    candidates = result.get("candidates", [])
    comparison_rows = []
    for candidate in candidates:
        summary = candidate.get("summary", {})
        comparison_rows.append({
            "Policy": candidate.get("policy", "unknown").replace("_", " ").title(),
            "Estimated cost": summary.get("estimated_energy_cost"),
            "Grid import (kWh)": summary.get("grid_import_kwh"),
            "Diesel generation (kWh)": summary.get("diesel_generation_kwh"),
            "Unmet load (kWh)": summary.get("unmet_load_kwh"),
            "Critical unmet load (kWh)": summary.get("critical_unmet_load_kwh"),
            "Battery degradation cost": summary.get("battery_degradation_cost"),
        })
    if comparison_rows:
        st.dataframe(pd.DataFrame(comparison_rows), use_container_width=True, hide_index=True)
    economics = result.get("robust_customer_economics", {})
    if economics.get("cost_comparison_valid"):
        st.metric(
            "Modeled cost reduction vs grid-first",
            f"{economics.get('estimated_cost_reduction', 0.0):,.2f} {currency}",
        )
        st.caption("Displayed only because modeled service is equivalent; this is not measured customer savings.")
    else:
        st.warning(economics.get("interpretation", "Service equivalence did not pass; savings are withheld."))

    schedule_rows = []
    schedule_keys = (
        "battery_setpoints_kw", "diesel_setpoints_kw", "grid_import_setpoints_kw",
        "grid_export_setpoints_kw",
    )
    for key in schedule_keys:
        series = recommendation.get(key)
        if series is not None:
            for index, value in enumerate(series):
                schedule_rows.append({
                    "Timestamp (UTC)": target_timestamps[index],
                    "Setpoint": key.replace("_setpoints_kw", "").replace("_", " ").title(),
                    "Power (kW)": value,
                })
    if schedule_rows:
        st.subheader("Hourly setpoint schedule")
        schedule_frame = pd.DataFrame(schedule_rows)
        st.line_chart(schedule_frame.pivot(index="Timestamp (UTC)", columns="Setpoint", values="Power (kW)"))
        st.dataframe(schedule_frame, use_container_width=True, hide_index=True)
    else:
        st.caption("Schedule vectors are available in the downloadable audit report.")

    with st.expander("Decision trace, model provenance and limitations"):
        st.write({
            "source_file_sha256": source_hash,
            "forecast_handoff": handoff,
            "forecast_scenario_scope": result.get("forecast_scenario_scope"),
            "decision_scope": result.get("decision_scope"),
            "objective": result.get("objective"),
            "optimizer": "bounded seeded heuristic; not a guaranteed global optimum",
            "device_write_authorized": handoff.get("device_write_authorized"),
        })
        st.caption("Stress envelopes are deterministic and are not probabilistic joint confidence intervals.")

    report = {
        "input_provenance": source,
        "source_file_sha256": source_hash,
        "forecast_models": {
            key: {"model_id": value.model_id, "model_version": value.model_version,
                  "backtest_mae": value.backtest.mae, "backtest_rmse": value.backtest.rmse}
            for key, value in predictions.items()
        },
        "recommendation": recommendation,
        "policy_comparison": comparison_rows,
        "robust_customer_economics": economics,
        "generic_prediction_handoff": handoff,
        "forecast_scenario_scope": result.get("forecast_scenario_scope"),
        "decision_scope": result.get("decision_scope"),
        "assumptions": {
            "pv_capacity_kw": pv_capacity, "wind_capacity_kw": wind_capacity,
            "grid_import_limit_kw": grid_limit, "battery_capacity_kwh": battery_capacity,
            "battery_power_limit_kw": battery_power, "diesel_capacity_kw": diesel_capacity,
            "diesel_variable_cost_per_kwh": diesel_cost, "currency": currency,
            "search_population": population, "search_generations": generations, "seed": seed,
        },
        "mode": "offline_schedule_search",
        "device_write_authorized": False,
    }
    st.download_button(
        "Download joint schedule audit (JSON)",
        data=json.dumps(report, indent=2, default=str).encode("utf-8"),
        file_name="islandos_joint_resource_schedule.json",
        mime="application/json",
    )
except (ValueError, KeyError, TypeError) as exc:
    st.error(f"Joint resource scheduling could not run: {exc}")
    st.caption("Check the hourly history, units, forecast horizon, and explicit asset assumptions.")
