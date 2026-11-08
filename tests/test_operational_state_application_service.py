from datetime import datetime, timezone

from islandos_core.application import evaluate_site_operational_readiness
from islandos_core.assets import AssetRecord
from islandos_core.operational_state import AssetOperationalState


def test_application_service_exposes_operational_readiness_gate():
    now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
    asset = AssetRecord(
        asset_id="battery-1", site_id="site-1", asset_type="generic",
        nameplate_parameters={}, installed_parameters={}, observed_parameters={},
        constraints=(),
    )
    observation = AssetOperationalState(
        "battery-1", "site-1", "online", now,
        "operator verified status log", True,
    )
    result = evaluate_site_operational_readiness([asset], [observation], as_of=now)
    assert result["can_dispatch_screen"] is True
    assert result["scope"] == "read_only_operational_state_readiness"
