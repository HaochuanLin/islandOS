"""Deterministic MILP reference dispatch for a bounded islanded/microgrid model.

Scope: hourly/sub-hourly energy balance with renewable curtailment, grid import,
battery charge/discharge and a single diesel unit. Optional extensions: joint
RO water production with tank inventory, a terminal tank level, an RO minimum
production rate, and one aggregate flexible load with a fixed energy budget.
The MILP is replayed through the shared physical simulator before a schedule
is returned, and it follows that simulator's rules: leftover renewable power
charges the battery before anything is curtailed, and the grid is used before
diesel. It is not a live controller and does not model network flows, grid
charging, export, nonlinear diesel fuel curves, or battery capacity fade.
A diesel minimum stable output can make the model infeasible, because unserved
load and dumping diesel surplus are not allowed.
"""
from __future__ import annotations

import math
from time import perf_counter
from typing import Sequence

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from islandos_core.energy_system import (
    EnergySystemConfig,
    EnergySystemInputs,
    dispatch_energy_system,
)
from islandos_core.water_dispatch import build_price_aware_ro_schedule
from islandos_core.water_resource_adapter import (
    WaterServiceSpec,
    build_ro_energy_load,
)
from .energy_system_optimizer import OptimizationError, _audit


def _validate_diesel_schedule(
    power_kw: Sequence[float],
    commitment: Sequence[bool],
    available: Sequence[bool],
    config: EnergySystemConfig,
    *,
    tolerance: float = 1e-6,
) -> list[str]:
    """Independently validate diesel output, availability, ramps and run times."""
    spec = config.diesel
    if spec is None:
        raise OptimizationError("diesel configuration is required")
    n = len(power_kw)
    if len(commitment) != n or len(available) != n:
        raise OptimizationError("diesel schedule, commitment and availability lengths must match")
    errors: list[str] = []
    for t, (power, on, can_run) in enumerate(zip(power_kw, commitment, available)):
        if not math.isfinite(float(power)) or power < -tolerance:
            errors.append(f"invalid_power_at_{t}")
            continue
        if not isinstance(on, bool) or not isinstance(can_run, bool):
            errors.append(f"invalid_boolean_state_at_{t}")
            continue
        if not can_run and (on or power > tolerance):
            errors.append(f"unavailable_unit_committed_at_{t}")
        if power > spec.rated_power_kw + tolerance:
            errors.append(f"rated_power_exceeded_at_{t}")
        if on and power + tolerance < spec.min_stable_power_kw:
            errors.append(f"minimum_stable_power_violated_at_{t}")
        if not on and power > tolerance:
            errors.append(f"power_while_off_at_{t}")
    previous = 0.0
    for t, power in enumerate(power_kw):
        power = float(power)
        if spec.ramp_up_kw_per_hour is not None:
            limit = spec.ramp_up_kw_per_hour * config.dt_hours
            if power - previous > limit + tolerance:
                errors.append(f"ramp_up_exceeded_at_{t}")
        if spec.ramp_down_kw_per_hour is not None:
            limit = spec.ramp_down_kw_per_hour * config.dt_hours
            if previous - power > limit + tolerance:
                errors.append(f"ramp_down_exceeded_at_{t}")
        previous = power

    # The horizon starts from an assumed OFF state. Only completed runs are
    # constrained; a run continuing at the horizon boundary is left open.
    run_start = 0
    for t in range(1, n + 1):
        if t == n or commitment[t] != commitment[run_start]:
            state = commitment[run_start]
            duration = (t - run_start) * config.dt_hours
            if t < n:
                required = spec.min_up_time_hours if state else spec.min_down_time_hours
                if not state and run_start == 0:
                    required = 0.0  # unknown pre-horizon off duration
                if duration + tolerance < required:
                    errors.append(
                        f"minimum_{'up' if state else 'down'}_time_violated_before_{t}"
                    )
            run_start = t
    return errors




def _audit_water_schedule(
    production_m3_per_hour: Sequence[float],
    demand_m3_per_hour: Sequence[float],
    inventory_end_m3: Sequence[float],
    spec: WaterServiceSpec,
    *,
    dt_hours: float,
    tolerance: float = 1e-6,
) -> dict:
    """Independently replay RO production and tank inventory against service bounds."""
    errors: list[str] = []
    n = len(demand_m3_per_hour)
    if len(production_m3_per_hour) != n or len(inventory_end_m3) != n:
        return {"passed": False, "errors": ["water schedule lengths do not match"]}
    inventory = spec.initial_inventory_m3
    for t, (production, demand, reported_inventory) in enumerate(
        zip(production_m3_per_hour, demand_m3_per_hour, inventory_end_m3)
    ):
        if not all(math.isfinite(float(value)) for value in (production, demand, reported_inventory)):
            errors.append(f"non_finite_water_value_at_{t}")
            continue
        if production < -tolerance or production > spec.ro_capacity_m3_per_hour + tolerance:
            errors.append(f"ro_capacity_violated_at_{t}")
        inventory = inventory + float(production) * dt_hours - float(demand) * dt_hours
        if inventory < spec.reserve_m3 - tolerance:
            errors.append(f"water_reserve_violated_at_{t}")
        if inventory > spec.tank_capacity_m3 + tolerance:
            errors.append(f"water_tank_capacity_violated_at_{t}")
        if abs(inventory - float(reported_inventory)) > tolerance:
            errors.append(f"water_inventory_replay_mismatch_at_{t}")
    return {
        "passed": not errors,
        "errors": errors,
        "ending_inventory_m3": inventory,
        "total_production_m3": sum(float(value) for value in production_m3_per_hour) * dt_hours,
        "total_demand_m3": sum(float(value) for value in demand_m3_per_hour) * dt_hours,
    }


def optimize_dispatch_milp(
    inputs: EnergySystemInputs,
    config: EnergySystemConfig,
    *,
    terminal_battery_soc_min: float | None = None,
    time_limit_seconds: float = 30.0,
    mip_relative_gap: float = 0.0,
    water_service: WaterServiceSpec | None = None,
    water_demand_m3_per_hour: Sequence[float] | None = None,
    ro_variable_cost_per_m3: float = 0.0,
    terminal_water_inventory_min_m3: float | None = None,
    ro_min_production_m3_per_hour: float = 0.0,
    price_aware_lookahead_hours: int = 6,
    flexible_load_energy_kwh: float | None = None,
    flexible_load_available_steps: Sequence[bool] | None = None,
    flexible_load_max_power_kw: float | None = None,
) -> dict:
    """Solve a deterministic, bounded MILP and physically replay its schedule.

    The horizon begins with the diesel unit OFF and the battery at configured
    initial SOC. Every timestep's electrical demand must be served; infeasible
    instances fail closed. The model allows battery charging only from
    contemporaneous renewable surplus (no grid/diesel charging).

    Optional extensions:
    - ``terminal_water_inventory_min_m3`` keeps at least this much water in
      the tank at the end, so the schedule cannot look cheap by emptying it.
    - ``ro_min_production_m3_per_hour`` makes RO semi-continuous: each hour it
      is either off or produces at least this rate (one binary per hour).
    - ``flexible_load_*`` adds one aggregate shiftable load whose energy must be
      delivered inside its availability window, within a per-step power cap.
    """
    if config.battery is None or config.diesel is None:
        raise OptimizationError("MILP dispatch requires configured battery and diesel assets")
    if config.grid_export_limit_kw > 0:
        raise OptimizationError("MILP reference solver currently does not support grid export")
    if config.battery.cycle_life_efc is not None:
        raise OptimizationError(
            "MILP reference solver does not yet model cycle-driven battery capacity fade; "
            "use a battery configuration without cycle_life_efc"
        )
    if config.diesel.fuel_curve_liters_per_hour is not None:
        raise OptimizationError("MILP reference solver does not support nonlinear diesel fuel curves")
    if inputs.grid_available is None or inputs.diesel_available is None:
        raise OptimizationError("grid_available and diesel_available must be explicit")
    n = len(inputs.load_kw)
    if n < 1:
        raise OptimizationError("optimization horizon must contain at least one timestep")
    if n > 168:
        raise OptimizationError("MILP reference solver supports at most 168 timesteps")
    if terminal_battery_soc_min is not None:
        if (isinstance(terminal_battery_soc_min, bool)
                or not isinstance(terminal_battery_soc_min, (int, float))
                or not math.isfinite(float(terminal_battery_soc_min))
                or not config.battery.min_soc <= terminal_battery_soc_min <= config.battery.max_soc):
            raise OptimizationError("terminal_battery_soc_min must be within configured battery SOC limits")
    if (isinstance(time_limit_seconds, bool) or not isinstance(time_limit_seconds, (int, float))
            or not math.isfinite(float(time_limit_seconds)) or time_limit_seconds <= 0):
        raise OptimizationError("time_limit_seconds must be finite and > 0")
    if (isinstance(mip_relative_gap, bool) or not isinstance(mip_relative_gap, (int, float))
            or not math.isfinite(float(mip_relative_gap)) or mip_relative_gap < 0):
        raise OptimizationError("mip_relative_gap must be finite and >= 0")
    if (isinstance(ro_variable_cost_per_m3, bool)
            or not isinstance(ro_variable_cost_per_m3, (int, float))
            or not math.isfinite(float(ro_variable_cost_per_m3))
            or ro_variable_cost_per_m3 < 0):
        raise OptimizationError("ro_variable_cost_per_m3 must be finite and >= 0")

    def nonneg_number(name: str, value) -> float:
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value)) or value < 0):
            raise OptimizationError(f"{name} must be finite and >= 0")
        return float(value)

    ro_min_rate = nonneg_number("ro_min_production_m3_per_hour", ro_min_production_m3_per_hour)
    if (isinstance(price_aware_lookahead_hours, bool) or not isinstance(price_aware_lookahead_hours, int)
            or price_aware_lookahead_hours < 1):
        raise OptimizationError("price_aware_lookahead_hours must be a positive integer")
    if terminal_water_inventory_min_m3 is not None:
        nonneg_number("terminal_water_inventory_min_m3", terminal_water_inventory_min_m3)

    def series(name: str, values: Sequence[float]) -> list[float]:
        try:
            result = list(values)
        except TypeError as exc:
            raise OptimizationError(f"{name} must be a one-dimensional sequence") from exc
        if len(result) != n:
            raise OptimizationError(f"{name} must contain exactly {n} values")
        normalized = []
        for t, value in enumerate(result):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise OptimizationError(f"{name}[{t}] must be finite numeric")
            normalized.append(float(value))
        return normalized

    pv = series("pv_generation_kw", inputs.pv_generation_kw)
    wind = series("wind_generation_kw", inputs.wind_generation_kw)
    load = series("load_kw", inputs.load_kw)
    prices = series("grid_price_per_kwh", inputs.grid_price_per_kwh)
    grid_ok = list(inputs.grid_available)
    diesel_ok = list(inputs.diesel_available)
    if any(not isinstance(x, bool) for x in grid_ok + diesel_ok) or len(grid_ok) != n or len(diesel_ok) != n:
        raise OptimizationError("grid_available and diesel_available must contain exactly n booleans")
    if any(x < 0 for x in pv + wind + load):
        raise OptimizationError("PV, wind and load values must be non-negative")
    if any(x > config.pv_rated_kw + 1e-8 for x in pv) or any(x > config.wind_rated_kw + 1e-8 for x in wind):
        raise OptimizationError("forecast renewable generation exceeds configured rated power")
    if (water_service is None) != (water_demand_m3_per_hour is None):
        raise OptimizationError("water_service and water_demand_m3_per_hour must be supplied together")
    if water_service is not None and not isinstance(water_service, WaterServiceSpec):
        raise OptimizationError("water_service must be a WaterServiceSpec")
    if water_service is None and (terminal_water_inventory_min_m3 is not None or ro_min_rate > 0):
        raise OptimizationError("water terminal and RO minimum settings require water_service")
    if water_service is not None:
        if ro_min_rate > water_service.ro_capacity_m3_per_hour + 1e-12:
            raise OptimizationError("ro_min_production_m3_per_hour exceeds RO capacity")
        if (terminal_water_inventory_min_m3 is not None
                and not water_service.reserve_m3 - 1e-12 <= terminal_water_inventory_min_m3
                <= water_service.tank_capacity_m3 + 1e-12):
            raise OptimizationError("terminal_water_inventory_min_m3 must be within reserve and tank capacity")
    flexible_settings = (flexible_load_energy_kwh, flexible_load_available_steps, flexible_load_max_power_kw)
    flexible_enabled = any(value is not None for value in flexible_settings)
    if flexible_enabled and any(value is None for value in flexible_settings):
        raise OptimizationError("flexible-load energy, availability and maximum power must be supplied together")
    if flexible_enabled:
        flex_energy = nonneg_number("flexible_load_energy_kwh", flexible_load_energy_kwh)
        flex_max = nonneg_number("flexible_load_max_power_kw", flexible_load_max_power_kw)
        if flex_energy <= 0 or flex_max <= 0:
            raise OptimizationError("flexible-load energy and maximum power must be > 0")
        flex_available = list(flexible_load_available_steps)
        if len(flex_available) != n or any(not isinstance(value, bool) for value in flex_available):
            raise OptimizationError(f"flexible_load_available_steps must contain exactly {n} booleans")
        if flex_energy > sum(flex_available) * flex_max * float(config.dt_hours) + 1e-9:
            raise OptimizationError("flexible-load energy exceeds available-window power capacity")
    else:
        flex_energy, flex_max, flex_available = 0.0, 0.0, [False] * n
    if inputs.flexible_load_kw is not None or inputs.critical_load_kw is not None:
        raise OptimizationError("MILP reference solver currently accepts total load only; flexible/critical load modelling is a later extension")
    if inputs.grid_export_available is not None or inputs.grid_export_price_per_kwh is not None:
        raise OptimizationError("grid export inputs are unsupported when export is disabled")
    dt = float(config.dt_hours)
    battery = config.battery
    diesel = config.diesel
    effective_capacity = battery.capacity_kwh * battery.initial_state_of_health
    if diesel.fuel_curve_liters_per_hour is not None:
        raise OptimizationError("nonlinear diesel fuel curve is unsupported")
    fuel_model = diesel.fuel_consumption_l_per_kwh is not None
    if fuel_model and diesel.initial_fuel_liters is None:
        raise OptimizationError("fuel inventory requires initial fuel")
    if (fuel_model and diesel.fuel_tank_capacity_liters is not None
            and float(diesel.initial_fuel_liters) > diesel.fuel_tank_capacity_liters + 1e-9):
        raise OptimizationError("initial diesel fuel exceeds configured tank capacity")
    water_demand = (
        series("water_demand_m3_per_hour", water_demand_m3_per_hour)
        if water_demand_m3_per_hour is not None else None
    )
    if water_demand is not None and any(value < 0 for value in water_demand):
        raise OptimizationError("water demand must be non-negative")
    deliveries = (
        series("diesel_fuel_delivery_liters", inputs.diesel_fuel_delivery_liters)
        if inputs.diesel_fuel_delivery_liters is not None else [0.0] * n
    )
    if any(x < 0 for x in deliveries):
        raise OptimizationError("diesel fuel deliveries must be non-negative")
    if inputs.diesel_fuel_delivery_liters is not None and not fuel_model:
        raise OptimizationError("fuel deliveries require a constant-rate diesel fuel model")

    # The physical replay always stores leftover renewable power in the battery
    # when there is room. Binary "curtail allowed" variables (below) make the
    # MILP follow the same rule exactly, so only a tiny tie-breaker remains.
    curtail_weight = [1e-8] * n
    discharge_tie_breaker = 0.0

    # Variable blocks.
    cursor = 0
    def block(name: str, size: int) -> np.ndarray:
        nonlocal cursor
        ids = np.arange(cursor, cursor + size, dtype=int)
        cursor += size
        return ids
    charge = block("charge", n)
    discharge = block("discharge", n)
    soc = block("soc", n + 1)
    diesel_power = block("diesel_power", n)
    diesel_on = block("diesel_on", n)
    starts = block("starts", n)
    stops = block("stops", n)
    grid = block("grid", n)
    curtail = block("curtail", n)
    charge_mode = block("charge_mode", n)
    fuel = block("fuel", n + 1) if fuel_model else None
    water_production = block("water_production", n) if water_service is not None else None
    water_inventory = block("water_inventory", n + 1) if water_service is not None else None
    ro_on = block("ro_on", n) if (water_service is not None and ro_min_rate > 0) else None
    flex = block("flexible_load", n) if flexible_enabled else None
    curtail_allowed = block("curtail_allowed", n)
    at_max_charge = block("at_max_charge", n)
    battery_full = block("battery_full", n)
    peak = block("peak", 1)[0]
    total_vars = cursor

    lower = np.zeros(total_vars)
    upper = np.full(total_vars, np.inf)
    integrality = np.zeros(total_vars, dtype=int)
    objective = np.zeros(total_vars)

    for t in range(n):
        upper[charge[t]] = min(battery.max_charge_kw, max(0.0, pv[t] + wind[t] - load[t]))
        if water_service is not None:
            upper[water_production[t]] = water_service.ro_capacity_m3_per_hour
            objective[water_production[t]] = float(ro_variable_cost_per_m3) * dt
        upper[discharge[t]] = battery.max_discharge_kw
        upper[diesel_power[t]] = diesel.rated_power_kw if diesel_ok[t] else 0.0
        upper[diesel_on[t]] = 1.0 if diesel_ok[t] else 0.0
        upper[starts[t]] = 1.0 if diesel_ok[t] else 0.0
        upper[stops[t]] = 1.0
        upper[grid[t]] = config.grid_import_limit_kw if grid_ok[t] else 0.0
        upper[curtail[t]] = pv[t] + wind[t]
        upper[charge_mode[t]] = 1.0
        for idx in (diesel_on[t], starts[t], stops[t], charge_mode[t]):
            integrality[idx] = 1
        for idx in (curtail_allowed[t], at_max_charge[t], battery_full[t]):
            upper[idx] = 1.0
            integrality[idx] = 1
        if ro_on is not None:
            upper[ro_on[t]] = 1.0
            integrality[ro_on[t]] = 1
        if flex is not None:
            upper[flex[t]] = flex_max if flex_available[t] else 0.0
        objective[grid[t]] = prices[t] * dt
        objective[diesel_power[t]] = diesel.variable_cost_per_kwh * dt
        objective[charge[t]] = battery.throughput_cost_per_kwh * dt
        objective[discharge[t]] = battery.throughput_cost_per_kwh * dt
        objective[starts[t]] = diesel.start_cost_per_start
        objective[stops[t]] = diesel.stop_cost_per_stop
        objective[curtail[t]] = curtail_weight[t] * dt
        # Matching tie-breaker on discharge so that "discharge, curtail, then
        # recharge" never looks cheaper than just curtailing (battery losses
        # would otherwise make the curtailment penalty reward it).
        objective[discharge[t]] += discharge_tie_breaker * dt
        if fuel_model and diesel.fuel_price_per_liter is not None:
            objective[diesel_power[t]] += (
                diesel.fuel_consumption_l_per_kwh * diesel.fuel_price_per_liter * dt
            )
    upper[peak] = config.grid_import_limit_kw
    objective[peak] = config.grid_demand_charge_per_kw
    lower[soc] = effective_capacity * battery.min_soc
    upper[soc] = effective_capacity * battery.max_soc
    lower[soc[0]] = upper[soc[0]] = effective_capacity * battery.initial_soc
    if terminal_battery_soc_min is not None:
        lower[soc[-1]] = effective_capacity * float(terminal_battery_soc_min)
    if water_service is not None:
        lower[water_inventory] = water_service.reserve_m3
        upper[water_inventory] = water_service.tank_capacity_m3
        lower[water_inventory[0]] = upper[water_inventory[0]] = water_service.initial_inventory_m3
        if terminal_water_inventory_min_m3 is not None:
            lower[water_inventory[-1]] = max(lower[water_inventory[-1]], float(terminal_water_inventory_min_m3))
    if fuel_model:
        max_fuel = diesel.fuel_tank_capacity_liters
        if max_fuel is None:
            max_fuel = float(diesel.initial_fuel_liters) + sum(deliveries)
        lower[fuel] = 0.0
        upper[fuel] = max_fuel
        lower[fuel[0]] = upper[fuel[0]] = float(diesel.initial_fuel_liters)

    rows: list[dict[int, float]] = []
    row_l: list[float] = []
    row_u: list[float] = []
    def constraint(coefficients: dict[int, float], lb: float, ub: float) -> None:
        rows.append(coefficients)
        row_l.append(lb)
        row_u.append(ub)

    for t in range(n):
        renewable = pv[t] + wind[t]
        constraint({
            int(grid[t]): 1.0, int(diesel_power[t]): 1.0,
            int(discharge[t]): 1.0, int(curtail[t]): -1.0,
            int(charge[t]): -1.0,
            **({int(water_production[t]): -water_service.specific_energy_kwh_per_m3}
               if water_service is not None else {}),
            **({int(flex[t]): -1.0} if flex is not None else {}),
        }, load[t] - renewable, load[t] - renewable)
        if water_service is not None or flex is not None:
            # With RO or flexible demand on top of base load, the surplus bound on
            # charging is no longer exact. Charging is then only allowed in steps
            # where neither diesel nor grid runs, so charge energy is renewable,
            # matching the physical replay.
            constraint({int(diesel_power[t]): 1.0, int(charge_mode[t]): diesel.rated_power_kw},
                       -np.inf, diesel.rated_power_kw)
            if config.grid_import_limit_kw > 0:
                constraint({int(grid[t]): 1.0, int(charge_mode[t]): config.grid_import_limit_kw},
                           -np.inf, config.grid_import_limit_kw)
        if ro_on is not None:
            constraint({int(water_production[t]): 1.0,
                        int(ro_on[t]): -water_service.ro_capacity_m3_per_hour}, -np.inf, 0.0)
            constraint({int(water_production[t]): 1.0, int(ro_on[t]): -ro_min_rate}, 0.0, np.inf)
        constraint({int(charge[t]): 1.0, int(charge_mode[t]): -battery.max_charge_kw}, -np.inf, 0.0)
        # Curtail only when the battery cannot take more: it is charging at its
        # power limit or it ends the step full. No discharge while curtailing.
        constraint({int(curtail[t]): 1.0, int(curtail_allowed[t]): -max(renewable, 0.0)}, -np.inf, 0.0)
        constraint({int(at_max_charge[t]): 1.0, int(battery_full[t]): 1.0,
                    int(curtail_allowed[t]): -1.0}, 0.0, np.inf)
        constraint({int(charge[t]): 1.0, int(at_max_charge[t]): -battery.max_charge_kw}, 0.0, np.inf)
        constraint({int(soc[t + 1]): 1.0,
                    int(battery_full[t]): -effective_capacity * battery.max_soc}, 0.0, np.inf)
        constraint({int(discharge[t]): 1.0, int(curtail_allowed[t]): battery.max_discharge_kw},
                   -np.inf, battery.max_discharge_kw)
        constraint({int(discharge[t]): 1.0, int(charge_mode[t]): battery.max_discharge_kw}, -np.inf, battery.max_discharge_kw)
        constraint({int(soc[t + 1]): 1.0, int(soc[t]): -1.0,
                    int(charge[t]): -battery.charge_efficiency * dt,
                    int(discharge[t]): dt / battery.discharge_efficiency}, 0.0, 0.0)
        constraint({int(grid[t]): 1.0, int(peak): -1.0}, -np.inf, 0.0)
        constraint({int(diesel_power[t]): 1.0, int(diesel_on[t]): -diesel.rated_power_kw}, -np.inf, 0.0)
        if config.grid_import_limit_kw > 0 and grid_ok[t] and diesel_ok[t]:
            # The shared dispatch always draws on the grid before diesel, so a
            # committed diesel unit may only produce once the grid is at its limit.
            constraint({int(grid[t]): 1.0, int(diesel_on[t]): -config.grid_import_limit_kw},
                       0.0, np.inf)
        if diesel.min_stable_power_kw > 0:
            constraint({int(diesel_power[t]): 1.0, int(diesel_on[t]): -diesel.min_stable_power_kw}, 0.0, np.inf)
        # Commitment transition: initial state is OFF; starts/stops are exact.
        transition = {int(diesel_on[t]): 1.0, int(starts[t]): -1.0, int(stops[t]): 1.0}
        if t > 0:
            transition[int(diesel_on[t - 1])] = -1.0
        constraint(transition, 0.0, 0.0)
        constraint({int(starts[t]): 1.0, int(stops[t]): 1.0}, -np.inf, 1.0)
        if diesel.ramp_up_kw_per_hour is not None:
            ramp = {int(diesel_power[t]): 1.0}
            if t > 0:
                ramp[int(diesel_power[t - 1])] = -1.0
            constraint(ramp, -np.inf, diesel.ramp_up_kw_per_hour * dt)
        if diesel.ramp_down_kw_per_hour is not None and t > 0:
            constraint({int(diesel_power[t - 1]): 1.0, int(diesel_power[t]): -1.0},
                       -np.inf, diesel.ramp_down_kw_per_hour * dt)
        if water_service is not None:
            constraint({int(water_inventory[t + 1]): 1.0,
                        int(water_inventory[t]): -1.0,
                        int(water_production[t]): -dt},
                       -water_demand[t] * dt, -water_demand[t] * dt)
        if fuel_model:
            constraint({int(fuel[t + 1]): 1.0, int(fuel[t]): -1.0,
                        int(diesel_power[t]): diesel.fuel_consumption_l_per_kwh * dt},
                       deliveries[t], deliveries[t])
    if flex is not None:
        constraint({int(flex[t]): dt for t in range(n)}, flex_energy, flex_energy)
    min_up_steps = int(math.ceil(diesel.min_up_time_hours / dt - 1e-12))
    min_down_steps = int(math.ceil(diesel.min_down_time_hours / dt - 1e-12))
    for t in range(n):
        if min_up_steps:
            start_window = range(max(0, t - min_up_steps + 1), t + 1)
            constraint({**{int(starts[k]): 1.0 for k in start_window},
                        int(diesel_on[t]): -1.0}, -np.inf, 0.0)
        if min_down_steps:
            stop_window = range(max(0, t - min_down_steps + 1), t + 1)
            constraint({**{int(stops[k]): 1.0 for k in stop_window},
                        int(diesel_on[t]): 1.0}, -np.inf, 1.0)

    matrix = lil_matrix((len(rows), total_vars), dtype=float)
    for i, coefficients in enumerate(rows):
        for j, value in coefficients.items():
            matrix[i, j] = value
    solve_started = perf_counter()
    result = milp(
        c=objective,
        integrality=integrality,
        bounds=Bounds(lower, upper),
        constraints=LinearConstraint(matrix.tocsr(), np.asarray(row_l), np.asarray(row_u)),
        options={"time_limit": float(time_limit_seconds), "mip_rel_gap": float(mip_relative_gap)},
    )
    solve_time_seconds = perf_counter() - solve_started
    if result.x is None:
        raise OptimizationError(f"MILP did not produce a feasible schedule: {result.message}")
    # HiGHS may return values a hair outside their bounds (for example -1e-12);
    # clip to the declared bounds before replay so tiny noise never fails validation.
    solution = np.clip(result.x, lower, upper)
    solution[np.abs(solution) < 1e-9] = 0.0
    battery_setpoints = [float(solution[discharge[t]] - solution[charge[t]]) for t in range(n)]
    diesel_outputs = [float(solution[diesel_power[t]]) for t in range(n)]
    commitments = [bool(solution[diesel_on[t]] >= 0.5) for t in range(n)]
    diesel_errors = _validate_diesel_schedule(
        diesel_outputs, commitments, diesel_ok, config
    )
    if diesel_errors:
        raise OptimizationError("MILP diesel schedule failed independent validation: " + "; ".join(diesel_errors))

    water_production_rates = (
        [float(solution[water_production[t]]) for t in range(n)]
        if water_service is not None else None
    )
    ro_power_kw = (
        [rate * water_service.specific_energy_kwh_per_m3 for rate in water_production_rates]
        if water_service is not None else [0.0] * n
    )
    water_inventory_trace = (
        [float(solution[water_inventory[t + 1]]) for t in range(n)]
        if water_service is not None else None
    )
    water_audit = (
        _audit_water_schedule(
            water_production_rates, water_demand, water_inventory_trace,
            water_service, dt_hours=dt,
        )
        if water_service is not None else None
    )
    if water_audit is not None and ro_min_rate > 0:
        below_minimum = [
            t for t, rate in enumerate(water_production_rates)
            if 1e-6 < rate < ro_min_rate - 1e-6
        ]
        if below_minimum:
            water_audit["passed"] = False
            water_audit["errors"].extend(f"ro_minimum_production_violated_at_{t}" for t in below_minimum)
    if (water_audit is not None and terminal_water_inventory_min_m3 is not None
            and water_audit["ending_inventory_m3"] < float(terminal_water_inventory_min_m3) - 1e-6):
        water_audit["passed"] = False
        water_audit["errors"].append("terminal_water_inventory_below_minimum")
    if water_audit is not None and not water_audit["passed"]:
        raise OptimizationError(
            "MILP water schedule failed independent validation: "
            + "; ".join(water_audit["errors"])
        )
    flex_power_kw = (
        [float(solution[flex[t]]) for t in range(n)] if flex is not None else [0.0] * n
    )
    if flex is not None:
        delivered = sum(flex_power_kw) * dt
        if abs(delivered - flex_energy) > 1e-5 or any(
            p > 1e-6 and not flex_available[t] for t, p in enumerate(flex_power_kw)
        ):
            raise OptimizationError("MILP flexible-load schedule failed independent validation")
    replay_inputs = EnergySystemInputs(
        pv_generation_kw=inputs.pv_generation_kw,
        wind_generation_kw=inputs.wind_generation_kw,
        load_kw=[float(base) + ro + f for base, ro, f in zip(load, ro_power_kw, flex_power_kw)],
        grid_price_per_kwh=inputs.grid_price_per_kwh,
        grid_available=inputs.grid_available,
        diesel_available=inputs.diesel_available,
        diesel_fuel_delivery_liters=inputs.diesel_fuel_delivery_liters,
        battery_power_setpoint_kw=battery_setpoints,
        diesel_commitment_schedule=commitments,
        diesel_power_setpoint_kw=diesel_outputs,
    )
    dispatch = dispatch_energy_system(replay_inputs, config, policy="grid_first")
    audit = _audit(dispatch)
    if not audit["passed"]:
        raise OptimizationError("MILP schedule failed shared physical replay audit: " + "; ".join(audit["errors"]))
    if dispatch["summary"]["unmet_load_kwh"] > 1e-6:
        raise OptimizationError("MILP schedule replay did not serve the full load")
    replay_diesel = [float(row.get("diesel_generation_kw", 0.0)) for row in dispatch["rows"]]
    replay_grid = [float(row.get("grid_import_kw", 0.0)) for row in dispatch["rows"]]
    model_grid = [float(solution[grid[t]]) for t in range(n)]
    replay_battery = [
        float(row.get("battery_discharge_kw", 0.0)) - float(row.get("battery_charge_kw", 0.0))
        for row in dispatch["rows"]
    ]
    if any(abs(a - b) > 1e-4 for a, b in zip(replay_diesel, diesel_outputs)):
        raise OptimizationError("MILP diesel set-points differ from physical replay")
    if any(abs(a - b) > 1e-4 for a, b in zip(replay_grid, model_grid)):
        raise OptimizationError("MILP grid-import set-points differ from physical replay")
    if any(abs(a - b) > 1e-4 for a, b in zip(replay_battery, battery_setpoints)):
        raise OptimizationError("MILP battery set-points differ from physical replay")

    replay_summary = dispatch["summary"]
    ro_operating_cost = (
        sum(water_production_rates) * dt * float(ro_variable_cost_per_m3)
        if water_production_rates is not None else 0.0
    )
    objective_components = {
        "grid_energy_cost": float(replay_summary["grid_energy_cost"]),
        "diesel_variable_energy_cost": float(replay_summary["diesel_energy_cost"]),
        "diesel_fuel_cost": float(replay_summary["diesel_fuel_cost"]),
        "diesel_start_cost": float(replay_summary["diesel_start_cost"]),
        "diesel_stop_cost": float(replay_summary["diesel_stop_cost"]),
        "battery_throughput_cost": float(replay_summary["battery_degradation_cost"]),
        "grid_demand_charge": float(replay_summary["grid_demand_charge"]),
        "ro_variable_operating_cost": float(ro_operating_cost),
        "curtailment_tie_breaker": float(sum(float(solution[curtail[t]]) * curtail_weight[t] for t in range(n)) * dt),
        "discharge_tie_breaker": float(sum(float(solution[discharge[t]]) for t in range(n)) * discharge_tie_breaker * dt),
    }
    reconstructed_objective = sum(objective_components.values())
    if abs(reconstructed_objective - float(result.fun)) > 1e-4 * max(1.0, abs(float(result.fun))):
        raise OptimizationError(
            "MILP objective does not reconcile with replayed cost components: "
            f"model={float(result.fun):.8g}, replay={reconstructed_objective:.8g}"
        )

    # Baseline flexible load: run as early as allowed at full power.
    baseline_flex = [0.0] * n
    if flexible_enabled:
        remaining = flex_energy
        for t in range(n):
            if flex_available[t] and remaining > 1e-12:
                baseline_flex[t] = min(flex_max, remaining / dt)
                remaining -= baseline_flex[t] * dt

    def run_rule_baselines(ro_profile_kw: Sequence[float], water_record, note: str) -> dict:
        baseline_inputs = EnergySystemInputs(
            pv_generation_kw=inputs.pv_generation_kw,
            wind_generation_kw=inputs.wind_generation_kw,
            load_kw=[base + ro + f for base, ro, f in zip(load, ro_profile_kw, baseline_flex)],
            grid_price_per_kwh=inputs.grid_price_per_kwh,
            grid_available=inputs.grid_available,
            diesel_available=inputs.diesel_available,
            diesel_fuel_delivery_liters=inputs.diesel_fuel_delivery_liters,
        )
        rows = {}
        for policy in ("battery_first", "grid_first"):
            try:
                candidate = dispatch_energy_system(baseline_inputs, config, policy=policy)
                baseline_audit = _audit(candidate)
                rows[policy] = {
                    "summary": candidate["summary"],
                    "audit": baseline_audit,
                    "feasible": baseline_audit["passed"] and candidate["summary"]["unmet_load_kwh"] <= 1e-6,
                    "water_service": water_record,
                    "comparison_note": note,
                }
            except (ValueError, RuntimeError) as exc:
                rows[policy] = {"feasible": False, "error": str(exc)}
        return rows

    water_policy_baselines = {}
    if water_service is not None:
        try:
            baseline_water = build_ro_energy_load(
                water_demand, spec=water_service, dt_hours=dt,
            )
        except ValueError as exc:
            # Just-in-time RO cannot keep up (for example a demand spike above
            # RO capacity) while the MILP pre-fills the tank. Record that the
            # rule baseline fails instead of failing the whole solve.
            baseline_water = None
            baseline = {policy: {"feasible": False, "error": str(exc)}
                        for policy in ("battery_first", "grid_first")}
        if baseline_water is not None:
            baseline_water_service = {
                "production_m3": list(baseline_water.production_m3),
                "ro_power_kw": list(baseline_water.ro_power_kw),
                "total_production_m3": baseline_water.total_production_m3,
                "total_demand_m3": baseline_water.total_demand_m3,
                "policy": "just_in_time",
            }
            baseline = run_rule_baselines(
                baseline_water.ro_power_kw, baseline_water_service,
                "same just-in-time RO production profile and water demand",
            )
        water_policy_baselines["just_in_time"] = baseline
        try:
            price_aware = build_price_aware_ro_schedule(
                water_demand, prices, spec=water_service,
                lookahead_hours=price_aware_lookahead_hours, dt_hours=dt,
            )
            price_aware_record = {
                "production_m3": list(price_aware["production_m3"]),
                "ro_power_kw": list(price_aware["ro_power_kw"]),
                "total_production_m3": price_aware["total_production_m3"],
                "total_demand_m3": price_aware["total_demand_m3"],
                "ending_inventory_m3": price_aware["inventory_end_m3"][-1],
                "policy": "price_aware_lookahead",
                "lookahead_hours": price_aware_lookahead_hours,
            }
            water_policy_baselines["price_aware_lookahead"] = run_rule_baselines(
                price_aware["ro_power_kw"], price_aware_record,
                "tariff-look-ahead RO production profile and the same water demand",
            )
        except ValueError as exc:
            water_policy_baselines["price_aware_lookahead"] = {"feasible": False, "error": str(exc)}
    else:
        baseline = run_rule_baselines([0.0] * n, None, "energy-only baseline")
    return {
        "algorithm": "scipy_highs_mixed_integer_linear_program",
        "solver_status": int(result.status),
        "solver_message": str(result.message),
        "solve_time_seconds": float(solve_time_seconds),
        "optimality_proven_for_declared_milp": bool(result.status == 0),
        "mip_gap": float(getattr(result, "mip_gap", np.nan)),
        "objective_value": float(result.fun),
        "objective_components": objective_components,
        "objective_reconciliation": {
            "reconstructed_from_physical_replay": float(reconstructed_objective),
            "absolute_difference": abs(reconstructed_objective - float(result.fun)),
            "passed": True,
        },
        "battery_power_setpoint_kw": battery_setpoints,
        "battery_soc_kwh": [float(solution[soc[t]]) for t in range(n + 1)],
        "diesel_commitment_schedule": commitments,
        "diesel_power_setpoint_kw": diesel_outputs,
        "water_service": ({
            "production_m3_per_hour": water_production_rates,
            "ending_inventory_m3": water_audit["ending_inventory_m3"],
            "inventory_end_m3": water_inventory_trace,
            "ro_power_kw": ro_power_kw,
            "total_production_m3": sum(water_production_rates) * dt,
            "total_demand_m3": sum(water_demand) * dt,
            "service_feasible": True,
            "audit": water_audit,
            "production_policy": "joint_milp_water_energy",
            "device_write_authorized": False,
        } if water_service is not None else None),
        "grid_import_model_kw": [float(solution[grid[t]]) for t in range(n)],
        "renewable_curtailment_model_kw": [float(solution[curtail[t]]) for t in range(n)],
        "dispatch": dispatch,
        "physical_audit": audit,
        "diesel_constraint_audit": {"passed": not diesel_errors, "errors": diesel_errors},
        "baseline_comparison": baseline,
        "water_policy_baselines": water_policy_baselines,
        "flexible_load": ({
            "power_kw": flex_power_kw,
            "energy_kwh": flex_energy,
            "baseline_power_kw": baseline_flex,
            "baseline_rule": "earliest_available_steps_at_max_power",
        } if flexible_enabled else None),
        "assumptions": {
            "initial_diesel_state": "off",
            "battery_charging_source": "renewable_surplus_only",
            "unserved_load": "not_permitted",
            "grid_export": "unsupported",
            "fuel_curve": "constant_l_per_kwh_only",
            "water_energy": "jointly_optimized_when_water_service_and_demand_are_supplied",
            "ro_variable_cost_per_m3": float(ro_variable_cost_per_m3),
            "flexible_load_jointly_optimized": bool(flexible_enabled),
            "terminal_water_inventory_min_m3": (
                float(terminal_water_inventory_min_m3)
                if terminal_water_inventory_min_m3 is not None else None
            ),
            "ro_min_production_m3_per_hour": ro_min_rate,
            "scope": "single-bus energy balance; one battery and one diesel unit",
        },
        "model_scope": {
            "deterministic_milp": True,
            "global_optimum_claim": bool(result.status == 0),
            "global_optimum_claim_scope": "only the declared MILP formulation and input data",
            "site_validation": False,
            "device_write_authorized": False,
        },
    }
