# J-01 跨页面 Run Identity 产品定义（正式主线）

- 状态：**产品规则 D1-D9 已由负责人确认；PD-1 至 PD-6 据此收敛。数据库字段与错误码仍待 PR #359 作者确认。**
- 审查基线：`main = aacdbe9`（2026-11-25，IslandOS visual system 修复）；PR #359 head = `94388ed`（未合并）；PR #371 为 Draft（ProjectBinding 增量，未合并）。
- 主线：**PR #362 是 J-01 正式文档主线。PR #360 是早期 draft，不再扩展为第二套身份契约；二者不得同时作为实现依据。**
- 范围：页面 05 / 06 / 09 的身份、项目绑定和持久化边界。本轮 P1a 只实现输入组纯函数；P3 只实现项目上下文；不实现 `derive_run_id`，不修改 #359 数据库。

一句话：**两级身份**——`input_group_id` 标识“同一份物理输入数据”，`run_id` 标识“一个页面、一次可复现的技术运行定义”；同一输入组跨页面只做关联，永不自动合并为一次实验。

## 1. 决策状态

| 项目 | 状态 |
| --- | --- |
| D1-D9 产品规则 | 已确认，见 §2 |
| PD-1 输入组 | 已收敛；P1a 已实现纯函数与固定向量 |
| PD-2 run identity | 已收敛为“稳定模型策略身份”；本轮不实现 |
| PD-3 成功记录幂等 | 已确认方向；状态码/错误体待 #359 作者 |
| PD-4 失败只进审计 | 已确认方向；payload 待 #359 作者 |
| PD-5 投资绑定 | 只冻结设计；本轮不建表 |
| PD-6 旧 id 兼容 | 已确认；不重算、不改写、不删除 |
| A1-A8 #359 契约 | 建议已整理，见 `J-01_PR359_A1_A8_CONTRACT.md`；未改 #359 |

## 2. D1-D9 产品规则（已确认）

| ID | 规则 | 实现影响 |
| --- | --- | --- |
| D1 | `unregistered` 永不落库，只允许作为内存上下文。没有真实项目时允许模拟，但不写项目历史。 | `run_records` 只接受真实 `project_id`；无项目不调用写入口；不建假项目 |
| D2 | 项目选择不是模拟运行的前提。Page 05/06 默认不选择项目，没有项目仍可运行模拟。 | 计算路径不依赖 Workspace；selector 是可选项；持久化另设门禁 |
| D3 | 真实 `project_id` 只能来自本地 Workspace `projects` 表。不能使用 `streamlit-*` manifest label，不能自动创建项目，不能连接 Customer Console tenant/site。 | Page 08 创建；05/06 只读 lookup；固定 label 仅作 legacy manifest 字段 |
| D4 | 输入组采用币种中立单位；`tariff_per_kwh` canonical token 为 `currency/kWh`；USD/CNY/GBP 等只进 run settings；05/06 相同物理信号使用相同 canonical name；不确定语义不强行映射；固定向量重算。 | P1a 的 `derive_input_group_id`、alias adapter、units canonicalizer、fixtures |
| D5 | `run_id` 使用稳定的模型策略身份，不要求在 forecast 前拿到实际 selected model IDs。身份体现 canonical input group、site/config digest、forecast settings、model selection policy ID/version、model catalogue/registry version、optimizer ID/version、影响技术结果的算法组件版本、identity schema version。实际 selected models、指标和结果属于 run evidence。 | `derive_run_id` 设计；Page 06 不需要重排 manifest/forecast；run evidence 另存 |
| D6 | 完整 `request_sha256` 与技术请求摘要分离；建议命名 `run_request_sha256`。纯财务分析参数不进入技术摘要；会改变设备配置、容量、预测、优化或调度结果的参数必须保留。 | `run_records` 幂等键使用技术摘要；完整请求用于回放/保留同意 |
| D7 | 投资分析使用独立 append-only `run_bindings`；同一技术 run 可关联多个投资假设；投资参数变化不自动创建新技术 run。当前只冻结设计，不实现数据库表。 | 后续 P5；`run_records` 不加投资列 |
| D8 | Page 09 暂不进入持久化。不写 `run_records`，不创建 `input_group_id`，保持 `run_id=None`，不伪造 canonical identity。 | Page 09 零持久化；不显示伪造 id |
| D9 | 统一 session key：`islandos_active_project_id`。Page 08、05、06 使用相同选择机制。默认不选择；每次使用前重新验证；失效选择 fail closed；项目选择不代表持久化权限。 | `workspace_project_context` + `project_context_selector`；P3 实现 |

## 3. PD-1 至 PD-6

### PD-1 `input_group_id`：只认数据

**规则**：

- canonical 四信号固定为 `pv_power_kw`、`wind_power_kw`、`load_kw`、`tariff_per_kwh`。
- Page 05 展示名映射：`pv_power`、`wind_power`、`essential_load`、`electricity_price`；Page 06 使用 canonical 名。适配层只改名，不推断语义。
- `tariff_per_kwh` 单位规范为 `currency/kWh`；`USD/kWh`、`CNY/kWh`、`GBP/kWh` 等归一到同一 token。币种值只进 `run_settings`。
- 组只含 canonical history、units、`hour_count`；不含站点、页面、文件名、币种、投资参数、执行时间或项目。
- 时间戳统一转 UTC 后排序；重复时间戳拒绝；输入行顺序不影响组；空值和缺失行不填充。
- 数值沿用 `canonical_history_sha256` 的六位小数量化；单位变化改变组；历史值或行数变化改变组。

```
H = canonical_history_sha256(utc(timestamps), pv, wind, load, tariff)
units_sha256 = sha256(canonical_json({四个 canonical 名: 归一单位}))
input_group_sha256 = sha256(canonical_json({
  "schema": "islandos-input-group-v1",
  "history_sha256": H,
  "units_sha256": units_sha256,
  "hour_count": N
}))
input_group_id = "ig-" + input_group_sha256[:16]
```

**固定向量**（实际 P1a 实现重算，见 `docs/fixtures/j01_run_identity_vectors.json`）：

| 项目 | 值 |
| --- | --- |
| history | `db13539cb15d68101bfdb28ad106c6fc2f36e249200f62c07056c7ebe0884d70` |
| units（`currency/kWh`） | `f9649c8dc9775e90525e1e7d2f97916619144fea84b40b42dd7e7467f3b7cc04` |
| input group | `ig-3a993a72953b9348` |
| 组 sha256 | `3a993a72953b9348e62f72919a129d4dcfc1cddd6fd68ed9c4a03ef401b49761` |
| 改 `load_kw` 为 `MW` | `ig-180f52a578a52b95` |

旧的 `ig-ca9c886e6fb1343c` 依赖 `USD/kWh` 进入单位摘要，已被 D4 取代；不能继续作为固定向量。

### PD-2 `run_id`：页面内的可复现技术运行定义

**规则**：

- 必含：page、canonical input group（可空）、site/configuration digest、forecast settings、page settings/inputs、run settings、model selection policy ID/version、model catalogue/registry version、optimizer ID/version、影响技术结果的算法组件版本、identity schema version。
- **不要求**实际 selected model IDs 进入 `run_id`；selected model IDs、预测指标、执行结果写入 run evidence。
- 不含：执行时刻、操作者、项目、文件名、尝试次数、结果。
- 格式：`run-<05|06|09>-<sha256(canonical json)[:16]>`；页面进入摘要。
- 旧 `run-<16>` 与 `run-dashboard-<16>` 只读兼容，不重算。

D5 要求的是**模型选择策略身份**，不是“先把 forecast 跑完再建 manifest”。这样 Page 06 不需要重排计算顺序，也不会把实际 selected IDs 作为身份前置条件。

### PD-3 成功记录幂等

- 幂等键：`(project_id, run_id)`。
- 完全相同的重复提交：返回已有记录，标记 replay；不新增、不改时间、不改 actor。
- 同 `run_id` 不同技术摘要/page/input group：`run_id_conflict`。
- 同技术请求不同结果：`run_result_conflict`。
- 首次保存和重复保存都不覆盖；不可变触发器保留。
- HTTP 200/201 与响应体由 PR #359 作者确认；本文件不替作者批准。

### PD-4 失败只进审计

- 失败不写 `run_records`，只追加 `audit_events`，事件类型 `run_failed`。
- payload 至少含：`run_id`、`page`、`run_request_sha256`、`input_group_id`（可空）、受控 `error_code`、`attempt_no`、`occurred_at`。
- 不含请求正文、原始历史或敏感数据；失败重试沿用同一 `run_id`。
- 失败审计是否需要真实项目/同意，仍待 #359 作者和负责人确认。

### PD-5 投资分析：独立 append-only binding

- 技术 run 由 D5 身份定义；投资参数只生成 `investment_assumptions_sha256`。
- `binding_sha256` 由技术 run 与投资摘要合成；同一技术 run 可关联多个 binding。
- 投资参数变化不重跑优化、不产生新技术 `run_id`。
- 设计为独立 append-only 表，建议 PK 至少 `(project_id, run_id, binding_sha256)`；本轮不建表、不改 #359。
- 旧 `run-dashboard-*` 是把投资参数混入 run id 的 legacy 口径，保留只读，不重算。

### PD-6 旧 id 兼容

- 不重算、不改写、不删除历史 `run_id` 与记录。
- 新记录 `identity_schema_version=1`；旧记录缺失视为 `0`（legacy）。
- 新格式 `^run-(05|06|09)-[0-9a-f]{16}$`；旧格式继续可查。
- 旧记录没有 `input_group_id` 时保持 `null`，不补算、不伪造分组。

## 4. 当前代码与差距

| 事实 | 当前证据 | 影响 |
| --- | --- | --- |
| Page 05/06 不写 Workspace | 两页没有 `workspace_store`/`site_workspace` 写入口；身份仍是内存 manifest | 项目选择必须可选；持久化另设门禁 |
| Page 05 使用短名 | `history` 使用 `pv_power`/`wind_power`/`essential_load`/`electricity_price` | P1a adapter 负责映射到四个物理名 |
| Page 06 使用物理名 | `signal_history` 直接使用 `*_kw`/`*_per_kwh` | 与 05 共用同一组 |
| Page 06 先 manifest 后 forecast | 现有 manifest 在 selected models 之前建立 | D5 用模型策略身份，不要求重排 |
| Page 09 无身份 | summary `run_id=None`，无 manifest | D8 保持零持久化 |
| #359 项目级不可变 | `run_records` PK `(project_id, run_id)`；重复即拒 | 需 A1-A8 扩展；本轮不改 |
| #371 只读 lookup | `disabled`/`not_initialized`/`available`/`unavailable`；`resolve_selected_project` 返回 project 或 None | P3 需增加 registered/unregistered/invalid 状态与共享 key |
| API 契约仍 v3 | `app_view_models.CONTRACT_VERSION = 3`，无 `run_identity` 块 | 身份接入页面/契约是后续步骤 |

## 5. Page 05/06：选择、模拟、持久化分离

1. **默认不选择项目**。Page 05/06 启动时不自动选第一个项目。
2. **没有项目仍可模拟**。计算、预测、优化和下载不依赖 Workspace；Workspace disabled 时照常运行。
3. **选择不等于持久化权限**。`registered` 只说明项目存在；result-storage consent 与 full-request retention consent 另行检查。
4. **只读刷新**。每次使用选择前重新 `load_workspace_projects`；项目删除/非法 id 返回 `invalid` 并 fail closed，清空选择。
5. **不自动创建**。lookup 不初始化 DB、不建父目录、不建项目。
6. **共享 key**。`islandos_active_project_id` 是唯一选择来源；Page 08 创建项目后可设置；05/06 只读取/显示。

## 6. hosted demo 与 local Workspace 隔离

- hosted demo 默认 `ISLANDOS_ENABLE_LOCAL_WORKSPACE` 未设置：P3 返回 `disabled`，不显示项目 selector，不读取本地 DB，不初始化 Workspace。
- 只有明确 `=1` 的本地部署才读取 `ISLANDOS_WORKSPACE_DB`；数据库不存在返回 `not_initialized`，不得创建。
- 本地 DB 读取失败返回 `unavailable`，不泄露绝对路径；不得把本地路径写入 hosted demo 日志或页面。
- 项目元数据、原始历史文件和运行记录都不应进入公共 hosted demo；这是部署边界，不是 UI 偏好。

## 7. 三种同意必须独立

| 同意 | 作用 | 不得推导 |
| --- | --- | --- |
| 项目元数据存储同意 | Page 08 创建项目/配置时存本地元数据 | 不等于允许保存 run record |
| result-storage consent | 允许把某次运行结果写入项目历史 | 不等于允许保存完整请求 |
| full-request retention consent | 允许保留完整请求/历史正文 | 不等于默认开启；metadata-only 是默认 |

`ProjectBinding` 不携带任何 consent 字段，也不返回 `can_persist`/`can_write`；持久化层必须单独检查。任何一次同意都不能被另一次同意替代。

## 8. Page 09 零持久化边界

- 保持 `run_id=None`。
- 不创建 `input_group_id`；没有历史数据，不得伪造组。
- 不写 `run_records`、不写 `run_manifests`、不写项目历史。
- 不生成“ephemeral canonical identity”冒充可复现身份；只保留现有 `request_sha256` 与页面摘要。
- 若未来要进入持久化，必须先单独确认 D8 和 identity contract，不能由 P1a/P3 顺带开启。

## 9. 接口与固定向量

- 输入组纯函数已按 `docs/J-01_RUN_IDENTITY_INTERFACE.md` 落地：无 Streamlit、无环境变量、无数据库；只做校验、canonical JSON、SHA-256。
- `derive_run_id` 仍为设计，本轮不实现；不得把设计签名当成已交付代码。
- 固定向量只覆盖输入组，由实际实现重算；旧 `USD/kWh` 向量已作废。
- 时间范围、`hour_count`、输入顺序、空值、数值序列化规则在接口文档与测试中固定。

## 10. PR #359 与 A1-A8

本轮不修改 PR #359 分支、不修改数据库。A1-A8 的字段、类型、nullable、索引、幂等、冲突分类、失败 payload、迁移、旧记录兼容与包导入导出建议，见：

- `docs/J-01_PR359_A1_A8_CONTRACT.md`
- `docs/J-01_PR359_IDEMPOTENCY_REVIEW.md`

原则：旧记录不回填虚构 identity，不重写旧 run_id，不复用旧 `run_manifests` 主键，不破坏 audit chain，不改变 consent 含义。

## 11. 当前实施状态

| 工作 | 状态 |
| --- | --- |
| #362 J-01 文档 | 本文件与接口/向量已更新；#360 不再扩展 |
| P1a 输入组 | 独立分支实现；14 项测试通过；未接页面 |
| P3 ProjectBinding | 独立分支基于 #371；未接持久化；状态与共享 key 测试 |
| #359 A1-A8 | 仅技术契约建议；未改分支/DB |
| B-02 年度预测 | 继续暂缓；等待 B-01、正式 run identity、#359 契约、annualisation 规则 |

## 12. 兼容性与未决

**兼容**：旧 run id 只读；旧记录 `input_group_id=null`；旧 `run_manifests` 不迁移；旧包继续可导入（待 A6 确认）。

**未决（不阻塞 P1a/P3）**：

1. #359 状态码、错误体、字段名与迁移方式（A1-A8）。
2. 失败审计是否需要真实项目与独立同意。
3. `run_bindings` 的最终表结构与保留策略（P5）。
4. `run_identity` 进入 v4 请求/结果契约的时点。
5. Page 09 是否永不进入持久化，或另立 identity 规则。
