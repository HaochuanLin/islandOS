"""Versioned asset and operating-constraint records for IslandOS.

This is a planning/decision-support contract. It does not certify equipment
settings or authorize control writes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping


ASSET_TYPES = {"pv", "wind", "battery", "diesel_generator", "grid_connection", "flexible_load", "generic"}
SOURCE_TYPES = {"measured", "customer_provided", "vendor_specification", "inferred", "synthetic"}
SEVERITIES = {"hard", "operational", "soft"}
OPERATORS = {"min", "max", "range"}

REQUIRED_INSTALLED_PARAMETERS = {
    "pv": {"configured_power_kw"},
    "wind": {"configured_power_kw"},
    "battery": {"configured_power_kw", "usable_energy_capacity_kwh"},
    "diesel_generator": {"configured_power_kw"},
    "grid_connection": {"configured_power_kw"},
    "flexible_load": {"configured_power_kw"},
    "generic": set(),
}

REQUIRED_HARD_CONSTRAINTS = {
    "pv": {"max_power_kw": "max"},
    "wind": {"max_power_kw": "max"},
    "battery": {
        "max_charge_kw": "max", "max_discharge_kw": "max",
        "soc_min_pct": "min", "soc_max_pct": "max",
    },
    "diesel_generator": {"max_power_kw": "max", "min_stable_power_kw": "min"},
    "grid_connection": {"import_limit_kw": "max"},
    "flexible_load": {"max_power_kw": "max", "min_power_kw": "min"},
    "generic": {},
}

EXPECTED_UNITS = {
    "max_power_kw": "kW", "min_power_kw": "kW",
    "max_charge_kw": "kW", "max_discharge_kw": "kW",
    "min_stable_power_kw": "kW", "import_limit_kw": "kW",
    "export_limit_kw": "kW", "soc_min_pct": "%", "soc_max_pct": "%",
    "ramp_limit_kw_per_min": "kW/min",
}


class AssetValidationError(ValueError):
    """Raised when an asset record is malformed or physically inconsistent."""


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise AssetValidationError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AssetValidationError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise AssetValidationError(f"{label} must be a finite number")
    return number


@dataclass(frozen=True)
class AssetParameter:
    """One parameter with provenance; vendor rating and installed value stay distinct."""

    value: float
    unit: str
    source_type: str
    source_reference: str
    confirmed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _finite(self.value, "parameter value"))
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise AssetValidationError("parameter unit is required")
        if self.source_type not in SOURCE_TYPES:
            raise AssetValidationError("unsupported parameter source_type")
        if not isinstance(self.source_reference, str) or not self.source_reference.strip():
            raise AssetValidationError("parameter source_reference is required")
        if not isinstance(self.confirmed, bool):
            raise AssetValidationError("parameter confirmed must be boolean")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AssetParameter":
        if not isinstance(value, Mapping):
            raise AssetValidationError("asset parameter must be an object")
        required = {"value", "unit", "source_type", "source_reference"}
        unknown = sorted(set(value) - set(cls.__dataclass_fields__))
        if unknown:
            raise AssetValidationError("unknown parameter fields: " + ", ".join(unknown))
        missing = sorted(required - set(value))
        if missing:
            raise AssetValidationError("missing parameter fields: " + ", ".join(missing))
        return cls(**{key: value[key] for key in cls.__dataclass_fields__ if key in value})


@dataclass(frozen=True)
class OperatingConstraint:
    """A documented min/max/range operating boundary for one asset parameter."""

    constraint_id: str
    parameter: str
    severity: str
    unit: str
    operator: str
    lower_bound: float | None = None
    upper_bound: float | None = None
    source_type: str = "customer_provided"
    source_reference: str = ""
    confirmed: bool = False
    rationale: str = ""

    def __post_init__(self) -> None:
        for field_name in ("constraint_id", "parameter", "unit", "source_reference"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise AssetValidationError(f"{field_name} is required")
        if self.severity not in SEVERITIES:
            raise AssetValidationError("severity must be hard, operational, or soft")
        if self.operator not in OPERATORS:
            raise AssetValidationError("operator must be min, max, or range")
        if self.source_type not in SOURCE_TYPES:
            raise AssetValidationError("unsupported constraint source_type")
        if not isinstance(self.confirmed, bool):
            raise AssetValidationError("constraint confirmed must be boolean")
        if self.lower_bound is not None:
            object.__setattr__(self, "lower_bound", _finite(self.lower_bound, "lower_bound"))
        if self.upper_bound is not None:
            object.__setattr__(self, "upper_bound", _finite(self.upper_bound, "upper_bound"))
        if self.operator == "min" and (self.lower_bound is None or self.upper_bound is not None):
            raise AssetValidationError("min constraint requires only lower_bound")
        if self.operator == "max" and (self.upper_bound is None or self.lower_bound is not None):
            raise AssetValidationError("max constraint requires only upper_bound")
        if self.operator == "range":
            if self.lower_bound is None or self.upper_bound is None:
                raise AssetValidationError("range constraint requires both bounds")
            if self.lower_bound > self.upper_bound:
                raise AssetValidationError("range lower_bound cannot exceed upper_bound")
        expected = EXPECTED_UNITS.get(self.parameter)
        if expected and self.unit != expected:
            raise AssetValidationError(f"{self.parameter} unit must be {expected}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OperatingConstraint":
        if not isinstance(value, Mapping):
            raise AssetValidationError("constraint must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise AssetValidationError("unknown constraint fields: " + ", ".join(unknown))
        try:
            return cls(**dict(value))
        except TypeError as exc:
            raise AssetValidationError(f"invalid constraint fields: {exc}") from exc


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    site_id: str
    asset_type: str
    nameplate_parameters: Mapping[str, AssetParameter]
    installed_parameters: Mapping[str, AssetParameter]
    observed_parameters: Mapping[str, AssetParameter]
    constraints: tuple[OperatingConstraint, ...]
    available: bool = True
    schema_version: str = "1.0"
    manufacturer: str | None = None
    model: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("asset_id", "site_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise AssetValidationError(f"{field_name} is required")
        if self.asset_type not in ASSET_TYPES:
            raise AssetValidationError("unsupported asset_type")
        if self.schema_version != "1.0":
            raise AssetValidationError("unsupported asset schema_version")
        if not isinstance(self.available, bool):
            raise AssetValidationError("available must be boolean")
        for group_name in ("nameplate_parameters", "installed_parameters", "observed_parameters"):
            group = getattr(self, group_name)
            if not isinstance(group, Mapping):
                raise AssetValidationError(f"{group_name} must be a mapping")
            for key, value in group.items():
                if not isinstance(key, str) or not key.strip() or not isinstance(value, AssetParameter):
                    raise AssetValidationError(f"{group_name} entries must map names to AssetParameter")
        if not isinstance(self.constraints, tuple) or any(not isinstance(item, OperatingConstraint) for item in self.constraints):
            raise AssetValidationError("constraints must be a tuple of OperatingConstraint")
        ids = [item.constraint_id for item in self.constraints]
        if len(ids) != len(set(ids)):
            raise AssetValidationError("constraint_id values must be unique")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AssetRecord":
        if not isinstance(value, Mapping):
            raise AssetValidationError("asset record must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise AssetValidationError("unknown asset fields: " + ", ".join(unknown))
        groups = {}
        for group_name in ("nameplate_parameters", "installed_parameters", "observed_parameters"):
            raw_group = value.get(group_name, {})
            if not isinstance(raw_group, Mapping):
                raise AssetValidationError(f"{group_name} must be a mapping")
            groups[group_name] = {
                key: item if isinstance(item, AssetParameter) else AssetParameter.from_mapping(item)
                for key, item in raw_group.items()
            }
        raw_constraints = value.get("constraints", [])
        if not isinstance(raw_constraints, (list, tuple)):
            raise AssetValidationError("constraints must be a list")
        constraints = tuple(
            item if isinstance(item, OperatingConstraint) else OperatingConstraint.from_mapping(item)
            for item in raw_constraints
        )
        try:
            return cls(
                asset_id=value.get("asset_id", ""),
                site_id=value.get("site_id", ""),
                asset_type=value.get("asset_type", ""),
                constraints=constraints,
                **groups,
                **{key: value[key] for key in ("available", "schema_version", "manufacturer", "model") if key in value},
            )
        except TypeError as exc:
            raise AssetValidationError(f"invalid asset fields: {exc}") from exc

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "site_id": self.site_id,
            "asset_type": self.asset_type,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "available": self.available,
            "nameplate_parameters": {key: asdict(value) for key, value in self.nameplate_parameters.items()},
            "installed_parameters": {key: asdict(value) for key, value in self.installed_parameters.items()},
            "observed_parameters": {key: asdict(value) for key, value in self.observed_parameters.items()},
            "constraints": [asdict(value) for value in self.constraints],
        }


def evaluate_asset_readiness(asset: AssetRecord) -> dict[str, Any]:
    """Report whether an asset has confirmed minimum operating constraints."""
    if not isinstance(asset, AssetRecord):
        raise TypeError("asset must be an AssetRecord")
    if not asset.available:
        return {"asset_id": asset.asset_id, "status": "unavailable", "can_screen": False, "blockers": ["asset_unavailable"]}
    required_installed = REQUIRED_INSTALLED_PARAMETERS[asset.asset_type]
    blockers = []
    for parameter in sorted(required_installed):
        installed = asset.installed_parameters.get(parameter)
        if installed is None or not installed.confirmed:
            blockers.append("confirmed_installed_parameter_required:" + parameter)
    nameplate_power = asset.nameplate_parameters.get("rated_power_kw")
    installed_power = asset.installed_parameters.get("configured_power_kw")
    if nameplate_power and installed_power and installed_power.value > nameplate_power.value:
        blockers.append("installed_power_exceeds_nameplate")
    nameplate_energy = asset.nameplate_parameters.get("energy_capacity_kwh")
    installed_energy = asset.installed_parameters.get("usable_energy_capacity_kwh")
    if nameplate_energy and installed_energy and installed_energy.value > nameplate_energy.value:
        blockers.append("installed_energy_exceeds_nameplate")

    required = REQUIRED_HARD_CONSTRAINTS[asset.asset_type]
    by_parameter: dict[str, list[OperatingConstraint]] = {}
    for constraint in asset.constraints:
        by_parameter.setdefault(constraint.parameter, []).append(constraint)
    for parameter, expected_operator in sorted(required.items()):
        candidates = by_parameter.get(parameter, [])
        hard_confirmed = [
            item for item in candidates
            if item.severity == "hard" and item.confirmed and item.operator == expected_operator
        ]
        if not hard_confirmed:
            blockers.append(
                "confirmed_hard_constraint_required:" + parameter + ":" + expected_operator
            )
    if installed_power:
        for parameter in ("max_power_kw", "max_charge_kw", "max_discharge_kw", "import_limit_kw", "min_stable_power_kw", "min_power_kw"):
            for item in by_parameter.get(parameter, []):
                bound = item.upper_bound if item.operator == "max" else item.lower_bound
                if bound is not None and bound > installed_power.value:
                    blockers.append("constraint_exceeds_installed_power:" + parameter)
    if asset.asset_type in {"diesel_generator", "flexible_load"}:
        minimum_name = "min_stable_power_kw" if asset.asset_type == "diesel_generator" else "min_power_kw"
        minimums = [item.lower_bound for item in by_parameter.get(minimum_name, []) if item.lower_bound is not None]
        maximums = [item.upper_bound for item in by_parameter.get("max_power_kw", []) if item.upper_bound is not None]
        if minimums and maximums and max(minimums) > min(maximums):
            blockers.append("minimum_power_exceeds_maximum_power")
    if asset.asset_type == "battery":
        lower = by_parameter.get("soc_min_pct", [])
        upper = by_parameter.get("soc_max_pct", [])
        if lower and upper:
            low_values = [item.lower_bound for item in lower if item.operator == "min" and item.lower_bound is not None]
            high_values = [item.upper_bound for item in upper if item.operator == "max" and item.upper_bound is not None]
            if low_values and high_values and max(low_values) >= min(high_values):
                blockers.append("battery_soc_bounds_inconsistent")
    return {
        "asset_id": asset.asset_id,
        "status": "ready_for_offline_screening" if not blockers else "blocked",
        "can_screen": not blockers,
        "blockers": blockers,
        "note": "Asset readiness is a data/constraint completeness check, not equipment certification or authorization for control.",
    }
