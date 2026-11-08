import pytest

from islandos_core.assets import AssetRecord
from islandos_core.electrical_topology import (
    AssetPortConnection,
    ElectricalBranch,
    ElectricalBus,
    ElectricalTopology,
    TopologyValidationError,
    validate_electrical_topology,
)


def bus(bus_id="bus-a", *, site="site-1", voltage=400, current="AC", basis="line_to_line", phases=3, confirmed=True):
    return ElectricalBus(bus_id, site, voltage, current, basis, phases, "approved single-line diagram rev A", confirmed)


def branch(branch_id="tie-1", left="bus-a", right="bus-b", *, confirmed=True, closed=True):
    return ElectricalBranch(branch_id, "site-1", left, right, "approved single-line diagram rev A", confirmed, closed)


def connection(asset_id, bus_id="bus-a", *, connection_id="port-1", confirmed=True, voltage=400):
    return AssetPortConnection(
        connection_id, "site-1", asset_id, "main", bus_id,
        "AC", voltage, "line_to_line", 3,
        "vendor interface drawing rev B", confirmed,
    )


def asset(asset_id="pv-1", site_id="site-1"):
    return AssetRecord(
        asset_id=asset_id, site_id=site_id, asset_type="generic",
        nameplate_parameters={}, installed_parameters={}, observed_parameters={},
        constraints=(),
    )


def test_valid_topology_is_structurally_ready():
    topology = ElectricalTopology(
        "site-1", (bus(), bus("bus-b")),
        (branch(),), (connection("pv-1"),),
    )
    result = validate_electrical_topology(topology, [asset()])
    assert result["is_structurally_ready"] is True
    assert result["normally_connected_component_count"] == 1
    assert result["scope"] == "structural_topology_validation_only"


def test_unconfirmed_bus_branch_or_port_blocks_readiness():
    topology = ElectricalTopology(
        "site-1", (bus(confirmed=False), bus("bus-b")),
        (branch(confirmed=False),), (connection("pv-1", confirmed=False),),
    )
    result = validate_electrical_topology(topology, [asset()])
    assert result["is_structurally_ready"] is False
    assert any(item.startswith("bus_not_confirmed") for item in result["blockers"])
    assert any(item.startswith("branch_not_confirmed") for item in result["blockers"])
    assert any(item.startswith("connection_not_confirmed") for item in result["blockers"])


def test_missing_bus_or_asset_blocks_connection():
    topology = ElectricalTopology("site-1", (bus(),), (), (connection("missing", "ghost"),))
    result = validate_electrical_topology(topology, [])
    assert "connection_asset_missing:port-1" in result["blockers"]
    assert "connection_bus_missing:port-1" in result["blockers"]


def test_cross_site_bus_is_rejected():
    topology = ElectricalTopology("site-1", (bus(site="site-2"),), (), ())
    result = validate_electrical_topology(topology, [])
    assert "bus_site_mismatch:bus-a" in result["blockers"]


def test_cross_site_asset_connection_is_rejected():
    topology = ElectricalTopology("site-1", (bus(),), (), (connection("pv-1"),))
    result = validate_electrical_topology(topology, [asset(site_id="site-2")])
    assert "connection_asset_site_mismatch:port-1" in result["blockers"]


def test_connection_voltage_or_phase_mismatch_blocks_readiness():
    topology = ElectricalTopology("site-1", (bus(),), (), (connection("pv-1", voltage=230),))
    result = validate_electrical_topology(topology, [asset()])
    assert "connection_interface_mismatch:port-1" in result["blockers"]


def test_branch_with_incompatible_bus_interfaces_is_blocked():
    topology = ElectricalTopology(
        "site-1", (bus(), bus("bus-b", voltage=230)),
        (branch(),), (),
    )
    result = validate_electrical_topology(topology, [])
    assert "branch_bus_interface_mismatch:tie-1" in result["blockers"]


def test_disconnected_components_are_reported_as_warning_not_silent_success():
    topology = ElectricalTopology("site-1", (bus(), bus("bus-b")), (), ())
    result = validate_electrical_topology(topology, [])
    assert result["is_structurally_ready"] is True
    assert result["normally_connected_component_count"] == 2
    assert "topology_has_2_normally_connected_components" in result["warnings"]


def test_duplicate_bus_ids_are_blocked():
    topology = ElectricalTopology("site-1", (bus(), bus()), (), ())
    result = validate_electrical_topology(topology, [])
    assert "duplicate_bus_ids" in result["blockers"]


def test_invalid_voltage_is_rejected_at_record_creation():
    with pytest.raises(TopologyValidationError):
        bus(voltage=0)


def test_normally_open_branch_does_not_join_components():
    topology = ElectricalTopology(
        "site-1", (bus(), bus("bus-b")),
        (branch(closed=False),), (),
    )
    result = validate_electrical_topology(topology, [])
    assert result["normally_connected_component_count"] == 2



def test_unavailable_connected_asset_blocks_topology_readiness():
    unavailable = AssetRecord(
        asset_id="pv-1", site_id="site-1", asset_type="generic",
        nameplate_parameters={}, installed_parameters={}, observed_parameters={},
        constraints=(), available=False,
    )
    topology = ElectricalTopology("site-1", (bus(),), (), (connection("pv-1"),))
    result = validate_electrical_topology(topology, [unavailable])
    assert "connection_asset_unavailable:port-1" in result["blockers"]
    assert result["is_structurally_ready"] is False


def test_duplicate_branch_and_connection_ids_are_blocked():
    topology = ElectricalTopology(
        "site-1",
        (bus(), bus("bus-b")),
        (branch("same", "bus-a", "bus-b"), branch("same", "bus-a", "bus-b")),
        (
            connection("pv-1", connection_id="same-port"),
            connection("pv-1", connection_id="same-port", bus_id="bus-b"),
        ),
    )
    result = validate_electrical_topology(topology, [asset()])
    assert "duplicate_branch_ids" in result["blockers"]
    assert "duplicate_connection_ids" in result["blockers"]
    assert "duplicate_asset_port_connections" in result["blockers"]
