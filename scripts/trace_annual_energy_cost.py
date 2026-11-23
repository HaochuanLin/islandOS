"""Reproduce page 06's annual projection for a chosen wall-clock anchor hour.

Page 06 builds its default (synthetic) history from ``datetime.now(timezone.utc)``
truncated to the hour, then runs the joint optimizer and, if the box is ticked,
annualises the recommended schedule's own dispatch summary with a declared
equal-days assumption. This script replays exactly that path for an explicit
anchor instead of "now", so two recorded runs can be compared on equal footing.

The synthetic history comes from ``islandos_core.demo_site_history``; this script
does not keep a second copy of the formulas.

Usage (same environment knobs as the other page checks):

    $env:OPENBLAS_NUM_THREADS="1"; $env:OMP_NUM_THREADS="1"
    .\\.venv\\Scripts\\python.exe scripts\\trace_annual_energy_cost.py --anchor 2026-11-22T14:00Z
    .\\.venv\\Scripts\\python.exe scripts\\trace_annual_energy_cost.py --sweep-hours --date 2026-11-22

The output is a single JSON document: the annual record, its components, the
dispatch inputs that entered it, and an identity check that re-adds the annual
cost from its parts. Nothing here writes to a device.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from islandos_core.annual_operating_basis import (  # noqa: E402
    annualise_run_summary,
    verify_annual_operating_basis,
)
from islandos_core.app_view_models import build_annual_projection  # noqa: E402
from islandos_core.canonical_run import create_run_manifest, deterministic_run_id  # noqa: E402
from islandos_core.demo_site_history import build_synthetic_site_history  # noqa: E402
from islandos_core.run_orchestration import run_joint_optimizer  # noqa: E402
from islandos_core.site_inputs import (  # noqa: E402
    BATTERY_INITIAL_SOC,
    BATTERY_MAX_SOC,
    BATTERY_MIN_SOC,
    SiteAssumptions,
)

# The page's defaults, copied from pages/06_Forecast_Led_Joint_Resource_Optimizer.py.
DEFAULTS = {
    "currency": "USD",
    "pv_capacity": 40.0,
    "wind_capacity": 20.0,
    "grid_limit": 100.0,
    "battery_capacity": 80.0,
    "battery_power": 20.0,
    "diesel_capacity": 30.0,
    "diesel_cost": 0.32,
    "population": 12,
    "generations": 5,
    "seed": 20261113,
}


def synthetic_history(anchor: datetime, defaults: dict[str, Any]) -> dict[str, Any]:
    """The page's synthetic branch, using the production builder."""
    synthetic = build_synthetic_site_history(
        anchor,
        pv_rated_kw=float(defaults["pv_capacity"]),
        wind_rated_kw=float(defaults["wind_capacity"]),
    )
    values: dict[str, list[float]] = {
        "pv_power": list(synthetic.pv_power_kw),
        "wind_power": list(synthetic.wind_power_kw),
        "essential_load": list(synthetic.load_kw),
        "electricity_price": list(synthetic.tariff_per_kwh),
    }
    return {
        "anchor": synthetic.anchor_utc,
        "timestamps": list(synthetic.timestamps),
        "values": values,
    }


def run_once(anchor: datetime, days: int = 365) -> dict[str, Any]:
    defaults = DEFAULTS
    history = synthetic_history(anchor, defaults)
    timestamps = history["timestamps"]
    values = history["values"]

    signal_history = {
        "pv_power_kw": values["pv_power"],
        "wind_power_kw": values["wind_power"],
        "load_kw": values["essential_load"],
        "tariff_per_kwh": values["electricity_price"],
    }
    signal_units = {
        "pv_power_kw": "kW",
        "wind_power_kw": "kW",
        "load_kw": "kW",
        "tariff_per_kwh": f"{defaults['currency']}/kWh",
    }
    site = SiteAssumptions(
        pv_rated_kw=defaults["pv_capacity"],
        wind_rated_kw=defaults["wind_capacity"],
        grid_import_limit_kw=defaults["grid_limit"],
        battery_capacity_kwh=defaults["battery_capacity"],
        battery_power_kw=defaults["battery_power"],
        battery_initial_soc=BATTERY_INITIAL_SOC,
        battery_min_soc=BATTERY_MIN_SOC,
        battery_max_soc=BATTERY_MAX_SOC,
        diesel_rated_kw=defaults["diesel_capacity"],
        diesel_variable_cost_per_kwh=defaults["diesel_cost"],
    )
    config = site.to_energy_system_config()
    grid_available = [True] * 24
    diesel_available = [True] * 24

    dataset_payload = {
        "timestamps_utc": [stamp.isoformat() for stamp in timestamps],
        "signals": signal_history,
        "units": signal_units,
    }
    dataset_digest = hashlib.sha256(
        json.dumps(dataset_payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        .encode("utf-8")
    ).hexdigest()
    site_configuration_digest = hashlib.sha256(
        json.dumps(asdict(config), sort_keys=True, separators=(",", ":"), allow_nan=False)
        .encode("utf-8")
    ).hexdigest()
    run_id = deterministic_run_id("run-trace", {"anchor": history["anchor"].isoformat()})
    manifest = create_run_manifest(
        project_id="streamlit-joint-resource-workspace",
        run_id=run_id,
        site_ref="synthetic-demo-site",
        created_at_utc=history["anchor"].isoformat(),
        dataset_sha256=dataset_digest,
        dataset_schema_version="canonical-hourly-signals-v1",
        source_type="synthetic",
        site_configuration_version="1",
        site_configuration_sha256=site_configuration_digest,
        required_signals=signal_units,
        forecast_horizon_hours=24,
        optimizer_id="prediction_resource_dispatch",
        optimizer_version="1",
        optimizer_settings={
            "population_size": defaults["population"],
            "generations": defaults["generations"],
            "seed": defaults["seed"],
        },
        scenario_assumptions={"grid_available": grid_available, "diesel_available": diesel_available},
        forecast_settings={"backtest_horizon": 24, "season_length": 24, "confidence_level": 0.90},
    )
    outputs = run_joint_optimizer(
        run_manifest=manifest,
        timestamps=timestamps,
        history=signal_history,
        units=signal_units,
        config=config,
        grid_available=grid_available,
        diesel_available=diesel_available,
    )
    result = outputs["result"]
    recommendation = result["recommendation"]
    dispatch = recommendation.get("dispatch") or {}
    summary = dispatch.get("summary") or {}
    rows = list(dispatch.get("rows") or [])

    annual_record = annualise_run_summary(
        summary,
        dispatch_rows=rows,
        simulated_hours=len(outputs["target_timestamps"]),
        days_equivalent_per_year=days,
        run_id=outputs["planning_run"]["run_id"],
        manifest_sha256=outputs["planning_run"]["manifest_sha256"],
        data_provenance="Synthetic demonstration data",
        summary_source=(
            "recommended schedule's own nominal dispatch summary (the same 24-hour run "
            "that produced the hourly setpoint rows on this page)"
        ),
    )
    verified = verify_annual_operating_basis(annual_record)
    annual_view = build_annual_projection(annual_record, currency=defaults["currency"])

    target_stamps = list(outputs["target_timestamps"])
    target_tariff = signal_history["tariff_per_kwh"][-24:]
    target_pv = signal_history["pv_power_kw"][-24:]
    target_wind = signal_history["wind_power_kw"][-24:]
    target_load = signal_history["load_kw"][-24:]

    # Re-add the annual cost from the run summary. `estimated_energy_cost` is net of
    # export revenue, so the identity is gross minus export, then scaled by days.
    day_parts = {
        "grid_energy_cost": summary.get("grid_energy_cost", 0.0),
        "grid_demand_charge": summary.get("grid_demand_charge", 0.0),
        "diesel_energy_cost": summary.get("diesel_energy_cost", 0.0),
        "diesel_fuel_cost": summary.get("diesel_fuel_cost", 0.0),
        "battery_degradation_cost": summary.get("battery_degradation_cost", 0.0),
        "diesel_start_cost": summary.get("diesel_start_cost", 0.0),
        "diesel_stop_cost": summary.get("diesel_stop_cost", 0.0),
    }
    day_export_revenue = summary.get("grid_export_revenue", 0.0)
    day_net = round(
        sum(day_parts.values()) - day_export_revenue, 8
    )
    identity = {
        "day_parts": day_parts,
        "day_export_revenue": day_export_revenue,
        "day_net_recomputed": day_net,
        "day_estimated_energy_cost": summary.get("estimated_energy_cost"),
        "day_difference": round(day_net - float(summary.get("estimated_energy_cost", 0.0)), 8),
        "annual_parts": {key: round(value * days, 6) for key, value in day_parts.items()},
        "annual_export_revenue": round(day_export_revenue * days, 6),
        "annual_net_recomputed": round(day_net * days, 6),
        "annual_energy_cost_in_record": annual_record["figures"]["annual_energy_cost"],
    }

    return {
        "anchor_utc": history["anchor"].isoformat(),
        "anchor_hour_utc": history["anchor"].hour,
        "run_id": outputs["planning_run"]["run_id"],
        "manifest_sha256": outputs["planning_run"]["manifest_sha256"],
        "site_configuration_sha256": site_configuration_digest,
        "dataset_sha256": dataset_digest,
        "optimizer_settings": manifest.to_dict()["optimizer"]["settings"],
        "recommended_policy": result["recommendation"].get("policy"),
        "day_summary": {
            key: summary.get(key)
            for key in (
                "load_energy_kwh", "load_served_kwh", "unmet_load_kwh",
                "estimated_energy_cost", "grid_energy_cost", "grid_export_revenue",
                "grid_import_kwh", "grid_export_energy_kwh", "battery_throughput_kwh",
                "battery_degradation_cost", "diesel_generation_kwh", "diesel_fuel_cost",
                "diesel_start_cost", "diesel_stop_cost", "grid_demand_charge",
                "diesel_energy_cost", "renewable_curtailed_kwh",
            )
        },
        "target_window": {
            "first_hour_utc": target_stamps[0].isoformat() if target_stamps else None,
            "last_hour_utc": target_stamps[-1].isoformat() if target_stamps else None,
            "tariff_sum": round(sum(target_tariff), 6),
            "tariff_mean": round(sum(target_tariff) / 24, 6),
            "tariff_shape": [f"{value:.2f}" for value in target_tariff],
            "pv_kwh": round(sum(target_pv), 6),
            "wind_kwh": round(sum(target_wind), 6),
            "load_kwh": round(sum(target_load), 6),
        },
        "annual_record": annual_record,
        "annual_view_figures": annual_view["figures"],
        "annual_verified": verified,
        "identity": identity,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", help="ISO instant for the simulated 'now', e.g. 2026-11-22T22:00Z")
    parser.add_argument("--date", default="2026-11-22", help="date for --sweep-hours")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--sweep-hours", action="store_true", help="run all 24 anchor hours")
    parser.add_argument("--out", help="write JSON here as well as stdout")
    args = parser.parse_args()

    if args.sweep_hours:
        base = datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc)
        results = [run_once(base.replace(hour=hour), days=args.days) for hour in range(24)]
        payload: Any = {
            "mode": "sweep",
            "date": args.date,
            "days_equivalent_per_year": args.days,
            "runs": [
                {
                    "anchor_hour_utc": item["anchor_hour_utc"],
                    "annual_energy_cost": item["annual_record"]["figures"]["annual_energy_cost"],
                    "annual_load_energy_kwh": item["annual_record"]["figures"][
                        "annual_load_energy_kwh"
                    ],
                    "annual_equipment_operating_cost": item["annual_record"]["figures"][
                        "annual_equipment_operating_cost"
                    ],
                    "annual_diesel_run_hours": item["annual_record"]["figures"]["annual_diesel_run_hours"],
                    "day_grid_energy_cost": item["day_summary"]["grid_energy_cost"],
                    "day_export_revenue": item["day_summary"]["grid_export_revenue"],
                    "day_grid_import_kwh": item["day_summary"]["grid_import_kwh"],
                    "pv_kwh": item["target_window"]["pv_kwh"],
                    "wind_kwh": item["target_window"]["wind_kwh"],
                    "tariff_sum": item["target_window"]["tariff_sum"],
                }
                for item in results
            ],
        }
    else:
        if not args.anchor:
            parser.error("--anchor is required unless --sweep-hours is given")
        anchor = datetime.fromisoformat(args.anchor.replace("Z", "+00:00"))
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        payload = run_once(anchor, days=args.days)

    text = json.dumps(payload, indent=2, sort_keys=False, default=str)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
