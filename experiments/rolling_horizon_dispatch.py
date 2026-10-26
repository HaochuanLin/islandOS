"""Receding-horizon dispatch prototype for IslandOS.

At each hour, evaluate the two load priorities over a finite forecast horizon,
execute only the first hour against realized surplus, carry inventories and RO
minimum-run commitment forward, and replan. Inputs are synthetic. This models
a simple run commitment, not plant interlocks or full operational feasibility.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dispatch_engine import dispatch_flexible_loads
from experiments.compare_dispatch_policies import (
    Scenario, build_scenarios, make_ice, make_ro,
)
from flexible_loads import IceStorageConfig, IceStorageLoad, ROConfig, ROWaterLoad


HORIZON_HOURS = 3


def _make_ro_with_inventory(water_m3: float) -> ROWaterLoad:
    base = make_ro().config
    return ROWaterLoad(replace(base, initial_water_m3=water_m3))


def _make_ice_with_inventory(cold_kwh_th: float) -> IceStorageLoad:
    base = make_ice().config
    return IceStorageLoad(replace(base, initial_storage_kwh_th=cold_kwh_th))


def _run_horizon(
    power, water_demand, cooling_demand, water_inventory, cold_inventory,
    priority, ro_run_hours_remaining=0, ro_fault_lockout_hours_remaining=0,
):
    ro = _make_ro_with_inventory(water_inventory)
    ice = _make_ice_with_inventory(cold_inventory)
    requests = (
        [(ro, water_demand), (ice, cooling_demand)]
        if priority == "ro_first"
        else [(ice, cooling_demand), (ro, water_demand)]
    )
    return dispatch_flexible_loads(
        power, requests,
        initial_ro_run_hours_remaining=ro_run_hours_remaining,
        initial_ro_fault_lockout_hours_remaining=ro_fault_lockout_hours_remaining,
    )


def _score(result, water_demand, cooling_demand) -> float:
    water_total = max(float(np.sum(water_demand)), 1e-9)
    cooling_total = max(float(np.sum(cooling_demand)), 1e-9)
    ro = result.loads.get("ro_desalination")
    ice = result.loads.get("ice_cold_storage")
    water_unmet = float(np.sum(ro.unmet_demand)) if ro else water_total
    cooling_unmet = float(np.sum(ice.unmet_demand)) if ice else cooling_total
    total_available = max(float(np.sum(result.initial_available_power_kw)), 1e-9)
    surplus_ratio = float(np.sum(result.remaining_power_kw)) / total_available
    return 0.45 * water_unmet / water_total + 0.45 * cooling_unmet / cooling_total + 0.10 * surplus_ratio


def _execute_one(
    actual_power, water_demand, cooling_demand, water_inventory, cold_inventory,
    priority, ro_run_hours_remaining=0, ro_fault_lockout_hours_remaining=0, start_ro=False,
):
    # A planned start commits the unit for its configured minimum run even
    # though this call executes only one realized hour.
    initial_commitment = ro_run_hours_remaining
    if start_ro and initial_commitment == 0:
        initial_commitment = make_ro().config.min_run_hours
    result = _run_horizon(
        [actual_power], [water_demand], [cooling_demand],
        water_inventory, cold_inventory, priority, initial_commitment,
        ro_fault_lockout_hours_remaining,
    )
    ro = result.loads.get("ro_desalination")
    ice = result.loads.get("ice_cold_storage")
    return {
        "water_inventory": float(ro.inventory[-1]) if ro else water_inventory,
        "cold_inventory": float(ice.inventory[-1]) if ice else cold_inventory,
        "water_inventory_before": float(water_inventory),
        "cold_inventory_before": float(cold_inventory),
        "water_produced": float(ro.resource_produced[0]) if ro else 0.0,
        "water_served": float(ro.demand_served[0]) if ro else 0.0,
        "water_spill": float(ro.spill[0]) if ro else 0.0,
        "cooling_produced": float(ice.resource_produced[0]) if ice else 0.0,
        "cooling_served": float(ice.demand_served[0]) if ice else 0.0,
        "cooling_spill": float(ice.spill[0]) if ice else 0.0,
        "water_unmet": float(ro.unmet_demand.sum()) if ro else water_demand,
        "cooling_unmet": float(ice.unmet_demand.sum()) if ice else cooling_demand,
        "renewable_used": float(result.renewable_power_used_kw.sum()),
        "remaining_surplus": float(result.remaining_power_kw.sum()),
        "constraint_violations": int(sum(np.sum(x.constraint_violation) for x in result.loads.values())),
        "ro_active": bool(ro is not None and ro.active[0]),
        "ro_operating_state": str(ro.operating_state[0]) if ro is not None and ro.operating_state is not None else "OFF",
        "ro_power_kw": float(ro.power_used_kw[0]) if ro else 0.0,
        "ro_constraint_violation": int(ro.constraint_violation[0]) if ro else 0,
        "ice_active": bool(ice is not None and ice.active[0]),
        "ice_power_kw": float(ice.power_used_kw[0]) if ice else 0.0,
        "ro_run_hours_remaining": int(ro.run_hours_remaining) if ro else ro_run_hours_remaining,
        "ro_fault_lockout_hours_remaining": int(ro.fault_lockout_hours_remaining) if ro else ro_fault_lockout_hours_remaining,
    }


def parse_scenario_csv(text: str, name: str = "uploaded_csv") -> dict:
    """Parse an aligned hourly power/water/cooling CSV for the rolling dispatcher.

    Required columns: timestamp_utc, actual_surplus_kw, forecast_surplus_kw,
    water_demand_m3, cooling_demand_kw_th. An optional forecast_water_demand_m3
    column supplies planning demand separately from realized demand.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("CSV input must be non-empty text")
    reader = csv.DictReader(io.StringIO(text))
    required = {
        "timestamp_utc", "actual_surplus_kw", "forecast_surplus_kw",
        "water_demand_m3", "cooling_demand_kw_th",
    }
    if not reader.fieldnames:
        raise ValueError("CSV must include a header row")
    headers = reader.fieldnames
    if any(not isinstance(header, str) or not header.strip() for header in headers):
        raise ValueError("CSV column names must be non-empty")
    if len(headers) != len(set(headers)):
        raise ValueError("CSV column names must be unique")
    missing = sorted(required - set(headers))
    if missing:
        raise ValueError(f"CSV missing required columns: {', '.join(missing)}")
    rows = list(reader)
    if not rows:
        raise ValueError("CSV must contain at least one data row")
    for index, row in enumerate(rows, start=2):
        if None in row:
            raise ValueError(f"row {index}: CSV has extra fields beyond the header")
        if any(row.get(header) is None for header in headers):
            raise ValueError(f"row {index}: CSV has fewer fields than the header")

    timestamps = []
    numeric = {key: [] for key in (
        "actual_surplus_kw", "forecast_surplus_kw", "water_demand_m3", "cooling_demand_kw_th"
    )}
    has_forecast_water = "forecast_water_demand_m3" in reader.fieldnames
    forecast_water = []
    for index, row in enumerate(rows, start=2):
        stamp_text = (row.get("timestamp_utc") or "").strip()
        try:
            stamp = datetime.fromisoformat(stamp_text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"row {index}: timestamp_utc must be a valid ISO-8601 timestamp") from exc
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError(f"row {index}: timestamp_utc must include a timezone")
        stamp = stamp.astimezone(timezone.utc)
        if timestamps:
            delta = stamp - timestamps[-1]
            if delta <= timedelta(0):
                raise ValueError("timestamp_utc values must be strictly increasing after UTC normalization")
            if delta != timedelta(hours=1):
                raise ValueError("timestamp_utc values must be exactly one hour apart")
        timestamps.append(stamp)

        for key in numeric:
            raw_value = (row.get(key) or "").strip()
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise ValueError(f"row {index}: {key} must be numeric") from exc
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"row {index}: {key} must be finite and non-negative")
            numeric[key].append(value)

        if has_forecast_water:
            raw_value = (row.get("forecast_water_demand_m3") or "").strip()
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise ValueError(f"row {index}: forecast_water_demand_m3 must be numeric") from exc
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"row {index}: forecast_water_demand_m3 must be finite and non-negative")
            forecast_water.append(value)

    scenario = Scenario(
        name=str(name),
        available_surplus_kw=tuple(numeric["actual_surplus_kw"]),
        water_demand_m3_per_hour=tuple(numeric["water_demand_m3"]),
        cooling_demand_kw_th=tuple(numeric["cooling_demand_kw_th"]),
    )
    return {
        "scenario": scenario,
        "forecast_surplus_kw": tuple(numeric["forecast_surplus_kw"]),
        "forecast_water_demand_m3_per_hour": tuple(forecast_water) if has_forecast_water else None,
        "timestamps_utc": tuple(stamp.isoformat().replace("+00:00", "Z") for stamp in timestamps),
    }


def generate_synthetic_scenario_csv(hours: int = 24) -> str:
    """Return a deterministic, explicitly synthetic paired hourly dispatch CSV."""
    if isinstance(hours, bool) or not isinstance(hours, int) or hours < 1 or hours > 168:
        raise ValueError("hours must be an integer from 1 to 168")
    output = io.StringIO(newline="")
    fields = [
        "timestamp_utc", "actual_surplus_kw", "forecast_surplus_kw",
        "water_demand_m3", "cooling_demand_kw_th", "forecast_water_demand_m3",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(hours):
        actual_surplus = 0.0 if index % 6 == 3 else float(15 + (index % 8) * 4)
        forecast_surplus = max(0.0, actual_surplus + (8.0 if index % 4 == 0 else -5.0))
        water_demand = float(4 + index % 4)
        cooling_demand = float(6 + index % 5)
        forecast_water = max(0.0, water_demand + (1.0 if index % 3 == 0 else -0.5))
        writer.writerow({
            "timestamp_utc": (start + timedelta(hours=index)).isoformat().replace("+00:00", "Z"),
            "actual_surplus_kw": actual_surplus,
            "forecast_surplus_kw": forecast_surplus,
            "water_demand_m3": water_demand,
            "cooling_demand_kw_th": cooling_demand,
            "forecast_water_demand_m3": forecast_water,
        })
    return output.getvalue()


def simulate_rolling(
    scenario: Scenario,
    forecast_surplus,
    policy: str = "rolling",
    forecast_water_demand_m3_per_hour=None,
    forecast_cooling_demand_kw_th=None,
) -> dict:
    """Simulate one-hour commits with causal forecasts and realized execution.

    If a demand forecast is omitted, use persistence based only on the current
    observation. Future realized demand is reserved for the offline hindsight
    reference policy and never leaks into forecast-based planning.
    """
    actual = np.asarray(scenario.available_surplus_kw, dtype=float)
    forecast = np.asarray(forecast_surplus, dtype=float)
    water_demand = np.asarray(scenario.water_demand_m3_per_hour, dtype=float)
    cooling_demand = np.asarray(scenario.cooling_demand_kw_th, dtype=float)
    water_forecast = (
        None if forecast_water_demand_m3_per_hour is None
        else np.asarray(forecast_water_demand_m3_per_hour, dtype=float)
    )
    cooling_forecast = (
        None if forecast_cooling_demand_kw_th is None
        else np.asarray(forecast_cooling_demand_kw_th, dtype=float)
    )

    # Validate the realized scenario at this public entry point as well as
    # validating CSV inputs. Callers may construct Scenario objects directly.
    realized_series = {
        "available_surplus_kw": actual,
        "water_demand_m3_per_hour": water_demand,
        "cooling_demand_kw_th": cooling_demand,
    }
    if actual.ndim != 1 or actual.size == 0:
        raise ValueError("scenario series must be non-empty one-dimensional arrays")
    for name, values in realized_series.items():
        if values.ndim != 1 or values.shape != actual.shape:
            raise ValueError(f"{name} must match the non-empty scenario horizon")
        if not np.all(np.isfinite(values)) or np.any(values < 0):
            raise ValueError(f"{name} must be finite and non-negative")
    if forecast.ndim != 1 or forecast.shape != actual.shape:
        raise ValueError("forecast_surplus must match the one-dimensional scenario horizon")
    if not np.all(np.isfinite(forecast)) or np.any(forecast < 0):
        raise ValueError("forecast_surplus must be finite and non-negative")
    for name, values in (
        ("forecast_water_demand_m3_per_hour", water_forecast),
        ("forecast_cooling_demand_kw_th", cooling_forecast),
    ):
        if values is not None:
            if values.ndim != 1 or values.shape != actual.shape:
                raise ValueError(f"{name} must match the scenario horizon")
            if not np.all(np.isfinite(values)) or np.any(values < 0):
                raise ValueError(f"{name} must be finite and non-negative")
    if policy not in ("rolling", "ro_first", "ice_first", "perfect_information"):
        raise ValueError("policy must be rolling, ro_first, ice_first, or perfect_information")

    water_inventory = make_ro().config.initial_water_m3
    cold_inventory = make_ice().config.initial_storage_kwh_th
    ro_run_hours_remaining = 0
    ro_fault_lockout_hours_remaining = 0
    totals = {"water_unmet_m3": 0.0, "cooling_unmet_kwh_th": 0.0,
              "renewable_flexible_load_kwh": 0.0, "remaining_surplus_kwh": 0.0,
              "constraint_violation_hours": 0}
    decisions = []
    hourly_audit = []
    violation_steps = []

    for t in range(len(actual)):
        end = min(len(actual), t + HORIZON_HOURS)
        horizon_len = end - t
        # Causal persistence: today's observation is held across the planning
        # horizon rather than reading future realized demand from the scenario.
        water_plan = (
            water_forecast[t:end] if water_forecast is not None
            else np.full(horizon_len, water_demand[t], dtype=float)
        )
        cooling_plan = (
            cooling_forecast[t:end] if cooling_forecast is not None
            else np.full(horizon_len, cooling_demand[t], dtype=float)
        )
        planning_power = forecast[t:end]
        if policy == "rolling":
            candidates = []
            for priority in ("ro_first", "ice_first"):
                predicted = _run_horizon(
                    planning_power, water_plan, cooling_plan,
                    water_inventory, cold_inventory, priority,
                    ro_run_hours_remaining, ro_fault_lockout_hours_remaining,
                )
                candidates.append((
                    _score(predicted, water_plan, cooling_plan),
                    priority, predicted,
                ))
            _, chosen, chosen_plan = min(candidates, key=lambda item: (item[0], item[1]))
            ro_plan = chosen_plan.loads.get("ro_desalination")
            start_ro = bool(ro_plan is not None and ro_plan.active[0] and ro_run_hours_remaining == 0)
        elif policy in ("ro_first", "ice_first", "perfect_information"):
            if policy == "perfect_information":
                # Hindsight upper bound only; this is not a deployable policy.
                info_water = water_demand[t:end]
                info_cooling = cooling_demand[t:end]
                candidates = []
                for priority in ("ro_first", "ice_first"):
                    predicted = _run_horizon(
                        actual[t:end], info_water, info_cooling,
                        water_inventory, cold_inventory, priority,
                        ro_run_hours_remaining, ro_fault_lockout_hours_remaining,
                    )
                    candidates.append((
                        _score(predicted, info_water, info_cooling),
                        priority, predicted,
                    ))
                _, chosen, chosen_plan = min(candidates, key=lambda item: (item[0], item[1]))
                ro_plan = chosen_plan.loads.get("ro_desalination")
                start_ro = bool(ro_plan is not None and ro_plan.active[0] and ro_run_hours_remaining == 0)
            else:
                chosen = policy
                plan = _run_horizon(
                    planning_power, water_plan, cooling_plan,
                    water_inventory, cold_inventory, chosen, ro_run_hours_remaining,
                    ro_fault_lockout_hours_remaining,
                )
                ro_plan = plan.loads.get("ro_desalination")
                start_ro = bool(ro_plan is not None and ro_plan.active[0] and ro_run_hours_remaining == 0)
        else:
            raise ValueError("policy must be rolling, ro_first, ice_first, or perfect_information")

        step = _execute_one(
            actual[t], water_demand[t], cooling_demand[t],
            water_inventory, cold_inventory, chosen, ro_run_hours_remaining,
            ro_fault_lockout_hours_remaining, start_ro,
        )
        water_inventory = step["water_inventory"]
        cold_inventory = step["cold_inventory"]
        ro_run_hours_remaining = step["ro_run_hours_remaining"]
        ro_fault_lockout_hours_remaining = step["ro_fault_lockout_hours_remaining"]
        totals["water_unmet_m3"] += step["water_unmet"]
        totals["cooling_unmet_kwh_th"] += step["cooling_unmet"]
        totals["renewable_flexible_load_kwh"] += step["renewable_used"]
        totals["remaining_surplus_kwh"] += step["remaining_surplus"]
        totals["constraint_violation_hours"] += int(step["constraint_violations"] > 0)
        decisions.append(chosen)
        hourly_audit.append({
            "hour_index": t,
            "actual_surplus_kw": float(actual[t]),
            "forecast_surplus_kw": float(forecast[t]),
            "actual_water_demand_m3": float(water_demand[t]),
            "forecast_water_demand_m3": float(water_plan[0]),
            "planning_water_demand_m3": float(water_plan[0]),
            "actual_cooling_demand_kw_th": float(cooling_demand[t]),
            "forecast_cooling_demand_kw_th": float(cooling_plan[0]),
            "planning_cooling_demand_kw_th": float(cooling_plan[0]),
            "demand_forecast_method": (
                "explicit_forecast" if water_forecast is not None or cooling_forecast is not None
                else "causal_persistence_fallback"
            ),
            "priority": chosen,
            "ro_active": step["ro_active"],
            "ro_operating_state": step["ro_operating_state"],
            "ro_power_kw": round(step["ro_power_kw"], 6),
            "ice_power_kw": round(step["ice_power_kw"], 6),
            "ro_constraint_violation": step["ro_constraint_violation"],
            "ro_run_hours_remaining": step["ro_run_hours_remaining"],
            "ro_fault_lockout_hours_remaining": step["ro_fault_lockout_hours_remaining"],
            "water_inventory_before_m3": round(step["water_inventory_before"], 6),
            "water_produced_m3": round(step["water_produced"], 6),
            "water_served_m3": round(step["water_served"], 6),
            "water_spill_m3": round(step["water_spill"], 6),
            "water_inventory_m3": round(water_inventory, 6),
            "cold_inventory_before_kwh_th": round(step["cold_inventory_before"], 6),
            "cooling_produced_kwh_th": round(step["cooling_produced"], 6),
            "cooling_served_kwh_th": round(step["cooling_served"], 6),
            "cooling_spill_kwh_th": round(step["cooling_spill"], 6),
            "cold_inventory_kwh_th": round(cold_inventory, 6),
            "total_constraint_violations": step["constraint_violations"],
        })
        if step["constraint_violations"]:
            violation_steps.append(t)

    return {
        "policy": policy,
        "demand_forecast_policy": {
            "water": "explicit_forecast" if water_forecast is not None else "causal_persistence_fallback",
            "cooling": "explicit_forecast" if cooling_forecast is not None else "causal_persistence_fallback",
            "perfect_information_is_offline_reference": policy == "perfect_information",
        },
        **{key: round(value, 3) for key, value in totals.items()},
        "final_water_inventory_m3": round(water_inventory, 3),
        "final_cold_inventory_kwh_th": round(cold_inventory, 3),
        "hourly_priority_decisions": decisions,
        "hourly_audit": hourly_audit,
        "constraint_violation_hour_indices": violation_steps,
    }


def run_experiment() -> list[dict]:
    rows = []
    for scenario in build_scenarios():
        actual = np.asarray(scenario.available_surplus_kw, dtype=float)
        error_profiles = {
            "perfect": np.zeros_like(actual),
            "overforecast_20pct": actual * 1.2,
            "underforecast_20pct": actual * 0.8,
            "alternating_pm20pct": actual * np.asarray(
                [1.2 if i % 2 == 0 else 0.8 for i in range(len(actual))]
            ),
        }
        for error_name, forecast in error_profiles.items():
            for policy in ("rolling", "ro_first", "ice_first", "perfect_information"):
                result = simulate_rolling(scenario, forecast, policy)
                rows.append({
                    "scenario": scenario.name,
                    "forecast_error_profile": error_name,
                    "result": result,
                    "data_status": "synthetic prototype; not field-validated",
                })
    return rows



def summarize_experiment(rows=None):
    """Compare rolling policy with fixed policies using one normalized score."""
    if rows is None:
        rows = run_experiment()
    scenarios = {scenario.name: scenario for scenario in build_scenarios()}
    grouped = {}
    for row in rows:
        key = (row["scenario"], row["forecast_error_profile"])
        grouped.setdefault(key, {})[row["result"]["policy"]] = row["result"]

    summaries = []
    for (scenario_name, error_name), policies in sorted(grouped.items()):
        scenario = scenarios[scenario_name]
        water_total = max(float(sum(scenario.water_demand_m3_per_hour)), 1e-9)
        cooling_total = max(float(sum(scenario.cooling_demand_kw_th)), 1e-9)
        power_total = max(float(sum(scenario.available_surplus_kw)), 1e-9)

        def score(result):
            return (0.45 * result["water_unmet_m3"] / water_total
                    + 0.45 * result["cooling_unmet_kwh_th"] / cooling_total
                    + 0.10 * result["remaining_surplus_kwh"] / power_total)

        rolling_score = score(policies["rolling"])
        fixed_scores = {name: score(policies[name]) for name in ("ro_first", "ice_first")}
        best_fixed_name = min(fixed_scores, key=lambda name: (fixed_scores[name], name))
        best_fixed_score = fixed_scores[best_fixed_name]
        summaries.append({
            "scenario": scenario_name,
            "forecast_error_profile": error_name,
            "rolling_score": round(rolling_score, 6),
            "ro_first_score": round(fixed_scores["ro_first"], 6),
            "ice_first_score": round(fixed_scores["ice_first"], 6),
            "best_fixed_policy": best_fixed_name,
            "best_fixed_score": round(best_fixed_score, 6),
            "rolling_minus_best_fixed": round(rolling_score - best_fixed_score, 6),
            "perfect_information_score": round(score(policies["perfect_information"]), 6),
            "rolling_water_unmet_m3": round(policies["rolling"]["water_unmet_m3"], 3),
            "best_fixed_water_unmet_m3": round(policies[best_fixed_name]["water_unmet_m3"], 3),
            "rolling_cooling_unmet_kwh_th": round(policies["rolling"]["cooling_unmet_kwh_th"], 3),
            "best_fixed_cooling_unmet_kwh_th": round(policies[best_fixed_name]["cooling_unmet_kwh_th"], 3),
            "rolling_remaining_surplus_kwh": round(policies["rolling"]["remaining_surplus_kwh"], 3),
            "best_fixed_remaining_surplus_kwh": round(policies[best_fixed_name]["remaining_surplus_kwh"], 3),
            "rolling_constraint_violation_hours": int(policies["rolling"]["constraint_violation_hours"]),
            "best_fixed_constraint_violation_hours": int(policies[best_fixed_name]["constraint_violation_hours"]),
            "interpretation": "case-specific comparison; no universal winner assumed",
        })
    return summaries


def summarize_aggregate(summaries):
    """Summarize policy deltas across cases without implying universal superiority."""
    deltas = [float(row["rolling_minus_best_fixed"]) for row in summaries]
    if not deltas:
        return {
            "comparison_count": 0,
            "rolling_better_count": 0,
            "rolling_tied_count": 0,
            "rolling_worse_count": 0,
            "mean_score_delta": None,
            "median_score_delta": None,
            "best_case": None,
            "worst_case": None,
            "interpretation": "No cases were available for aggregation.",
        }

    ordered = sorted(summaries, key=lambda row: row["rolling_minus_best_fixed"])
    better = sum(delta < -1e-9 for delta in deltas)
    tied = sum(abs(delta) <= 1e-9 for delta in deltas)
    worse = sum(delta > 1e-9 for delta in deltas)
    return {
        "comparison_count": len(deltas),
        "rolling_better_count": better,
        "rolling_tied_count": tied,
        "rolling_worse_count": worse,
        "mean_score_delta": round(float(np.mean(deltas)), 6),
        "median_score_delta": round(float(np.median(deltas)), 6),
        "best_case": {
            "scenario": ordered[0]["scenario"],
            "forecast_error_profile": ordered[0]["forecast_error_profile"],
            "score_delta": ordered[0]["rolling_minus_best_fixed"],
        },
        "worst_case": {
            "scenario": ordered[-1]["scenario"],
            "forecast_error_profile": ordered[-1]["forecast_error_profile"],
            "score_delta": ordered[-1]["rolling_minus_best_fixed"],
        },
        "interpretation": (
            "Negative delta favors rolling over the best fixed-priority policy; "
            "results are case-specific synthetic comparisons, not field validation."
        ),
    }


def summarize_weight_sensitivity(rows=None):
    """Check whether rolling-vs-fixed conclusions change with objective weights."""
    if rows is None:
        rows = run_experiment()
    scenarios = {scenario.name: scenario for scenario in build_scenarios()}
    grouped = {}
    for row in rows:
        key = (row["scenario"], row["forecast_error_profile"])
        grouped.setdefault(key, {})[row["result"]["policy"]] = row["result"]

    weight_profiles = {
        "balanced": {"water": 0.45, "cooling": 0.45, "surplus": 0.10},
        "water_priority": {"water": 0.60, "cooling": 0.30, "surplus": 0.10},
        "cooling_priority": {"water": 0.30, "cooling": 0.60, "surplus": 0.10},
    }
    reports = []
    for profile_name, weights in weight_profiles.items():
        deltas = []
        for (scenario_name, _error_name), policies in sorted(grouped.items()):
            required = {"rolling", "ro_first", "ice_first"}
            if not required.issubset(policies):
                raise ValueError(f"incomplete policy group for {scenario_name}: {sorted(policies)}")
            scenario = scenarios[scenario_name]
            water_total = max(float(sum(scenario.water_demand_m3_per_hour)), 1e-9)
            cooling_total = max(float(sum(scenario.cooling_demand_kw_th)), 1e-9)
            power_total = max(float(sum(scenario.available_surplus_kw)), 1e-9)

            def score(result):
                return (
                    weights["water"] * result["water_unmet_m3"] / water_total
                    + weights["cooling"] * result["cooling_unmet_kwh_th"] / cooling_total
                    + weights["surplus"] * result["remaining_surplus_kwh"] / power_total
                )

            best_fixed = min(score(policies[name]) for name in ("ro_first", "ice_first"))
            deltas.append(score(policies["rolling"]) - best_fixed)
        reports.append({
            "weight_profile": profile_name,
            "weights": weights,
            "comparison_count": len(deltas),
            "rolling_better_count": sum(delta < -1e-9 for delta in deltas),
            "rolling_tied_count": sum(abs(delta) <= 1e-9 for delta in deltas),
            "rolling_worse_count": sum(delta > 1e-9 for delta in deltas),
            "mean_score_delta": round(float(np.mean(deltas)), 6) if deltas else None,
            "median_score_delta": round(float(np.median(deltas)), 6) if deltas else None,
            "interpretation": "Synthetic case-matched sensitivity only; weights are illustrative, not stakeholder-validated.",
        })
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = run_experiment()
    summaries = summarize_experiment(rows)
    if args.json:
        print(json.dumps({
            "case_count": len(rows),
            "summary_case_count": len(summaries),
            "interpretation": "Finite-horizon policy selection; only first-hour priority is executed before replanning. Lower normalized score is better.",
            "limitations": [
                "Synthetic profiles only; no trained forecast model.",
                "RO minimum-run commitment is carried between hourly replans, but plant interlocks and startup/ramp dynamics are not modeled.",
                "Perfect-information policy is a hindsight reference, not deployable.",
                "Weights are illustrative and should be sensitivity-tested before decision use.",
            ],
            "summary": summaries,
            "aggregate_summary": summarize_aggregate(summaries),
            "weight_sensitivity": summarize_weight_sensitivity(rows),
            "rows": rows,
        }, indent=2))
    else:
        print("Synthetic rolling-horizon prototype — not field validated")
        print("Negative delta means rolling scored better than the best fixed priority.")
        aggregate = summarize_aggregate(summaries)
        print("scenario | forecast | rolling score | best fixed | fixed score | rolling - fixed")
        for row in summaries:
            print(f"{row['scenario']} | {row['forecast_error_profile']} | {row['rolling_score']:.4f} | "
                  f"{row['best_fixed_policy']} | {row['best_fixed_score']:.4f} | "
                  f"{row['rolling_minus_best_fixed']:+.4f}")
        print(
            "Aggregate: "
            f"rolling better/tied/worse = {aggregate['rolling_better_count']}/"
            f"{aggregate['rolling_tied_count']}/{aggregate['rolling_worse_count']}; "
            f"mean delta = {aggregate['mean_score_delta']:+.4f}; "
            f"median delta = {aggregate['median_score_delta']:+.4f}"
        )


if __name__ == "__main__":
    main()
