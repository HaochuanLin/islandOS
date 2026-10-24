#!/usr/bin/env python3
"""Compare island energy-to-water operating strategies on aligned site time series.

This is a transparent screening experiment, not a site-ready controller or
economic optimiser. It never creates site data. See docs/ENERGY_WATER_STRATEGY_COMPARISON.md.
"""
from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

REQUIRED_COLUMNS = (
    "timestamp",
    "renewable_surplus_kw",
    "diesel_displacement_potential_kw",
    "grid_price_per_kwh",
    "off_peak",
    "grid_available",
    "water_demand_m3",
)
STRATEGIES = (
    "no_ro_baseline",
    "surplus_only",
    "off_peak_only",
    "hybrid_surplus_then_off_peak",
    "emergency_backup",
)


@dataclass(frozen=True)
class SiteStep:
    timestamp: str
    renewable_surplus_kw: float
    diesel_displacement_potential_kw: float
    grid_price_per_kwh: float
    off_peak: bool
    grid_available: bool
    water_demand_m3: float
    backup_available_kw: float = 0.0


@dataclass(frozen=True)
class Config:
    ro_rated_power_kw: float
    specific_energy_kwh_m3: float
    tank_capacity_m3: float
    initial_water_m3: float
    min_run_hours: int = 1
    dt_hours: float = 1.0
    diesel_cost_per_kwh: float | None = None


def _finite_nonnegative(value: str, field: str, row_number: int) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Row {row_number}: {field} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Row {row_number}: {field} must be finite and >= 0")
    return number


def _flag(value: str, field: str, row_number: int) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"Row {row_number}: {field} must be 0/1 or true/false")


def load_site_steps(path: str | Path) -> list[SiteStep]:
    """Load a user-supplied CSV; no synthetic or missing values are imputed."""
    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        if not fieldnames:
            raise ValueError("Input CSV is missing a header")
        if any(not name.strip() for name in fieldnames):
            raise ValueError("Input CSV contains an empty column name")
        if len(fieldnames) != len(set(fieldnames)):
            raise ValueError("Input CSV contains duplicate column names")
        columns = set(fieldnames)
        missing = [name for name in REQUIRED_COLUMNS if name not in columns]
        if missing:
            raise ValueError("Input CSV is missing required columns: " + ", ".join(missing))
        steps: list[SiteStep] = []
        previous_timestamp: datetime | None = None
        previous_timezone_aware: bool | None = None
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(
                    f"Row {row_number}: contains extra fields beyond the header"
                )
            missing_fields = [name for name in fieldnames if row.get(name) is None]
            if missing_fields:
                raise ValueError(
                    f"Row {row_number}: missing field(s): " + ", ".join(missing_fields)
                )
            timestamp = (row.get("timestamp") or "").strip()
            if not timestamp:
                raise ValueError(f"Row {row_number}: timestamp is required")
            normalized_timestamp = (
                timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
            )
            try:
                parsed_timestamp = datetime.fromisoformat(normalized_timestamp)
            except ValueError as exc:
                raise ValueError(
                    f"Row {row_number}: timestamp must be ISO-8601, got {timestamp!r}"
                ) from exc
            timezone_aware = parsed_timestamp.utcoffset() is not None
            if previous_timezone_aware is not None and timezone_aware != previous_timezone_aware:
                raise ValueError("timestamps mix timezone-aware and timezone-naive values")
            if previous_timestamp is not None and parsed_timestamp <= previous_timestamp:
                raise ValueError(
                    f"Row {row_number}: timestamps must be strictly increasing in time"
                )
            previous_timestamp = parsed_timestamp
            previous_timezone_aware = timezone_aware
            backup_raw = row.get("backup_available_kw", "")
            backup_kw = (
                0.0 if backup_raw is None or not backup_raw.strip()
                else _finite_nonnegative(backup_raw, "backup_available_kw", row_number)
            )
            price = _finite_nonnegative(row["grid_price_per_kwh"], "grid_price_per_kwh", row_number)
            steps.append(SiteStep(
                timestamp=timestamp,
                renewable_surplus_kw=_finite_nonnegative(row["renewable_surplus_kw"], "renewable_surplus_kw", row_number),
                diesel_displacement_potential_kw=_finite_nonnegative(row["diesel_displacement_potential_kw"], "diesel_displacement_potential_kw", row_number),
                grid_price_per_kwh=price,
                off_peak=_flag(row["off_peak"], "off_peak", row_number),
                grid_available=_flag(row["grid_available"], "grid_available", row_number),
                water_demand_m3=_finite_nonnegative(row["water_demand_m3"], "water_demand_m3", row_number),
                backup_available_kw=backup_kw,
            ))
    if not steps:
        raise ValueError("Input CSV must contain at least one data row")
    return steps


def _source_for_step(step: SiteStep, strategy: str, rated_kw: float) -> str | None:
    if strategy == "surplus_only":
        return "surplus" if step.renewable_surplus_kw >= rated_kw else None
    if strategy == "off_peak_only":
        return "grid" if step.grid_available and step.off_peak else None
    if strategy == "hybrid_surplus_then_off_peak":
        if step.renewable_surplus_kw >= rated_kw:
            return "surplus"
        if step.grid_available and step.off_peak:
            return "grid"
        return None
    if strategy == "emergency_backup":
        return "backup" if step.backup_available_kw >= rated_kw else None
    return None


def _minimum_run_steps(config: Config) -> int:
    """Convert the equipment minimum run duration into input time steps."""
    return math.ceil(config.min_run_hours / config.dt_hours)


def _can_start(steps: list[SiteStep], index: int, strategy: str, config: Config) -> bool:
    end = index + _minimum_run_steps(config)
    if end > len(steps):
        return False
    if all(_source_for_step(steps[j], strategy, config.ro_rated_power_kw) is not None
           for j in range(index, end)):
        return True
    return False


def _simulate_strategy(
    steps: list[SiteStep], strategy: str, config: Config
) -> tuple[list[dict], dict]:
    inventory = config.initial_water_m3
    remaining_run = 0
    detail: list[dict] = []
    totals = {
        "strategy": strategy,
        "timesteps": len(steps),
        "ro_run_hours": 0.0,
        "water_produced_m3": 0.0,
        "water_served_m3": 0.0,
        "unmet_water_demand_m3": 0.0,
        "water_spill_m3": 0.0,
        "renewable_surplus_available_kwh": sum(
            s.renewable_surplus_kw * config.dt_hours for s in steps
        ),
        "surplus_energy_to_ro_kwh": 0.0,
        "renewable_surplus_unused_kwh": 0.0,
        "grid_energy_to_ro_kwh": 0.0,
        "backup_energy_to_ro_kwh": 0.0,
        "grid_energy_cost": 0.0,
        "backup_energy_cost_estimate": None,
        "direct_diesel_displacement_potential_kwh": sum(
            s.diesel_displacement_potential_kw * config.dt_hours for s in steps
        ),
        "ending_water_inventory_m3": None,
        "minimum_run_constraint_violations": 0,
    }
    backup_cost = 0.0
    produced_total = served_total = unmet_total = spill_total = 0.0
    surplus_energy = grid_energy = backup_energy = grid_cost = 0.0
    for i, step in enumerate(steps):
        source: str | None = None
        if strategy != "no_ro_baseline":
            if remaining_run > 0:
                source = _source_for_step(step, strategy, config.ro_rated_power_kw)
                if source is None:
                    # This should not occur for a known, complete time series after
                    # the start-window check. Retain a visible violation if it does.
                    totals["minimum_run_constraint_violations"] += 1
                    remaining_run = 0
            elif inventory < config.tank_capacity_m3 and _can_start(steps, i, strategy, config):
                source = _source_for_step(step, strategy, config.ro_rated_power_kw)
                if source is not None:
                    remaining_run = _minimum_run_steps(config)
        power_kw = config.ro_rated_power_kw if source else 0.0
        energy_kwh = power_kw * config.dt_hours
        produced = energy_kwh / config.specific_energy_kwh_m3
        inventory_before = inventory
        inventory += produced
        spill = max(0.0, inventory - config.tank_capacity_m3)
        inventory = min(config.tank_capacity_m3, inventory)
        served = min(inventory, step.water_demand_m3)
        inventory -= served
        unmet = step.water_demand_m3 - served

        if source == "surplus":
            surplus_energy += energy_kwh
        elif source == "grid":
            grid_energy += energy_kwh
            grid_cost += energy_kwh * step.grid_price_per_kwh
        elif source == "backup":
            backup_energy += energy_kwh
            if config.diesel_cost_per_kwh is not None:
                backup_cost += energy_kwh * config.diesel_cost_per_kwh

        if source:
            totals["ro_run_hours"] += config.dt_hours
            remaining_run -= 1
        produced_total += produced
        served_total += served
        unmet_total += unmet
        spill_total += spill
        detail.append({
            "timestamp": step.timestamp,
            "strategy": strategy,
            "ro_source": source or "off",
            "ro_power_kw": round(power_kw, 6),
            "ro_energy_kwh": round(energy_kwh, 6),
            "water_produced_m3": round(produced, 6),
            "water_inventory_before_m3": round(inventory_before, 6),
            "water_served_m3": round(served, 6),
            "unmet_water_demand_m3": round(unmet, 6),
            "water_spill_m3": round(spill, 6),
            "remaining_water_inventory_m3": round(inventory, 6),
            "grid_price_per_kwh": step.grid_price_per_kwh,
            "renewable_surplus_available_kw": step.renewable_surplus_kw,
            "renewable_surplus_unused_kw": round(max(
                0.0, step.renewable_surplus_kw - (power_kw if source == "surplus" else 0.0)
            ), 6),
            "direct_diesel_displacement_potential_kw": step.diesel_displacement_potential_kw,
        })
    totals.update({
        "water_produced_m3": round(produced_total, 6),
        "water_served_m3": round(served_total, 6),
        "unmet_water_demand_m3": round(unmet_total, 6),
        "water_spill_m3": round(spill_total, 6),
        "renewable_surplus_available_kwh": round(sum(
            s.renewable_surplus_kw * config.dt_hours for s in steps
        ), 6),
        "surplus_energy_to_ro_kwh": round(surplus_energy, 6),
        "renewable_surplus_unused_kwh": round(max(
            0.0,
            sum(s.renewable_surplus_kw * config.dt_hours for s in steps) - surplus_energy
        ), 6),
        "grid_energy_to_ro_kwh": round(grid_energy, 6),
        "backup_energy_to_ro_kwh": round(backup_energy, 6),
        "grid_energy_cost": round(grid_cost, 6),
        "backup_energy_cost_estimate": (
            round(backup_cost, 6) if config.diesel_cost_per_kwh is not None else None
        ),
        "ending_water_inventory_m3": round(inventory, 6),
    })
    return detail, totals


def compare_strategies(steps: list[SiteStep], config: Config) -> tuple[list[dict], list[dict]]:
    """Return per-timestep audit rows and one summary row per strategy."""
    _validate_config(config)
    details: list[dict] = []
    summaries: list[dict] = []
    for strategy in STRATEGIES:
        rows, summary = _simulate_strategy(steps, strategy, config)
        details.extend(rows)
        summaries.append(summary)
    return details, summaries


def _validate_config(config: Config) -> None:
    for name in ("ro_rated_power_kw", "specific_energy_kwh_m3", "tank_capacity_m3", "dt_hours"):
        value = getattr(config, name)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and > 0")
    if not math.isfinite(config.initial_water_m3) or not 0 <= config.initial_water_m3 <= config.tank_capacity_m3:
        raise ValueError("initial_water_m3 must be within [0, tank_capacity_m3]")
    if isinstance(config.min_run_hours, bool) or not isinstance(config.min_run_hours, int) or config.min_run_hours < 1:
        raise ValueError("min_run_hours must be an integer >= 1")
    if config.diesel_cost_per_kwh is not None and (
        not math.isfinite(config.diesel_cost_per_kwh) or config.diesel_cost_per_kwh < 0
    ):
        raise ValueError("diesel_cost_per_kwh must be finite and >= 0")


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"No rows to write to {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Site hourly CSV; see the accompanying docs")
    parser.add_argument("--output-dir", default="build/energy-water-strategy-comparison")
    parser.add_argument("--ro-rated-power-kw", type=float, required=True)
    parser.add_argument("--specific-energy-kwh-m3", type=float, required=True)
    parser.add_argument("--tank-capacity-m3", type=float, required=True)
    parser.add_argument("--initial-water-m3", type=float, default=0.0)
    parser.add_argument("--min-run-hours", type=int, default=1)
    parser.add_argument("--dt-hours", type=float, default=1.0)
    parser.add_argument("--diesel-cost-per-kwh", type=float, default=None,
                        help="Optional site-specific cost; do not treat as a universal fuel price")
    args = parser.parse_args(argv)
    steps = load_site_steps(args.input)
    config = Config(
        ro_rated_power_kw=args.ro_rated_power_kw,
        specific_energy_kwh_m3=args.specific_energy_kwh_m3,
        tank_capacity_m3=args.tank_capacity_m3,
        initial_water_m3=args.initial_water_m3,
        min_run_hours=args.min_run_hours,
        dt_hours=args.dt_hours,
        diesel_cost_per_kwh=args.diesel_cost_per_kwh,
    )
    detail, summary = compare_strategies(steps, config)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "strategy_summary.csv", summary)
    _write_csv(out / "timestep_audit.csv", detail)
    print(f"Wrote {out / 'strategy_summary.csv'}")
    print(f"Wrote {out / 'timestep_audit.csv'}")
    print("Screening results only: validate inputs, source constraints, full costs and site controls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
