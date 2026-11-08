"""Timestamped equipment operating-state snapshots and readiness evaluation.

This is a read-only data-quality/readiness layer. It does not infer a state from
asset type, command equipment, or change the static asset registry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from islandos_core.assets import AssetRecord
from islandos_core.electrical_topology import ElectricalTopology


OPERATIONAL_STATES = {"online", "offline", "maintenance", "fault", "unknown"}


class OperationalStateError(ValueError):
    """Raised when an operating-state observation is malformed."""


@dataclass(frozen=True)
class AssetOperationalState:
    asset_id: str
    site_id: str
    state: str
    observed_at: datetime
    source_reference: str
    confirmed: bool = False

    def __post_init__(self) -> None:
        for field_name in ("asset_id", "site_id", "source_reference"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise OperationalStateError(f"{field_name} is required")
        if self.state not in OPERATIONAL_STATES:
            raise OperationalStateError("unsupported operational state")
        if not isinstance(self.observed_at, datetime):
            raise OperationalStateError("observed_at must be a datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise OperationalStateError("observed_at must be timezone-aware")
        if not isinstance(self.confirmed, bool):
            raise OperationalStateError("confirmed must be boolean")


def evaluate_operational_readiness(
    assets: Sequence[AssetRecord],
    observations: Sequence[AssetOperationalState],
    *,
    as_of: datetime,
    max_age: timedelta = timedelta(minutes=15),
    topology: ElectricalTopology | None = None,
) -> dict:
    """Evaluate whether observed asset states are sufficiently fresh/confirmed.

    Missing, stale, unconfirmed, unknown, unavailable, and non-online assets
    block dispatch readiness. Assets not connected in the optional topology
    are excluded from the connected-asset set; this is not a dispatch model.
    """
    if not isinstance(assets, Sequence) or isinstance(assets, (str, bytes)):
        raise OperationalStateError("assets must be a sequence")
    if any(not isinstance(asset, AssetRecord) for asset in assets):
        raise OperationalStateError("assets must contain AssetRecord values")
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        raise OperationalStateError("observations must be a sequence")
    if any(not isinstance(item, AssetOperationalState) for item in observations):
        raise OperationalStateError("observations must contain AssetOperationalState values")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise OperationalStateError("as_of must be timezone-aware")
    if topology is not None and not isinstance(topology, ElectricalTopology):
        raise OperationalStateError("topology must be an ElectricalTopology")
    if not isinstance(max_age, timedelta) or max_age <= timedelta(0):
        raise OperationalStateError("max_age must be a positive timedelta")
    asset_by_id = {asset.asset_id: asset for asset in assets}
    blockers: list[str] = []
    warnings: list[str] = []
    if not assets:
        blockers.append("at_least_one_asset_required")
    if len(asset_by_id) != len(assets):
        blockers.append("duplicate_asset_ids")
    observation_by_id: dict[str, AssetOperationalState] = {}
    for observation in observations:
        if observation.asset_id in observation_by_id:
            blockers.append(f"duplicate_operational_state:{observation.asset_id}")
            continue
        observation_by_id[observation.asset_id] = observation
        asset = asset_by_id.get(observation.asset_id)
        if asset is None:
            blockers.append(f"operational_state_asset_missing:{observation.asset_id}")
            continue
        if observation.site_id != asset.site_id:
            blockers.append(f"operational_state_site_mismatch:{observation.asset_id}")
        if topology is not None and observation.site_id != topology.site_id:
            blockers.append(f"operational_state_topology_site_mismatch:{observation.asset_id}")
    if topology is not None:
        if any(asset.site_id != topology.site_id for asset in assets):
            blockers.append("asset_topology_site_mismatch")
        from islandos_core.electrical_topology import validate_electrical_topology

        topology_readiness = validate_electrical_topology(topology, assets)
        if not topology_readiness["is_structurally_ready"]:
            blockers.extend("topology:" + item for item in topology_readiness["blockers"])
        connected_ids = {item.asset_id for item in topology.asset_connections}
        target_assets = {asset_id: asset for asset_id, asset in asset_by_id.items() if asset_id in connected_ids}
    else:
        target_assets = asset_by_id

    now = as_of.astimezone(timezone.utc)
    for asset_id, asset in sorted(target_assets.items()):
        if not asset.available:
            blockers.append(f"asset_unavailable:{asset_id}")
        observation = observation_by_id.get(asset_id)
        if observation is None:
            blockers.append(f"operational_state_missing:{asset_id}")
            continue
        age = now - observation.observed_at.astimezone(timezone.utc)
        if age < timedelta(0):
            blockers.append(f"operational_state_from_future:{asset_id}")
        elif age > max_age:
            blockers.append(f"operational_state_stale:{asset_id}")
        if not observation.confirmed:
            blockers.append(f"operational_state_unconfirmed:{asset_id}")
        if observation.state == "unknown":
            blockers.append(f"operational_state_unknown:{asset_id}")
        elif observation.state != "online":
            blockers.append(f"asset_not_online:{asset_id}:{observation.state}")
    return {
        "status": "operationally_ready" if not blockers else "blocked",
        "can_dispatch_screen": not blockers,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "evaluated_asset_count": len(target_assets),
        "observed_asset_count": sum(asset_id in observation_by_id for asset_id in target_assets),
        "topology_structurally_ready": (
            topology_readiness["is_structurally_ready"] if topology is not None else None
        ),
        "max_observation_age_seconds": max_age.total_seconds(),
        "scope": "read_only_operational_state_readiness",
        "limitations": [
            "State observations are not live device telemetry unless the source explicitly establishes that provenance",
            "No device commands or autonomous control are issued",
            "Operational readiness does not prove electrical safety or physical connectivity",
        ],
    }
