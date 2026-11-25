# J-01 纯函数接口设计与固定测试向量

- 状态：**接口设计，尚未实现**。本轮不新增 `islandos_core/run_identity.py`，不接入 05/06/09，不改现有计算。
- 目的：把 PD-1 / PD-2 的算法固化为可评审的纯函数契约，供 B-01 在负责人签署后落地。
- 关联：`docs/J-01_RUN_IDENTITY_DECISION.md`、`docs/fixtures/j01_run_identity_vectors.json`。

## 1. 边界

- 无 I/O、无数据库、无 Streamlit、无 `session_state`、无全局状态。
- 不读系统时钟、不用随机数、不读环境变量。
- 不解析 CSV、不推断缺失信号；输入必须是已经校验过的数据。
- 不写日志、不抛非确定性错误文本（错误消息固定，便于测试）。
- 只做：校验 → canonical JSON → SHA-256 → 返回冻结对象。

## 2. 规范信号名映射

页面契约使用展示名，canonical history 使用物理名；接口只接受后者。

| 页面/契约名 | canonical 名 | 进入组摘要 | 单位示例 |
| --- | --- | --- | --- |
| `pv_power` | `pv_power_kw` | 是 | kW |
| `wind_power` | `wind_power_kw` | 是 | kW |
| `essential_load` | `load_kw` | 是 | kW |
| `electricity_price` | `tariff_per_kwh` | 是 | USD/kWh |

页面适配层负责改名；适配层不放核心身份函数里。

## 3. 返回对象

```python
@dataclass(frozen=True)
class InputGroupIdentity:
    input_group_id: str          # "ig-" + sha256[:16]
    input_group_sha256: str      # 64 hex
    history_sha256: str          # canonical_history_sha256 结果
    units_sha256: str
    hour_count: int

@dataclass(frozen=True)
class RunIdentity:
    run_id: str                  # "run-<slug>-" + sha256[:16]
    run_identity_sha256: str     # 64 hex
    identity_schema_version: int # 1
    page: str
    input_group: InputGroupIdentity | None
```

## 4. 函数签名

```python
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
    model_ids: Mapping[str, str],
    optimizer: Mapping[str, str],
) -> RunIdentity: ...
```

不提供 `hour_count` 参数：由 `len(timestamps)` 推出，避免与数组长度不一致。
不提供 `history_sha256` 参数：由函数内部计算，避免调用方传入不匹配的摘要。

## 5. 校验规则

### 5.1 输入组

- `timestamps` 非空；每个元素是 tz-aware `datetime`；先 `astimezone(timezone.utc)` 再交给 `canonical_history_sha256`（该函数按传入 `isoformat()` 哈希，不做时区归一）。
- `signals` 必须**恰好**含四个 canonical 名，不能多也不能少；全部为有限 `float`/`int`（拒绝 `bool`、`NaN`、`inf`、字符串）。
- 四个数组长度一致且等于 `len(timestamps)`。
- `units` 必须恰好含四个 canonical 名；单位非空字符串；大小写敏感（`kW` ≠ `kw`）。
- 返回 `hour_count = len(timestamps)`。

### 5.2 运行

- `page` ∈ `{customer_dashboard, joint_resource_optimizer, device_flexibility_planner}`；slug 固定 `05/06/09`。
- `site_configuration_sha256` 为 64 位小写 hex。
- `page_settings` / `page_inputs` / `run_settings` 为 JSON-safe mapping：键为非空字符串，值为有限数、字符串、布尔、None、嵌套 mapping/list；拒绝 `NaN`、`inf`、`datetime`、`Path`、`Decimal`。
- `run_settings["currency"]` 必须存在且为非空字符串。
- `model_ids` 为 `str -> str`，可为空；`optimizer` 必须含非空 `id` 与 `version`。
- `input_group=None` 时，运行摘要里 `input_group_sha256=null`，`input_group_bound=false`。

## 6. 算法与域分隔

```
canonical_json(v) = json.dumps(v, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False)

H = canonical_history_sha256(utc(timestamps), pv, wind, load, tariff)
units_sha256 = sha256(canonical_json({四个 canonical 名: 单位}))
input_group_sha256 = sha256(canonical_json({
    "schema": "islandos-input-group-v1",
    "history_sha256": H,
    "units_sha256": units_sha256,
    "hour_count": N,
}))
input_group_id = "ig-" + input_group_sha256[:16]

page_inputs_sha256 = sha256(canonical_json(page_inputs))       # 空映射也要算
run_identity_sha256 = sha256(canonical_json({
    "schema": "islandos-run-identity-v1",
    "page": page,
    "input_group_sha256": input_group_sha256 or None,
    "site_configuration_sha256": site_configuration_sha256,
    "page_settings": page_settings,
    "page_inputs_sha256": page_inputs_sha256,
    "run_settings": run_settings,
    "model_ids": model_ids,
    "optimizer": optimizer,       # {"id": ..., "version": ...}
}))
run_id = "run-" + slug(page) + "-" + run_identity_sha256[:16]
```

要点：

- `schema` 字符串是域分隔，禁止省略或复用；未来算法变化必须改 `schema` 并升 `identity_schema_version`，不得悄悄改公式。
- 先组、后运行；运行只消费组的 **完整 sha256**，不消费短 id，避免截断碰撞进入运行身份。
- 页面的 slug 只用于可读 id，页面名同时进入摘要，二者不一致时以摘要为准。
- 组摘要不含 `page_inputs`；运行摘要含，保证 09 的任务变化产生新 run_id、但不产生新组。

## 7. 固定测试向量

机器可读版本：`docs/fixtures/j01_run_identity_vectors.json`。已用仓库 venv 与 `canonical_history_sha256` 逐项重算，全部匹配。

公共历史（3 行，UTC）：时间戳 `2026-01-01T00:00:00+00:00` 起逐小时；PV `[0.0, 1.5, 4.25]`、风电 `[2.0, 2.5, 3.0]`、负荷 `[10.0, 12.5, 11.0]`、电价 `[0.20, 0.25, 0.30]`；单位 `kW/kW/kW/USD/kWh`。

| 向量 | 关键输入 | 期望 |
| --- | --- | --- |
| 历史摘要 | 上述数组 | `db13539cb15d68101bfdb28ad106c6fc2f36e249200f62c07056c7ebe0884d70` |
| 单位摘要 | `kW/kW/kW/USD/kWh` | `a03cc9eb750e632ea9fa3f3b942abc0c0c2672f6a833bca6fdf18fe3fda21d23` |
| 输入组 | 上述 | `ig-ca9c886e6fb1343c`（sha `ca9c886e…9a7e`） |
| 05 基线 | `demand_scale=1.0, tariff_scale=1.0, cost_priority=0.7, currency=USD` | `run-05-1925b948348f5516` |
| 05 改负荷水平 | `demand_scale=1.2` | `run-05-00f3a05c937534c9`（同组） |
| 06 基线 | optimizer `12/5/20261113`，双可用，persistence 模型 | `run-06-172bcc278c85563f` |
| 09 无组 | 任务预算 40 kW，单任务 laundry | `run-09-c0eedc90612f9299` |
| 改单位 | `load_kw` 单位改为 `MW` | 组 `ig-25a1c78d3cac8d4e`；05 运行 `run-05-1aa503b84f32bd9a` |

说明：fixture 的站点 digest 是 `sha256("site-05-default")` 这类字面标签，仅为向量可读；生产必须传 `SiteAssumptions.digest()`。

## 8. 测试方案（实现时落地，本轮不写）

文件：`tests/test_run_identity.py`（尚未创建）。

1. **固定向量**：逐条读 fixture，断言 `history_sha256`、`units_sha256`、`input_group_id`、三个 `run_id` 完全相等。
2. **确定性**：同一输入连续调用两次，结果逐字段相等；不依赖字典插入顺序。
3. **组独立性**：改页面、站点、页面设置、运行设置、模型版本，`input_group_id` 不变、`run_id` 变。
4. **单位敏感**：`load_kw` 改 `MW` → 新组、新 run；`kW` 改 `kw` → 新组（大小写敏感）。
5. **无组**：09 输入组为 `None`，`input_group_bound=false`，run_id 仍稳定。
6. **拒绝项**：缺一个单位、多一个信号、数组长度不一致、`NaN`、`bool` 数值、非 tz-aware 时间戳、非法 site digest、缺 currency、空 optimizer id → 均抛 `RunIdentityError`，消息固定。
7. **无副作用**：函数不 import `streamlit` / `pandas`；不调用 `datetime.now` / `uuid`；测试可通过源码断言或依赖检查覆盖。
8. **兼容**：新 id 不匹配旧正则 `^run-[0-9a-f]{16}$`，旧 id 不被解析为 v1；`identity_schema_version=1` 明确返回。

## 9. 兼容性与集成顺序

- 本轮不建模块、不改页面；05/06/09 继续使用现有指纹与旧 id。
- 实现落地时，页面只调用函数、不自拼 hash；`request_sha256` 的计算范围不变，`run_identity` 不参与。
- 旧记录不重算；新函数只服务新运行。
- 若负责人未签署 PD-1/PD-2，以上签名与向量只作为评审材料，不进入生产代码。

## 10. 需要 B-01 确认的接口细节

1. 函数放 `islandos_core/run_identity.py` 还是并入 `canonical_run.py`（建议独立模块，避免 canonical manifest 结构变化）。
2. `RunIdentityError` 是否作为 `ValueError` 子类，便于现有页面异常捕获。
3. `page_inputs` 是否直接接收任务对象（含 `datetime`），还是要求调用方先转 JSON-safe 字典（建议后者）。
4. 单位映射是否允许额外键（建议拒绝，保持组身份唯一）。
5. `identity_schema_version` 是否随 run 记录持久化；字段名与版本号。
