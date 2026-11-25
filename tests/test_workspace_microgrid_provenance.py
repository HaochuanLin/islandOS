"""Provenance tests for the Microgrid screening workspace section.

Covers the input fingerprint attached to candidate CSV exports and the
consistency of the forecast-related copy. The fingerprint is a pure function
in ``islandos_ui.workspace``; the remaining assertions read the rendered
section source so a future copy edit cannot quietly reintroduce the
"says it is not a forecast, then calls the forecast" contradiction.
"""
from __future__ import annotations

import re
from pathlib import Path

from islandos_ui import workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_FILE = REPO_ROOT / "islandos_ui" / "workspace.py"


def base_kwargs() -> dict:
    return {
        "horizon": 72,
        "pv_peak": 45.0,
        "wind_mean": 12.0,
        "essential_mean": 24.0,
        "water_demand": 0.45,
        "ro_rating": 20.0,
        "sec": 4.0,
        "tank_capacity": 60.0,
        "initial_water": 15.0,
        "pv_series": [10.0, 20.0, 30.0],
        "wind_series": [5.0, 5.0, 5.0],
        "load_series": [24.0, 24.0, 24.0],
        "demand_series": [0.45, 0.45, 0.45],
    }


def test_fingerprint_is_stable_for_identical_inputs():
    first = workspace.microgrid_scenario_fingerprint(**base_kwargs())
    second = workspace.microgrid_scenario_fingerprint(**base_kwargs())
    assert first == second


def test_fingerprint_changes_when_setting_or_series_changes():
    baseline = workspace.microgrid_scenario_fingerprint(**base_kwargs())

    horizon_variant = base_kwargs()
    horizon_variant["horizon"] = 48
    assert workspace.microgrid_scenario_fingerprint(**horizon_variant) != baseline

    pv_variant = base_kwargs()
    pv_variant["pv_peak"] = 50.0
    assert workspace.microgrid_scenario_fingerprint(**pv_variant) != baseline

    for series_key in ("pv_series", "wind_series", "load_series", "demand_series"):
        variant = base_kwargs()
        variant[series_key] = [value + 1.0 for value in variant[series_key]]
        assert workspace.microgrid_scenario_fingerprint(**variant) != baseline


def test_fingerprint_is_full_64_char_lowercase_hex():
    digest = workspace.microgrid_scenario_fingerprint(**base_kwargs())
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert digest == digest.lower()


def test_candidate_export_carries_fingerprint_column_and_caption():
    source = WORKSPACE_FILE.read_text(encoding="utf-8")
    assert 'frame["scenario_input_sha256"] = scenario_input_sha256' in source
    assert "Scenario input SHA-256:" in source


def test_microgrid_forecast_copy_is_consistent():
    source = WORKSPACE_FILE.read_text(encoding="utf-8")
    # The old contradiction: the section calls a forecast, then denies it.
    assert "does not predict future weather or demand" not in source

    warning_block = source.split('elif page == "Microgrid screening":', 1)[1].split(
        'with st.expander("Scenario and equipment assumptions"', 1
    )[0]
    assert "seasonal-naive baseline forecast" in warning_block
    assert "not a forecast" not in warning_block
