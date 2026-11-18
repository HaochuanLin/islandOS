"""Canonical offline forecast-to-dispatch application workflow.

This service composes the existing forecast catalog and dispatch adapter behind
one validated run manifest. It is a planning workflow, not a controller.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import hashlib
import json
from typing import Any

from .canonical_run import CanonicalRunManifest, verify_run_manifest
from .forecast_signal_catalog import forecast_site_signals
from .prediction_dispatch_adapter import optimize_prediction_resource_schedule


_ALLOWED_OPTIMIZER_SETTINGS = {
    "population_size",
    "generations",
    "seed",
    "max_unmet_load_kwh",
    "max_critical_unmet_load_kwh",
    "terminal_battery_soc_min",
    "water_schedule_mode",
    "water_lookahead_hours",
}


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_forecast_dispatch(
    manifest: CanonicalRunManifest | Mapping[str, Any],
    *,
    timestamps: Sequence[datetime],
    history: Mapping[str, Sequence[float]],
    units: Mapping[str, str],
    energy_system_config,
    grid_available: Sequence[bool],
    diesel_available: Sequence[bool],
    water_service=None,
    water_schedule_mode: str = "just_in_time",
    water_lookahead_hours: int = 6,
) -> dict[str, Any]:
    """Run one manifest-bound forecast and offline resource dispatch.

    The manifest is checked before any model is run. Signal IDs, units and
    forecast horizon must match it exactly. The result includes the forecast
    provenance, complete optimizer result and a digest of decision evidence.
    No missing data is imputed and no device command is produced.
    """
    if isinstance(manifest, CanonicalRunManifest):
        manifest_value = manifest.to_dict()
    elif isinstance(manifest, Mapping):
        manifest_value = dict(manifest)
    else:
        raise TypeError("manifest must be a CanonicalRunManifest or mapping")
    verification = verify_run_manifest(manifest_value)
    if not verification["valid"]:
        raise ValueError("run manifest verification failed: " + "; ".join(verification["errors"]))

    forecast_spec = manifest_value["forecast"]
    required_signals = dict(forecast_spec["required_signals"])
    if not isinstance(history, Mapping) or set(history) != set(required_signals):
        raise ValueError("history signal IDs must exactly match the manifest required_signals")
    if not isinstance(units, Mapping) or dict(units) != required_signals:
        raise ValueError("units must exactly match the manifest signal-to-unit contract")
    if not isinstance(timestamps, Sequence) or len(timestamps) < 3:
        raise ValueError("timestamps must contain at least three observations")
    horizon = forecast_spec["horizon_hours"]
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError("manifest forecast horizon is invalid")
    if len(grid_available) != horizon or len(diesel_available) != horizon:
        raise ValueError("grid and diesel availability arrays must match the manifest forecast horizon")
    optimizer_id = manifest_value["optimizer"]["id"]
    if optimizer_id != "prediction_resource_dispatch":
        raise ValueError("manifest optimizer.id must be 'prediction_resource_dispatch'")
    scenario = manifest_value["scenario_assumptions"]
    if scenario.get("grid_available") != list(grid_available):
        raise ValueError("grid availability must exactly match the manifest scenario_assumptions")
    if scenario.get("diesel_available") != list(diesel_available):
        raise ValueError("diesel availability must exactly match the manifest scenario_assumptions")
    price_unit = required_signals.get("tariff_per_kwh")
    if not isinstance(price_unit, str) or not price_unit.strip():
        raise ValueError("the current resource dispatch workflow requires tariff_per_kwh with an explicit unit")

    optimizer_settings = dict(manifest_value["optimizer"]["settings"])
    unknown_settings = set(optimizer_settings) - _ALLOWED_OPTIMIZER_SETTINGS
    if unknown_settings:
        raise ValueError("unsupported optimizer settings: " + ", ".join(sorted(unknown_settings)))
    if "water_schedule_mode" in optimizer_settings and optimizer_settings["water_schedule_mode"] != water_schedule_mode:
        raise ValueError("water_schedule_mode must match the manifest optimizer settings")
    if "water_lookahead_hours" in optimizer_settings and optimizer_settings["water_lookahead_hours"] != water_lookahead_hours:
        raise ValueError("water_lookahead_hours must match the manifest optimizer settings")

    forecast_settings = dict(forecast_spec["settings"])
    bundle = forecast_site_signals(
        timestamps,
        history,
        units,
        horizon=horizon,
        backtest_horizon=forecast_settings["backtest_horizon"],
        season_length=forecast_settings["season_length"],
        confidence_level=forecast_settings["confidence_level"],
    )
    selected_models = {
        signal_id: result.model_id
        for signal_id, result in sorted(bundle.results.items())
    }
    expected_models = dict(forecast_spec.get("model_ids", {}))
    mismatched_models = {
        signal_id: (expected, selected_models.get(signal_id))
        for signal_id, expected in expected_models.items()
        if selected_models.get(signal_id) != expected
    }
    if mismatched_models:
        raise ValueError("selected forecast models do not match manifest: " + repr(mismatched_models))

    optimizer_kwargs = dict(optimizer_settings)
    optimizer_kwargs.pop("water_schedule_mode", None)
    optimizer_kwargs.pop("water_lookahead_hours", None)
    dispatch_result = optimize_prediction_resource_schedule(
        bundle.results,
        energy_system_config,
        history_start_utc=bundle.history_start_utc,
        history_end_utc=bundle.history_end_utc,
        grid_available=grid_available,
        diesel_available=diesel_available,
        price_unit=price_unit,
        water_service=water_service,
        water_schedule_mode=water_schedule_mode,
        water_lookahead_hours=water_lookahead_hours,
        **optimizer_kwargs,
    )

    recommendation = dispatch_result.get("recommendation")
    if not isinstance(recommendation, Mapping):
        raise ValueError("optimizer did not return a structured recommendation")
    handoff = dispatch_result.get("generic_prediction_handoff")
    if not isinstance(handoff, Mapping) or handoff.get("device_write_authorized") is not False:
        raise ValueError("optimizer handoff is missing or violates the advisory-only boundary")

    evidence = {
        "manifest_sha256": manifest_value["manifest_sha256"],
        "forecast_bundle_sha256": bundle.input_history_sha256,
        "selected_models": selected_models,
        "grid_available": list(grid_available),
        "diesel_available": list(diesel_available),
        "forecast_history_digests": {
            key: value.input_history_sha256 for key, value in sorted(bundle.results.items())
        },
        "recommendation": dict(recommendation),
        "generic_prediction_handoff": dict(handoff),
        "robust_customer_economics": dispatch_result.get("robust_customer_economics"),
        "decision_scope": dispatch_result.get("decision_scope"),
    }
    try:
        evidence_sha256 = _canonical_digest(evidence)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"optimizer output is not safely serializable for evidence hashing: {exc}") from exc

    return {
        "schema_version": 1,
        "record_type": "islandos_canonical_planning_run",
        "project_id": manifest_value["project_id"],
        "run_id": manifest_value["run_id"],
        "manifest": manifest_value,
        "manifest_sha256": manifest_value["manifest_sha256"],
        "forecast": {
            "bundle_sha256": bundle.input_history_sha256,
            "history_start_utc": bundle.history_start_utc.isoformat(),
            "history_end_utc": bundle.history_end_utc.isoformat(),
            "horizon_hours": horizon,
            "selected_models": selected_models,
            "history_digests": evidence["forecast_history_digests"],
            "grid_available": list(grid_available),
            "diesel_available": list(diesel_available),
            "limitations": list(bundle.planning.limitations),
            "settings": forecast_settings,
        },
        "optimization": dispatch_result,
        "evidence_sha256": evidence_sha256,
        "human_review_required": True,
        "operator_approval": "pending",
        "device_write_authorized": False,
        "command_generated": False,
    }
