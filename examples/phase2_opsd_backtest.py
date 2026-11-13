"""Run the generic IslandOS forecast engine on a local OPSD hourly CSV.

Example:
    python examples/phase2_opsd_backtest.py --csv ./time_series_60min_singleindex.csv --region AT
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Sequence

from islandos_core.forecast_engine import forecast_signals
from islandos_core.opsd_adapter import load_opsd_singleindex_csv


def _utc_bound(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise argparse.ArgumentTypeError("date bounds must include a UTC offset, e.g. 2020-01-01T00:00:00Z")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="Path to the OPSD 60-minute single-index CSV")
    parser.add_argument("--region", default="AT", help="OPSD region code (default: AT)")
    parser.add_argument(
        "--signals", nargs="+", choices=("load", "solar", "wind", "price"),
        default=("load", "solar", "wind", "price"),
        help="Signals to require (default: all four)",
    )
    parser.add_argument("--start-utc", type=_utc_bound, help="Inclusive ISO-8601 UTC start")
    parser.add_argument("--end-utc", type=_utc_bound, help="Exclusive ISO-8601 UTC end")
    parser.add_argument("--horizon", type=int, default=24, help="Forecast horizon in hours (1–168)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset = load_opsd_singleindex_csv(
        args.csv,
        args.region,
        required_signals=tuple(args.signals),
        start_utc=args.start_utc,
        end_utc=args.end_utc,
    )
    bundle = forecast_signals(
        timestamps=dataset.timestamps,
        history=dataset.history,
        units=dataset.units,
        horizon=args.horizon,
        non_negative_signals=tuple(signal for signal in dataset.history if signal != "price"),
    )
    report = {
        "data_provenance": {
            "source": dataset.source_name,
            "version": dataset.source_version,
            "source_url": dataset.source_url,
            "attribution": dataset.attribution,
            "region_code": dataset.region_code,
            "source_columns": dict(dataset.source_columns),
            "history_sha256": dataset.data_sha256,
            "observations": len(dataset.timestamps),
            "history_start_utc": dataset.timestamps[0].isoformat(),
            "history_end_utc": dataset.timestamps[-1].isoformat(),
        },
        "evaluation_scope": (
            "One chronological 20% holdout per signal; this is an initial public-data "
            "integration check, not a rolling-origin model qualification."
        ),
        "forecast_horizon_hours": args.horizon,
        "signals": {
            name: {
                "unit": forecast.unit,
                "selected_model": forecast.model_id,
                "beats_baseline": forecast.selected_model_beats_baseline,
                "holdout_mae": forecast.holdout_metrics.mae,
                "holdout_rmse": forecast.holdout_metrics.rmse,
                "holdout_bias": forecast.holdout_metrics.bias_predicted_minus_actual,
                "baseline_metrics": {
                    model: {
                        "mae": metrics.mae,
                        "rmse": metrics.rmse,
                        "bias": metrics.bias_predicted_minus_actual,
                    }
                    for model, metrics in forecast.baseline_metrics.items()
                },
                "first_forecast_utc": forecast.points[0].timestamp.isoformat(),
                "first_forecast_value": forecast.points[0].predicted,
                "last_forecast_value": forecast.points[-1].predicted,
                "uncertainty_method": forecast.uncertainty_method,
                "residual_abs_error_p90": forecast.residual_abs_error_p90,
            }
            for name, forecast in bundle.forecasts.items()
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
