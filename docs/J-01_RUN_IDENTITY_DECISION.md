# J-01 跨页面 Run Identity 产品定义（技术契约草案）

- 状态：**Proposed Decision，待负责人签署**。本文区分：`已确认方向`（2026-11-25 负责人给定）、`仍待 PR #359 作者确认`（数据库/API 细节）、`仍待产品确认`。
- 审查基线：`main` = `9615d82`（F-01 文档同步，#358）；PR #359 head = `94388ed`（分支 `feat/persistent-run-records-2026-11-25`，未合并）。
- 范围：页面 05 / 06 / 09 的 Run Identity；本轮不接入页面、不改模型与经济口径、不合并 PR。
- 一句话：**两级身份**——`run_id` 标识“一个页面、一次可复现的运行定义”，`input_group_id` 标识“一组可被多个运行共享的数据输入”；同一份数据跨页面只做关联，永不自动合并为一次实验。

## 1. 决策状态总表

| 编号 | Proposed Decision | 状态 | 兼容性影响 |
| --- | --- | --- | --- |
| PD-1 | `input_group_id` 第一版只含 canonical history、units、hour_count | 已确认方向 | 新字段，不改旧记录 |
| PD-2 | `run_id` 含页面、输入组、站点 digest、页面设置、运行设置、模型/优化器版本 | 已确认方向 | 新格式与旧 id 并存，旧 id 不改写 |
| PD-3 | 同 `(project_id, run_id)` 成功运行幂等；同 id 不同内容报错，不覆盖 | 已确认方向；具体状态码待 #359 作者确认 | 不改主键；新增分支逻辑 |
| PD-4 | 失败运行不写不可变成功记录，只写失败审计 | 已确认方向；审计字段待 #359 作者确认 | 不改表；复用 `audit_events` |
| PD-5 | 05 年度投资绑定先分类参数：投资参数不改 run_id，技术与模型参数才改 | 已确认方向；落地代码未做 | 旧 `run-dashboard-*` 保留为 legacy |
| PD-6 | 旧 `run_id` 只做兼容映射，不重算、不改写、不删除 | 已确认方向；迁移细节待确认 | 历史记录原样可读 |

## 2. 当前真实实现（已由代码验证）

### 2.1 三层身份并存

| 层 | 代码位置 | 生成方式 | 作用域 | 现状 |
| --- | --- | --- | --- | --- |
| Canonical run | `islandos_core/canonical_run.py` | 调用方传入 `run_id`；`deterministic_run_id(prefix, payload)` = `prefix-<sha256(canonical json)[:16]>` | 全局 | 06 使用；05 仅年度绑定使用；不落库 |
| Workspace run manifest | `workspace_store.py:334` | **随机 `uuid.uuid4()`**，忽略确定性 id | 项目库 `run_manifests` | 仅站点导入流程（`site_workspace.py:602`，页面 08）写入；05/06 不写 |
| PR #359 run record | `workspace_store.py`（PR 分支） | 调用方传入任意非空 `run_id` | `run_records`，PK `(project_id, run_id)` | 未合并；05/06/09 未接入 |

另有 05 的 `operator_decision_record.recommendation_id = dashboard-<history12>-<policy>`，是人工复核引用，不是运行身份。

### 2.2 页面 05

- `build_run_request(page="customer_dashboard")` 只产出 `request_sha256`，没有 run_id / input_group_id。
- `build_input_fingerprint(page="decision_dashboard", history_sha256, site_digest, units, hour_count, currency, page_settings)`；`fingerprint_sha256` 含 history、site digest、units、hour_count、currency；`page_settings` 单独摘要，仅存 `st.session_state`。
- 结果摘要 `run_id="None"`；优化运行与其投资屏引用的运行被明确区分。
- 年度投资绑定：`deterministic_run_id("run-dashboard", {dataset_sha256, site_configuration_sha256, history_sha256, recommended_policy, weights, project_life_years, currency})`，manifest `project_id="streamlit-customer-decision-dashboard"`。

### 2.3 页面 06

- `deterministic_run_id("run", {dataset_sha256, site_configuration_sha256, window_end_utc, currency, optimizer_settings, availability})`。
- 上传 CSV 的 `dataset_sha256` 是文件字节 hash，合成数据是 canonical history hash。
- manifest `project_id="streamlit-joint-resource-workspace"`；结果摘要带 run_id / manifest / evidence。
- 复算入口 `transport /run` 用 `deterministic_run_id("run", {"request": request})`，与页面路径不同，同一输入两个 id。

### 2.4 页面 09

- 请求有 `request_sha256`；`build_device_flexibility_summary.run_id` 硬编码 `None`；无 manifest、无数据身份。

### 2.5 PR #359（已核对 diff，未合并）

- `run_records`：PK `(project_id, run_id)`，`run_id TEXT NOT NULL` 任意字符串，`input_fingerprint_sha256` / `history_sha256` / canonical manifest 可空，`request_sha256` 必填，`retention_mode` 二选一。
- 不可变触发器 `run_records_no_update` / `no_delete`；同 `(project_id, run_id)` 第二次写入直接抛 `run record already exists for this project; records are immutable`。
- 测试允许同一 canonical run 存在两个项目；无 `input_group_id`、无状态、无 attempt。
- `SCHEMA_VERSION = "1.1"`，已有 1.0→1.1 迁移；`record_run_record` 是唯一写入口。

## 3. 差距清单

| 编号 | 差距 | 证据 | 影响 |
| --- | --- | --- | --- |
| G1 | 无跨页面、可持久化输入组 | 05/06 只有会话内指纹；09 无 | 历史无法按同一份数据聚合 |
| G2 | 指纹混入站点配置 | `build_input_fingerprint` 含 `site_digest`；05 默认柴油 0 kW、06 默认 30 kW | 同 CSV 默认参数下指纹不匹配（实测站点 digest `6d5c96f9…` vs `2bae8a40…`，指纹 `95132eb1…` vs `0fa314c7…`） |
| G3 | 上传身份是文件字节 | `history_sha256 = source_sha256`；provenance 含文件名 | 同数据重新编码即新身份 |
| G4 | 05 主运行、09 无 run_id | 结果摘要 `run_id=None` | 无对象可引用/落库 |
| G5 | run_id payload 不统一 | 06 页面 vs `transport /run`；05 年度绑定另起一套 | 同一运行多入口多个 id |
| G6 | #359 无幂等/失败语义 | 不可变 + 重复即拒 | 重跑、失败重试无法落库 |
| G7 | `project_id` 两套含义 | canonical 硬编码 `streamlit-*`；项目库是真实 id | 记录无法归入客户项目 |
| G8 | 无历史查询接口 | 只有 `get/list_run_records` 级函数 | 页面无法展示相关历史 |
| G9 | 页面标识三套命名 | 契约 `customer_dashboard`；指纹 `decision_dashboard`；UI 05/06/09 | 请求、指纹、记录无法按同一键关联 |

## 4. Proposed Decision

### PD-1 `input_group_id`：只认数据

**规则（已确认方向）**：

- 只含：canonical history、units、hour_count。
- 不含：站点、页面、文件名、币种、运行参数、执行时间、项目。
- 计算沿用 `canonical_history_sha256`（时间戳 + 四信号，六位小数量化）；units 摘要只覆盖四个 canonical 信号单位；`hour_count` 显式入摘要。

```
H = canonical_history_sha256(timestamps, pv_power_kw, wind_power_kw, load_kw, tariff_per_kwh)
units_sha256 = sha256(canonical_json({pv_power_kw, wind_power_kw, load_kw, tariff_per_kwh 的单位}))
input_group_sha256 = sha256(canonical_json({
  "schema": "islandos-input-group-v1",
  "history_sha256": H,
  "units_sha256": units_sha256,
  "hour_count": N
}))
input_group_id = "ig-" + input_group_sha256[:16]
```

- 同一数据重新编码/换文件名 → 同组；单位变化 → 不同组；增删行或改数值 → 不同组。
- 无数据运行 → `null`。

**兼容性影响**：新增字段；旧运行没有该字段，一律视为 `null`，不回填、不推断。

### PD-2 `run_id`：页面内的可复现运行定义

**规则（已确认方向）**：

- 必含：页面标识、`input_group_sha256`（可空）、站点 digest、页面设置、运行设置、模型/优化器版本、page_inputs 摘要。
- 不含：执行时刻、操作者、项目、文件名、尝试次数、结果。
- 格式：`run-<05|06|09>-<sha256(canonical json)[:16]>`；页面进摘要，05/06 永不撞 id。

```
run-identity-sha256 = sha256(canonical_json({
  "schema": "islandos-run-identity-v1",
  "page": page,                     # 契约名，不是深链名
  "input_group_sha256": ...,       # 无组为 null
  "site_configuration_sha256": ...,
  "page_settings": {...},
  "page_inputs_sha256": ...,
  "run_settings": {...},
  "model_ids": {...},
  "optimizer": {"id": ..., "version": ...}
}))
run_id = "run-" + page_slug + "-" + run-identity-sha256[:16]
```

**兼容性影响**：新 id 与旧 `run-<16>` / `run-dashboard-<16>` 不冲突（旧格式无页面段）；旧记录不改写，见 PD-6。

### PD-3 幂等写入

**规则（已确认方向）**：

- 幂等键：`(project_id, run_id)`。
- 完全相同的重复提交（同 page、同 `request_sha256`、同 `input_group_id`、同 `result_sha256`）：返回已有记录，`idempotent_replay=true`，**不新增记录、不改时间、不改 actor**。
- 同 `run_id` 但 `page` / `request_sha256` / `input_group_id` 任一不同：明确报错 `run_id_conflict`。
- 同请求但结果不同：报错 `run_result_conflict`（提示非确定性或代码版本变化），不得静默返回旧结果。
- 首次保存与重复保存都不得覆盖；不可变触发器保留。

**兼容性影响**：行为从“一律拒绝”变为“200 命中 + 409 冲突”；旧记录不受影响。状态码与错误体待 #359 作者确认。

### PD-4 失败只进审计

**规则（已确认方向）**：

- 失败运行不写 `run_records`（该表无状态且不可变）。
- 只追加 `audit_events`，事件类型 `run_failed`；payload 含 `run_id`、`page`、`request_sha256`、`input_group_id`（可空）、`error_code`（受控枚举）、`attempt_no`、`occurred_at`；不含请求正文、不含敏感数据。
- 失败后重试沿用同一 `run_id`；成功时再写成功记录。
- 重复失败允许多条审计（attempt 递增），不产生成功记录。

**兼容性影响**：无需改表；审计链只追加，不改变已有事件哈希。

### PD-5 05 年度投资绑定：先分类参数

**运行定义参数（变化 → 新 `run_id`）**：

| 类别 | 参数 |
| --- | --- |
| 页面 | `page` |
| 数据 | canonical history、units、hour_count（经 `input_group_sha256`） |
| 站点 | PV/风电装机、并网限值、电池容量/功率/SOC 边界、柴油额定功率与变动成本 |
| 页面设置 | 05 的 `demand_scale`、`tariff_scale`、`cost_priority`；09 的任务与预算 |
| 运行设置 | `currency`、可用性、优化器 population/generations/seed |
| 模型 | forecast model ids、优化器 id/version、forecast settings |

**非运行定义参数（变化 → 同一 `run_id`，只换投资绑定摘要）**：

`baseline_annual_energy_cost`、`proposed_annual_energy_cost`、`annual_incremental_om_cost`、`upfront_capex`、`project_life_years`、`discount_rate`、两种 escalation、`replacement_year`、`replacement_cost`、`residual_value`。

**规则**：

- 技术运行输出 `run_id`；投资屏输出 `investment_assumptions_sha256`；两者合成 `binding_sha256`。
- 只改投资参数不生成新运行，也不重跑优化；绑定摘要变化即可追溯。
- 技术参数变化：新 `run_id` + 新绑定。
- 现有 `run-dashboard-*` 是把 `project_life_years`、weights 混入运行 id 的旧口径，保留为 legacy，不重算。

**兼容性影响**：旧 JSON 导出中的 `run-dashboard-*` 仍有效；新导出同时带 `run_id`（技术运行）与 `binding_sha256`；不删除旧字段。

### PD-6 旧 run_id 迁移

**规则（已确认方向）**：

- 不重算、不改写、不删除任何历史 `run_id` 及其记录。
- 用显式版本区分：新记录 `identity_schema_version=1`；旧记录缺失即视为 `0`（legacy）。
- 新格式 `^run-(05|06|09)-[0-9a-f]{16}$`；旧格式 `^run-[0-9a-f]{16}$`、`^run-dashboard-[0-9a-f]{16}$` 继续可查。
- 只有当旧 id 可由公开公式确定性重算时，才可在新记录 metadata 写 `legacy_run_id` 做提示映射；不保证一一对应，不做批量 backfill。
- 05 年度绑定旧 manifest 原样保留；新绑定引用技术 run_id，并保留 `legacy_run_id`（若可证明）。

**兼容性影响**：读路径同时接受新旧 id；写路径只产生新 id；历史列表按 `project_id + input_group_id` 聚合时，legacy 记录以 `input_group_id=null` 单独展示，不伪造分组。

## 5. 生成与传递规则

1. 生成位置：核心层纯函数（建议 `islandos_core/run_identity.py`，由 B-01 落地）；页面不得自行拼 hash。
2. 顺序：先 `derive_input_group_id`，再 `derive_run_id`。
3. 请求契约新增 `run_identity` 块；`request_sha256` 仍按现有字段计算，**不含** `run_identity`，避免循环依赖。
4. 结果摘要新增 `run_id`（05 不再为 null）、`input_group_id`、`input_group_bound`、`identity_schema_version`。
5. canonical manifest 暂不改 v1 结构；`input_group_id` 存运行记录旁路，避免改变所有 manifest 摘要（待确认是否升 v2）。
6. 持久化保存 `run_id`、`input_group_id`、`request_sha256`、canonical `history_sha256`、`result_sha256`、`page`、`project_id`；`project_id` 必须是真实项目库 id，未绑定项目时显式 `unregistered`。

### JSON 示例

请求（05，节选）：

```json
{
  "schema_version": 4,
  "request_type": "islandos_run_request",
  "page": "customer_dashboard",
  "run_identity": {
    "schema_version": 1,
    "project_id": "proj-north-microgrid",
    "run_id": "run-05-1925b948348f5516",
    "input_group_id": "ig-ca9c886e6fb1343c",
    "input_group_bound": true
  },
  "history": {"hour_count": 168, "provenance": "Customer-uploaded CSV", "source_sha256": "…"},
  "request_sha256": "…"
}
```

结果（05，节选）：

```json
{
  "record_type": "islandos_run_result_summary",
  "page": "customer_dashboard",
  "run_id": "run-05-1925b948348f5516",
  "input_group_id": "ig-ca9c886e6fb1343c",
  "input_group_bound": true,
  "summary_sha256": "…"
}
```

运行记录（PR #359 扩展后，节选）：

```json
{
  "project_id": "proj-north-microgrid",
  "run_id": "run-05-1925b948348f5516",
  "page": "customer_dashboard",
  "input_group_id": "ig-ca9c886e6fb1343c",
  "request_sha256": "…",
  "result_sha256": "…",
  "retention_mode": "metadata_only"
}
```

## 6. 页面 05 / 06 / 09 的用法

- **05**：用解析后的历史算组；`run_id` 含 page=05、组、站点、05 页面设置、currency（不含投资参数）。投资屏用同一 `run_id` + `binding_sha256`；展示 `Run`、`Input group`、`Data source`、legacy 标识。
- **06**：`dataset_sha256` 仍进 manifest，但 run 身份改用 `input_group_sha256`；站点、窗口、optimizer、availability、模型版本进入。复算入口必须同算法。
- **09**：无历史 → `input_group_id=null`、`input_group_bound=false`；`run_id` 可生成（page=09、任务/预算、站点），待确认是否落库；不得伪造组 id。

## 7. 与 PR #359 的兼容性结论

**兼容**：PK `(project_id, run_id)`、任意字符串 run_id、同 canonical run 跨项目、可空 fingerprint。

**需补（最小改动，详见 `docs/J-01_PR359_IDEMPOTENCY_REVIEW.md`）**：

1. `input_group_id` 可空列 + `(project_id, input_group_id, created_at)` 索引。
2. `record_run_record` 幂等分支：200 命中 / 409 冲突 / 不覆盖；并发用唯一键兜底。
3. 失败审计函数，复用 `audit_events`，不加状态列、不加失败表。
4. 保留不可变触发器、PK、retention 约束不变。

以上均属 **仍待 PR #359 作者确认** 的数据库事项，本任务未修改 #359 分支。

## 8. B-01 后端接口与字段（摘要）

- `POST /api/v1/projects/{project_id}/runs`：新增 `input_group_id`，幂等 200 / 冲突 409。
- `GET /api/v1/projects/{project_id}/runs?input_group_id=&page=&limit=`。
- `GET /api/v1/projects/{project_id}/runs/{run_id}`。
- `GET /api/v1/projects/{project_id}/input-groups/{input_group_id}`。
- `POST /api/v1/projects/{project_id}/run-attempts`：失败审计，仅写 `run_failed`。
- 所有响应增加 `identity_schema_version`、`input_group_id`、`input_group_bound`；不返回请求正文（除非 retention 授权）。

完整字段与错误码见 `J-01_PR359_IDEMPOTENCY_REVIEW.md`。

## 9. 仍待确认

**待 PR #359 作者确认（数据库/API）**：

1. 加列是在合并前直接改 CREATE TABLE，还是合并后发 `1.1→1.2` 迁移。
2. 幂等命中返回 200 还是 201；冲突错误码命名与响应体结构。
3. 同请求不同结果是否一律 409，还是允许 `result_mismatch` 标记后人工复核。
4. `retention_mode` 冲突（首次 metadata_only，二次请求 full retention）如何处理；建议 409，不得升级或覆盖。
5. 失败审计的 `error_code` 枚举与 payload schema；由 core 还是 API 层写。
6. `legacy_run_id` 放 metadata 还是加列；是否需要按旧 id 查询的 API。
7. `input_group_id` 的格式校验放在 core 还是 API。

**待产品/负责人确认**：

1. `project_id` 绑定：canonical manifest 的 `streamlit-*` 是否改为真实项目 id；未登录是否允许 `unregistered` 落库。
2. manifest 是否升 v2 收编 `input_group_id`（当前建议旁路保存）。
3. 09 是否必须生成并保存 `run_id`，还是只保留 `request_sha256`。
4. 旧 id 的 UI 呈现文案（legacy 标识、是否允许按旧 id 直接打开）。

## 10. 实施顺序

1. 负责人签署 PD-1..PD-6；#359 作者确认 §9 数据库事项。
2. 核心层落 `derive_input_group_id` / `derive_run_id` 纯函数与固定向量测试（设计见 `J-01_RUN_IDENTITY_INTERFACE.md`）。
3. B-01 落 `input_group_id` 列、幂等写入、失败审计；不碰页面。
4. 05/06 先只读展示派生身份，验证与现有指纹/旧 id 的对照；09 保持 null。
5. 最后再改 `run_identity` 进入请求/结果契约；任何一步都不得改写历史记录。

## 11. 每项决策的兼容性影响

| 决策 | 现有数据 | 旧 API/导出 | 迁移动作 |
| --- | --- | --- | --- |
| PD-1 | 旧运行无组字段，保持 null | 响应新增字段，旧客户端可忽略 | 无回填 |
| PD-2 | 旧 id 原样有效 | 新导出同时给新旧 id | 无重算 |
| PD-3 | 旧记录只读 | 重复保存行为变为 200/409 | 无 schema 变更 |
| PD-4 | 旧审计链不变 | 新增 `run_failed` 事件类型 | 无 schema 变更 |
| PD-5 | 旧 `run-dashboard-*` 保留 | 新导出增加 `binding_sha256` | 旧字段不删 |
| PD-6 | 历史记录可查 | 读路径兼容两种正则 | 可选 legacy 提示，无 backfill |

## 12. 关联文档

- `docs/J-01_PR359_IDEMPOTENCY_REVIEW.md`：只读兼容性审查与最小改动。
- `docs/J-01_RUN_IDENTITY_INTERFACE.md`：纯函数签名、校验规则、固定向量。
- `docs/fixtures/j01_run_identity_vectors.json`：机器可读测试向量。
