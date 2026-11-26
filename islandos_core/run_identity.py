"""Canonical, deterministic input-group and technical run identity for IslandOS.

P1a identifies physical input history independently of page names and currency.
P1b identifies one reproducible Page 05/06 technical run definition from stable
settings and model-selection policy. Both functions are pure: no environment
variables, Streamlit state, database access, wall-clock time, or random IDs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from islandos_core.demo_site_history import canonical_history_sha256


INPUT_GROUP_SCHEMA = "islandos-input-group-v1"
INPUT_GROUP_SCHEMA_VERSION = 1
TARIFF_UNIT_TOKEN = "currency/kWh"

CANONICAL_SIGNAL_NAMES = (
    "pv_power_kw",
    "wind_power_kw",
    "load_kw",
    "tariff_per_kwh",
)
POWER_SIGNAL_NAMES = CANONICAL_SIGNAL_NAMES[:3]
PAGE_SIGNAL_ALIASES = {
    "pv_power": "pv_power_kw",
    "wind_power": "wind_power_kw",
    "essential_load": "load_kw",
    "electricity_price": "tariff_per_kwh",
}
_CURRENCY_UNIT = re.compile(r"^[A-Z]{3}/kWh$")


class RunIdentityError(ValueError):
    """Base error for invalid identity inputs; messages are deterministic."""


@dataclass(frozen=True)
class InputGroupIdentity:
    """A stable identity for the physical input series, independent of pages."""

    input_group_id: str
    input_group_sha256: str
    history_sha256: str
    units_sha256: str
    hour_count: int
    schema_version: int = INPUT_GROUP_SCHEMA_VERSION


def canonical_signal_name(name: str) -> str:
    """Map a Page 05 display name or canonical name to the physical name."""
    if not isinstance(name, str) or not name.strip():
        raise RunIdentityError("signal names must be non-empty strings")
    if name in CANONICAL_SIGNAL_NAMES:
        return name
    if name in PAGE_SIGNAL_ALIASES:
        return PAGE_SIGNAL_ALIASES[name]
    raise RunIdentityError(f"unsupported signal name: {name}")


def _canonical_mapping(mapping: Mapping[str, Any], field: str) -> dict[str, Any]:
    if not isinstance(mapping, Mapping):
        raise RunIdentityError(f"{field} must be a mapping")
    normalized: dict[str, Any] = {}
    for raw_name, value in mapping.items():
        name = canonical_signal_name(raw_name)
        if name in normalized:
            raise RunIdentityError(f"{field} contains duplicate signal: {name}")
        normalized[name] = value
    if set(normalized) != set(CANONICAL_SIGNAL_NAMES):
        raise RunIdentityError(
            f"{field} must contain exactly the four canonical signals"
        )
    return normalized


def canonicalize_history_signals(
    signals: Mapping[str, Sequence[float]],
) -> dict[str, list[float]]:
    """Return canonical physical names and validated numeric series.

    Both Page 05 (short display names) and Page 06 (physical names) are
    accepted. Missing, extra, or duplicate signals fail closed instead of
    being silently dropped or imputed.
    """
    normalized = _canonical_mapping(signals, "signals")
    lengths = set()
    result: dict[str, list[float]] = {}
    for name in CANONICAL_SIGNAL_NAMES:
        values = normalized[name]
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise RunIdentityError(f"signal {name} must be a sequence of numbers")
        if not values:
            raise RunIdentityError(f"signal {name} must not be empty")
        cleaned: list[float] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RunIdentityError(f"signal {name} must contain only finite numbers")
            number = float(value)
            if not math.isfinite(number):
                raise RunIdentityError(f"signal {name} must contain only finite numbers")
            cleaned.append(number)
        result[name] = cleaned
        lengths.add(len(cleaned))
    if len(lengths) != 1:
        raise RunIdentityError("all four signal arrays must share one length")
    return result


def canonicalize_units(units: Mapping[str, str]) -> dict[str, str]:
    """Return fixed physical unit labels with a currency-neutral tariff token."""
    normalized = _canonical_mapping(units, "units")
    result: dict[str, str] = {}
    for name in CANONICAL_SIGNAL_NAMES:
        unit = normalized[name]
        if not isinstance(unit, str) or not unit.strip():
            raise RunIdentityError(f"unit for {name} must be a non-empty string")
        unit = unit.strip()
        if name == "tariff_per_kwh" and _CURRENCY_UNIT.fullmatch(unit):
            unit = TARIFF_UNIT_TOKEN
        result[name] = unit
    return result


def _utc_timestamps(timestamps: Sequence[datetime]) -> tuple[datetime, ...]:
    if not isinstance(timestamps, Sequence) or isinstance(timestamps, (str, bytes)):
        raise RunIdentityError("timestamps must be a sequence of timezone-aware datetimes")
    if not timestamps:
        raise RunIdentityError("timestamps must not be empty")
    normalized: list[datetime] = []
    for value in timestamps:
        if not isinstance(value, datetime):
            raise RunIdentityError("timestamps must contain timezone-aware datetimes")
        if value.tzinfo is None or value.utcoffset() is None:
            raise RunIdentityError("timestamps must be timezone-aware")
        normalized.append(value.astimezone(timezone.utc))
    if len(set(normalized)) != len(normalized):
        raise RunIdentityError("timestamps must be unique")
    return tuple(sorted(normalized))


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def derive_input_group_id(
    *,
    timestamps: Sequence[datetime],
    signals: Mapping[str, Sequence[float]],
    units: Mapping[str, str],
) -> InputGroupIdentity:
    """Derive a cross-page identity from canonical history, units and row count.

    The time axis is sorted in UTC before hashing, so equivalent histories
    supplied in a different row order produce the same group. Duplicate
    timestamps are refused because their ordering would be ambiguous. Values
    are quantised to six decimals by ``canonical_history_sha256``; no null
    values are allowed and no missing rows are imputed.
    """
    stamps = _utc_timestamps(timestamps)
    normalized_signals = canonicalize_history_signals(signals)
    normalized_units = canonicalize_units(units)

    lengths = {len(values) for values in normalized_signals.values()}
    if len(lengths) != 1:
        raise RunIdentityError("all four signal arrays must share one length")
    hour_count = len(stamps)
    if next(iter(lengths)) != hour_count:
        raise RunIdentityError("timestamps and all four signal arrays must have the same length")

    # Sorting timestamps may require reordering the corresponding signal rows.
    source_stamps = [
        value.astimezone(timezone.utc) if isinstance(value, datetime) else value
        for value in timestamps
    ]
    order = sorted(range(hour_count), key=lambda index: source_stamps[index])
    sorted_signals = {
        name: [normalized_signals[name][index] for index in order]
        for name in CANONICAL_SIGNAL_NAMES
    }

    history_sha256 = canonical_history_sha256(
        timestamps=stamps,
        pv_power_kw=tuple(sorted_signals["pv_power_kw"]),
        wind_power_kw=tuple(sorted_signals["wind_power_kw"]),
        load_kw=tuple(sorted_signals["load_kw"]),
        tariff_per_kwh=tuple(sorted_signals["tariff_per_kwh"]),
    )
    units_sha256 = _sha256(normalized_units)
    input_group_sha256 = _sha256({
        "schema": INPUT_GROUP_SCHEMA,
        "history_sha256": history_sha256,
        "units_sha256": units_sha256,
        "hour_count": hour_count,
    })
    return InputGroupIdentity(
        input_group_id=f"ig-{input_group_sha256[:16]}",
        input_group_sha256=input_group_sha256,
        history_sha256=history_sha256,
        units_sha256=units_sha256,
        hour_count=hour_count,
    )
# P1b: deterministic technical run identity. This deliberately does not accept
# selected model IDs or investment-only assumptions; those are run evidence and
# append-only investment bindings, respectively.
RUN_IDENTITY_SCHEMA = "islandos-run-identity-v2"
RUN_IDENTITY_SCHEMA_VERSION = 1
PAGE_SLUGS = {
    "customer_dashboard": "05",
    "joint_resource_optimizer": "06",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INVESTMENT_ONLY_KEYS = {
    "investment",
    "investment_assumptions",
    "baseline_annual_energy_cost",
    "proposed_annual_energy_cost",
    "annual_incremental_om_cost",
    "upfront_capex",
    "project_life_years",
    "discount_rate",
    "annual_energy_saving_escalation_rate",
    "annual_om_escalation_rate",
    "replacement_cost",
    "residual_value",
    "payback_period",
    "net_present_value",
    "internal_rate_of_return",
}


@dataclass(frozen=True)
class RunIdentity:
    """A stable identity for one page's technical run definition."""

    run_id: str
    run_identity_sha256: str
    identity_schema_version: int
    page: str
    input_group: InputGroupIdentity | None


def _validate_json_value(value: Any, field: str) -> Any:
    """Validate and copy the deliberately narrow JSON-safe value set."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RunIdentityError(f"{field} must contain only finite JSON numbers")
        return value
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or not key.strip():
                raise RunIdentityError(f"{field} mapping keys must be non-empty strings")
            copied[key] = _validate_json_value(nested, f"{field}.{key}")
        return copied
    if isinstance(value, list):
        return [
            _validate_json_value(item, f"{field}[{index}]")
            for index, item in enumerate(value)
        ]
    raise RunIdentityError(f"{field} must contain JSON-safe values")


def _json_safe_mapping(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RunIdentityError(f"{field} must be a mapping")
    copied = _validate_json_value(value, field)
    if not isinstance(copied, dict):
        raise RunIdentityError(f"{field} must be a mapping")
    return copied


def _required_id_version(value: Mapping[str, str], field: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"id", "version"}:
        raise RunIdentityError(f"{field} must contain exactly non-empty id and version")
    identifier = value.get("id")
    version = value.get("version")
    if not isinstance(identifier, str) or not identifier.strip():
        raise RunIdentityError(f"{field}.id must be a non-empty string")
    if not isinstance(version, str) or not version.strip():
        raise RunIdentityError(f"{field}.version must be a non-empty string")
    return {"id": identifier.strip(), "version": version.strip()}


def _validate_input_group_identity(
    input_group: InputGroupIdentity | None,
) -> str | None:
    if input_group is None:
        return None
    if not isinstance(input_group, InputGroupIdentity):
        raise RunIdentityError("input_group must be an InputGroupIdentity or None")
    for field in ("input_group_sha256", "history_sha256", "units_sha256"):
        value = getattr(input_group, field)
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise RunIdentityError(f"input_group.{field} must be a 64-character lowercase SHA-256")
    if input_group.input_group_id != f"ig-{input_group.input_group_sha256[:16]}":
        raise RunIdentityError("input_group_id does not match input_group_sha256")
    if isinstance(input_group.hour_count, bool) or not isinstance(input_group.hour_count, int) or input_group.hour_count < 1:
        raise RunIdentityError("input_group.hour_count must be a positive integer")
    if (
        isinstance(input_group.schema_version, bool)
        or not isinstance(input_group.schema_version, int)
        or input_group.schema_version != INPUT_GROUP_SCHEMA_VERSION
    ):
        raise RunIdentityError("unsupported input-group schema version")
    return input_group.input_group_sha256


def _reject_investment_only_fields(value: Any, field: str) -> None:
    """Keep D6/D7 financial assumptions out of the technical run identity."""
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in _INVESTMENT_ONLY_KEYS:
                raise RunIdentityError(
                    f"{field}.{key} is investment-only and must use a separate run binding"
                )
            _reject_investment_only_fields(nested, f"{field}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_investment_only_fields(nested, f"{field}[{index}]")


def derive_run_id(
    *,
    page: str,
    input_group: InputGroupIdentity | None,
    site_configuration_sha256: str,
    page_settings: Mapping[str, Any],
    page_inputs: Mapping[str, Any],
    run_settings: Mapping[str, Any],
    forecast_settings: Mapping[str, Any],
    model_selection_policy: Mapping[str, str],
    model_catalogue_version: str,
    optimizer: Mapping[str, str],
    algorithm_versions: Mapping[str, str],
) -> RunIdentity:
    """Derive a page-scoped identity from stable technical run assumptions.

    Actual selected model IDs and result metrics are intentionally excluded:
    the stable selection policy and catalogue version are known before forecast.
    Investment-only assumptions are not accepted by this interface; they belong
    in a separate append-only run binding.
    """
    if not isinstance(page, str) or page not in PAGE_SLUGS:
        raise RunIdentityError("unsupported page for persistent run identity")
    if not isinstance(site_configuration_sha256, str) or not _SHA256_RE.fullmatch(site_configuration_sha256):
        raise RunIdentityError("site_configuration_sha256 must be a 64-character lowercase SHA-256")

    input_group_sha256 = _validate_input_group_identity(input_group)
    normalized_page_settings = _json_safe_mapping(page_settings, "page_settings")
    normalized_page_inputs = _json_safe_mapping(page_inputs, "page_inputs")
    normalized_run_settings = _json_safe_mapping(run_settings, "run_settings")
    normalized_forecast_settings = _json_safe_mapping(forecast_settings, "forecast_settings")
    _reject_investment_only_fields(normalized_page_settings, "page_settings")
    _reject_investment_only_fields(normalized_page_inputs, "page_inputs")
    _reject_investment_only_fields(normalized_run_settings, "run_settings")
    _reject_investment_only_fields(normalized_forecast_settings, "forecast_settings")
    currency = normalized_run_settings.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        raise RunIdentityError("run_settings.currency must be a non-empty string")
    normalized_run_settings["currency"] = currency.strip()

    normalized_policy = _required_id_version(model_selection_policy, "model_selection_policy")
    normalized_optimizer = _required_id_version(optimizer, "optimizer")
    if not isinstance(model_catalogue_version, str) or not model_catalogue_version.strip():
        raise RunIdentityError("model_catalogue_version must be a non-empty string")
    if not isinstance(algorithm_versions, Mapping) or not algorithm_versions:
        raise RunIdentityError("algorithm_versions must be a non-empty string mapping")
    normalized_algorithm_versions: dict[str, str] = {}
    for key, value in algorithm_versions.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip():
            raise RunIdentityError("algorithm_versions must be a non-empty string mapping")
        normalized_key = key.strip()
        if normalized_key in normalized_algorithm_versions:
            raise RunIdentityError("algorithm_versions contains duplicate normalized keys")
        normalized_algorithm_versions[normalized_key] = value.strip()

    page_inputs_sha256 = _sha256(normalized_page_inputs)
    run_identity_sha256 = _sha256({
        "schema": RUN_IDENTITY_SCHEMA,
        "identity_schema_version": RUN_IDENTITY_SCHEMA_VERSION,
        "page": page,
        "input_group_sha256": input_group_sha256,
        "site_configuration_sha256": site_configuration_sha256,
        "page_settings": normalized_page_settings,
        "page_inputs_sha256": page_inputs_sha256,
        "run_settings": normalized_run_settings,
        "forecast_settings": normalized_forecast_settings,
        "model_selection_policy": normalized_policy,
        "model_catalogue_version": model_catalogue_version.strip(),
        "optimizer": normalized_optimizer,
        "algorithm_versions": normalized_algorithm_versions,
    })
    return RunIdentity(
        run_id=f"run-{PAGE_SLUGS[page]}-{run_identity_sha256[:16]}",
        run_identity_sha256=run_identity_sha256,
        identity_schema_version=RUN_IDENTITY_SCHEMA_VERSION,
        page=page,
        input_group=input_group,
    )


def _validate_run_identity(identity: RunIdentity) -> None:
    if not isinstance(identity, RunIdentity):
        raise RunIdentityError("identity must be a RunIdentity")
    if not isinstance(identity.page, str) or identity.page not in PAGE_SLUGS:
        raise RunIdentityError("identity contains an unsupported page")
    if (
        isinstance(identity.identity_schema_version, bool)
        or not isinstance(identity.identity_schema_version, int)
        or identity.identity_schema_version != RUN_IDENTITY_SCHEMA_VERSION
    ):
        raise RunIdentityError("identity contains an unsupported identity schema version")
    if not isinstance(identity.run_identity_sha256, str) or not _SHA256_RE.fullmatch(identity.run_identity_sha256):
        raise RunIdentityError("identity has an invalid run_identity_sha256")
    if not isinstance(identity.run_id, str):
        raise RunIdentityError("identity has an invalid run_id")
    expected_run_id = f"run-{PAGE_SLUGS[identity.page]}-{identity.run_identity_sha256[:16]}"
    if identity.run_id != expected_run_id:
        raise RunIdentityError("run_id does not match the identity page and digest")
    _validate_input_group_identity(identity.input_group)


def run_record_identity_fields(identity: RunIdentity) -> dict[str, str | None]:
    """Map a derived run identity onto the immutable run-record identity fields.

    D5's technical identity digest is the D6 technical request digest: both
    cover exactly the inputs that can change a technical result. Do not hash the
    run id again, and do not substitute the full request digest. The returned
    mapping is meant to be passed to ``record_run_record`` together with the
    result and consent arguments::

        record_run_record(
            db, **run_record_identity_fields(identity),
            request_sha256=full_request_sha256,
            request_metadata=..., result=..., actor_id=...,
            consent_to_store_result=True,
        )
    """
    _validate_run_identity(identity)
    return {
        "run_id": identity.run_id,
        "page": identity.page,
        "run_request_sha256": identity.run_identity_sha256,
        "input_group_id": (
            identity.input_group.input_group_id
            if identity.input_group is not None
            else None
        ),
    }
