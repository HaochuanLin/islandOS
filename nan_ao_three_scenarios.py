#!/usr/bin/env python3
# Important
# nan_ao_three_scenarios.py is post-hoc economic screening script ONLY.
# Physical water-yield Monte-Carlo is from nan_ao_scenario.py seed=20261021, UNCHANGED.
# Scenario-1 is judging baseline (new-procurement RO).
# Scenario2-4 are hypothetical exploratory cases. Scenario-4 requires purchasing valley-hour grid-power and is NOT part of July-03 submission pilot scope.
# Assumption for scenario2-4: RO hardware & land treated as sunk-cost, no capital charge.
# Scenario-4 assumption: all curtailment events occur outside valley-hour windows, no time-overlap. Real-world occasional overlap may exist.
"""Post-hoc financial screening for four Nan'ao RO operating scenarios.

This script does not import, execute, or modify nan_ao_scenario.py. It reuses
only the frozen physical-yield summary values supplied for this screening:
P5=237.6, median=442.7, P95=693.2 m³/year.

All costs are assumption-based screening estimates, not measured site results.
Run: python nan_ao_three_scenarios.py
"""
from __future__ import annotations

from dataclasses import dataclass

# Frozen physical simulation summary; do not rerun Monte Carlo here.
WATER_P5_M3_YEAR = 237.6
WATER_MEDIAN_M3_YEAR = 442.7
WATER_P95_M3_YEAR = 693.2

RO_SEC_KWH_PER_M3 = 4.0
VALLEY_PRICE_RMB_PER_KWH = 0.272
ANNUAL_OPEX_LOW_RMB = 8_000.0
ANNUAL_OPEX_HIGH_RMB = 18_000.0
RO_CAPEX_LOW_RMB = 1_600_000.0
RO_CAPEX_HIGH_RMB = 3_300_000.0
CAPEX_AMORTIZATION_YEARS = 10
VALLEY_HOURS_PER_DAY_MAX = 8
RO_AVAILABILITY = 0.925
SCENARIO_3_VALLEY_WATER_M3_YEAR = 33_650.0


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    annual_water_m3: float
    capital_included: str
    opex_per_m3: tuple[float, float]
    electricity_per_m3: tuple[float, float]
    total_per_m3: tuple[float, float]


def _range(low: float, high: float) -> tuple[float, float]:
    return (min(low, high), max(low, high))


def _fmt(value: float) -> str:
    return f"{value:,.2f}"


def _fmt_range(values: tuple[float, float]) -> str:
    return f"{_fmt(values[0])}–{_fmt(values[1])}"


def build_scenarios() -> list[Scenario]:
    # Baseline comparisons use the stated median annual yield as the common
    # denominator. P5/P95 are shown in the explanation as physical uncertainty,
    # not silently mixed into the cost range.
    baseline_water = WATER_MEDIAN_M3_YEAR
    s1_capital_per_year = (
        RO_CAPEX_LOW_RMB / CAPEX_AMORTIZATION_YEARS,
        RO_CAPEX_HIGH_RMB / CAPEX_AMORTIZATION_YEARS,
    )
    s1_opex = _range(
        ANNUAL_OPEX_LOW_RMB / baseline_water,
        ANNUAL_OPEX_HIGH_RMB / baseline_water,
    )
    s1_capital = _range(
        s1_capital_per_year[0] / baseline_water,
        s1_capital_per_year[1] / baseline_water,
    )
    s1_total = (
        s1_capital[0] + s1_opex[0],
        s1_capital[1] + s1_opex[1],
    )

    # S2: sunk RO/land, curtailment-only; no purchased electricity.
    s2_opex = _range(
        ANNUAL_OPEX_LOW_RMB / baseline_water,
        ANNUAL_OPEX_HIGH_RMB / baseline_water,
    )

    # S3: timer-only, 0–8 scheduled valley hours/day, 92.5% availability.
    # The user-specified annual production of 33,650 m³ is authoritative for
    # this financial screen; hours/availability are recorded as assumptions.
    s3_water = SCENARIO_3_VALLEY_WATER_M3_YEAR
    s3_opex = _range(
        ANNUAL_OPEX_LOW_RMB / s3_water,
        ANNUAL_OPEX_HIGH_RMB / s3_water,
    )
    s3_electricity = RO_SEC_KWH_PER_M3 * VALLEY_PRICE_RMB_PER_KWH
    s3_total = (
        s3_opex[0] + s3_electricity,
        s3_opex[1] + s3_electricity,
    )

    # S4: hypothetical disjoint windows. Add timer-based valley production to
    # each supplied physical curtailment-yield percentile. Electricity is paid
    # only for the valley-produced water; fixed O&M is spread over total water.
    s4_water_low = s3_water + WATER_P5_M3_YEAR
    s4_water_high = s3_water + WATER_P95_M3_YEAR
    s4_water_mid = s3_water + WATER_MEDIAN_M3_YEAR
    s4_opex = _range(
        ANNUAL_OPEX_LOW_RMB / s4_water_high,
        ANNUAL_OPEX_HIGH_RMB / s4_water_low,
    )
    s4_electricity = (
        s3_water * RO_SEC_KWH_PER_M3 * VALLEY_PRICE_RMB_PER_KWH / s4_water_high,
        s3_water * RO_SEC_KWH_PER_M3 * VALLEY_PRICE_RMB_PER_KWH / s4_water_low,
    )
    s4_total = (
        s4_opex[0] + s4_electricity[0],
        s4_opex[1] + s4_electricity[1],
    )

    return [
        Scenario(
            "Judgement Baseline",
            "新采购50 kW RO；仅弃风运行；RO资本按10年直线摊销；电费为0",
            baseline_water,
            "是（1.6–3.3百万元，10年摊销）",
            s1_opex,
            (0.0, 0.0),
            s1_total,
        ),
        Scenario(
            "Hypothetical-A",
            "RO与土地视为沉没资产；仅弃风运行；固定年度运维；电费为0",
            baseline_water,
            "否（沉没资产）",
            s2_opex,
            (0.0, 0.0),
            s2_opex,
        ),
        Scenario(
            "Hypothetical-B",
            "RO与土地不计资本；谷电定时器0–8 h/day、可用率92.5%；年产水按指定33,650 m³",
            s3_water,
            "否（沉没资产）",
            s3_opex,
            (s3_electricity, s3_electricity),
            s3_total,
        ),
        Scenario(
            "Hypothetical-C (IslandOS)",
            "弃风窗口与谷电窗口完全不重叠；同时利用两套窗口；谷电产水33,650 m³/年，另加弃风产水",
            s4_water_mid,
            "否（沉没资产）",
            s4_opex,
            s4_electricity,
            s4_total,
        ),
    ]


def render_markdown_table(scenarios: list[Scenario]) -> str:
    lines = [
        "| 情景名称 | 说明 | 年产水量(m³) | RO资本是否计入 | 运维分摊(RMB/m³) | 电费(RMB/m³) | 合计筛查成本(RMB/m³) |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for s in scenarios:
        water = f"{s.annual_water_m3:,.1f}"
        lines.append(
            f"| {s.name} | {s.description} | {water} | {s.capital_included} "
            f"| {_fmt_range(s.opex_per_m3)} | {_fmt_range(s.electricity_per_m3)} "
            f"| {_fmt_range(s.total_per_m3)} |"
        )
    return "\n".join(lines)


def main() -> int:
    scenarios = build_scenarios()
    print("# Nan'ao 四组后处理财务筛查")
    print()
    print(render_markdown_table(scenarios))
    print()
    print("## 外部应急供水对标（用户提供的参考区间，未经本脚本独立核验）")
    print("- 运水船：20–35 RMB/m³（灾后，受台风海况限制）")
    print("- 瓶装矿泉水：2,000–4,000 RMB/m³（灾后，物流受天气制约）")
    print("- IslandOS混合模式定位为灾前预储备；预先储水可降低灾后对海况和即时物流的依赖，但实际保障能力取决于储水规模与运行条件。")
    print()
    print("## 口径与重要限制")
    print(
        f"- 复用的物理产水统计：P5={WATER_P5_M3_YEAR:.1f}、"
        f"median={WATER_MEDIAN_M3_YEAR:.1f}、P95={WATER_P95_M3_YEAR:.1f} m³/year；"
        "本脚本不运行蒙特卡洛。"
    )
    print("- 情景1–2单位成本使用中位数产水量442.7 m³/year作共同分母；因此它们是中位数产量下的筛查值，不是P5/P95成本区间。")
    print("- 固定运维按年度固定金额计算后除以年度总产水量，不按产量线性增加。")
    print("- 情景3按指定年产水量33,650 m³/year计算。其SEC×电价为1.088 RMB/m³，另加年度固定运维分摊。")
    print("- 情景4按不重叠假设，将谷电产水与弃风产水相加；电费仅计谷电产水对应电量，固定运维分摊到总产水量。真实现场可能偶有时间重叠。")
    print("- 情景4年产水量表格显示为谷电产水+弃风产水中位数；成本范围则使用弃风产水P5至P95估算。")
    print("- 情景2–4均是假设性探索情景；情景4需要购买谷电，不属于7月3日提交试点范围。")
    print("- 未计入RO资本的情景仍可能存在膜更换、药剂、土建、取排水、浓盐水处理、需量电费等其他成本；这些不在本表筛查口径内。")
    print()
    print("注：输出表格可复制进docs/COST_TRADEOFFS.md、PPT、Word。本脚本不改动原始物理仿真。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
