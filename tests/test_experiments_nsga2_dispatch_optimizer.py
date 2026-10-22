import numpy as np

from experiments.compare_energy_water_strategies import Config, SiteStep
from experiments.nsga2_dispatch_optimizer import _evaluate_schedule, optimize_dispatch


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


def test_zero_unmet_demand_is_required_for_feasibility():
    steps = sample_steps(demand=0.0)
    config = sample_config()
    summary, _ = _evaluate_schedule(np.array([0, 0, 0, 0]), steps, config)
    assert summary["unmet_water_demand_m3"] == 0.0

    summary_with_demand, _ = _evaluate_schedule(
        np.array([0, 0, 0, 0]), sample_steps(demand=1.0), config
    )
    assert summary_with_demand["unmet_water_demand_m3"] > 0.0

    summaries, _, meta = optimize_dispatch(
        steps, config, population_size=20, generations=5, seed=7
    )
    assert summaries, meta["message"]
    assert all(row["unmet_water_demand_m3"] == 0.0 for row in summaries)
    assert all(row["minimum_run_constraint_violations"] == 0 for row in summaries)


def test_returned_solutions_are_non_dominated():
    summaries, _, meta = optimize_dispatch(
        sample_steps(), sample_config(), population_size=24, generations=6, seed=19
    )
    assert summaries, meta["message"]
    for i, candidate in enumerate(summaries):
        for j, other in enumerate(summaries):
            if i == j:
                continue
            no_worse = (
                other["grid_energy_cost"] <= candidate["grid_energy_cost"]
                and other["surplus_energy_to_ro_kwh"] >= candidate["surplus_energy_to_ro_kwh"]
            )
            strictly_better = (
                other["grid_energy_cost"] < candidate["grid_energy_cost"]
                or other["surplus_energy_to_ro_kwh"] > candidate["surplus_energy_to_ro_kwh"]
            )
            assert not (no_worse and strictly_better), (
                f"{other['strategy']} dominates {candidate['strategy']}"
            )


def test_optimizer_is_reproducible_for_fixed_seed():
    args = dict(population_size=24, generations=6, seed=123)
    first, _, _ = optimize_dispatch(sample_steps(), sample_config(), **args)
    second, _, _ = optimize_dispatch(sample_steps(), sample_config(), **args)
    first_values = [
        (row["grid_energy_cost"], row["surplus_energy_to_ro_kwh"],
         row["water_produced_m3"], row["unmet_water_demand_m3"])
        for row in first
    ]
    second_values = [
        (row["grid_energy_cost"], row["surplus_energy_to_ro_kwh"],
         row["water_produced_m3"], row["unmet_water_demand_m3"])
        for row in second
    ]
    assert first_values == second_values
