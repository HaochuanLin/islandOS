from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from islandos_ui.customer_workflow import (
    HISTORY_CONTEXT_KEY,
    build_input_fingerprint,
    compare_history_context,
    compare_input_fingerprints,
    record_history_context,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_DIGEST = "a" * 64


def _fingerprint(**overrides):
    values = {
        "page": "decision_dashboard",
        "history_sha256": "sha-a",
        "site_digest": SITE_DIGEST,
        "units": {"pv_power": "kW", "wind_power": "kW"},
        "hour_count": 24,
        "currency": "USD",
        "page_settings": {"demand_scale": 1.0, "tariff_scale": 1.0},
    }
    values.update(overrides)
    return build_input_fingerprint(**values)


def _run_workflow_note(history_sha256: str) -> AppTest:
    source = f'''
import streamlit as st
st.session_state[{HISTORY_CONTEXT_KEY!r}] = {{
    "joint_optimizer": {{
        "history_sha256": "sha-a",
        "source_label": "synthetic",
    }}
}}
from islandos_ui.customer_workflow import render_customer_workflow
render_customer_workflow(
    active_page="decision_dashboard",
    history_sha256={history_sha256!r},
    source_label="shared CSV",
)
'''
    at = AppTest.from_string(source, default_timeout=15).run()
    assert not at.exception
    return at


def _run_workflow_note_with_fingerprint(
    previous: dict, current: dict
) -> AppTest:
    source = f'''
import streamlit as st
st.session_state[{HISTORY_CONTEXT_KEY!r}] = {{"joint_optimizer": {previous!r}}}
from islandos_ui.customer_workflow import render_customer_workflow
render_customer_workflow(
    active_page="decision_dashboard",
    history_sha256={current["history_sha256"]!r},
    source_label="shared CSV",
    fingerprint={current!r},
)
'''
    at = AppTest.from_string(source, default_timeout=15).run()
    assert not at.exception
    return at


def test_record_history_context_returns_the_other_page_and_keeps_both():
    state = {}
    assert record_history_context(
        state, page="joint_optimizer", history_sha256="sha-a", source_label="synthetic"
    ) is None

    previous = record_history_context(
        state, page="decision_dashboard", history_sha256="sha-a", source_label="shared CSV"
    )

    assert previous == {"history_sha256": "sha-a", "source_label": "synthetic"}
    assert state[HISTORY_CONTEXT_KEY]["joint_optimizer"]["history_sha256"] == "sha-a"
    assert state[HISTORY_CONTEXT_KEY]["decision_dashboard"]["source_label"] == "shared CSV"


def test_compare_history_context_matches_identical_hashes_and_rejects_others():
    assert compare_history_context(None, "sha-a") == "no_previous"
    assert compare_history_context({"history_sha256": "sha-a"}, "sha-a") == "match"
    assert compare_history_context({"history_sha256": "sha-a"}, "sha-b") == "mismatch"


def test_build_input_fingerprint_is_stable_and_order_independent():
    first = _fingerprint(
        units={"wind_power": "kW", "pv_power": "kW"},
        page_settings={"tariff_scale": 1.0, "demand_scale": 1.0},
    )
    second = _fingerprint(
        units={"pv_power": "kW", "wind_power": "kW"},
        page_settings={"demand_scale": 1.0, "tariff_scale": 1.0},
    )
    assert first["fingerprint_sha256"] == second["fingerprint_sha256"]
    assert first["page_settings_sha256"] == second["page_settings_sha256"]
    assert first["units"] == second["units"]


def test_shared_fingerprint_matches_across_pages_while_page_settings_stay_local():
    decision = _fingerprint(
        page="decision_dashboard", page_settings={"demand_scale": 1.0}
    )
    joint = _fingerprint(page="joint_optimizer", page_settings={})
    assert decision["fingerprint_sha256"] == joint["fingerprint_sha256"]
    assert decision["page_settings_sha256"] != joint["page_settings_sha256"]
    assert compare_input_fingerprints(joint, decision) == "match"


@pytest.mark.parametrize(
    "field,value",
    [
        ("history_sha256", "sha-b"),
        ("site_digest", "b" * 64),
        ("units", {"pv_power": "MW", "wind_power": "kW"}),
        ("hour_count", 25),
        ("currency", "EUR"),
    ],
)
def test_shared_fingerprint_changes_when_shared_input_changes(field, value):
    assert _fingerprint(**{field: value})["fingerprint_sha256"] != _fingerprint()[
        "fingerprint_sha256"
    ]


def test_compare_input_fingerprints_handles_missing_and_different_digests():
    first = _fingerprint()
    other = _fingerprint(history_sha256="sha-b")
    assert compare_input_fingerprints(None, first) == "no_previous"
    assert compare_input_fingerprints({}, first) == "no_previous"
    assert compare_input_fingerprints(first, {}) == "no_previous"
    assert compare_input_fingerprints(first, first) == "match"
    assert compare_input_fingerprints(first, other) == "mismatch"


def test_record_history_context_stores_optional_fingerprint_for_the_other_page():
    state = {}
    joint = _fingerprint(page="joint_optimizer", page_settings={})
    decision = _fingerprint(
        page="decision_dashboard", page_settings={"demand_scale": 1.0}
    )

    assert record_history_context(
        state,
        page="joint_optimizer",
        history_sha256="sha-a",
        source_label="synthetic",
        fingerprint=joint,
    ) is None

    previous = record_history_context(
        state,
        page="decision_dashboard",
        history_sha256="sha-a",
        source_label="shared CSV",
        fingerprint=decision,
    )

    assert previous["fingerprint"]["fingerprint_sha256"] == joint["fingerprint_sha256"]
    assert state[HISTORY_CONTEXT_KEY]["decision_dashboard"]["fingerprint"]["page"] == (
        "decision_dashboard"
    )
    assert compare_history_context(previous, "sha-a", fingerprint=decision) == "match"


def test_fingerprint_match_and_mismatch_notes_name_the_shared_fingerprint():
    previous = {
        "history_sha256": "sha-a",
        "source_label": "synthetic",
        "fingerprint": _fingerprint(page="joint_optimizer", page_settings={}),
    }
    matching = _run_workflow_note_with_fingerprint(
        previous,
        _fingerprint(page="decision_dashboard", page_settings={"demand_scale": 1.0}),
    )
    assert "same shared input fingerprint" in " ".join(
        item.value for item in matching.caption
    )
    assert "separate runs" in " ".join(item.value for item in matching.caption)

    mismatching = _run_workflow_note_with_fingerprint(
        previous,
        _fingerprint(
            page="decision_dashboard",
            site_digest="b" * 64,
            page_settings={"demand_scale": 1.0},
        ),
    )
    assert "Input fingerprint differs" in " ".join(
        item.value for item in mismatching.warning
    )
    assert "not like-for-like" in " ".join(item.value for item in mismatching.warning)


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"page": "workspace"}, "unknown customer page"),
        ({"site_digest": ""}, "site_digest"),
        ({"units": {}}, "units"),
        ({"hour_count": 0}, "hour_count"),
        ({"currency": " "}, "currency"),
        ({"page_settings": None}, "page_settings"),
        ({"page_settings": {"bad": float("nan")}}, "JSON-serializable"),
    ],
)
def test_build_input_fingerprint_rejects_invalid_inputs(overrides, message):
    with pytest.raises(ValueError, match=message):
        _fingerprint(**overrides)


def test_record_history_context_rejects_incomplete_fingerprint():
    with pytest.raises(ValueError, match="fingerprint_sha256"):
        record_history_context(
            {},
            page="joint_optimizer",
            history_sha256="sha-a",
            source_label="synthetic",
            fingerprint={"page": "joint_optimizer"},
        )
    with pytest.raises(ValueError, match="does not match"):
        record_history_context(
            {},
            page="decision_dashboard",
            history_sha256="sha-a",
            source_label="synthetic",
            fingerprint=_fingerprint(page="joint_optimizer"),
        )


def test_match_note_states_that_matching_input_does_not_merge_cost_results():
    at = _run_workflow_note("sha-a")
    captions = " ".join(item.value for item in at.caption)
    assert "Input match" in captions
    assert "separate runs" in captions
    assert "cost or saving totals as interchangeable" in captions


def test_mismatch_note_warns_that_outputs_are_not_like_for_like():
    at = _run_workflow_note("sha-b")
    warnings = " ".join(item.value for item in at.warning)
    assert "Input differs" in warnings
    assert "not like-for-like" in warnings


def test_page_upload_can_be_shared_into_the_existing_session_handoff():
    payload = b"timestamp_utc,pv_power_kw,wind_power_kw,essential_load_kw,electricity_price_per_kwh\n"
    source = f'''
import streamlit as st
from islandos_ui.customer_workflow import render_page_upload_handoff
render_page_upload_handoff(
    page_key="decision_dashboard",
    file_name="sample.csv",
    payload={payload!r},
)
'''
    at = AppTest.from_string(source, default_timeout=15).run()
    assert not at.exception
    assert "Share this CSV" in at.button[0].label

    at.button[0].click().run()
    assert not at.exception
    record = at.session_state["islandos_session_site_dataset"]
    assert record["file_name"] == "sample.csv"
    assert record["source_type"] == "customer_provided"
    assert record["payload"] == payload

    at.run()
    assert not at.exception
    assert "already shared" in " ".join(item.value for item in at.caption)




def test_record_history_context_rejects_unknown_page_and_empty_hash():
    with pytest.raises(ValueError, match="unknown customer page"):
        record_history_context({}, page="workspace", history_sha256="sha", source_label="x")
    with pytest.raises(ValueError, match="non-empty"):
        record_history_context(
            {}, page="joint_optimizer", history_sha256="", source_label="x"
        )


@pytest.mark.parametrize(
    "relative_path",
    [
        "pages/05_Customer_Decision_Dashboard.py",
        "pages/06_Forecast_Led_Joint_Resource_Optimizer.py",
    ],
)
def test_customer_pages_wire_the_shared_context_and_upload_handoff(relative_path: str):
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert "render_customer_workflow(" in source
    assert "history_sha256=history_sha256" in source
    assert "render_page_upload_handoff(" in source


def test_overview_orders_the_customer_journey_before_the_optional_device_check():
    source = (REPO_ROOT / "islandos_ui" / "workspace.py").read_text(encoding="utf-8")
    first = source.index("1 · Forecast and coordinate")
    second = source.index("2 · Compare policies and economics")
    third = source.index("3 · Optional device check")
    assert first < second < third
    assert "fixed synthetic site inputs" in source[third:third + 500]
