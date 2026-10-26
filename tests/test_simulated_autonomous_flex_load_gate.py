"""Tests for the simulation-only autonomous flexible-load gate."""
import pytest

from experiments.simulated_autonomous_flex_load_gate import evaluate_simulated_action


def plan(**overrides):
    row = {
        "hour_index": 0,
        "actual_surplus_kw": 250.0,
        "ro_power_kw": 200.0,
        "ice_power_kw": 30.0,
        "water_inventory_m3": 100.0,
        "ro_active": True,
        "total_constraint_violations": 0,
    }
    row.update(overrides)
    return row


def evaluate(row=None, **overrides):
    return evaluate_simulated_action(
        plan() if row is None else row,
        telemetry_valid=overrides.pop("telemetry_valid", True),
        interlocks_healthy=overrides.pop("interlocks_healthy", True),
        operator_stop=overrides.pop("operator_stop", False),
        **overrides,
    )


def test_approves_only_a_simulated_on_action_inside_power_envelope():
    result = evaluate()
    assert result["action"] == "ON"
    assert result["reason_code"] == "SIM_RO_PLAN_ON_APPROVED"
    assert result["mode"] == "simulation_only"
    assert result["physical_write_performed"] is False
    assert result["live_control_enabled"] is False


def test_off_plan_remains_off_with_auditable_reason():
    result = evaluate(plan(ro_active=False))
    assert result["action"] == "OFF"
    assert result["reason_code"] == "SIM_RO_PLAN_OFF_APPROVED"


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"telemetry_valid": False}, "HOLD_TELEMETRY_INVALID"),
        ({"interlocks_healthy": False}, "HOLD_INTERLOCK_UNHEALTHY"),
        ({"operator_stop": True}, "HOLD_OPERATOR_STOP"),
    ],
)
def test_safety_gates_fail_closed(kwargs, reason):
    result = evaluate(plan(actual_surplus_kw="malformed"), **kwargs)
    assert result["action"] == "HOLD"
    assert result["reason_code"] == reason
    assert result["physical_write_performed"] is False


def test_rejects_power_exceeding_surplus_even_if_dispatch_plan_requests_on():
    result = evaluate(plan(actual_surplus_kw=100.0))
    assert result["action"] == "HOLD"
    assert result["reason_code"] == "HOLD_SURPLUS_BALANCE_FAILED"


def test_rejects_power_above_configured_envelope():
    result = evaluate(max_total_power_kw=200.0)
    assert result["action"] == "HOLD"
    assert result["reason_code"] == "HOLD_AUTHORIZED_POWER_LIMIT"


def test_rejects_existing_dispatch_constraint_violation():
    result = evaluate(plan(total_constraint_violations=1))
    assert result["action"] == "HOLD"
    assert result["reason_code"] == "HOLD_DISPATCH_CONSTRAINT_VIOLATION"


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual_surplus_kw", float("nan")),
        ("ro_power_kw", -1),
        ("ice_power_kw", True),
        ("water_inventory_m3", "unknown"),
    ],
)
def test_rejects_bad_numeric_telemetry(field, value):
    with pytest.raises(ValueError):
        evaluate(plan(**{field: value}))


def test_rejects_non_boolean_gate_flags():
    with pytest.raises(ValueError, match="telemetry_valid must be boolean"):
        evaluate(telemetry_valid=1)
