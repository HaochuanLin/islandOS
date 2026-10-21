"""Shared electricity-budget dispatch for IslandOS flexible-load plug-ins.

Loads are dispatched sequentially in the explicit order supplied by the caller.
Each load receives only the renewable surplus left by higher-priority loads.
Backup electricity is reported separately and is never subtracted from the
renewable-surplus budget. This is a transparent baseline dispatcher, not an
optimizer and not a grid/diesel/battery commitment model.
"""
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from flexible_loads import FlexibleLoad, LoadSimulationResult, ROWaterLoad


@dataclass
class DispatchResult:
    """Aggregate results from one shared-budget dispatch run."""
    initial_available_power_kw: np.ndarray
    remaining_power_kw: np.ndarray
    renewable_power_used_kw: np.ndarray
    backup_power_kw: np.ndarray
    loads: Mapping[str, LoadSimulationResult]


def dispatch_flexible_loads(
    available_power_kw: Sequence[float],
    requests: Sequence[tuple[FlexibleLoad, Sequence[float]]],
    dt_hours: float = 1.0,
    initial_ro_run_hours_remaining: int = 0,
) -> DispatchResult:
    """Dispatch (load, demand_series) requests against one shared budget.

    The request order is the priority order. For RO, each start forecast is
    built from the residual surplus after all earlier-priority loads have
    been scheduled over the full horizon. This is still perfect look-ahead
    over the supplied series, not an operational forecast.

    A load's power_used_kw is its total plant demand; any backup_power_kw
    is excluded from renewable draw. The dispatcher checks that each module's
    renewable draw fits its residual budget, preventing double allocation.
    """
    available = _series(available_power_kw, "available_power_kw")
    if not np.isfinite(dt_hours) or dt_hours <= 0:
        raise ValueError("dt_hours must be finite and > 0")

    residual = available.copy()
    total_renewable = np.zeros_like(available)
    total_backup = np.zeros_like(available)
    results: dict[str, LoadSimulationResult] = {}
    names: set[str] = set()

    for load, demand in requests:
        name = getattr(load, "name", None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Every load must have a non-empty name")
        if name in names:
            raise ValueError(f"Duplicate load name: {name}")
        names.add(name)

        demand_array = _series(demand, f"{name}.demand")
        if len(demand_array) != len(available):
            raise ValueError(f"{name}.demand must match available_power_kw length")

        if isinstance(load, ROWaterLoad):
            cfg = load.config
            forecast = [
                residual[t:min(len(residual), t + cfg.min_run_hours)].tolist()
                for t in range(len(residual))
            ]
            result = load.simulate(
                residual, demand_array, dt_hours=dt_hours,
                forecast_available_power_kw=forecast,
                initial_run_hours_remaining=initial_ro_run_hours_remaining,
            )
        else:
            result = load.simulate(residual, demand_array, dt_hours=dt_hours)

        backup = np.asarray(result.backup_power_kw, dtype=float)
        total_power = np.asarray(result.power_used_kw, dtype=float)
        renewable_draw = total_power - backup
        if (backup.shape != residual.shape or total_power.shape != residual.shape
                or not np.all(np.isfinite(backup))
                or not np.all(np.isfinite(total_power))
                or np.any(backup < -1e-8)
                or np.any(renewable_draw < -1e-8)):
            raise ValueError(f"{name} returned invalid power accounting")

        renewable_draw = np.maximum(0.0, renewable_draw)
        if np.any(renewable_draw > residual + 1e-7):
            raise RuntimeError(
                f"{name} allocated more renewable power than its residual budget"
            )

        results[name] = result
        residual = np.maximum(0.0, residual - renewable_draw)
        total_renewable += renewable_draw
        total_backup += backup

    if not np.allclose(available, total_renewable + residual, atol=1e-7, rtol=0):
        raise RuntimeError("Shared renewable-power budget failed conservation check")

    return DispatchResult(
        initial_available_power_kw=available,
        remaining_power_kw=residual,
        renewable_power_used_kw=total_renewable,
        backup_power_kw=total_backup,
        loads=results,
    )


def _series(values: Sequence[float], name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be a one-dimensional series")
    if not np.all(np.isfinite(arr)) or np.any(arr < 0):
        raise ValueError(f"{name} must contain only finite, non-negative values")
    return arr
