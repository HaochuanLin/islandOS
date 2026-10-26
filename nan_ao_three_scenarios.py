#!/usr/bin/env python3
# 重要说明
# nan_ao_three_scenarios.py 是全新的探索对比仿真脚本
# 不会改动冻结基线文件 nan_ao_scenario.py（seed=20261021）
# 情景1输出应当贴近原脚本中位数约443 m³/年，用来做一致性校验
# 情景2、3为补充探索分析，不属于提交评审的基线方案
# 情景3新增简易水库状态机，原始基线模型没有该模块
"""Nan'ao RO three-scenario Monte Carlo comparison.

This is an assumption-driven screening model, not a measured-site forecast.
It deliberately imports no functions from nan_ao_scenario.py and never writes
to that frozen baseline file. The baseline event draws below mirror its current
random draw order and distributions so scenario 1 can be checked for parity.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from statistics import median
from typing import Any

DEFAULT_SEED = 20261021
DEFAULT_RUNS = 1000
YEAR_HOURS = 365 * 24

RO_POWER_KW = 50.0
SEC_KWH_PER_M3 = 4.0
RO_AVAILABILITY = 0.925
CAPEX_LOW_RMB = 1_600_000.0
CAPEX_HIGH_RMB = 3_300_000.0
AMORTIZATION_YEARS = 10.0
VALLEY_PRICE_RMB_PER_KWH = 0.272
VALLEY_HOURS = 8  # local hour 00:00–07:59; no peak/flat-period operation
RESERVOIR_CAPACITY_M3 = 100.0
RESERVOIR_EMERGENCY_THRESHOLD_M3 = 25.0
RESERVOIR_RECOVERY_TARGET_M3 = 75.0  # hysteresis target: continue valley run until this level
RESERVOIR_INITIAL_M3 = 50.0
ASSUMED_WATER_DEMAND_M3_PER_DAY = 80.0

SCENARIO_NAMES = {
    "wind_only": "情景1：仅弃风（项目基线）",
    "valley_only": "情景2：仅谷电（定时器参考组）",
    "hybrid": "情景3：弃风+条件谷电混合模式（IslandOS探索）",
}


def triangular_integer(rng: random.Random, low: int, high: int, mode: int) -> int:
    """Keep the exact integer event-count transform used by the frozen baseline."""
    return max(0, int(round(rng.triangular(low, high, mode))))


def percentile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolated percentile, matching nan_ao_scenario.py."""
    if not sorted_values:
        raise ValueError("values must not be empty")
    position = (len(sorted_values) - 1) * p
    lo = math.floor(position)
    hi = math.ceil(position)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] * (hi - position) + sorted_values[hi] * (position - lo)


def _draw_annual_events(rng: random.Random, run_id: int) -> dict[str, Any]:
    """Mirror the frozen baseline's random draws, distributions, and draw order."""
    event_count = triangular_integer(rng, 4, 12, 8)
    events: list[dict[str, float]] = []
    total_hours = 0.0
    total_energy_kwh = 0.0
    for _ in range(event_count):
        duration_h = min(24.0, max(2.0, rng.lognormvariate(math.log(8.0), 0.5)))
        available_kw = rng.triangular(5.0, 50.0, 25.0)
        event_availability = rng.uniform(0.85, 1.0)
        usable_kw = min(available_kw, RO_POWER_KW)
        total_hours += duration_h
        total_energy_kwh += duration_h * usable_kw * event_availability
        events.append({
            "duration_h": duration_h,
            "available_surplus_kw": available_kw,
            "event_availability": event_availability,
        })
    # Match the baseline's per-run rounding before percentile calculations.
    return {
        "run_id": run_id,
        "events": events,
        "event_count": event_count,
        "baseline_event_hours": total_hours,
        "wind_energy_kwh": total_energy_kwh,
        "wind_water_m3": round(total_energy_kwh / SEC_KWH_PER_M3, 3),
        "wind_effective_runtime_h": sum(
            event["duration_h"] * event["event_availability"] for event in events
        ),
    }


def _schedule_events_without_overlap(
    annual: dict[str, Any], rng: random.Random
) -> list[dict[str, float]]:
    """Assign illustrative integer-hour start times without overlapping events.

    Timing is not present in the original annual event-energy abstraction. These
    synthetic start times are used only to exercise the hybrid reservoir state
    machine; scenario 1's annual energy is calculated directly from baseline
    draws and is not affected by this schedule.
    """
    scheduled: list[dict[str, float]] = []
    occupied: set[int] = set()
    for event in annual["events"]:
        duration = float(event["duration_h"])
        span = max(1, math.ceil(duration))
        chosen_start = None
        for _ in range(20_000):
            start = rng.randrange(0, YEAR_HOURS - span + 1)
            slots = range(start, start + span)
            if all(slot not in occupied for slot in slots):
                chosen_start = start
                occupied.update(slots)
                break
        if chosen_start is None:
            raise RuntimeError("could not place non-overlapping synthetic wind events")
        scheduled.append({**event, "start_hour": float(chosen_start)})
    return scheduled


def _simulate_hybrid(annual: dict[str, Any], scheduled_events: list[dict[str, float]]) -> dict[str, float]:
    """Run a simple reservoir state machine with hourly demand and event priority.

    Within an hour containing any part of a curtailment event, the model treats
    that hour as a wind-event hour and does not mix in grid power. This is a
    conservative hourly-resolution simplification for the final fractional hour
    of an event. The emergency state latches after inventory falls below the
    threshold and remains active until inventory reaches the 75 m³ recovery
    target. Grid RO can run only from 00:00 through 07:59 while that state is
    active, preventing repeated one-hour pulses from under-replenishing storage.
    """
    event_by_hour: dict[int, dict[str, float]] = {}
    for event in scheduled_events:
        start = int(event["start_hour"])
        end = start + float(event["duration_h"])
        for hour in range(start, min(YEAR_HOURS, math.ceil(end))):
            event_by_hour[hour] = event

    inventory = RESERVOIR_INITIAL_M3
    water_produced_m3 = 0.0
    wind_water_m3 = 0.0
    valley_water_m3 = 0.0
    valley_energy_kwh = 0.0
    effective_runtime_h = 0.0
    water_served_m3 = 0.0
    unmet_demand_m3 = 0.0
    spilled_water_m3 = 0.0
    emergency_replenishment_active = False
    demand_per_hour = ASSUMED_WATER_DEMAND_M3_PER_DAY / 24.0

    for hour in range(YEAR_HOURS):
        served = min(inventory, demand_per_hour)
        inventory -= served
        water_served_m3 += served
        unmet_demand_m3 += demand_per_hour - served

        if inventory < RESERVOIR_EMERGENCY_THRESHOLD_M3:
            emergency_replenishment_active = True
        elif inventory >= RESERVOIR_RECOVERY_TARGET_M3:
            emergency_replenishment_active = False

        event = event_by_hour.get(hour)
        if event is not None:
            start = int(event["start_hour"])
            event_fraction = min(1.0, max(0.0, start + event["duration_h"] - hour))
            event_water = (
                event["available_surplus_kw"]
                * event["event_availability"]
                * event_fraction
                / SEC_KWH_PER_M3
            )
            wind_water_m3 += event_water
            water_produced_m3 += event_water
            effective_runtime_h += event_fraction * event["event_availability"]
            stored = min(event_water, max(0.0, RESERVOIR_CAPACITY_M3 - inventory))
            inventory += stored
            spilled_water_m3 += event_water - stored
            if inventory >= RESERVOIR_RECOVERY_TARGET_M3:
                emergency_replenishment_active = False
            continue

        hour_of_day = hour % 24
        if hour_of_day < VALLEY_HOURS and emergency_replenishment_active:
            grid_runtime = RO_AVAILABILITY
            grid_energy = RO_POWER_KW * grid_runtime
            grid_water = grid_energy / SEC_KWH_PER_M3
            valley_energy_kwh += grid_energy
            valley_water_m3 += grid_water
            water_produced_m3 += grid_water
            effective_runtime_h += grid_runtime
            stored = min(grid_water, max(0.0, RESERVOIR_CAPACITY_M3 - inventory))
            inventory += stored
            spilled_water_m3 += grid_water - stored
            if inventory >= RESERVOIR_RECOVERY_TARGET_M3:
                emergency_replenishment_active = False

    return {
        "annual_water_m3": water_produced_m3,
        "wind_water_m3": wind_water_m3,
        "valley_water_m3": valley_water_m3,
        "valley_energy_kwh": valley_energy_kwh,
        "effective_runtime_h": effective_runtime_h,
        "water_served_m3": water_served_m3,
        "unmet_demand_m3": unmet_demand_m3,
        "spilled_water_m3": spilled_water_m3,
        "ending_inventory_m3": inventory,
    }


def _summarize(
    scenario_key: str,
    annual_water: list[float],
    runtime_hours: list[float],
    electricity_cost_per_m3: list[float],
) -> dict[str, Any]:
    water_sorted = sorted(annual_water)
    runtime_sorted = sorted(runtime_hours)
    electricity_sorted = sorted(electricity_cost_per_m3)
    p5 = percentile(water_sorted, 0.05)
    p50 = percentile(water_sorted, 0.50)
    p95 = percentile(water_sorted, 0.95)
    hardware_low = CAPEX_LOW_RMB / AMORTIZATION_YEARS / p50
    hardware_high = CAPEX_HIGH_RMB / AMORTIZATION_YEARS / p50
    electricity_median = median(electricity_sorted)
    return {
        "scenario_key": scenario_key,
        "scenario_name": SCENARIO_NAMES[scenario_key],
        "annual_water_p5_m3": p5,
        "annual_water_p50_m3": p50,
        "annual_water_p95_m3": p95,
        "runtime_hours_p50": percentile(runtime_sorted, 0.50),
        "hardware_amortization_low_rmb_per_m3": hardware_low,
        "hardware_amortization_high_rmb_per_m3": hardware_high,
        "electricity_cost_median_rmb_per_m3": electricity_median,
        "screening_cost_low_rmb_per_m3": hardware_low + electricity_median,
        "screening_cost_high_rmb_per_m3": hardware_high + electricity_median,
    }


def run_three_scenarios(runs: int = DEFAULT_RUNS, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    if isinstance(runs, bool) or not isinstance(runs, int) or runs != DEFAULT_RUNS:
        raise ValueError("runs must be exactly 1000 to preserve the requested comparison setup")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed != DEFAULT_SEED:
        raise ValueError("seed must be exactly 20261021 for baseline parity")

    # One shared master RNG first draws every annual event exactly as the frozen
    # baseline does. Only after all baseline-equivalent draws are complete do we
    # consume more random values for illustrative event timing. This preserves
    # the original 1,000-run scenario-1 sequence byte-for-byte at the value level.
    master_rng = random.Random(seed)
    annual_cases = [_draw_annual_events(master_rng, run_id + 1) for run_id in range(runs)]
    timing_rng = master_rng
    scheduled_cases = [
        _schedule_events_without_overlap(annual, timing_rng) for annual in annual_cases
    ]

    baseline_water = [float(case["wind_water_m3"]) for case in annual_cases]
    baseline_runtime = [float(case["wind_effective_runtime_h"]) for case in annual_cases]
    baseline_cost = [0.0 for _ in annual_cases]

    valley_run_hours = YEAR_HOURS / 24 * VALLEY_HOURS * RO_AVAILABILITY
    valley_water_per_year = valley_run_hours * RO_POWER_KW / SEC_KWH_PER_M3
    valley_energy_per_year = valley_run_hours * RO_POWER_KW
    valley_cost_per_m3 = (
        valley_energy_per_year * VALLEY_PRICE_RMB_PER_KWH / valley_water_per_year
    )
    valley_water = [valley_water_per_year for _ in annual_cases]
    valley_runtime = [valley_run_hours for _ in annual_cases]
    valley_cost = [valley_cost_per_m3 for _ in annual_cases]

    hybrid_runs = [
        _simulate_hybrid(annual, scheduled)
        for annual, scheduled in zip(annual_cases, scheduled_cases)
    ]
    hybrid_water = [float(result["annual_water_m3"]) for result in hybrid_runs]
    hybrid_runtime = [float(result["effective_runtime_h"]) for result in hybrid_runs]
    hybrid_cost = [
        (
            result["valley_energy_kwh"] * VALLEY_PRICE_RMB_PER_KWH
            / result["annual_water_m3"]
            if result["annual_water_m3"] > 0
            else 0.0
        )
        for result in hybrid_runs
    ]

    summaries = [
        _summarize("wind_only", baseline_water, baseline_runtime, baseline_cost),
        _summarize("valley_only", valley_water, valley_runtime, valley_cost),
        _summarize("hybrid", hybrid_water, hybrid_runtime, hybrid_cost),
    ]
    baseline_median = summaries[0]["annual_water_p50_m3"]
    assert abs(baseline_median - 443.0) <= 5.0, (
        "Scenario 1 parity check failed: expected median close to 443 m³/year, "
        f"got {baseline_median:.3f}. Do not alter nan_ao_scenario.py to force a match."
    )

    return {
        "title": "Nan'ao RO three-scenario Monte Carlo screening comparison",
        "seed": seed,
        "runs": runs,
        "scenarios": summaries,
        "scenario1_baseline_parity": {
            "expected_median_m3_per_year_approx": 443.0,
            "actual_median_m3_per_year": baseline_median,
            "tolerance_m3_per_year": 5.0,
            "passed": True,
            "method": "same Python random seed, same event distributions, same draw order, and same per-run yield rounding as nan_ao_scenario.py",
        },
        "hybrid_diagnostics": {
            "assumed_reservoir_capacity_m3": RESERVOIR_CAPACITY_M3,
            "assumed_emergency_threshold_m3": RESERVOIR_EMERGENCY_THRESHOLD_M3,
            "assumed_recovery_target_m3": RESERVOIR_RECOVERY_TARGET_M3,
            "assumed_initial_inventory_m3": RESERVOIR_INITIAL_M3,
            "assumed_water_demand_m3_per_day": ASSUMED_WATER_DEMAND_M3_PER_DAY,
            "median_water_served_m3_per_year": median([item["water_served_m3"] for item in hybrid_runs]),
            "median_unmet_demand_m3_per_year": median([item["unmet_demand_m3"] for item in hybrid_runs]),
            "median_spilled_water_m3_per_year": median([item["spilled_water_m3"] for item in hybrid_runs]),
            "median_ending_inventory_m3": median([item["ending_inventory_m3"] for item in hybrid_runs]),
            "median_valley_energy_kwh_per_year": median([item["valley_energy_kwh"] for item in hybrid_runs]),
            "median_wind_water_m3_per_year": median([item["wind_water_m3"] for item in hybrid_runs]),
            "median_valley_water_m3_per_year": median([item["valley_water_m3"] for item in hybrid_runs]),
        },
        "assumptions": {
            "ro_power_kw": RO_POWER_KW,
            "specific_energy_kwh_per_m3": SEC_KWH_PER_M3,
            "ro_availability_for_valley_and_hybrid_grid_runs": RO_AVAILABILITY,
            "capex_low_rmb": CAPEX_LOW_RMB,
            "capex_high_rmb": CAPEX_HIGH_RMB,
            "amortization_years": AMORTIZATION_YEARS,
            "valley_price_rmb_per_kwh": VALLEY_PRICE_RMB_PER_KWH,
            "valley_period_local_hour": "00:00–07:59",
            "hybrid_reservoir_capacity_m3": RESERVOIR_CAPACITY_M3,
            "hybrid_emergency_threshold_m3": RESERVOIR_EMERGENCY_THRESHOLD_M3,
            "hybrid_recovery_target_m3": RESERVOIR_RECOVERY_TARGET_M3,
            "hybrid_initial_inventory_m3": RESERVOIR_INITIAL_M3,
            "hybrid_assumed_water_demand_m3_per_day": ASSUMED_WATER_DEMAND_M3_PER_DAY,
            "synthetic_event_start_time_assumption": "uniform integer-hour placement over a 365-day year, without event overlap; timing is not in the frozen baseline",
            "scenario2_annual_valley_operation": "2920 scheduled hours/year multiplied by 0.925 availability; expected runtime 2701 hours/year",
            "scenario3_energy_costing": "grid electricity charged only for conditional valley operation; modeled curtailment energy cost is zero",
            "cost_denominator": "total simulated RO production, including any water spilled from the reservoir; not delivered/served water",
        },
        "calculation_scope_and_limits": [
            "This screening calculation includes hardware amortization plus purchased-electricity charges only.",
            "Excluded: civil works, seawater intake/outfall, brine disposal, membrane and chemical O&M, demand charges, and equipment end-of-life/disposal cost.",
            "This is a screening estimate only, not a full life-cycle water cost and not an actual water selling price.",
            "Scenario 2 and scenario 3 are exploratory extensions, not the original pilot-review baseline.",
            "Scenario 1 uses the frozen baseline's event-energy abstraction and does not model event timestamps.",
            "Scenario 2 and scenario 3 are simplified models; no measured Nan'ao data or validated reservoir demand profile was supplied.",
            "Scenario 3's reservoir capacity, emergency threshold, 75 m³ recovery target, initial inventory, and 80 m³/day demand are illustrative assumptions because no site reservoir/demand data was supplied.",
            "Water production percentiles describe assumptions only, not measured performance or a validated forecast.",
        ],
    }


def _rmb(value: float) -> str:
    return f"{value:,.2f}"


def render_markdown_table(report: dict[str, Any]) -> str:
    lines = [
        "| 情景名称 | 年产水量P5 (m³/年) | 年产水量中位数 (m³/年) | 年产水量P95 (m³/年) | 年运行小时中位数 (h) | 硬件摊销区间 (元/m³) | 中位数电费 (元/m³) | 合计筛查成本区间 (元/m³) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["scenarios"]:
        lines.append(
            "| {name} | {p5:,.1f} | {p50:,.1f} | {p95:,.1f} | {hours:,.1f} | {capex_low}–{capex_high} | {electricity} | {total_low}–{total_high} |".format(
                name=item["scenario_name"],
                p5=item["annual_water_p5_m3"],
                p50=item["annual_water_p50_m3"],
                p95=item["annual_water_p95_m3"],
                hours=item["runtime_hours_p50"],
                capex_low=_rmb(item["hardware_amortization_low_rmb_per_m3"]),
                capex_high=_rmb(item["hardware_amortization_high_rmb_per_m3"]),
                electricity=_rmb(item["electricity_cost_median_rmb_per_m3"]),
                total_low=_rmb(item["screening_cost_low_rmb_per_m3"]),
                total_high=_rmb(item["screening_cost_high_rmb_per_m3"]),
            )
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args(argv)
    report = run_three_scenarios()
    print(render_markdown_table(report))
    print()
    print("口径限制：仅包含硬件摊销 + 购电电费；不含土建、海水取排水、浓盐水处置、膜与药剂运维、需量电费、设备报废成本。")
    print("本结果仅为筛查测算值，不是全生命周期水成本，不等于实际售水价格。情景2、3为探索拓展分析，不属于原始试点评审基线。")
    print(
        "情景3水库假设：容量 100 m³、应急阈值 25 m³、恢复目标 75 m³、初始库存 50 m³、日需求 80 m³；"
        "这些参数不是实测数据。成本分母为RO总产水量，包含可能的水库溢流。"
    )
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(f"JSON 详细报告：{args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
