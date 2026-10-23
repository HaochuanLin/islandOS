"Explainable, read-only screening recommendation for RO operation.

This is a one-step heuristic for demonstrations, not an optimizer, controller,
or substitute for plant operating procedures. Inputs must already be validated.
"
from __future__ import annotations

from dataclasses import dataclass

from .configuration import SiteConfiguration
from .signals import SignalReading


@dataclass(frozen=True)
class ScreeningRecommendation:
    """A human-reviewable suggestion; never an equipment command."""

    action: str
    reason: str
    estimated_full_load_power_kw: float
    water_inventory_m3: float
    target_inventory_m3: float
    renewable_surplus_kw: float
    assumptions: tuple[str, ...]


def recommend_ro_screening(
    config: SiteConfiguration,
    *,
    renewable_surplus: SignalReading,
    water_inventory: SignalReading,
) -> ScreeningRecommendation:
    """Return a conservative screening suggestion from two validated readings.

    action is either consider_run_on_surplus or hold_and_review. No grid/backup
    operation, startup sequence, minimum run-time, forecast, tank dynamics, or
    equipment interlocks are modelled here.
    """
    expected = (
        (renewable_surplus, "renewable_surplus_kw", "kW"),
        (water_inventory, "water_inventory_m3", "m3"),
    )
    for reading, signal_id, unit in expected:
        if reading.signal_id != signal_id:
            raise ValueError(f"expected signal_id {signal_id!r}, got {reading.signal_id!r}")
        if reading.unit != unit:
            raise ValueError(f"expected unit {unit!r} for {signal_id}, got {reading.unit!r}")
        if reading.value < 0:
            raise ValueError(f"{signal_id} must be >= 0")
    if config.ro_capacity_m3_per_day <= 0 or config.ro_specific_energy_kwh_per_m3 <= 0:
        raise ValueError("RO capacity and specific energy must both be > 0 for screening")
    if water_inventory.value > config.storage_capacity_m3:
        raise ValueError("water inventory exceeds configured storage capacity")

    full_load_power = config.ro_capacity_m3_per_day * config.ro_specific_energy_kwh_per_m3 / 24.0
    target_inventory = min(config.storage_capacity_m3, config.water_demand_m3_per_day * 0.25)
    assumptions = (
        "RO capacity is treated as a 24-hour equivalent for estimating full-load power.",
        "A screening target of 25% of daily water demand is used, capped by tank capacity.",
        "Only current renewable surplus is considered; no forecast or essential-load recheck is performed.",
        "This is advice for human review only and does not issue commands.",
    )
    if water_inventory.value < target_inventory and renewable_surplus.value >= full_load_power:
        action = "consider_run_on_surplus"
        reason = (
            f"Water inventory ({water_inventory.value:.2f} m3) is below the screening "
            f"target ({target_inventory:.2f} m3), and renewable surplus "
            f"({renewable_surplus.value:.2f} kW) meets the estimated full-load "
            f"power ({full_load_power:.2f} kW). Review site constraints before acting."
        )
    else:
        action = "hold_and_review"
        if water_inventory.value >= target_inventory:
            reason = (
                f"Water inventory ({water_inventory.value:.2f} m3) meets or exceeds "
                f"the screening target ({target_inventory:.2f} m3); this heuristic "
                "does not recommend starting RO from these inputs."
            )
        else:
            reason = (
                f"Water inventory ({water_inventory.value:.2f} m3) is below the "
                f"screening target ({target_inventory:.2f} m3), but renewable surplus "
                f"({renewable_surplus.value:.2f} kW) is below estimated full-load "
                f"power ({full_load_power:.2f} kW). Review other approved operating options."
            )
    return ScreeningRecommendation(
        action=action,
        reason=reason,
        estimated_full_load_power_kw=round(full_load_power, 6),
        water_inventory_m3=water_inventory.value,
        target_inventory_m3=round(target_inventory, 6),
        renewable_surplus_kw=renewable_surplus.value,
        assumptions=assumptions,
    )
