"""Compare an incumbent and candidate water-demand forecast before human review.

The gate evaluates already-issued forecasts against matching actual readings.
It never trains, deploys, or automatically replaces a model.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = (
    "timestamp",
    "actual_water_demand_m3",
    "incumbent_forecast_m3",
    "candidate_forecast_m3",
)


def _timestamp(raw: str, line: int) -> datetime:
    try:
        stamp = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid timestamp at CSV line {line}: {raw!r}") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"Timestamp must include a timezone at CSV line {line}")
    return stamp


def _value(raw: str | None, field: str, line: int) -> float:
    try:
        value = float(raw or "")
    except ValueError as exc:
        raise ValueError(f"Invalid {field} at CSV line {line}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be finite and non-negative at CSV line {line}")
    return value


def _metrics(actual: list[float], forecast: list[float]) -> dict[str, float]:
    if not actual or len(actual) != len(forecast):
        raise ValueError("Metric inputs must be non-empty and aligned")
    errors = [prediction - observed for observed, prediction in zip(actual, forecast)]
    return {
        "sample_count": len(actual),
        "mae_m3_per_hour": sum(abs(error) for error in errors) / len(errors),
        "rmse_m3_per_hour": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias_predicted_minus_actual_m3_per_hour": sum(errors) / len(errors),
        "underforecast_rate": sum(error < 0 for error in errors) / len(errors),
    }


def evaluate_candidate(
    input_csv: str | Path,
    output_json: str | Path,
    high_demand_threshold_m3: float,
    min_mae_improvement_fraction: float = 0.0,
    max_underforecast_rate_increase: float = 0.02,
    min_high_demand_samples: int = 5,
) -> dict[str, Any]:
    """Score two aligned forecast series and make a conservative review recommendation."""
    if not math.isfinite(high_demand_threshold_m3) or high_demand_threshold_m3 <= 0:
        raise ValueError("high_demand_threshold_m3 must be finite and greater than zero")
    if not 0.0 <= min_mae_improvement_fraction <= 1.0:
        raise ValueError("min_mae_improvement_fraction must be between 0 and 1")
    if not 0.0 <= max_underforecast_rate_increase <= 1.0:
        raise ValueError("max_underforecast_rate_increase must be between 0 and 1")
    if isinstance(min_high_demand_samples, bool) or not isinstance(min_high_demand_samples, int) or min_high_demand_samples < 1:
        raise ValueError("min_high_demand_samples must be a positive integer")

    with Path(input_csv).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)

    if len(rows) < 24:
        raise ValueError("Need at least 24 aligned hourly rows for candidate review")

    timestamps: list[datetime] = []
    actual: list[float] = []
    incumbent: list[float] = []
    candidate: list[float] = []
    for line, row in enumerate(rows, start=2):
        stamp = _timestamp(row.get("timestamp") or "", line)
        if timestamps and (stamp - timestamps[-1]).total_seconds() != 3600:
            raise ValueError(
                f"Expected strictly ordered, continuous hourly records at CSV line {line}"
            )
        timestamps.append(stamp)
        actual.append(_value(row.get("actual_water_demand_m3"), "actual_water_demand_m3", line))
        incumbent.append(_value(row.get("incumbent_forecast_m3"), "incumbent_forecast_m3", line))
        candidate.append(_value(row.get("candidate_forecast_m3"), "candidate_forecast_m3", line))

    peak_indices = [i for i, observed in enumerate(actual) if observed >= high_demand_threshold_m3]
    # Zero qualifying peak observations are insufficient evidence, not malformed
    # input. Keep the report schema explicit and refuse to recommend a candidate.
    high_demand_evidence_sufficient = len(peak_indices) >= min_high_demand_samples

    overall = {
        "incumbent": _metrics(actual, incumbent),
        "candidate": _metrics(actual, candidate),
    }
    peak_actual = [actual[i] for i in peak_indices]
    peak_incumbent = [incumbent[i] for i in peak_indices]
    peak_candidate = [candidate[i] for i in peak_indices]
    high_demand = {
        "threshold_m3_per_hour": high_demand_threshold_m3,
        "event_count": len(peak_indices),
        "incumbent": _metrics(peak_actual, peak_incumbent) if peak_indices else None,
        "candidate": _metrics(peak_actual, peak_candidate) if peak_indices else None,
    }

    incumbent_mae = overall["incumbent"]["mae_m3_per_hour"]
    candidate_mae = overall["candidate"]["mae_m3_per_hour"]
    mae_improvement = (
        (incumbent_mae - candidate_mae) / incumbent_mae
        if incumbent_mae > 1e-12
        else (0.0 if candidate_mae <= 1e-12 else -1.0)
    )
    overall_improved = (
        mae_improvement >= min_mae_improvement_fraction
        and candidate_mae < incumbent_mae - 1e-12
    )
    peak_underforecast_delta = (
        high_demand["candidate"]["underforecast_rate"]
        - high_demand["incumbent"]["underforecast_rate"]
        if peak_indices else None
    )
    peak_mae_not_worse = bool(peak_indices) and (
        high_demand["candidate"]["mae_m3_per_hour"]
        <= high_demand["incumbent"]["mae_m3_per_hour"] + 1e-12
    )
    peak_risk_acceptable = (
        peak_underforecast_delta is not None
        and peak_underforecast_delta <= max_underforecast_rate_increase
        and peak_mae_not_worse
    )
    recommend = overall_improved and peak_risk_acceptable and high_demand_evidence_sufficient
    if recommend:
        status = "candidate_recommended_for_review"
    elif not high_demand_evidence_sufficient:
        status = "insufficient_high_demand_evidence"
    else:
        status = "keep_incumbent_for_now"

    report: dict[str, Any] = {
        "status": status,
        "decision_scope": "offline comparison only; human review required before any model change",
        "input_csv": str(input_csv),
        "target": "freshwater demand",
        "units": "m3 per hourly interval",
        "row_count": len(rows),
        "first_timestamp": timestamps[0].isoformat(),
        "last_timestamp": timestamps[-1].isoformat(),
        "overall_metrics": overall,
        "high_demand_metrics": high_demand,
        "decision_checks": {
            "minimum_mae_improvement_fraction": min_mae_improvement_fraction,
            "observed_mae_improvement_fraction": mae_improvement,
            "minimum_high_demand_samples": min_high_demand_samples,
            "high_demand_evidence_sufficient": high_demand_evidence_sufficient,
            "overall_mae_check_passed": overall_improved,
            "maximum_allowed_high_demand_underforecast_rate_increase": max_underforecast_rate_increase,
            "high_demand_underforecast_rate_delta_candidate_minus_incumbent": peak_underforecast_delta,
            "high_demand_mae_not_worse": peak_mae_not_worse,
            "high_demand_risk_check_passed": peak_risk_acceptable,
        },
        "limitations": [
            "Use only forecasts issued before their matching actual observations were available.",
            "Choose the high-demand threshold from operational requirements or training history, not by optimizing on this holdout.",
            "A candidate passing this gate is only recommended for human review; this report does not deploy or retrain a model.",
            "Synthetic data verifies the software path but does not establish real-site forecast skill.",
        ],
    }
    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Aligned hourly actual, incumbent and candidate forecasts")
    parser.add_argument("--high-demand-threshold-m3", type=float, required=True)
    parser.add_argument("--min-mae-improvement-fraction", type=float, default=0.0)
    parser.add_argument("--max-underforecast-rate-increase", type=float, default=0.02)
    parser.add_argument("--min-high-demand-samples", type=int, default=5)
    parser.add_argument("--output", default="build/water-demand-forecast/candidate-review.json")
    args = parser.parse_args()
    report = evaluate_candidate(
        args.input_csv,
        args.output,
        high_demand_threshold_m3=args.high_demand_threshold_m3,
        min_mae_improvement_fraction=args.min_mae_improvement_fraction,
        max_underforecast_rate_increase=args.max_underforecast_rate_increase,
        min_high_demand_samples=args.min_high_demand_samples,
    )
    print(json.dumps({
        "status": report["status"],
        "row_count": report["row_count"],
        "overall_metrics": report["overall_metrics"],
        "high_demand_metrics": report["high_demand_metrics"],
        "decision_checks": report["decision_checks"],
        "output": str(args.output),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
