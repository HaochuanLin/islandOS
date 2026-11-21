"""Connect forecast stress scenarios and water-shortage stress events to the optimizer.

Two questions are answered here, on synthetic inputs only:

1. If the forecast turns out worse than expected (less renewable power, more
   demand, higher prices), does the optimizer change its schedule, and how
   badly does a schedule planned on the central forecast do when the stress
   case actually happens?
2. Under named stress events (a low-renewable week, a spike in water demand),
   which operating strategies run out of water?

Every plan is replayed through ``dispatch_energy_system`` with the battery-first
controller acting live, so a plan that was made on the wrong forecast can still
use the battery, diesel or grid in real time. Only the RO schedule is held to
the plan. Water is tracked hour by hour: if the tank runs dry, the missing
volume is counted as a shortage.

Nothing here is a measurement or a site study.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from islandos_core.energy_system import EnergySystemInputs, dispatch_energy_system
from islandos_core.forecast_stress_scenarios import build_interval_stress_scenarios
from islandos_core.impact_scenario import (
    IslandSiteConfig, StrategyRules, SyntheticInputs, energy_system_setup, run_strategy, tou_tariff,
)

SIGNALS = ("pv_generation_kw", "wind_generation_kw", "load_kw", "water_demand_m3_per_hour", "grid_price_per_kwh")


def _prices(inputs: SyntheticInputs, case: str) -> list[float]:
    return [0.0] * inputs.hours if case == "island" else tou_tariff(inputs.hours)


def central_signals(inputs: SyntheticInputs, case: str) -> dict[str, list[float]]:
    return {
        "pv_generation_kw": [float(x) for x in inputs.pv_kw],
        "wind_generation_kw": [float(x) for x in inputs.wind_kw],
        "load_kw": [float(x) for x in inputs.essential_kw],
        "water_demand_m3_per_hour": [float(x) for x in inputs.water_demand_m3],
        "grid_price_per_kwh": _prices(inputs, case),
    }


def synthetic_forecast_intervals(
    inputs: SyntheticInputs,
    case: str = "island",
    *,
    renewable_band: float = 0.3,
    demand_band: float = 0.15,
    price_band: float = 0.25,
) -> dict[str, dict[str, list[float]]]:
    """Symmetric relative intervals around the synthetic series.

    These stand in for the forecast intervals a real forecaster would supply
    (``build_interval_stress_scenarios`` accepts either). The bands are
    assumptions chosen for testing, not calibrated forecast errors.
    """
    bands = {
        "pv_generation_kw": renewable_band,
        "wind_generation_kw": renewable_band,
        "load_kw": demand_band,
        "water_demand_m3_per_hour": demand_band,
        "grid_price_per_kwh": price_band,
    }
    out = {}
    for name, central in central_signals(inputs, case).items():
        band = bands[name]
        out[name] = {
            "central": central,
            "lower": [max(0.0, v * (1 - band)) for v in central],
            "upper": [v * (1 + band) for v in central],
        }
    return out


def apply_signals(inputs: SyntheticInputs, signals: dict[str, list[float]]) -> SyntheticInputs:
    """Return a copy of the synthetic inputs with stressed series swapped in."""
    return replace(
        inputs,
        pv_kw=np.asarray(signals["pv_generation_kw"], dtype=float),
        wind_kw=np.asarray(signals["wind_generation_kw"], dtype=float),
        essential_kw=np.asarray(signals["load_kw"], dtype=float),
        water_demand_m3=np.asarray(signals["water_demand_m3_per_hour"], dtype=float),
    )


def _energy_inputs(signals: dict[str, list[float]], case: str, extra_load_kw=None) -> EnergySystemInputs:
    n = len(signals["load_kw"])
    extra = list(extra_load_kw) if extra_load_kw is not None else [0.0] * n
    return EnergySystemInputs(
        pv_generation_kw=list(signals["pv_generation_kw"]),
        wind_generation_kw=list(signals["wind_generation_kw"]),
        load_kw=[float(a) + float(b) for a, b in zip(signals["load_kw"], extra)],
        grid_price_per_kwh=list(signals["grid_price_per_kwh"]),
        grid_available=[case != "island"] * n,
        diesel_available=[case != "grid_tou"] * n,
    )


def plan_joint_milp(signals: dict[str, list[float]], site: IslandSiteConfig, case: str,
                    time_limit_seconds: float = 120.0, reserve_m3: float = 0.0) -> dict:
    """Solve the joint water-energy MILP on one set of signals.

    ``reserve_m3`` is a tank level the plan may not go below. Without it the
    optimizer runs the tank close to empty whenever that is cheapest, which
    leaves no buffer for demand it did not expect.
    """
    from optimization.milp_dispatch_optimizer import optimize_dispatch_milp

    config, water = energy_system_setup(site, case)
    water = replace(water, reserve_m3=float(reserve_m3))
    result = optimize_dispatch_milp(
        _energy_inputs(signals, case),
        config,
        water_service=water,
        water_demand_m3_per_hour=list(signals["water_demand_m3_per_hour"]),
        terminal_water_inventory_min_m3=site.tank_initial_m3,
        ro_min_production_m3_per_hour=site.ro_min_power_kw / site.ro_specific_energy_kwh_per_m3,
        time_limit_seconds=time_limit_seconds,
    )
    ro_kw = [float(x) for x in result["water_service"]["ro_power_kw"]]
    battery = [float(row["battery_discharge_kw"]) - float(row["battery_charge_kw"])
               for row in result["dispatch"]["rows"]]
    return {"ro_power_kw": ro_kw, "battery_kw": battery,
            "cost": float(result["dispatch"]["summary"]["estimated_energy_cost"]),
            "optimality_proven": bool(result["optimality_proven_for_declared_milp"])}


def replay_ro_plan(ro_power_kw, signals: dict[str, list[float]], site: IslandSiteConfig, case: str) -> dict:
    """Hold an RO schedule fixed and see what happens under the given signals.

    Electricity is dispatched live by the battery-first controller. If the RO
    load cannot be fully powered, RO loses power first. Water shortage is any
    hour where the tank cannot meet demand.
    """
    config, _ = energy_system_setup(site, case)
    rows = dispatch_energy_system(_energy_inputs(signals, case, ro_power_kw), config, policy="battery_first")
    summary = rows["summary"]
    sec = site.ro_specific_energy_kwh_per_m3
    tank = site.tank_initial_m3
    shortage = 0.0
    min_tank = tank
    for t, row in enumerate(rows["rows"]):
        unmet_kw = float(row["unmet_load_kw"])
        ro_served = max(0.0, float(ro_power_kw[t]) - unmet_kw)
        tank = min(site.tank_capacity_m3, tank + ro_served / sec)
        demand = float(signals["water_demand_m3_per_hour"][t])
        served = min(demand, tank)
        shortage += demand - served
        tank -= served
        min_tank = min(min_tank, tank)
    refill_kwh = (site.tank_initial_m3 - tank) * sec
    out = {
        "energy_cost": float(summary["estimated_energy_cost"]),
        "diesel_kwh": float(summary["diesel_generation_kwh"]),
        "unmet_electric_kwh": float(summary["unmet_load_kwh"]),
        "water_shortage_m3": shortage,
        "min_tank_m3": min_tank,
        "ending_tank_m3": tank,
    }
    if case == "island":
        out["headline_tank_adjusted"] = (out["diesel_kwh"] + refill_kwh) * site.diesel_litres_per_kwh
    else:
        from islandos_core.impact_scenario import TOU_PRICES
        mean_price = (TOU_PRICES["off_peak"] * 8 + TOU_PRICES["shoulder"] * 12 + TOU_PRICES["peak"] * 4) / 24
        out["headline_tank_adjusted"] = out["energy_cost"] + refill_kwh * mean_price
    return out


def forecast_stress_study(
    inputs: SyntheticInputs,
    site: IslandSiteConfig,
    case: str = "island",
    *,
    interval_kwargs: dict | None = None,
    time_limit_seconds: float = 120.0,
) -> dict:
    """Plan on each stress scenario, then evaluate every plan in every scenario.

    Returns, for each scenario, how far the optimizer moves the RO and battery
    schedule away from the central plan, and a plan-by-outcome matrix of cost
    and water shortage.
    """
    intervals = synthetic_forecast_intervals(inputs, case, **(interval_kwargs or {}))
    stress = build_interval_stress_scenarios(intervals)
    scenarios = stress["scenarios"]
    plans = {name: plan_joint_milp(signals, site, case, time_limit_seconds) for name, signals in scenarios.items()}
    central = plans["central"]
    schedule_change = {}
    for name, plan in plans.items():
        ro_moved = 0.5 * sum(abs(a - b) for a, b in zip(plan["ro_power_kw"], central["ro_power_kw"]))
        battery_moved = sum(abs(a - b) for a, b in zip(plan["battery_kw"], central["battery_kw"]))
        hours_changed = sum(abs(a - b) > 0.5 for a, b in zip(plan["ro_power_kw"], central["ro_power_kw"]))
        schedule_change[name] = {
            "ro_energy_moved_kwh": ro_moved,
            "ro_hours_changed": hours_changed,
            "battery_setpoint_change_kwh": battery_moved,
            "planned_cost": plan["cost"],
            "planned_cost_change_vs_central_pct": 100.0 * (plan["cost"] - central["cost"]) / max(central["cost"], 1e-9),
            "schedule_changed": hours_changed > 0 or battery_moved > 1.0,
            "optimality_proven": plan["optimality_proven"],
        }
    outcomes = {}
    for plan_name in ("central", "combined_stress"):
        outcomes[plan_name] = {
            realised: replay_ro_plan(plans[plan_name]["ro_power_kw"], signals, site, case)
            for realised, signals in scenarios.items()
        }
    return {
        "case": case,
        "seed": inputs.seed,
        "probability_status": stress["probability_status"],
        "schedule_change": schedule_change,
        "plan_outcomes": outcomes,
    }


STRESS_EVENTS = ("low_renewable_week", "water_demand_spike", "low_renewable_and_spike")


def apply_stress_event(inputs: SyntheticInputs, event: str, *, renewable_factor: float = 0.4,
                       spike_factor: float = 1.6, spike_days: tuple[int, int] = (2, 4)) -> SyntheticInputs:
    """Named water-shortage stress events.

    ``low_renewable_week``: solar and wind at ``renewable_factor`` of normal.
    ``water_demand_spike``: water demand times ``spike_factor`` on the days in
    ``spike_days`` (start inclusive, end exclusive), for example a festival or
    a heatwave. ``low_renewable_and_spike``: both at once.
    """
    if event not in STRESS_EVENTS:
        raise ValueError(f"event must be one of {STRESS_EVENTS}")
    pv, wind, water = inputs.pv_kw.copy(), inputs.wind_kw.copy(), inputs.water_demand_m3.copy()
    if event in ("low_renewable_week", "low_renewable_and_spike"):
        pv *= renewable_factor
        wind *= renewable_factor
    if event in ("water_demand_spike", "low_renewable_and_spike"):
        start, end = spike_days[0] * 24, min(inputs.hours, spike_days[1] * 24)
        water[start:end] *= spike_factor
    return replace(inputs, pv_kw=pv, wind_kw=wind, water_demand_m3=water)


def water_shortage_stress_test(
    inputs: SyntheticInputs,
    site: IslandSiteConfig,
    event: str,
    case: str = "island",
    rules: StrategyRules | None = None,
    *,
    time_limit_seconds: float = 120.0,
    reserve_m3: float = 20.0,
) -> list[dict]:
    """Run every strategy through one stress event and report water shortage.

    The MILP appears three times: planned on the normal (unstressed) forecast
    and held, which is what happens when the event is not forecast; the same
    but with a tank reserve of ``reserve_m3`` the plan may not use; and
    re-planned with the event known in advance.
    """
    from optimization.energy_system_optimizer import OptimizationError

    rules = rules or StrategyRules()
    stressed = apply_stress_event(inputs, event)
    stressed_signals = central_signals(stressed, case)
    rows = []
    for label, strategy, strategy_rules in (
        ("fixed_timetable", "baseline", rules),
        ("surplus_rule", "coordinated", rules),
        ("forecast_rule", "forecast_coordinated", rules),
    ):
        # Rule strategies react to the actual tank level; the forecast rule
        # sees the stressed renewables because it forecasts from the inputs it is given.
        sim = run_strategy(strategy, stressed, site, strategy_rules)
        replay = replay_ro_plan([float(x) for x in sim.hourly["ro_power_kw"]], stressed_signals, site, case)
        rows.append({"strategy": label, "event": event, "case": case, **replay,
                     "water_shortage_m3": float(sim.summary["unmet_water_m3"]),
                     "min_tank_m3": float(sim.summary["min_tank_m3"])})
    for label, reserve in (("joint_milp_planned_on_normal_forecast", 0.0),
                           ("joint_milp_with_reserve_planned_on_normal_forecast", reserve_m3)):
        normal_plan = plan_joint_milp(central_signals(inputs, case), site, case, time_limit_seconds, reserve)
        rows.append({"strategy": label, "event": event, "case": case, "reserve_m3": reserve,
                     **replay_ro_plan(normal_plan["ro_power_kw"], stressed_signals, site, case)})
    try:
        known = plan_joint_milp(stressed_signals, site, case, time_limit_seconds)
        rows.append({"strategy": "joint_milp_event_forecast", "event": event, "case": case,
                     **replay_ro_plan(known["ro_power_kw"], stressed_signals, site, case)})
    except OptimizationError as exc:
        rows.append({"strategy": "joint_milp_event_forecast", "event": event, "case": case,
                     "infeasible": str(exc)[:160]})
    return rows
