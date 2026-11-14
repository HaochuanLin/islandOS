"""Bridge device-task schedules into the shared IslandOS energy accounting."""
from __future__ import annotations
from dataclasses import replace
from typing import Sequence

from .energy_system import EnergySystemInputs
from .flexible_tasks import DeviceSchedulingResult


def attach_device_task_schedule(
    inputs: EnergySystemInputs,
    schedule: DeviceSchedulingResult,
) -> EnergySystemInputs:
    """Add scheduled critical/flexible task profiles to existing energy inputs.

    Existing load_kw is the site's base load. Critical task power is added to
    both base and critical load; semi/fully-flexible task power is added to the
    separate flexible_load_kw channel so the energy engine can report shedding
    independently. The caller must build the task scheduler's available-power
    budget after accounting for other fixed site loads.
    """
    horizon = len(inputs.load_kw)
    if horizon == 0 or len(schedule.total_power_kw) != horizon:
        raise ValueError("device task schedule must match the energy input horizon")
    critical = list(schedule.critical_power_kw)
    flexible = [
        sum(item.power_kw[t] for item in schedule.schedules if item.load_class != "critical")
        for t in range(horizon)
    ]
    if len(critical) != horizon:
        raise ValueError("critical task schedule must match the energy input horizon")
    existing_flexible = list(inputs.flexible_load_kw) if inputs.flexible_load_kw is not None else [0.0] * horizon
    existing_critical = list(inputs.critical_load_kw) if inputs.critical_load_kw is not None else list(inputs.load_kw)
    if len(existing_flexible) != horizon or len(existing_critical) != horizon:
        raise ValueError("existing flexible and critical load series must match load_kw")
    if any(value < 0 for value in existing_flexible + existing_critical):
        raise ValueError("existing flexible and critical loads must be non-negative")
    base = [float(inputs.load_kw[t]) + critical[t] for t in range(horizon)]
    critical_total = [float(existing_critical[t]) + critical[t] for t in range(horizon)]
    flexible_total = [float(existing_flexible[t]) + flexible[t] for t in range(horizon)]
    if any(c > b + 1e-9 for c, b in zip(critical_total, base)):
        raise ValueError("combined critical load cannot exceed combined base load")
    return replace(
        inputs,
        load_kw=base,
        critical_load_kw=critical_total,
        flexible_load_kw=flexible_total,
    )
