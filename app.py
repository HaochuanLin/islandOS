from __future__ import annotations

"""islandOS interactive energy-water strategy screening app.

This is a planning/simulation interface, not a live microgrid controller.
Uploaded site data is used as supplied; the built-in demo is synthetic.
"""

import csv
import io
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from app_state import strategy_run_signature

import pandas as pd
import streamlit as st

from experiments.compare_energy_water_strategies import (
    REQUIRED_COLUMNS,
    Config,
    SiteStep,
    compare_strategies,
    load_site_steps,
)
from experiments.nsga2_dispatch_optimizer import optimize_dispatch
from experiments.rolling_horizon_dispatch import (
    run_experiment as run_rolling_dispatch_experiment,
    summarize_aggregate as summarize_rolling_aggregate,
    summarize_experiment as summarize_rolling_experiment,
    summarize_weight_sensitivity as summarize_rolling_weight_sensitivity,
    parse_scenario_csv as parse_rolling_scenario_csv,
    simulate_rolling as simulate_rolling_dispatch,
    generate_synthetic_scenario_csv as generate_rolling_dispatch_template,
)

st.set_page_config(
    page_title="islandOS | Energy-Water Planner",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.8rem; padding-bottom: 3rem; max-width: 1400px;}
      .hero {padding: 1.5rem 1.7rem; border-radius: 18px;
             background: linear-gradient(120deg, #102d3b, #176b70); color: white;
             margin-bottom: 1rem;}
      .hero h1 {color: white; margin-bottom: .35rem; font-size: 2.25rem;}
      .hero p {color: #e0f2f1; margin-bottom: .2rem; font-size: 1.05rem;}
      .note {padding: .8rem 1rem; border-left: 4px solid #d69e36;
             background: rgba(214,158,54,.10); border-radius: 5px;}
      div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.25);
          padding: .8rem; border-radius: 12px;}
    </style>
    """,
    unsafe_allow_html=True,
)


def demo_csv_bytes(hours: int = 168) -> bytes:
    """Create a synthetic, repeatable example dataset."""
    output = io.StringIO()
    fields = list(REQUIRED_COLUMNS) + ["backup_available_kw"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    start = datetime(2026, 1, 1)
    for i in range(hours):
        timestamp = start + timedelta(hours=i)
        hour = timestamp.hour
        day = timestamp.day
        solar = max(0.0, 34.0 * math.sin(math.pi * (hour - 6) / 12.0))
        wind = 5.0 + 4.0 * (0.5 + 0.5 * math.sin(i * 0.37))
        demand = 18.0 + 5.0 * (hour in range(18, 23)) + 2.0 * (hour in range(7, 10))
        surplus = max(0.0, solar + wind - demand)
        diesel_potential = max(0.0, min(8.0, solar + wind - 12.0))
        off_peak = hour < 7 or hour >= 23
        price = 0.12 if off_peak else (0.28 if hour in range(17, 22) else 0.20)
        writer.writerow({
            "timestamp": timestamp.isoformat(timespec="minutes"),
            "renewable_surplus_kw": round(surplus, 3),
            "diesel_displacement_potential_kw": round(diesel_potential, 3),
            "grid_price_per_kwh": price,
            "off_peak": str(off_peak).lower(),
            "grid_available": "true",
            "water_demand_m3": round(1.0 + (0.35 if hour in range(6, 9) or hour in range(18, 21) else 0.0), 3),
            "backup_available_kw": 30.0 if day % 5 else 0.0,
        })
    return output.getvalue().encode("utf-8")


def csv_template_bytes() -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(list(REQUIRED_COLUMNS) + ["backup_available_kw"])
    writer.writerow([
        "2026-01-01T00:00:00", 0, 0, 0.12, "true", "true", 1.0, 0
    ])
    return output.getvalue().encode("utf-8")


def parse_uploaded_csv(raw: bytes) -> list[SiteStep]:
    """Parse uploaded data using the repository's existing validation logic."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as temp:
        temp.write(raw)
        temp_path = Path(temp.name)
    try:
        return load_site_steps(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def dataframe_csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


with st.sidebar:
    st.markdown("## 🌊 islandOS")
    st.caption("Island energy + water planning")
    page = st.radio(
        "Navigate",
        ["Overview", "Strategy simulator", "Rolling dispatch lab", "Custom dispatch CSV", "Data guide"],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("Research prototype · not for real-time control")
    st.download_button(
        "⬇ Download CSV template",
        data=csv_template_bytes(),
        file_name="islandos_site_data_template.csv",
        mime="text/csv",
        use_container_width=True,
    )

if page == "Overview":
    st.markdown(
        """
        <div class="hero">
          <h1>Plan energy. Protect essential services. Make water.</h1>
          <p>Explore how flexible desalination could fit around renewable-energy availability,
          electricity costs, water demand, and operating constraints.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info(
        "This first web MVP runs the repository's existing strategy-comparison model. "
        "The built-in demo is synthetic; no real-island performance is implied."
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Strategy policies", "5", help="Baseline plus four RO operating policies")
    c2.metric("Input format", "Hourly CSV", help="Timestamped, aligned site time series")
    c3.metric("Output", "CSV + charts", help="Summary metrics and timestep-level audit")
    st.subheader("What is implemented now vs. the next optimization layer")
    existing_col, future_col = st.columns(2)
    with existing_col:
        st.markdown(
            "**Existing — heuristic fixed dispatch strategies**\n\n"
            "Implemented: five transparent if-else policies (no_ro_baseline, surplus_only, "
            "off_peak_only, hybrid_surplus_then_off_peak, emergency_backup), with "
            "water/energy metrics, hourly audit and CSV export."
        )
    with future_col:
        st.markdown(
            "**Experimental optimizer — NSGA-II Pareto search**\n\n"
            "The optimizer searches candidate hourly RO schedules and retains non-dominated "
            "feasible solutions. It is a model-based search, not machine learning trained on field data."
        )
    st.subheader("What this prototype helps you compare")
    left, right = st.columns(2)
    with left:
        st.markdown(
            """
            **Energy-side questions**
            - How much renewable surplus is available?
            - How much surplus could be used by the RO load?
            - What direct diesel-displacement potential must be preserved?
            - What would off-peak grid operation cost under the supplied tariff?
            """
        )
    with right:
        st.markdown(
            """
            **Water-side questions**
            - How much water is produced and served?
            - How much demand remains unmet?
            - Does the tank spill or finish with stored water?
            - How do minimum run-time and rated power affect operation?
            """
        )
    st.subheader("Recommended workflow")
    st.markdown(
        "1. Open **Strategy simulator** and run the labelled synthetic demo, or upload a site CSV.\n"
        "2. Set RO power, specific energy consumption, tank capacity, and run-time assumptions.\n"
        "3. Compare all five policies, inspect the hourly audit, and download results.\n"
        "4. Replace demo inputs with validated local measurements before making decisions."
    )
    st.markdown(
        '<div class="note"><b>Important:</b> available renewable energy is not automatically '
        'surplus. The uploaded series must already account for essential demand, reserves, '
        'and any other priority loads. This tool does not dispatch the real grid or equipment.</div>',
        unsafe_allow_html=True,
    )

elif page == "Strategy simulator":
    st.title("Energy-water strategy simulator")
    st.write("Run a transparent screening comparison using a demo dataset or your own aligned CSV.")
    source = st.radio("Data source", ["Synthetic demo (illustrative)", "Upload site CSV"], horizontal=True)
    uploaded = None
    if source == "Upload site CSV":
        uploaded = st.file_uploader("Upload hourly CSV", type=["csv"])
        st.caption("Required columns are listed in Data guide. No missing values are imputed.")
        if uploaded is None:
            st.stop()
        raw = uploaded.getvalue()
        source_label = f"User-uploaded file: {uploaded.name}"
    else:
        raw = demo_csv_bytes()
        source_label = "Synthetic demo data — not measured site data"

    with st.expander("Model assumptions", expanded=True):
        a, b, c = st.columns(3)
        with a:
            ro_kw = st.number_input("RO rated power (kW)", min_value=0.1, value=10.0, step=1.0)
            sec = st.number_input("Specific energy (kWh/m³)", min_value=0.1, value=4.0, step=0.1)
        with b:
            tank = st.number_input("Tank capacity (m³)", min_value=0.1, value=50.0, step=5.0)
            initial = st.number_input("Initial tank inventory (m³)", min_value=0.0, value=10.0, step=1.0)
        with c:
            min_run = st.number_input("Minimum run time (hours)", min_value=1, value=1, step=1)
            dt = st.number_input("Input interval (hours)", min_value=0.1, value=1.0, step=0.5)
            diesel_cost = st.number_input(
                "Backup energy cost (currency/kWh, optional)",
                min_value=0.0, value=0.0, step=0.05,
                help="Set to 0 to leave the optional estimate disabled. Use a site-specific value.",
            )
    if initial > tank:
        st.error("Initial tank inventory cannot exceed tank capacity.")
        st.stop()

    current_signature = strategy_run_signature(
        raw,
        source_label,
        {
            "ro_rated_power_kw": float(ro_kw),
            "specific_energy_kwh_m3": float(sec),
            "tank_capacity_m3": float(tank),
            "initial_water_m3": float(initial),
            "min_run_hours": int(min_run),
            "dt_hours": float(dt),
            "diesel_cost_per_kwh": float(diesel_cost) if diesel_cost > 0 else None,
        },
    )

    if st.button("▶ Run strategy comparison", type="primary", use_container_width=True):
        try:
            steps = parse_uploaded_csv(raw)
            config = Config(
                ro_rated_power_kw=float(ro_kw),
                specific_energy_kwh_m3=float(sec),
                tank_capacity_m3=float(tank),
                initial_water_m3=float(initial),
                min_run_hours=int(min_run),
                dt_hours=float(dt),
                diesel_cost_per_kwh=float(diesel_cost) if diesel_cost > 0 else None,
            )
            detail, summary = compare_strategies(steps, config)
            st.session_state["islandos_result"] = {
                "detail": detail,
                "summary": summary,
                "source": source_label,
                "input_signature": current_signature,
            }
            st.session_state.pop("islandos_optimizer_result", None)
        except Exception as exc:
            st.error(f"Could not run the comparison: {exc}")
            st.stop()

    result = st.session_state.get("islandos_result")
    if result and result.get("input_signature") != current_signature:
        st.warning(
            "Inputs changed since the last strategy run. Previous results were cleared; "
            "click Run strategy comparison to calculate results for the current settings."
        )
        st.session_state.pop("islandos_result", None)
        st.session_state.pop("islandos_optimizer_result", None)
        result = None
    if result:
        st.caption(f"Data provenance: **{result['source']}**")
        summaries = pd.DataFrame(result["summary"])
        details = pd.DataFrame(result["detail"])
        st.subheader("Results at a glance")
        preferred = summaries.loc[summaries["strategy"] == "hybrid_surplus_then_off_peak"].iloc[0]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Water produced", f"{preferred['water_produced_m3']:,.1f} m³",
                  help="Hybrid policy; modelled production, not guaranteed supply")
        m2.metric("Water served", f"{preferred['water_served_m3']:,.1f} m³")
        m3.metric("Unmet demand", f"{preferred['unmet_water_demand_m3']:,.1f} m³")
        m4.metric("Grid energy cost", f"{preferred['grid_energy_cost']:,.2f}",
                  help="Uses the price series supplied in the input; excludes other costs")
        st.subheader("Compare all policies")
        display_columns = [
            "strategy", "ro_run_hours", "water_produced_m3", "water_served_m3",
            "unmet_water_demand_m3", "surplus_energy_to_ro_kwh",
            "grid_energy_to_ro_kwh", "backup_energy_to_ro_kwh", "grid_energy_cost",
            "direct_diesel_displacement_potential_kwh",
        ]
        st.dataframe(summaries[display_columns], use_container_width=True, hide_index=True)
        st.caption(
            "Direct diesel-displacement potential is reported separately from RO consumption; "
            "this app does not claim that RO operation creates additional diesel savings."
        )
        st.subheader("Water outcomes by strategy")
        chart_df = summaries.set_index("strategy")[[
            "water_produced_m3", "water_served_m3", "unmet_water_demand_m3"
        ]]
        st.bar_chart(chart_df)
        st.subheader("Hourly operating audit")
        chosen = st.selectbox("Inspect strategy", summaries["strategy"].tolist(), index=3)
        chosen_rows = details[details["strategy"] == chosen].copy()
        if not chosen_rows.empty:
            chart = chosen_rows.set_index("timestamp")[[
                "ro_power_kw", "water_inventory_before_m3", "remaining_water_inventory_m3"
            ]]
            st.line_chart(chart)
        st.dataframe(chosen_rows, use_container_width=True, hide_index=True)
        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "⬇ Download strategy summary",
                dataframe_csv(result["summary"]),
                file_name="islandos_strategy_summary.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with d2:
            st.download_button(
                "⬇ Download timestep audit",
                dataframe_csv(result["detail"]),
                file_name="islandos_timestep_audit.csv",
                mime="text/csv",
                use_container_width=True,
            )
        st.divider()
        st.subheader("Experimental optimizer — NSGA-II Pareto search")
        st.markdown(
            "The optimizer selects RO power at each interval from off / 6 / 8 / 10 kW. "
            "The source rule is renewable-surplus power first, then available off-peak grid power. "
            "**Hard feasibility requirements:** unmet water demand = 0, minimum run-time violations = 0, "
            "and tank overflow = 0. NSGA-II minimizes actual grid electricity cost and RO start count. "
            "Surplus energy is accounting-only and may be curtailed. Peak grid power remains observation-only."
        )
        st.caption("Runtime build: NSGA2-2OBJ-DIAG-v1 · This is a model-based optimization module using the selected input series; it is not a trained ML model or real-time controller.")
        p1, p2 = st.columns(2)
        with p1:
            pop_size = st.number_input("NSGA-II population size", min_value=120, max_value=300, value=120, step=20)
        with p2:
            generations = st.number_input("NSGA-II generations", min_value=60, max_value=300, value=60, step=10)
        optimizer_signature = strategy_run_signature(
            raw,
            source_label,
            {
                "strategy_input_signature": current_signature,
                "nsga2_population_size": int(pop_size),
                "nsga2_generations": int(generations),
            },
        )
        if st.button("Run NSGA-II Pareto optimization", type="primary", use_container_width=True):
            try:
                # Streamlit reruns the script on every button click. Rebuild the
                # inputs here instead of relying on local variables created by the
                # earlier "Run strategy comparison" click.
                optimizer_steps = parse_uploaded_csv(raw)
                optimizer_config = Config(
                    ro_rated_power_kw=float(ro_kw),
                    specific_energy_kwh_m3=float(sec),
                    tank_capacity_m3=float(tank),
                    initial_water_m3=float(initial),
                    min_run_hours=int(min_run),
                    dt_hours=float(dt),
                    diesel_cost_per_kwh=float(diesel_cost) if diesel_cost > 0 else None,
                )
                with st.spinner("Searching candidate schedules and filtering for zero unmet demand..."):
                    pareto_summaries, pareto_details, optimizer_meta = optimize_dispatch(
                        optimizer_steps, optimizer_config,
                        population_size=int(pop_size), generations=int(generations), seed=42
                    )
                st.session_state["islandos_optimizer_result"] = {
                    "summary": pareto_summaries, "detail": pareto_details,
                    "meta": optimizer_meta, "source": source_label,
                    "input_signature": optimizer_signature,
                }
            except Exception as exc:
                st.error(f"NSGA-II optimization failed: {exc}")
        optimizer_result = st.session_state.get("islandos_optimizer_result")
        if optimizer_result and optimizer_result.get("input_signature") != optimizer_signature:
            st.session_state.pop("islandos_optimizer_result", None)
            optimizer_result = None
        if optimizer_result:
            meta = optimizer_result["meta"]
            # Never present stale or incompatible session-state output as a successful
            # result. The current optimizer contract has exactly two objectives and
            # must count actual chromosome evaluations. Old Streamlit sessions can
            # survive code reloads, so validate stored metadata before plotting it.
            objective_count = meta.get("objective_count")
            evaluations = meta.get("evaluations")
            if objective_count != 2 or not isinstance(evaluations, (int, float)) or evaluations <= 0:
                st.error(
                    "Stale or incompatible NSGA-II result detected. Expected objective_count=2 "
                    "and evaluations > 0, but got "
                    f"objective_count={objective_count!r}, evaluations={evaluations!r}. "
                    "Please click Run strategy comparison, then run NSGA-II again. "
                    "If this message persists, the deployed app/optimizer code is out of sync."
                )
                st.stop()
            st.caption(f"Optimizer data provenance: **{optimizer_result['source']}**")
            st.write(meta.get("message", ""))
            st.write(
                f"Evaluations: {meta.get('evaluations', 0)} · "
                f"Feasible non-dominated schedules retained: {meta.get('feasible_count', 0)}"
            )
            st.caption(
                f"Objectives: {meta.get('objective_count', 2)} · "
                f"Unique feasible chromosomes: {meta.get('unique_feasible_count', 0)} · "
                f"Distinct objective vectors: {meta.get('distinct_objective_vectors', 0)}"
            )
            pareto_rows = optimizer_result["summary"]
            if pareto_rows:
                pareto_df = pd.DataFrame(pareto_rows)
                baseline_df = summaries.copy()
                # Existing heuristic summaries stay untouched; derive their
                # switch count from the hourly audit solely for the shared plot.
                heuristic_switches = {}
                for strategy_name, strategy_rows in details.groupby("strategy"):
                    on = strategy_rows["ro_power_kw"].fillna(0).astype(float).gt(0).tolist()
                    heuristic_switches[strategy_name] = sum(
                        1 for i, is_on in enumerate(on)
                        if is_on and (i == 0 or not on[i - 1])
                    )
                baseline_df["ro_switch_on_count"] = baseline_df["strategy"].map(heuristic_switches).fillna(0)
                baseline_df["series_type"] = "Existing fixed strategy"
                pareto_df["series_type"] = "NSGA-II Pareto candidate"
                plot_df = pd.concat([
                    baseline_df[["strategy", "grid_energy_cost", "ro_switch_on_count", "series_type"]],
                    pareto_df[["strategy", "grid_energy_cost", "ro_switch_on_count", "series_type"]],
                ], ignore_index=True)
                st.subheader("Pareto trade-off: grid cost vs. RO start count")
                st.scatter_chart(
                    plot_df, x="grid_energy_cost", y="ro_switch_on_count",
                    color="series_type",
                    x_label="Grid electricity cost",
                    y_label="RO switch-on count",
                    height=440,
                )
                st.caption("All five existing fixed strategies and feasible NSGA-II candidates are shown together. Fixed strategies are references and may be infeasible.")
                st.dataframe(pareto_df[[
                    "strategy", "ro_run_hours", "water_produced_m3", "water_served_m3",
                    "unmet_water_demand_m3", "grid_energy_cost", "surplus_energy_to_ro_kwh",
                    "grid_energy_to_ro_kwh", "grid_peak_power_kw", "ro_switch_on_count",
                    "water_spill_m3", "ending_water_inventory_m3",
                ]], use_container_width=True, hide_index=True)
                st.subheader("Automatic quantitative comparison: hybrid vs. fixed alternatives")
                hybrid = summaries.loc[summaries["strategy"] == "hybrid_surplus_then_off_peak"].iloc[0]
                def _delta_text(metric_label, metric_key, reference):
                    base_value = float(reference[metric_key])
                    hybrid_value = float(hybrid[metric_key])
                    difference = hybrid_value - base_value
                    if abs(base_value) > 1e-12:
                        pct_text = f" ({difference / abs(base_value) * 100:+.1f}%)"
                    else:
                        pct_text = " (percentage change undefined because reference is zero)"
                    return f"- {metric_label}: {hybrid_value:.2f} vs {base_value:.2f}; change {difference:+.2f}{pct_text}"
                for reference_name in ("surplus_only", "off_peak_only"):
                    reference = summaries.loc[summaries["strategy"] == reference_name].iloc[0]
                    st.markdown(f"**Hybrid vs. {reference_name}**")
                    st.markdown("\n".join([
                        _delta_text("RO run time (h)", "ro_run_hours", reference),
                        _delta_text("Water produced (m³)", "water_produced_m3", reference),
                        _delta_text("Grid electricity cost", "grid_energy_cost", reference),
                    ]))
                st.download_button(
                    "Download NSGA-II Pareto solutions",
                    dataframe_csv(pareto_rows),
                    file_name="islandos_nsga2_pareto_solutions.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                st.warning("No feasible schedule with exactly zero unmet demand was found in this search budget. No Pareto result is reported as feasible. Try more generations/population or review the input and model assumptions.")
        st.markdown(
            '<div class="note"><b>Interpretation:</b> results depend on input quality and '
            'simplified model assumptions. Validate timestamp intervals, essential-load priority, '
            'equipment constraints, full costs, and local operating rules before using results.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("Set assumptions above, then click **Run strategy comparison** to see results.")

elif page == "Rolling dispatch lab":
    st.title("Rolling-horizon energy–water dispatch lab")
    st.write(
        "Run a reproducible synthetic experiment that compares receding-horizon priority selection "
        "with fixed RO-first and cooling-first policies under renewable-forecast errors."
    )
    st.info(
        "This lab uses synthetic scenarios only. It demonstrates the dispatch algorithm and audit "
        "workflow; it does not establish real-island forecast skill or operational performance."
    )
    st.markdown(
        "**Experiment design:** 48 runs across the configured scenarios, four forecast-error profiles, "
        "and four policies. The report compares rolling dispatch against the best fixed-priority policy "
        "and checks whether conclusions change under three illustrative objective-weight profiles."
    )
    if st.button("▶ Run 48-case rolling-horizon experiment", type="primary", use_container_width=True):
        with st.spinner("Running scenario, forecast-error, and policy combinations..."):
            rolling_rows = run_rolling_dispatch_experiment()
            rolling_summaries = summarize_rolling_experiment(rolling_rows)
            rolling_aggregate = summarize_rolling_aggregate(rolling_summaries)
            rolling_sensitivity = summarize_rolling_weight_sensitivity(rolling_rows)
        st.session_state["islandos_rolling_result"] = {
            "rows": rolling_rows,
            "summary": rolling_summaries,
            "aggregate": rolling_aggregate,
            "weight_sensitivity": rolling_sensitivity,
        }

    rolling_result = st.session_state.get("islandos_rolling_result")
    if rolling_result:
        aggregate = rolling_result["aggregate"]
        st.subheader("Cross-case result")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Paired comparisons", str(aggregate["comparison_count"]))
        m2.metric("Rolling better", str(aggregate["rolling_better_count"]))
        m3.metric("Tied", str(aggregate["rolling_tied_count"]))
        m4.metric("Rolling worse", str(aggregate["rolling_worse_count"]))
        st.caption(
            f"Mean score delta: {aggregate['mean_score_delta']:+.4f}; "
            f"median delta: {aggregate['median_score_delta']:+.4f}. "
            "Negative delta favors rolling dispatch. No universal winner is assumed."
        )
        summary_df = pd.DataFrame(rolling_result["summary"])
        st.subheader("Rolling vs. best fixed-priority policy")
        st.dataframe(summary_df, use_container_width=True, hide_index=True)
        chart_df = summary_df.copy()
        chart_df["case"] = chart_df["scenario"] + " / " + chart_df["forecast_error_profile"]
        st.bar_chart(chart_df.set_index("case")[["rolling_minus_best_fixed"]])

        st.subheader("Objective-weight sensitivity")
        sensitivity_df = pd.DataFrame(rolling_result["weight_sensitivity"])
        st.dataframe(sensitivity_df, use_container_width=True, hide_index=True)
        st.caption(
            "Weights are illustrative, not stakeholder-validated. Sensitivity counts expose how often "
            "the rolling policy beats, ties, or loses to the best fixed policy under each weighting."
        )

        all_rows = rolling_result["rows"]
        scenario_names = sorted({row["scenario"] for row in all_rows})
        error_names = sorted({row["forecast_error_profile"] for row in all_rows})
        policy_names = ["rolling", "ro_first", "ice_first", "perfect_information"]
        s1, s2, s3 = st.columns(3)
        selected_scenario = s1.selectbox("Scenario", scenario_names, key="rolling_lab_scenario")
        selected_error = s2.selectbox("Forecast-error profile", error_names, key="rolling_lab_error")
        selected_policy = s3.selectbox("Policy to audit", policy_names, key="rolling_lab_policy")
        selected = next(
            row for row in all_rows
            if row["scenario"] == selected_scenario
            and row["forecast_error_profile"] == selected_error
            and row["result"]["policy"] == selected_policy
        )
        audit_df = pd.DataFrame(selected["result"]["hourly_audit"])
        st.subheader("Hourly operating audit")
        st.line_chart(
            audit_df.set_index("hour_index")[["actual_surplus_kw", "forecast_surplus_kw"]]
        )
        st.line_chart(
            audit_df.set_index("hour_index")[["water_inventory_m3", "cold_inventory_kwh_th"]]
        )
        st.dataframe(audit_df, use_container_width=True, hide_index=True)
        download_a, download_b, download_c = st.columns(3)
        with download_a:
            st.download_button(
                "Download comparison CSV",
                dataframe_csv(rolling_result["summary"]),
                file_name="islandos_rolling_comparison.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with download_b:
            st.download_button(
                "Download hourly audit CSV",
                dataframe_csv(selected["result"]["hourly_audit"]),
                file_name="islandos_rolling_hourly_audit.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with download_c:
            report_payload = {
                "data_status": "synthetic prototype; not field-validated",
                "aggregate_summary": aggregate,
                "summary": rolling_result["summary"],
                "weight_sensitivity": rolling_result["weight_sensitivity"],
                "rows": all_rows,
            }
            st.download_button(
                "Download full JSON evidence",
                json.dumps(report_payload, indent=2).encode("utf-8"),
                file_name="islandos_rolling_horizon_evidence.json",
                mime="application/json",
                use_container_width=True,
            )
    else:
        st.info("Click Run 48-case rolling-horizon experiment to generate comparisons and hourly audit evidence.")

elif page == "Custom dispatch CSV":
    st.title("Run rolling dispatch on your own hourly data")
    st.write(
        "Upload aligned renewable-surplus forecasts, realized surplus, water demand, and cooling demand. "
        "The app will compare four policies and expose the hourly audit for each."
    )
    st.markdown(
        "**Required columns:** `timestamp_utc`, `actual_surplus_kw`, `forecast_surplus_kw`, "
        "`water_demand_m3`, and `cooling_demand_kw_th`. Optional: `forecast_water_demand_m3` "
        "for planning demand separate from realized demand. Timestamps must be ISO-8601 with a timezone, "
        "strictly increasing after UTC normalization. Numeric values must be finite and non-negative."
    )
    st.caption(
        "The actual series is used for hourly execution and evaluation; forecasts are planning inputs. "
        "This is a research simulation, not a live controller or a site-safety assessment."
    )
    st.download_button(
        "Download 24-hour synthetic CSV template",
        data=generate_rolling_dispatch_template().encode("utf-8"),
        file_name="islandos_rolling_dispatch_template.csv",
        mime="text/csv",
        use_container_width=True,
    )
    custom_upload = st.file_uploader(
        "Upload paired hourly CSV", type=["csv"], key="custom_rolling_csv"
    )
    if custom_upload is None:
        st.info("Upload a CSV with the required columns to begin.")
    else:
        custom_raw = custom_upload.getvalue()
        custom_signature = strategy_run_signature(
            custom_raw, custom_upload.name, {"mode": "custom_rolling_dispatch"}
        )
        custom_result = st.session_state.get("islandos_custom_rolling_result")
        if custom_result and custom_result.get("input_signature") != custom_signature:
            st.session_state.pop("islandos_custom_rolling_result", None)
            custom_result = None
            st.warning("The uploaded file changed. Previous results were cleared; run the comparison again.")
        try:
            parsed_custom = parse_rolling_scenario_csv(
                custom_raw.decode("utf-8-sig"), name=Path(custom_upload.name).stem
            )
        except (UnicodeDecodeError, ValueError) as exc:
            st.error(f"CSV validation failed: {exc}")
            parsed_custom = None

        if parsed_custom and st.button(
            "▶ Compare rolling and fixed policies", type="primary", use_container_width=True
        ):
            with st.spinner("Simulating four policies with state carried between hours..."):
                policy_results = []
                for policy_name in ("rolling", "ro_first", "ice_first", "perfect_information"):
                    result = simulate_rolling_dispatch(
                        parsed_custom["scenario"],
                        parsed_custom["forecast_surplus_kw"],
                        policy_name,
                        forecast_water_demand_m3_per_hour=parsed_custom[
                            "forecast_water_demand_m3_per_hour"
                        ],
                    )
                    policy_results.append({"policy": policy_name, "result": result})
            st.session_state["islandos_custom_rolling_result"] = {
                "input_signature": custom_signature,
                "source": custom_upload.name,
                "timestamps_utc": parsed_custom["timestamps_utc"],
                "rows": policy_results,
            }
            custom_result = st.session_state["islandos_custom_rolling_result"]

        if custom_result:
            st.caption(f"Input provenance: **{custom_result['source']}** · {len(custom_result['timestamps_utc'])} hourly rows")
            comparison_rows = []
            for item in custom_result["rows"]:
                result = item["result"]
                comparison_rows.append({
                    "policy": item["policy"],
                    "water_produced_m3": round(sum(row["water_produced_m3"] for row in result["hourly_audit"]), 3),
                    "water_served_m3": round(sum(row["water_served_m3"] for row in result["hourly_audit"]), 3),
                    "water_unmet_m3": result["water_unmet_m3"],
                    "cooling_produced_kwh_th": round(sum(row["cooling_produced_kwh_th"] for row in result["hourly_audit"]), 3),
                    "cooling_served_kwh_th": round(sum(row["cooling_served_kwh_th"] for row in result["hourly_audit"]), 3),
                    "cooling_unmet_kwh_th": result["cooling_unmet_kwh_th"],
                    "renewable_flexible_load_kwh": result["renewable_flexible_load_kwh"],
                    "remaining_surplus_kwh": result["remaining_surplus_kwh"],
                    "constraint_violation_hours": result["constraint_violation_hours"],
                    "final_water_inventory_m3": result["final_water_inventory_m3"],
                    "final_cold_inventory_kwh_th": result["final_cold_inventory_kwh_th"],
                })
            comparison_df = pd.DataFrame(comparison_rows)
            st.subheader("Policy comparison")
            st.dataframe(comparison_df, use_container_width=True, hide_index=True)
            st.caption(
                "Perfect-information is a hindsight reference, not a deployable policy. Lower unmet demand "
                "and fewer constraint violations matter; remaining surplus alone is not a complete value metric."
            )
            policy_choice = st.selectbox(
                "Policy to inspect",
                [item["policy"] for item in custom_result["rows"]],
                key="custom_rolling_policy",
            )
            chosen_item = next(item for item in custom_result["rows"] if item["policy"] == policy_choice)
            audit_df = pd.DataFrame(chosen_item["result"]["hourly_audit"])
            audit_df["timestamp_utc"] = list(custom_result["timestamps_utc"])
            st.subheader("Hourly operating audit")
            st.line_chart(audit_df.set_index("hour_index")[["actual_surplus_kw", "forecast_surplus_kw"]])
            st.line_chart(audit_df.set_index("hour_index")[["water_inventory_m3"]])
            st.line_chart(audit_df.set_index("hour_index")[["cold_inventory_kwh_th"]])
            st.dataframe(audit_df, use_container_width=True, hide_index=True)
            d1, d2, d3 = st.columns(3)
            with d1:
                st.download_button(
                    "Download policy comparison", dataframe_csv(comparison_rows),
                    file_name="islandos_custom_dispatch_comparison.csv", mime="text/csv",
                    use_container_width=True,
                )
            with d2:
                st.download_button(
                    "Download hourly audit", dataframe_csv(audit_df.to_dict(orient="records")),
                    file_name="islandos_custom_dispatch_audit.csv", mime="text/csv",
                    use_container_width=True,
                )
            with d3:
                payload = {
                    "data_status": "user-supplied input; not field-validated by islandOS",
                    "source": custom_result["source"],
                    "comparison": comparison_rows,
                    "policy_results": custom_result["rows"],
                }
                st.download_button(
                    "Download full JSON evidence", json.dumps(payload, indent=2).encode("utf-8"),
                    file_name="islandos_custom_dispatch_evidence.json", mime="application/json",
                    use_container_width=True,
                )

else:
    st.title("Data guide")
    st.write("The uploaded CSV must contain one row per time step, with strictly increasing timestamps.")
    st.markdown("**Required columns**")
    st.dataframe(pd.DataFrame({
        "Column": list(REQUIRED_COLUMNS),
        "Meaning": [
            "Timestamp text, strictly increasing",
            "Renewable surplus available for flexible loads (kW)",
            "Potential direct diesel displacement (kW), tracked separately",
            "Site electricity price (currency/kWh)",
            "Whether the interval is off-peak (true/false or 1/0)",
            "Whether grid electricity is available (true/false or 1/0)",
            "Water demand during the interval (m³)",
        ],
    }), use_container_width=True, hide_index=True)
    st.markdown(
        """
        **Optional column**
        - backup_available_kw: available backup-generation capacity for RO operation in that interval.
          If omitted or blank, it defaults to zero.

        **Input rules**
        - Numeric values must be finite and non-negative.
        - Timestamp values must be non-empty and strictly increasing.
        - Boolean columns accept true/false, yes/no, or 1/0.
        - No synthetic values are silently added to uploaded data.
        - Ensure every row represents the interval specified in the simulator settings.

        **What is not included**
        - No real-time control, equipment communication, forecasting integration, or automatic safety interlocks.
        - No complete lifecycle cost, water-quality compliance, pump/start-up constraints beyond the model's minimum run time, or tariff interpretation.
        - No claim that a site's renewable surplus is available until essential demand and reserve needs have been accounted for.
        """
    )
    st.download_button(
        "⬇ Download CSV template",
        data=csv_template_bytes(),
        file_name="islandos_site_data_template.csv",
        mime="text/csv",
    )
