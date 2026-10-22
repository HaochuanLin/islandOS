import numpy as np

from experiments.compare_energy_water_strategies import Config, SiteStep
from experiments.nsga2_dispatch_optimizer import (
    _evaluate_schedule,
    _objective_vector,
    _is_dominated,
    _decode_power_levels,
    optimize_dispatch,
)


def sample_steps(demand=0.0):
    return [
        SiteStep("2026-01-01T00:00", 10.0, 0.0, 0.5, True, True, demand),
        SiteStep("2026-01-01T01:00", 0.0, 0.0, 0.1, True, True, demand),
        SiteStep("2026-01-01T02:00", 10.0, 0.0, 0.5, False, True, demand),
        SiteStep("2026-01-01T03:00", 0.0, 0.0, 0.1, True, True, demand),
    ]


def sample_config():
    return Config(
        ro_rated_power_kw=10.0,
        specific_energy_kwh_m3=4.0,
        tank_capacity_m3=100.0,
        initial_water_m3=0.0,
        min_run_hours=1,
        dt_hours=1.0,
    )


def test_evaluator_uses_genes_and_manual_schedules_change_metrics():
    steps, config = sample_steps(), sample_config()
    renewable_schedule = np.array([1, 0, 0, 0])  # index 1 => 6 kW in interval 0
    grid_schedule = np.array([0, 1, 0, 0])       # index 1 => 6 kW in interval 1
    renewable, renewable_detail = _evaluate_schedule(renewable_schedule, steps, config)
    grid, grid_detail = _evaluate_schedule(grid_schedule, steps, config)

    assert renewable["surplus_energy_to_ro_kwh"] == 6.0
    assert renewable["grid_energy_cost"] == 0.0
    assert grid["surplus_energy_to_ro_kwh"] == 0.0
    assert grid["grid_energy_cost"] == 0.6
    assert renewable_detail[0]["ro_source"] == "surplus"
    assert renewable_detail[0]["ro_power_kw"] == 6.0
    assert grid_detail[1]["ro_source"] == "grid"
    assert grid_detail[1]["ro_power_kw"] == 6.0
    assert _decode_power_levels(np.array([0, 1, 2, 3]), 4) == [0, 6, 8, 10]
    assert _objective_vector(renewable) != _objective_vector(grid)


def test_zero_unmet_demand_and_tank_overflow_are_hard_constraints():
    steps, config = sample_steps(demand=0.0), sample_config()
    summary, _ = _evaluate_schedule(np.array([0, 0, 0, 0]), steps, config)
    assert summary["unmet_water_demand_m3"] == 0.0
    assert summary["water_spill_m3"] == 0.0

    summary_with_demand, _ = _evaluate_schedule(
        np.array([0, 0, 0, 0]), sample_steps(demand=1.0), config
    )
    assert summary_with_demand["unmet_water_demand_m3"] > 0.0

    small_tank = Config(10.0, 4.0, 2.0, 0.0, min_run_hours=1, dt_hours=1.0)
    spilling, _ = _evaluate_schedule(np.array([1, 1, 0, 0]), steps, small_tank)
    assert spilling["water_spill_m3"] > 0.0


def test_returned_solutions_are_unique_feasible_and_non_dominated():
    summaries, details, meta = optimize_dispatch(
        sample_steps(), sample_config(), population_size=120, generations=60, seed=19
    )
    assert summaries, meta["message"]
    assert all(row["unmet_water_demand_m3"] == 0.0 for row in summaries)
    assert all(row["minimum_run_constraint_violations"] == 0 for row in summaries)
    assert all(row["water_spill_m3"] == 0.0 for row in summaries)
    assert meta["objective_count"] == 2
    # With no early termination, pymoo evaluates the initial population and each
    # generation's offspring population. Keep the live metric contract explicit.
    assert meta["evaluations"] == 120 * 60
    assert all(-1e-6 <= row["ending_water_inventory_m3"] <= sample_config().tank_capacity_m3 + 1e-6 for row in summaries)
    assert len({row["strategy"] for row in summaries}) == len(summaries)
    assert len(details) == len(summaries) * len(sample_steps())

    vectors = [_objective_vector(row) for row in summaries]
    assert len(set(vectors)) == len(vectors)
    for i, candidate in enumerate(vectors):
        assert not _is_dominated(candidate, vectors[:i] + vectors[i + 1:])


def test_optimizer_is_reproducible_for_fixed_seed():
    args = dict(population_size=120, generations=60, seed=123)
    first, _, _ = optimize_dispatch(sample_steps(), sample_config(), **args)
    second, _, _ = optimize_dispatch(sample_steps(), sample_config(), **args)
    first_values = [_objective_vector(row) for row in first]
    second_values = [_objective_vector(row) for row in second]
    assert first_values == second_values


def test_optimizer_rejects_search_budget_below_requested_minimum():
    import pytest
    with pytest.raises(ValueError, match="population_size must be >= 120"):
        optimize_dispatch(sample_steps(), sample_config(), population_size=119, generations=60)
