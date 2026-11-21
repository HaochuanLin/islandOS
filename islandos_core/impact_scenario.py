"""Synthetic baseline-versus-coordinated impact scenario for an off-grid island.

This module answers one question with synthetic data: if an island already
has solar, wind, a battery, a diesel generator and an RO desalination unit,
how much do the numbers change when RO is timed around renewable surplus
instead of following a fixed operator timetable?

Both strategies run on the same inputs and the same equipment, and both use
``simulate_microgrid`` for the electricity side, one hour at a time, so the
battery and tank state carry over between hours. Water is tracked here so that
RO can be served either from surplus renewables only (the model's normal RO
path) or as a firm load that may draw on the battery or diesel.

Everything produced by this module is a simulation result on synthetic
inputs. It is not a measurement, a site study or a savings claim.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math

import numpy as np

from islandos_core.microgrid_model import MicrogridConfig, MicrogridInputs, simulate_microgrid


@dataclass(frozen=True)
class IslandSiteConfig:
    """Equipment and cost assumptions. Power in kW, energy in kWh, water in m3."""

    pv_rated_kw: float = 60.0
    wind_rated_kw: float = 40.0
    battery_capacity_kwh: float = 120.0
    battery_min_soc_kwh: float = 24.0
    battery_initial_soc_kwh: float = 60.0
    battery_max_charge_kw: float = 30.0
    battery_max_discharge_kw: float = 30.0
    battery_efficiency: float = 0.95
    diesel_capacity_kw: float = 80.0
    ro_rated_power_kw: float = 15.0
    ro_min_power_kw: float = 6.0
    ro_specific_energy_kwh_per_m3: float = 4.0
    ro_recovery_ratio: float = 0.45
    tank_capacity_m3: float = 80.0
    tank_initial_m3: float = 40.0
    mean_essential_load_kw: float = 30.0
    daily_water_demand_m3: float = 40.0
    diesel_cost_per_kwh: float = 0.35
    diesel_litres_per_kwh: float = 0.30
    co2_kg_per_litre_diesel: float = 2.68
    households_served: int = 150


@dataclass(frozen=True)
class StrategyRules:
    """Operating rules for the two strategies being compared."""

    # Baseline: a staffed shift runs RO at full power while the tank is not full.
    baseline_shift_start_hour: int = 7
    baseline_shift_end_hour: int = 19
    baseline_stop_fill_fraction: float = 0.95
    # Coordinated: run RO on renewable surplus whenever there is tank headroom,
    # and fall back to firm RO only when the tank drops below this reserve.
    coordinated_reserve_fraction: float = 0.25
    # Once RO starts it stays on for at least this many hours (while the tank
    # has room), because real membranes do not like frequent stop/starts.
    # 1 means no minimum run time.
    ro_min_run_hours: int = 1
    # Forecast-based coordinated rule: look this many hours ahead at forecast
    # renewable surplus and water demand. Run RO firm now only if the tank is
    # projected to fall below the reserve before surplus arrives.
    forecast_lookahead_hours: int = 12
    # Relative error of the renewable forecast used by that rule (0 = perfect
    # foresight). Errors are seeded and reproducible.
    forecast_error_fraction: float = 0.0
    forecast_error_seed: int = 7


@dataclass
class SyntheticInputs:
    pv_kw: np.ndarray
    wind_kw: np.ndarray
    essential_kw: np.ndarray
    water_demand_m3: np.ndarray
    seed: int
    hours: int

    def sha256(self) -> str:
        payload = np.vstack([self.pv_kw, self.wind_kw, self.essential_kw, self.water_demand_m3])
        return hashlib.sha256(np.round(payload, 6).tobytes()).hexdigest()


@dataclass
class StrategyResult:
    name: str
    hourly: dict[str, np.ndarray] = field(repr=False)
    summary: dict[str, float] = field(default_factory=dict)


def generate_synthetic_inputs(site: IslandSiteConfig, *, days: int = 7, seed: int = 0) -> SyntheticInputs:
    """Build hourly inputs for a generic remote island. Not data from a real site.

    Solar follows a daylight curve scaled by a random daily cloud factor.
    Wind is a smoothed random series with some day-to-day persistence.
    Essential load and water demand have a morning and evening peak.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    rng = np.random.default_rng(seed)
    hours = days * 24
    hour_of_day = np.arange(hours) % 24

    daylight = np.clip(np.sin((hour_of_day - 6) / 12 * math.pi), 0, None)
    cloud = np.repeat(rng.uniform(0.35, 1.0, size=days), 24)
    pv = site.pv_rated_kw * 0.85 * daylight * cloud

    wind_speed = np.empty(hours)
    level = rng.uniform(0.2, 0.7)
    for t in range(hours):
        level = 0.92 * level + 0.08 * rng.uniform(0.0, 1.0)
        wind_speed[t] = level
    wind = site.wind_rated_kw * np.clip(wind_speed + rng.normal(0, 0.05, hours), 0, 1)

    load_shape = 0.8 + 0.25 * np.exp(-((hour_of_day - 8) ** 2) / 6) + 0.4 * np.exp(-((hour_of_day - 19) ** 2) / 5)
    load_shape = load_shape / load_shape.mean()
    essential = site.mean_essential_load_kw * load_shape * rng.normal(1.0, 0.05, hours)
    essential = np.clip(essential, 0, None)

    water_shape = 0.6 + 0.8 * np.exp(-((hour_of_day - 7) ** 2) / 4) + 0.6 * np.exp(-((hour_of_day - 18) ** 2) / 5)
    water_shape = water_shape / water_shape.mean()
    water = site.daily_water_demand_m3 / 24 * water_shape * rng.normal(1.0, 0.05, hours)
    water = np.clip(water, 0, None)

    return SyntheticInputs(pv, wind, essential, water, seed, hours)


def _microgrid_config(site: IslandSiteConfig, soc_kwh: float, tank_m3: float) -> MicrogridConfig:
    return MicrogridConfig(
        battery_capacity_kwh=site.battery_capacity_kwh,
        battery_initial_soc_kwh=soc_kwh,
        battery_min_soc_kwh=site.battery_min_soc_kwh,
        battery_max_charge_kw=site.battery_max_charge_kw,
        battery_max_discharge_kw=site.battery_max_discharge_kw,
        battery_charge_efficiency=site.battery_efficiency,
        battery_discharge_efficiency=site.battery_efficiency,
        grid_import_limit_kw=0.0,
        diesel_capacity_kw=site.diesel_capacity_kw,
        ro_rated_power_kw=site.ro_rated_power_kw,
        ro_specific_energy_kwh_per_m3=site.ro_specific_energy_kwh_per_m3,
        water_tank_capacity_m3=site.tank_capacity_m3,
        water_initial_inventory_m3=tank_m3,
    )


STRATEGIES = ("baseline", "coordinated", "forecast_coordinated")


def renewable_forecast(inputs: SyntheticInputs, rules: StrategyRules) -> np.ndarray:
    """Forecast of hourly renewable power used by the forecast-based rule.

    The forecast is the actual synthetic renewable series with a seeded,
    multiplicative error, so the effect of forecast quality can be tested.
    """
    actual = inputs.pv_kw + inputs.wind_kw
    if rules.forecast_error_fraction <= 0:
        return actual.copy()
    rng = np.random.default_rng(rules.forecast_error_seed)
    return np.clip(actual * (1.0 + rng.normal(0.0, rules.forecast_error_fraction, actual.shape)), 0, None)


def _forecast_needs_firm(t: int, tank_m3: float, inputs: SyntheticInputs, site: IslandSiteConfig,
                         rules: StrategyRules, forecast_kw: np.ndarray) -> bool:
    """True when the tank is projected to drop below the reserve within the
    look-ahead window even after using the forecast renewable surplus."""
    reserve = rules.coordinated_reserve_fraction * site.tank_capacity_m3
    projected = tank_m3
    for k in range(t, min(inputs.hours, t + rules.forecast_lookahead_hours)):
        leftover = max(0.0, float(forecast_kw[k]) - float(inputs.essential_kw[k]))
        ro_kw = min(leftover, site.ro_rated_power_kw)
        if ro_kw < site.ro_min_power_kw:
            ro_kw = 0.0
        projected = min(site.tank_capacity_m3, projected + ro_kw / site.ro_specific_energy_kwh_per_m3)
        projected -= float(inputs.water_demand_m3[k])
        if projected < reserve:
            return True
    return False


def _decide(strategy: str, hour: int, tank_m3: float, site: IslandSiteConfig, rules: StrategyRules,
            inputs: SyntheticInputs | None = None, forecast_kw: np.ndarray | None = None) -> str:
    """Return 'firm', 'surplus' or 'off' for RO in this hour."""
    if strategy == "baseline":
        in_shift = rules.baseline_shift_start_hour <= hour % 24 < rules.baseline_shift_end_hour
        not_full = tank_m3 < rules.baseline_stop_fill_fraction * site.tank_capacity_m3
        return "firm" if in_shift and not_full else "off"
    if strategy == "coordinated":
        if tank_m3 < rules.coordinated_reserve_fraction * site.tank_capacity_m3:
            return "firm"
        return "surplus" if tank_m3 < site.tank_capacity_m3 else "off"
    if strategy == "forecast_coordinated":
        if inputs is None or forecast_kw is None:
            raise ValueError("forecast_coordinated needs the inputs and a renewable forecast")
        if tank_m3 >= site.tank_capacity_m3:
            return "off"
        if _forecast_needs_firm(hour, tank_m3, inputs, site, rules, forecast_kw):
            return "firm"
        return "surplus"
    raise ValueError(f"unknown strategy: {strategy}")


def run_strategy(
    strategy: str,
    inputs: SyntheticInputs,
    site: IslandSiteConfig,
    rules: StrategyRules | None = None,
) -> StrategyResult:
    """Simulate one strategy hour by hour and return hourly series plus a summary."""
    rules = rules or StrategyRules()
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy}")
    if rules.ro_min_run_hours < 1 or rules.forecast_lookahead_hours < 1:
        raise ValueError("ro_min_run_hours and forecast_lookahead_hours must be at least 1")
    forecast_kw = renewable_forecast(inputs, rules) if strategy == "forecast_coordinated" else None
    n = inputs.hours
    keys = (
        "ro_mode_firm", "ro_power_kw", "water_produced_m3", "water_served_m3",
        "unmet_water_m3", "tank_m3", "soc_kwh", "diesel_kw", "battery_discharge_kw",
        "battery_charge_kw", "curtailed_kw", "unserved_essential_kw", "ro_start",
    )
    h = {k: np.zeros(n) for k in keys}
    soc = site.battery_initial_soc_kwh
    tank = site.tank_initial_m3
    ro_was_on = False
    run_hours = 0
    sec = site.ro_specific_energy_kwh_per_m3

    for t in range(n):
        mode = _decide(strategy, t, tank, site, rules, inputs, forecast_kw)
        if ro_was_on and run_hours < rules.ro_min_run_hours and tank < site.tank_capacity_m3:
            # Minimum run time: a plant that started recently keeps running firm.
            mode = "firm"
        headroom_kw = max(0.0, site.tank_capacity_m3 - tank) * sec
        firm_kw = min(site.ro_rated_power_kw, headroom_kw) if mode == "firm" else 0.0
        surplus_request = site.ro_rated_power_kw if mode == "surplus" else 0.0
        # A real RO plant cannot run below a minimum power, so skip the hour
        # when the power it could actually get is under that minimum.
        if firm_kw < site.ro_min_power_kw:
            firm_kw = 0.0
        if surplus_request:
            leftover = max(0.0, inputs.pv_kw[t] + inputs.wind_kw[t] - inputs.essential_kw[t])
            if min(leftover, site.ro_rated_power_kw, headroom_kw) < site.ro_min_power_kw:
                surplus_request = 0.0

        step = simulate_microgrid(
            MicrogridInputs(
                pv_power_kw=[inputs.pv_kw[t]],
                wind_power_kw=[inputs.wind_kw[t]],
                essential_load_kw=[inputs.essential_kw[t] + firm_kw],
                ro_requested_power_kw=[surplus_request],
                water_demand_m3=[0.0],
                diesel_cost_per_kwh=site.diesel_cost_per_kwh,
            ),
            _microgrid_config(site, soc, tank),
        )

        # If anything goes unserved, RO is the first load to lose power.
        unserved = float(step.unserved_essential_kw[0])
        firm_served = max(0.0, firm_kw - unserved)
        ro_kw = firm_served + float(step.ro_power_served_kw[0])
        produced = ro_kw / sec
        available = tank + produced
        served = min(inputs.water_demand_m3[t], available)

        h["ro_mode_firm"][t] = 1.0 if firm_kw > 0 else 0.0
        h["ro_power_kw"][t] = ro_kw
        h["water_produced_m3"][t] = produced
        h["water_served_m3"][t] = served
        h["unmet_water_m3"][t] = inputs.water_demand_m3[t] - served
        h["diesel_kw"][t] = float(step.diesel_generation_kw[0])
        h["battery_discharge_kw"][t] = float(step.battery_discharge_kw[0])
        h["battery_charge_kw"][t] = float(step.battery_charge_kw[0])
        h["curtailed_kw"][t] = float(step.renewable_curtailed_kw[0])
        h["unserved_essential_kw"][t] = max(0.0, unserved - firm_kw)
        h["ro_start"][t] = 1.0 if ro_kw > 1e-6 and not ro_was_on else 0.0
        run_hours = run_hours + 1 if ro_kw > 1e-6 else 0
        ro_was_on = ro_kw > 1e-6

        # Clamp tiny floating-point drift so the next step's config stays valid.
        soc = min(max(float(step.battery_soc_kwh[-1]), site.battery_min_soc_kwh), site.battery_capacity_kwh)
        tank = min(max(available - served, 0.0), site.tank_capacity_m3)
        h["tank_m3"][t] = tank
        h["soc_kwh"][t] = soc

    return StrategyResult(strategy, h, summarise(h, inputs, site))


def summarise(h: dict[str, np.ndarray], inputs: SyntheticInputs, site: IslandSiteConfig) -> dict[str, float]:
    renewable_kwh = float(np.sum(inputs.pv_kw + inputs.wind_kw))
    curtailed_kwh = float(np.sum(h["curtailed_kw"]))
    diesel_kwh = float(np.sum(h["diesel_kw"]))
    litres = diesel_kwh * site.diesel_litres_per_kwh
    demand = float(np.sum(inputs.water_demand_m3))
    unmet = float(np.sum(h["unmet_water_m3"]))
    # Fair comparison: a strategy that ends the period with less water in the
    # tank has borrowed energy from the future. Charge it the diesel needed to
    # refill the tank to its starting level (and credit any surplus the same way).
    refill_kwh = (site.tank_initial_m3 - float(h["tank_m3"][-1])) * site.ro_specific_energy_kwh_per_m3
    adjusted_litres = litres + refill_kwh * site.diesel_litres_per_kwh
    return {
        "days": inputs.hours / 24,
        "renewable_available_kwh": renewable_kwh,
        "renewable_curtailed_kwh": curtailed_kwh,
        "renewable_used_pct": 100.0 * (renewable_kwh - curtailed_kwh) / renewable_kwh if renewable_kwh else 0.0,
        "diesel_kwh": diesel_kwh,
        "diesel_litres": litres,
        "co2_kg": litres * site.co2_kg_per_litre_diesel,
        "diesel_litres_tank_adjusted": adjusted_litres,
        "co2_kg_tank_adjusted": adjusted_litres * site.co2_kg_per_litre_diesel,
        "diesel_cost": diesel_kwh * site.diesel_cost_per_kwh,
        "diesel_hours": float(np.sum(h["diesel_kw"] > 1e-6)),
        "ro_electricity_kwh": float(np.sum(h["ro_power_kw"])),
        "ro_firm_hours": float(np.sum(h["ro_mode_firm"])),
        "ro_starts": float(np.sum(h["ro_start"])),
        "water_demand_m3": demand,
        "water_produced_m3": float(np.sum(h["water_produced_m3"])),
        "unmet_water_m3": unmet,
        "water_service_pct": 100.0 * (demand - unmet) / demand if demand else 100.0,
        "water_litres_per_household_per_day": 1000.0 * (demand - unmet) / (inputs.hours / 24) / site.households_served if site.households_served else 0.0,
        "brine_m3": float(np.sum(h["water_produced_m3"])) * (1.0 / site.ro_recovery_ratio - 1.0),
        "min_tank_m3": float(np.min(h["tank_m3"])),
        "final_tank_m3": float(h["tank_m3"][-1]),
        "unserved_essential_kwh": float(np.sum(h["unserved_essential_kw"])),
    }


def compare(inputs: SyntheticInputs, site: IslandSiteConfig, rules: StrategyRules | None = None) -> dict:
    """Run both strategies on identical inputs and return both summaries and the difference."""
    base = run_strategy("baseline", inputs, site, rules)
    coord = run_strategy("coordinated", inputs, site, rules)
    diff = {k: coord.summary[k] - base.summary[k] for k in base.summary if k != "days"}
    return {"seed": inputs.seed, "input_sha256": inputs.sha256(), "baseline": base, "coordinated": coord, "difference": diff}


def assumptions_record(site: IslandSiteConfig, rules: StrategyRules) -> str:
    return json.dumps({"site": asdict(site), "rules": asdict(rules)}, indent=2, sort_keys=True)


TOU_PRICES = {"off_peak": 0.12, "shoulder": 0.20, "peak": 0.38}


CASES = ("island", "grid_tou", "hybrid_tou")
HYBRID_DIESEL_START_COST = 5.0
HYBRID_GRID_LIMIT_KW = 30.0
# Tank level (m3) the reserve variant of the joint MILP may not go below: a
# quarter of the tank, the same reserve the surplus rule falls back on.
MILP_WATER_RESERVE_M3 = 20.0


def tou_tariff(hours: int) -> list[float]:
    """Illustrative time-of-use tariff (USD/kWh): cheap at night, peak 17:00 to 21:00."""
    prices = []
    for t in range(hours):
        h = t % 24
        if h < 7 or h >= 23:
            prices.append(TOU_PRICES["off_peak"])
        elif 17 <= h < 21:
            prices.append(TOU_PRICES["peak"])
        else:
            prices.append(TOU_PRICES["shoulder"])
    return prices


def energy_system_setup(site: IslandSiteConfig, case: str = "island"):
    """Translate the synthetic island into the shared energy-system and water specs.

    ``case="island"``: off-grid, diesel backup. ``case="grid_tou"``: the same
    site connected to a weak grid (80 kW) with a time-of-use tariff and no diesel.
    ``case="hybrid_tou"``: a very weak TOU grid (30 kW) plus the diesel unit, which then
    pays a start cost (illustrative, 5 USD per start), so the optimizer has to
    decide when diesel is worth starting instead of buying peak power.
    """
    if case not in CASES:
        raise ValueError(f"case must be one of {CASES}")
    from islandos_core.energy_system import BatterySpec, DieselSpec, EnergySystemConfig
    from islandos_core.water_resource_adapter import WaterServiceSpec

    config = EnergySystemConfig(
        pv_rated_kw=site.pv_rated_kw,
        wind_rated_kw=site.wind_rated_kw,
        grid_import_limit_kw={"island": 0.0, "grid_tou": 80.0, "hybrid_tou": HYBRID_GRID_LIMIT_KW}[case],
        battery=BatterySpec(
            capacity_kwh=site.battery_capacity_kwh,
            max_charge_kw=site.battery_max_charge_kw,
            max_discharge_kw=site.battery_max_discharge_kw,
            initial_soc=site.battery_initial_soc_kwh / site.battery_capacity_kwh,
            min_soc=site.battery_min_soc_kwh / site.battery_capacity_kwh,
            max_soc=1.0,
            charge_efficiency=site.battery_efficiency,
            discharge_efficiency=site.battery_efficiency,
        ),
        diesel=DieselSpec(
            rated_power_kw=site.diesel_capacity_kw,
            variable_cost_per_kwh=site.diesel_cost_per_kwh,
            start_cost_per_start=HYBRID_DIESEL_START_COST if case == "hybrid_tou" else 0.0,
        ),
    )
    water = WaterServiceSpec(
        specific_energy_kwh_per_m3=site.ro_specific_energy_kwh_per_m3,
        ro_capacity_m3_per_hour=site.ro_rated_power_kw / site.ro_specific_energy_kwh_per_m3,
        tank_capacity_m3=site.tank_capacity_m3,
        initial_inventory_m3=site.tank_initial_m3,
        reserve_m3=0.0,
    )
    return config, water


def _energy_inputs(inputs: SyntheticInputs, case: str, extra_load_kw=None):
    from islandos_core.energy_system import EnergySystemInputs

    n = inputs.hours
    extra = extra_load_kw if extra_load_kw is not None else [0.0] * n
    return EnergySystemInputs(
        pv_generation_kw=[float(x) for x in inputs.pv_kw],
        wind_generation_kw=[float(x) for x in inputs.wind_kw],
        load_kw=[float(e) + float(r) for e, r in zip(inputs.essential_kw, extra)],
        grid_price_per_kwh=[0.0] * n if case == "island" else tou_tariff(n),
        grid_available=[case != "island"] * n,
        diesel_available=[case != "grid_tou"] * n,
    )


def _replay(inputs: SyntheticInputs, site: IslandSiteConfig, ro_power_kw, config, case: str = "island") -> dict:
    from islandos_core.energy_system import dispatch_energy_system

    result = dispatch_energy_system(_energy_inputs(inputs, case, ro_power_kw), config, policy="battery_first")
    return result["summary"]


def _strategy_row(name: str, summary: dict, ending_tank: float, water_unmet_m3: float,
                  site: IslandSiteConfig, case: str, extra: dict | None = None) -> dict:
    """One comparable row. Each strategy is charged (or credited) for refilling
    its tank to the starting level: at the diesel rate on the island, and at the
    average tariff on the grid."""
    refill_kwh = (site.tank_initial_m3 - ending_tank) * site.ro_specific_energy_kwh_per_m3
    diesel_kwh = float(summary["diesel_generation_kwh"])
    litres = diesel_kwh * site.diesel_litres_per_kwh
    row = {
        "strategy": name,
        "case": case,
        "diesel_kwh": diesel_kwh,
        "grid_kwh": float(summary.get("grid_import_kwh", 0.0)),
        "energy_cost": float(summary["estimated_energy_cost"]),
        "ending_tank_m3": ending_tank,
        "unmet_electric_kwh": float(summary["unmet_load_kwh"]),
        "unmet_water_m3": water_unmet_m3,
    }
    if case == "island":
        adjusted = litres + refill_kwh * site.diesel_litres_per_kwh
        row.update({
            "diesel_litres": litres,
            "diesel_litres_tank_adjusted": adjusted,
            "co2_kg_tank_adjusted": adjusted * site.co2_kg_per_litre_diesel,
            "headline_tank_adjusted": adjusted,
        })
    else:
        mean_price = sum(TOU_PRICES[k] * w for k, w in (("off_peak", 8), ("shoulder", 12), ("peak", 4))) / 24
        adjusted_cost = row["energy_cost"] + refill_kwh * mean_price
        row.update({"energy_cost_tank_adjusted": adjusted_cost, "headline_tank_adjusted": adjusted_cost})
    row.update(extra or {})
    return row


def compare_with_optimizer(
    inputs: SyntheticInputs,
    site: IslandSiteConfig,
    rules: StrategyRules | None = None,
    *,
    case: str = "island",
    time_limit_seconds: float = 120.0,
    mip_relative_gap: float = 0.0,
) -> dict:
    """Compare rule strategies with the joint water-energy MILP on identical inputs.

    Every strategy's electricity is replayed through ``dispatch_energy_system``
    (battery first), so all share the same physics. The MILP must end with at
    least the starting tank volume and respects the RO minimum power. On the
    island the headline metric is tank-adjusted diesel litres; on the grid case
    it is tank-adjusted energy cost, and the tariff-look-ahead RO rule is added.
    """
    from islandos_core.water_resource_adapter import build_ro_energy_load
    from islandos_core.water_dispatch import build_price_aware_ro_schedule
    from optimization.milp_dispatch_optimizer import optimize_dispatch_milp

    rules = rules or StrategyRules()
    config, water = energy_system_setup(site, case)
    demand = [float(x) for x in inputs.water_demand_m3]
    rows = []

    for name in ("baseline", "coordinated"):
        sim = run_strategy(name, inputs, site, rules)
        summary = _replay(inputs, site, sim.hourly["ro_power_kw"], config, case)
        rows.append(_strategy_row(
            "fixed_timetable" if name == "baseline" else "surplus_rule",
            summary, float(sim.hourly["tank_m3"][-1]), float(sim.summary["unmet_water_m3"]), site, case,
        ))

    from dataclasses import replace as _replace

    for label, variant_rules, note in (
        ("forecast_rule", rules, "forecast-based rule, perfect renewable forecast"),
        ("forecast_rule_realistic",
         _replace(rules, forecast_error_fraction=0.2, ro_min_run_hours=3),
         "forecast-based rule, 20% renewable forecast error, RO minimum run 3 h"),
    ):
        sim = run_strategy("forecast_coordinated", inputs, site, variant_rules)
        rows.append(_strategy_row(
            label, _replay(inputs, site, sim.hourly["ro_power_kw"], config, case),
            float(sim.hourly["tank_m3"][-1]), float(sim.summary["unmet_water_m3"]), site, case,
            {"note": note, "ro_starts": float(sim.summary["ro_starts"])},
        ))

    jit = build_ro_energy_load(demand, spec=water, dt_hours=1.0)
    rows.append(_strategy_row(
        "just_in_time", _replay(inputs, site, jit.ro_power_kw, config, case),
        float(jit.inventory_after_demand_m3[-1]), 0.0, site, case,
        {"note": "no RO minimum power; produces only what each hour needs"},
    ))

    if case != "island":
        aware = build_price_aware_ro_schedule(demand, tou_tariff(inputs.hours), spec=water, lookahead_hours=12)
        rows.append(_strategy_row(
            "tariff_lookahead", _replay(inputs, site, aware["ro_power_kw"], config, case),
            float(aware["inventory_end_m3"][-1]), 0.0, site, case,
            {"note": "existing price-aware RO heuristic, 12-hour look-ahead; no RO minimum power"},
        ))

    # Control: optimise the battery and diesel/grid only, with RO kept on the
    # fixed timetable. The gap between this and the joint MILP is what RO
    # timing adds; the gap to the fixed timetable is what battery scheduling adds.
    fixed_sim = run_strategy("baseline", inputs, site, rules)
    battery_only = optimize_dispatch_milp(
        _energy_inputs(inputs, case, fixed_sim.hourly["ro_power_kw"]),
        config,
        time_limit_seconds=time_limit_seconds,
        mip_relative_gap=mip_relative_gap,
    )
    rows.append(_strategy_row(
        "milp_battery_only_fixed_ro", battery_only["dispatch"]["summary"],
        float(fixed_sim.hourly["tank_m3"][-1]), 0.0, site, case,
        {"solver_status": battery_only["solver_status"],
         "optimality_proven": battery_only["optimality_proven_for_declared_milp"]},
    ))

    milp = optimize_dispatch_milp(
        _energy_inputs(inputs, case),
        config,
        water_service=water,
        water_demand_m3_per_hour=demand,
        terminal_water_inventory_min_m3=site.tank_initial_m3,
        ro_min_production_m3_per_hour=site.ro_min_power_kw / site.ro_specific_energy_kwh_per_m3,
        time_limit_seconds=time_limit_seconds,
        mip_relative_gap=mip_relative_gap,
    )
    rows.append(_strategy_row(
        "joint_milp", milp["dispatch"]["summary"], float(milp["water_service"]["ending_inventory_m3"]),
        0.0, site, case,
        {"solver_status": milp["solver_status"], "mip_gap": milp["mip_gap"],
         "solve_time_seconds": milp["solve_time_seconds"],
         "optimality_proven": milp["optimality_proven_for_declared_milp"]},
    ))
    # Same optimisation, but the tank may not drop below a reserve. This is
    # the price of keeping a buffer for demand the forecast did not expect.
    reserved = optimize_dispatch_milp(
        _energy_inputs(inputs, case),
        config,
        water_service=_replace(water, reserve_m3=MILP_WATER_RESERVE_M3),
        water_demand_m3_per_hour=demand,
        terminal_water_inventory_min_m3=site.tank_initial_m3,
        ro_min_production_m3_per_hour=site.ro_min_power_kw / site.ro_specific_energy_kwh_per_m3,
        time_limit_seconds=time_limit_seconds,
        mip_relative_gap=mip_relative_gap,
    )
    rows.append(_strategy_row(
        "joint_milp_with_reserve", reserved["dispatch"]["summary"],
        float(reserved["water_service"]["ending_inventory_m3"]), 0.0, site, case,
        {"solver_status": reserved["solver_status"], "reserve_m3": MILP_WATER_RESERVE_M3,
         "optimality_proven": reserved["optimality_proven_for_declared_milp"]},
    ))
    return {"seed": inputs.seed, "case": case, "input_sha256": inputs.sha256(), "strategies": rows}


def flexible_load_study(
    inputs: SyntheticInputs,
    site: IslandSiteConfig,
    *,
    case: str = "island",
    energy_kwh_per_day: float = 40.0,
    max_power_kw: float = 10.0,
    window: tuple[int, int] = (6, 22),
    time_limit_seconds: float = 60.0,
) -> dict:
    """What does letting the optimizer time one flexible load add?

    The flexible load stands for something like ice making or pumping: a fixed
    amount of energy that must be delivered inside a daily window, at any power
    up to ``max_power_kw``. RO stays on the fixed timetable in all three rows,
    so the only differences are battery scheduling and flexible-load timing.

    Rows: rule dispatch with the load run as early as allowed; the MILP with
    the load still run early (battery scheduling only); the MILP choosing the
    timing as well. Use one-day inputs: the energy budget covers the whole horizon.
    """
    from islandos_core.energy_system import dispatch_energy_system
    from optimization.milp_dispatch_optimizer import optimize_dispatch_milp

    config, _ = energy_system_setup(site, case)
    n = inputs.hours
    total_kwh = energy_kwh_per_day * n / 24.0
    available = [window[0] <= t % 24 < window[1] for t in range(n)]
    ro_kw = run_strategy("baseline", inputs, site).hourly["ro_power_kw"]

    early, remaining = [0.0] * n, total_kwh
    for t in range(n):
        if available[t] and remaining > 1e-12:
            early[t] = min(max_power_kw, remaining)
            remaining -= early[t]
    fixed_load = [float(a) + b for a, b in zip(ro_kw, early)]

    rule = dispatch_energy_system(_energy_inputs(inputs, case, fixed_load), config, policy="battery_first")["summary"]
    battery_only = optimize_dispatch_milp(
        _energy_inputs(inputs, case, fixed_load), config, time_limit_seconds=time_limit_seconds)
    joint = optimize_dispatch_milp(
        _energy_inputs(inputs, case, ro_kw), config, time_limit_seconds=time_limit_seconds,
        flexible_load_energy_kwh=total_kwh, flexible_load_available_steps=available,
        flexible_load_max_power_kw=max_power_kw,
    )

    def row(name: str, summary: dict, extra: dict | None = None) -> dict:
        out = {
            "strategy": name,
            "energy_cost": float(summary["estimated_energy_cost"]),
            "diesel_litres": float(summary["diesel_generation_kwh"]) * site.diesel_litres_per_kwh,
            "curtailed_kwh": float(summary["renewable_curtailed_kwh"]),
            "unmet_electric_kwh": float(summary["unmet_load_kwh"]),
        }
        out.update(extra or {})
        return out

    return {
        "seed": inputs.seed, "case": case, "flexible_energy_kwh": total_kwh,
        "window_hours": list(window), "max_power_kw": max_power_kw,
        "strategies": [
            row("rule_dispatch_early_flexible_load", rule),
            row("milp_battery_only_early_flexible_load", battery_only["dispatch"]["summary"],
                {"optimality_proven": battery_only["optimality_proven_for_declared_milp"]}),
            row("milp_joint_flexible_load", joint["dispatch"]["summary"],
                {"optimality_proven": joint["optimality_proven_for_declared_milp"],
                 "flexible_power_kw": joint["flexible_load"]["power_kw"]}),
        ],
    }
