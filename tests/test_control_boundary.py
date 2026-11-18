from islandos_core.control_boundary import build_human_review_envelope


def test_review_envelope_never_authorizes_or_generates_commands():
    envelope = build_human_review_envelope(
        {"action": "consider_run_on_surplus", "reason": "screening only"},
        site_id="site-001", asset_ids=("ro-01", "battery-01"),
        created_at_utc="2026-11-14T04:00:00Z",
        evidence_refs={"forecast": "sha256:abc"},
    )
    assert envelope["review_state"] == "pending_human_review"
    assert envelope["operational_authorization"] is False
    assert envelope["device_write_enabled"] is False
    assert envelope["command_generated"] is False
    assert envelope["control_command"] is None
    assert len(envelope["record_sha256"]) == 64


def test_review_envelope_rejects_duplicate_assets_and_naive_timestamp():
    import pytest

    with pytest.raises(ValueError, match="unique"):
        build_human_review_envelope(
            {"action": "hold"}, site_id="site-001",
            asset_ids=("asset-1", "asset-1"), created_at_utc="2026-11-14T04:00:00Z",
        )
    with pytest.raises(ValueError, match="timezone"):
        build_human_review_envelope(
            {"action": "hold"}, site_id="site-001",
            asset_ids=("asset-1",), created_at_utc="2026-11-14T04:00:00",
        )
