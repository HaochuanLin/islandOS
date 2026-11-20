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


def _decide(strategy: str, hour: int, tank_m3: float, site: IslandSiteConfig, rules: StrategyRules) -> str:
    """Return 'firm', 'surplus' or 'off' for RO in this hour."""
    if strategy == "baseline":
        in_shift = rules.baseline_shift_start_hour <= hour % 24 < rules.baseline_shift_end_hour
        not_full = tank_m3 < rules.baseline_stop_fill_fraction * site.tank_capacity_m3
        return "firm" if in_shift and not_full else "off"
    if strategy == "coordinated":
        if tank_m3 < rules.coordinated_reserve_fraction * site.tank_capacity_m3:
            return "firm"
        return "surplus" if tank_m3 < site.tank_capacity_m3 else "off"
    raise ValueError(f"unknown strategy: {strategy}")


def run_strategy(
    strategy: str,
    inputs: SyntheticInputs,
    site: IslandSiteConfig,
    rules: StrategyRules | None = None,
) -> StrategyResult:
    """Simulate one strategy hour by hour and return hourly series plus a summary."""
    rules = rules or StrategyRules()
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
    sec = site.ro_specific_energy_kwh_per_m3

    for t in range(n):
        mode = _decide(strategy, t, tank, site, rules)
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
