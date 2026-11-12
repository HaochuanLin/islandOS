from __future__ import annotations

"""IslandOS interactive, simulation-first decision-support prototype.

The hosted interface currently exposes a bounded energy–water screening module; it does not yet implement the complete four-step IslandOS workflow.
This is a planning/simulation interface, not a live microgrid controller.
Uploaded site data is used as supplied; the built-in demo is synthetic.
"""

import csv
import hashlib
import io
import json
import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from experiments.compare_energy_water_strategies import REQUIRED_COLUMNS, Config
from experiments.nsga2_dispatch_optimizer import optimize_dispatch
from optimization.price_aware_load_optimizer import optimize_flexible_load

from islandos_core import SiteConfiguration, recommend_ro_screening
from islandos_core.microgrid_model import MicrogridConfig, MicrogridInputs
from islandos_core.schedule_evaluator import (
    screen_renewable_surplus_candidates, evaluate_schedule_robustness,
    search_ro_schedule,
)
from islandos_core.scenario_forecasting import (
    forecast_microgrid_signals, generate_synthetic_microgrid_history,
    rolling_origin_evaluate,
)
from islandos_core.app_workflow import (
    dataframe_csv,
    parse_uploaded_csv,
    run_uploaded_strategy_comparison,
)
from islandos_core.simulation_adapter import simulation_row_to_screening_signals
from islandos_core.virtual_instrument import make_virtual_reading
from ro_costing import ROCostRates, calculate_ro_operating_cost
from ro_historical_baseline import reconstruct_historical_ro_cost

# Keep the app shell product-generic while clearly labelling the current energy–water module.
st.set_page_config(
    page_title="IslandOS | Decision Lab",
    page_icon="⚡",
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


def stable_signature(payload: dict) -> str:
    """Return a deterministic signature for the exact run inputs and settings."""
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


with st.sidebar:
    st.markdown("## ⚡ IslandOS")
    st.caption("Energy & resource decision support")
    page = st.radio(
        "Navigate",
        ["Overview", "Flexible-load cost optimizer", "Strategy simulator", "Microgrid screening", "Historical RO baseline", "Data guide"],
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
          <h1>From energy data to intelligent decisions.</h1>
          <p>Organize system inputs, examine future conditions, compare feasible alternatives,
          and review explainable recommendations.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info(
        "This public research prototype currently exposes an energy–water screening module. "
        "The broader IslandOS product workflow is INPUT → PREDICT → OPTIMIZE → DECIDE; "
        "the hosted app does not yet implement that complete end-to-end workflow. "
        "The built-in demo is synthetic, not measured site data."
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Strategy policies", "5", help="Baseline plus four RO operating policies")
    c2.metric("Input format", "Hourly CSV", help="Timestamped, aligned site time series")
    c3.metric("Output", "CSV + charts", help="Summary metrics and timestep-level audit")
    st.subheader("Current module: energy–water strategy screening")
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
    st.subheader("What the current module helps you compare")
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
    st.subheader("Example decision support: read-only RO screening")
    st.caption(
        "Manual/virtual inputs only. This isolated heuristic preview does not read plant instruments, "
        "change the strategy simulator, or send equipment commands."
    )
    with st.expander("Try an explainable screening recommendation", expanded=False):
        p1, p2, p3 = st.columns(3)
        with p1:
            preview_demand = st.number_input(
                "Daily water demand (m³/day)", min_value=0.1, value=30.0, step=1.0,
                key="preview_demand",
            )
            preview_ro_capacity = st.number_input(
                "RO capacity (m³/day)", min_value=0.1, value=60.0, step=1.0,
                key="preview_ro_capacity",
            )
        with p2:
            preview_sec = st.number_input(
                "RO specific energy (kWh/m³)", min_value=0.1, value=4.0, step=0.1,
                key="preview_sec",
            )
            preview_tank = st.number_input(
                "Storage capacity (m³)", min_value=0.1, value=50.0, step=1.0,
                key="preview_tank",
            )
        with p3:
            preview_inventory = st.number_input(
                "Current water inventory (m³)", min_value=0.0, value=10.0, step=1.0,
                key="preview_inventory",
            )
            preview_surplus = st.number_input(
                "Renewable surplus (kW)", min_value=0.0, value=12.0, step=0.5,
                key="preview_surplus",
            )
        preview_price = st.number_input(
            "Energy price (currency/kWh; recorded as an assumption)",
            min_value=0.0, value=0.20, step=0.01, key="preview_price",
        )
        if preview_inventory > preview_tank:
            st.error("Current water inventory cannot exceed storage capacity.")
        else:
            preview_config = SiteConfiguration(
                site_id="manual-screening-preview",
                water_demand_m3_per_day=preview_demand,
                ro_capacity_m3_per_day=preview_ro_capacity,
                energy_price_per_kwh=preview_price,
                ro_specific_energy_kwh_per_m3=preview_sec,
                storage_capacity_m3=preview_tank,
                initial_storage_m3=min(preview_inventory, preview_tank),
            )
            preview = recommend_ro_screening(
                preview_config,
                renewable_surplus=make_virtual_reading(
                    "renewable_surplus_kw", preview_surplus, "kW",
                    source="manual-demo-input",
                ),
                water_inventory=make_virtual_reading(
                    "water_inventory_m3", preview_inventory, "m3",
                    source="manual-demo-input",
                ),
            )
            st.markdown(f"**Screening outcome:** `{preview.action}`")
            st.write(preview.reason)
            m1, m2, m3 = st.columns(3)
            m1.metric("Estimated full-load power", f"{preview.estimated_full_load_power_kw:.2f} kW")
            m2.metric("Inventory screening target", f"{preview.target_inventory_m3:.2f} m³")
            m3.metric("Input renewable surplus", f"{preview.renewable_surplus_kw:.2f} kW")
            with st.expander("Assumptions and limits"):
                for assumption in preview.assumptions:
                    st.write(f"- {assumption}")
                st.write(
                    "The energy-price field is captured as a site assumption but is not used by this "
                    "surplus-only heuristic. The recommendation is not an optimizer or operating instruction."
                )

    st.subheader("Try the current screening module")
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

elif page == "Flexible-load cost optimizer":
    st.title("Flexible-load cost optimizer")
    st.write(
        "Compare a fixed operating profile with a lower-cost schedule while "
        "delivering exactly the same electrical energy."
    )
    st.info(
        "Experimental decision-support module. The default profile is synthetic. "
        "It does not control equipment, forecast prices, or verify site savings."
    )

    currency = st.text_input(
        "Currency label (used only for display)", value="currency",
        help="Enter a label such as USD, EUR, or your local currency. This does not convert prices.",
    ).strip() or "currency"
    max_power = st.number_input(
        "Equipment maximum power (kW)", min_value=0.1, value=2.0, step=0.1,
        help="Nameplate upper bound for the flexible load.",
    )
    dt_hours = st.number_input(
        "Interval duration (hours)", min_value=0.05, value=1.0, step=0.25,
        help="All energy and cost calculations use this interval duration.",
    )

    hours = list(range(24))
    prices = [
        0.12 if hour < 6 else
        0.20 if hour < 16 else
        0.32 if hour < 21 else
        0.18
        for hour in hours
    ]
    default_profile = pd.DataFrame({
        "Interval": [f"{hour:02d}:00" for hour in hours],
        "Price (currency/kWh)": prices,
        "Available power budget (kW)": [1.5] * 24,
        "Baseline power (kW)": [0.5] * 24,
    })
    st.markdown("### Scenario inputs")
    st.caption(
        "Edit the tariff, available power budget, and baseline profile below. "
        "The baseline determines the required total energy, so the comparison "
        "keeps service quantity equal."
    )
    profile = st.data_editor(
        default_profile,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=["Interval"],
        column_config={
            "Price (currency/kWh)": st.column_config.NumberColumn(
                min_value=-1000000.0, max_value=1000000.0, step=0.01, format="%.3f"
            ),
            "Available power budget (kW)": st.column_config.NumberColumn(
                min_value=0.0, max_value=1000000.0, step=0.1, format="%.2f"
            ),
            "Baseline power (kW)": st.column_config.NumberColumn(
                min_value=0.0, max_value=1000000.0, step=0.1, format="%.2f"
            ),
        },
        key="price_aware_profile_editor",
    )

    try:
        price_values = [float(value) for value in profile["Price (currency/kWh)"]]
        budget_values = [float(value) for value in profile["Available power budget (kW)"]]
        baseline_values = [float(value) for value in profile["Baseline power (kW)"]]
        if not all(math.isfinite(value) for value in price_values):
            raise ValueError("Tariff values must be finite.")
        if not all(math.isfinite(value) and value >= 0 for value in budget_values):
            raise ValueError("Available power budgets must be finite and non-negative.")
        if not all(math.isfinite(value) and value >= 0 for value in baseline_values):
            raise ValueError("Baseline power values must be finite and non-negative.")

        required_energy = sum(baseline_values) * float(dt_hours)
        if required_energy <= 0:
            raise ValueError("The baseline must contain a positive energy requirement.")
        result = optimize_flexible_load(
            price_per_kwh=price_values,
            energy_requirement_kwh=required_energy,
            max_power_kw=float(max_power),
            available_power_kw=budget_values,
            baseline_power_kw=baseline_values,
            dt_hours=float(dt_hours),
        )
        st.markdown("### Cost comparison")
        first, second, third = st.columns(3)
        first.metric("Baseline cost", f"{currency} {result.baseline_cost:,.3f}")
        second.metric("Optimized cost", f"{currency} {result.total_cost:,.3f}")
        difference = result.cost_difference_vs_baseline
        third.metric(
            "Cost difference",
            f"{currency} {difference:,.3f}",
            delta=(
                f"{result.cost_difference_percent_vs_baseline:.1f}%"
                if result.cost_difference_percent_vs_baseline is not None
                else "Percentage unavailable"
            ),
            delta_color="normal",
        )
        st.caption(
            f"Equal service: {result.total_energy_kwh:,.3f} kWh delivered over "
            f"{len(profile)} intervals. Positive cost difference means the optimized "
            "schedule costs less; a negative value means it costs more."
        )
        if difference > 1e-8:
            st.success("Under the supplied assumptions, the optimized schedule has a lower energy charge.")
        elif difference < -1e-8:
            st.warning("Under the supplied assumptions, the optimized schedule costs more than the baseline.")
        else:
            st.info("The optimized schedule has the same energy charge as the baseline.")

        schedule_frame = pd.DataFrame({
            "Interval": profile["Interval"],
            "Tariff": price_values,
            "Available power budget (kW)": budget_values,
            "Baseline power (kW)": baseline_values,
            "Optimized power (kW)": list(result.power_kw),
            "Optimized energy (kWh)": list(result.energy_kwh),
        })
        st.markdown("### Operating schedule")
        st.line_chart(
            schedule_frame.set_index("Interval")[
                ["Baseline power (kW)", "Optimized power (kW)"]
            ]
        )
        st.dataframe(schedule_frame, use_container_width=True, hide_index=True)
        export = schedule_frame.copy()
        export["data_provenance"] = (
            "User-edited scenario assumptions; not independently verified site data"
        )
        export["currency_label"] = currency
        export["baseline_cost"] = result.baseline_cost
        export["optimized_cost"] = result.total_cost
        export["cost_difference_vs_baseline"] = result.cost_difference_vs_baseline
        st.download_button(
            "Download schedule and cost comparison (CSV)",
            data=export.to_csv(index=False).encode("utf-8-sig"),
            file_name="islandos_flexible_load_cost_comparison.csv",
            mime="text/csv",
            use_container_width=True,
        )
        with st.expander("Model assumptions and limitations"):
            st.write(
                "- The baseline and optimized schedules deliver the same total electrical energy.\n"
                "- The optimizer shifts a continuous, deferrable load across the supplied intervals.\n"
                "- The available power budget is a hard per-interval limit after essential demand and higher-priority reservations.\n"
                "- The model does not include demand charges, taxes, fixed fees, startup costs, minimum run times, ramp rates, process dynamics, or network constraints.\n"
                "- The tariff is treated as supplied; no tariff interpretation or currency conversion is performed.\n"
                "- A lower modeled energy charge is not proof of realizable customer savings or plant feasibility."
            )
    except (ValueError, TypeError, KeyError) as exc:
        st.error(f"Cannot calculate this scenario: {exc}")

elif page == "Strategy simulator":
    st.title("Current module: energy–water strategy simulator")
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
        source_type = "user_uploaded_unverified"
    else:
        raw = demo_csv_bytes()
        source_label = "Synthetic demo data — not measured site data"
        source_type = "synthetic"
    input_provenance = {
        "source_type": source_type,
        "source_label": source_label,
        "input_sha256": hashlib.sha256(raw).hexdigest(),
    }

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

    simulation_signature = stable_signature({
        "input_sha256": input_provenance["input_sha256"],
        "ro_rated_power_kw": float(ro_kw),
        "specific_energy_kwh_m3": float(sec),
        "tank_capacity_m3": float(tank),
        "initial_water_m3": float(initial),
        "min_run_hours": int(min_run),
        "dt_hours": float(dt),
        "diesel_cost_per_kwh": float(diesel_cost) if diesel_cost > 0 else None,
    })
    export_provenance = {
        **input_provenance,
        "run_signature": simulation_signature,
        "ro_rated_power_kw": float(ro_kw),
        "specific_energy_kwh_m3": float(sec),
        "tank_capacity_m3": float(tank),
        "initial_water_m3": float(initial),
        "min_run_hours": int(min_run),
        "input_interval_hours": float(dt),
        "backup_energy_cost_per_kwh": float(diesel_cost) if diesel_cost > 0 else None,
    }

    if st.button("▶ Run strategy comparison", type="primary", use_container_width=True):
        try:
            config = Config(
                ro_rated_power_kw=float(ro_kw),
                specific_energy_kwh_m3=float(sec),
                tank_capacity_m3=float(tank),
                initial_water_m3=float(initial),
                min_run_hours=int(min_run),
                dt_hours=float(dt),
                diesel_cost_per_kwh=float(diesel_cost) if diesel_cost > 0 else None,
            )
            steps, detail, summary = run_uploaded_strategy_comparison(raw, config)
            st.session_state["islandos_result"] = {
                "detail": detail,
                "summary": summary,
                "source": source_label,
                "provenance": export_provenance,
                "run_signature": simulation_signature,
            }
            st.session_state.pop("islandos_optimizer_result", None)
        except Exception as exc:
            st.error(f"Could not run the comparison: {exc}")
            st.stop()

    result = st.session_state.get("islandos_result")
    if result and result.get("run_signature") != simulation_signature:
        # Input data and model settings are part of the result identity. Clear
        # old output rather than leaving a visually plausible but stale report.
        st.session_state.pop("islandos_result", None)
        st.session_state.pop("islandos_optimizer_result", None)
        result = None
        st.info("Previous results were cleared because input data or model assumptions changed. Run the comparison again.")
    if result:
        st.caption(f"Data provenance: **{result['source']}**")
        st.caption(
            f"Source type: `{result['provenance']['source_type']}` · "
            f"Input SHA-256: `{result['provenance']['input_sha256']}`"
        )
        st.caption(f"Run signature: `{result['provenance']['run_signature']}`")
        with st.expander("Input provenance details", expanded=False):
            st.write(
                "The digest identifies the exact input bytes used for this run. "
                "It does not certify measurement accuracy, completeness, licensing, or trust."
            )
            st.code(result["provenance"]["input_sha256"], language=None)
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

        st.subheader("RO operating-cost estimate")
        st.caption(
            "Uses the selected strategy's simulated production and grid-supplied RO energy. "
            "Renewable-energy opportunity cost and backup-fuel cost are excluded from this first-pass estimate; "
            "enter customer-confirmed non-electric rates. This is not a measured bill."
        )
        with st.expander("Enter site operating-cost assumptions", expanded=False):
            cost_a, cost_b, cost_c = st.columns(3)
            with cost_a:
                cost_currency = st.text_input("Currency label", value="CNY", key="cost_currency")
                chemical_rate = st.number_input(
                    "Chemical cost (currency/m³)", min_value=0.0, value=0.0, step=0.01,
                    key="cost_chemical_rate",
                )
            with cost_b:
                variable_om_rate = st.number_input(
                    "Variable O&M (currency/m³)", min_value=0.0, value=0.0, step=0.01,
                    key="cost_variable_om_rate",
                )
                maintenance_rate = st.number_input(
                    "Maintenance (currency/runtime hour)", min_value=0.0, value=0.0, step=0.1,
                    key="cost_maintenance_rate",
                )
            with cost_c:
                start_cost = st.number_input(
                    "Cost per start event (currency)", min_value=0.0, value=0.0, step=0.1,
                    key="cost_start_event",
                )
                fixed_om = st.number_input(
                    "Annual fixed O&M (currency/year)", min_value=0.0, value=0.0, step=100.0,
                    key="cost_fixed_om",
                )
            fixed_hours = st.number_input(
                "Annual fixed-O&M allocation hours", min_value=1.0, value=8760.0, step=24.0,
                key="cost_fixed_hours",
            )
        try:
            rates = ROCostRates(
                currency=cost_currency,
                electricity_price_per_kwh=0.0,
                chemical_cost_per_m3=float(chemical_rate),
                variable_om_cost_per_m3=float(variable_om_rate),
                maintenance_cost_per_runtime_hour=float(maintenance_rate),
                start_stop_cost_per_event=float(start_cost),
                fixed_om_per_year=float(fixed_om),
                fixed_om_allocation_hours=float(fixed_hours),
            )
            cost_rows = []
            for strategy_name, strategy_detail in details.groupby("strategy", sort=False):
                strategy_detail = strategy_detail.reset_index(drop=True)
                on = strategy_detail["ro_power_kw"].astype(float).gt(0).tolist()
                starts = [
                    1 if active and (index == 0 or not on[index - 1]) else 0
                    for index, active in enumerate(on)
                ]
                grid_energy = [
                    float(row.ro_energy_kwh) if row.ro_source == "grid" else 0.0
                    for row in strategy_detail.itertuples()
                ]
                report = calculate_ro_operating_cost(
                    energy_kwh=grid_energy,
                    water_m3=strategy_detail["water_produced_m3"].astype(float).tolist(),
                    electricity_price_per_kwh=strategy_detail["grid_price_per_kwh"].astype(float).tolist(),
                    rates=rates,
                    runtime_hours=[
                        float(active) * float(dt) for active in on
                    ],
                    start_events=starts,
                    provenance=source_type,
                    dt_hours=float(dt),
                )
                cost_rows.append({
                    "strategy": strategy_name,
                    "currency": report.currency,
                    "grid_electricity_cost": report.electricity_cost,
                    "chemical_cost": report.chemical_cost,
                    "variable_om_cost": report.variable_om_cost,
                    "maintenance_cost": report.maintenance_cost,
                    "start_stop_cost": report.start_stop_cost,
                    "allocated_fixed_om": report.allocated_fixed_om_cost,
                    "estimated_total_cost": report.total_operating_cost,
                    "water_produced_m3": report.water_m3,
                    "estimated_cost_per_m3": report.cost_per_m3,
                    "provenance": report.provenance,
                })
            cost_frame = pd.DataFrame(cost_rows)
            st.dataframe(cost_frame, use_container_width=True, hide_index=True)
            st.download_button(
                "Download operating-cost comparison (CSV)",
                data=cost_frame.to_csv(index=False).encode("utf-8-sig"),
                file_name="islandos_ro_operating_cost_comparison.csv",
                mime="text/csv",
                help="Exports the displayed estimates and provenance. Review the exclusions below before using it for a purchase or operating decision.",
            )
            st.caption(
                "Cost estimate excludes renewable-energy opportunity cost, backup energy/fuel, "
                "demand charges, taxes, water-quality penalties and any unentered cost items. "
                "Zero-valued assumptions mean 'not entered', not proof that the cost is zero. "
                "Do not interpret the ranking as a validated saving until all material cost items "
                "and equivalent service constraints are confirmed."
            )
        except (ValueError, TypeError) as exc:
            st.error(f"Could not calculate operating costs: {exc}")
        st.subheader("Water outcomes by strategy")
        chart_df = summaries.set_index("strategy")[[
            "water_produced_m3", "water_served_m3", "unmet_water_demand_m3"
        ]]
        st.bar_chart(chart_df)
        st.subheader("Screen a simulated timestep")
        st.caption(
            "Uses one selected row from the current simulation result as virtual input. "
            "It is an offline explanation layer, not a live measurement or an instruction to operate equipment."
        )
        screen_strategy = st.selectbox(
            "Strategy row to inspect",
            summaries["strategy"].tolist(),
            index=3,
            key="screen_strategy",
        )
        strategy_rows = details[details["strategy"] == screen_strategy].copy()
        if not strategy_rows.empty:
            screen_timestamp = st.selectbox(
                "Timestep",
                strategy_rows["timestamp"].tolist(),
                key="screen_timestamp",
            )
            screen_row = strategy_rows.loc[
                strategy_rows["timestamp"] == screen_timestamp
            ].iloc[0]
            # Parse once; this estimate is derived from the selected offline input series.
            input_steps = parse_uploaded_csv(raw)
            estimated_daily_demand = (
                sum(step.water_demand_m3 for step in input_steps)
                / max(1e-9, len(input_steps) * float(dt))
                * 24.0
            )
            screen_demand = st.number_input(
                "Assumed daily water demand for screening (m³/day)",
                min_value=0.1,
                value=max(0.1, float(estimated_daily_demand)),
                step=1.0,
                key="screen_daily_demand",
                help="Annualized from the selected input series' average interval demand; edit to override.",
            )
            screen_config = SiteConfiguration(
                site_id="simulation-row-screening",
                water_demand_m3_per_day=screen_demand,
                ro_capacity_m3_per_day=24.0 * float(ro_kw) / float(sec),
                energy_price_per_kwh=float(screen_row["grid_price_per_kwh"]),
                ro_specific_energy_kwh_per_m3=float(sec),
                storage_capacity_m3=float(tank),
                initial_storage_m3=float(screen_row["water_inventory_before_m3"]),
            )
            # Simulation timestamps in the built-in CSV are timezone-naive. For this
            # offline demo only, explicitly interpret naive timestamps as UTC.
            screen_timestamp_text = str(screen_row["timestamp"])
            parsed_screen_timestamp = datetime.fromisoformat(
                screen_timestamp_text.replace("Z", "+00:00")
            )
            if parsed_screen_timestamp.tzinfo is None:
                parsed_screen_timestamp = parsed_screen_timestamp.replace(tzinfo=timezone.utc)
            virtual_signals = simulation_row_to_screening_signals({
                "timestamp": parsed_screen_timestamp.isoformat(),
                "renewable_surplus_available_kw": screen_row["renewable_surplus_available_kw"],
                "water_inventory_before_m3": screen_row["water_inventory_before_m3"],
            })
            screen_result = recommend_ro_screening(
                screen_config,
                renewable_surplus=virtual_signals[0],
                water_inventory=virtual_signals[1],
            )
            st.markdown(f"**Screening outcome:** `{screen_result.action}`")
            st.write(screen_result.reason)
            st.caption(
                "Inputs are taken from the selected simulated row. The daily-demand estimate is "
                "based on the uploaded/demo time series and may not represent a full-day operating profile."
            )

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
                "⬇ Download strategy summary (with provenance)",
                dataframe_csv(result["summary"], result["provenance"]),
                file_name="islandos_strategy_summary.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with d2:
            st.download_button(
                "⬇ Download timestep audit (with provenance)",
                dataframe_csv(result["detail"], result["provenance"]),
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
        optimizer_signature = stable_signature({
            "simulation_signature": simulation_signature,
            "population_size": int(pop_size),
            "generations": int(generations),
            "seed": 42,
            "optimizer_build": "NSGA2-2OBJ-DIAG-v1",
        })
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
                    "provenance": {
                        **export_provenance,
                        "run_signature": optimizer_signature,
                        "optimizer_population_size": int(pop_size),
                        "optimizer_generations": int(generations),
                        "optimizer_seed": 42,
                        "optimizer_build": "NSGA2-2OBJ-DIAG-v1",
                    },
                    "run_signature": optimizer_signature,
                }
            except Exception as exc:
                st.error(f"NSGA-II optimization failed: {exc}")
        optimizer_result = st.session_state.get("islandos_optimizer_result")
        if optimizer_result and optimizer_result.get("run_signature") != optimizer_signature:
            # A Streamlit session can outlive input or settings changes. Never show
            # optimizer output produced for a different run configuration.
            st.session_state.pop("islandos_optimizer_result", None)
            optimizer_result = None
            st.info("Previous NSGA-II results were cleared because input data, model assumptions, or optimizer settings changed. Run the optimizer again.")
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
                    "Download NSGA-II Pareto solutions (with provenance)",
                    dataframe_csv(pareto_rows, optimizer_result["provenance"]),
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

elif page == "Microgrid screening":
    st.title("Integrated microgrid strategy screening")
    st.write(
        "Change a small set of site assumptions, generate a transparent synthetic "
        "energy-and-water scenario, and compare three RO scheduling candidates "
        "against the same physical constraints."
    )
    st.warning(
        "Synthetic scenario only — not measured site data, a forecast, a global optimizer, "
        "or a live controller. Replace assumptions with validated site measurements before use."
    )
    with st.expander("Scenario and equipment assumptions", expanded=True):
        a, b, c = st.columns(3)
        with a:
            horizon = st.select_slider("Scenario horizon (hours)", options=[24, 48, 72, 120, 168], value=72)
            pv_peak = st.number_input("PV peak output (kW)", min_value=0.0, value=45.0, step=5.0)
            wind_mean = st.number_input("Wind average output (kW)", min_value=0.0, value=12.0, step=2.0)
        with b:
            essential_mean = st.number_input("Essential electric load (kW)", min_value=0.1, value=24.0, step=2.0)
            water_demand = st.number_input("Water demand (m³/hour)", min_value=0.0, value=0.45, step=0.05)
            ro_rating = st.number_input("RO rated power (kW)", min_value=0.1, value=20.0, step=2.0)
        with c:
            sec = st.number_input("RO specific energy (kWh/m³)", min_value=0.1, value=4.0, step=0.1)
            tank_capacity = st.number_input("Water tank capacity (m³)", min_value=0.1, value=60.0, step=5.0)
            initial_water = st.number_input("Initial water inventory (m³)", min_value=0.0, value=15.0, step=1.0)
    if initial_water > tank_capacity:
        st.error("Initial water inventory cannot exceed tank capacity.")
        st.stop()

    if st.button("▶ Generate scenario and compare candidates", type="primary", use_container_width=True):
        import math

        # Build a synthetic seven-day observation window, then forecast the
        # requested horizon using only the latest observed daily profile.
        history = generate_synthetic_microgrid_history(
            pv_peak_kw=float(pv_peak),
            wind_mean_kw=float(wind_mean),
            essential_load_mean_kw=float(essential_mean),
            water_demand_mean_m3_per_hour=float(water_demand),
            hours=168,
        )

        forecast = forecast_microgrid_signals(history, int(horizon), season_length=24)
        pv_series = forecast["pv_kw"]
        wind_series = forecast["wind_kw"]
        load_series = forecast["essential_load_kw"]
        demand_series = forecast["water_demand_m3"]

        scenario = MicrogridInputs(
            pv_power_kw=pv_series,
            wind_power_kw=wind_series,
            essential_load_kw=load_series,
            ro_requested_power_kw=[0.0] * int(horizon),
            water_demand_m3=demand_series,
            grid_available=[True] * int(horizon),
            grid_price_per_kwh=[0.25] * int(horizon),
            grid_emissions_kg_per_kwh=[0.4] * int(horizon),
        )
        config = MicrogridConfig(
            grid_import_limit_kw=max(float(essential_mean) * 2.0, 1.0),
            ro_rated_power_kw=float(ro_rating),
            ro_specific_energy_kwh_per_m3=float(sec),
            water_tank_capacity_m3=float(tank_capacity),
            water_initial_inventory_m3=float(initial_water),
        )
        try:
            ranked = screen_renewable_surplus_candidates(scenario, config)
            search_result = search_ro_schedule(
                scenario, config, max_passes=1, power_levels=(0.0, 0.5, 1.0)
            )
            candidate_schedules = {
                item.schedule_id: item.result.ro_requested_power_kw for item in ranked
            }
            candidate_schedules["coordinate_search"] = search_result.best.result.ro_requested_power_kw
            robustness = evaluate_schedule_robustness(
                candidate_schedules, scenario, config
            )
        except (ValueError, TypeError) as exc:
            st.error(f"Could not evaluate this scenario: {exc}")
            st.stop()

        rows = []
        for rank, item in enumerate(ranked, start=1):
            row = item.to_dict()
            row["rank"] = rank
            row["water_served_m3"] = float(item.result.water_served_m3.sum())
            row["final_water_inventory_m3"] = float(item.result.water_inventory_m3[-1])
            rows.append(row)
        baseline_row = next((row for row in rows if row["schedule_id"] == "no_ro"), None)
        for row in rows:
            served = row["water_served_m3"]
            row["whole_system_operating_cost_per_m3_served"] = (
                row["operating_cost"] / served if served > 0 else None
            )
            if baseline_row is not None:
                additional_water = served - baseline_row["water_served_m3"]
                row["incremental_cost_per_additional_m3_vs_no_ro"] = (
                    (row["operating_cost"] - baseline_row["operating_cost"]) / additional_water
                    if additional_water > 1e-9 else None
                )
        frame = pd.DataFrame(rows)
        st.caption(
            f"Data provenance: Synthetic demo data — not measured site data · "
            f"168 historical hourly observations → {horizon}-hour baseline forecast · "
            "seasonal-naive (repeat latest 24-hour profile)"
        )
        st.subheader("Baseline forecast used by the scheduler")
        forecast_frame = pd.DataFrame({
            "hour_ahead": list(range(1, int(horizon) + 1)),
            "PV forecast (kW)": pv_series,
            "Wind forecast (kW)": wind_series,
            "Essential load forecast (kW)": load_series,
            "Water demand forecast (m³/h)": demand_series,
        })
        st.line_chart(
            forecast_frame.set_index("hour_ahead"),
            use_container_width=True,
        )
        st.caption(
            "This is a transparent seasonal-naive benchmark, not a trained model. "
            "The same forecast series are passed into the physical simulator for every candidate."
        )
        replay_rows = []
        for signal_name, values in history.items():
            replay = rolling_origin_evaluate(
                values, initial_history=48, horizon=24, season_length=24
            )
            replay_rows.append({
                "Signal": signal_name,
                "Samples": replay.samples,
                "MAE": replay.mae,
                "RMSE": replay.rmse,
                "WAPE (%)": replay.wape_percent,
            })
        st.subheader("Synthetic historical replay")
        st.dataframe(
            pd.DataFrame(replay_rows).round(3),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Chronological replay on the generated synthetic history only. "
            "These errors measure this toy scenario's baseline behavior, not expected accuracy at a real site."
        )
        st.subheader("Ranked strategy comparison")
        display = frame[[
            "rank", "schedule_id", "feasible", "water_produced_m3",
            "water_served_m3", "unmet_water_m3", "operating_cost",
            "emissions_kg", "renewable_curtailed_kwh", "ro_electricity_kwh",
        ]]
        st.dataframe(display, use_container_width=True, hide_index=True)
        winner = ranked[0]
        st.subheader("Why this candidate ranked first")
        if winner.feasible:
            st.success(f"{winner.schedule_id} is the highest-ranked candidate and meets the modelled essential-electricity and water-demand constraints.")
        else:
            st.warning(
                f"No candidate meets all modelled service constraints. {winner.schedule_id} "
                "ranks first only as the least-infeasible option under the screening rule; "
                "do not treat it as an acceptable operating plan."
            )
        st.caption(
            "Ranking order: feasibility first, then unmet essential electricity, unmet water, "
            "operating cost, emissions, and renewable curtailment."
        )

        st.subheader("Physics-connected schedule search")
        st.caption(
            "A deterministic coordinate search tests zero, half-rated, and full-rated RO requests "
            "at each time step. Every trial is re-simulated by the same physical model. "
            "This bounded heuristic is not a global optimum."
        )
        searched = search_result.best
        search_metrics = st.columns(4)
        search_metrics[0].metric("Search evaluations", f"{search_result.evaluations:,}")
        search_metrics[1].metric("Water unmet", f"{searched.unmet_water_m3:,.2f} m³")
        search_metrics[2].metric("RO energy", f"{searched.ro_electricity_kwh:,.1f} kWh")
        search_metrics[3].metric("Search status", "Converged" if search_result.converged else "Pass limit")
        st.write(
            f"Selected schedule: **{searched.schedule_id}** · "
            f"Feasible: **{searched.feasible}** · "
            f"Passes: **{search_result.passes_completed}**"
        )
        search_schedule_frame = pd.DataFrame({
            "hour_ahead": list(range(1, int(horizon) + 1)),
            "RO requested power (kW)": searched.result.ro_requested_power_kw,
            "RO power served (kW)": searched.result.ro_power_served_kw,
            "Water demand (m³)": demand_series,
            "Water produced (m³)": searched.result.water_produced_m3,
        }).set_index("hour_ahead")
        st.line_chart(search_schedule_frame, use_container_width=True)
        st.download_button(
            "Download searched schedule (CSV)",
            data=search_schedule_frame.to_csv().encode("utf-8-sig"),
            file_name="islandos_coordinate_search_schedule.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.subheader("Stress-test robustness")
        st.caption(
            "The same candidate schedules are replayed under deterministic input shocks. "
            "These are illustrative sensitivity assumptions, not probabilities or measured forecast errors."
        )
        robustness_frame = pd.DataFrame([item.to_dict() for item in robustness])
        st.dataframe(
            robustness_frame[[
                "schedule_id", "robust_feasible", "scenarios_evaluated",
                "worst_essential_unserved_kwh", "worst_unmet_water_m3",
                "worst_operating_cost", "worst_emissions_kg",
            ]].round(3),
            use_container_width=True,
            hide_index=True,
        )
        stress_detail_rows = []
        for robustness_item in robustness:
            for scenario_name, evaluation in robustness_item.scenario_results.items():
                stress_detail_rows.append({
                    "schedule_id": robustness_item.schedule_id,
                    "stress_scenario": scenario_name,
                    **evaluation.to_dict(),
                })
        stress_detail_frame = pd.DataFrame(stress_detail_rows)
        with st.expander("Inspect scenario-by-scenario results"):
            st.dataframe(
                stress_detail_frame.round(3),
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                "Download stress-test audit (CSV)",
                data=stress_detail_frame.to_csv(index=False).encode("utf-8-sig"),
                file_name="islandos_stress_test_audit.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with st.expander("Stress scenario assumptions"):
            st.write("- Nominal: unchanged inputs.")
            st.write("- Low renewables: PV and wind reduced to 80% of baseline.")
            st.write("- High demand: essential electricity and water demand increased to 115%.")
            st.write("- High energy price: grid tariff and diesel unit cost increased to 125%.")
            st.write("- Grid outage: grid supply is unavailable for the full horizon.")
            st.write("- Combined stress: low renewables, high demand, and higher energy prices apply.")
            st.write(
                "Robust feasible means all tested scenarios satisfy the modelled essential-electricity "
                "and water-service constraints. It is not a reliability guarantee."
            )
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Water produced", f"{winner.water_produced_m3:,.1f} m³")
        k2.metric("Water demand unmet", f"{winner.unmet_water_m3:,.1f} m³")
        k3.metric("Operating cost", f"{winner.operating_cost:,.2f}")
        k4.metric("Renewable curtailment", f"{winner.renewable_curtailed_kwh:,.1f} kWh")
        chart = frame.set_index("schedule_id")[[
            "water_produced_m3", "unmet_water_m3", "renewable_curtailed_kwh"
        ]]
        st.bar_chart(chart)
        st.subheader("Customer economics indicators")
        st.dataframe(
            frame[[
                "schedule_id", "water_served_m3", "operating_cost",
                "whole_system_operating_cost_per_m3_served",
                "incremental_cost_per_additional_m3_vs_no_ro",
            ]].round(4),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Whole-system operating cost per m³ divides modelled site operating cost by water served. "
            "Incremental cost per additional m³ compares each candidate with the no-RO reference. "
            "These are scenario accounting indicators, not RO equipment tariffs, customer bills, "
            "CAPEX payback, or validated savings; values are only meaningful when service and cost "
            "boundaries are comparable."
        )
        st.download_button(
            "Download candidate comparison (CSV)",
            data=frame.to_csv(index=False).encode("utf-8-sig"),
            file_name="islandos_microgrid_candidate_screening.csv",
            mime="text/csv",
            use_container_width=True,
        )
        with st.expander("Candidate definitions and model limits"):
            st.write("- no_ro: RO power request is zero.")
            st.write("- conservative_surplus_50pct: requests 50% of renewable power above essential load.")
            st.write("- renewable_surplus_full: requests all renewable power above essential load.")
            st.write(
                "All candidates are evaluated by the same physical model. The model serves essential "
                "electricity first; RO uses remaining renewable power only. Grid imports can cover "
                "essential load but are not used to power RO in this screening model. Candidate "
                "generation is rule-based and uses the scenario values directly; it does not predict "
                "future weather or demand and does not prove savings."
            )

elif page == "Historical RO baseline":
    st.title("Historical RO operating-cost baseline")
    st.write(
        "Upload an exported RO operating log to reconstruct costs for the supplied period. "
        "This is the first customer-facing step before testing an optimizer against a real baseline."
    )
    st.warning(
        "Customer-supplied data is not independently verified. The report is historical accounting only: "
        "it does not forecast, optimize, annualize, or prove savings."
    )
    baseline_file = st.file_uploader(
        "Upload historical RO CSV", type=["csv"], key="historical_ro_csv"
    )
    st.markdown("**Required columns**")
    st.code(
        "timestamp,energy_kwh,water_produced_m3,electricity_price_per_kwh,"
        "runtime_hours,start_events",
        language="text",
    )
    st.caption(
        "One row per fixed-duration interval. Use ISO-8601 timestamps; include a timezone when available. "
        "Do not omit unknown costs by entering zero unless the customer confirms they are zero."
    )
    with st.expander("Enter customer-confirmed cost assumptions", expanded=True):
        rate_a, rate_b, rate_c = st.columns(3)
        with rate_a:
            hist_currency = st.text_input("Currency", value="CNY", key="hist_currency")
            hist_chemical = st.number_input(
                "Chemical cost (currency/m³)", min_value=0.0, value=0.0, step=0.01,
                key="hist_chemical",
            )
        with rate_b:
            hist_variable_om = st.number_input(
                "Variable O&M (currency/m³)", min_value=0.0, value=0.0, step=0.01,
                key="hist_variable_om",
            )
            hist_maintenance = st.number_input(
                "Maintenance (currency/runtime hour)", min_value=0.0, value=0.0, step=0.1,
                key="hist_maintenance",
            )
        with rate_c:
            hist_start_cost = st.number_input(
                "Start/stop cost per event", min_value=0.0, value=0.0, step=0.1,
                key="hist_start_cost",
            )
            hist_fixed_om = st.number_input(
                "Annual fixed O&M", min_value=0.0, value=0.0, step=100.0,
                key="hist_fixed_om",
            )
        hist_fixed_hours = st.number_input(
            "Annual fixed-O&M allocation hours", min_value=1.0, value=8760.0, step=24.0,
            key="hist_fixed_hours",
        )
    interval_a, interval_b = st.columns(2)
    with interval_a:
        hist_dt = st.number_input(
            "Duration represented by each row (hours)", min_value=0.001,
            value=1.0, step=0.5, key="hist_dt",
        )
    with interval_b:
        check_intervals = st.checkbox(
            "Reject missing/irregular timestamps", value=True, key="hist_check_intervals"
        )
        hist_expected_interval = st.number_input(
            "Expected timestamp interval (hours)", min_value=0.001,
            value=float(hist_dt), step=0.5, key="hist_expected_interval",
            disabled=not check_intervals,
        )
    if baseline_file is not None:
        try:
            rates = ROCostRates(
                currency=hist_currency,
                electricity_price_per_kwh=0.0,
                chemical_cost_per_m3=float(hist_chemical),
                variable_om_cost_per_m3=float(hist_variable_om),
                maintenance_cost_per_runtime_hour=float(hist_maintenance),
                start_stop_cost_per_event=float(hist_start_cost),
                fixed_om_per_year=float(hist_fixed_om),
                fixed_om_allocation_hours=float(hist_fixed_hours),
            )
            raw_text = baseline_file.getvalue().decode("utf-8-sig")
            reconstructed = reconstruct_historical_ro_cost(
                io.StringIO(raw_text),
                rates,
                dt_hours=float(hist_dt),
                expected_interval_hours=(
                    float(hist_expected_interval) if check_intervals else None
                ),
            )
            report = reconstructed["cost_report"]
            st.subheader("Reconstructed historical period")
            st.caption(
                f"Period: {reconstructed['period_start']} → {reconstructed['period_end']} · "
                f"{reconstructed['rows']} rows · {reconstructed['represented_hours']:.2f} represented hours"
            )
            st.caption(
                f"Provenance: {reconstructed['data_provenance']} · "
                f"Measurement status: {reconstructed['measurement_status']}"
            )
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Total supplied cost", f"{report.total_operating_cost:,.2f} {report.currency}")
            k2.metric(
                "Cost per m³",
                "N/A" if report.cost_per_m3 is None else f"{report.cost_per_m3:,.4f} {report.currency}/m³",
            )
            k3.metric("Water produced", f"{report.water_m3:,.2f} m³")
            k4.metric("Electricity", f"{report.energy_kwh:,.2f} kWh")
            breakdown = pd.DataFrame(
                [{"Cost component": name, "Cost": value, "Currency": report.currency}
                 for name, value in report.cost_breakdown.items()]
            )
            st.dataframe(breakdown, use_container_width=True, hide_index=True)
            export = {
                "status": reconstructed["status"],
                "data_provenance": reconstructed["data_provenance"],
                "measurement_status": reconstructed["measurement_status"],
                "period_start": reconstructed["period_start"],
                "period_end": reconstructed["period_end"],
                "rows": reconstructed["rows"],
                "represented_hours": reconstructed["represented_hours"],
                "currency": report.currency,
                "energy_kwh": report.energy_kwh,
                "water_m3": report.water_m3,
                "runtime_hours": report.runtime_hours,
                "start_stop_events": report.start_stop_events,
                **report.cost_breakdown,
                "total_operating_cost": report.total_operating_cost,
                "cost_per_m3": report.cost_per_m3,
            }
            st.download_button(
                "Download historical baseline report (CSV)",
                data=pd.DataFrame([export]).to_csv(index=False).encode("utf-8-sig"),
                file_name="islandos_historical_ro_baseline.csv",
                mime="text/csv",
                use_container_width=True,
            )
            with st.expander("Limitations and exclusions"):
                for limitation in reconstructed["limitations"]:
                    st.write(f"- {limitation}")
                st.write(
                    "A candidate schedule must later be compared over the same period, "
                    "water quantity and quality, service conditions, tariff, and equipment constraints. "
                    "Subtract integration, software, and operational-change costs before claiming net customer benefit."
                )
        except (ValueError, TypeError, UnicodeDecodeError) as exc:
            st.error(f"Could not reconstruct historical costs: {exc}")
    else:
        st.info("Upload a customer-supplied RO CSV to reconstruct the costs for its represented period. Data is not independently verified.")

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
