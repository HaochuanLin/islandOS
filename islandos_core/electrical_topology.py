"""Structural electrical-topology records for offline IslandOS site modeling.

Validates declared bus/branch/asset-port relationships only. It does not
perform load flow, short-circuit, protection, grounding, arc-flash, or safety
analysis, and it never authorizes equipment operation.
"""
from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass
import math
from typing import Sequence

class TopologyValidationError(ValueError):
    """Raised when an electrical topology declaration is malformed."""

def _positive_finite(value: float, label: str) -> float:
    if isinstance(value, bool):
        raise TopologyValidationError(f"{label} must be a positive finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TopologyValidationError(f"{label} must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0:
        raise TopologyValidationError(f"{label} must be a positive finite number")
    return number

def _required_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TopologyValidationError(f"{label} is required")

@dataclass(frozen=True)
class ElectricalBus:
    bus_id: str
    site_id: str
    nominal_voltage_v: float
    current_type: str
    voltage_basis: str
    phases: int | None
    source_reference: str
    confirmed: bool = False

    def __post_init__(self) -> None:
        for key in ("bus_id", "site_id", "source_reference"):
            _required_text(getattr(self, key), key)
        object.__setattr__(self, "nominal_voltage_v", _positive_finite(self.nominal_voltage_v, "nominal_voltage_v"))
        if self.current_type not in {"AC", "DC"}:
            raise TopologyValidationError("current_type must be AC or DC")
        if self.current_type == "AC":
            if self.voltage_basis not in {"line_to_line", "line_to_neutral"}:
                raise TopologyValidationError("AC voltage_basis must be line_to_line or line_to_neutral")
            if self.phases not in {1, 2, 3}:
                raise TopologyValidationError("AC phases must be 1, 2, or 3")
        elif self.voltage_basis != "dc" or self.phases is not None:
            raise TopologyValidationError("DC bus requires voltage_basis='dc' and phases=None")
        if not isinstance(self.confirmed, bool):
            raise TopologyValidationError("confirmed must be boolean")

@dataclass(frozen=True)
class ElectricalBranch:
    branch_id: str
    site_id: str
    from_bus_id: str
    to_bus_id: str
    source_reference: str
    confirmed: bool = False
    normally_closed: bool = True

    def __post_init__(self) -> None:
        for key in ("branch_id", "site_id", "from_bus_id", "to_bus_id", "source_reference"):
            _required_text(getattr(self, key), key)
        if self.from_bus_id == self.to_bus_id:
            raise TopologyValidationError("branch endpoints must be different buses")
        if not isinstance(self.confirmed, bool) or not isinstance(self.normally_closed, bool):
            raise TopologyValidationError("branch confirmed/normally_closed must be boolean")

@dataclass(frozen=True)
class AssetPortConnection:
    connection_id: str
    site_id: str
    asset_id: str
    port_id: str
    bus_id: str
    current_type: str
    nominal_voltage_v: float
    voltage_basis: str
    phases: int | None
    source_reference: str
    confirmed: bool = False

    def __post_init__(self) -> None:
        for key in ("connection_id", "site_id", "asset_id", "port_id", "bus_id", "source_reference"):
            _required_text(getattr(self, key), key)
        object.__setattr__(self, "nominal_voltage_v", _positive_finite(self.nominal_voltage_v, "nominal_voltage_v"))
        if self.current_type not in {"AC", "DC"}:
            raise TopologyValidationError("connection current_type must be AC or DC")
        if self.current_type == "AC":
            if self.voltage_basis not in {"line_to_line", "line_to_neutral"} or self.phases not in {1, 2, 3}:
                raise TopologyValidationError("invalid AC connection interface")
        elif self.voltage_basis != "dc" or self.phases is not None:
            raise TopologyValidationError("DC connection requires voltage_basis='dc' and phases=None")
        if not isinstance(self.confirmed, bool):
            raise TopologyValidationError("confirmed must be boolean")

@dataclass(frozen=True)
class ElectricalTopology:
    site_id: str
    buses: tuple[ElectricalBus, ...]
    branches: tuple[ElectricalBranch, ...]
    asset_connections: tuple[AssetPortConnection, ...]

    def __post_init__(self) -> None:
        _required_text(self.site_id, "site_id")
        for label, values, expected in (
            ("buses", self.buses, ElectricalBus),
            ("branches", self.branches, ElectricalBranch),
            ("asset_connections", self.asset_connections, AssetPortConnection),
        ):
            if not isinstance(values, tuple) or any(not isinstance(item, expected) for item in values):
                raise TopologyValidationError(f"{label} must be a tuple of {expected.__name__}")

def validate_electrical_topology(topology: ElectricalTopology, assets: Sequence[object]) -> dict:
    """Validate structure only; never infer port data or claim electrical safety."""
    from islandos_core.assets import AssetRecord
    if not isinstance(topology, ElectricalTopology):
        raise TopologyValidationError("topology must be an ElectricalTopology")
    if not isinstance(assets, Sequence) or isinstance(assets, (str, bytes)):
        raise TopologyValidationError("assets must be a sequence of AssetRecord")
    if any(not isinstance(asset, AssetRecord) for asset in assets):
        raise TopologyValidationError("every asset must be an AssetRecord")
    blockers: list[str] = []
    warnings: list[str] = []
    if not topology.buses:
        blockers.append("at_least_one_bus_required")
    asset_by_id = {asset.asset_id: asset for asset in assets}
    if len(asset_by_id) != len(assets):
        blockers.append("duplicate_asset_ids")
    bus_by_id = {bus.bus_id: bus for bus in topology.buses}
    if len(bus_by_id) != len(topology.buses):
        blockers.append("duplicate_bus_ids")
    branch_ids = [item.branch_id for item in topology.branches]
    if len(branch_ids) != len(set(branch_ids)):
        blockers.append("duplicate_branch_ids")
    connection_ids = [item.connection_id for item in topology.asset_connections]
    if len(connection_ids) != len(set(connection_ids)):
        blockers.append("duplicate_connection_ids")
    port_keys = [(item.asset_id, item.port_id) for item in topology.asset_connections]
    if len(port_keys) != len(set(port_keys)):
        blockers.append("duplicate_asset_port_connections")
    for bus in topology.buses:
        if bus.site_id != topology.site_id:
            blockers.append(f"bus_site_mismatch:{bus.bus_id}")
        if not bus.confirmed:
            blockers.append(f"bus_not_confirmed:{bus.bus_id}")
    adjacency: dict[str, set[str]] = defaultdict(set)
    for branch in topology.branches:
        if branch.site_id != topology.site_id:
            blockers.append(f"branch_site_mismatch:{branch.branch_id}")
        left, right = bus_by_id.get(branch.from_bus_id), bus_by_id.get(branch.to_bus_id)
        if left is None or right is None:
            blockers.append(f"branch_bus_missing:{branch.branch_id}")
            continue
        left_interface = (left.current_type, left.nominal_voltage_v, left.voltage_basis, left.phases)
        right_interface = (right.current_type, right.nominal_voltage_v, right.voltage_basis, right.phases)
        if left_interface != right_interface:
            blockers.append(f"branch_bus_interface_mismatch:{branch.branch_id}")
        if not branch.confirmed:
            blockers.append(f"branch_not_confirmed:{branch.branch_id}")
        if branch.normally_closed:
            adjacency[left.bus_id].add(right.bus_id)
            adjacency[right.bus_id].add(left.bus_id)
    for connection in topology.asset_connections:
        if connection.site_id != topology.site_id:
            blockers.append(f"connection_site_mismatch:{connection.connection_id}")
        asset = asset_by_id.get(connection.asset_id)
        bus = bus_by_id.get(connection.bus_id)
        if asset is None:
            blockers.append(f"connection_asset_missing:{connection.connection_id}")
        else:
            if asset.site_id != topology.site_id:
                blockers.append(f"connection_asset_site_mismatch:{connection.connection_id}")
            if not asset.available:
                blockers.append(f"connection_asset_unavailable:{connection.connection_id}")
        if bus is None:
            blockers.append(f"connection_bus_missing:{connection.connection_id}")
        else:
            actual = (connection.current_type, connection.nominal_voltage_v, connection.voltage_basis, connection.phases)
            expected = (bus.current_type, bus.nominal_voltage_v, bus.voltage_basis, bus.phases)
            if actual != expected:
                blockers.append(f"connection_interface_mismatch:{connection.connection_id}")
        if not connection.confirmed:
            blockers.append(f"connection_not_confirmed:{connection.connection_id}")
    unseen = set(bus_by_id)
    components = 0
    while unseen:
        components += 1
        start = unseen.pop()
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current] & unseen:
                unseen.remove(neighbor)
                queue.append(neighbor)
    if components > 1:
        warnings.append(f"topology_has_{components}_normally_connected_components")
    connected_bus_ids = set(bus_by_id)
    connected_asset_ids = {item.asset_id for item in topology.asset_connections if item.bus_id in connected_bus_ids}
    unconnected_assets = sorted(set(asset_by_id) - connected_asset_ids)
    if unconnected_assets:
        warnings.append("assets_without_declared_electrical_connection:" + ",".join(unconnected_assets))
    return {
        "site_id": topology.site_id,
        "status": "structurally_ready" if not blockers else "blocked",
        "is_structurally_ready": not blockers,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "bus_count": len(topology.buses),
        "branch_count": len(topology.branches),
        "asset_connection_count": len(topology.asset_connections),
        "normally_connected_component_count": components,
        "scope": "structural_topology_validation_only",
        "limitations": [
            "No load-flow or power-flow calculation",
            "No short-circuit, protection, grounding, arc-flash, or stability analysis",
            "No equipment compatibility certification or authorization for control",
        ],
    }
