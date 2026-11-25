from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from islandos_core.run_identity import (
    CANONICAL_SIGNAL_NAMES,
    InputGroupIdentity,
    PAGE_SIGNAL_ALIASES,
    RunIdentityError,
    canonical_signal_name,
    canonicalize_history_signals,
    canonicalize_units,
    derive_input_group_id,
)


base_timestamps = [datetime(2026, 1, 1, hour, tzinfo=timezone.utc) for hour in range(3)]
base_signals = {
    "pv_power_kw": [0.0, 1.5, 4.25],
    "wind_power_kw": [2.0, 2.5, 3.0],
    "load_kw": [10.0, 12.5, 11.0],
    "tariff_per_kwh": [0.20, 0.25, 0.30],
}
base_units = {
    "pv_power_kw": "kW",
    "wind_power_kw": "kW",
    "load_kw": "kW",
    "tariff_per_kwh": "USD/kWh",
}
BASE_EXPECTED = InputGroupIdentity(
    input_group_id="ig-3a993a72953b9348",
    input_group_sha256="3a993a72953b9348e62f72919a129d4dcfc1cddd6fd68ed9c4a03ef401b49761",
    history_sha256="db13539cb15d68101bfdb28ad106c6fc2f36e249200f62c07056c7ebe0884d70",
    units_sha256="f9649c8dc9775e90525e1e7d2f97916619144fea84b40b42dd7e7467f3b7cc04",
    hour_count=3,
)


def test_fixed_input_group_vector_matches_latest_implementation():
    identity = derive_input_group_id(
        timestamps=base_timestamps,
        signals=base_signals,
        units=base_units,
    )

    assert identity == BASE_EXPECTED


def test_fixture_file_matches_the_implementation():
    fixture = json.loads(
        (Path(__file__).parents[1] / "docs" / "fixtures" / "j01_input_group_vectors.json")
        .read_text(encoding="utf-8")
    )
    base = fixture["cases"][0]
    identity = derive_input_group_id(
        timestamps=base_timestamps,
        signals=base_signals,
        units=base["units"],
    )

    assert identity.history_sha256 == base["expected_history_sha256"]
    assert identity.units_sha256 == base["expected_units_sha256"]
    assert identity.input_group_sha256 == base["expected_input_group_sha256"]
    assert identity.input_group_id == base["expected_input_group_id"]


def test_currency_codes_are_currency_neutral_for_the_same_physical_history():
    for currency in ("USD", "CNY", "GBP", "EUR"):
        identity = derive_input_group_id(
            timestamps=base_timestamps,
            signals=base_signals,
            units={**base_units, "tariff_per_kwh": f"{currency}/kWh"},
        )
        assert identity == BASE_EXPECTED

    identity = derive_input_group_id(
        timestamps=base_timestamps,
        signals=base_signals,
        units={**base_units, "tariff_per_kwh": "currency/kWh"},
    )
    assert identity == BASE_EXPECTED


def test_page_05_aliases_and_page_06_physical_names_share_one_identity():
    page_05_signals = {
        "pv_power": [0.0, 1.5, 4.25],
        "wind_power": [2.0, 2.5, 3.0],
        "essential_load": [10.0, 12.5, 11.0],
        "electricity_price": [0.20, 0.25, 0.30],
    }
    page_05_units = {
        "pv_power": "kW",
        "wind_power": "kW",
        "essential_load": "kW",
        "electricity_price": "USD/kWh",
    }

    page_05 = derive_input_group_id(
        timestamps=base_timestamps,
        signals=page_05_signals,
        units=page_05_units,
    )
    page_06 = derive_input_group_id(
        timestamps=base_timestamps,
        signals=base_signals,
        units=base_units,
    )

    assert page_05 == page_06 == BASE_EXPECTED
    assert canonicalize_history_signals(page_05_signals) == base_signals
    assert canonicalize_units(page_05_units) == {
        **base_units,
        "tariff_per_kwh": "currency/kWh",
    }


def test_physical_unit_change_creates_a_new_input_group():
    identity = derive_input_group_id(
        timestamps=base_timestamps,
        signals=base_signals,
        units={**base_units, "load_kw": "MW"},
    )

    assert identity.input_group_id == "ig-180f52a578a52b95"
    assert identity.input_group_sha256 == "180f52a578a52b954025f9d31a7fcd26cf25db243dba5461bfde006558d7334a"
    assert identity.history_sha256 == BASE_EXPECTED.history_sha256
    assert identity.input_group_id != BASE_EXPECTED.input_group_id


def test_row_order_does_not_change_the_input_group():
    reversed_timestamps = list(reversed(base_timestamps))
    reversed_signals = {
        name: list(reversed(values)) for name, values in base_signals.items()
    }

    identity = derive_input_group_id(
        timestamps=reversed_timestamps,
        signals=reversed_signals,
        units=base_units,
    )

    assert identity == BASE_EXPECTED


def test_equivalent_timezone_offsets_share_one_input_group():
    offset_timestamps = [
        datetime(2026, 1, 1, hour + 1, tzinfo=timezone(timedelta(hours=1)))
        for hour in range(3)
    ]

    identity = derive_input_group_id(
        timestamps=offset_timestamps,
        signals=base_signals,
        units=base_units,
    )

    assert identity == BASE_EXPECTED


def test_history_or_row_count_change_creates_a_new_input_group():
    changed = {
        **base_signals,
        "load_kw": [10.0, 12.5, 12.0],
    }
    changed_identity = derive_input_group_id(
        timestamps=base_timestamps,
        signals=changed,
        units=base_units,
    )

    longer_timestamps = [*base_timestamps, datetime(2026, 1, 1, 3, tzinfo=timezone.utc)]
    longer_signals = {name: [*values, values[-1]] for name, values in base_signals.items()}
    longer_identity = derive_input_group_id(
        timestamps=longer_timestamps,
        signals=longer_signals,
        units=base_units,
    )

    assert changed_identity.history_sha256 != BASE_EXPECTED.history_sha256
    assert changed_identity.input_group_id != BASE_EXPECTED.input_group_id
    assert longer_identity.hour_count == 4
    assert longer_identity.input_group_id != BASE_EXPECTED.input_group_id


def test_missing_extra_duplicate_and_unknown_names_fail_closed():
    with pytest.raises(RunIdentityError, match="exactly the four canonical signals"):
        derive_input_group_id(
            timestamps=base_timestamps,
            signals={name: base_signals[name] for name in CANONICAL_SIGNAL_NAMES[:3]},
            units=base_units,
        )

    with pytest.raises(RunIdentityError, match="unsupported signal name"):
        derive_input_group_id(
            timestamps=base_timestamps,
            signals={**base_signals, "unknown": [1.0, 2.0, 3.0]},
            units={**base_units, "unknown": "kW"},
        )

    with pytest.raises(RunIdentityError, match="duplicate signal"):
        derive_input_group_id(
            timestamps=base_timestamps,
            signals={
                **{name: base_signals[name] for name in CANONICAL_SIGNAL_NAMES[:3]},
                "pv_power": base_signals["pv_power_kw"],
                "pv_power_kw": base_signals["pv_power_kw"],
            },
            units=base_units,
        )

    with pytest.raises(RunIdentityError, match="unsupported signal name"):
        canonical_signal_name("dc_power")


def test_null_non_numeric_and_non_finite_values_are_refused():
    for bad_value in (None, "1.0", True, float("nan"), float("inf")):
        with pytest.raises(RunIdentityError, match="finite numbers"):
            derive_input_group_id(
                timestamps=base_timestamps,
                signals={**base_signals, "load_kw": [10.0, bad_value, 11.0]},
                units=base_units,
            )


def test_length_mismatch_and_empty_series_are_refused():
    with pytest.raises(RunIdentityError, match="share one length"):
        derive_input_group_id(
            timestamps=base_timestamps,
            signals={**base_signals, "load_kw": [10.0, 12.5]},
            units=base_units,
        )

    with pytest.raises(RunIdentityError, match="must not be empty"):
        derive_input_group_id(
            timestamps=base_timestamps,
            signals={**base_signals, "load_kw": []},
            units=base_units,
        )


def test_duplicate_or_naive_timestamps_are_refused():
    duplicate = [base_timestamps[0], base_timestamps[0], base_timestamps[1]]
    with pytest.raises(RunIdentityError, match="timestamps must be unique"):
        derive_input_group_id(
            timestamps=duplicate,
            signals=base_signals,
            units=base_units,
        )

    naive = [timestamp.replace(tzinfo=None) for timestamp in base_timestamps]
    with pytest.raises(RunIdentityError, match="timezone-aware"):
        derive_input_group_id(
            timestamps=naive,
            signals=base_signals,
            units=base_units,
        )


def test_alias_table_covers_both_page_05_and_page_06_names():
    assert set(PAGE_SIGNAL_ALIASES) == {
        "pv_power",
        "wind_power",
        "essential_load",
        "electricity_price",
    }
    assert set(PAGE_SIGNAL_ALIASES.values()) == set(CANONICAL_SIGNAL_NAMES)


def test_module_has_no_streamlit_environment_or_database_dependency():
    source = Path(__file__).parents[1] / "islandos_core" / "run_identity.py"
    text = source.read_text(encoding="utf-8")

    assert "import streamlit" not in text
    assert "sqlite3" not in text
    assert "os.environ" not in text
    assert "requests" not in text
