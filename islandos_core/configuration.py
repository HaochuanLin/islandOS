"""Validated, UI-independent site assumptions for IslandOS.

These values are operator-provided planning inputs, not measured plant facts.
The model intentionally does not issue equipment commands.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


class ConfigurationError(ValueError):
    """Raised when site configuration is incomplete or physically inconsistent."""


def _finite_nonnegative(name: str, value: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be numeric") from exc
    if not math.isfinite(numeric) or numeric < 0:
        raise ConfigurationError(f"{name} must be finite and >= 0")
    return numeric


@dataclass(frozen=True)
class SiteConfiguration:
    """Minimum generic assumptions shared by the energy/water decision workflow."""

    site_id: str
    water_demand_m3_per_day: float
    ro_capacity_m3_per_day: float
    energy_price_per_kwh: float
    ro_specific_energy_kwh_per_m3: float
    storage_capacity_m3: float = 0.0
    initial_storage_m3: float = 0.0

    def __post_init__(self) -> None:
        if not self.site_id.strip():
            raise ConfigurationError("site_id is required")
        for name in (
            "water_demand_m3_per_day", "ro_capacity_m3_per_day",
            "energy_price_per_kwh", "ro_specific_energy_kwh_per_m3",
            "storage_capacity_m3", "initial_storage_m3",
        ):
            value = _finite_nonnegative(name, getattr(self, name))
            object.__setattr__(self, name, value)
        if self.initial_storage_m3 > self.storage_capacity_m3:
            raise ConfigurationError("initial_storage_m3 cannot exceed storage_capacity_m3")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "SiteConfiguration":
        """Build configuration from JSON/YAML-decoded mappings with clear errors."""
        required = {
            "site_id", "water_demand_m3_per_day", "ro_capacity_m3_per_day",
            "energy_price_per_kwh", "ro_specific_energy_kwh_per_m3",
        }
        missing = sorted(required - set(values))
        if missing:
            raise ConfigurationError("missing required configuration fields: " + ", ".join(missing))
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ConfigurationError("invalid configuration fields: " + ", ".join(unknown))
        try:
            return cls(**{key: values[key] for key in allowed if key in values})
        except TypeError as exc:
            raise ConfigurationError(f"invalid configuration fields: {exc}") from exc

    def to_mapping(self) -> dict[str, str | float]:
        """Return a JSON-compatible representation of the explicit assumptions."""
        return {
            "site_id": self.site_id,
            "water_demand_m3_per_day": self.water_demand_m3_per_day,
            "ro_capacity_m3_per_day": self.ro_capacity_m3_per_day,
            "energy_price_per_kwh": self.energy_price_per_kwh,
            "ro_specific_energy_kwh_per_m3": self.ro_specific_energy_kwh_per_m3,
            "storage_capacity_m3": self.storage_capacity_m3,
            "initial_storage_m3": self.initial_storage_m3,
        }
