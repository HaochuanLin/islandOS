"""The call order behind the two decision pages, in one Streamlit-free place.

T4 gave a run a shape (``app_view_models``); this module gives it a *sequence*. The
dashboard page used to spell out forecast → coordination inputs → optimize → economics →
stress → paired impact inside its own body, and the joint optimizer page spelled out
manifest → dispatch search. A second front end would have had to reproduce that order
exactly, including which weights go where.

Nothing here calculates anything new: the functions call the same core entry points with
the same keyword arguments the pages used, and return every intermediate the pages still
read. No Streamlit import, no session state, no UI.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence
import uuid

from .app_view_models import build_run_result_summary
from .canonical_run import create_run_manifest
from .energy_system import EnergySystemConfig
from .forecast_engine import forecast_signals
from .forecast_optimizer_adapter import (
    build_coordination_inputs,
    build_service_equivalent_economics,
    evaluate_forecast_stress_scenarios,
)
from .impact_assessment import assess_energy_policy_impact
from optimization.energy_system_optimizer import optimize_energy_system, OptimizationWeights
from .planning_workflow import run_forecast_dispatch
from .site_inputs import SiteAssumptions


def run_customer_dashboard(
    *,
    history_stamps: Sequence[Any],
    history: Mapping[str, Any],
    units: Mapping[str, str],
    site: Any,
    currency: str,
    cost_priority: float,
    provenance: str,
) -> dict:
    """The dashboard's run, in the order and with the weights the page has always used.

    ``site`` is a ``SiteAssumptions``; the config and the objective weights are derived
    here so the caller cannot pair a site with weights built from a different slider.
    """
    config: EnergySystemConfig = site.to_energy_system_config()
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
    weights = OptimizationWeights(
        cost=float(cost_priority),
        reliability=float(1.0 - cost_priority),
        curtailment=0.0,
        battery_wear=0.0,
    )
    result = optimize_energy_system(coordinated.inputs, config, weights=weights)
    economics = build_service_equivalent_economics(result)
    stress = evaluate_forecast_stress_scenarios(coordinated, config)
    paired_impact = assess_energy_policy_impact(
        coordinated.inputs,
        config,
        currency=currency,
        evaluation_period="24-hour dispatch scenario",
        data_provenance=provenance,
    )
    return {
        "site": site,
        "config": config,
        "bundle": bundle,
        "coordinated": coordinated,
        "weights": weights,
        "result": result,
        "economics": economics,
        "stress": stress,
        "paired_impact": paired_impact,
    }


def run_joint_optimizer(
    *,
    run_manifest: Mapping[str, Any],
    timestamps: Sequence[Any],
    history: Mapping[str, Any],
    units: Mapping[str, str],
    config: EnergySystemConfig,
    grid_available: Sequence[bool],
    diesel_available: Sequence[bool],
) -> dict:
    """The joint optimizer's canonical run: dispatch search, then its own outputs.

    The forecast engine and the schedule search are one call here because the page has
    always obtained them through ``run_forecast_dispatch``; splitting them would invent a
    call order the core does not support.
    """
    planning_run = run_forecast_dispatch(
        run_manifest,
        timestamps=timestamps,
        history=history,
        units=units,
        energy_system_config=config,
        grid_available=list(grid_available),
        diesel_available=list(diesel_available),
    )
    predictions = planning_run["forecast_results"]
    target_timestamps = tuple(point.timestamp for point in predictions["pv_power_kw"].points)
    result = planning_run["optimization"]
    return {
        "planning_run": planning_run,
        "predictions": predictions,
        "target_timestamps": target_timestamps,
        "result": result,
        "handoff": result["generic_prediction_handoff"],
    }


def _site_from_request(request: Mapping[str, Any]) -> SiteAssumptions:
    site = dict(request["site"])
    site.pop("digest", None)
    return SiteAssumptions(**site)


def _timestamps_from_request(request: Mapping[str, Any]) -> tuple[datetime, ...]:
    stamps = request["history"]["timestamps_utc"]
    return tuple(
        datetime.fromisoformat(str(stamp).replace("Z", "+00:00")) for stamp in stamps
    )


def _manifest_from_request(
    request: Mapping[str, Any], config: EnergySystemConfig,
) -> dict:
    """The manifest the joint optimizer page builds, reconstructed from the request alone."""
    history_block = request["history"]
    dataset_payload = {
        "timestamps_utc": list(history_block["timestamps_utc"]),
        "signals": dict(history_block["signals"]),
        "units": dict(history_block["units"]),
    }
    dataset_digest = history_block.get("source_sha256") or hashlib.sha256(
        json.dumps(dataset_payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        .encode("utf-8")
    ).hexdigest()
    site_configuration_digest = hashlib.sha256(
        json.dumps(asdict(config), sort_keys=True, separators=(",", ":"), allow_nan=False)
        .encode("utf-8")
    ).hexdigest()
    availability = request["run_settings"]["availability"]
    optimizer_settings = request["run_settings"]["optimizer_settings"]
    horizon_hours = 24
    return create_run_manifest(
        project_id="streamlit-joint-resource-workspace",
        run_id=f"run-{uuid.uuid4().hex}",
        site_ref=(
            "customer-uploaded-site" if history_block.get("source_sha256") else "synthetic-demo-site"
        ),
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        dataset_sha256=dataset_digest,
        dataset_schema_version="canonical-hourly-signals-v1",
        source_type="customer_provided" if history_block.get("source_sha256") else "synthetic",
        site_configuration_version="1",
        site_configuration_sha256=site_configuration_digest,
        required_signals=dict(history_block["units"]),
        forecast_horizon_hours=horizon_hours,
        optimizer_id="prediction_resource_dispatch",
        optimizer_version="1",
        optimizer_settings={
            "population_size": int(optimizer_settings["population_size"]),
            "generations": int(optimizer_settings["generations"]),
            "seed": int(optimizer_settings["seed"]),
        },
        scenario_assumptions={
            "grid_available": [bool(availability["grid_all_hours"])] * horizon_hours,
            "diesel_available": [bool(availability["diesel_all_hours"])] * horizon_hours,
        },
        forecast_settings={
            "backtest_horizon": 24,
            "season_length": 24,
            "confidence_level": 0.90,
        },
    )


def replay_run_request(request: Mapping[str, Any]) -> dict:
    """Replay a `run_request` view with no page and no Streamlit, and return its summary.

    This is what a transport can call: the request carries the site, the time axis, the
    history with its units, the page-specific settings and the run-specific settings, so
    the same run can be produced from a file instead of a browser session. It refuses a
    request whose page it does not know rather than guessing a sequence.
    """
    page = request.get("page")
    site = _site_from_request(request)
    timestamps = _timestamps_from_request(request)
    history_block = request["history"]
    history = dict(history_block["signals"])
    units = dict(history_block["units"])
    provenance = str(history_block["provenance"])
    currency = str(request["run_settings"]["currency"])

    if page == "customer_dashboard":
        cost_priority = float(request["page_settings"]["cost_priority"])
        outputs = run_customer_dashboard(
            history_stamps=timestamps,
            history=history,
            units=units,
            site=site,
            currency=currency,
            cost_priority=cost_priority,
            provenance=provenance,
        )
        summary = build_run_result_summary(
            page=page, result=outputs["result"], economics=outputs["economics"],
            currency=currency,
        )
        return {"page": page, "result": summary, "annual": None}

    if page == "joint_resource_optimizer":
        config = site.to_energy_system_config()
        manifest = _manifest_from_request(request, config)
        availability = request["run_settings"]["availability"]
        outputs = run_joint_optimizer(
            run_manifest=manifest,
            timestamps=timestamps,
            history=history,
            units=units,
            config=config,
            grid_available=[bool(availability["grid_all_hours"])] * 24,
            diesel_available=[bool(availability["diesel_all_hours"])] * 24,
        )
        summary = build_run_result_summary(
            page=page,
            result=outputs["result"],
            planning_run=outputs["planning_run"],
            currency=currency,
        )
        return {"page": page, "result": summary, "annual": None}

    raise ValueError(f"page must be one of customer_dashboard, joint_resource_optimizer; got {page!r}")
