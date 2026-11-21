"""Tests for the simulation and optimisation work package.

Covers the joint MILP extensions (terminal tank, RO minimum, flexible load,
price-aware baseline, grid-before-diesel, non-fatal rule baselines, timeouts),
diesel ramp-down and minimum run times in the evolutionary search, the
forecast-based RO rule, the stress studies, and the experiment runners.
All inputs are synthetic.
"""
from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest

from islandos_core.energy_system import dispatch_energy_system
from islandos_core.impact_scenario import (
    CASES, IslandSiteConfig, StrategyRules, _energy_inputs, compare_with_optimizer,
    energy_system_setup, generate_synthetic_inputs, renewable_forecast, run_strategy,
)
from islandos_core.stress_dispatch import (
    STRESS_EVENTS, apply_stress_event, central_signals, forecast_stress_study,
    replay_ro_plan, water_shortage_stress_test,
)
from optimization.energy_system_optimizer import OptimizationError, optimize_battery_and_diesel_schedule
from optimization.milp_dispatch_optimizer import optimize_dispatch_milp


SITE = IslandSiteConfig()


@pytest.fixture(scope="module")
def day():
    return generate_synthetic_inputs(SITE, days=1, seed=3)


def _water_milp(day, case="grid_tou", **kwargs):
    config, water = energy_system_setup(SITE, case)
    return optimize_dispatch_milp(
        _energy_inputs(day, case), config, water_service=water,
        water_demand_m3_per_hour=[float(x) for x in day.water_demand_m3], **kwargs,
    )


def _runs(commitments):
    runs, start = [], 0
    for i in range(1, len(commitments) + 1):
        if i == len(commitments) or commitments[i] != commitments[start]:
            runs.append((commitments[start], start, i))
            start = i
    return runs


class TestJointMilpExtensions:
    def test_terminal_tank_and_ro_minimum_are_respected(self, day):
        ro_min = SITE.ro_min_power_kw / SITE.ro_specific_energy_kwh_per_m3
        result = _water_milp(day, terminal_water_inventory_min_m3=SITE.tank_initial_m3,
                             ro_min_production_m3_per_hour=ro_min)
        assert result["optimality_proven_for_declared_milp"]
        assert result["water_service"]["ending_inventory_m3"] >= SITE.tank_initial_m3 - 1e-6
        for kw in result["water_service"]["ro_power_kw"]:
            assert kw < 1e-6 or kw >= SITE.ro_min_power_kw - 1e-6
        assert result["assumptions"]["terminal_water_inventory_min_m3"] == SITE.tank_initial_m3

    def test_without_terminal_constraint_the_tank_is_drawn_down(self, day):
        free = _water_milp(day)
        held = _water_milp(day, terminal_water_inventory_min_m3=SITE.tank_initial_m3)
        assert free["water_service"]["ending_inventory_m3"] < held["water_service"]["ending_inventory_m3"]
        assert free["dispatch"]["summary"]["estimated_energy_cost"] <= held["dispatch"]["summary"]["estimated_energy_cost"] + 1e-6

    def test_price_aware_baseline_is_reported(self, day):
        result = _water_milp(day, terminal_water_inventory_min_m3=SITE.tank_initial_m3)
        baselines = result["water_policy_baselines"]
        assert set(baselines) == {"just_in_time", "price_aware_lookahead"}
        assert baselines["price_aware_lookahead"]["battery_first"]["feasible"]
        assert result["baseline_comparison"] is baselines["just_in_time"]

    def test_flexible_load_is_conserved_and_shifted_to_cheap_hours(self, day):
        config, _ = energy_system_setup(SITE, "grid_tou")
        available = [True] * day.hours
        result = optimize_dispatch_milp(
            _energy_inputs(day, "grid_tou"), config,
            flexible_load_energy_kwh=40.0, flexible_load_available_steps=available,
            flexible_load_max_power_kw=10.0,
        )
        flex = result["flexible_load"]
        assert sum(flex["power_kw"]) == pytest.approx(40.0, abs=1e-5)
        assert max(flex["power_kw"]) <= 10.0 + 1e-6
        assert result["assumptions"]["flexible_load_jointly_optimized"] is True
        baseline_cost = result["baseline_comparison"]["battery_first"]["summary"]["estimated_energy_cost"]
        assert result["dispatch"]["summary"]["estimated_energy_cost"] <= baseline_cost + 1e-6

    def test_flexible_load_respects_availability(self, day):
        config, _ = energy_system_setup(SITE, "grid_tou")
        available = [6 <= t % 24 < 12 for t in range(day.hours)]
        result = optimize_dispatch_milp(
            _energy_inputs(day, "grid_tou"), config,
            flexible_load_energy_kwh=12.0, flexible_load_available_steps=available,
            flexible_load_max_power_kw=4.0,
        )
        for t, kw in enumerate(result["flexible_load"]["power_kw"]):
            if not available[t]:
                assert kw == pytest.approx(0.0, abs=1e-6)

    def test_flexible_load_parameters_must_come_together(self, day):
        config, _ = energy_system_setup(SITE, "grid_tou")
        with pytest.raises(OptimizationError):
            optimize_dispatch_milp(_energy_inputs(day, "grid_tou"), config, flexible_load_energy_kwh=5.0)

    def test_grid_is_used_before_diesel_on_hybrid_sites(self, day):
        config, _ = energy_system_setup(SITE, "hybrid_tou")
        result = optimize_dispatch_milp(_energy_inputs(day, "hybrid_tou"), config)
        for row in result["dispatch"]["rows"]:
            if float(row["diesel_generation_kw"]) > 1e-6:
                assert float(row["grid_import_kw"]) == pytest.approx(config.grid_import_limit_kw, abs=1e-4)

    def test_failing_just_in_time_baseline_does_not_fail_the_solve(self):
        spiky = apply_stress_event(generate_synthetic_inputs(SITE, days=7, seed=0), "water_demand_spike")
        config, water = energy_system_setup(SITE, "grid_tou")
        result = optimize_dispatch_milp(
            _energy_inputs(spiky, "grid_tou"), config, water_service=water,
            water_demand_m3_per_hour=[float(x) for x in spiky.water_demand_m3],
            terminal_water_inventory_min_m3=SITE.tank_initial_m3,
        )
        jit = result["water_policy_baselines"]["just_in_time"]
        assert jit["battery_first"]["feasible"] is False
        assert "exceeds capacity" in jit["battery_first"]["error"]

    def test_tiny_time_limit_never_claims_optimality(self):
        week = generate_synthetic_inputs(SITE, days=7, seed=0)
        config, water = energy_system_setup(SITE, "grid_tou")
        try:
            result = optimize_dispatch_milp(
                _energy_inputs(week, "grid_tou"), config, water_service=water,
                water_demand_m3_per_hour=[float(x) for x in week.water_demand_m3],
                terminal_water_inventory_min_m3=SITE.tank_initial_m3,
                ro_min_production_m3_per_hour=1.5, time_limit_seconds=0.01,
            )
        except OptimizationError as exc:
            assert "time limit" in str(exc).lower() or "feasible" in str(exc).lower()
        else:
            assert result["solver_status"] != 0
            assert result["optimality_proven_for_declared_milp"] is False


@pytest.fixture(scope="module")
def constrained():
    week = generate_synthetic_inputs(SITE, days=1, seed=0)
    config, _ = energy_system_setup(SITE, "island")
    config = replace(config, diesel=replace(
        config.diesel, ramp_down_kw_per_hour=10.0, min_up_time_hours=3.0, min_down_time_hours=3.0))
    ro = run_strategy("baseline", week, SITE).hourly["ro_power_kw"]
    return _energy_inputs(week, "island", ro), config


class TestEvolutionaryDieselConstraints:
    def test_ramp_down_and_minimum_times_are_no_longer_rejected(self, constrained):
        inputs, config = constrained
        result = optimize_battery_and_diesel_schedule(
            inputs, config, population_size=12, generations=4, seed=5, max_unmet_load_kwh=0.01,
            warm_start_from_rule_dispatch=True,
        )
        assert result["model_scope"]["diesel_ramp_down_and_minimum_up_down_time_enforced"] is True
        commitments = result["recommendation"]["diesel_commitment_schedule"]
        runs = _runs(commitments)
        for state, start, end in runs[:-1]:
            if state:
                assert end - start >= 3
            elif start > 0:
                assert end - start >= 3
        # The recommendation replays cleanly through the shared physics.
        assert result["recommendation"]["dispatch"]["summary"]["unmet_load_kwh"] <= 0.01

    def test_ramp_down_is_respected_before_each_stop(self, constrained):
        inputs, config = constrained
        result = optimize_battery_and_diesel_schedule(
            inputs, config, population_size=12, generations=4, seed=9, max_unmet_load_kwh=0.01,
            warm_start_from_rule_dispatch=True,
        )
        rows = result["recommendation"]["dispatch"]["rows"]
        for prev, cur in zip(rows, rows[1:]):
            drop = float(prev["diesel_generation_kw"]) - float(cur["diesel_generation_kw"])
            assert drop <= 10.0 + 1e-6

    def test_warm_start_is_never_worse_than_the_rule_dispatch(self, constrained):
        inputs, config = constrained
        plain_config = replace(config, diesel=replace(
            config.diesel, ramp_down_kw_per_hour=None, min_up_time_hours=0.0, min_down_time_hours=0.0))
        rule_cost = dispatch_energy_system(inputs, plain_config)["summary"]["estimated_energy_cost"]
        result = optimize_battery_and_diesel_schedule(
            inputs, plain_config, population_size=8, generations=2, seed=1,
            max_unmet_load_kwh=0.01, warm_start_from_rule_dispatch=True,
        )
        cheapest = min(row["objectives"]["estimated_energy_cost"] for row in result["pareto_schedules"])
        assert cheapest <= rule_cost + 1e-6

    def test_default_search_is_unchanged_without_diesel_limits(self, constrained):
        inputs, config = constrained
        plain = replace(config, diesel=replace(
            config.diesel, ramp_down_kw_per_hour=None, min_up_time_hours=0.0, min_down_time_hours=0.0))
        first = optimize_battery_and_diesel_schedule(inputs, plain, population_size=6, generations=2, seed=3)
        second = optimize_battery_and_diesel_schedule(inputs, plain, population_size=6, generations=2, seed=3)
        assert first["recommendation"]["battery_setpoints_kw"] == second["recommendation"]["battery_setpoints_kw"]
        assert first["model_scope"]["diesel_schedule_repair"] == "not needed for this diesel configuration"


class TestRuleStrategies:
    def test_forecast_rule_balances_water(self):
        week = generate_synthetic_inputs(SITE, days=7, seed=1)
        sim = run_strategy("forecast_coordinated", week, SITE)
        h = sim.hourly
        produced, served = h["water_produced_m3"].sum(), h["water_served_m3"].sum()
        assert SITE.tank_initial_m3 + produced - served == pytest.approx(h["tank_m3"][-1], abs=1e-6)
        assert sim.summary["unmet_water_m3"] == pytest.approx(0.0, abs=1e-9)

    def test_minimum_run_time_reduces_ro_starts(self):
        week = generate_synthetic_inputs(SITE, days=7, seed=2)
        loose = run_strategy("coordinated", week, SITE, StrategyRules(ro_min_run_hours=1))
        strict = run_strategy("coordinated", week, SITE, StrategyRules(ro_min_run_hours=4))
        assert strict.summary["ro_starts"] <= loose.summary["ro_starts"]

    def test_minimum_run_time_default_keeps_old_results(self):
        week = generate_synthetic_inputs(SITE, days=7, seed=2)
        a = run_strategy("baseline", week, SITE, StrategyRules())
        b = run_strategy("baseline", week, SITE, StrategyRules(ro_min_run_hours=1))
        assert a.summary == b.summary

    def test_forecast_error_is_seeded(self):
        week = generate_synthetic_inputs(SITE, days=2, seed=4)
        rules = StrategyRules(forecast_error_fraction=0.2)
        assert np.array_equal(renewable_forecast(week, rules), renewable_forecast(week, rules))
        assert not np.array_equal(renewable_forecast(week, rules), week.pv_kw + week.wind_kw)

    def test_invalid_rule_settings_rejected(self):
        week = generate_synthetic_inputs(SITE, days=1, seed=4)
        with pytest.raises(ValueError):
            run_strategy("coordinated", week, SITE, StrategyRules(ro_min_run_hours=0))


class TestCompareWithOptimizer:
    @pytest.mark.parametrize("case", CASES)
    def test_joint_milp_beats_or_matches_fixed_timetable(self, day, case):
        result = compare_with_optimizer(day, SITE, case=case)
        rows = {row["strategy"]: row for row in result["strategies"]}
        assert rows["joint_milp"]["optimality_proven"]
        assert rows["joint_milp"]["headline_tank_adjusted"] <= rows["fixed_timetable"]["headline_tank_adjusted"] + 1e-6
        assert rows["joint_milp_with_reserve"]["ending_tank_m3"] >= SITE.tank_initial_m3 - 1e-6
        assert ("tariff_lookahead" in rows) == (case != "island")
        assert {"forecast_rule", "forecast_rule_realistic"} <= set(rows)

    @pytest.mark.parametrize("case", ("island", "grid_tou"))
    def test_flexible_load_study_orders_strategies(self, day, case):
        from islandos_core.impact_scenario import flexible_load_study
        rows = {r["strategy"]: r for r in flexible_load_study(day, SITE, case=case)["strategies"]}
        rule = rows["rule_dispatch_early_flexible_load"]["energy_cost"]
        battery = rows["milp_battery_only_early_flexible_load"]["energy_cost"]
        joint = rows["milp_joint_flexible_load"]["energy_cost"]
        assert joint <= battery + 1e-6 <= rule + 2e-6
        assert sum(rows["milp_joint_flexible_load"]["flexible_power_kw"]) == pytest.approx(40.0, abs=1e-5)

    def test_unknown_case_rejected(self):
        with pytest.raises(ValueError):
            energy_system_setup(SITE, "moon_base")


class TestStressStudies:
    def test_forecast_stress_study_reports_schedule_changes(self, day):
        study = forecast_stress_study(day, SITE, "grid_tou")
        assert set(study["schedule_change"]) == {"central", "renewable_low_demand_high", "cost_high", "combined_stress"}
        assert study["schedule_change"]["central"]["schedule_changed"] is False
        assert study["probability_status"].startswith("not_assigned")
        outcomes = study["plan_outcomes"]
        assert set(outcomes) == {"central", "combined_stress"}
        # A plan made for the stress case keeps water through every scenario.
        assert all(v["water_shortage_m3"] == pytest.approx(0.0, abs=1e-6) for v in outcomes["combined_stress"].values())

    def test_replay_counts_shortage_when_ro_is_off(self, day):
        signals = central_signals(day, "island")
        replay = replay_ro_plan([0.0] * day.hours, signals, SITE, "island")
        expected = max(0.0, float(day.water_demand_m3.sum()) - SITE.tank_initial_m3)
        assert replay["water_shortage_m3"] == pytest.approx(expected, abs=1e-6)

    def test_stress_events_change_the_right_series(self):
        week = generate_synthetic_inputs(SITE, days=7, seed=0)
        low = apply_stress_event(week, "low_renewable_week")
        assert np.allclose(low.pv_kw, week.pv_kw * 0.4)
        assert np.array_equal(low.water_demand_m3, week.water_demand_m3)
        spike = apply_stress_event(week, "water_demand_spike")
        assert np.allclose(spike.water_demand_m3[48:96], week.water_demand_m3[48:96] * 1.6)
        assert np.array_equal(spike.water_demand_m3[:48], week.water_demand_m3[:48])
        with pytest.raises(ValueError):
            apply_stress_event(week, "meteor")

    def test_water_shortage_stress_test_covers_every_strategy(self):
        week = generate_synthetic_inputs(SITE, days=7, seed=0)
        rows = water_shortage_stress_test(week, SITE, "water_demand_spike", "island")
        names = [row["strategy"] for row in rows]
        assert names == ["fixed_timetable", "surplus_rule", "forecast_rule",
                         "joint_milp_planned_on_normal_forecast",
                         "joint_milp_with_reserve_planned_on_normal_forecast",
                         "joint_milp_event_forecast"]
        by_name = {row["strategy"]: row for row in rows}
        assert by_name["joint_milp_event_forecast"]["water_shortage_m3"] == pytest.approx(0.0, abs=1e-6)
        # A reserve can only reduce the shortage of a plan made on the normal forecast.
        assert (by_name["joint_milp_with_reserve_planned_on_normal_forecast"]["water_shortage_m3"]
                <= by_name["joint_milp_planned_on_normal_forecast"]["water_shortage_m3"] + 1e-6)
        assert set(STRESS_EVENTS) == {"low_renewable_week", "water_demand_spike", "low_renewable_and_spike"}


class TestExperimentRunners:
    def test_benchmark_runner_writes_outputs(self, tmp_path):
        from experiments.run_optimizer_benchmark import main
        assert main(["--input-seeds", "1", "--ea-seeds", "1", "--horizons", "24", "--population", "6",
                     "--generations", "1", "--output-dir", str(tmp_path)]) == 0
        aggregate = json.loads((tmp_path / "aggregate.json").read_text())
        methods = {row["method"] for row in aggregate["aggregate"]}
        assert {"rule", "milp", "ea_cold", "ea_warm"} <= methods
        assert aggregate["timeout_probe"]["optimality_proven"] is False
        milp_rows = [row for row in aggregate["aggregate"] if row["method"] == "milp"]
        assert all(row["mean_gap_vs_milp_pct"] == 0 for row in milp_rows)
        assert (tmp_path / "summary.md").exists() and (tmp_path / "runs.csv").exists()

    def test_impact_runner_writes_outputs(self, tmp_path):
        from experiments.run_optimizer_impact import main
        results = main(["--seeds", "1", "--days", "1", "--output-dir", str(tmp_path)])
        assert set(CASES) <= set(results)
        assert results["grid_tou"]["_joint_milp_all_optimal"] is True
        assert "unmet_water_m3_total" in results["island"]["joint_milp"]
        assert (tmp_path / "summary.md").read_text().count("## ") == len(CASES) + 1
        assert set(results["flexible_load"]) == {"island/daytime_06_22", "island/any_hour", "grid_tou/daytime_06_22", "grid_tou/any_hour"}

    def test_stress_runner_writes_outputs(self, tmp_path):
        from experiments.run_stress_tests import main
        assert main(["--seeds", "1", "--output-dir", str(tmp_path)]) == 0
        text = (tmp_path / "summary.md").read_text()
        assert "Water-shortage stress events" in text
        assert (tmp_path / "water_shortage_runs.csv").exists()
