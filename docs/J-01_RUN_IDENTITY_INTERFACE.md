# J-01 纯函数接口设计与固定测试向量

- 状态：**P1a 输入组已实现；`derive_run_id` 仍为设计，未实现。**
- 基线：`main = 2d24b1f`；P1a 分支：`feat/j01-input-group-identity-2026-11-25`。
- 关联：`docs/J-01_RUN_IDENTITY_DECISION.md`、`docs/fixtures/j01_run_identity_vectors.json`。

## 1. 边界

- P1a 无 I/O、无数据库、无 Streamlit、无 `session_state`、无环境变量、无全局状态。
- 不读系统时钟、不用随机数、不解析 CSV、不推断缺失信号。
- 只做：校验 → canonical JSON → SHA-256 → 冻结对象。
- `derive_run_id` 本轮不写代码；其签名、D5 字段和兼容规则只作为后续设计。

## 2. 规范信号名与页面适配

| Page 05 展示名 | Page 06 / canonical 名 | 进入组 | 单位 |
| --- | --- | --- | --- |
| `pv_power` | `pv_power_kw` | 是 | `kW` |
| `wind_power` | `wind_power_kw` | 是 | `kW` |
| `essential_load` | `load_kw` | 是 | `kW` |
| `electricity_price` | `tariff_per_kwh` | 是 | 归一为 `currency/kWh` |

适配层只接受别名/物理名，不按名称猜语义；未知名、额外名、重复名一律拒绝。

## 3. 返回对象

P1a 实际实现：

```python
@dataclass(frozen=True)
class InputGroupIdentity:
    input_group_id: str
    input_group_sha256: str
    history_sha256: str
    units_sha256: str
    hour_count: int
    schema_version: int = 1
```

后续 `derive_run_id` 设计（未实现）：

```python
@dataclass(frozen=True)
class RunIdentity:
    run_id: str
    run_identity_sha256: str
    identity_schema_version: int
    page: str
    input_group: InputGroupIdentity | None
```

## 4. P1a 函数签名

```python
def canonical_signal_name(name: str) -> str: ...
def canonicalize_history_signals(
    signals: Mapping[str, Sequence[float]],
) -> dict[str, list[float]]: ...
def canonicalize_units(units: Mapping[str, str]) -> dict[str, str]: ...

def derive_input_group_id(
    *,
    timestamps: Sequence[datetime],
    signals: Mapping[str, Sequence[float]],
    units: Mapping[str, str],
) -> InputGroupIdentity: ...
```

不接收 `hour_count` 或 `history_sha256` 作为参数：前者由时间戳长度推出，后者由函数内部计算，避免调用方传入不一致值。

## 5. 校验与规范化规则

### 5.1 时间轴

- `timestamps` 非空，元素必须是 tz-aware `datetime`。
- 先 `astimezone(timezone.utc)`，再排序。
- 重复时间戳（UTC 后相同）拒绝，避免同一时刻多行排序歧义。
- 行顺序不影响组；等价时区偏移得到同一组。

### 5.2 信号

- 规范化后必须恰好含四个 canonical 名；不能多、不能少。
- 别名和 canonical 名混用且重复时拒绝。
- 每个序列非空；值只能是有限 `int/float`；拒绝 `bool`、`NaN`、`inf`、字符串、`None`。
- 四个序列长度一致，且等于 `len(timestamps)`。

### 5.3 单位

- 规范化后必须恰好含四个 canonical 名；单位非空。
- `tariff_per_kwh` 的 `USD/kWh`、`CNY/kWh`、`GBP/kWh`、`EUR/kWh` 等三字母币种 + `/kWh` 归一为 `currency/kWh`。
- 非 `kWh` 计价单位（如 `USD/MWh`）不被换算，作为不同物理单位进入组摘要。
- kW 信号保留原字符串，`kW` 与 `kw` 不互相归一；大小写差异视为不同单位。

### 5.4 数值序列化

- 复用 `canonical_history_sha256`：每个信号 `round(float(value), 6)`，负零归一为零。
- canonical JSON：`sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False`。
- 不填充空值、不插值、不重采样。

## 6. 算法与域分隔

```
H = canonical_history_sha256(utc_sorted(timestamps), pv, wind, load, tariff)
units_sha256 = sha256(canonical_json({四个 canonical 名: 归一单位}))
input_group_sha256 = sha256(canonical_json({
    "schema": "islandos-input-group-v1",
    "history_sha256": H,
    "units_sha256": units_sha256,
    "hour_count": N,
}))
input_group_id = "ig-" + input_group_sha256[:16]
```

- `schema` 是域分隔，未来算法变化必须改 schema 并升 `identity_schema_version`，不得静默改公式。
- 组摘要不含 page、site digest、`page_inputs`、币种、投资参数。

## 7. `derive_run_id` 设计（D5，未实现）

D5 使用稳定模型策略身份，不要求 forecast 前拿到实际 selected model IDs：

```
run_identity_sha256 = sha256(canonical_json({
  "schema": "islandos-run-identity-v2",
  "identity_schema_version": 1,
  "page": page,
  "input_group_sha256": ... | null,
  "site_configuration_sha256": ...,
  "page_settings": {...},
  "page_inputs_sha256": ...,
  "run_settings": {...},
  "forecast_settings": {...},
  "model_selection_policy": {"id": ..., "version": ...},
  "model_catalogue_version": ...,
  "optimizer": {"id": ..., "version": ...},
  "algorithm_versions": {...}
}))
run_id = "run-" + slug(page) + "-" + run_identity_sha256[:16]
```

- `model_ids` 实际 selected IDs 不放这里；它们写入 run evidence。
- 不把 investment 参数放进 run identity。
- 页面 slug 只用于可读 id；页面名进入摘要。
- 旧 id 只读兼容，不重算。

## 8. 固定向量

机器可读：`docs/fixtures/j01_run_identity_vectors.json`。字段与实际实现一致，全部由 P1a 代码重算。

公共历史：3 行 UTC；PV `[0.0, 1.5, 4.25]`、风电 `[2.0, 2.5, 3.0]`、负荷 `[10.0, 12.5, 11.0]`、电价 `[0.20, 0.25, 0.30]`。

| 向量 | 关键输入 | 期望 |
| --- | --- | --- |
| 历史摘要 | 上述 | `db13539cb15d68101bfdb28ad106c6fc2f36e249200f62c07056c7ebe0884d70` |
| 单位摘要 | `kW/kW/kW/currency/kWh` | `f9649c8dc9775e90525e1e7d2f97916619144fea84b40b42dd7e7467f3b7cc04` |
| 输入组 | 上述 | `ig-3a993a72953b9348` |
| 组 sha256 | 上述 | `3a993a72953b9348e62f72919a129d4dcfc1cddd6fd68ed9c4a03ef401b49761` |
| USD | `USD/kWh` | 同 `ig-3a993a72953b9348` |
| CNY/GBP/EUR | 对应 `/kWh` | 同 `ig-3a993a72953b9348` |
| Page 05 别名 | 四个展示名 | 同 `ig-3a993a72953b9348` |
| 改 `load_kw` 为 `MW` | `MW` | `ig-180f52a578a52b95` |
| 行顺序反转 | 时间戳与值同时反转 | 同 `ig-3a993a72953b9348` |
| 等价 +01:00 偏移 | 同一 UTC 时刻 | 同 `ig-3a993a72953b9348` |

旧 `ig-ca9c886e6fb1343c` / `a03cc9eb…` 是 `USD/kWh` 进入单位摘要的旧口径，已作废。

## 9. 测试状态

文件：`tests/test_run_identity.py`；当前 **14 passed**。

覆盖：

1. 固定向量与 fixture 一致。
2. USD/CNY/GBP/EUR 币种中立。
3. Page 05/06 跨页面同组。
4. 物理单位变化新组。
5. 行顺序、时区偏移等价。
6. 历史值/行数变化新组。
7. 缺失、额外、重复、未知信号拒绝。
8. `None`/字符串/`bool`/`NaN`/`inf` 拒绝。
9. 长度不一致、空序列拒绝。
10. 重复/无时区时间戳拒绝。
11. 模块无 Streamlit / 环境变量 / 数据库依赖。

## 10. 后续集成顺序

1. P1a 合并后，05/06 仅通过 adapter 调用，不自行拼 hash。
2. `request_sha256` 范围不变；`run_identity` 不参与，避免循环。
3. `derive_run_id` 待 D5 字段与 A1-A8 契约确认后实现。
4. Page 05/06 持久化、Page 09、`run_bindings` 不在 P1a/P3 范围。
