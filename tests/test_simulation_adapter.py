from datetime import datetime, timezone

import pytest

from islandos_core.simulation_adapter import (
    SimulationRowAdapterError,
    simulation_row_to_screening_signals,
)


def valid_row():
    return {
        "timestamp": "2026-10-23T10:00:00+00:00",
        "renewable_surplus_available_kw": 12.5,
        "water_inventory_before_m3": 18,
    }


def test_maps_simulation_row_to_normalized_virtual_signals():
    renewable, inventory = simulation_row_to_screening_signals(valid_row())
    assert (renewable.signal_id, renewable.value, renewable.unit) == ("renewable_surplus_kw", 12.5, "kW")
    assert (inventory.signal_id, inventory.value, inventory.unit) == ("water_inventory_m3", 18.0, "m3")
    assert renewable.source == inventory.source == "offline-simulation"
    assert renewable.timestamp == datetime(2026, 10, 23, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize("field", ["timestamp", "renewable_surplus_available_kw", "water_inventory_before_m3"])
def test_rejects_missing_fields(field):
    row = valid_row()
    del row[field]
    with pytest.raises(SimulationRowAdapterError, match="missing"):
        simulation_row_to_screening_signals(row)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), "not-a-number"])
def test_rejects_invalid_numeric_values(value):
    row = valid_row()
    row["renewable_surplus_available_kw"] = value
    with pytest.raises(SimulationRowAdapterError):
        simulation_row_to_screening_signals(row)


def test_rejects_naive_timestamp():
    row = valid_row()
    row["timestamp"] = "2026-10-23T10:00:00"
    with pytest.raises(SimulationRowAdapterError, match="timezone"):
        simulation_row_to_screening_signals(row)
