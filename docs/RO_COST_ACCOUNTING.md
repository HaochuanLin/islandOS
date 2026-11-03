# RO 运行成本核算

本模块用于在同一时间范围内核算一份 RO 生产计划的运行成本，并比较基线计划与候选计划。它是 IslandOS 经济核算的基础组件，不代表已经获得任何水厂的实测节省。

## 成本边界

纳入：
- 分时电费：逐时电量 × 对应时段电价；
- 药剂成本：产水量 × 单位药剂成本；
- 可变运维：产水量 × 单位可变运维成本；
- 维护成本：运行小时 × 每运行小时维护成本；
- 启停成本：启停事件数 × 单次启停成本；
- 固定运维：按本次数据覆盖小时数占年度分摊小时数的比例分摊。

不纳入调度目标：
- 已经发生、无法因本次排产改变的沉没设备 CAPEX；
- 未经客户确认的税费、融资、折旧、替换投资和机会成本。

若进行新建项目或扩建设计评估，CAPEX 应另行进入生命周期/投资模型，不能混入既有设备的短期排产比较。

## 使用方式

```python
from ro_costing import ROCostRates, calculate_ro_operating_cost, compare_ro_operating_plans

rates = ROCostRates(
    currency="CNY",
    electricity_price_per_kwh=0.65,  # replace with customer tariff
    chemical_cost_per_m3=0.10,       # replace with verified site value
)
baseline = calculate_ro_operating_cost(
    energy_kwh=[100, 110],
    water_m3=[25, 27],
    electricity_price_per_kwh=[0.3, 0.8],
    rates=rates,
    provenance="measured",
)
```

示例数字仅展示接口用法，不是默认站点参数。真实项目必须记录数据来源、币种、单位、时间范围和缺失项。没有运行小时或启停记录时，不应猜测维护和启停成本；没有水质、储水状态和设备约束审查时，成本差额也不能直接视为可实现节省。

## 验收边界

- 所有序列必须逐时对齐、有限且非负；
- 电价可为单一电价或逐时分时电价；
- 产水量为零时，单位水成本返回 null；
- 比较结果同时报告产水量变化，不只展示节省百分比；
- 结果保留 provenance 标签；synthetic/modelled 不得标成 measured。
