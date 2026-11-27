# J-01 纯函数接口与固定测试向量

- 状态：**P1a 输入组、P1b `derive_run_id` 和 run-record 身份映射均已实现；页面接入未做。**
- 基线：`main = f9ca1b0`（2026-11-27）；P1a #372、P1b #373、存储契约 #359、run-record 映射 #379 已合并。
- 关联：`docs/J-01_RUN_IDENTITY_DECISION.md`、`docs/fixtures/j01_run_identity_vectors.json`、`docs/fixtures/j01_run_identity_p1b_vectors.json`。

## 1. 边界

- 纯函数无 I/O、无数据库、无 Streamlit、无 `session_state`、无环境变量、无全局状态。
- 不读系统时钟、不用随机数、不解析 CSV、不推断缺失信号。
- 只做：校验 → canonical JSON → SHA-256 → 冻结对象。
- `run_record_identity_fields()` 只做字段映射，不写数据库；持久化仍由 `workspace_store.record_run_record()` 负责。

## 2. 规范信号名与页面适配

| Page 05 展示名 | Page 06 / canonical 名 | 进入组 | 单位 |
| --- | --- | --- | --- |
| `pv_power` | `pv_power_kw` | 是 | `kW` |
| `wind_power` | `wind_power_kw` | 是 | `kW` |
| `essential_load` | `load_kw` | 是 | `kW` |
| `electricity_price` | `tariff_per_kwh` | 是 | 归一为 `currency/kWh` |

适配层只接受别名/物理名，不按名称猜语义；未知名、额外名、重复名一律拒绝。

## 3. 返回对象

```python
@dataclass(frozen=True)
class InputGroupIdentity:
    input_group_id: str
    input_group_sha256: str
    history_sha256: str
    units_sha256: str
    hour_count: int
    schema_version: int = 1

@dataclass(frozen=True)
class RunIdentity:
    run_id: str
    run_identity_sha256: str
    identity_schema_version: int
    page: str
    input_group: InputGroupIdentity | None
```

## 4. 函数签名

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

def derive_run_id(
    *,
    page: str,
    input_group: InputGroupIdentity | None,
    site_configuration_sha256: str,
    page_settings: Mapping[str, Any],
    page_inputs: Mapping[str, Any],
    run_settings: Mapping[str, Any],
    forecast_settings: Mapping[str, Any],
    model_selection_policy: Mapping[str, str],
    model_catalogue_version: str,
    optimizer: Mapping[str, str],
    algorithm_versions: Mapping[str, str],
) -> RunIdentity: ...

def run_record_identity_fields(identity: RunIdentity) -> dict[str, str | None]: ...
```

不接收 `hour_count` 或 `history_sha256` 作为入参：前者由时间戳长度推出，后者由函数内部计算，避免调用方传入不一致值。

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

## 6. P1a 输入组算法

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

`schema` 是域分隔；未来算法变化必须改 schema 并升 `identity_schema_version`，不得静默改公式。组摘要不含 page、site digest、`page_inputs`、币种、投资参数。

## 7. P1b 技术 run 身份算法

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

- `page` 只允许 `customer_dashboard`（05）和 `joint_resource_optimizer`（06）；Page 09 按 D8 不进入持久化。
- 实际 selected model IDs 和结果指标不进入身份；稳定 selection policy + catalogue version 进入。
- investment-only 字段递归拒绝，留给后续 append-only run binding。
- `run_settings.currency` 必填；币种不进入 input group，但进入 run identity。

## 8. 映射到 `run_records`

`run_record_identity_fields()` 返回：

```python
{
    "run_id": identity.run_id,
    "page": identity.page,
    "run_request_sha256": identity.run_identity_sha256,
    "input_group_id": identity.input_group.input_group_id if ... else None,
}
```

调用方式：

```python
record_run_record(
    db,
    project_id=selected_project_id,
    **run_record_identity_fields(identity),
    request_sha256=full_request_sha256,
    request_metadata=...,
    result=...,
    actor_id=...,
    consent_to_store_result=True,
)
```

约定：**`run_request_sha256` 直接使用 `run_identity_sha256`**。两者覆盖的是同一组技术输入；不再对 `run_id` 做二次 hash，也不用完整 `request_sha256` 代替。该映射只生成字段，不检查项目选择、consent 或数据库状态。

`run_record_identity_fields()` 会拒绝手工构造的不一致 `RunIdentity`：`run_id` 必须与 page + digest 匹配，`identity_schema_version` 必须为 1，input group 必须通过 P1a 校验。

## 9. 固定向量

机器可读：`docs/fixtures/j01_run_identity_vectors.json`（P1a）与 `docs/fixtures/j01_run_identity_p1b_vectors.json`（P1b）。

公共历史：3 行 UTC；PV `[0.0, 1.5, 4.25]`、风电 `[2.0, 2.5, 3.0]`、负荷 `[10.0, 12.5, 11.0]`、电价 `[0.20, 0.25, 0.30]`。

| 向量 | 期望 |
| --- | --- |
| 历史摘要 | `db13539cb15d68101bfdb28ad106c6fc2f36e249200f62c07056c7ebe0884d70` |
| 单位摘要 | `f9649c8dc9775e90525e1e7d2f97916619144fea84b40b42dd7e7467f3b7cc04` |
| 输入组 | `ig-3a993a72953b9348` |
| 组 sha256 | `3a993a72953b9348e62f72919a129d4dcfc1cddd6fd68ed9c4a03ef401b49761` |
| Page 05 run id | `run-05-f099924addce15e4` |
| Page 05 identity sha256 | `f099924addce15e4bde6c2d7146cd397fecb169dc1bfd06fbc11bb2b02073896` |
| Page 06 run id | `run-06-906cce6af6da7a0f` |
| Page 06 identity sha256 | `906cce6af6da7a0f6061f11f27393fa6aa61f49e494bdf9a29abbf5e6e893a47` |

旧 `ig-ca9c886e6fb1343c` / `a03cc9eb…` 是 `USD/kWh` 进入单位摘要的旧口径，已作废。

## 10. 测试状态

文件：`tests/test_run_identity.py`、`tests/test_run_identity_record_mapping.py`；当前 **40 passed**。

覆盖：

1. P1a/P1b 固定向量与 fixture 一致。
2. USD/CNY/GBP/EUR 币种中立；币种只进 run identity。
3. Page 05/06 跨页面同组、不同 page 身份。
4. 物理单位、历史值、行数、时间范围变化。
5. 行顺序、时区偏移等价。
6. 缺失、额外、重复、未知信号拒绝。
7. `None`/字符串/`bool`/`NaN`/`inf` 拒绝。
8. 重复/无时区时间戳拒绝。
9. 技术字段、模型策略/目录版本、optimizer、算法版本变化改变 run id。
10. investment-only 字段拒绝；Page 09 拒绝。
11. `run_record_identity_fields` 映射、错误身份拒绝。
12. 映射结果写入 `run_records` 后字段一致、完全重放幂等、不同结果抛 `run_result_conflict`。

## 11. 后续集成顺序

1. 先接 core 映射（本文件），不接页面。
2. Page 05/06 接入时，保留旧 `run-dashboard-*` / `run-*` 记录只读；新 run 使用新身份，是否迁移旧记录另行决定。
3. 持久化必须同时满足：真实项目、result-storage consent、run identity 可用；缺一项不写 `run_records`。
4. Page 09、`run_bindings`、API v4 契约不在 P1a/P1b 范围。
