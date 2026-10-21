"""Common simulation contract for pluggable flexible loads.

This module is an experimental extension point. It does not yet replace the
legacy RO simulator or implement a site-ready plant controller.

All time-series inputs use a constant step size:
- available_power_kw: power available to flexible loads after essential demand
- demand: m3/h for RO water demand, kW_th for ice/cold-store cooling demand
"""
from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

import numpy as np


@dataclass
class LoadSimulationResult:
    """Standardized output shape shared by flexible-load modules."""
    power_used_kw: np.ndarray
    backup_power_kw: np.ndarray
    constraint_violation: np.ndarray
    resource_produced: np.ndarray
    demand_served: np.ndarray
    unmet_demand: np.ndarray
    spill: np.ndarray
    active: np.ndarray
    inventory: np.ndarray  # length T + 1
    run_hours_remaining: int = 0  # RO commitment state carried to the next call
    operating_state: np.ndarray | None = None  # optional per-step equipment-state labels


@runtime_checkable
class FlexibleLoad(Protocol):
    """Minimum common API for a flexible-load simulation plug-in."""
    name: str

    def simulate(
        self,
        available_power_kw: Sequence[float],
        demand: Sequence[float],
        dt_hours: float = 1.0,
    ) -> LoadSimulationResult:
        """Simulate one aligned time series and return standardized metrics."""
        ...


@dataclass
class ROConfig:
    rated_power_kw: float = 400.0
    specific_energy_kwh_m3: float = 3.5
    reservoir_capacity_m3: float = 3000.0
    initial_water_m3: float = 800.0
    dead_storage_m3: float = 200.0
    min_run_hours: int = 2
    start_ratio: float = 0.8
    allow_backup_power: bool = True


class ROWaterLoad:
    """RO desalination plug-in with a simple reservoir water balance.

    In no-backup mode, a start requires an explicit forecast window that covers
    every minimum-run hour at rated power. Without that forecast the module
    conservatively refuses to start when min_run_hours > 1. This is a planning
    simplification, not a substitute for plant interlocks or rolling control.
    """

    name = "ro_desalination"

    def __init__(self, config: ROConfig | None = None):
        self.config = config or ROConfig()

    def simulate(
        self,
        available_power_kw: Sequence[float],
        demand: Sequence[float],
        dt_hours: float = 1.0,
        forecast_available_power_kw: Sequence[Sequence[float]] | None = None,
        initial_run_hours_remaining: int = 0,
    ) -> LoadSimulationResult:
        available = _validate_series(available_power_kw, "available_power_kw")
        water_demand = _validate_series(demand, "demand")
        _validate_dt(dt_hours)
        if len(available) != len(water_demand):
            raise ValueError("available_power_kw and demand must have equal lengths")
        if forecast_available_power_kw is not None and len(forecast_available_power_kw) != len(available):
            raise ValueError("forecast_available_power_kw must have one forecast window per time step")
        if forecast_available_power_kw is not None:
            # Validate every forecast window at the input boundary. In particular,
            # do not let NaN/negative forecast values silently become a failed start.
            for t, window_values in enumerate(forecast_available_power_kw):
                window = np.asarray(window_values, dtype=float)
                if window.ndim != 1 or not np.all(np.isfinite(window)) or np.any(window < 0):
                    raise ValueError(
                        f"forecast_available_power_kw[{t}] must be a finite, non-negative 1D series"
                    )

        c = self.config
        numeric_config = (
            c.rated_power_kw, c.specific_energy_kwh_m3,
            c.reservoir_capacity_m3, c.initial_water_m3,
            c.dead_storage_m3, c.start_ratio,
        )
        if not all(np.isfinite(value) for value in numeric_config):
            raise ValueError("RO configuration values must be finite")
        if c.rated_power_kw <= 0 or c.specific_energy_kwh_m3 <= 0:
            raise ValueError("RO rated power and specific energy must be positive")
        if not isinstance(c.min_run_hours, int) or c.min_run_hours < 1:
            raise ValueError("min_run_hours must be an integer >= 1")
        if (not isinstance(initial_run_hours_remaining, int)
                or initial_run_hours_remaining < 0
                or initial_run_hours_remaining > c.min_run_hours):
            raise ValueError(
                "initial_run_hours_remaining must be an integer within [0, min_run_hours]"
            )
        if not (0 <= c.dead_storage_m3 <= c.initial_water_m3 <= c.reservoir_capacity_m3):
            raise ValueError("Require 0 <= dead storage <= initial water <= reservoir capacity")
        if not np.isfinite(c.start_ratio) or not (0 <= c.start_ratio <= 1):
            raise ValueError("start_ratio must be finite and within [0, 1]")

        n = len(available)
        power = np.zeros(n)
        produced = np.zeros(n)
        served = np.zeros(n)
        unmet = np.zeros(n)
        spill = np.zeros(n)
        active = np.zeros(n, dtype=int)
        backup = np.zeros(n)
        violations = np.zeros(n, dtype=int)
        operating_state = np.full(n, "OFF", dtype=object)
        inventory = np.zeros(n + 1)
        inventory[0] = c.initial_water_m3
        run_remaining = initial_run_hours_remaining

        for t in range(n):
            full = inventory[t] >= c.reservoir_capacity_m3 - 1e-9
            on = False
            if run_remaining > 0:
                on = True
            elif not full and (n - t) >= c.min_run_hours:
                # Do not initiate a minimum-run cycle that cannot finish within
                # this simulation horizon. An already-running cycle may still
                # reach the horizon boundary; that is reported as a limitation.
                if c.allow_backup_power:
                    on = available[t] >= c.start_ratio * c.rated_power_kw
                elif c.min_run_hours == 1:
                    on = available[t] >= c.rated_power_kw
                elif forecast_available_power_kw is not None:
                    window = np.asarray(forecast_available_power_kw[t], dtype=float)
                    expected = min(c.min_run_hours, n - t)
                    on = (
                        len(window) >= c.min_run_hours
                        and np.all(np.isfinite(window))
                        and np.all(window[:c.min_run_hours] >= c.rated_power_kw)
                        and expected == c.min_run_hours
                        and available[t] >= c.rated_power_kw
                    )

            if on:
                power[t] = min(available[t], c.rated_power_kw)
                if c.allow_backup_power:
                    # Total plant demand is rated power; report backup separately.
                    backup[t] = max(0.0, c.rated_power_kw - available[t])
                    power[t] = c.rated_power_kw
                    operating_state[t] = (
                        "RUNNING_WITH_BACKUP" if backup[t] > 1e-9 else "RUNNING"
                    )
                elif power[t] < c.rated_power_kw:
                    # No backup: this is not a feasible operating point. Do not
                    # claim partial desalination production under the simplified
                    # rated-power-only model; preserve the commitment state but
                    # report zero production and an explicit constraint violation.
                    violations[t] = 1
                    power[t] = 0.0
                    operating_state[t] = "COMMITMENT_POWER_SHORTFALL"
                else:
                    operating_state[t] = "RUNNING"
                produced[t] = power[t] * dt_hours / c.specific_energy_kwh_m3
                # active means energized / consuming power, not merely carrying
                # a minimum-run commitment. The latter is represented by
                # operating_state and the run-hours counter.
                active[t] = int(power[t] > 0)
                if run_remaining == 0:
                    run_remaining = c.min_run_hours
                run_remaining -= 1
            else:
                operating_state[t] = "OFF"
                run_remaining = 0

            volume = inventory[t] + produced[t]
            if volume > c.reservoir_capacity_m3:
                spill[t] = volume - c.reservoir_capacity_m3
                volume = c.reservoir_capacity_m3
            demand_volume = water_demand[t] * dt_hours
            deliverable = max(0.0, volume - c.dead_storage_m3)
            served[t] = min(demand_volume, deliverable)
            unmet[t] = demand_volume - served[t]
            inventory[t + 1] = volume - served[t]

        return LoadSimulationResult(
            power, backup, violations, produced, served, unmet, spill, active,
            inventory, run_hours_remaining=run_remaining,
            operating_state=operating_state,
        )


@dataclass
class IceStorageConfig:
    """Simplified ice/cold-storage parameters."""
    rated_power_kw: float = 100.0
    coefficient_of_performance: float = 2.5
    storage_capacity_kwh_th: float = 1200.0
    initial_storage_kwh_th: float = 0.0


class IceStorageLoad:
    """Thermal storage plug-in for fisheries/cooling demand.

    Surplus electricity drives a chiller; cooling energy is stored as a thermal
    inventory and later serves demand. It is not converted back to electricity.
    This first model omits thermal leakage, icing curves, compressor cycling,
    temperature-dependent COP, and product-quality constraints.
    """

    name = "ice_cold_storage"

    def __init__(self, config: IceStorageConfig | None = None):
        self.config = config or IceStorageConfig()

    def simulate(
        self,
        available_power_kw: Sequence[float],
        demand: Sequence[float],
        dt_hours: float = 1.0,
    ) -> LoadSimulationResult:
        available = _validate_series(available_power_kw, "available_power_kw")
        cooling_demand_kw_th = _validate_series(demand, "demand")
        _validate_dt(dt_hours)
        if len(available) != len(cooling_demand_kw_th):
            raise ValueError("available_power_kw and demand must have equal lengths")

        c = self.config
        numeric_config = (
            c.rated_power_kw, c.coefficient_of_performance,
            c.storage_capacity_kwh_th, c.initial_storage_kwh_th,
        )
        if not all(np.isfinite(value) for value in numeric_config):
            raise ValueError("Ice-storage configuration values must be finite")
        if c.rated_power_kw <= 0 or c.coefficient_of_performance <= 0:
            raise ValueError("Chiller rated power and COP must be positive")
        if c.storage_capacity_kwh_th < 0 or not (
            0 <= c.initial_storage_kwh_th <= c.storage_capacity_kwh_th
        ):
            raise ValueError("Initial thermal storage must be within [0, capacity]")

        n = len(available)
        power = np.zeros(n)
        produced = np.zeros(n)
        served = np.zeros(n)
        unmet = np.zeros(n)
        spill = np.zeros(n)
        active = np.zeros(n, dtype=int)
        backup = np.zeros(n)
        violations = np.zeros(n, dtype=int)
        inventory = np.zeros(n + 1)
        inventory[0] = c.initial_storage_kwh_th

        for t in range(n):
            room = max(0.0, c.storage_capacity_kwh_th - inventory[t])
            power_limit_for_storage = room / (c.coefficient_of_performance * dt_hours) if dt_hours else 0.0
            power[t] = min(max(0.0, available[t]), c.rated_power_kw, power_limit_for_storage)
            produced[t] = power[t] * dt_hours * c.coefficient_of_performance
            active[t] = int(power[t] > 0)
            thermal_available = inventory[t] + produced[t]
            demand_energy = cooling_demand_kw_th[t] * dt_hours
            served[t] = min(demand_energy, thermal_available)
            unmet[t] = demand_energy - served[t]
            inventory[t + 1] = thermal_available - served[t]

        return LoadSimulationResult(power, backup, violations, produced, served, unmet, spill, active, inventory)


def _validate_series(values: Sequence[float], name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be a one-dimensional series")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    if np.any(arr < 0):
        raise ValueError(f"{name} must be non-negative")
    return arr


def _validate_dt(dt_hours: float) -> None:
    if not np.isfinite(dt_hours) or dt_hours <= 0:
        raise ValueError("dt_hours must be finite and > 0")
