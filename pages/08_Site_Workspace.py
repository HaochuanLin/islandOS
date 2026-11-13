"""Local-first project and site workspace.

This page is available only in an explicitly enabled local deployment. The
public hosted demo must not be used as a customer data room.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

import streamlit as st

from islandos_core.assets import AssetRecord, evaluate_asset_readiness
from islandos_core.site_workspace import (
    export_project_package,
    list_site_profiles,
    save_site_profile,
)
from islandos_core.workspace_store import (
    WorkspaceStoreError,
    create_project,
    initialize_workspace,
    list_projects,
    list_asset_records,
    list_import_artifacts,
    save_asset_record,
    verify_audit_chain,
)

st.set_page_config(page_title="IslandOS | Site Workspace", page_icon="🏝️", layout="wide")
st.title("Site workspace")
st.caption("Local project records, site configuration, asset register and portable evidence export")

if os.getenv("ISLANDOS_ENABLE_LOCAL_WORKSPACE", "").strip() != "1":
    st.warning("The local workspace is disabled. Set ISLANDOS_ENABLE_LOCAL_WORKSPACE=1 in a trusted local deployment.")
    st.info("The public Streamlit demonstration is not a customer data room. Do not upload confidential site telemetry or personal information there.")
    st.stop()

db_path = Path(os.getenv("ISLANDOS_WORKSPACE_DB", ".islandos/workspace.sqlite3"))
storage_root = Path(os.getenv("ISLANDOS_SOURCE_STORAGE_DIR", ".islandos/source_files"))
actor_id = os.getenv("ISLANDOS_LOCAL_ACTOR_ID", "local_operator").strip() or "local_operator"
initialize_workspace(
    db_path,
    workspace_id=os.getenv("ISLANDOS_WORKSPACE_ID", "local-islandos-workspace"),
    actor_id=actor_id,
)

st.subheader("Projects")
projects = list_projects(db_path)
with st.expander("Create a project", expanded=not bool(projects)):
    with st.form("create_site_project"):
        project_name = st.text_input("Project / site workspace name", max_chars=120)
        consent = st.checkbox("I consent to storing this project name and related configuration locally on this computer.")
        submitted = st.form_submit_button("Create project", disabled=not consent)
    if submitted:
        if not project_name.strip():
            st.error("Enter a project name.")
        else:
            import uuid
            project_id = "site-" + uuid.uuid4().hex[:12]
            try:
                create_project(
                    db_path, project_id=project_id, display_name=project_name.strip(),
                    actor_id=actor_id, consent_to_store_metadata=True,
                )
                st.success("Project created. Select it below to configure the site.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not create project: {exc}")

projects = list_projects(db_path)
if not projects:
    st.info("Create a project to begin. A project is a local container for one site's configuration, equipment and data provenance.")
    st.stop()

labels = {f"{item['display_name']} · {item['project_id']}": item["project_id"] for item in projects}
selected_label = st.selectbox("Active project", list(labels))
project_id = labels[selected_label]

st.divider()
st.subheader("Site configuration")
profiles = list_site_profiles(db_path, project_id=project_id)
latest = profiles[-1]["profile"] if profiles else {}
with st.form("site_profile_form"):
    site_name = st.text_input("Site name", value=latest.get("site_name", ""))
    c1, c2 = st.columns(2)
    with c1:
        site_type = st.selectbox(
            "Site type", ["microgrid", "island", "industrial", "commercial", "community", "other"],
            index=["microgrid", "island", "industrial", "commercial", "community", "other"].index(latest.get("site_type", "other")),
        )
        country = st.text_input("Country / region", value=latest.get("country", ""))
        timezone_name = st.text_input("IANA time zone", value=latest.get("timezone", "UTC"), help="Example: Asia/Tokyo")
    with c2:
        currency = st.text_input("Reporting currency (3-letter code)", value=latest.get("currency", "USD"), max_chars=3)
        description = st.text_area("Description / operating context", value=latest.get("description", ""), max_chars=2000)
    save_profile = st.form_submit_button("Save new site configuration version")
if save_profile:
    try:
        saved = save_site_profile(
            db_path, project_id=project_id,
            profile={
                "site_name": site_name, "site_type": site_type, "country": country,
                "timezone": timezone_name, "currency": currency.upper(),
                "description": description,
            },
            actor_id=actor_id,
        )
        st.success(f"Saved site configuration version {saved['version']}. Previous versions remain available.")
        st.rerun()
    except Exception as exc:
        st.error(f"Site configuration was not saved: {exc}")

if profiles:
    st.caption(f"Configuration history: {len(profiles)} immutable version(s). Latest SHA-256: {profiles[-1]['profile_sha256']}")
    with st.expander("View configuration history"):
        for item in reversed(profiles):
            st.markdown(f"**Version {item['version']}** · {item['created_at']} · `{item['profile_sha256'][:16]}…`")
            st.json(item["profile"])

st.divider()
st.subheader("Equipment register")
st.caption("Add equipment with explicit source references and confirmed limits. Incomplete assets remain recorded but are blocked from screening.")
example = {
    "asset_id": "pv-01",
    "site_id": project_id,
    "asset_type": "pv",
    "nameplate_parameters": {
        "rated_power_kw": {"value": 100, "unit": "kW", "source_type": "vendor_specification", "source_reference": "PV datasheet rev A", "confirmed": True}
    },
    "installed_parameters": {
        "configured_power_kw": {"value": 90, "unit": "kW", "source_type": "customer_provided", "source_reference": "Commissioning record", "confirmed": True}
    },
    "observed_parameters": {},
    "constraints": [
        {"constraint_id": "pv-max-01", "parameter": "max_power_kw", "severity": "hard", "unit": "kW", "operator": "max", "upper_bound": 90, "source_type": "customer_provided", "source_reference": "Inverter configured limit", "confirmed": True}
    ],
}
with st.expander("Add or version an asset"):
    st.caption("Edit the example JSON or paste a complete AssetRecord. Saving an existing asset ID creates a new immutable version.")
    asset_json = st.text_area("Asset record JSON", value=json.dumps(example, ensure_ascii=False, indent=2), height=360)
    if st.button("Validate and save asset"):
        try:
            raw = json.loads(asset_json)
            asset = AssetRecord.from_mapping(raw)
            saved = save_asset_record(db_path, project_id=project_id, asset=asset, actor_id=actor_id)
            st.success(f"Saved {saved['asset_id']} version {saved['version']}.")
            st.json(saved["readiness"])
            st.rerun()
        except Exception as exc:
            st.error(f"Asset was not saved: {exc}")

assets = list_asset_records(db_path, project_id=project_id, include_history=True)
if assets:
    st.markdown("**Registered asset versions**")
    rows = []
    for item in assets:
        readiness = item.get("readiness", {})
        rows.append({
            "Asset": item.get("asset_id"), "Type": item.get("asset_type"),
            "Version": item.get("version"), "Readiness": readiness.get("status"),
            "Can screen": readiness.get("can_screen"),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
    with st.expander("Inspect asset records"):
        for item in assets:
            st.markdown(f"**{item['asset_id']} · v{item['version']}**")
            st.json(item["record"])
else:
    st.info("No equipment has been registered in this project yet.")

st.divider()
st.subheader("Imported datasets")
imports = list_import_artifacts(db_path, project_id=project_id)
if imports:
    st.dataframe(imports, use_container_width=True, hide_index=True)
else:
    st.info("No import metadata is registered yet. Use Data onboarding & workspace to inspect a CSV/XLSX file and register its provenance.")

st.divider()
st.subheader("Portable project export")
st.caption("Export one project's configuration, equipment history, import metadata, run manifests and audit evidence. Original source files are included only if they were separately retained with explicit consent.")
include_sources = st.checkbox("Include locally retained original CSV/XLSX files", value=True)
if st.button("Build verified project package"):
    try:
        with tempfile.TemporaryDirectory(prefix="islandos-export-") as temp_dir:
            target = Path(temp_dir) / "islandos-project.zip"
            result = export_project_package(
                db_path, target, project_id=project_id,
                storage_dir=storage_root, include_retained_sources=include_sources,
            )
            package_bytes = target.read_bytes()
        st.success(f"Package integrity verified · SHA-256: {result['sha256']}")
        st.download_button(
            "Download project package",
            data=package_bytes,
            file_name=f"islandos-{project_id}.zip",
            mime="application/zip",
        )
    except Exception as exc:
        st.error(f"Project export failed: {exc}")

audit = verify_audit_chain(db_path)
st.divider()
st.caption(f"Local workspace audit chain: {'valid' if audit['valid'] else 'FAILED'} · {audit['event_count']} events")
if not audit["valid"]:
    st.error("Workspace audit integrity failed. Do not use this workspace for further decision-support runs until investigated.")
