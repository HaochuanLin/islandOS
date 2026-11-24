"""Generic canonical-catalog prediction-to-joint-resource decision page (Stage F).

Synthetic inputs are used by default. Uploaded site history is not independently
verified. Outputs are offline schedule-search estimates, never device commands.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from islandos_ui.upload_guard import offer_schema_conformant_csv, reject_upload
from islandos_ui.page_header import render_page_header
from islandos_ui.decision_record_panel import render_decision_record

from islandos_core.customer_dashboard import parse_customer_history_csv
from islandos_core.session_dataset import clear_session_dataset, read_session_dataset
from islandos_core.site_inputs import (
    BATTERY_INITIAL_SOC,
    BATTERY_MAX_SOC,
    BATTERY_MIN_SOC,
    SiteAssumptions,
)
from islandos_core.app_view_models import (
    build_annual_projection,
    build_run_request,
    build_run_result_summary,
)
from islandos_core.canonical_run import create_run_manifest, deterministic_run_id
from islandos_core.demo_site_history import (
    build_synthetic_site_history,
    demo_anchor_for_hour,
)
from islandos_core.demo_clock_defaults import DEMO_CLOCK_DEFAULT_DATE, DEMO_CLOCK_DEFAULT_HOUR
from islandos_core.annual_operating_basis import (
    annualise_run_summary,
    verify_annual_operating_basis,
)
from islandos_core.run_orchestration import run_joint_optimizer


st.set_page_config(page_title="IslandOS | Joint Resource Optimizer", page_icon="⚡", layout="wide")
st.title("Forecast-led joint resource optimizer")
st.caption("One pipeline: site history → model selection → aligned forecasts → battery/diesel schedule search")

render_page_header(
    question="What battery and diesel schedule follows from aligned forecasts for this site?",
    data="The synthetic default, or an uploaded history put through the canonical forecast catalogue.",
    conclusions="A candidate schedule, its energy balance, and whether the constraints bind.",
    limits="A schedule-search result only: no device commands and no warranty of feasibility on real equipment.",
)

st.info(
    "Default inputs are synthetic. Uploaded CSV values are customer-supplied and not independently verified. "
    "This page performs offline planning only: it does not connect to live telemetry or write commands to equipment."
)

now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

with st.sidebar:
    st.subheader("Site and asset assumptions")
    currency = st.text_input("Tariff currency", "USD").strip() or "currency"
    upload = st.file_uploader("Hourly site history CSV (optional)", type=["csv"])
    shared_dataset, dataset_error = read_session_dataset(st.session_state)
    if dataset_error:
        st.warning(
            "The shared session dataset was discarded: "
            f"{dataset_error}. Upload the file again on this page or use the shared "
            "upload control if you still need it."
        )
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
    st.divider()
    st.subheader("Demo clock")
    demo_date = st.date_input(
        "Demo date (UTC)", value=DEMO_CLOCK_DEFAULT_DATE, key="demo_date_joint_optimizer",
        help=(
            "The date the synthetic window ends on. Defaults to 2026-11-22, frozen so "
            "the default screen is reproducible."
        ),
    )
    demo_hour = st.slider(
        "Demo clock (UTC hour)", 0, 23, DEMO_CLOCK_DEFAULT_HOUR, key="demo_clock_hour_joint_optimizer",
        help=(
            "Pins the synthetic default history to this UTC hour so a recorded annual "
            "figure can be reproduced. It has no effect on an uploaded CSV."
        ),
    )
    st.caption(
        "Synthetic default only, frozen at 2026-11-22 14:00 UTC; move either control to "
        "reproduce another hour. An uploaded CSV carries its own timestamps."
    )

demo_anchor = demo_anchor_for_hour(now, int(demo_hour), demo_date=demo_date)
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
        reject_upload("Site history CSV", exc)
        offer_schema_conformant_csv()
        st.stop()
    timestamps = list(site.timestamps_utc)
    values = {name: list(series) for name, series in site.signals.items()}
    prefix = "Customer-uploaded" if upload is not None else "Session-shared"
    source = f"{prefix} CSV: {site.source_name} (not independently verified)"
    source_hash = site.source_sha256
else:
    # The default window is synthetic and its anchor is the demo clock, not the
    # wall clock; the builder takes that anchor as an argument so a test can pin it.
    synthetic = build_synthetic_site_history(
        demo_anchor, pv_rated_kw=float(pv_capacity), wind_rated_kw=float(wind_capacity)
    )
    timestamps = list(synthetic.timestamps)
    values = {
        "pv_power": list(synthetic.pv_power_kw),
        "wind_power": list(synthetic.wind_power_kw),
        "essential_load": list(synthetic.load_kw),
        "electricity_price": list(synthetic.tariff_per_kwh),
    }
    source_hash = None

st.caption(f"Data provenance: {source}")
demo_note = f" · Demo clock pin {int(demo_hour):02d}:00 UTC" if shared_payload is None else ""
st.caption(
    f"History window: {timestamps[0].isoformat()} → {timestamps[-1].isoformat()} "
    f"({len(timestamps)} hourly rows){demo_note}"
)

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
    site_assumptions = SiteAssumptions(
        pv_rated_kw=float(pv_capacity),
        wind_rated_kw=float(wind_capacity),
        grid_import_limit_kw=float(grid_limit),
        battery_capacity_kwh=float(battery_capacity),
        battery_power_kw=float(battery_power),
        battery_initial_soc=BATTERY_INITIAL_SOC,
        battery_min_soc=BATTERY_MIN_SOC,
        battery_max_soc=BATTERY_MAX_SOC,
        diesel_rated_kw=float(diesel_capacity),
        diesel_variable_cost_per_kwh=float(diesel_cost),
    )
    config = site_assumptions.to_energy_system_config()
    grid_available = [True] * 24
    diesel_available = [True] * 24
    # The request this run answers, in the shared application-facing shape: site,
    # history with units and provenance, and the run-specific settings (search knobs and
    # availability). No page-specific block exists on this page, so it stays empty.
    run_request_view = build_run_request(
        page="joint_resource_optimizer",
        site=site_assumptions,
        timestamps=timestamps,
        history=signal_history,
        units=signal_units,
        page_settings={},
        run_settings={
            "currency": currency,
            "optimizer_settings": {
                "population_size": int(population),
                "generations": int(generations),
                "seed": int(seed),
            },
            "availability": {
                "grid_all_hours": bool(all(grid_available)),
                "diesel_all_hours": bool(all(diesel_available)),
            },
        },
        provenance=source,
        source_sha256=source_hash,
    )
    dataset_payload = {
        "timestamps_utc": [stamp.isoformat() for stamp in timestamps],
        "signals": signal_history,
        "units": signal_units,
    }
    dataset_digest = source_hash or hashlib.sha256(
        json.dumps(dataset_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    site_configuration_digest = hashlib.sha256(
        json.dumps(asdict(config), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    # The run's identity is derived from the inputs that define it, not from the wall clock.
    # A page that reruns on every widget change would otherwise mint a new uuid on every
    # keystroke, so two downloads of the same pinned window would carry different digests
    # and a reader could not tell whether they hold the same record. The manifest's
    # created_at is the window the run speaks for (the demo anchor for synthetic data, the
    # last history hour for an uploaded CSV), not the moment the page was opened.
    created_at = demo_anchor if shared_payload is None else timestamps[-1]
    run_id = deterministic_run_id(
        "run",
        {
            "dataset_sha256": dataset_digest,
            "site_configuration_sha256": site_configuration_digest,
            "window_end_utc": created_at.isoformat(),
            "currency": currency,
            "optimizer_settings": {
                "population_size": int(population),
                "generations": int(generations),
                "seed": int(seed),
            },
            "availability": {
                "grid_all_hours": bool(all(grid_available)),
                "diesel_all_hours": bool(all(diesel_available)),
            },
        },
    )
    run_manifest = create_run_manifest(
        project_id="streamlit-joint-resource-workspace",
        run_id=run_id,
        site_ref="customer-uploaded-site" if shared_payload is not None else "synthetic-demo-site",
        created_at_utc=created_at.isoformat(),
        dataset_sha256=dataset_digest,
        dataset_schema_version="canonical-hourly-signals-v1",
        source_type="customer_provided" if shared_payload is not None else "synthetic",
        site_configuration_version="1",
        site_configuration_sha256=site_configuration_digest,
        required_signals=signal_units,
        forecast_horizon_hours=24,
        optimizer_id="prediction_resource_dispatch",
        optimizer_version="1",
        optimizer_settings={
            "population_size": int(population),
            "generations": int(generations),
            "seed": int(seed),
        },
        scenario_assumptions={
            "grid_available": grid_available,
            "diesel_available": diesel_available,
        },
        forecast_settings={
            "backtest_horizon": 24,
            "season_length": 24,
            "confidence_level": 0.90,
        },
    )
    with st.spinner("Validating run manifest, forecasting and searching the joint resource schedule…"):
        # The canonical call order lives in islandos_core.run_orchestration, not in the page.
        run_outputs = run_joint_optimizer(
            run_manifest=run_manifest,
            timestamps=timestamps,
            history=signal_history,
            units=signal_units,
            config=config,
            grid_available=grid_available,
            diesel_available=diesel_available,
        )
    planning_run = run_outputs["planning_run"]
    predictions = run_outputs["predictions"]
    target_timestamps = run_outputs["target_timestamps"]
    result = run_outputs["result"]
    handoff = run_outputs["handoff"]
    st.caption(f"Canonical run: {planning_run['run_id']} · Manifest SHA-256: {planning_run['manifest_sha256'][:16]}… · Evidence SHA-256: {planning_run['evidence_sha256'][:16]}…")
    render_decision_record(planning_run["decision_record"])
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
    result_view = build_run_result_summary(
        page="joint_resource_optimizer",
        result=result,
        planning_run=planning_run,
        currency=currency,
    )
    st.metric("Selected policy", result_view["recommended_policy_label"])
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

    # The run above is 24 hours. A year is a different object, and this is where the
    # page says so instead of quietly multiplying by 365: the reader declares how many
    # days the simulated day stands for, and the record prints that declaration.
    st.subheader("Annual operating basis")
    st.caption(
        "Everything above is one simulated 24-hour day. Annual operating figures are not "
        "derived on this page unless an equal-days assumption is declared below; the "
        "investment screen on the customer dashboard takes customer-entered annual bills "
        "instead, and the two are not interchangeable."
    )
    selected_summary = None
    selected_dispatch_rows = []
    summary_source = ""
    # The optimizer behind this page returns the recommended schedule's own 24-hour
    # dispatch (nominal scenario) together with its summary. That dispatch is the run
    # the setpoint chart above draws, so it is the only honest thing to project: using
    # a per-scenario replay or a candidate summary would annualise a different day
    # than the one on screen. The policy-keyed candidate path is kept as a fallback for
    # any optimizer variant that returns candidates instead.
    dispatch = recommendation.get("dispatch")
    if isinstance(dispatch, dict) and isinstance(dispatch.get("summary"), dict) and dispatch["summary"]:
        selected_summary = dispatch["summary"]
        selected_dispatch_rows = list(dispatch.get("rows") or [])
        summary_source = (
            "recommended schedule's own nominal dispatch summary (the same 24-hour run "
            "that produced the hourly setpoint rows on this page)"
        )
    else:
        for candidate in candidates:
            if candidate.get("policy") == recommended_policy:
                selected_summary = candidate.get("summary")
                selected_dispatch_rows = list((candidate.get("dispatch") or {}).get("rows") or [])
                summary_source = "summary of the candidate the optimizer selected"
                break
    annual_record = None
    annual_view = None
    project_annual = st.checkbox(
        "Project this 24-hour run onto a year (declared equal-days assumption)",
        key="annual_projection_joint_optimizer",
    )
    if project_annual:
        days_equivalent = st.slider(
            "Days the simulated day stands for, per year", 1, 366, 365, key="annual_days_joint_optimizer",
        )
        if selected_summary is None:
            st.warning("The recommended policy's summary is missing, so no annual projection is produced.")
        else:
            annual_record = annualise_run_summary(
                selected_summary,
                dispatch_rows=selected_dispatch_rows,
                simulated_hours=len(target_timestamps),
                days_equivalent_per_year=int(days_equivalent),
                run_id=planning_run["run_id"],
                manifest_sha256=planning_run["manifest_sha256"],
                data_provenance=source,
                summary_source=summary_source,
            )
            annual_verification = verify_annual_operating_basis(annual_record)
            if not annual_verification["valid"]:
                st.error(
                    "Annual operating basis integrity check failed: "
                    + "; ".join(annual_verification["errors"])
                )
                st.stop()
            annual_view = build_annual_projection(annual_record, currency=currency)
            figures = annual_view["figures"]
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Annual load energy", f"{figures['annual_load_energy_kwh']:,.0f} kWh")
            a2.metric(f"Annual energy cost ({currency})", f"{figures['annual_energy_cost']:,.2f}")
            a3.metric(f"Annual equipment operating cost ({currency})", f"{figures['annual_equipment_operating_cost']:,.2f}")
            a4.metric("Annual diesel run hours", f"{figures['annual_diesel_run_hours']:,.0f} h")
            st.caption(
                f"This projection belongs to the {target_timestamps[0].isoformat()} → "
                f"{target_timestamps[-1].isoformat()} window."
                + (
                    f" Demo clock pin {int(demo_hour):02d}:00 UTC; a different hour projects "
                    "a different day and a different annual cost."
                    if shared_payload is None else ""
                )
            )
            st.caption(
                f"Assumption: {annual_view['basis']['days_equivalent_per_year']} simulated day(s) per year "
                f"({annual_view['basis']['hours_equivalent_per_year']} hours), each standing for the "
                "annual average day — no seasonal weighting, no load growth, no tariff-year change. "
                "Equipment operating cost is a breakdown of the energy cost above (fuel, battery "
                "throughput, diesel start/stop), not an addition to it. This is a projection of an "
                "offline run, not a bill, not measured consumption, and not site-validated."
            )
            st.caption(
                f"Traceable to run {annual_view['run_id']} · Manifest SHA-256 "
                f"{annual_view['manifest_sha256'][:16]}… · Projection SHA-256 "
                f"{annual_view['projection_sha256'][:16]}…"
            )
            st.caption(
                f"Projected figure source: {annual_view['summary_source']}. Each scenario in the "
                "run replays this same schedule under different inputs; annualising the base day "
                "does not annualise the worst case, and no scenario probability is assigned."
            )
    else:
        st.caption(
            "Annual figures are withheld: nothing is annualised until an equal-days assumption is "
            "declared, because one simulated day is not a year."
        )

    with st.expander("Decision trace, model provenance and limitations"):
        st.write({
            "source_file_sha256": source_hash,
            "canonical_run_manifest": planning_run["manifest"],
            "canonical_run_forecast_evidence": planning_run["forecast"],
            "evidence_sha256": planning_run["evidence_sha256"],
            "forecast_handoff": handoff,
            "forecast_scenario_scope": result.get("forecast_scenario_scope"),
            "decision_scope": result.get("decision_scope"),
            "physical_audit": result.get("physical_audit"),
            "operator_decision_record": planning_run["decision_record"],
            "objective": result.get("objective"),
            "optimizer": "bounded seeded heuristic; not a guaranteed global optimum",
            "device_write_authorized": handoff.get("device_write_authorized"),
        })
        st.caption("Stress envelopes are deterministic and are not probabilistic joint confidence intervals.")

    report = {
        "canonical_run": {
            "project_id": planning_run["project_id"],
            "run_id": planning_run["run_id"],
            "manifest": planning_run["manifest"],
            "manifest_sha256": planning_run["manifest_sha256"],
            "forecast": planning_run["forecast"],
            "evidence_sha256": planning_run["evidence_sha256"],
            "decision_record": planning_run["decision_record"],
            "decision_record_sha256": planning_run["decision_record_sha256"],
            "human_review_required": planning_run["human_review_required"],
            "operator_approval": planning_run["operator_approval"],
            "device_write_authorized": planning_run["device_write_authorized"],
            "command_generated": planning_run["command_generated"],
        },
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
        "annual_operating_basis": annual_record,
        # The application-facing view models, so a reader (or a non-Streamlit client) gets
        # the same validated shapes the page rendered, not a second hand-built copy.
        "application_views": {
            "request": run_request_view,
            "result": result_view,
            "annual": annual_view,
        },
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
