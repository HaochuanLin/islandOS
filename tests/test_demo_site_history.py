"""The default window must be a function of its anchor, not of the host clock."""

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from islandos_core.demo_site_history import (
    SYNTHETIC_HISTORY_HOURS,
    build_synthetic_site_history,
)

MODULE = Path(__file__).resolve().parents[1] / "islandos_core" / "demo_site_history.py"
SITE = {"pv_rated_kw": 40.0, "wind_rated_kw": 20.0}


def _history(hour: int, *, minute: int = 0):
    return build_synthetic_site_history(
        datetime(2026, 11, 22, hour, minute, tzinfo=timezone.utc), **SITE
    )


def test_the_same_anchor_reproduces_the_same_window():
    first = _history(14)
    second = _history(14)
    assert first == second
    assert first.timestamps == second.timestamps
    assert first.pv_power_kw == second.pv_power_kw


def test_the_window_is_seven_days_ending_at_the_truncated_anchor():
    history = _history(14, minute=37)
    assert len(history.timestamps) == SYNTHETIC_HISTORY_HOURS == 168
    assert history.anchor_utc == datetime(2026, 11, 22, 14, tzinfo=timezone.utc)
    assert history.timestamps[0] == datetime(2026, 11, 15, 15, tzinfo=timezone.utc)
    assert history.timestamps[-1] == history.anchor_utc


@pytest.mark.parametrize("hour", [2, 14])
def test_every_24_hour_block_carries_the_same_load_energy(hour: int):
    history = _history(hour)
    for start in range(0, SYNTHETIC_HISTORY_HOURS, 24):
        assert round(sum(history.load_kw[start:start + 24]), 6) == 510.0


def test_moving_the_anchor_changes_the_renewable_window_not_the_daily_load():
    two = _history(2)
    fourteen = _history(14)
    # Same length and same daily load total, different PV phase: this is the exact
    # property that made 7,709.55 and 5,332.57 two windows of one formula.
    assert two.pv_power_kw != fourteen.pv_power_kw
    assert sum(two.load_kw[:24]) == sum(fourteen.load_kw[:24]) == 510.0
    assert round(sum(two.tariff_per_kwh[-24:]), 6) == 3.91
    assert round(sum(fourteen.tariff_per_kwh[-24:]), 6) == 3.91


def test_a_naive_anchor_is_refused():
    with pytest.raises(ValueError, match="timezone-aware"):
        build_synthetic_site_history(datetime(2026, 11, 22, 14), **SITE)


def test_the_builder_does_not_read_the_wall_clock():
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    clock_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"now", "utcnow", "today"}
    ]
    assert clock_calls == []
