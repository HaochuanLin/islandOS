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
            bias_predicted_minus_actual=None,
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
) -> dict:
    """Run the existing offline joint battery/diesel optimizer from generic forecasts.

    The four canonical prediction IDs are explicitly mapped to the established
    dispatch bundle names. This is an offline schedule search, not live control.
    """
    from dataclasses import replace
    from .forecast_optimizer_adapter import optimize_forecasted_resource_schedule

    required = {
        "pv_power_kw": "pv_power",
        "wind_power_kw": "wind_power",
        "load_kw": "essential_load",
        "tariff_per_kwh": "electricity_price",
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
    result["generic_prediction_handoff"] = {
        "canonical_signal_mapping": required,
        "source_signal_ids": sorted(required),
        "forecast_model_versions": {
            key: {"model_id": value.model_id, "model_version": value.model_version}
            for key, value in sorted(results.items()) if key in required
        },
        "source_history_sha256": {
            key: value.input_history_sha256 for key, value in sorted(results.items())
            if key in required
        },
        "target_timestamps_utc": [
            point.timestamp.astimezone(timezone.utc).isoformat()
            for point in next(iter(results.values())).points
        ],
        "mode": "offline_schedule_search",
        "device_write_authorized": False,
    }
    return result
