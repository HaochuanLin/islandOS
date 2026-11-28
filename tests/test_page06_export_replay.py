"""Page06's real audit export must replay to the same canonical run.

The page is exercised through AppTest, its download handler is captured, and the
exported request is fed to the actual replay function and manifest builder. The
test deliberately does not rebuild the request by hand: a reconstructed request
would prove only that the reconstructor agrees with itself.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from islandos_core.demo_site_history import build_synthetic_site_history
from islandos_core.run_orchestration import (
    build_joint_optimizer_manifest,
    replay_run_request,
)
from islandos_core.session_dataset import store_session_dataset

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "pages" / "06_Forecast_Led_Joint_Resource_Optimizer.py"
AUDIT_LABEL = "Download joint schedule audit (JSON)"
UPLOAD_NAME = "page06-export-replay.csv"


def _uploaded_payload() -> bytes:
    """A real uploaded-data scenario with enough contiguous hourly rows."""
    history = build_synthetic_site_history(
        datetime(2026, 11, 22, 14, tzinfo=timezone.utc),
        pv_rated_kw=40.0,
        wind_rated_kw=20.0,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "timestamp_utc",
        "pv_power_kw",
        "wind_power_kw",
        "essential_load_kw",
        "electricity_price_per_kwh",
    ])
    for index in range(-72, 0):
        writer.writerow([
            history.timestamps[index].isoformat().replace("+00:00", "Z"),
            history.pv_power_kw[index],
            history.wind_power_kw[index],
            history.load_kw[index],
            history.tariff_per_kwh[index],
        ])
    return buffer.getvalue().encode("utf-8")


def _run_page_and_capture(*, uploaded: bool) -> dict:
    captured: dict[str, bytes] = {}
    original = st.download_button

    def recorder(label, data=None, *args, **kwargs):
        if data is not None and AUDIT_LABEL in str(label):
            captured["report"] = bytes(data) if not isinstance(data, bytes) else data
        return original(label, data=data, *args, **kwargs)

    st.download_button = recorder
    try:
        app = AppTest.from_file(str(PAGE), default_timeout=180)
        if uploaded:
            payload = _uploaded_payload()
            store_session_dataset(
                app.session_state,
                file_name=UPLOAD_NAME,
                payload=payload,
                source_type="customer_provided",
            )
        app.run()
        assert not app.exception, "\n".join(str(error) for error in app.exception)
    finally:
        st.download_button = original

    assert "report" in captured, "Page06 did not emit its audit download"
    return json.loads(captured["report"])


def _request_sha256(request: dict) -> str:
    payload = {key: value for key, value in request.items() if key != "request_sha256"}
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_export_replays(report: dict) -> None:
    request = report["application_views"]["request"]
    canonical = report["canonical_run"]
    exported_result = report["application_views"]["result"]

    assert request["page"] == "joint_resource_optimizer"
    assert request["history"]["hour_count"] == len(request["history"]["timestamps_utc"])
    assert request["request_sha256"] == _request_sha256(request)

    replay_result = replay_run_request(request)["result"]
    builder_manifest = build_joint_optimizer_manifest(request).to_dict()

    assert canonical["run_id"] == builder_manifest["run_id"] == replay_result["run_id"]
    assert (
        canonical["manifest_sha256"]
        == builder_manifest["manifest_sha256"]
        == replay_result["manifest_sha256"]
    )
    assert canonical["manifest"]["manifest_sha256"] == canonical["manifest_sha256"]
    assert canonical["manifest"]["created_at_utc"] == builder_manifest["created_at_utc"]

    last_stamp = datetime.fromisoformat(
        request["history"]["timestamps_utc"][-1].replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    assert canonical["manifest"]["created_at_utc"] == last_stamp.isoformat().replace(
        "+00:00", "Z"
    )

    # The replay result is the same summary object the page exported, including
    # its own digest, not merely a run id that happens to match.
    assert exported_result == replay_result
    assert exported_result["summary_sha256"] == replay_result["summary_sha256"]
    assert exported_result["evidence_sha256"] == canonical["evidence_sha256"]


def test_page06_synthetic_export_replays_to_the_same_canonical_run():
    report = _run_page_and_capture(uploaded=False)
    assert report["source_file_sha256"] is None
    _assert_export_replays(report)


def test_page06_uploaded_export_replays_to_the_same_canonical_run():
    report = _run_page_and_capture(uploaded=True)
    assert report["source_file_sha256"]
    assert UPLOAD_NAME in report["input_provenance"]
    _assert_export_replays(report)
