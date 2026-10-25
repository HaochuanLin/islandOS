"""Reproducible synthetic renewable-surplus forecasting experiment.

All inputs are synthetic scenario assumptions, not measured real-world data.
This experiment is advisory research; it does not control equipment.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_SEEDS = tuple(range(20261021, 20261031))
TRAIN_HOURS = 14 * 24
TOTAL_HOURS = 21 * 24
MODEL_NAMES = ("persistence", "seasonal_naive_24h", "hist_gradient_boosting")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_synthetic_series(seed: int, hours: int = TOTAL_HOURS) -> list[dict[str, Any]]:
    """Create a deterministic illustrative surplus trace; never site measurements."""
    if hours < TRAIN_HOURS + 48:
        raise ValueError(f"hours must be at least {TRAIN_HOURS + 48}")
    rng = np.random.default_rng(seed)
    wind = np.zeros(hours, dtype=float)
    wind[0] = 115.0
    for i in range(1, hours):
        wind[i] = max(0.0, 0.78 * wind[i - 1] + 0.22 * 115.0 + rng.normal(0, 22))
    rows = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(hours):
        stamp = start + timedelta(hours=i)
        hour = stamp.hour
        day = i // 24
        daylight = max(0.0, math.sin(math.pi * (hour - 6) / 12.0))
        seasonal = 0.88 + 0.12 * math.sin(2 * math.pi * day / 30.0)
        solar = 300.0 * daylight * seasonal + max(0.0, rng.normal(0, 8))
        load = 145.0 + 18.0 * math.sin(2 * math.pi * (hour - 8) / 24.0) + rng.normal(0, 7)
        surplus = max(0.0, solar + wind[i] - load)
        water_demand = max(0.0, 22.0 + 4.0 * math.sin(2 * math.pi * (hour - 7) / 24.0) + rng.normal(0, 1.5))
        rows.append({
            "timestamp_utc": stamp.isoformat().replace("+00:00", "Z"),
            "actual_surplus_kw": round(float(surplus), 6),
            "water_demand_m3": round(float(water_demand), 6),
        })
    return rows


def features(rows: list[dict[str, Any]], index: int) -> list[float]:
    """Features use only realized values available before the forecast hour."""
    y = [float(row["actual_surplus_kw"]) for row in rows]
    stamp = datetime.fromisoformat(rows[index]["timestamp_utc"].replace("Z", "+00:00"))
    return [
        y[index - 1],
        y[index - 24],
        y[index - 168],
        math.sin(2 * math.pi * stamp.hour / 24.0),
        math.cos(2 * math.pi * stamp.hour / 24.0),
        math.sin(2 * math.pi * stamp.timetuple().tm_yday / 366.0),
        math.cos(2 * math.pi * stamp.timetuple().tm_yday / 366.0),
    ]


def walk_forward_forecasts(rows: list[dict[str, Any]], seed: int) -> dict[str, dict[int, float]]:
    """Evaluate expanding-window, one-step-ahead forecasts in daily test blocks."""
    output = {name: {} for name in MODEL_NAMES}
    sklearn_model = None
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
        sklearn_model = HistGradientBoostingRegressor(
            max_iter=60, max_leaf_nodes=15, l2_regularization=1.0,
            random_state=seed,
        )
    except ImportError:
        pass

    for block_start in range(TRAIN_HOURS, len(rows), 24):
        block_end = min(block_start + 24, len(rows))
        train_indices = list(range(168, block_start))
        if sklearn_model is not None and train_indices:
            x_train = [features(rows, i) for i in train_indices]
            y_train = [float(rows[i]["actual_surplus_kw"]) for i in train_indices]
            model = HistGradientBoostingRegressor(
                max_iter=60, max_leaf_nodes=15, l2_regularization=1.0,
                random_state=seed + block_start,
            )
            model.fit(x_train, y_train)
        else:
            model = None
        for i in range(block_start, block_end):
            actual = float(rows[i]["actual_surplus_kw"])
            output["persistence"][i] = float(rows[i - 1]["actual_surplus_kw"])
            output["seasonal_naive_24h"][i] = float(rows[i - 24]["actual_surplus_kw"])
            if model is not None:
                prediction = float(model.predict([features(rows, i)])[0])
                output["hist_gradient_boosting"][i] = max(0.0, prediction)
    return output


def metric(actual: list[float], predicted: list[float]) -> dict[str, float]:
    errors = [p - a for a, p in zip(actual, predicted)]
    return {
        "mae_kw": mean(abs(e) for e in errors),
        "rmse_kw": math.sqrt(mean(e * e for e in errors)),
        "bias_kw": mean(errors),
    }


def bootstrap_mean_ci(values: list[float], seed: int, draws: int = 3000) -> dict[str, float]:
    if not values:
        return {"mean": float("nan"), "ci95_low": float("nan"), "ci95_high": float("nan")}
    rng = np.random.default_rng(seed)
    samples = np.asarray(values, dtype=float)
    boot_means = np.mean(rng.choice(samples, size=(draws, len(samples)), replace=True), axis=1)
    return {
        "mean": float(np.mean(samples)),
        "ci95_low": float(np.quantile(boot_means, 0.025)),
        "ci95_high": float(np.quantile(boot_means, 0.975)),
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(output_dir: Path, seeds: tuple[int, ...] = DEFAULT_SEEDS) -> dict[str, Any]:
    if not seeds:
        raise ValueError("at least one seed is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    metric_rows: list[dict[str, Any]] = []
    dispatch_rows: list[dict[str, Any]] = []
    plot_payload = None
    sklearn_available = True
    try:
        import sklearn  # noqa: F401
    except ImportError:
        sklearn_available = False

    # Import the existing simulator/evaluator rather than duplicating dispatch logic.
    from experiments.evaluate_forecast_driven_ro_sim import evaluate_forecast_driven_ro_sim

    for seed in seeds:
        rows = generate_synthetic_series(seed)
        input_path = output_dir / f"synthetic_surplus_input_seed_{seed}.csv"
        write_csv(input_path, ["timestamp_utc", "actual_surplus_kw", "water_demand_m3"], rows)
        predictions = walk_forward_forecasts(rows, seed)
        test_indices = sorted(predictions["persistence"])
        actual = [float(rows[i]["actual_surplus_kw"]) for i in test_indices]
        for model_name, model_predictions in predictions.items():
            if not model_predictions:
                continue
            pred = [float(model_predictions[i]) for i in test_indices]
            scores = metric(actual, pred)
            metric_rows.append({
                "seed": seed, "model": model_name, "test_hours": len(test_indices), **scores,
                "data_status": "synthetic / scenario assumption, not measured real-world data",
            })
            if model_name == "persistence" and plot_payload is None:
                plot_payload = (rows, test_indices, predictions)

            dispatch_input = output_dir / f"dispatch_input_{model_name}_seed_{seed}.csv"
            paired_rows = []
            for i in test_indices:
                paired_rows.append({
                    "timestamp_utc": rows[i]["timestamp_utc"],
                    "actual_surplus_kw": rows[i]["actual_surplus_kw"],
                    "forecast_surplus_kw": model_predictions[i],
                    "water_demand_m3": rows[i]["water_demand_m3"],
                    # Demand is deliberately held at the synthetic realized value to isolate
                    # the effect of the surplus forecast; this is not a deployable forecast.
                    "forecast_water_demand_m3": rows[i]["water_demand_m3"],
                })
            write_csv(dispatch_input, [
                "timestamp_utc", "actual_surplus_kw", "forecast_surplus_kw",
                "water_demand_m3", "forecast_water_demand_m3",
            ], paired_rows)
            dispatch_output = output_dir / f"dispatch_{model_name}_seed_{seed}_hourly.csv"
            dispatch_report = output_dir / f"dispatch_{model_name}_seed_{seed}_report.json"
            result = evaluate_forecast_driven_ro_sim(
                dispatch_input, dispatch_output, dispatch_report,
            )
            dispatch_rows.append({
                "seed": seed, "model": model_name,
                "forecast_mae_kw": scores["mae_kw"], "forecast_rmse_kw": scores["rmse_kw"],
                "forecast_driven_backup_energy_kwh": result["forecast_driven_scenario"]["backup_energy_kwh"],
                "forecast_driven_unmet_water_m3": result["forecast_driven_scenario"]["unmet_water_demand_m3"],
                "forecast_driven_water_spill_m3": result["forecast_driven_scenario"]["water_spill_m3"],
                "perfect_foresight_backup_energy_kwh": result["perfect_foresight_reference"]["backup_energy_kwh"],
                "perfect_foresight_unmet_water_m3": result["perfect_foresight_reference"]["unmet_water_demand_m3"],
                "data_status": "synthetic / scenario assumption, not measured real-world data",
            })

    write_csv(output_dir / "forecast_metrics.csv",
              ["seed", "model", "test_hours", "mae_kw", "rmse_kw", "bias_kw", "data_status"], metric_rows)
    write_csv(output_dir / "dispatch_comparison.csv", [
        "seed", "model", "forecast_mae_kw", "forecast_rmse_kw",
        "forecast_driven_backup_energy_kwh", "forecast_driven_unmet_water_m3",
        "forecast_driven_water_spill_m3", "perfect_foresight_backup_energy_kwh",
        "perfect_foresight_unmet_water_m3", "data_status",
    ], dispatch_rows)

    summaries = {}
    for model_name in MODEL_NAMES:
        selected = [r for r in metric_rows if r["model"] == model_name]
        if not selected:
            continue
        summaries[model_name] = {
            key: bootstrap_mean_ci([float(r[key]) for r in selected], seed=20261021 + i)
            for i, key in enumerate(("mae_kw", "rmse_kw", "bias_kw"))
        }
    dispatch_summaries = {}
    for model_name in MODEL_NAMES:
        selected = [r for r in dispatch_rows if r["model"] == model_name]
        if selected:
            dispatch_summaries[model_name] = {
                key: bootstrap_mean_ci([float(r[key]) for r in selected], seed=20261101 + i)
                for i, key in enumerate((
                    "forecast_driven_backup_energy_kwh",
                    "forecast_driven_unmet_water_m3",
                    "forecast_driven_water_spill_m3",
                ))
            }

    plot_path = output_dir / "forecast_comparison.png"
    if plot_payload is not None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            rows, test_indices, predictions = plot_payload
            fig, ax = plt.subplots(figsize=(12, 5))
            ax.plot(range(len(test_indices)), [rows[i]["actual_surplus_kw"] for i in test_indices],
                    label="Actual synthetic surplus", linewidth=1.5)
            for model_name, model_predictions in predictions.items():
                if model_predictions:
                    ax.plot(range(len(test_indices)), [model_predictions[i] for i in test_indices],
                            label=model_name, alpha=0.8)
            ax.set(title="Synthetic renewable-surplus forecasting (one-step walk-forward)",
                   xlabel="Test hour", ylabel="Surplus power (kW)")
            ax.legend()
            fig.tight_layout()
            fig.savefig(plot_path, dpi=140)
            plt.close(fig)
        except ImportError:
            plot_path = None

    report = {
        "status": "synthetic_forecast_experiment_completed",
        "data_status": "synthetic / scenario assumption, not measured real-world data",
        "seeds": list(seeds),
        "train_hours_per_seed": TRAIN_HOURS,
        "test_hours_per_seed": TOTAL_HOURS - TRAIN_HOURS,
        "forecast_method": "expanding-window daily refit; one-step-ahead forecasts; only past realized surplus features",
        "models": list(summaries),
        "forecast_metric_summary": summaries,
        "dispatch_metric_summary": dispatch_summaries,
        "sklearn_available": sklearn_available,
        "demand_assumption": "Synthetic realized demand is reused as the demand forecast to isolate the surplus forecast effect; this is an oracle-like experimental assumption, not a deployable setup.",
        "interpretation_limits": [
            "All data are synthetic scenario assumptions, not measured real-world data.",
            "Bootstrap intervals describe variation across the selected synthetic seeds only; they are not site-level confidence intervals.",
            "Perfect foresight is an optimistic reference, not an achievable operating policy.",
            "No model superiority is assumed; inspect the emitted metrics rather than relying on this report's status.",
            "The experiment does not control hardware and is not a deployed control system.",
        ],
        "artifacts": {},
    }
    report_path = output_dir / "run_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    artifacts = sorted(
        p for p in output_dir.iterdir()
        if p.is_file() and p.name not in {"manifest.json", "run_report.json"}
    )
    manifest = {
        "dataset_type": "synthetic",
        "is_measured_site_data": False,
        "seed_list": list(seeds),
        "artifacts": {
            p.name: {"bytes": p.stat().st_size, "sha256": sha256(p)}
            for p in artifacts
        },
        "limitations": ["A SHA-256 digest proves file identity, not measurement authenticity."],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["artifacts"] = manifest["artifacts"]
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="build/ai-renewable-forecast")
    parser.add_argument("--seeds", nargs="+", type=int, default=list(DEFAULT_SEEDS))
    args = parser.parse_args(argv)
    try:
        report = run(Path(args.output_dir), tuple(args.seeds))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": report["status"], "seeds": report["seeds"],
        "models": report["models"], "output_dir": str(Path(args.output_dir)),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
