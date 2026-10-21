"""Central parameter configuration for IslandOS research simulations.

Configuration values are assumptions until the user replaces them with sourced
site/equipment data. This module validates inputs; it does not certify physics,
plant safety, or the accuracy of a supplied parameter.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": 1,
    "metadata": {
        "name": "IslandOS illustrative baseline",
        "status": "illustrative_defaults_not_site_data",
        "notes": "Replace example values with sourced site/equipment data before interpreting results for a real site.",
    },
    "equipment": {
        "ro": {
            "specific_energy_kwh_m3": 3.5,
            "reservoir_capacity_m3": 500.0,
            "initial_water_m3": 150.0,
            "dead_storage_m3": 20.0,
            "allow_backup_power": False,
        },
        "ice": {
            "coefficient_of_performance": 2.5,
            "storage_capacity_kwh_th": 400.0,
            "initial_storage_kwh_th": 100.0,
        },
    },
    "search_space": {
        "priority": ["ro_first", "ice_first"],
        "ro_min_run_hours": [1, 2, 3, 4],
        "ro_start_ratio": [0.6, 0.7, 0.8, 0.9],
        "ro_rated_power_kw": [250.0, 300.0, 350.0, 400.0],
        "ice_rated_power_kw": [50.0, 75.0, 100.0],
    },
    "economics": {
        "currency": "USD",
        "electricity_price_per_kwh": None,
        "ro_capex": None,
        "ro_fixed_om_per_year": None,
        "ro_variable_om_per_m3": None,
        "chiller_capex": None,
        "chiller_fixed_om_per_year": None,
        "analysis_years": None,
        "discount_rate": None,
        "source_notes": "Cost fields are intentionally blank. The current optimizer does not calculate lifecycle cost.",
    },
    "parameter_sources": {
        "default_policy": "Each parameter must be identified as measured, vendor-sourced, public, assumed, or unknown before site-specific claims are made.",
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def validate_config(config: dict[str, Any]) -> list[str]:
    """Return validation errors; an empty list means structurally valid."""
    errors: list[str] = []
    if config.get("config_version") != 1:
        errors.append("config_version must be 1")
    equipment = config.get("equipment")
    search = config.get("search_space")
    economics = config.get("economics")
    if not isinstance(equipment, dict) or not isinstance(search, dict) or not isinstance(economics, dict):
        return errors + ["equipment, search_space, and economics must be objects"]

    def finite_number(container: dict, key: str, path: str, *, minimum: float | None = None,
                      allow_none: bool = False) -> float | None:
        value = container.get(key)
        if value is None and allow_none:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            errors.append(f"{path}.{key} must be a finite number" + (" or null" if allow_none else ""))
            return None
        if minimum is not None and value < minimum:
            errors.append(f"{path}.{key} must be >= {minimum}")
        return float(value)

    ro = equipment.get("ro", {})
    ice = equipment.get("ice", {})
    if not isinstance(ro, dict) or not isinstance(ice, dict):
        return errors + ["equipment.ro and equipment.ice must be objects"]
    finite_number(ro, "specific_energy_kwh_m3", "equipment.ro", minimum=1e-12)
    capacity = finite_number(ro, "reservoir_capacity_m3", "equipment.ro", minimum=0)
    initial = finite_number(ro, "initial_water_m3", "equipment.ro", minimum=0)
    dead = finite_number(ro, "dead_storage_m3", "equipment.ro", minimum=0)
    if capacity is not None and initial is not None and initial > capacity:
        errors.append("equipment.ro.initial_water_m3 must be <= reservoir_capacity_m3")
    if dead is not None and initial is not None and dead > initial:
        errors.append("equipment.ro.dead_storage_m3 must be <= initial_water_m3")
    if "allow_backup_power" in ro and not isinstance(ro["allow_backup_power"], bool):
        errors.append("equipment.ro.allow_backup_power must be boolean")
    finite_number(ice, "coefficient_of_performance", "equipment.ice", minimum=1e-12)
    ice_capacity = finite_number(ice, "storage_capacity_kwh_th", "equipment.ice", minimum=0)
    ice_initial = finite_number(ice, "initial_storage_kwh_th", "equipment.ice", minimum=0)
    if ice_capacity is not None and ice_initial is not None and ice_initial > ice_capacity:
        errors.append("equipment.ice.initial_storage_kwh_th must be <= storage_capacity_kwh_th")

    expected = {
        "priority": lambda v: isinstance(v, str) and v in {"ro_first", "ice_first"},
        "ro_min_run_hours": lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 1,
        "ro_start_ratio": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1,
        "ro_rated_power_kw": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0,
        "ice_rated_power_kw": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0,
    }
    for key, predicate in expected.items():
        values = search.get(key)
        if not isinstance(values, list) or not values:
            errors.append(f"search_space.{key} must be a non-empty list")
        elif any(not predicate(value) for value in values):
            errors.append(f"search_space.{key} contains an invalid value")

    for key in (
        "electricity_price_per_kwh", "ro_capex", "ro_fixed_om_per_year",
        "ro_variable_om_per_m3", "chiller_capex", "chiller_fixed_om_per_year",
        "analysis_years", "discount_rate",
    ):
        value = economics.get(key)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                errors.append(f"economics.{key} must be a finite non-negative number or null")
    return errors


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load defaults plus optional JSON overrides, then validate the result."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    if path is not None:
        config_path = Path(path)
        try:
            supplied = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON configuration {config_path}: {exc}") from exc
        if not isinstance(supplied, dict):
            raise ValueError("Configuration root must be a JSON object")
        config = _merge(config, supplied)
        config["_loaded_from"] = str(config_path)
    errors = validate_config(config)
    if errors:
        raise ValueError("Invalid IslandOS configuration: " + "; ".join(errors))
    return config


def economics_completeness(config: dict[str, Any]) -> dict[str, Any]:
    """Report economic-data completeness without implying cost optimization exists."""
    required = (
        "electricity_price_per_kwh", "ro_capex", "ro_fixed_om_per_year",
        "ro_variable_om_per_m3", "chiller_capex", "chiller_fixed_om_per_year",
        "analysis_years", "discount_rate",
    )
    economics = config["economics"]
    missing = [key for key in required if economics.get(key) is None]
    return {
        "complete_for_current_declared_fields": not missing,
        "missing_fields": missing,
        "cost_objective_implemented": False,
        "note": "Completing fields does not activate lifecycle-cost optimization; the current optimizer does not calculate costs.",
    }
