from islandos_core.application import validate_site_electrical_topology
from islandos_core.assets import AssetRecord
from islandos_core.electrical_topology import (
    AssetPortConnection, ElectricalBus, ElectricalTopology,
)


def test_application_boundary_exposes_structural_topology_validation():
    asset = AssetRecord(
        asset_id="load-1", site_id="site-1", asset_type="generic",
        nameplate_parameters={}, installed_parameters={}, observed_parameters={},
        constraints=(),
    )
    bus = ElectricalBus(
        bus_id="main", site_id="site-1", nominal_voltage_v=400,
        current_type="AC", voltage_basis="line_to_line", phases=3,
        source_reference="single-line diagram rev 2", confirmed=True,
    )
    port = AssetPortConnection(
        connection_id="load-1-main", site_id="site-1", asset_id="load-1",
        port_id="main", bus_id="main", current_type="AC",
        nominal_voltage_v=400, voltage_basis="line_to_line", phases=3,
        source_reference="equipment connection schedule rev 2", confirmed=True,
    )
    topology = ElectricalTopology("site-1", (bus,), (), (port,))
    result = validate_site_electrical_topology(topology, [asset])
    assert result["is_structurally_ready"] is True
    assert result["scope"] == "structural_topology_validation_only"
    assert result["limitations"]
