"""Streamlit experiment for the shared IslandOS asset/constraint model."""
from __future__ import annotations

import json

import streamlit as st

from islandos_core.assets import (
    AssetParameter,
    AssetRecord,
    OperatingConstraint,
    evaluate_asset_readiness,
)

st.set_page_config(page_title="IslandOS Asset Registry Lab", page_icon="🔧", layout="wide")
st.title("IslandOS · Asset & Constraint Registry")
st.caption("Streamlit product laboratory · versioned asset records · no device control")

st.info(
    "This experiment records vendor nameplate ratings separately from the configuration "
    "actually installed at the site. Hard operating limits must come from an authoritative "
    "site or manufacturer source and be confirmed by an authorized operator."
)

if "islandos_asset_records" not in st.session_state:
    st.session_state["islandos_asset_records"] = {}

ASSET_FIELDS = {
    "battery": [
        ("max_charge_kw", "Maximum charge power", "kW", "max"),
        ("max_discharge_kw", "Maximum discharge power", "kW", "max"),
        ("soc_min_pct", "Minimum permitted SOC", "%", "min"),
        ("soc_max_pct", "Maximum permitted SOC", "%", "max"),
    ],
    "pv": [("max_power_kw", "Maximum usable PV power", "kW", "max")],
    "wind": [("max_power_kw", "Maximum usable wind power", "kW", "max")],
    "diesel_generator": [
        ("max_power_kw", "Maximum generator power", "kW", "max"),
        ("min_stable_power_kw", "Minimum stable generator power", "kW", "min"),
    ],
    "grid_connection": [("import_limit_kw", "Grid import limit", "kW", "max")],
    "flexible_load": [
        ("max_power_kw", "Maximum flexible-load power", "kW", "max"),
        ("min_power_kw", "Minimum operating power", "kW", "min"),
    ],
    "generic": [],
}

with st.form("asset_registry_form"):
    st.subheader("1 · Identify the asset")
    c1, c2 = st.columns(2)
    asset_id = c1.text_input("Unique asset ID", placeholder="battery-main-01")
    site_id = c2.text_input("Site ID", placeholder="site-001")
    c3, c4, c5 = st.columns(3)
    asset_type = c3.selectbox(
        "Asset type",
        ["battery", "pv", "wind", "diesel_generator", "grid_connection", "flexible_load", "generic"],
        format_func=lambda value: {
            "battery": "Battery energy storage",
            "pv": "Solar PV",
            "wind": "Wind turbine / farm",
            "diesel_generator": "Diesel generator",
            "grid_connection": "Grid connection",
            "flexible_load": "Flexible load",
            "generic": "Other asset",
        }[value],
    )
    manufacturer = c4.text_input("Manufacturer (optional)")
    model = c5.text_input("Model (optional)")

    st.subheader("2 · Separate nameplate ratings from installed configuration")
    st.caption("Leave a field blank if unknown. Do not copy a vendor maximum into the installed field unless that is the actual site configuration.")
    nameplate_power = st.text_input("Vendor nameplate power (kW)", key="asset_nameplate_power")
    installed_power = st.text_input("Installed / configured power (kW)", key="asset_installed_power")
    nameplate_energy = ""
    installed_energy = ""
    if asset_type == "battery":
        nameplate_energy = st.text_input("Vendor nameplate energy capacity (kWh)", key="asset_nameplate_energy")
        installed_energy = st.text_input("Installed usable energy capacity (kWh)", key="asset_installed_energy")

    st.subheader("3 · Enter hard operating constraints")
    st.caption("These are safety/feasibility boundaries, not optimization preferences. Unknown limits remain missing and block the relevant asset screening.")
    constraint_inputs = {}
    for field, label, unit, operator in ASSET_FIELDS[asset_type]:
        constraint_inputs[field] = st.text_input(f"{label} ({unit})", key=f"asset_constraint_{field}")
    source_type = st.selectbox(
        "Where do these parameters come from?",
        ["customer_provided", "vendor_specification", "measured", "inferred"],
        format_func=lambda value: {
            "customer_provided": "Site engineer / operator / commissioning record",
            "vendor_specification": "Manufacturer datasheet",
            "measured": "Measured operating data",
            "inferred": "Estimated / inferred (not confirmed)",
        }[value],
    )
    source_reference = st.text_input(
        "Source reference",
        placeholder="e.g. commissioning sheet rev. 3, page 12",
        help="Record a document name, equipment tag, or other traceable source. Do not enter confidential credentials.",
    )
    confirmed = st.checkbox("I confirm these entered hard limits match the installed site configuration")
    available = st.checkbox("Asset is currently available for scenario analysis", value=True)

    submitted = st.form_submit_button("Validate and add asset", type="primary", use_container_width=True)

if submitted:
    try:
        if not asset_id.strip() or not site_id.strip():
            raise ValueError("Asset ID and Site ID are required.")
        nameplate = {}
        installed = {}
        if nameplate_power.strip():
            nameplate["rated_power_kw"] = AssetParameter(
                float(nameplate_power), "kW", "vendor_specification",
                source_reference.strip() or "source not yet documented", False,
            )
        if installed_power.strip():
            installed["configured_power_kw"] = AssetParameter(
                float(installed_power), "kW", source_type,
                source_reference.strip() or "source not yet documented", confirmed,
            )
        if asset_type == "battery":
            if nameplate_energy.strip():
                nameplate["energy_capacity_kwh"] = AssetParameter(
                    float(nameplate_energy), "kWh", "vendor_specification",
                    source_reference.strip() or "source not yet documented", False,
                )
            if installed_energy.strip():
                installed["usable_energy_capacity_kwh"] = AssetParameter(
                    float(installed_energy), "kWh", source_type,
                    source_reference.strip() or "source not yet documented", confirmed,
                )
        constraints = []
        for field, label, unit, operator in ASSET_FIELDS[asset_type]:
            raw_value = constraint_inputs[field].strip()
            if not raw_value:
                continue
            value = float(raw_value)
            constraints.append(OperatingConstraint(
                constraint_id=f"{asset_id}:{field}",
                parameter=field,
                severity="hard",
                unit=unit,
                operator=operator,
                lower_bound=value if operator == "min" else None,
                upper_bound=value if operator == "max" else None,
                source_type=source_type,
                source_reference=source_reference.strip() or "source not yet documented",
                confirmed=confirmed and bool(source_reference.strip()),
                rationale=label,
            ))
        asset = AssetRecord(
            asset_id=asset_id.strip(),
            site_id=site_id.strip(),
            asset_type=asset_type,
            manufacturer=manufacturer.strip() or None,
            model=model.strip() or None,
            nameplate_parameters=nameplate,
            installed_parameters=installed,
            observed_parameters={},
            constraints=tuple(constraints),
            available=available,
        )
        st.session_state["islandos_asset_records"][asset.asset_id] = asset
        st.success(f"Saved asset record: {asset.asset_id}")
    except (ValueError, TypeError) as exc:
        st.error(f"Asset was not saved: {exc}")

records = st.session_state["islandos_asset_records"]
st.subheader("4 · Review asset readiness")
if not records:
    st.info("No assets have been added in this session yet.")
else:
    for asset in records.values():
        with st.expander(f"{asset.asset_id} · {asset.asset_type}", expanded=True):
            readiness = evaluate_asset_readiness(asset)
            if readiness["can_screen"]:
                st.success("Ready for offline scenario screening")
            else:
                st.warning("Blocked: required confirmed hard constraints are missing or inconsistent")
            for blocker in readiness["blockers"]:
                st.write(f"- {blocker}")
            st.json(asset.to_mapping(), expanded=False)
    st.download_button(
        "Export asset registry (JSON)",
        data=json.dumps(
            {"schema_version": "1.0", "assets": [asset.to_mapping() for asset in records.values()]},
            ensure_ascii=False, indent=2,
        ).encode("utf-8"),
        file_name="islandos_asset_registry.json",
        mime="application/json",
        use_container_width=True,
    )

st.caption(
    "This page stores records only in the current Streamlit session. It does not persist a "
    "customer project, connect to hardware, verify the source document, or certify equipment safety."
)
