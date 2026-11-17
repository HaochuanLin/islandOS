"""Empirical validation for forecast prediction intervals.

Intervals are treated as marginal, horizon-specific bounds. This module does
not infer joint scenario probabilities or claim calibrated uncertainty until
held-out chronological observations provide enough evidence.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from numbers import Real
from typing import Sequence


def evaluate_prediction_interval(
    actual: Sequence[float],
    lower: Sequence[float],
    upper: Sequence[float],
    *,
    nominal_coverage: float,
    timestamps: Sequence[datetime] | None = None,
    minimum_samples: int = 30,
) -> dict:
    """Score aligned prediction bounds on held-out observations.

    Coverage is the fraction of actual values inside [lower, upper]. Mean width
    is reported in the original signal unit. If timestamps are supplied they
    must be timezone-aware, strictly increasing and hourly contiguous; callers
    should pass only a chronological held-out block, never training rows.
    """
    if isinstance(nominal_coverage, bool) or not isinstance(nominal_coverage, Real):
        raise ValueError("nominal_coverage must be numeric between 0 and 1")
    nominal = float(nominal_coverage)
    if not math.isfinite(nominal) or not 0 < nominal < 1:
        raise ValueError("nominal_coverage must be strictly between 0 and 1")
    if isinstance(minimum_samples, bool) or not isinstance(minimum_samples, int) or minimum_samples < 1:
        raise ValueError("minimum_samples must be a positive integer")

    def values(name: str, series: Sequence[float]) -> list[float]:
        if isinstance(series, (str, bytes)):
            raise ValueError(f"{name} must be a numeric sequence")
        try:
            raw = list(series)
        except TypeError as exc:
            raise ValueError(f"{name} must be a numeric sequence") from exc
        result = []
        for index, item in enumerate(raw):
            if isinstance(item, bool) or not isinstance(item, Real) or not math.isfinite(float(item)):
                raise ValueError(f"{name}[{index}] must be finite numeric data")
            result.append(float(item))
        return result

    truth = values("actual", actual)
    lo = values("lower", lower)
    hi = values("upper", upper)
    if not truth or len(truth) != len(lo) or len(truth) != len(hi):
        raise ValueError("actual, lower and upper must be non-empty and equally sized")
    if any(a > b for a, b in zip(lo, hi)):
        raise ValueError("lower interval bound cannot exceed upper bound")
    if timestamps is not None:
        stamps = list(timestamps)
        if len(stamps) != len(truth):
            raise ValueError("timestamps must align with interval observations")
        normalized = []
        for stamp in stamps:
            if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("timestamps must be timezone-aware")
            normalized.append(stamp.astimezone(timezone.utc))
        for left, right in zip(normalized, normalized[1:]):
            if (right - left).total_seconds() != 3600:
                raise ValueError("timestamps must be strictly increasing and hourly contiguous")

    covered = [low <= observed <= high for observed, low, high in zip(truth, lo, hi)]
    widths = [high - low for low, high in zip(lo, hi)]
    under = [max(0.0, low - observed) for observed, low in zip(truth, lo)]
    over = [max(0.0, observed - high) for observed, high in zip(truth, hi)]
    count = len(truth)
    empirical = sum(covered) / count
    return {
        "samples": count,
        "nominal_coverage": nominal,
        "empirical_coverage": empirical,
        "coverage_error": empirical - nominal,
        "mean_interval_width": sum(widths) / count,
        "under_coverage_mean_excess": sum(under) / count,
        "over_coverage_mean_excess": sum(over) / count,
        "calibration_evidence": "sufficient_sample_screen" if count >= minimum_samples else "insufficient_sample",
        "minimum_samples_for_screen": minimum_samples,
        "claim_scope": "marginal_interval_empirical_coverage_on_supplied_held_out_block",
        "joint_scenario_probabilities_available": False,
        "calibrated_uncertainty_claim_authorized": False,
    }
