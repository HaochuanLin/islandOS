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
    RunIdentity,
    canonical_signal_name,
    canonicalize_history_signals,
    canonicalize_units,
    derive_input_group_id,
    derive_run_id,
    run_record_identity_fields,
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


RUN05_INPUTS = {
    "page": "customer_dashboard",
    "input_group": BASE_EXPECTED,
    "site_configuration_sha256": "2eb26336383cd110d964c1297654d4b61a011c125fa2a02e4e2d85e025ea4ab2",
    "page_settings": {"demand_scale": 1.0, "tariff_scale": 1.0, "cost_priority": 0.7},
    "page_inputs": {},
    "run_settings": {"currency": "USD"},
    "forecast_settings": {"horizon_hours": 24, "forecast_policy": "fixed"},
    "model_selection_policy": {"id": "forecast_policy_default", "version": "1"},
    "model_catalogue_version": "catalogue-v1",
    "optimizer": {"id": "customer_dashboard_policy_comparison", "version": "1"},
    "algorithm_versions": {"input_adapter": "1", "customer_workflow": "1"},
}

RUN06_INPUTS = {
    "page": "joint_resource_optimizer",
    "input_group": BASE_EXPECTED,
    "site_configuration_sha256": "4063d8d5acb192b871a7e11dbc406f8c68c9e2618906c16add2ac1e5ba328f6b",
    "page_settings": {},
    "page_inputs": {"window_end_utc": "2026-01-01T03:00:00Z"},
    "run_settings": {
        "currency": "USD",
        "availability": {"grid_all_hours": True, "diesel_all_hours": True},
    },
    "forecast_settings": {"horizon_hours": 168, "forecast_lead_hours": 24},
    "model_selection_policy": {"id": "per_signal_auto_select", "version": "1"},
    "model_catalogue_version": "catalogue-v1",
    "optimizer": {"id": "prediction_resource_dispatch", "version": "1"},
    "algorithm_versions": {"forecast_engine": "1", "dispatch_optimizer": "1"},
}


def test_run_identity_fixed_page_05_vector():
    identity = derive_run_id(**RUN05_INPUTS)

    assert isinstance(identity, RunIdentity)
    assert identity.run_id == "run-05-f099924addce15e4"
    assert identity.run_identity_sha256 == "f099924addce15e4bde6c2d7146cd397fecb169dc1bfd06fbc11bb2b02073896"
    assert identity.identity_schema_version == 1
    assert identity.page == "customer_dashboard"
    assert identity.input_group == BASE_EXPECTED


def test_run_identity_fixed_page_06_vector():
    identity = derive_run_id(**RUN06_INPUTS)

    assert identity.run_id == "run-06-906cce6af6da7a0f"
    assert identity.run_identity_sha256 == "906cce6af6da7a0f6061f11f27393fa6aa61f49e494bdf9a29abbf5e6e893a47"
    assert identity.identity_schema_version == 1
    assert identity.page == "joint_resource_optimizer"


def test_run_record_identity_fields_are_the_record_identity():
    identity = derive_run_id(**RUN05_INPUTS)

    assert run_record_identity_fields(identity) == {
        "run_id": "run-05-f099924addce15e4",
        "page": "customer_dashboard",
        "run_request_sha256": "f099924addce15e4bde6c2d7146cd397fecb169dc1bfd06fbc11bb2b02073896",
        "input_group_id": "ig-3a993a72953b9348",
    }

    without_group = derive_run_id(**{**RUN05_INPUTS, "input_group": None})
    assert run_record_identity_fields(without_group)["input_group_id"] is None


def test_run_record_identity_fields_reject_a_manually_corrupted_identity():
    corrupted = RunIdentity(
        run_id="run-05-1111111111111111",
        run_identity_sha256="0" * 64,
        identity_schema_version=1,
        page="customer_dashboard",
        input_group=BASE_EXPECTED,
    )

    with pytest.raises(RunIdentityError, match="run_id does not match"):
        run_record_identity_fields(corrupted)
    with pytest.raises(RunIdentityError, match="unsupported page"):
        run_record_identity_fields(
            RunIdentity(
                run_id="run-05-f099924addce15e4",
                run_identity_sha256="0" * 64,
                identity_schema_version=1,
                page="device_flexibility_planner",
                input_group=BASE_EXPECTED,
            )
        )
    with pytest.raises(RunIdentityError, match="schema version"):
        run_record_identity_fields(
            RunIdentity(
                run_id="run-05-f099924addce15e4",
                run_identity_sha256="0" * 64,
                identity_schema_version=2,
                page="customer_dashboard",
                input_group=BASE_EXPECTED,
            )
        )
    with pytest.raises(RunIdentityError, match="RunIdentity"):
        run_record_identity_fields({"run_id": "not-an-identity"})


def test_run_identity_is_deterministic_and_mapping_order_independent():
    first = derive_run_id(**RUN05_INPUTS)
    second = derive_run_id(
        **{
            **RUN05_INPUTS,
            "page_settings": dict(reversed(list(RUN05_INPUTS["page_settings"].items()))),
            "run_settings": {"currency": "USD"},
        }
    )

    assert first == second


def test_technical_settings_change_run_id_but_not_input_group():
    baseline = derive_run_id(**RUN05_INPUTS)
    changed = derive_run_id(
        **{
            **RUN05_INPUTS,
            "page_settings": {**RUN05_INPUTS["page_settings"], "demand_scale": 1.2},
        }
    )

    assert changed.run_id == "run-05-1efacbd210e4c652"
    assert changed.input_group == baseline.input_group


def test_model_policy_and_catalogue_versions_are_part_of_run_identity():
    baseline = derive_run_id(**RUN06_INPUTS)
    changed_policy = derive_run_id(
        **{
            **RUN06_INPUTS,
            "model_selection_policy": {"id": "per_signal_auto_select", "version": "2"},
        }
    )
    changed_catalogue = derive_run_id(
        **{**RUN06_INPUTS, "model_catalogue_version": "catalogue-v2"}
    )

    assert changed_policy.run_id != baseline.run_id
    assert changed_catalogue.run_id == "run-06-2c3e86dbb13ec2e7"


def test_currency_is_run_setting_not_input_group_identity():
    baseline = derive_run_id(**RUN05_INPUTS)
    changed = derive_run_id(
        **{
            **RUN05_INPUTS,
            "run_settings": {"currency": "CNY"},
        }
    )

    assert changed.run_id != baseline.run_id
    assert changed.input_group == baseline.input_group


def test_missing_input_group_is_supported_without_fabricating_a_group():
    identity = derive_run_id(**{**RUN05_INPUTS, "input_group": None})

    assert identity.input_group is None
    assert identity.run_id.startswith("run-05-")


def test_page_09_is_not_supported_by_the_persistent_run_identity_function():
    with pytest.raises(RunIdentityError, match="unsupported page"):
        derive_run_id(**{**RUN05_INPUTS, "page": "device_flexibility_planner"})


def test_actual_selected_model_ids_are_not_an_identity_input():
    with pytest.raises(TypeError):
        derive_run_id(**{**RUN05_INPUTS, "model_ids": {"load_kw": "ridge"}})


def test_run_identity_rejects_invalid_site_digest_and_missing_currency():
    with pytest.raises(RunIdentityError, match="site_configuration_sha256"):
        derive_run_id(**{**RUN05_INPUTS, "site_configuration_sha256": "not-a-digest"})
    with pytest.raises(RunIdentityError, match="run_settings.currency"):
        derive_run_id(**{**RUN05_INPUTS, "run_settings": {}})


def test_run_identity_rejects_non_json_safe_values():
    from datetime import datetime, timezone

    with pytest.raises(RunIdentityError, match="JSON-safe"):
        derive_run_id(
            **{
                **RUN05_INPUTS,
                "page_inputs": {"created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
            }
        )
    with pytest.raises(RunIdentityError, match="finite JSON numbers"):
        derive_run_id(**{**RUN05_INPUTS, "page_settings": {"weight": float("nan")}})


def test_run_identity_rejects_malformed_input_group_objects():
    malformed = InputGroupIdentity(
        input_group_id="ig-wrong",
        input_group_sha256=BASE_EXPECTED.input_group_sha256,
        history_sha256=BASE_EXPECTED.history_sha256,
        units_sha256=BASE_EXPECTED.units_sha256,
        hour_count=3,
    )
    with pytest.raises(RunIdentityError, match="does not match"):
        derive_run_id(**{**RUN05_INPUTS, "input_group": malformed})


def test_run_identity_output_is_immutable():
    identity = derive_run_id(**RUN05_INPUTS)
    with pytest.raises(Exception):
        identity.run_id = "run-05-mutated"


def test_run_identity_schema_is_versioned_and_page_scoped():
    identity_05 = derive_run_id(**RUN05_INPUTS)
    identity_06 = derive_run_id(**RUN06_INPUTS)

    assert identity_05.run_id.startswith("run-05-")
    assert identity_06.run_id.startswith("run-06-")
    assert identity_05.run_id != identity_06.run_id


def test_run_identity_fixture_matches_implemented_contract():
    fixture_path = Path(__file__).parents[1] / "docs" / "fixtures" / "j01_run_identity_p1b_vectors.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    for case in fixture["cases"]:
        identity = derive_run_id(
            **case["inputs"],
            input_group=BASE_EXPECTED,
        )
        assert identity.run_id == case["expected_run_id"]
        assert identity.run_identity_sha256 == case["expected_run_identity_sha256"]


@pytest.mark.parametrize(
    "override",
    [
        {"site_configuration_sha256": "9" * 64},
        {"page_inputs": {"window_end_utc": "2026-01-02T03:00:00Z"}},
        {"forecast_settings": {"horizon_hours": 48, "forecast_policy": "fixed"}},
        {"optimizer": {"id": "prediction_resource_dispatch", "version": "2"}},
        {"algorithm_versions": {"forecast_engine": "2", "dispatch_optimizer": "1"}},
    ],
)
def test_each_technical_identity_dimension_changes_run_id(override):
    baseline = derive_run_id(**RUN06_INPUTS)
    changed = derive_run_id(**{**RUN06_INPUTS, **override})

    assert changed.run_id != baseline.run_id
    assert changed.input_group == baseline.input_group


def test_input_group_change_changes_run_id():
    changed_group = derive_input_group_id(
        timestamps=base_timestamps,
        signals=base_signals,
        units={**base_units, "load_kw": "MW"},
    )
    changed = derive_run_id(**{**RUN05_INPUTS, "input_group": changed_group})
    baseline = derive_run_id(**RUN05_INPUTS)

    assert changed.run_id != baseline.run_id
    assert changed.input_group == changed_group


def test_investment_assumptions_are_not_accepted_as_run_identity_inputs():
    with pytest.raises(TypeError):
        derive_run_id(**{**RUN05_INPUTS, "investment_assumptions": {"upfront_capex": 1000}})


def test_investment_only_assumptions_are_rejected_from_technical_identity():
    with pytest.raises(RunIdentityError, match="investment-only"):
        derive_run_id(
            **{
                **RUN05_INPUTS,
                "run_settings": {
                    "currency": "USD",
                    "investment": {
                        "upfront_capex": 1000,
                        "project_life_years": 15,
                    },
                },
            }
        )
    with pytest.raises(RunIdentityError, match="investment-only"):
        derive_run_id(
            **{
                **RUN05_INPUTS,
                "page_inputs": {"discount_rate": 0.08},
            }
        )
