"""Testable CSV upload -> validation -> strategy comparison -> export workflow.

The Streamlit UI is intentionally thin: this module contains the deterministic
business path so it can be regression-tested without a browser session.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from experiments.compare_energy_water_strategies import (
    Config,
    SiteStep,
    compare_strategies,
    load_site_steps,
)


def parse_uploaded_csv(raw: bytes) -> list[SiteStep]:
    """Validate uploaded CSV bytes using the shared site-series schema."""
    if not isinstance(raw, bytes):
        raise TypeError("Uploaded CSV content must be bytes")
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as temp:
        temp.write(raw)
        temp_path = Path(temp.name)
    try:
        return load_site_steps(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def run_uploaded_strategy_comparison(
    raw: bytes, config: Config
) -> tuple[list[SiteStep], list[dict], list[dict]]:
    """Validate upload bytes, run the five policies, and return detail and summary."""
    steps = parse_uploaded_csv(raw)
    detail, summary = compare_strategies(steps, config)
    return steps, detail, summary


def dataframe_csv(rows: list[dict], provenance: dict | None = None) -> bytes:
    """Serialize report rows and optionally repeat scalar provenance on each row."""
    frame = pd.DataFrame(rows)
    if provenance:
        for key, value in provenance.items():
            frame[key] = value
    return frame.to_csv(index=False).encode("utf-8")
