"""Evaluate an optional PyTorch LSTM water-demand model against naive baselines.

The model is an experimental plug-in candidate, not a production or online-learning
service. One-step forecasts use only observations strictly before each target.
Install the optional dependency with: python -m pip install -r requirements-deep-learning.txt
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import torch
    from torch import nn
except ImportError as exc:  # pragma: no cover - exercised in optional environment
    raise SystemExit(
        "This experiment requires PyTorch. Install with: "
        "python -m pip install -r requirements-deep-learning.txt"
    ) from exc

LAG_HOURS = 168


def load_series(path: str | Path) -> tuple[list[datetime], list[float]]:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"timestamp", "water_demand_m3"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)
    if len(rows) < LAG_HOURS + 100:
        raise ValueError(f"Need at least {LAG_HOURS + 100} continuous hourly rows")

    stamps: list[datetime] = []
    values: list[float] = []
    for line, row in enumerate(rows, start=2):
        raw = (row.get("timestamp") or "").strip()
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid timestamp at CSV line {line}: {raw!r}") from exc
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError(f"timestamp must include timezone at CSV line {line}")
        if stamps and (stamp - stamps[-1]).total_seconds() != 3600:
            raise ValueError(f"Expected continuous hourly timestamps at CSV line {line}")
        try:
            value = float(row.get("water_demand_m3") or "")
        except ValueError as exc:
            raise ValueError(f"Invalid water_demand_m3 at CSV line {line}") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"water_demand_m3 must be finite and non-negative at line {line}")
        stamps.append(stamp)
        values.append(value)
    return stamps, values


def metrics(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual or len(actual) != len(predicted):
        raise ValueError("Metric inputs must be non-empty and aligned")
    errors = [p - a for a, p in zip(actual, predicted)]
    return {
        "mae_m3_per_hour": sum(abs(e) for e in errors) / len(errors),
        "rmse_m3_per_hour": math.sqrt(sum(e * e for e in errors) / len(errors)),
        "bias_predicted_minus_actual_m3_per_hour": sum(errors) / len(errors),
    }


def sequence_features(index: int, stamps: list[datetime], values: list[float],
                      mean: float, scale: float) -> list[list[float]]:
    features = []
    for j in range(index - LAG_HOURS, index):
        stamp = stamps[j]
        features.append([
            (values[j] - mean) / scale,
            math.sin(2 * math.pi * stamp.hour / 24),
            math.cos(2 * math.pi * stamp.hour / 24),
            math.sin(2 * math.pi * stamp.weekday() / 7),
            math.cos(2 * math.pi * stamp.weekday() / 7),
        ])
    return features


def tabular_features(index: int, stamps: list[datetime], values: list[float]) -> list[float]:
    stamp = stamps[index]
    recent = values[index - 24:index]
    return [
        values[index - 1],
        values[index - 24],
        values[index - 168],
        sum(recent) / 24,
        math.sin(2 * math.pi * stamp.hour / 24),
        math.cos(2 * math.pi * stamp.hour / 24),
        math.sin(2 * math.pi * stamp.weekday() / 7),
        math.cos(2 * math.pi * stamp.weekday() / 7),
    ]


class DemandLSTM(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.lstm = nn.LSTM(input_size=5, hidden_size=16, num_layers=1, batch_first=True)
        self.head = nn.Sequential(nn.Linear(16, 8), nn.ReLU(), nn.Linear(8, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        sequence, _ = self.lstm(x)
        return self.head(sequence[:, -1, :]).squeeze(-1)



def _fit_with_chronological_early_stopping(
    x: torch.Tensor,
    y: torch.Tensor,
    max_epochs: int,
    seed: int,
    scale: float,
    patience: int = 4,
) -> tuple[DemandLSTM, dict[str, Any]]:
    """Choose an epoch count on a chronological validation tail, then refit all history."""
    if len(x) < 64:
        raise ValueError("Need at least 64 training examples for chronological early stopping")
    validation_count = max(24, int(len(x) * 0.15))
    fit_count = len(x) - validation_count
    x_fit, y_fit = x[:fit_count], y[:fit_count]
    x_validation, y_validation = x[fit_count:], y[fit_count:]
    loss_fn = nn.MSELoss()
    batch_size = 128
    torch.manual_seed(seed)
    probe = DemandLSTM()
    optimizer = torch.optim.Adam(probe.parameters(), lr=0.003, weight_decay=1e-4)
    best_loss = float("inf")
    best_epoch = 1
    stale_epochs = 0
    validation_history: list[float] = []
    for epoch in range(1, max_epochs + 1):
        probe.train()
        permutation = torch.randperm(len(x_fit))
        for start in range(0, len(permutation), batch_size):
            indices = permutation[start:start + batch_size]
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(probe(x_fit[indices]), y_fit[indices])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(probe.parameters(), max_norm=1.0)
            optimizer.step()
        probe.eval()
        with torch.no_grad():
            val_predictions = probe(x_validation)
            val_mae = float(torch.mean(torch.abs(val_predictions - y_validation)).item()) * scale
        validation_history.append(val_mae)
        if val_mae < best_loss - 1e-8:
            best_loss = val_mae
            best_epoch = epoch
            stale_epochs = 0
        else:
            stale_epochs += 1
        if stale_epochs >= patience:
            break

    # The validation tail chooses training duration only. Final fit uses all
    # available pre-test history, and the test window is never used for tuning.
    torch.manual_seed(seed)
    final_model = DemandLSTM()
    final_optimizer = torch.optim.Adam(final_model.parameters(), lr=0.003, weight_decay=1e-4)
    final_model.train()
    for _ in range(best_epoch):
        permutation = torch.randperm(len(x))
        for start in range(0, len(permutation), batch_size):
            indices = permutation[start:start + batch_size]
            final_optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(final_model(x[indices]), y[indices])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(final_model.parameters(), max_norm=1.0)
            final_optimizer.step()
    return final_model, {
        "max_epochs": max_epochs,
        "selected_epochs": best_epoch,
        "validation_samples": validation_count,
        "validation_mae_m3_per_hour": best_loss,
        "validation_history_mae_m3_per_hour": validation_history,
        "selection_method": "chronological validation tail with early stopping; final refit on all pre-test history",
    }


def compare(input_csv: str | Path, output_json: str | Path,
            train_fraction: float = 0.70, epochs: int = 12,
            seed: int = 20261024) -> dict[str, Any]:
    if not 0.60 <= train_fraction <= 0.85:
        raise ValueError("train_fraction must be between 0.60 and 0.85")
    if not 1 <= epochs <= 100:
        raise ValueError("epochs must be between 1 and 100")
    random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)

    stamps, values = load_series(input_csv)
    split = int(len(values) * train_fraction)
    train_indices = list(range(LAG_HOURS, split))
    test_indices = list(range(split, len(values)))
    if len(train_indices) < 64 or len(test_indices) < 24:
        raise ValueError("Not enough train/test samples after lag warm-up")

    validation_count = max(24, int(len(train_indices) * 0.15))
    scaler_fit_end = train_indices[len(train_indices) - validation_count]
    history = values[:scaler_fit_end]
    mean = sum(history) / len(history)
    variance = sum((x - mean) ** 2 for x in history) / len(history)
    scale = max(math.sqrt(variance), 1e-6)

    x_train = torch.tensor(
        [sequence_features(i, stamps, values, mean, scale) for i in train_indices],
        dtype=torch.float32,
    )
    y_train = torch.tensor([(values[i] - mean) / scale for i in train_indices], dtype=torch.float32)
    x_test = torch.tensor(
        [sequence_features(i, stamps, values, mean, scale) for i in test_indices],
        dtype=torch.float32,
    )

    model, early_stopping = _fit_with_chronological_early_stopping(
        x_train, y_train, epochs, seed, scale
    )
    model.eval()
    with torch.no_grad():
        predictions = model(x_test).cpu().tolist()
    lstm_predictions = [max(0.0, float(value) * scale + mean) for value in predictions]
    actual = [values[i] for i in test_indices]
    from sklearn.ensemble import HistGradientBoostingRegressor

    hgb = HistGradientBoostingRegressor(
        learning_rate=0.08, max_iter=120, max_leaf_nodes=15,
        l2_regularization=1.0, random_state=2026,
    )
    hgb.fit(
        [tabular_features(i, stamps, values) for i in train_indices],
        [values[i] for i in train_indices],
    )
    hgb_predictions = [max(0.0, float(p)) for p in hgb.predict(
        [tabular_features(i, stamps, values) for i in test_indices]
    )]
    prediction_sets = {
        "persistence_previous_hour": [values[i - 1] for i in test_indices],
        "seasonal_naive_previous_day": [values[i - 24] for i in test_indices],
        "seasonal_naive_previous_week": [values[i - 168] for i in test_indices],
        "lstm_deep_learning": lstm_predictions,
        "hist_gradient_boosting": hgb_predictions,
    }
    test_metrics = {name: metrics(actual, pred) for name, pred in prediction_sets.items()}

    # A second expanding-window check refits the model once at a later boundary.
    # This guards against treating one lucky split as sufficient evidence.
    second_start = split + max(24, (len(values) - split) // 2)
    wf_indices = list(range(second_start, len(values)))
    wf_summary: dict[str, Any] = {"method": "second chronological window; fit uses only earlier targets"}
    if len(wf_indices) >= 24:
        wf_train_indices = list(range(LAG_HOURS, second_start))
        wf_validation_count = max(24, int(len(wf_train_indices) * 0.15))
        wf_scaler_fit_end = wf_train_indices[len(wf_train_indices) - wf_validation_count]
        wf_history = values[:wf_scaler_fit_end]
        wf_mean = sum(wf_history) / len(wf_history)
        wf_variance = sum((value - wf_mean) ** 2 for value in wf_history) / len(wf_history)
        wf_scale = max(math.sqrt(wf_variance), 1e-6)
        wf_x = torch.tensor(
            [sequence_features(i, stamps, values, wf_mean, wf_scale) for i in wf_train_indices],
            dtype=torch.float32,
        )
        wf_y = torch.tensor(
            [(values[i] - wf_mean) / wf_scale for i in wf_train_indices],
            dtype=torch.float32,
        )
        wf_model, wf_early_stopping = _fit_with_chronological_early_stopping(
            wf_x, wf_y, epochs, seed, wf_scale
        )
        wf_model.eval()
        wf_test_x = torch.tensor(
            [sequence_features(i, stamps, values, wf_mean, wf_scale) for i in wf_indices],
            dtype=torch.float32,
        )
        with torch.no_grad():
            wf_pred = [
                max(0.0, float(p) * wf_scale + wf_mean)
                for p in wf_model(wf_test_x).tolist()
            ]
        wf_actual = [values[i] for i in wf_indices]
        wf_hgb = HistGradientBoostingRegressor(
            learning_rate=0.08, max_iter=120, max_leaf_nodes=15,
            l2_regularization=1.0, random_state=2026,
        )
        wf_hgb.fit(
            [tabular_features(i, stamps, values) for i in wf_train_indices],
            [values[i] for i in wf_train_indices],
        )
        wf_hgb_pred = [max(0.0, float(p)) for p in wf_hgb.predict(
            [tabular_features(i, stamps, values) for i in wf_indices]
        )]
        wf_sets = {
            "persistence_previous_hour": [values[i - 1] for i in wf_indices],
            "seasonal_naive_previous_week": [values[i - 168] for i in wf_indices],
            "lstm_deep_learning": wf_pred,
            "hist_gradient_boosting": wf_hgb_pred,
        }
        wf_summary.update({
            "training_samples": len(wf_train_indices),
            "test_samples": len(wf_indices),
            "scaler_fit_on_training_history_only": True,
            "scaler_fit_end_timestamp": stamps[wf_scaler_fit_end - 1].isoformat(),
            "validation_tail_excluded_from_scaler_fit": True,
            "early_stopping": wf_early_stopping,
            "test_metrics": {name: metrics(wf_actual, pred) for name, pred in wf_sets.items()},
        })

    rows = []
    for row_index, (index, actual_value, lstm_value, hgb_value) in enumerate(zip(test_indices, actual, lstm_predictions, hgb_predictions)):
        rows.append({
            "timestamp": stamps[index].isoformat(),
            "actual_water_demand_m3": actual_value,
            "lstm_deep_learning": lstm_value,
            "hist_gradient_boosting": hgb_value,
            "persistence_previous_hour": values[index - 1],
            "seasonal_naive_previous_day": values[index - 24],
            "seasonal_naive_previous_week": values[index - 168],
        })
    result: dict[str, Any] = {
        "status": "models_compared",
        "model_family": "PyTorch LSTM recurrent neural network",
        "input_csv": Path(input_csv).name,
        "input_csv_sha256": hashlib.sha256(Path(input_csv).read_bytes()).hexdigest(),
        "library_versions": {"torch": torch.__version__},
        "seed": seed,
        "training": {
            "train_fraction": train_fraction,
            "training_samples": len(train_indices),
            "test_samples": len(test_indices),
            "sequence_length_hours": LAG_HOURS,
            "epochs": epochs,
            "features": ["normalized past demand", "hour-of-day sine/cosine", "day-of-week sine/cosine"],
            "scaler_fit_on_training_history_only": True,
            "scaler_fit_end_timestamp": stamps[scaler_fit_end - 1].isoformat(),
            "validation_tail_excluded_from_scaler_fit": True,
            "early_stopping": early_stopping,
        },
        "test_metrics": test_metrics,
        "walk_forward_summary": wf_summary,
        "lowest_mae_model_on_this_holdout": min(test_metrics, key=lambda k: test_metrics[k]["mae_m3_per_hour"]),
        "forecast_rows": rows,
        "limitations": [
            "Experimental one-step-ahead LSTM; not an online-learning system.",
            "Earlier observed demand in the test window is used as lag input, matching rolling one-step operation.",
            "One source series and one secondary chronological window do not establish cross-site transfer.",
            "Forecast quality does not establish improved dispatch economics or safe plant operation.",
            "Predictions are candidate outputs and are not automatically wired into the live app or a controller.",
        ],
    }
    output = Path(output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Prepared hourly CSV with timestamp and water_demand_m3")
    parser.add_argument("--output", default="build/deep-learning/lstm_comparison.json")
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20261024)
    args = parser.parse_args()
    report = compare(args.input_csv, args.output, args.train_fraction, args.epochs, args.seed)
    print(json.dumps({
        "status": report["status"],
        "model_family": report["model_family"],
        "training_samples": report["training"]["training_samples"],
        "test_samples": report["training"]["test_samples"],
        "test_metrics": report["test_metrics"],
        "walk_forward_summary": report["walk_forward_summary"],
        "lowest_mae_model_on_this_holdout": report["lowest_mae_model_on_this_holdout"],
    }, indent=2))


if __name__ == "__main__":
    main()
