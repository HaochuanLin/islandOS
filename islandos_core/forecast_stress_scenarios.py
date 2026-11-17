"""Transparent directional stress scenarios from marginal forecast intervals."""
from __future__ import annotations

import math
from numbers import Real
from typing import Mapping, Sequence


def build_interval_stress_scenarios(
    forecast_intervals: Mapping[str, Mapping[str, Sequence[float]]],
    *,
    renewable_signals: Sequence[str] = ("pv_generation_kw", "wind_generation_kw"),
    demand_signals: Sequence[str] = ("load_kw", "water_demand_m3_per_hour"),
    cost_signals: Sequence[str] = ("grid_price_per_kwh",),
) -> dict:
    """Build deterministic stress cases; do not infer joint probabilities."""
    if not isinstance(forecast_intervals, Mapping) or not forecast_intervals:
        raise ValueError("forecast_intervals must be a non-empty mapping")
    roles = {
        "renewable": tuple(renewable_signals),
        "demand": tuple(demand_signals),
        "cost": tuple(cost_signals),
    }
    all_roles = [name for group in roles.values() for name in group]
    if len(all_roles) != len(set(all_roles)):
        raise ValueError("a signal cannot belong to more than one stress role")

    normalized = {}
    horizon = None
    for signal, bounds in forecast_intervals.items():
        if not isinstance(signal, str) or not signal.strip() or not isinstance(bounds, Mapping):
            raise ValueError("each forecast signal must map to central/lower/upper sequences")
        parsed = {}
        for key in ("central", "lower", "upper"):
            if key not in bounds or isinstance(bounds[key], (str, bytes)):
                raise ValueError(f"{signal}.{key} must be a numeric sequence")
            try:
                raw = list(bounds[key])
            except TypeError as exc:
                raise ValueError(f"{signal}.{key} must be a numeric sequence") from exc
            values = []
            for index, value in enumerate(raw):
                if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
                    raise ValueError(f"{signal}.{key}[{index}] must be finite numeric data")
                values.append(float(value))
            if not values:
                raise ValueError(f"{signal}.{key} cannot be empty")
            if horizon is None:
                horizon = len(values)
            if len(values) != horizon:
                raise ValueError("all forecast signals must share the same horizon")
            parsed[key] = values
        if any(lo > mid or mid > hi for lo, mid, hi in zip(parsed["lower"], parsed["central"], parsed["upper"])):
            raise ValueError(f"{signal} must satisfy lower <= central <= upper")
        normalized[signal] = parsed

    unknown_roles = set(all_roles) - set(normalized)
    if unknown_roles:
        raise ValueError(f"stress role signals are missing forecast intervals: {sorted(unknown_roles)}")

    def make_scenario(mode: str) -> dict:
        result = {}
        for signal, bounds in normalized.items():
            role = next((name for name, members in roles.items() if signal in members), None)
            use_bound = (
                mode == "combined"
                or (mode == "renewable_low_demand_high" and role in ("renewable", "demand"))
                or (mode == "cost_high" and role == "cost")
            )
            if not use_bound or role is None:
                result[signal] = list(bounds["central"])
            elif role == "renewable":
                result[signal] = list(bounds["lower"])
            else:
                result[signal] = list(bounds["upper"])
        return result

    return {
        "scenarios": {
            "central": {key: list(value["central"]) for key, value in normalized.items()},
            "renewable_low_demand_high": make_scenario("renewable_low_demand_high"),
            "cost_high": make_scenario("cost_high"),
            "combined_stress": make_scenario("combined"),
        },
        "scenario_probabilities": None,
        "probability_status": "not_assigned_marginal_intervals_do_not_define_joint_probabilities",
        "uncertainty_scope": "deterministic_directional_stress_cases",
        "signal_roles": {key: list(value) for key, value in roles.items()},
        "horizon_steps": horizon,
        "input_signal_names": list(normalized),
    }
