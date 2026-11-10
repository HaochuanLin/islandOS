"""Deterministic, auditable energy-system dispatch for IslandOS.

This is an offline planning model, not a live controller or a validated plant model.
PV/wind inputs are available generation forecasts or measurements in kW. The model
balances each time step across renewables, load, battery, grid, diesel and curtailment.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


class EnergyModelError(ValueError):
    """Raised when an energy-system configuration or input series is invalid."""


def _number(name: str, value: float, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EnergyModelError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise EnergyModelError(f"{name} must be finite and >= {minimum}")
    return result


def _diesel_fuel_rate_lph(spec: "DieselSpec", power_kw: float) -> float:
    """Interpolate a confirmed piecewise-linear fuel-rate curve, or use legacy L/kWh."""
    if power_kw <= 0:
        return 0.0
    if spec.fuel_curve_liters_per_hour is None:
        return power_kw * float(spec.fuel_consumption_l_per_kwh or 0.0)
    curve = spec.fuel_curve_liters_per_hour
    if power_kw >= curve[-1][0]:
        return curve[-1][1]
    for (left_kw, left_rate), (right_kw, right_rate) in zip(curve, curve[1:]):
        if power_kw <= right_kw:
            fraction = (power_kw - left_kw) / (right_kw - left_kw)
            return left_rate + fraction * (right_rate - left_rate)
    raise EnergyModelError("diesel fuel curve does not cover requested output")


@dataclass(frozen=True)
class BatterySpec:
    capacity_kwh: float
    max_charge_kw: float
    max_discharge_kw: float
    initial_soc: float = 0.5
    min_soc: float = 0.1
    max_soc: float = 0.95
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    throughput_cost_per_kwh: float = 0.0
    initial_state_of_health: float = 1.0
    cycle_life_efc: float | None = None
    end_of_life_capacity_fraction: float | None = None

    def __post_init__(self) -> None:
        for name in (
            "capacity_kwh", "max_charge_kw", "max_discharge_kw",
            "throughput_cost_per_kwh",
        ):
            _number(name, getattr(self, name))
        for name in (
            "initial_soc", "min_soc", "max_soc", "charge_efficiency",
            "discharge_efficiency", "initial_state_of_health",
        ):
            value = _number(name, getattr(self, name))
            if value > 1:
                raise EnergyModelError(f"{name} must be <= 1")
        if self.capacity_kwh <= 0:
            raise EnergyModelError("battery capacity_kwh must be > 0")
        if self.max_soc <= self.min_soc:
            raise EnergyModelError("battery max_soc must be greater than min_soc")
        if not self.min_soc <= self.initial_soc <= self.max_soc:
            raise EnergyModelError("battery initial_soc must be within SOC limits")
        if self.charge_efficiency <= 0 or self.discharge_efficiency <= 0:
            raise EnergyModelError("battery efficiencies must be > 0")
        if self.initial_state_of_health <= 0:
            raise EnergyModelError("battery initial_state_of_health must be > 0")
        if self.cycle_life_efc is not None:
            _number("battery cycle_life_efc", self.cycle_life_efc)
            if self.cycle_life_efc <= 0:
                raise EnergyModelError("battery cycle_life_efc must be > 0")
            end_of_life_fraction = (
                0.8 if self.end_of_life_capacity_fraction is None
                else self.end_of_life_capacity_fraction
            )
            object.__setattr__(
                self, "end_of_life_capacity_fraction", end_of_life_fraction
            )
            _number(
                "battery end_of_life_capacity_fraction", end_of_life_fraction
            )
            if not 0 < end_of_life_fraction < 1:
                raise EnergyModelError(
                    "battery end_of_life_capacity_fraction must be between 0 and 1"
                )
            if self.initial_state_of_health < end_of_life_fraction:
                raise EnergyModelError(
                    "battery initial_state_of_health cannot be below end-of-life fraction"
                )
        elif self.end_of_life_capacity_fraction is not None:
            raise EnergyModelError(
                "battery end_of_life_capacity_fraction requires cycle_life_efc"
            )


@dataclass(frozen=True)
class DieselSpec:
    rated_power_kw: float
    variable_cost_per_kwh: float
    min_stable_power_kw: float = 0.0
    ramp_up_kw_per_hour: float | None = None
    min_up_time_hours: float = 0.0
    min_down_time_hours: float = 0.0
    start_cost_per_start: float = 0.0
    stop_cost_per_stop: float = 0.0
    fuel_consumption_l_per_kwh: float | None = None
    fuel_curve_liters_per_hour: tuple[tuple[float, float], ...] | None = None
    initial_fuel_liters: float | None = None
    fuel_tank_capacity_liters: float | None = None
    fuel_price_per_liter: float | None = None

    def __post_init__(self) -> None:
        for name in ("rated_power_kw", "variable_cost_per_kwh",
                     "min_stable_power_kw", "min_up_time_hours",
                     "min_down_time_hours", "start_cost_per_start",
                     "stop_cost_per_stop"):
            _number(f"diesel {name}", getattr(self, name))
        if self.ramp_up_kw_per_hour is not None:
            _number("diesel ramp_up_kw_per_hour", self.ramp_up_kw_per_hour)
            if self.ramp_up_kw_per_hour <= 0:
                raise EnergyModelError("diesel ramp_up_kw_per_hour must be > 0 when specified")
        has_constant_fuel_rate = self.fuel_consumption_l_per_kwh is not None
        has_fuel_curve = self.fuel_curve_liters_per_hour is not None
        if has_constant_fuel_rate and has_fuel_curve:
            raise EnergyModelError(
                "diesel constant fuel rate and nonlinear fuel curve are mutually exclusive"
            )
        if (has_constant_fuel_rate or has_fuel_curve) != (self.initial_fuel_liters is not None):
            raise EnergyModelError(
                "diesel fuel model and initial_fuel_liters must be supplied together"
            )
        if has_constant_fuel_rate:
            _number("diesel fuel_consumption_l_per_kwh", self.fuel_consumption_l_per_kwh)
            if self.fuel_consumption_l_per_kwh <= 0:
                raise EnergyModelError("diesel fuel_consumption_l_per_kwh must be > 0")
        if has_fuel_curve:
            curve = self.fuel_curve_liters_per_hour
            if not isinstance(curve, tuple) or len(curve) < 2:
                raise EnergyModelError("diesel fuel_curve_liters_per_hour must contain at least two points")
            previous_power = previous_rate = -1.0
            for index, point in enumerate(curve):
                if not isinstance(point, tuple) or len(point) != 2:
                    raise EnergyModelError(f"diesel fuel curve point {index} must be a (kW, L/h) tuple")
                power = _number(f"diesel fuel curve power[{index}]", point[0])
                rate = _number(f"diesel fuel curve rate[{index}]", point[1])
                if index == 0 and (power != 0 or rate != 0):
                    raise EnergyModelError("diesel fuel curve must start at (0 kW, 0 L/h)")
                if power <= previous_power or rate < previous_rate:
                    raise EnergyModelError("diesel fuel curve power must increase and fuel rate must not decrease")
                previous_power, previous_rate = power, rate
            if not math.isclose(curve[-1][0], self.rated_power_kw, rel_tol=0, abs_tol=1e-9):
                raise EnergyModelError("diesel fuel curve must end at rated_power_kw")
            if curve[-1][1] <= 0:
                raise EnergyModelError("diesel fuel curve rated-power fuel rate must be > 0")
        if self.initial_fuel_liters is not None:
            _number("diesel initial_fuel_liters", self.initial_fuel_liters)
        if self.fuel_price_per_liter is not None:
            _number("diesel fuel_price_per_liter", self.fuel_price_per_liter)
            if self.initial_fuel_liters is None:
                raise EnergyModelError(
                    "diesel fuel_price_per_liter requires a configured fuel model"
                )
        if self.fuel_tank_capacity_liters is not None:
            _number("diesel fuel_tank_capacity_liters", self.fuel_tank_capacity_liters)
            if self.fuel_tank_capacity_liters <= 0:
                raise EnergyModelError("diesel fuel_tank_capacity_liters must be > 0")
            if self.initial_fuel_liters is None:
                raise EnergyModelError(
                    "diesel fuel_tank_capacity_liters requires a fuel-inventory model"
                )
            if self.initial_fuel_liters > self.fuel_tank_capacity_liters:
                raise EnergyModelError(
                    "diesel initial_fuel_liters cannot exceed fuel_tank_capacity_liters"
                )
        if self.rated_power_kw <= 0:
            raise EnergyModelError("diesel rated_power_kw must be > 0")
        if self.min_stable_power_kw > self.rated_power_kw:
            raise EnergyModelError("diesel min_stable_power_kw cannot exceed rated power")


@dataclass(frozen=True)
class EnergySystemConfig:
    pv_rated_kw: float
    wind_rated_kw: float
    grid_import_limit_kw: float
    dt_hours: float = 1.0
    battery: BatterySpec | None = None
    diesel: DieselSpec | None = None
    grid_export_limit_kw: float = 0.0
    grid_demand_charge_per_kw: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "pv_rated_kw", "wind_rated_kw", "grid_import_limit_kw",
            "grid_export_limit_kw", "grid_demand_charge_per_kw",
        ):
            _number(name, getattr(self, name))
        _number("dt_hours", self.dt_hours)
        if self.dt_hours <= 0:
            raise EnergyModelError("dt_hours must be > 0")


@dataclass(frozen=True)
class EnergySystemInputs:
    pv_generation_kw: Sequence[float]
    wind_generation_kw: Sequence[float]
    load_kw: Sequence[float]
    grid_price_per_kwh: Sequence[float]
    grid_available: Sequence[bool]
    diesel_available: Sequence[bool] | None = None
    grid_export_price_per_kwh: Sequence[float] | None = None
    grid_export_available: Sequence[bool] | None = None
    diesel_fuel_delivery_liters: Sequence[float] | None = None
    # Negative charges from renewable surplus; positive discharges to load.
    battery_power_setpoint_kw: Sequence[float] | None = None
    diesel_commitment_schedule: Sequence[bool] | None = None
    diesel_power_setpoint_kw: Sequence[float] | None = None
    # Optional per-step cap; the physical balance still determines actual export.
    grid_export_power_setpoint_kw: Sequence[float] | None = None
    # Optional additional shiftable demand; shed before critical/base demand in a shortfall.
    flexible_load_kw: Sequence[float] | None = None
    # Critical subset of base load_kw; defaults to all base load being critical.
    critical_load_kw: Sequence[float] | None = None


def _series(name: str, values: Sequence[float], *, allow_zero: bool = True) -> list[float]:
    try:
        result = list(values)
    except TypeError as exc:
        raise EnergyModelError(f"{name} must be a one-dimensional series") from exc
    if not result:
        raise EnergyModelError(f"{name} must contain at least one time step")
    normalized = [_number(f"{name}[{i}]", value) for i, value in enumerate(result)]
    if not allow_zero and any(value <= 0 for value in normalized):
        raise EnergyModelError(f"{name} values must be > 0")
    return normalized



def _signed_series(name: str, values: Sequence[float]) -> list[float]:
    """Validate finite numeric values while allowing negative market prices."""
    try:
        result = list(values)
    except TypeError as exc:
        raise EnergyModelError(f"{name} must be a one-dimensional series") from exc
    if not result:
        raise EnergyModelError(f"{name} must contain at least one time step")
    normalized = []
    for index, value in enumerate(result):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EnergyModelError(f"{name}[{index}] must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise EnergyModelError(f"{name}[{index}] must be finite")
        normalized.append(number)
    return normalized


def _flags(name: str, values: Sequence[bool] | None, n: int, *, default: bool) -> list[bool]:
    if values is None:
        return [default] * n
    result = list(values)
    if len(result) != n or any(not isinstance(value, bool) for value in result):
        raise EnergyModelError(f"{name} must contain exactly {n} boolean values")
    return result


def dispatch_energy_system(
    inputs: EnergySystemInputs,
    config: EnergySystemConfig,
    *,
    policy: str = "battery_first",
    policy_schedule: Sequence[str] | None = None,
) -> dict:
    """Run auditable dispatch; optional signed battery set-points override battery priority.

    Policies are explicit operating priorities, not optimized schedules:
    - battery_first: renewables -> battery -> grid -> diesel
    - grid_first: renewables -> grid -> battery -> diesel

    A signed set-point is positive for discharge and negative for charging.
    Charging from set-points is limited to renewable surplus; grid charging is not modeled.
    Renewable surplus charges the battery first, then exports up to the explicit
    grid export limit when the grid is available. Remaining surplus is curtailed.
    Export requires an explicit feed-in price series. Diesel minimum stable
    loading, optional ramp-up after startup, and per-start/per-stop costs are
    modeled explicitly. Ramp-down, degradation-cost, and network constraints
    are not modeled.
    """
    if policy not in {"battery_first", "grid_first"}:
        raise EnergyModelError("policy must be 'battery_first' or 'grid_first'")
    pv = _series("pv_generation_kw", inputs.pv_generation_kw)
    wind = _series("wind_generation_kw", inputs.wind_generation_kw)
    base_load = _series("load_kw", inputs.load_kw)
    flexible_load = (
        _series("flexible_load_kw", inputs.flexible_load_kw)
        if inputs.flexible_load_kw is not None else [0.0] * len(base_load)
    )
    critical_load = (
        _series("critical_load_kw", inputs.critical_load_kw)
        if inputs.critical_load_kw is not None else list(base_load)
    )
    if len(flexible_load) != len(base_load) or len(critical_load) != len(base_load):
        raise EnergyModelError("base, flexible, and critical load series must have equal lengths")
    if any(critical > base + 1e-9 for critical, base in zip(critical_load, base_load)):
        raise EnergyModelError("critical_load_kw cannot exceed base load_kw at any timestep")
    load = [base + flexible for base, flexible in zip(base_load, flexible_load)]
    price = _signed_series("grid_price_per_kwh", inputs.grid_price_per_kwh)
    export_price = (
        _signed_series("grid_export_price_per_kwh", inputs.grid_export_price_per_kwh)
        if inputs.grid_export_price_per_kwh is not None else [0.0] * len(load)
    )
    fuel_deliveries = (
        _series("diesel_fuel_delivery_liters", inputs.diesel_fuel_delivery_liters)
        if inputs.diesel_fuel_delivery_liters is not None else [0.0] * len(load)
    )
    battery_setpoints = (
        _signed_series("battery_power_setpoint_kw", inputs.battery_power_setpoint_kw)
        if inputs.battery_power_setpoint_kw is not None else None
    )
    diesel_setpoints = (
        _series("diesel_power_setpoint_kw", inputs.diesel_power_setpoint_kw)
        if inputs.diesel_power_setpoint_kw is not None else None
    )
    export_setpoints = (
        _series("grid_export_power_setpoint_kw", inputs.grid_export_power_setpoint_kw)
        if inputs.grid_export_power_setpoint_kw is not None else None
    )
    n = len(load)
    if inputs.diesel_commitment_schedule is not None:
        if config.diesel is None:
            raise EnergyModelError("diesel_commitment_schedule requires a configured diesel unit")
        diesel_commitment = list(inputs.diesel_commitment_schedule)
        if len(diesel_commitment) != n or any(not isinstance(value, bool) for value in diesel_commitment):
            raise EnergyModelError(f"diesel_commitment_schedule must contain exactly {n} boolean values")
    else:
        diesel_commitment = [True] * n
    if inputs.diesel_commitment_schedule is not None and config.diesel is not None:
        # Validate completed commitment runs. The horizon is assumed to begin
        # with the unit off, but its pre-horizon off duration is unknown, so the
        # first off run is not treated as a completed minimum-down interval.
        spec = config.diesel
        run_start = 0
        for index in range(1, n + 1):
            if index == n or diesel_commitment[index] != diesel_commitment[run_start]:
                run_state = diesel_commitment[run_start]
                run_hours = (index - run_start) * config.dt_hours
                if index < n:
                    required = spec.min_up_time_hours if run_state else spec.min_down_time_hours
                    # Do not apply minimum-down time to the initial off segment:
                    # the actual time spent off before this horizon is unknown.
                    if not run_state and run_start == 0:
                        required = 0.0
                    if run_hours + 1e-9 < required:
                        state_name = "up" if run_state else "down"
                        raise EnergyModelError(
                            f"diesel minimum {state_name} time violated: "
                            f"{run_hours:g} h < {required:g} h before step {index}"
                        )
                run_start = index
    if any(len(values) != n for values in (pv, wind, price, export_price, fuel_deliveries)):
        raise EnergyModelError("all numeric input series must have equal lengths")
    if battery_setpoints is not None and len(battery_setpoints) != n:
        raise EnergyModelError(f"battery_power_setpoint_kw must contain exactly {n} values")
    if diesel_setpoints is not None:
        if config.diesel is None:
            raise EnergyModelError("diesel_power_setpoint_kw requires a configured diesel unit")
        if len(diesel_setpoints) != n:
            raise EnergyModelError(f"diesel_power_setpoint_kw must contain exactly {n} values")
        if any(value > config.diesel.rated_power_kw + 1e-9 for value in diesel_setpoints):
            raise EnergyModelError("diesel_power_setpoint_kw exceeds configured rated power")
    if export_setpoints is not None:
        if len(export_setpoints) != n:
            raise EnergyModelError(f"grid_export_power_setpoint_kw must contain exactly {n} values")
        if any(value > config.grid_export_limit_kw + 1e-9 for value in export_setpoints):
            raise EnergyModelError("grid_export_power_setpoint_kw cannot exceed grid_export_limit_kw")
    if battery_setpoints is not None and config.battery is None:
        raise EnergyModelError("battery_power_setpoint_kw requires a configured battery")
    if battery_setpoints is not None and any(
        value < -config.battery.max_charge_kw - 1e-9
        or value > config.battery.max_discharge_kw + 1e-9
        for value in battery_setpoints
    ):
        raise EnergyModelError("battery_power_setpoint_kw exceeds configured power limits")
    if any(value > config.pv_rated_kw + 1e-9 for value in pv):
        raise EnergyModelError("PV generation exceeds configured rated power")
    if any(value > config.wind_rated_kw + 1e-9 for value in wind):
        raise EnergyModelError("wind generation exceeds configured rated power")
    if inputs.grid_available is None:
        raise EnergyModelError("grid_available must be explicitly supplied")
    if config.grid_export_limit_kw > 0:
        if inputs.grid_export_price_per_kwh is None:
            raise EnergyModelError(
                "grid_export_price_per_kwh must be explicitly supplied when grid export is enabled"
            )
        if inputs.grid_export_available is None:
            raise EnergyModelError(
                "grid_export_available must be explicitly supplied when grid export is enabled"
            )
    elif inputs.grid_export_price_per_kwh is not None or inputs.grid_export_available is not None:
        raise EnergyModelError(
            "grid export price/availability was supplied but grid_export_limit_kw is zero"
        )
    if config.diesel is not None and inputs.diesel_available is None:
        raise EnergyModelError(
            "diesel_available must be explicitly supplied when diesel is configured"
        )
    if inputs.diesel_fuel_delivery_liters is not None and (
        config.diesel is None or config.diesel.initial_fuel_liters is None
    ):
        raise EnergyModelError(
            "diesel_fuel_delivery_liters requires a diesel fuel-inventory model"
        )
    grid_ok = _flags("grid_available", inputs.grid_available, n, default=False)
    # An unconfigured diesel unit is never implicitly treated as available.
    diesel_ok = _flags("diesel_available", inputs.diesel_available, n, default=False)
    export_ok = _flags(
        "grid_export_available", inputs.grid_export_available, n, default=False
    )

    battery = config.battery
    battery_state_of_health = battery.initial_state_of_health if battery else 1.0
    battery_effective_capacity_kwh = (
        battery.capacity_kwh * battery_state_of_health if battery else 0.0
    )
    battery_efc_cumulative = 0.0
    soc = battery.initial_soc if battery else 0.0
    rows: list[dict] = []
    totals = {
        "load_energy_kwh": 0.0, "load_served_kwh": 0.0, "unmet_load_kwh": 0.0,
        "critical_load_energy_kwh": 0.0, "flexible_load_energy_kwh": 0.0,
        "critical_unmet_load_kwh": 0.0, "flexible_load_shed_kwh": 0.0,
        "pv_energy_kwh": 0.0, "wind_energy_kwh": 0.0,
        "renewable_curtailed_kwh": 0.0, "battery_charge_input_kwh": 0.0,
        "battery_discharge_output_kwh": 0.0, "grid_import_kwh": 0.0,
        "diesel_generation_kwh": 0.0, "diesel_start_count": 0.0,
        "diesel_stop_count": 0.0, "diesel_start_cost": 0.0,
        "diesel_stop_cost": 0.0, "grid_energy_cost": 0.0,
        "diesel_energy_cost": 0.0, "diesel_fuel_cost": 0.0,
        "grid_export_energy_kwh": 0.0,
        "grid_export_revenue": 0.0,
        "peak_grid_import_kw": 0.0,
        "grid_demand_charge": 0.0,
        "battery_throughput_kwh": 0.0,
        "battery_degradation_cost": 0.0,
        "battery_capacity_fade_kwh": 0.0,
        "battery_capacity_fade_spill_kwh": 0.0,
        "battery_equivalent_full_cycles": 0.0,
        "diesel_fuel_delivered_liters": 0.0,
    }

    previous_diesel_kw = 0.0
    fuel_remaining_liters = (
        config.diesel.initial_fuel_liters
        if config.diesel and config.diesel.initial_fuel_liters is not None
        else None
    )
    totals["diesel_fuel_used_liters"] = 0.0

    if policy_schedule is None:
        active_policy_schedule = [policy] * n
    else:
        try:
            active_policy_schedule = list(policy_schedule)
        except TypeError as exc:
            raise EnergyModelError("policy_schedule must be a sequence") from exc
        if len(active_policy_schedule) != n:
            raise EnergyModelError(f"policy_schedule must contain exactly {n} entries")
        if any(item not in {"battery_first", "grid_first"} for item in active_policy_schedule):
            raise EnergyModelError("policy_schedule entries must be 'battery_first' or 'grid_first'")

    for t in range(n):
        active_policy = active_policy_schedule[t]
        diesel_fuel_delivered_liters = fuel_deliveries[t]
        if fuel_remaining_liters is not None:
            fuel_remaining_liters += diesel_fuel_delivered_liters
            tank_capacity = config.diesel.fuel_tank_capacity_liters
            if tank_capacity is not None and fuel_remaining_liters > tank_capacity + 1e-9:
                raise EnergyModelError(
                    f"diesel fuel delivery exceeds tank capacity at timestep {t}"
                )
        renewable = pv[t] + wind[t]
        direct_renewable = min(renewable, load[t])
        surplus = renewable - direct_renewable
        deficit = load[t] - direct_renewable
        charge_kw = discharge_kw = grid_kw = diesel_kw = 0.0
        diesel_started = diesel_stopped = False

        requested_setpoint = battery_setpoints[t] if battery_setpoints is not None else None
        if battery and surplus > 0:
            soc_room_kwh = (battery.max_soc - soc) * battery_effective_capacity_kwh
            requested_charge_kw = max(0.0, -requested_setpoint) if requested_setpoint is not None else battery.max_charge_kw
            charge_kw = min(
                surplus, battery.max_charge_kw, requested_charge_kw,
                soc_room_kwh / (battery.charge_efficiency * config.dt_hours),
            )
            soc += (
                charge_kw * config.dt_hours * battery.charge_efficiency
                / battery_effective_capacity_kwh
            )
            surplus -= charge_kw

        def discharge(remaining_kw: float) -> float:
            nonlocal soc
            if not battery or remaining_kw <= 0:
                return 0.0
            available_kwh = (soc - battery.min_soc) * battery_effective_capacity_kwh
            output_limit_kw = available_kwh * battery.discharge_efficiency / config.dt_hours
            delivered = min(remaining_kw, battery.max_discharge_kw, output_limit_kw)
            soc -= delivered * config.dt_hours / (
                battery.discharge_efficiency * battery_effective_capacity_kwh
            )
            return delivered

        def import_grid(remaining_kw: float) -> float:
            return min(remaining_kw, config.grid_import_limit_kw) if grid_ok[t] else 0.0

        def run_diesel(remaining_kw: float) -> float:
            nonlocal diesel_started, diesel_stopped
            spec = config.diesel
            if not spec or not diesel_ok[t] or not diesel_commitment[t] or remaining_kw <= 0:
                diesel_stopped = previous_diesel_kw > 0
                return 0.0
            # Do not start (or remain online) below the confirmed stable minimum.
            if remaining_kw + 1e-9 < spec.min_stable_power_kw:
                diesel_stopped = previous_diesel_kw > 0
                return 0.0
            target = min(remaining_kw, spec.rated_power_kw)
            if diesel_setpoints is not None:
                target = min(target, diesel_setpoints[t])
            if target <= 0 or target + 1e-9 < spec.min_stable_power_kw:
                diesel_stopped = previous_diesel_kw > 0
                return 0.0
            if fuel_remaining_liters is not None:
                available_fuel = fuel_remaining_liters
                if _diesel_fuel_rate_lph(spec, spec.min_stable_power_kw) * config.dt_hours > available_fuel + 1e-9:
                    diesel_stopped = previous_diesel_kw > 0
                    return 0.0
                if _diesel_fuel_rate_lph(spec, target) * config.dt_hours > available_fuel + 1e-9:
                    low, high = spec.min_stable_power_kw, target
                    for _ in range(60):
                        midpoint = (low + high) / 2
                        if _diesel_fuel_rate_lph(spec, midpoint) * config.dt_hours <= available_fuel:
                            low = midpoint
                        else:
                            high = midpoint
                    target = low
            if previous_diesel_kw <= 0:
                # Startup is represented as reaching the stable operating point
                # within this timestep; the ramp limit applies to later increases.
                if target + 1e-9 < spec.min_stable_power_kw:
                    return 0.0
                diesel_started = target > 0
            elif spec.ramp_up_kw_per_hour is not None and target > previous_diesel_kw:
                target = min(target, previous_diesel_kw + spec.ramp_up_kw_per_hour * config.dt_hours)
            return target

        if deficit > 0 and requested_setpoint is not None:
            discharge_kw = discharge(min(deficit, max(0.0, requested_setpoint)))
            deficit -= discharge_kw
            grid_kw = import_grid(deficit)
            deficit -= grid_kw
            diesel_kw = run_diesel(deficit)
            deficit -= diesel_kw
        elif deficit > 0 and active_policy == "battery_first":
            discharge_kw = discharge(deficit)
            deficit -= discharge_kw
            grid_kw = import_grid(deficit)
            deficit -= grid_kw
            diesel_kw = run_diesel(deficit)
            deficit -= diesel_kw
        elif deficit > 0:
            grid_kw = import_grid(deficit)
            deficit -= grid_kw
            discharge_kw = discharge(deficit)
            deficit -= discharge_kw
            diesel_kw = run_diesel(deficit)
            deficit -= diesel_kw

        # A unit that supplied the previous step but receives no dispatch now
        # has stopped, even when the residual load was already covered by grid
        # or battery and run_diesel() was therefore never called.
        if previous_diesel_kw > 0 and diesel_kw <= 0 and not diesel_stopped:
            diesel_stopped = True
        if diesel_started and config.diesel:
            totals["diesel_start_count"] += 1
            totals["diesel_start_cost"] += config.diesel.start_cost_per_start
        if diesel_stopped and config.diesel:
            totals["diesel_stop_count"] += 1
            totals["diesel_stop_cost"] += config.diesel.stop_cost_per_stop
        previous_diesel_kw = diesel_kw
        battery_throughput_kwh = (charge_kw + discharge_kw) * config.dt_hours
        battery_degradation_cost = (
            battery_throughput_kwh * battery.throughput_cost_per_kwh
            if battery else 0.0
        )
        battery_efc_increment = (
            (
                charge_kw * config.dt_hours * battery.charge_efficiency
                + discharge_kw * config.dt_hours / battery.discharge_efficiency
            ) / (2 * battery.capacity_kwh)
            if battery else 0.0
        )
        battery_capacity_fade_kwh = 0.0
        battery_capacity_fade_spill_kwh = 0.0
        if battery and battery.cycle_life_efc is not None:
            previous_capacity = battery_effective_capacity_kwh
            stored_energy_kwh = soc * battery_effective_capacity_kwh
            fade_per_efc = (
                (1 - battery.end_of_life_capacity_fraction) / battery.cycle_life_efc
            )
            battery_state_of_health = max(
                battery.end_of_life_capacity_fraction,
                battery_state_of_health - battery_efc_increment * fade_per_efc,
            )
            battery_effective_capacity_kwh = (
                battery.capacity_kwh * battery_state_of_health
            )
            battery_capacity_fade_kwh = (
                previous_capacity - battery_effective_capacity_kwh
            )
            maximum_stored_energy = (
                battery_effective_capacity_kwh * battery.max_soc
            )
            battery_capacity_fade_spill_kwh = max(
                0.0, stored_energy_kwh - maximum_stored_energy
            )
            stored_energy_kwh -= battery_capacity_fade_spill_kwh
            soc = stored_energy_kwh / battery_effective_capacity_kwh
        battery_efc_cumulative += battery_efc_increment
        diesel_fuel_used_liters = (
            _diesel_fuel_rate_lph(config.diesel, diesel_kw) * config.dt_hours
            if config.diesel and config.diesel.initial_fuel_liters is not None
            else 0.0
        )
        diesel_fuel_cost = (
            diesel_fuel_used_liters * config.diesel.fuel_price_per_liter
            if config.diesel and config.diesel.fuel_price_per_liter is not None
            else 0.0
        )
        if fuel_remaining_liters is not None:
            fuel_remaining_liters = max(0.0, fuel_remaining_liters - diesel_fuel_used_liters)
        totals["diesel_fuel_used_liters"] += diesel_fuel_used_liters
        totals["diesel_fuel_cost"] += diesel_fuel_cost
        totals["diesel_fuel_delivered_liters"] += diesel_fuel_delivered_liters

        requested_export_kw = (
            export_setpoints[t] if export_setpoints is not None
            else config.grid_export_limit_kw
        )
        export_kw = (
            min(surplus, config.grid_export_limit_kw, requested_export_kw)
            if grid_ok[t] and export_ok[t] and config.grid_export_limit_kw > 0 else 0.0
        )
        curtailed_kw = max(0.0, surplus - export_kw)
        served_kw = load[t] - max(0.0, deficit)
        balance_residual = (
            pv[t] + wind[t] + discharge_kw + grid_kw + diesel_kw
            - served_kw - charge_kw - export_kw - curtailed_kw
        )
        if abs(balance_residual) > 1e-7:
            raise RuntimeError(f"energy balance failed at timestep {t}: {balance_residual}")
        if battery and not battery.min_soc - 1e-9 <= soc <= battery.max_soc + 1e-9:
            raise RuntimeError(f"battery SOC outside configured bounds at timestep {t}")

        row = {
            "timestep": t, "dispatch_priority": active_policy,
            "battery_power_setpoint_kw": requested_setpoint,
            "diesel_power_setpoint_kw": diesel_setpoints[t] if diesel_setpoints is not None else None,
            "pv_generation_kw": pv[t], "wind_generation_kw": wind[t],
            "load_kw": load[t], "renewable_direct_to_load_kw": direct_renewable,
            "battery_charge_kw": charge_kw, "battery_discharge_kw": discharge_kw,
            "battery_throughput_kwh": battery_throughput_kwh,
            "battery_degradation_cost": battery_degradation_cost,
            "battery_state_of_health": battery_state_of_health if battery else None,
            "battery_effective_capacity_kwh": battery_effective_capacity_kwh if battery else None,
            "battery_efc_increment": battery_efc_increment,
            "battery_efc_cumulative": battery_efc_cumulative,
            "battery_capacity_fade_kwh": battery_capacity_fade_kwh,
            "battery_capacity_fade_spill_kwh": battery_capacity_fade_spill_kwh,
            "grid_available": grid_ok[t],
            "grid_export_available": export_ok[t],
            "diesel_available": diesel_ok[t],
            "diesel_committed": diesel_commitment[t] if config.diesel else None,
            "grid_import_kw": grid_kw, "grid_export_kw": export_kw,
            "grid_export_price_per_kwh": export_price[t],
            "grid_export_revenue": export_kw * config.dt_hours * export_price[t],
            "diesel_generation_kw": diesel_kw,
            "diesel_fuel_delivered_liters": diesel_fuel_delivered_liters,
            "diesel_fuel_used_liters": diesel_fuel_used_liters,
            "diesel_fuel_cost": diesel_fuel_cost,
            "diesel_fuel_remaining_liters": fuel_remaining_liters,
            "diesel_started": diesel_started,
            "diesel_stopped": diesel_stopped,
            "diesel_start_cost": (
                config.diesel.start_cost_per_start if diesel_started and config.diesel else 0.0
            ),
            "diesel_stop_cost": (
                config.diesel.stop_cost_per_stop if diesel_stopped and config.diesel else 0.0
            ),
            "load_served_kw": served_kw, "unmet_load_kw": max(0.0, deficit),
            "renewable_curtailed_kw": curtailed_kw, "battery_soc": soc,
            "grid_price_per_kwh": price[t], "energy_balance_residual_kw": balance_residual,
        }
        critical_unmet_kw = max(0.0, critical_load[t] - served_kw)
        flexible_served_kw = min(
            flexible_load[t], max(0.0, served_kw - critical_load[t])
        )
        flexible_shed_kw = max(0.0, flexible_load[t] - flexible_served_kw)
        row.update({
            "base_load_kw": base_load[t],
            "critical_load_kw": critical_load[t],
            "flexible_load_kw": flexible_load[t],
            "critical_unmet_kw": critical_unmet_kw,
            "flexible_load_shed_kw": flexible_shed_kw,
        })
        rows.append(row)
        scale = config.dt_hours
        totals["load_energy_kwh"] += load[t] * scale
        totals["load_served_kwh"] += served_kw * scale
        totals["unmet_load_kwh"] += max(0.0, deficit) * scale
        totals["critical_load_energy_kwh"] += critical_load[t] * scale
        totals["flexible_load_energy_kwh"] += flexible_load[t] * scale
        totals["critical_unmet_load_kwh"] += critical_unmet_kw * scale
        totals["flexible_load_shed_kwh"] += flexible_shed_kw * scale
        totals["pv_energy_kwh"] += pv[t] * scale
        totals["wind_energy_kwh"] += wind[t] * scale
        totals["renewable_curtailed_kwh"] += curtailed_kw * scale
        totals["battery_charge_input_kwh"] += charge_kw * scale
        totals["battery_discharge_output_kwh"] += discharge_kw * scale
        totals["battery_throughput_kwh"] += battery_throughput_kwh
        totals["battery_degradation_cost"] += battery_degradation_cost
        totals["battery_capacity_fade_kwh"] += battery_capacity_fade_kwh
        totals["battery_capacity_fade_spill_kwh"] += battery_capacity_fade_spill_kwh
        totals["battery_equivalent_full_cycles"] += battery_efc_increment
        totals["grid_import_kwh"] += grid_kw * scale
        totals["peak_grid_import_kw"] = max(totals["peak_grid_import_kw"], grid_kw)
        totals["grid_export_energy_kwh"] += export_kw * scale
        totals["grid_export_revenue"] += export_kw * scale * export_price[t]
        totals["diesel_generation_kwh"] += diesel_kw * scale
        totals["grid_energy_cost"] += grid_kw * scale * price[t]
        if config.diesel:
            totals["diesel_energy_cost"] += diesel_kw * scale * config.diesel.variable_cost_per_kwh

    totals["grid_demand_charge"] = (
        totals["peak_grid_import_kw"] * config.grid_demand_charge_per_kw
    )
    totals["grid_demand_charge_per_kw"] = config.grid_demand_charge_per_kw
    totals = {key: round(value, 8) for key, value in totals.items()}
    totals["unmet_load_fraction"] = (
        totals["unmet_load_kwh"] / totals["load_energy_kwh"]
        if totals["load_energy_kwh"] else 0.0
    )
    totals["critical_unmet_load_fraction"] = (
        totals["critical_unmet_load_kwh"] / totals["critical_load_energy_kwh"]
        if totals["critical_load_energy_kwh"] else 0.0
    )
    totals["ending_battery_soc"] = round(soc, 8) if battery else None
    totals["ending_battery_state_of_health"] = (
        round(battery_state_of_health, 8) if battery else None
    )
    totals["ending_battery_effective_capacity_kwh"] = (
        round(battery_effective_capacity_kwh, 8) if battery else None
    )
    totals["ending_diesel_fuel_liters"] = (
        round(fuel_remaining_liters, 8) if fuel_remaining_liters is not None else None
    )
    totals["gross_energy_cost"] = round(
        totals["grid_energy_cost"] + totals["diesel_energy_cost"]
        + totals["diesel_start_cost"] + totals["diesel_stop_cost"]
        + totals["diesel_fuel_cost"] + totals["battery_degradation_cost"]
        + totals["grid_demand_charge"], 8
    )
    totals["estimated_energy_cost"] = round(
        totals["gross_energy_cost"] - totals["grid_export_revenue"], 8
    )
    return {
        "policy": policy if policy_schedule is None else "time_varying_priority_schedule",
        "policy_schedule": active_policy_schedule,
        "time_steps": n,
        "dt_hours": config.dt_hours,
        "grid_export_limit_kw": config.grid_export_limit_kw,
        "grid_demand_charge_per_kw": config.grid_demand_charge_per_kw,
        "summary": totals,
        "rows": rows,
        "model_scope": {
            "type": "deterministic_rule_based_offline_screening",
            "not_an_optimizer": True,
            "not_a_controller": True,
            "synthetic_or_user_supplied_inputs_only": True,
            "grid_export_enabled": config.grid_export_limit_kw > 0,
            "grid_export_power_setpoint_supported": export_setpoints is not None,
            "critical_load_priority_reporting_enabled": True,
            "flexible_load_shedding_accounted_separately": inputs.flexible_load_kw is not None,
            "grid_demand_charge_enabled": config.grid_demand_charge_per_kw > 0,
            "battery_throughput_cost_enabled": bool(
                battery and battery.throughput_cost_per_kwh > 0
            ),
            "battery_degradation_is_physical_capacity_fade": bool(
                battery and battery.cycle_life_efc is not None
            ),
            "battery_cycle_aging_enabled": bool(
                battery and battery.cycle_life_efc is not None
            ),
            "battery_calendar_aging_modeled": False,
            "battery_temperature_aging_modeled": False,
            "diesel_nonlinear_fuel_curve_enabled": bool(
                config.diesel and config.diesel.fuel_curve_liters_per_hour is not None
            ),
            "diesel_power_setpoint_input_enabled": diesel_setpoints is not None,
            "diesel_fuel_consumption_model": (
                "piecewise_linear_curve" if config.diesel and config.diesel.fuel_curve_liters_per_hour is not None
                else "constant_l_per_kwh" if config.diesel and config.diesel.fuel_consumption_l_per_kwh is not None
                else "not_configured"
            ),
            "diesel_fuel_cost_enabled": bool(
                config.diesel and config.diesel.fuel_price_per_liter is not None
            ),
            "interconnection_permission_validated": False,
            "network_power_flow_modeled": False,
        },
    }



def compare_energy_policies(
    inputs: EnergySystemInputs,
    config: EnergySystemConfig,
) -> dict:
    """Compare the two explicit dispatch baselines without declaring a winner."""
    battery_first = dispatch_energy_system(inputs, config, policy="battery_first")
    grid_first = dispatch_energy_system(inputs, config, policy="grid_first")
    metrics = (
        "estimated_energy_cost", "grid_import_kwh", "grid_export_energy_kwh",
        "grid_export_revenue", "diesel_generation_kwh",
        "diesel_fuel_used_liters", "diesel_fuel_cost", "diesel_energy_cost",
        "renewable_curtailed_kwh", "unmet_load_kwh", "battery_discharge_output_kwh",
        "battery_throughput_kwh", "battery_degradation_cost",
        "battery_capacity_fade_kwh", "battery_capacity_fade_spill_kwh",
        "battery_equivalent_full_cycles",
    )
    differences = {
        key: round(
            battery_first["summary"][key] - grid_first["summary"][key], 8
        )
        for key in metrics
    }
    return {
        "battery_first": battery_first,
        "grid_first": grid_first,
        "difference_battery_first_minus_grid_first": differences,
        "interpretation": (
            "Compare cost, unmet load, curtailment and battery use together. "
            "A lower estimated energy bill alone does not establish a better "
            "or safer operating policy."
        ),
    }
