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

from .app_view_models import build_device_flexibility_summary, build_run_result_summary
from .canonical_run import create_run_manifest, deterministic_run_id
from .energy_system import EnergySystemConfig, EnergySystemInputs, dispatch_energy_system
from .flexible_task_dispatch import attach_device_task_schedule
from .flexible_tasks import DeviceTask, schedule_device_tasks
from .forecast_engine import forecast_signals
from .forecast_optimizer_adapter import (
    build_coordination_inputs,
    build_service_equivalent_economics,
    evaluate_forecast_stress_scenarios,
)
from .impact_assessment import assess_energy_policy_impact
from .investment_economics import evaluate_investment_economics
from optimization.energy_system_optimizer import optimize_energy_system, OptimizationWeights
from .planning_workflow import run_forecast_dispatch
from .site_inputs import SiteAssumptions

#: A replay has no wall clock to stamp into the manifest, so it pins one. Fixed rather
#: than "now" because the point of a replay is that the same request reproduces the
#: same run: the epoch becomes part of the declaration, not a hidden variable.
REPLAY_CREATED_AT_UTC = "1970-01-01T00:00:00+00:00"


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
    request: Mapping[str, Any],
    config: EnergySystemConfig,
    *,
    run_id: str | None = None,
    created_at_utc: str | None = None,
) -> dict:
    """The manifest the joint optimizer page builds, reconstructed from the request alone.

    The page mints a fresh uuid and stamps the wall clock, so two page runs over the
    same inputs are two sessions. A replay has no wall clock and no session: it passes
    ``run_id`` and ``created_at_utc`` so the same request reproduces the same manifest
    digest, and therefore the same summary, every time.
    """
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
        run_id=run_id or f"run-{uuid.uuid4().hex}",
        site_ref=(
            "customer-uploaded-site" if history_block.get("source_sha256") else "synthetic-demo-site"
        ),
        created_at_utc=created_at_utc or datetime.now(timezone.utc).isoformat(),
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


def device_task_payload(task: DeviceTask) -> dict[str, Any]:
    """One ``DeviceTask`` as the request contract carries it; no validation, no maths."""
    return {
        "task_id": task.task_id,
        "name": task.name,
        "load_class": task.load_class,
        "rated_power_kw": float(task.rated_power_kw),
        "required_energy_kwh": float(task.required_energy_kwh),
        "earliest_start_step": int(task.earliest_start_step),
        "latest_finish_step": int(task.latest_finish_step),
        "min_power_kw": float(task.min_power_kw),
        "minimum_run_steps": int(task.minimum_run_steps),
        "interruptible": bool(task.interruptible),
        "priority": int(task.priority),
        "availability": list(task.availability) if task.availability is not None else None,
        "critical_power_profile_kw": (
            list(task.critical_power_profile_kw)
            if task.critical_power_profile_kw is not None
            else None
        ),
    }


def _task_from_payload(payload: Mapping[str, Any]) -> DeviceTask:
    availability = payload["availability"]
    profile = payload["critical_power_profile_kw"]
    return DeviceTask(
        task_id=str(payload["task_id"]),
        name=str(payload["name"]),
        load_class=str(payload["load_class"]),
        rated_power_kw=float(payload["rated_power_kw"]),
        required_energy_kwh=float(payload["required_energy_kwh"]),
        earliest_start_step=int(payload["earliest_start_step"]),
        latest_finish_step=int(payload["latest_finish_step"]),
        min_power_kw=float(payload["min_power_kw"]),
        minimum_run_steps=int(payload["minimum_run_steps"]),
        interruptible=bool(payload["interruptible"]),
        priority=int(payload["priority"]),
        availability=tuple(bool(x) for x in availability) if availability is not None else None,
        critical_power_profile_kw=(
            tuple(float(x) for x in profile) if profile is not None else None
        ),
    )


def run_device_planner(
    *,
    tasks: Sequence[DeviceTask],
    prices: Sequence[float],
    task_power_budget_kw: Sequence[float],
    pv_generation_kw: Sequence[float],
    wind_generation_kw: Sequence[float],
    base_load_kw: Sequence[float],
    site: Any,
) -> dict:
    """The device planner's schedule plus its two replays, in the page's own order.

    Nothing is recalculated here beyond what the page always did: reserve critical
    profiles, schedule the flexible tasks against the tariff, replay the schedule through
    the shared energy system, then replay an earliest-feasible reference for comparison.
    """
    config: EnergySystemConfig = site.to_energy_system_config()
    schedule = schedule_device_tasks(tasks, prices, task_power_budget_kw)
    inputs = EnergySystemInputs(
        pv_generation_kw=list(pv_generation_kw),
        wind_generation_kw=list(wind_generation_kw),
        load_kw=list(base_load_kw),
        grid_price_per_kwh=list(prices),
        grid_available=[True] * len(prices),
        diesel_available=[True] * len(prices),
    )
    replay = dispatch_energy_system(attach_device_task_schedule(inputs, schedule), config)
    reference_schedule = schedule_device_tasks(tasks, [1.0] * len(prices), task_power_budget_kw)
    reference_replay = dispatch_energy_system(
        attach_device_task_schedule(inputs, reference_schedule), config
    )
    return {
        "site": site,
        "config": config,
        "inputs": inputs,
        "schedule": schedule,
        "replay": replay,
        "reference_schedule": reference_schedule,
        "reference_replay": reference_replay,
    }


def _replay_investment(request: Mapping[str, Any], economics: Mapping[str, Any]) -> dict | None:
    """Replay page 05's customer-entered investment screen, when the request carries it.

    The eight investment fields are already validated by ``build_run_request``. This calls
    the same evaluator the page calls and passes the same service-equivalence gate. It does
    not annualise a simulated day: the annual bills are customer-entered inputs, not model
    outputs.
    """
    investment = request["run_settings"].get("investment")
    if investment is None:
        return None
    if not isinstance(investment, Mapping):
        raise ValueError("run_settings.investment must be an object")
    service_equivalent = bool(
        economics.get("service_equivalent") and economics.get("cost_comparison_valid")
    )
    result = evaluate_investment_economics(
        baseline_annual_energy_cost=float(investment["baseline_annual_energy_cost"]),
        proposed_annual_energy_cost=float(investment["proposed_annual_energy_cost"]),
        annual_incremental_om_cost=float(investment["annual_incremental_om_cost"]),
        upfront_capex=float(investment["upfront_capex"]),
        project_life_years=int(investment["project_life_years"]),
        discount_rate=float(investment["discount_rate"]),
        annual_energy_saving_escalation_rate=float(
            investment["annual_energy_saving_escalation_rate"]
        ),
        annual_om_escalation_rate=float(investment["annual_om_escalation_rate"]),
        service_equivalent=service_equivalent,
    )
    return result.to_dict()


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
        return {
            "page": page,
            "result": summary,
            "annual": None,
            "investment": _replay_investment(request, outputs["economics"]),
        }

    if page == "joint_resource_optimizer":
        config = site.to_energy_system_config()
        manifest = _manifest_from_request(
            request,
            config,
            run_id=deterministic_run_id("run", {"request": request}),
            created_at_utc=REPLAY_CREATED_AT_UTC,
        )
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

    if page == "device_flexibility_planner":
        page_inputs = request["page_inputs"]
        if not isinstance(page_inputs, Mapping):
            raise ValueError("the device planner request must carry page_inputs")
        tasks = [_task_from_payload(task) for task in page_inputs["tasks"]]
        outputs = run_device_planner(
            tasks=tasks,
            prices=history["tariff_per_kwh"],
            task_power_budget_kw=page_inputs["task_power_budget_kw"],
            pv_generation_kw=history["pv_generation_kw"],
            wind_generation_kw=history["wind_generation_kw"],
            base_load_kw=history["load_kw"],
            site=site,
        )
        summary = build_device_flexibility_summary(
            result=outputs["schedule"].to_dict(),
            metrics=outputs["replay"]["summary"],
            reference_metrics=outputs["reference_replay"]["summary"],
            currency=currency,
        )
        return {"page": page, "result": summary, "annual": None}

    raise ValueError(
        "page must be one of customer_dashboard, joint_resource_optimizer, "
        f"device_flexibility_planner; got {page!r}"
    )
