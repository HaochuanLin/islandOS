"""The default window must be a function of its anchor, not of the host clock."""

import ast
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from islandos_core.demo_site_history import (
    SYNTHETIC_HISTORY_HOURS,
    build_customer_site_history,
    build_synthetic_site_history,
    canonical_history_sha256,
    demo_anchor_for_hour,
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


def test_the_default_demo_hour_reproduces_the_unpinned_window():
    now = datetime(2026, 11, 22, 5, 37, tzinfo=timezone.utc)
    # The pages truncate `now` before building, so passing its own hour must change
    # nothing: the control is a dial whose default is still the live clock.
    assert demo_anchor_for_hour(now, now.hour) == now.replace(
        minute=0, second=0, microsecond=0
    )


def test_a_pinned_hour_is_applied_to_todays_date_without_reading_the_clock():
    now = datetime(2026, 11, 22, 5, 37, tzinfo=timezone.utc)
    assert demo_anchor_for_hour(now, 14) == datetime(2026, 11, 22, 14, tzinfo=timezone.utc)
    # A dial may point at an hour that has not happened today; that is the point of
    # reproducing a recorded 14:00 window at 05:00.
    assert demo_anchor_for_hour(now, 2) == datetime(2026, 11, 22, 2, tzinfo=timezone.utc)


def test_a_pinned_date_is_used_verbatim():
    now = datetime(2026, 11, 23, 5, 37, tzinfo=timezone.utc)
    assert demo_anchor_for_hour(now, 14, demo_date=date(2026, 11, 15)) == datetime(
        2026, 11, 15, 14, tzinfo=timezone.utc
    )


@pytest.mark.parametrize("hour", [-1, 24, True, 14.5, "14"])
def test_an_out_of_range_demo_hour_is_refused(hour):
    with pytest.raises(ValueError, match="0 to 23"):
        demo_anchor_for_hour(datetime(2026, 11, 22, 5, tzinfo=timezone.utc), hour)


def test_a_datetime_is_refused_where_a_date_is_expected():
    with pytest.raises(ValueError, match="not a datetime"):
        demo_anchor_for_hour(
            datetime(2026, 11, 22, 5, tzinfo=timezone.utc),
            14,
            demo_date=datetime(2026, 11, 22, 5, tzinfo=timezone.utc),
        )


def test_the_demo_anchor_requires_an_aware_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        demo_anchor_for_hour(datetime(2026, 11, 22, 5), 14)


def test_customer_wrapper_is_the_joint_default_at_nominal_site():
    anchor = datetime(2026, 11, 22, 14, tzinfo=timezone.utc)
    joint = build_synthetic_site_history(anchor, **SITE)
    customer = build_customer_site_history(anchor, demand_scale=1.0, tariff_scale=1.0)
    assert customer == joint
    assert canonical_history_sha256(
        timestamps=customer.timestamps,
        pv_power_kw=customer.pv_power_kw,
        wind_power_kw=customer.wind_power_kw,
        load_kw=customer.load_kw,
        tariff_per_kwh=customer.tariff_per_kwh,
    ) == canonical_history_sha256(
        timestamps=joint.timestamps,
        pv_power_kw=joint.pv_power_kw,
        wind_power_kw=joint.wind_power_kw,
        load_kw=joint.load_kw,
        tariff_per_kwh=joint.tariff_per_kwh,
    )


def test_customer_scales_change_load_and_price_but_not_renewables():
    anchor = datetime(2026, 11, 22, 14, tzinfo=timezone.utc)
    base = build_synthetic_site_history(anchor, **SITE)
    scaled = build_customer_site_history(
        anchor, demand_scale=1.5, tariff_scale=1.2
    )
    assert scaled.pv_power_kw == base.pv_power_kw
    assert scaled.wind_power_kw == base.wind_power_kw
    assert scaled.load_kw[0] == pytest.approx(base.load_kw[0] * 1.5)
    assert scaled.tariff_per_kwh[0] == pytest.approx(base.tariff_per_kwh[0] * 1.2)


@pytest.mark.parametrize("field,value", [("demand_scale", -1.0), ("tariff_scale", -1.0)])
def test_customer_scales_refuse_negative_values(field, value):
    with pytest.raises(ValueError, match="non-negative"):
        build_customer_site_history(
            datetime(2026, 11, 22, 14, tzinfo=timezone.utc),
            **{field: value},
        )


def test_canonical_history_hash_ignores_sub_micro_floating_jitter():
    history = _history(14)
    base = canonical_history_sha256(
        timestamps=history.timestamps,
        pv_power_kw=history.pv_power_kw,
        wind_power_kw=history.wind_power_kw,
        load_kw=history.load_kw,
        tariff_per_kwh=history.tariff_per_kwh,
    )
    jittered = canonical_history_sha256(
        timestamps=history.timestamps,
        pv_power_kw=tuple(value + 1e-9 for value in history.pv_power_kw),
        wind_power_kw=tuple(value - 1e-9 for value in history.wind_power_kw),
        load_kw=tuple(value + 1e-9 for value in history.load_kw),
        tariff_per_kwh=tuple(value - 1e-9 for value in history.tariff_per_kwh),
    )
    assert jittered == base


def test_canonical_history_hash_separates_values_on_the_sixth_decimal():
    stamp = datetime(2026, 11, 22, 14, tzinfo=timezone.utc)
    common = dict(
        timestamps=(stamp,),
        wind_power_kw=(1.0,),
        load_kw=(1.0,),
        tariff_per_kwh=(1.0,),
    )
    assert canonical_history_sha256(pv_power_kw=(1.0,), **common) != canonical_history_sha256(
        pv_power_kw=(1.000001,), **common
    )


def test_canonical_history_hash_normalises_negative_zero():
    stamp = datetime(2026, 11, 22, 14, tzinfo=timezone.utc)
    common = dict(
        timestamps=(stamp,),
        pv_power_kw=(0.0,),
        wind_power_kw=(0.0,),
        load_kw=(0.0,),
        tariff_per_kwh=(0.0,),
    )
    assert canonical_history_sha256(**common) == canonical_history_sha256(
        **{**common, "pv_power_kw": (-0.0,)}
    )


def test_canonical_history_hash_refuses_mismatched_lengths():
    history = _history(14)
    with pytest.raises(ValueError, match="same length"):
        canonical_history_sha256(
            timestamps=history.timestamps,
            pv_power_kw=history.pv_power_kw[:-1],
            wind_power_kw=history.wind_power_kw,
            load_kw=history.load_kw,
            tariff_per_kwh=history.tariff_per_kwh,
        )


def test_default_history_hash_is_pinned():
    anchor = datetime(2026, 11, 22, 14, tzinfo=timezone.utc)
    history = build_customer_site_history(anchor)
    assert canonical_history_sha256(
        timestamps=history.timestamps,
        pv_power_kw=history.pv_power_kw,
        wind_power_kw=history.wind_power_kw,
        load_kw=history.load_kw,
        tariff_per_kwh=history.tariff_per_kwh,
    ) == "7012014ef720e5802d1ff9147fe439b93d52736f47c538170da46d55b6d2ed70"

