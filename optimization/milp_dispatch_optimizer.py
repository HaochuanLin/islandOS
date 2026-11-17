"""Deterministic MILP reference dispatch for a bounded islanded/microgrid model.

Scope: hourly/sub-hourly energy balance with renewable curtailment, grid import,
battery charge/discharge and a single diesel unit. The MILP is replayed through
the shared physical simulator before a schedule is returned. It is not a live
controller and does not model network flows, grid charging, export, nonlinear
diesel fuel curves, or battery capacity fade.
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
from islandos_core.water_resource_adapter import (
    WaterServiceSpec,
    build_ro_energy_load,
    build_price_aware_ro_schedule,
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
) -> dict:
    """Solve a deterministic, bounded MILP and physically replay its schedule.

    The horizon begins with the diesel unit OFF and the battery at configured
    initial SOC. Every timestep's electrical demand must be served; infeasible
    instances fail closed. The model allows battery charging only from
    contemporaneous renewable surplus (no grid/diesel charging).
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
        objective[grid[t]] = prices[t] * dt
        objective[diesel_power[t]] = diesel.variable_cost_per_kwh * dt
        objective[charge[t]] = battery.throughput_cost_per_kwh * dt
        objective[discharge[t]] = battery.throughput_cost_per_kwh * dt
        objective[starts[t]] = diesel.start_cost_per_start
        objective[stops[t]] = diesel.stop_cost_per_stop
        # Tiny deterministic tie-breaker discourages needless curtailment only.
        objective[curtail[t]] = 1e-8 * dt
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
        }, load[t] - renewable, load[t] - renewable)
        constraint({int(charge[t]): 1.0, int(charge_mode[t]): -battery.max_charge_kw}, -np.inf, 0.0)
        constraint({int(discharge[t]): 1.0, int(charge_mode[t]): battery.max_discharge_kw}, -np.inf, battery.max_discharge_kw)
        constraint({int(soc[t + 1]): 1.0, int(soc[t]): -1.0,
                    int(charge[t]): -battery.charge_efficiency * dt,
                    int(discharge[t]): dt / battery.discharge_efficiency}, 0.0, 0.0)
        constraint({int(grid[t]): 1.0, int(peak): -1.0}, -np.inf, 0.0)
        constraint({int(diesel_power[t]): 1.0, int(diesel_on[t]): -diesel.rated_power_kw}, -np.inf, 0.0)
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
    solution = result.x
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
    if water_audit is not None and not water_audit["passed"]:
        raise OptimizationError(
            "MILP water schedule failed independent validation: "
            + "; ".join(water_audit["errors"])
        )
    replay_inputs = EnergySystemInputs(
        pv_generation_kw=inputs.pv_generation_kw,
        wind_generation_kw=inputs.wind_generation_kw,
        load_kw=[float(base) + ro for base, ro in zip(load, ro_power_kw)],
        grid_price_per_kwh=inputs.grid_price_per_kwh,
        grid_available=inputs.grid_available,
        diesel_available=inputs.diesel_available,
        diesel_fuel_delivery_liters=inputs.diesel_fuel_delivery_liters,
        battery_power_setpoint_kw=battery_setpoints,
        grid_import_power_setpoint_kw=[float(solution[grid[t]]) for t in range(n)],
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

    baseline_inputs = inputs
    baseline_water_service = None
    if water_service is not None:
        baseline_water = build_ro_energy_load(
            water_demand, spec=water_service, dt_hours=dt,
        )
        baseline_water_service = {
            "production_m3": list(baseline_water.production_m3),
            "ro_power_kw": list(baseline_water.ro_power_kw),
            "total_production_m3": baseline_water.total_production_m3,
            "total_demand_m3": baseline_water.total_demand_m3,
            "policy": "just_in_time",
        }
        baseline_inputs = EnergySystemInputs(
            pv_generation_kw=inputs.pv_generation_kw,
            wind_generation_kw=inputs.wind_generation_kw,
            load_kw=[base + ro for base, ro in zip(load, baseline_water.ro_power_kw)],
            grid_price_per_kwh=inputs.grid_price_per_kwh,
            grid_available=inputs.grid_available,
            diesel_available=inputs.diesel_available,
            diesel_fuel_delivery_liters=inputs.diesel_fuel_delivery_liters,
        )
    baseline = {}
    for policy in ("battery_first", "grid_first"):
        try:
            candidate = dispatch_energy_system(baseline_inputs, config, policy=policy)
            baseline_audit = _audit(candidate)
            baseline[policy] = {
                "summary": candidate["summary"],
                "audit": baseline_audit,
                "feasible": baseline_audit["passed"] and candidate["summary"]["unmet_load_kwh"] <= 1e-6,
                "water_service": baseline_water_service,
                "comparison_note": (
                    "same just-in-time RO production profile and water demand"
                    if water_service is not None else "energy-only baseline"
                ),
            }
        except (ValueError, RuntimeError) as exc:
            baseline[policy] = {"feasible": False, "error": str(exc)}
    return {
        "algorithm": "scipy_highs_mixed_integer_linear_program",
        "solver_status": int(result.status),
        "solver_message": str(result.message),
        "solve_time_seconds": float(solve_time_seconds),
        "optimality_proven_for_declared_milp": bool(result.status == 0),
        "mip_gap": float(getattr(result, "mip_gap", np.nan)),
        "objective_value": float(result.fun),
        "battery_power_setpoint_kw": battery_setpoints,
        "battery_soc_kwh": [float(solution[soc[t]]) for t in range(n + 1)],
        "diesel_commitment_schedule": commitments,
        "diesel_power_setpoint_kw": diesel_outputs,
        "water_service": ({
            "production_m3_per_hour": water_production_rates,
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
        "assumptions": {
            "initial_diesel_state": "off",
            "battery_charging_source": "renewable_surplus_only",
            "unserved_load": "not_permitted",
            "grid_export": "unsupported",
            "fuel_curve": "constant_l_per_kwh_only",
            "water_energy": "jointly_optimized_when_water_service_and_demand_are_supplied",
            "ro_variable_cost_per_m3": float(ro_variable_cost_per_m3),
            "flexible_load_jointly_optimized": False,
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
