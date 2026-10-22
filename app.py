from __future__ import annotations

"""islandOS interactive energy-water strategy screening app.

This is a planning/simulation interface, not a live microgrid controller.
Uploaded site data is used as supplied; the built-in demo is synthetic.
"""

import csv
import io
import math
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

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
        ["Overview", "Strategy simulator", "Data guide"],
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
            "**AI Optimizer — NSGA-II multi-objective Pareto search**\n\n"
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
            }
            st.session_state.pop("islandos_optimizer_result", None)
        except Exception as exc:
            st.error(f"Could not run the comparison: {exc}")
            st.stop()

    result = st.session_state.get("islandos_result")
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
        st.subheader("AI Optimizer (Next Version) — NSGA-II Pareto search")
        st.markdown(
            "The optimizer searches hourly RO on/off schedules. The source rule is renewable-surplus "
            "power first, then available off-peak grid power. **Hard feasibility requirements:** "
            "total unmet water demand = 0 and minimum run-time violations = 0. Among feasible schedules, "
            "NSGA-II minimizes grid electricity cost and maximizes renewable-surplus energy used by RO."
        )
        st.caption("This is a model-based optimization module using the selected input series; it is not a trained ML model or real-time controller.")
        p1, p2 = st.columns(2)
        with p1:
            pop_size = st.number_input("NSGA-II population size", min_value=20, max_value=200, value=64, step=8)
        with p2:
            generations = st.number_input("NSGA-II generations", min_value=10, max_value=200, value=80, step=10)
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
                }
            except Exception as exc:
                st.error(f"NSGA-II optimization failed: {exc}")
        optimizer_result = st.session_state.get("islandos_optimizer_result")
        if optimizer_result:
            meta = optimizer_result["meta"]
            st.caption(f"Optimizer data provenance: **{optimizer_result['source']}**")
            st.write(meta.get("message", ""))
            st.write(
                f"Evaluations: {meta.get('evaluations', 0)} · "
                f"Feasible non-dominated schedules retained: {meta.get('feasible_count', 0)}"
            )
            st.caption(
                f"Objectives: {meta.get('objective_count', 4)} · "
                f"Unique feasible chromosomes: {meta.get('unique_feasible_count', 0)} · "
                f"Distinct objective vectors: {meta.get('distinct_objective_vectors', 0)}"
            )
            pareto_rows = optimizer_result["summary"]
            if pareto_rows:
                pareto_df = pd.DataFrame(pareto_rows)
                baseline_df = summaries.copy()
                baseline_df["series_type"] = "Existing fixed strategy"
                pareto_df["series_type"] = "NSGA-II Pareto candidate"
                plot_df = pd.concat([
                    baseline_df[["strategy", "grid_energy_cost", "surplus_energy_to_ro_kwh", "series_type"]],
                    pareto_df[["strategy", "grid_energy_cost", "surplus_energy_to_ro_kwh", "series_type"]],
                ], ignore_index=True)
                st.subheader("Pareto trade-off: grid cost vs. renewable-surplus energy used")
                st.scatter_chart(
                    plot_df, x="grid_energy_cost", y="surplus_energy_to_ro_kwh",
                    color="series_type",
                    x_label="Grid electricity cost (model units)",
                    y_label="Renewable-surplus energy used by RO (kWh)",
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
