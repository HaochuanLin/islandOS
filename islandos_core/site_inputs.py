"""Site-level physical assumptions, and the one place a page turns them into a config.

Three surfaces describe a site: the customer dashboard (05), the joint resource optimizer
(06) and the device flexibility planner (09). Each used to build its own
``EnergySystemConfig`` from its own sidebar values, so nothing guaranteed that two pages
describing "the site" described the same site.

This module is the single source for that construction. It holds:

* the vocabulary: every field that describes the site's physical and energy conditions,
  with no page-specific or run-specific parameter mixed in;
* the dashboard / joint-optimizer defaults, as named constants a page must pass
  explicitly — there are no implicit defaults on ``SiteAssumptions``;
* ``SiteAssumptions.to_energy_system_config()``, the only function that may assemble an
  ``EnergySystemConfig`` from site inputs.

What it deliberately does not hold: per-page simulation settings (objective weights, the
dashboard's synthetic load and tariff scalars, the optimizer's search population and
generations, the planner's device tasks and price vector) and per-run settings
(investment life, discount rate, escalation, availability flags). Those stay on their
pages, because they describe a *task*, not a site.

The device flexibility planner describes a deliberately smaller demo site than the other
two pages (12 kW PV, 4.5 kW wind, 20 kW grid, 12 kWh / 4 kW battery, 5 kW diesel). That
difference is data, not drift: it passes its own assumptions here instead of silently
inheriting another page's site.

No Streamlit import, no session state, no page function: a non-Streamlit front end can
call exactly the same code.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any

from .energy_system import BatterySpec, DieselSpec, EnergySystemConfig

# State-of-charge bounds are physical constants of the battery model, shared by every
# page that describes a battery; they are named so a page never re-types the literals.
BATTERY_INITIAL_SOC = 0.60
BATTERY_MIN_SOC = 0.10
BATTERY_MAX_SOC = 0.95

# The site the customer dashboard and the joint optimizer describe by default. These
# are the values both pages already shipped; they live here so the two cannot drift.
DEFAULT_SITE = {
    "pv_rated_kw": 40.0,
    "wind_rated_kw": 20.0,
    "grid_import_limit_kw": 100.0,
    "battery_capacity_kwh": 80.0,
    "battery_power_kw": 20.0,
    "battery_initial_soc": BATTERY_INITIAL_SOC,
    "battery_min_soc": BATTERY_MIN_SOC,
    "battery_max_soc": BATTERY_MAX_SOC,
    "diesel_rated_kw": 0.0,
    "diesel_variable_cost_per_kwh": 0.0,
}

# The device flexibility planner's much smaller demo site, kept as a named set so the
# difference is declared rather than accidental.
DEVICE_PLANNER_DEMO_SITE = {
    "pv_rated_kw": 12.0,
    "wind_rated_kw": 4.5,
    "grid_import_limit_kw": 20.0,
    "battery_capacity_kwh": 12.0,
    "battery_power_kw": 4.0,
    "battery_initial_soc": BATTERY_INITIAL_SOC,
    "battery_min_soc": BATTERY_MIN_SOC,
    "battery_max_soc": BATTERY_MAX_SOC,
    "diesel_rated_kw": 5.0,
    "diesel_variable_cost_per_kwh": 0.35,
}

SITE_FIELDS = tuple(DEFAULT_SITE)


def _number(value: object, name: str, *, minimum: float = 0.0) -> float:
    """A finite number at or above `minimum`; bools are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    if number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return number


@dataclass(frozen=True)
class SiteAssumptions:
    """The site's physical conditions. Every field is required on purpose.

    A default here would be a silent assumption a page could inherit by forgetting an
    argument, so there are none: a caller states all ten, or it does not get a config.
    """

    pv_rated_kw: float
    wind_rated_kw: float
    grid_import_limit_kw: float
    battery_capacity_kwh: float
    battery_power_kw: float
    battery_initial_soc: float
    battery_min_soc: float
    battery_max_soc: float
    diesel_rated_kw: float
    diesel_variable_cost_per_kwh: float

    def __post_init__(self) -> None:
        for name in (
            "pv_rated_kw",
            "wind_rated_kw",
            "grid_import_limit_kw",
            "battery_capacity_kwh",
            "battery_power_kw",
            "diesel_rated_kw",
            "diesel_variable_cost_per_kwh",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), name))
        for name in ("battery_initial_soc", "battery_min_soc", "battery_max_soc"):
            object.__setattr__(self, name, _number(getattr(self, name), name, minimum=0.0))
        if not 0.0 <= self.battery_min_soc < self.battery_max_soc <= 1.0:
            raise ValueError(
                "battery state-of-charge bounds must satisfy 0 <= min_soc < max_soc <= 1"
            )
        if not self.battery_min_soc <= self.battery_initial_soc <= self.battery_max_soc:
            raise ValueError("battery_initial_soc must lie between min_soc and max_soc")

    @property
    def has_battery(self) -> bool:
        """A battery exists only when both its energy and power capacity are positive."""
        return self.battery_capacity_kwh > 0.0 and self.battery_power_kw > 0.0

    @property
    def has_diesel(self) -> bool:
        return self.diesel_rated_kw > 0.0

    def battery_spec(self) -> BatterySpec | None:
        if not self.has_battery:
            return None
        return BatterySpec(
            capacity_kwh=self.battery_capacity_kwh,
            max_charge_kw=self.battery_power_kw,
            max_discharge_kw=self.battery_power_kw,
            initial_soc=self.battery_initial_soc,
            min_soc=self.battery_min_soc,
            max_soc=self.battery_max_soc,
        )

    def diesel_spec(self) -> DieselSpec | None:
        if not self.has_diesel:
            return None
        return DieselSpec(
            rated_power_kw=self.diesel_rated_kw,
            variable_cost_per_kwh=self.diesel_variable_cost_per_kwh,
            ramp_up_kw_per_hour=self.diesel_rated_kw,
        )

    def to_energy_system_config(self) -> EnergySystemConfig:
        """The one construction point for a site's ``EnergySystemConfig``."""
        return EnergySystemConfig(
            pv_rated_kw=self.pv_rated_kw,
            wind_rated_kw=self.wind_rated_kw,
            grid_import_limit_kw=self.grid_import_limit_kw,
            battery=self.battery_spec(),
            diesel=self.diesel_spec(),
        )

    def describe(self) -> dict[str, Any]:
        """Every shared field, in declaration order, as plain numbers."""
        return asdict(self)

    def digest(self) -> str:
        """SHA-256 over all ten shared fields, never a hand-picked subset."""
        payload = json.dumps(self.describe(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def with_overrides(self, **overrides: float) -> "SiteAssumptions":
        """A copy with named site fields replaced; unknown field names are refused."""
        unknown = sorted(set(overrides) - set(SITE_FIELDS))
        if unknown:
            raise ValueError(f"unknown site fields: {', '.join(unknown)}")
        merged = self.describe()
        merged.update(overrides)
        return SiteAssumptions(**merged)


def default_site() -> SiteAssumptions:
    """The dashboard / joint-optimizer site, assembled from ``DEFAULT_SITE``."""
    return SiteAssumptions(**DEFAULT_SITE)


def device_planner_demo_site() -> SiteAssumptions:
    """The deliberately smaller site the device flexibility planner replays."""
    return SiteAssumptions(**DEVICE_PLANNER_DEMO_SITE)
