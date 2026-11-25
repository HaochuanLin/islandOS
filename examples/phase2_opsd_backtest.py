"""Run the generic IslandOS forecast engine on a local OPSD hourly CSV.

Example:
    python examples/phase2_opsd_backtest.py --csv ./time_series_60min_singleindex.csv --region AT
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from typing import Sequence

from islandos_core.forecast_engine import evaluate_signal_rolling, forecast_signals
from islandos_core.forecast_signal_catalog import FORECAST_SIGNAL_SPECS, forecast_site_signals
from islandos_core.opsd_adapter import load_opsd_singleindex_csv
from islandos_core.prediction_engine import ForecastRequest, PredictionEngine, SignalObservation


def _utc_bound(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise argparse.ArgumentTypeError("date bounds must include a UTC offset, e.g. 2020-01-01T00:00:00Z")
    return value


_OPSD_CANONICAL_SIGNAL_MAP = {
    # OPSD source units are retained by the loader. These explicit scale factors
    # adapt them to IslandOS canonical units without silently changing the source.
    "load": ("load_kw", "MW", "kW", 1000.0, "MW × 1000 = kW"),
    "solar": ("pv_power_kw", "MW", "kW", 1000.0, "MW × 1000 = kW"),
    "wind": ("wind_power_kw", "MW", "kW", 1000.0, "MW × 1000 = kW"),
    "price": ("tariff_per_kwh", "EUR/MWh", "EUR/kWh", 0.001, "EUR/MWh × 0.001 = EUR/kWh"),
}


def _canonicalize_opsd_history(dataset):
    """Convert OPSD fields to canonical IslandOS IDs with explicit unit scaling."""
    canonical_history = {}
    canonical_units = {}
    source_mapping = {}
    for source_signal, values in dataset.history.items():
        if source_signal not in _OPSD_CANONICAL_SIGNAL_MAP:
            raise ValueError(f"unsupported OPSD signal for canonical forecasting: {source_signal}")
        signal_id, expected_source_unit, forecast_unit, factor, expression = _OPSD_CANONICAL_SIGNAL_MAP[source_signal]
        actual_source_unit = dataset.units.get(source_signal)
        if actual_source_unit != expected_source_unit:
            raise ValueError(
                f"{source_signal} source unit mismatch: expected {expected_source_unit}, got {actual_source_unit}"
            )
        canonical_history[signal_id] = tuple(float(value) * factor for value in values)
        canonical_units[signal_id] = forecast_unit
        source_mapping[source_signal] = {
            "canonical_signal_id": signal_id,
            "source_unit": expected_source_unit,
            "forecast_unit": forecast_unit,
            "multiplier": factor,
            "conversion": expression,
        }
    if not canonical_history:
        raise ValueError("OPSD dataset contains no signals for canonical forecasting")
    return canonical_history, canonical_units, source_mapping


def _score_holdout(actual, predicted):
    """Score one untouched chronological holdout in the signal's canonical unit."""
    actual_values = tuple(float(value) for value in actual)
    predicted_values = tuple(float(value) for value in predicted)
    if not actual_values or len(actual_values) != len(predicted_values):
        raise ValueError("holdout actual and predicted values must have equal non-empty lengths")
    if any(not math.isfinite(value) for value in actual_values + predicted_values):
        raise ValueError("holdout actual and predicted values must be finite")
    errors = tuple(guess - truth for truth, guess in zip(actual_values, predicted_values))
    denominator = sum(abs(value) for value in actual_values)
    return {
        "samples": len(actual_values),
        "mae": sum(abs(error) for error in errors) / len(errors),
        "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias_predicted_minus_actual": sum(errors) / len(errors),
        "wape_percent": (
            None
            if denominator == 0
            else sum(abs(error) for error in errors) / denominator * 100.0
        ),
    }


def _canonical_prediction_report(
    dataset,
    forecast_horizon: int,
    rolling_horizons=(),
    max_rolling_folds: int | None = None,
):
    """Evaluate model selection on history and score it on an untouched final block."""
    if (
        isinstance(forecast_horizon, bool)
        or not isinstance(forecast_horizon, int)
        or not 1 <= forecast_horizon <= 168
    ):
        raise ValueError("forecast_horizon must be an integer from 1 to 168 hours")

    timestamps = tuple(dataset.timestamps)
    minimum_training_samples = 72
    if len(timestamps) < minimum_training_samples + forecast_horizon:
        required = minimum_training_samples + forecast_horizon
        raise ValueError(
            f"OPSD history requires at least {required} contiguous hourly observations: "
            f"{minimum_training_samples} for canonical training and {forecast_horizon} "
            "for the untouched final chronological holdout"
        )

    canonical_history, canonical_units, source_mapping = _canonicalize_opsd_history(dataset)
    training_timestamps = tuple(
        stamp.astimezone(timezone.utc) for stamp in timestamps[:-forecast_horizon]
    )
    holdout_timestamps = tuple(
        stamp.astimezone(timezone.utc) for stamp in timestamps[-forecast_horizon:]
    )
    training_history = {
        signal_id: tuple(values[:-forecast_horizon])
        for signal_id, values in canonical_history.items()
    }
    holdout_history = {
        signal_id: tuple(values[-forecast_horizon:])
        for signal_id, values in canonical_history.items()
    }

    engine = PredictionEngine()
    bundle = forecast_site_signals(
        training_timestamps,
        training_history,
        canonical_units,
        forecast_horizon,
        engine=engine,
        backtest_horizon=24,
        season_length=24,
    )
    initial_history = min(48, len(training_timestamps) - 1)
    signals = {}
    for source_signal, mapping in source_mapping.items():
        signal_id = mapping["canonical_signal_id"]
        spec = FORECAST_SIGNAL_SPECS[signal_id]
        candidate_evaluations = {}
        for validation_horizon in rolling_horizons:
            ranking = engine.evaluate_candidates(
                training_history[signal_id],
                initial_history=initial_history,
                horizon=validation_horizon,
                season_length=24,
                non_negative=spec.non_negative,
                max_folds=max_rolling_folds,
            )
            available_complete_folds = (
                len(training_history[signal_id]) - initial_history
            ) // validation_horizon
            selected_fold_indices = [
                fold.fold_index for fold in ranking[0].fold_metrics
            ]
            if not selected_fold_indices:
                raise RuntimeError("canonical rolling evaluation returned no complete folds")
            scored_samples = ranking[0].samples
            skipped_complete_folds = (
                available_complete_folds - len(selected_fold_indices)
            )
            skipped_validation_samples = skipped_complete_folds * validation_horizon
            excluded_trailing_samples = (
                len(training_history[signal_id]) - initial_history
            ) % validation_horizon
            first_validation_index = (
                initial_history + (selected_fold_indices[0] - 1) * validation_horizon
            )
            last_validation_end_index = (
                initial_history + selected_fold_indices[-1] * validation_horizon - 1
            )
            candidate_evaluations[str(validation_horizon)] = {
                "evaluation_window": {
                    "initial_history_samples": initial_history,
                    "initial_history_start_utc": training_timestamps[0].isoformat(),
                    "initial_history_end_utc": training_timestamps[initial_history - 1].isoformat(),
                    "first_validation_start_utc": training_timestamps[first_validation_index].isoformat(),
                    "last_scored_validation_end_utc": training_timestamps[
                        last_validation_end_index
                    ].isoformat(),
                    "validation_horizon_hours": validation_horizon,
                    "complete_folds": available_complete_folds,
                    "available_complete_folds": available_complete_folds,
                    "evaluated_folds": len(selected_fold_indices),
                    "skipped_complete_folds": skipped_complete_folds,
                    "skipped_validation_samples": skipped_validation_samples,
                    "fold_indices": selected_fold_indices,
                    "max_rolling_folds": max_rolling_folds,
                    "selection_method": (
                        "all_complete_folds"
                        if not skipped_complete_folds
                        else "deterministic_even_spacing_with_first_and_last_fold"
                    ),
                    "scored_samples": scored_samples,
                    "excluded_trailing_samples": excluded_trailing_samples,
                },
                "best_by_mae": ranking[0].model_id,
                "models": [
                    {
                        "model_id": item.model_id,
                        "model_version": item.model_version,
                        "folds": item.folds,
                        "samples": item.samples,
                        "mae": item.mae,
                        "rmse": item.rmse,
                        "bias_predicted_minus_actual": item.bias_predicted_minus_actual,
                        "wape_percent": item.wape_percent,
                        "fold_metrics": [
                            {
                                "fold_index": fold.fold_index,
                                "train_start_utc": training_timestamps[0].isoformat(),
                                "train_end_utc": training_timestamps[
                                    initial_history + (fold.fold_index - 1) * validation_horizon - 1
                                ].isoformat(),
                                "validation_start_utc": training_timestamps[
                                    initial_history + (fold.fold_index - 1) * validation_horizon
                                ].isoformat(),
                                "validation_end_utc": training_timestamps[
                                    initial_history + fold.fold_index * validation_horizon - 1
                                ].isoformat(),
                                "train_samples": fold.train_samples,
                                "samples": fold.samples,
                                "mae": fold.mae,
                                "rmse": fold.rmse,
                                "bias_predicted_minus_actual": fold.bias_predicted_minus_actual,
                            }
                            for fold in item.fold_metrics
                        ],
                    }
                    for item in ranking
                ],
            }

        result = bundle.results[signal_id]
        predicted_holdout = tuple(point.predicted_value for point in result.points)
        if tuple(point.timestamp for point in result.points) != holdout_timestamps:
            raise RuntimeError("canonical forecast targets do not match the final chronological holdout")

        # Generate every candidate forecast from the same pre-holdout history.
        # Actual holdout values are passed only to the scoring function below.
        holdout_request = ForecastRequest(
            signal_id=signal_id,
            unit=canonical_units[signal_id],
            history=tuple(
                SignalObservation(timestamp=stamp, value=value)
                for stamp, value in zip(training_timestamps, training_history[signal_id])
            ),
            target_timestamps=holdout_timestamps,
            non_negative=spec.non_negative,
        )
        holdout_candidate_models = []
        holdout_candidate_exclusions = {}
        selected_holdout_metrics = None
        for candidate_id, candidate_version in engine.available_candidates():
            try:
                candidate_predictions = engine.predict_candidate(
                    holdout_request,
                    candidate_id,
                    season_length=24,
                )
            except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
                holdout_candidate_exclusions[candidate_id] = f"{type(exc).__name__}: {exc}"
                continue

            candidate_metrics = _score_holdout(
                holdout_history[signal_id],
                candidate_predictions,
            )
            if candidate_id == result.model_id:
                if candidate_predictions != predicted_holdout:
                    raise RuntimeError(
                        "selected candidate forecast differs from canonical prediction service output"
                    )
                selected_holdout_metrics = candidate_metrics

            holdout_candidate_models.append({
                "model_id": candidate_id,
                "model_version": candidate_version,
                "selected_for_forecast": candidate_id == result.model_id,
                "metrics": candidate_metrics,
                "forecast_points": [
                    {
                        "timestamp_utc": stamp.isoformat(),
                        "predicted_value": prediction,
                    }
                    for stamp, prediction in zip(holdout_timestamps, candidate_predictions)
                ],
            })

        if selected_holdout_metrics is None:
            raise RuntimeError("selected canonical model did not produce a valid holdout forecast")

        signals[source_signal] = {
            "canonical_signal_id": signal_id,
            "input_history_sha256": result.input_history_sha256,
            "unit": result.unit,
            "selected_model": result.model_id,
            "selected_model_version": result.model_version,
            "selection_backtest": {
                "folds": result.backtest.folds,
                "samples": result.backtest.samples,
                "mae": result.backtest.mae,
                "rmse": result.backtest.rmse,
                "bias_predicted_minus_actual": result.backtest.bias_predicted_minus_actual,
                "wape_percent": result.backtest.wape_percent,
                "fold_metrics": [
                    {
                        "fold_index": fold.fold_index,
                        "train_samples": fold.train_samples,
                        "samples": fold.samples,
                        "mae": fold.mae,
                        "rmse": fold.rmse,
                        "bias_predicted_minus_actual": fold.bias_predicted_minus_actual,
                    }
                    for fold in result.backtest.fold_metrics
                ],
            },
            "holdout_metrics": selected_holdout_metrics,
            "holdout_candidate_evaluations": {
                "method": (
                    "all registered candidates forecast from the same pre-holdout history; "
                    "actual holdout values are used only for scoring"
                ),
                "models": holdout_candidate_models,
                "excluded_candidates": holdout_candidate_exclusions,
            },
            "rolling_origin_candidate_evaluations": candidate_evaluations,
            "forecast_points": [
                {
                    "timestamp_utc": point.timestamp.isoformat(),
                    "predicted_value": point.predicted_value,
                    "lower_bound": point.lower_bound,
                    "upper_bound": point.upper_bound,
                }
                for point in result.points
            ],
            "interval_method": result.interval_method,
            "interval_calibration_samples": result.interval_calibration_samples,
            "limitations": list(result.limitations),
        }
    return {
        "engine": "canonical PredictionEngine via forecast_site_signals",
        "source_data_sha256": dataset.data_sha256,
        "canonical_bundle_history_sha256": bundle.input_history_sha256,
        "source_to_canonical_mapping": source_mapping,
        "holdout_window": {
            "method": "single_final_chronological_holdout",
            "training_samples": len(training_timestamps),
            "training_start_utc": training_timestamps[0].isoformat(),
            "training_end_utc": training_timestamps[-1].isoformat(),
            "holdout_samples": forecast_horizon,
            "holdout_start_utc": holdout_timestamps[0].isoformat(),
            "holdout_end_utc": holdout_timestamps[-1].isoformat(),
            "excluded_from_candidate_selection": True,
            "excluded_from_rolling_origin_evaluation": True,
            "excluded_from_interval_calibration": True,
        },
        "candidate_selection": (
            "lowest aggregate MAE among registered candidates on pre-holdout chronological "
            "rolling-origin replay; not a deployment promotion gate"
        ),
        "rolling_evaluation_scope": (
            "Rolling-origin candidate evaluations use only the pre-holdout training history. "
            "Each requested horizon uses chronological expanding-window blocks and trains only "
            "on observations available before each block. When max_rolling_folds is set, complete "
            "folds are sampled deterministically and evenly with the first and last folds retained. "
            "Incomplete trailing observations are excluded rather than shortened into a different horizon."
        ),
        "signals": signals,
        "limitations": [
            "OPSD observations are geographically aggregated public history, not facility telemetry.",
            "Unit scaling is explicit and does not convert country-level values into site-level values.",
            "Candidate selection and empirical error-band estimation reuse pre-holdout rolling-origin history; "
            "intervals are descriptive and not independently calibrated.",
            "The final chronological holdout is one historical test block, not repeated independent "
            "validation across sites, seasons, or operating regimes.",
            "No site accuracy, operational feasibility, or customer savings are established.",
        ],
    }

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
    parser.add_argument("--horizon", type=int, default=24, help="Final chronological holdout / forecast horizon in hours (1–168)")
    parser.add_argument(
        "--rolling-validation", action="store_true",
        help="Also evaluate legacy and canonical forecast candidates on expanding windows",
    )
    parser.add_argument(
        "--rolling-horizons", nargs="+", type=int, default=(1, 6, 24, 168),
        help="Rolling validation horizons in hours (default: 1 6 24 168)",
    )
    parser.add_argument(
        "--max-rolling-folds",
        type=int,
        default=168,
        help=(
            "Maximum canonical rolling-origin folds per signal and horizon "
            "(default: 168); first and last complete folds are retained"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_rolling_folds < 2:
        parser.error("--max-rolling-folds must be at least 2")
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
    canonical_horizons = tuple(args.rolling_horizons) if args.rolling_validation else ()
    report["canonical_prediction_service"] = _canonical_prediction_report(
        dataset,
        args.horizon,
        rolling_horizons=canonical_horizons,
        max_rolling_folds=(
            args.max_rolling_folds if args.rolling_validation else None
        ),
    )
    if args.rolling_validation:
        report["rolling_validation"] = {
            "method": "expanding_window",
            "folds": 4,
            "minimum_training_observations": 72,
            "horizons_hours": list(args.rolling_horizons),
            "signals": {},
        }
        for name, values in dataset.history.items():
            horizon_results = evaluate_signal_rolling(
                dataset.timestamps,
                values,
                horizons=tuple(args.rolling_horizons),
                non_negative=name != "price",
                min_train_size=72,
                folds=4,
            )
            signal_report = {}
            for horizon, models in horizon_results.items():
                baseline_ids = ("persistence", "seasonal_naive_24h")
                ridge = models["ridge_autoregressive"]
                fold_win_count = sum(
                    ridge.folds[index].mae
                    < min(models[baseline_id].folds[index].mae for baseline_id in baseline_ids)
                    for index in range(len(ridge.folds))
                )
                signal_report[str(horizon)] = {
                    "best_by_mean_mae": min(models, key=lambda model_id: models[model_id].mean_mae),
                    "ridge_fold_win_rate_vs_best_baseline": fold_win_count / len(ridge.folds),
                    "models": {
                        model_id: {
                            "mean_mae": score.mean_mae,
                            "mean_rmse": score.mean_rmse,
                            "mean_bias_predicted_minus_actual": score.mean_bias,
                            "folds": [
                                {
                                    "samples": fold.samples,
                                    "mae": fold.mae,
                                    "rmse": fold.rmse,
                                    "bias_predicted_minus_actual": fold.bias_predicted_minus_actual,
                                }
                                for fold in score.folds
                            ],
                        }
                        for model_id, score in models.items()
                    },
                }
            report["rolling_validation"]["signals"][name] = signal_report
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
