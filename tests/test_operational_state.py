from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.assets import AssetRecord
from islandos_core.electrical_topology import AssetPortConnection, ElectricalBus, ElectricalTopology
from islandos_core.operational_state import (
    AssetOperationalState,
    OperationalStateError,
    evaluate_operational_readiness,
)


NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def asset(asset_id="pv-1", *, site="site-1", available=True):
    return AssetRecord(
        asset_id=asset_id, site_id=site, asset_type="generic",
        nameplate_parameters={}, installed_parameters={}, observed_parameters={},
        constraints=(), available=available,
    )


def observation(asset_id="pv-1", *, state="online", at=NOW, confirmed=True, site="site-1"):
    return AssetOperationalState(asset_id, site, state, at, "SCADA export row 42", confirmed)


def topology_for(asset_id="pv-1"):
    bus = ElectricalBus(
        "main", "site-1", 400, "AC", "line_to_line", 3,
        "approved SLD rev C", True,
    )
    port = AssetPortConnection(
        "port-1", "site-1", asset_id, "main", "main", "AC",
        400, "line_to_line", 3, "vendor drawing rev C", True,
    )
    return ElectricalTopology("site-1", (bus,), (), (port,))


def test_fresh_confirmed_online_state_is_dispatch_screen_ready():
    result = evaluate_operational_readiness([asset()], [observation()], as_of=NOW)
    assert result["can_dispatch_screen"] is True
    assert result["status"] == "operationally_ready"


@pytest.mark.parametrize("state", ["offline", "maintenance", "fault", "unknown"])
def test_non_online_states_block_dispatch_screen(state):
    result = evaluate_operational_readiness(
        [asset()], [observation(state=state)], as_of=NOW,
    )
    assert result["can_dispatch_screen"] is False


def test_missing_state_blocks_readiness():
    result = evaluate_operational_readiness([asset()], [], as_of=NOW)
    assert "operational_state_missing:pv-1" in result["blockers"]


def test_stale_state_blocks_readiness():
    result = evaluate_operational_readiness(
        [asset()], [observation(at=NOW - timedelta(minutes=16))], as_of=NOW,
    )
    assert "operational_state_stale:pv-1" in result["blockers"]


def test_unconfirmed_state_blocks_readiness():
    result = evaluate_operational_readiness(
        [asset()], [observation(confirmed=False)], as_of=NOW,
    )
    assert "operational_state_unconfirmed:pv-1" in result["blockers"]


def test_future_state_timestamp_blocks_readiness():
    result = evaluate_operational_readiness(
        [asset()], [observation(at=NOW + timedelta(seconds=1))], as_of=NOW,
    )
    assert "operational_state_from_future:pv-1" in result["blockers"]


def test_unavailable_asset_blocks_even_with_online_observation():
    result = evaluate_operational_readiness(
        [asset(available=False)], [observation()], as_of=NOW,
    )
    assert "asset_unavailable:pv-1" in result["blockers"]


def test_duplicate_and_unknown_asset_observations_are_reported():
    result = evaluate_operational_readiness(
        [asset()],
        [observation(), observation(at=NOW - timedelta(seconds=1)), observation("ghost")],
        as_of=NOW,
    )
    assert "duplicate_operational_state:pv-1" in result["blockers"]
    assert "operational_state_asset_missing:ghost" in result["blockers"]


def test_site_mismatch_blocks_readiness():
    result = evaluate_operational_readiness(
        [asset()], [observation(site="site-2")], as_of=NOW,
    )
    assert "operational_state_site_mismatch:pv-1" in result["blockers"]


def test_topology_limits_evaluation_to_connected_assets():
    result = evaluate_operational_readiness(
        [asset(), asset("unused")], [observation()], as_of=NOW,
        topology=topology_for(),
    )
    assert result["evaluated_asset_count"] == 1
    assert result["can_dispatch_screen"] is True


def test_naive_timestamps_are_rejected():
    with pytest.raises(OperationalStateError):
        observation(at=datetime(2026, 11, 8, 12, 0))
