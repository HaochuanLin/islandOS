"""The trace script reproduces the two recorded 06 annual costs and its own identity.

This is a script-level test: it loads ``scripts/trace_annual_energy_cost.py`` as a
module and calls ``run_once`` with explicit anchors. The production window builder
is covered separately in ``test_demo_site_history.py``; what matters here is that
the script feeds that window through the same Annual projection path as page 06.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "trace_annual_energy_cost.py"
SPEC = importlib.util.spec_from_file_location("trace_annual_energy_cost", SCRIPT)
assert SPEC and SPEC.loader
trace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trace)


def test_the_trace_script_reproduces_both_recorded_annual_costs():
    at_14 = trace.run_once(datetime(2026, 11, 22, 14, tzinfo=timezone.utc))
    figures_14 = at_14["annual_record"]["figures"]
    assert figures_14["annual_load_energy_kwh"] == 186150
    assert figures_14["annual_energy_cost"] == 7709.553484
    assert at_14["annual_verified"] == {"valid": True, "errors": []}
    assert at_14["target_window"]["first_hour_utc"] == "2026-11-22T15:00:00+00:00"
    assert at_14["target_window"]["last_hour_utc"] == "2026-11-23T14:00:00+00:00"
    assert at_14["target_window"]["load_kwh"] == 510.0
    assert at_14["target_window"]["tariff_sum"] == 3.91

    at_02 = trace.run_once(datetime(2026, 11, 22, 2, tzinfo=timezone.utc))
    figures_02 = at_02["annual_record"]["figures"]
    assert figures_02["annual_load_energy_kwh"] == 186150
    assert figures_02["annual_energy_cost"] == 5332.569196
    assert at_02["annual_verified"] == {"valid": True, "errors": []}
