"""Bridge the generic prediction engine into the existing dispatch forecast contract.

This is Stage D's first integration seam. It preserves per-signal model and
history provenance while refusing misaligned horizons or mixed history windows.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping

from .forecast_engine import (
    ForecastBundle,
    ForecastMetrics,
    ForecastPoint as DispatchForecastPoint,
    SignalForecast,
)
from .prediction_engine import PredictionResult


def build_dispatch_forecast_bundle(
    results: Mapping[str, PredictionResult],
    *,
    history_start_utc: datetime,
    history_end_utc: datetime,
) -> ForecastBundle:
    """Convert one or more generic prediction results into a planner bundle."""
    if not isinstance(results, Mapping) or not results:
        raise ValueError("at least one named PredictionResult is required")
    for label, stamp in (("history_start_utc", history_start_utc),
                         ("history_end_utc", history_end_utc)):
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError(f"{label} must be timezone-aware")
    start = history_start_utc.astimezone(timezone.utc)
    end = history_end_utc.astimezone(timezone.utc)
    if end < start:
        raise ValueError("history_end_utc must not precede history_start_utc")

    forecasts = {}
    digests = {}
    common_targets = None
    for signal_name, result in sorted(results.items()):
        if not isinstance(signal_name, str) or not signal_name.strip():
            raise ValueError("forecast mapping keys must be non-empty signal names")
        if not isinstance(result, PredictionResult):
            raise TypeError(f"{signal_name} must map to a PredictionResult")
        if result.signal_id != signal_name:
            raise ValueError(f"forecast key does not match result signal_id: {signal_name}")
        digest = result.input_history_sha256
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"{signal_name} has an invalid input history SHA-256")
        targets = tuple(point.timestamp.astimezone(timezone.utc) for point in result.points)
        if not targets:
            raise ValueError(f"{signal_name} forecast horizon is empty")
        if common_targets is None:
            common_targets = targets
        elif targets != common_targets:
            raise ValueError("all resource forecasts must share identical target timestamps")
        points = tuple(
            DispatchForecastPoint(
                timestamp=point.timestamp,
                predicted=point.predicted_value,
                lower_bound=point.lower_bound,
                upper_bound=point.upper_bound,
            )
            for point in result.points
        )
        metrics = ForecastMetrics(
            samples=result.backtest.samples,
            mae=result.backtest.mae,
            rmse=result.backtest.rmse,
            bias_predicted_minus_actual=result.backtest.bias_predicted_minus_actual,
        )
        forecasts[signal_name] = SignalForecast(
            signal_name=signal_name,
            unit=result.unit,
            model_id=result.model_id,
            model_version=result.model_version,
            points=points,
            holdout_metrics=metrics,
            baseline_metrics=MappingProxyType({}),
            selected_model_beats_baseline=False,
            uncertainty_method=result.interval_method,
            residual_abs_error_p90=max(
                (point.upper_bound - point.predicted_value for point in result.points),
                default=0.0,
            ),
        )
        digests[signal_name] = digest

    canonical = json.dumps(digests, sort_keys=True, separators=(",", ":"))
    aggregate_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ForecastBundle(
        input_history_sha256=aggregate_digest,
        history_start_utc=start,
        history_end_utc=end,
        forecasts=MappingProxyType(forecasts),
    )


def build_resource_coordination_inputs(
    results: Mapping[str, PredictionResult],
    *,
    history_start_utc: datetime,
    history_end_utc: datetime,
    grid_available,
    price_unit: str,
    diesel_available=None,
    grid_export_price_per_kwh=None,
    grid_export_available=None,
):
    """Hand generic PV/wind/load/tariff predictions to the physical dispatch model.

    Required input keys are the canonical onboarding signal IDs:
    pv_power_kw, wind_power_kw, load_kw and tariff_per_kwh. These are explicitly
    mapped to the dispatch adapter's established signal names. All forecast
    horizons must align; no unit conversion or missing-signal substitution occurs.
    """
    required = {
        "pv_power_kw": ("pv_power", "kW"),
        "wind_power_kw": ("wind_power", "kW"),
        "load_kw": ("essential_load", "kW"),
        "tariff_per_kwh": ("electricity_price", price_unit),
    }
    if not isinstance(results, Mapping):
        raise ValueError("results must be a mapping of canonical signal IDs to PredictionResult")
    missing = sorted(set(required) - set(results))
    if missing:
        raise ValueError("missing required resource forecasts: " + ", ".join(missing))
    if not isinstance(price_unit, str) or not price_unit.strip():
        raise ValueError("price_unit must be an explicit non-empty unit")
    from dataclasses import replace
    from .forecast_optimizer_adapter import build_coordination_inputs

    mapped = {}
    for source_id, (dispatch_id, expected_unit) in required.items():
        result = results[source_id]
        if not isinstance(result, PredictionResult):
            raise TypeError(f"{source_id} must be a PredictionResult")
        if result.signal_id != source_id:
            raise ValueError(f"result signal_id must match canonical key {source_id}")
        if result.unit != expected_unit:
            raise ValueError(f"{source_id} must use {expected_unit}; got {result.unit}")
        # Keep the original history digest: it fingerprints the source signal ID
        # and observations, while the explicit mapping documents dispatch naming.
        mapped[dispatch_id] = replace(result, signal_id=dispatch_id)

    bundle = build_dispatch_forecast_bundle(
        mapped,
        history_start_utc=history_start_utc,
        history_end_utc=history_end_utc,
    )
    return build_coordination_inputs(
        bundle,
        grid_available=grid_available,
        price_unit=price_unit,
        diesel_available=diesel_available,
        grid_export_price_per_kwh=grid_export_price_per_kwh,
        grid_export_available=grid_export_available,
    )


def optimize_prediction_resource_schedule(
    results: Mapping[str, PredictionResult],
    config,
    *,
    history_start_utc: datetime,
    history_end_utc: datetime,
    grid_available,
    diesel_available,
    price_unit: str,
    population_size: int = 16,
    generations: int = 8,
    seed: int = 20261113,
    max_unmet_load_kwh: float | None = None,
    max_critical_unmet_load_kwh: float | None = None,
    terminal_battery_soc_min: float | None = None,
    water_service=None,
    water_schedule_mode: str = "just_in_time",
    water_lookahead_hours: int = 6,
) -> dict:
    """Run offline joint battery/diesel/flexible-load optimization from site forecasts.

    Optional water demand is converted to a reserve-constrained RO electrical
    load before physical optimization. The default just-in-time policy can be
    replaced by an explicit tariff-look-ahead RO heuristic; neither mode is a
    globally optimal joint water/energy schedule.
    """
    from dataclasses import replace
    import hashlib
    import json
    from .forecast_optimizer_adapter import optimize_forecasted_resource_schedule
    from .water_resource_adapter import WaterEnergyLoad, WaterServiceSpec, build_ro_energy_load
    from .water_dispatch import build_price_aware_ro_schedule

    if water_schedule_mode not in {"just_in_time", "price_aware", "auto"}:
        raise ValueError("water_schedule_mode must be 'just_in_time', 'price_aware', or 'auto'")
    if isinstance(water_lookahead_hours, bool) or not isinstance(water_lookahead_hours, int) or water_lookahead_hours < 1:
        raise ValueError("water_lookahead_hours must be a positive integer")

    if water_schedule_mode == "auto":
        if not isinstance(results, Mapping) or "water_demand_m3_per_hour" not in results:
            raise ValueError("automatic water-policy selection requires a water-demand forecast")
        if not isinstance(water_service, WaterServiceSpec):
            raise ValueError("automatic water-policy selection requires a WaterServiceSpec")
        candidates = {}
        failures = {}
        for mode in ("just_in_time", "price_aware"):
            try:
                candidates[mode] = optimize_prediction_resource_schedule(
                    results, config,
                    history_start_utc=history_start_utc,
                    history_end_utc=history_end_utc,
                    grid_available=grid_available,
                    diesel_available=diesel_available,
                    price_unit=price_unit,
                    population_size=population_size,
                    generations=generations,
                    seed=seed,
                    max_unmet_load_kwh=max_unmet_load_kwh,
                    max_critical_unmet_load_kwh=max_critical_unmet_load_kwh,
                    terminal_battery_soc_min=terminal_battery_soc_min,
                    water_service=water_service,
                    water_schedule_mode=mode,
                    water_lookahead_hours=water_lookahead_hours,
                )
            except (ValueError, TypeError) as exc:
                failures[mode] = str(exc)

        if not candidates:
            details = "; ".join(f"{mode}: {reason}" for mode, reason in sorted(failures.items()))
            raise ValueError("no water-production policy produced a feasible resource schedule: " + details)

        def coordination_rank(item):
            mode, candidate = item
            scenario_rows = candidate["recommendation"]["scenario_results"].values()
            worst_critical = max(
                (float(row["summary"].get("critical_unmet_load_kwh", 0.0)) for row in scenario_rows),
                default=0.0,
            )
            scenario_rows = candidate["recommendation"]["scenario_results"].values()
            worst_unmet = max(
                (float(row["summary"].get("unmet_load_kwh", 0.0)) for row in scenario_rows),
                default=0.0,
            )
            objectives = candidate["recommendation"]["objectives"]
            return (
                worst_critical,
                worst_unmet,
                float(objectives["estimated_energy_cost"]),
                float(objectives["renewable_curtailed_kwh"]),
                float(objectives["battery_throughput_kwh"]),
                mode,
            )

        selected_mode, selected = min(candidates.items(), key=coordination_rank)
        comparisons = {}
        for mode in ("just_in_time", "price_aware"):
            if mode in candidates:
                candidate = candidates[mode]
                objectives = candidate["recommendation"]["objectives"]
                comparisons[mode] = {
                    "feasible": True,
                    "worst_case_objectives": dict(objectives),
                    "water_energy_cost_estimate": candidate["water_service"]["estimated_ro_energy_cost"],
                    "production_policy": candidate["water_service"]["production_policy"],
                }
            else:
                comparisons[mode] = {
                    "feasible": False,
                    "failure_reason": failures[mode],
                }
        selected["water_policy_comparison"] = {
            "selected_mode": selected_mode,
            "selection_order": [
                "minimum worst-case critical unmet energy",
                "minimum worst-case total unmet energy",
                "minimum worst-case estimated energy cost",
                "minimum worst-case renewable curtailment",
                "minimum worst-case battery throughput",
            ],
            "candidates": comparisons,
            "method_scope": (
                "compares two explicit RO production heuristics, each followed by "
                "the same seeded multi-resource optimizer across the same forecast "
                "stress scenarios; this is not a globally joint water-energy optimum"
            ),
            "scenario_probabilities_assigned": False,
            "device_write_authorized": False,
        }
        selected["water_service"]["selected_schedule_mode"] = selected_mode
        return selected

    required = {
        "pv_power_kw": "pv_power",
        "wind_power_kw": "wind_power",
        "load_kw": "essential_load",
        "tariff_per_kwh": "electricity_price",
    }
    optional = {
        "flexible_load_kw": "flexible_load",
        "critical_load_kw": "critical_load",
    }
    if not isinstance(results, Mapping):
        raise ValueError("results must be a mapping of canonical signal IDs to PredictionResult")
    missing = sorted(set(required) - set(results))
    if missing:
        raise ValueError("missing required resource forecasts: " + ", ".join(missing))
    if not isinstance(price_unit, str) or not price_unit.strip():
        raise ValueError("price_unit must be an explicit non-empty unit")

    mapped = {}
    for source_id, dispatch_id in required.items():
        result = results[source_id]
        if not isinstance(result, PredictionResult):
            raise TypeError(f"{source_id} must be a PredictionResult")
        if result.signal_id != source_id:
            raise ValueError(f"result signal_id must match canonical key {source_id}")
        expected_unit = price_unit if source_id == "tariff_per_kwh" else "kW"
        if result.unit != expected_unit:
            raise ValueError(f"{source_id} must use {expected_unit}; got {result.unit}")
        mapped[dispatch_id] = replace(result, signal_id=dispatch_id)

    for source_id, dispatch_id in optional.items():
        if source_id not in results:
            continue
        result = results[source_id]
        if not isinstance(result, PredictionResult):
            raise TypeError(f"{source_id} must be a PredictionResult")
        if result.signal_id != source_id:
            raise ValueError(f"result signal_id must match canonical key {source_id}")
        if result.unit != "kW":
            raise ValueError(f"{source_id} must use kW; got {result.unit}")
        mapped[dispatch_id] = replace(result, signal_id=dispatch_id)

    water_result = results.get("water_demand_m3_per_hour")
    water_load = None
    if water_result is not None:
        if not isinstance(water_result, PredictionResult):
            raise TypeError("water_demand_m3_per_hour must be a PredictionResult")
        if water_result.signal_id != "water_demand_m3_per_hour":
            raise ValueError("water demand result signal_id must match its canonical key")
        if water_result.unit != "m3/h":
            raise ValueError("water_demand_m3_per_hour must use m3/h")
        if not isinstance(water_service, WaterServiceSpec):
            raise ValueError("water_service must be supplied when a water-demand forecast is present")
        load_result = results["load_kw"]
        load_targets = tuple(point.timestamp for point in load_result.points)
        water_targets = tuple(point.timestamp for point in water_result.points)
        if water_targets != load_targets:
            raise ValueError("water-demand and electrical-load forecast timestamps must align exactly")
        # Use the empirical upper planning bound for water service feasibility.
        water_demand_upper = [point.upper_bound for point in water_result.points]
        if water_schedule_mode == "price_aware":
            tariff_result = results["tariff_per_kwh"]
            if tuple(point.timestamp for point in tariff_result.points) != water_targets:
                raise ValueError("tariff and water-demand forecast timestamps must align exactly")
            schedule = build_price_aware_ro_schedule(
                water_demand_upper,
                [point.predicted_value for point in tariff_result.points],
                spec=water_service,
                lookahead_hours=water_lookahead_hours,
                dt_hours=config.dt_hours,
            )
            water_load = WaterEnergyLoad(
                production_m3=schedule["production_m3"],
                inventory_after_demand_m3=schedule["inventory_end_m3"],
                ro_power_kw=schedule["ro_power_kw"],
                total_demand_m3=schedule["total_demand_m3"],
                total_production_m3=schedule["total_production_m3"],
                specific_energy_kwh_per_m3=water_service.specific_energy_kwh_per_m3,
                service_feasible=schedule["service_feasible"],
            )
            water_production_policy = schedule["method"]
            water_estimated_energy_cost = schedule["estimated_ro_energy_cost"]
        else:
            water_load = build_ro_energy_load(
                water_demand_upper,
                spec=water_service,
                dt_hours=config.dt_hours,
            )
            water_production_policy = "reserve-constrained just-in-time"
            water_estimated_energy_cost = None
        combined_points = tuple(
            replace(
                point,
                predicted_value=point.predicted_value + ro_kw,
                lower_bound=point.lower_bound + ro_kw,
                upper_bound=point.upper_bound + ro_kw,
            )
            for point, ro_kw in zip(load_result.points, water_load.ro_power_kw)
        )
        combined_digest = hashlib.sha256(json.dumps({
            "electrical_load_history_sha256": load_result.input_history_sha256,
            "water_demand_history_sha256": water_result.input_history_sha256,
            "water_service_spec": {
                "specific_energy_kwh_per_m3": water_service.specific_energy_kwh_per_m3,
                "ro_capacity_m3_per_hour": water_service.ro_capacity_m3_per_hour,
                "tank_capacity_m3": water_service.tank_capacity_m3,
                "initial_inventory_m3": water_service.initial_inventory_m3,
                "reserve_m3": water_service.reserve_m3,
            },
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        mapped["essential_load"] = replace(
            mapped["essential_load"],
            input_history_sha256=combined_digest,
            points=combined_points,
        )
        if "critical_load" in mapped:
            mapped["critical_load"] = replace(
                mapped["critical_load"],
                points=tuple(
                    replace(point, predicted_value=point.predicted_value + ro_kw,
                            lower_bound=point.lower_bound + ro_kw,
                            upper_bound=point.upper_bound + ro_kw)
                    for point, ro_kw in zip(mapped["critical_load"].points, water_load.ro_power_kw)
                ),
            )
    elif water_service is not None:
        raise ValueError("water_service was supplied without a water-demand forecast")

    bundle = build_dispatch_forecast_bundle(
        mapped,
        history_start_utc=history_start_utc,
        history_end_utc=history_end_utc,
    )
    result = optimize_forecasted_resource_schedule(
        bundle,
        config,
        grid_available=grid_available,
        diesel_available=diesel_available,
        price_unit=price_unit,
        population_size=population_size,
        generations=generations,
        seed=seed,
        max_unmet_load_kwh=max_unmet_load_kwh,
        max_critical_unmet_load_kwh=max_critical_unmet_load_kwh,
        terminal_battery_soc_min=terminal_battery_soc_min,
    )
    source_ids = sorted(results)
    result["generic_prediction_handoff"] = {
        "canonical_signal_mapping": {**required, **optional},
        "source_signal_ids": source_ids,
        "forecast_model_versions": {
            key: {"model_id": value.model_id, "model_version": value.model_version}
            for key, value in sorted(results.items())
        },
        "source_history_sha256": {
            key: value.input_history_sha256 for key, value in sorted(results.items())
        },
        "target_timestamps_utc": [
            point.timestamp.astimezone(timezone.utc).isoformat()
            for point in results["pv_power_kw"].points
        ],
        "mode": "offline_schedule_search",
        "device_write_authorized": False,
    }
    if water_result is not None and water_load is not None:
        result["water_service"] = {
            "demand_forecast_m3_per_hour": [
                point.predicted_value for point in water_result.points
            ],
            "planning_upper_bound_m3_per_hour": [
                point.upper_bound for point in water_result.points
            ],
            "ro_production_m3": list(water_load.production_m3),
            "tank_inventory_after_demand_m3": list(water_load.inventory_after_demand_m3),
            "ro_power_kw_added_to_essential_load": list(water_load.ro_power_kw),
            "total_demand_upper_bound_m3": water_load.total_demand_m3,
            "total_ro_production_m3": water_load.total_production_m3,
            "specific_energy_kwh_per_m3": water_load.specific_energy_kwh_per_m3,
            "service_feasible": water_load.service_feasible,
            "production_policy": water_production_policy,
            "estimated_ro_energy_cost": water_estimated_energy_cost,
            "electricity_price_forecast_used": water_schedule_mode == "price_aware",
            "lookahead_hours": water_lookahead_hours if water_schedule_mode == "price_aware" else None,
            "device_write_authorized": False,
        }
    return result
