"""Synthetic telemetry anomaly-detection experiment with fail-closed review output.

Input values are synthetic scenario assumptions, not measured real-world data.
An anomaly flag is a reason for operator review, not a diagnosis.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

WINDOW = 24
DEFAULT_SEED = 20261021


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_telemetry(seed: int = DEFAULT_SEED, hours: int = 720) -> list[dict[str, Any]]:
    if hours < 120:
        raise ValueError("hours must be at least 120 to include a clean training window and fault cases")
    rng = np.random.default_rng(seed)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    meter = 80 + 7 * np.sin(np.arange(hours) * 2 * np.pi / 24) + rng.normal(0, 1.8, hours)
    reservoir = 500 + 18 * np.sin(np.arange(hours) * 2 * np.pi / 168) + rng.normal(0, 2.8, hours)
    meter = np.maximum(0.0, meter)
    reservoir = np.maximum(0.0, reservoir)
    labels = ["normal"] * hours

    def mark(index: int, label: str) -> None:
        if 0 <= index < hours:
            labels[index] = label

    for i in (85, 400):
        if i < hours:
            meter[i] = np.nan
            mark(i, "missing")
    for i in (140, 480):
        if i < hours:
            meter[i] += 65
            mark(i, "spike")
    if hours > 221:
        meter[210:222] = meter[209]
        for i in range(210, 222):
            mark(i, "stuck")
    if hours > 320:
        for offset, i in enumerate(range(300, 320), start=1):
            meter[i] += offset * 1.6
            mark(i, "drift")
    if hours > 571:
        reservoir[560:572] = reservoir[559]
        for i in range(560, 572):
            mark(i, "stuck")
    if hours > 669:
        for offset, i in enumerate(range(650, 670), start=1):
            reservoir[i] += offset * 1.1
            mark(i, "drift")
    rows = []
    for i in range(hours):
        rows.append({
            "timestamp_utc": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
            "meter_kw": None if not math.isfinite(float(meter[i])) else round(float(meter[i]), 3),
            "reservoir_m3": round(float(reservoir[i]), 3),
            "fault_label": labels[i],
            "is_synthetic": True,
        })
    return rows


def rolling_median_mad_flags(values: list[float | None], window: int = WINDOW,
                             threshold: float = 6.0) -> list[bool]:
    flags = []
    for i, value in enumerate(values):
        if value is None or not math.isfinite(float(value)):
            flags.append(True)
            continue
        history = [float(v) for v in values[max(0, i - window):i]
                   if v is not None and math.isfinite(float(v))]
        flag = False
        if len(history) >= 6:
            center = median(history)
            mad = median([abs(v - center) for v in history])
            scale = max(1.4826 * mad, 1e-6)
            flag = abs(float(value) - center) / scale > threshold
        # A long exact flatline is suspicious even if its value is near the median.
        if i >= 5:
            last = values[i - 5:i + 1]
            if all(v is not None for v in last) and len({float(v) for v in last}) == 1:
                flag = True
        flags.append(flag)
    return flags


def metrics(truth: list[bool], predicted: list[bool]) -> dict[str, float | int]:
    tp = sum(t and p for t, p in zip(truth, predicted))
    fp = sum((not t) and p for t, p in zip(truth, predicted))
    fn = sum(t and (not p) for t, p in zip(truth, predicted))
    tn = sum((not t) and (not p) for t, p in zip(truth, predicted))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    return {"true_positive": tp, "false_positive": fp, "false_negative": fn,
            "true_negative": tn, "precision": precision, "recall": recall,
            "false_positive_rate": fpr}


def _isolation_forest_flags(rows: list[dict[str, Any]], seed: int) -> list[bool] | None:
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        return None
    meter = np.asarray([np.nan if row["meter_kw"] is None else row["meter_kw"] for row in rows], dtype=float)
    reservoir = np.asarray([row["reservoir_m3"] for row in rows], dtype=float)
    meter_median = float(np.nanmedian(meter[:72]))
    meter[~np.isfinite(meter)] = meter_median
    train_meter = meter[:72]
    train_reservoir = reservoir[:72]
    center = np.asarray([np.median(train_meter), np.median(train_reservoir)])
    scale = np.asarray([
        max(1.4826 * np.median(np.abs(train_meter - np.median(train_meter))), 1e-3),
        max(1.4826 * np.median(np.abs(train_reservoir - np.median(train_reservoir))), 1e-3),
    ])
    normalized = (np.column_stack([meter, reservoir]) - center) / scale
    deltas = np.vstack([np.zeros((1, 2)), np.diff(normalized, axis=0)])
    features = np.column_stack([normalized, deltas])
    model = IsolationForest(
        n_estimators=200, contamination=0.08, random_state=seed,
        n_jobs=1,
    )
    model.fit(features[:72])
    return (model.predict(features) == -1).tolist()


def run(output_dir: Path, seed: int = DEFAULT_SEED, hours: int = 720) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = generate_telemetry(seed, hours)
    input_path = output_dir / "synthetic_telemetry_input.csv"
    fields = ["timestamp_utc", "meter_kw", "reservoir_m3", "fault_label", "is_synthetic"]
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "meter_kw": "" if row["meter_kw"] is None else row["meter_kw"]})

    meter_values = [row["meter_kw"] for row in rows]
    reservoir_values = [float(row["reservoir_m3"]) for row in rows]
    meter_flags = rolling_median_mad_flags(meter_values)
    reservoir_flags = rolling_median_mad_flags(reservoir_values)
    baseline_flags = [a or b for a, b in zip(meter_flags, reservoir_flags)]
    isolation_flags = _isolation_forest_flags(rows, seed)
    truth = [row["fault_label"] != "normal" for row in rows]
    baseline_metrics = metrics(truth, baseline_flags)
    isolation_metrics = metrics(truth, isolation_flags) if isolation_flags is not None else None

    output_path = output_dir / "telemetry_anomaly_results.csv"
    output_fields = [
        "timestamp_utc", "meter_kw", "reservoir_m3", "fault_label",
        "rolling_median_mad_flag", "isolation_forest_flag", "review_status",
        "review_reason",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields)
        writer.writeheader()
        for i, row in enumerate(rows):
            if row["fault_label"] == "missing":
                reason = "missing telemetry value"
            elif baseline_flags[i] or (isolation_flags is not None and isolation_flags[i]):
                reason = "statistical anomaly flag; operator review required"
            else:
                reason = "no configured detector flag; not proof of data validity"
            hold = row["fault_label"] == "missing" or baseline_flags[i] or (
                isolation_flags is not None and isolation_flags[i]
            )
            writer.writerow({
                "timestamp_utc": row["timestamp_utc"],
                "meter_kw": "" if row["meter_kw"] is None else row["meter_kw"],
                "reservoir_m3": row["reservoir_m3"],
                "fault_label": row["fault_label"],
                "rolling_median_mad_flag": int(baseline_flags[i]),
                "isolation_forest_flag": "" if isolation_flags is None else int(isolation_flags[i]),
                "review_status": "HOLD: data quality check failed" if hold else "REVIEW_REQUIRED",
                "review_reason": reason,
            })

    plot_path = output_dir / "telemetry_anomaly_plot.png"
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
        x = np.arange(len(rows))
        meter_plot = np.asarray([np.nan if v is None else v for v in meter_values], dtype=float)
        axes[0].plot(x, meter_plot, linewidth=0.9, label="meter_kw")
        axes[0].scatter([i for i, flag in enumerate(baseline_flags) if flag],
                        [meter_plot[i] for i, flag in enumerate(baseline_flags) if flag],
                        s=12, label="rolling median/MAD flag")
        axes[0].set_ylabel("Meter (kW)")
        axes[0].legend()
        axes[1].plot(x, reservoir_values, linewidth=0.9, label="reservoir_m3")
        axes[1].set_ylabel("Reservoir (m³)")
        axes[1].set_xlabel("Synthetic hour index")
        axes[1].legend()
        fig.suptitle("Synthetic telemetry with injected faults")
        fig.tight_layout()
        fig.savefig(plot_path, dpi=140)
        plt.close(fig)
    except ImportError:
        plot_path = None

    report = {
        "status": "synthetic_telemetry_anomaly_experiment_completed",
        "data_status": "synthetic / scenario assumption, not measured real-world data",
        "seed": seed, "row_count": len(rows),
        "injected_fault_rows": sum(truth),
        "rolling_median_mad": baseline_metrics,
        "isolation_forest": isolation_metrics,
        "isolation_forest_available": isolation_flags is not None,
        "quality_gate": {
            "rule": "Any missing value or configured detector flag routes that row to HOLD: data quality check failed.",
            "physical_write_performed": False,
            "operator_action_required": True,
        },
        "limitations": [
            "Faults and normal patterns are synthetic and chosen by this script.",
            "Metrics measure recovery of injected labels, not validated sensor-fault performance at a real site.",
            "A detector flag requests review; absence of a flag does not prove telemetry is valid.",
            "No live connection, actuator control, or deployed control system is provided.",
        ],
        "artifacts": {},
    }
    report_path = output_dir / "anomaly_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    artifacts = sorted(p for p in output_dir.iterdir() if p.is_file() and p.name != "manifest.json")
    manifest = {
        "dataset_type": "synthetic", "is_measured_site_data": False, "seed": seed,
        "artifacts": {p.name: {"bytes": p.stat().st_size, "sha256": sha256(p)} for p in artifacts},
        "limitations": ["A SHA-256 digest proves file identity, not measurement authenticity."],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["artifacts"] = manifest["artifacts"]
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="build/ai-telemetry-anomaly")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--hours", type=int, default=720)
    args = parser.parse_args(argv)
    try:
        report = run(Path(args.output_dir), args.seed, args.hours)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": report["status"], "row_count": report["row_count"],
        "rolling_median_mad": report["rolling_median_mad"],
        "isolation_forest": report["isolation_forest"],
        "output_dir": str(Path(args.output_dir)),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
