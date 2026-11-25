# J-01 跨页面 Run Identity 产品定义（技术契约草案）

- 状态：**草案，待负责人确认**。本文区分三类结论：`已由代码验证`、`合理推断`、`待团队确认`。
- 审查基线：`main` = `9615d82`（F-01 文档同步，#358）；PR #359 head = `94388ed`（分支 `feat/persistent-run-records-2026-11-25`，未合并）。
- 范围：页面 05 / 06 / 09 的 Run Identity；不改生产代码、不改模型与经济口径、不合并 PR。
- 一句话结论：**采用两级身份**——`run_id` 标识“一个页面、一次可复现的运行定义”，`input_group_id` 标识“一组可被多个运行共享的数据输入”。两者都不含执行时刻、操作者或尝试次数；两个页面使用同一份数据只做**关联**，不做合并。

## 1. 结论摘要

1. 系统今天**没有** `input_group_id`。最接近的是 `islandos_ui.customer_workflow.build_input_fingerprint` 的 `fingerprint_sha256`，但它是会话内 UI 提示，不持久化，且把站点配置混进“共享输入”，页面 05/06 的默认站点配置不同（柴油 0 kW vs 30 kW），**同一 CSV 在默认参数下指纹必然不匹配**（已实测，见 §3 G2）。
2. 06 已经有一套确定性 `run_id`（`deterministic_run_id` + canonical manifest）；05 只在年度投资绑定处生成 `run-dashboard-*`，主仪表盘运行本身**没有 run_id**；09 的结果摘要里 `run_id` 恒为 `null`。
3. 因此 `run_id` 与 `input_group_id` 不是新增概念替换旧概念，而是把三套并存的身份（canonical run、workspace run manifest、PR #359 run record）收敛到**两层语义**；旧 id 的迁移是破坏性变更，必须由团队确认。
4. PR #359 的 `(project_id, run_id)` 主键**兼容**本方案：`run_id` 是可读字符串、允许同一 run 存在多个项目、`input_fingerprint_sha256` 可空。缺口是三处：没有 `input_group_id` 列/索引、同 `run_id` 二次写入一律拒绝（没有幂等或 attempt 语义）、没有失败状态（表不可变）。
5. 页面 05 / 06 / 09 的“同 CSV”关联只到 `input_group_id` 层；是否算“同一次实验”永远由人决定，系统不自动合并。

## 2. 当前真实实现（已由代码验证）

### 2.1 三层身份并存

| 层 | 代码位置 | 生成方式 | 作用域 | 现状 |
| --- | --- | --- | --- | --- |
| Canonical run | `islandos_core/canonical_run.py` | 调用方传入 `run_id`；`deterministic_run_id(prefix, payload)` = `prefix-<sha256(canonical json)[:16]>` | 全局（无项目库约束） | 06 使用；05 仅年度绑定使用；不落库 |
| Workspace run manifest | `islandos_core/workspace_store.py:334` | **随机 `uuid.uuid4()`**，忽略调用方的确定性 id | 项目库 `run_manifests` 表 | 只有站点工作区导入流程（`site_workspace.py:602`，页面 08）写入；05/06 不写 |
| PR #359 run record | `workspace_store.py`（PR 分支） | 调用方传入任意非空 `run_id` | 项目库 `run_records`，主键 `(project_id, run_id)` | 未合并；页面 05/06/09 尚未接入 |

另有 `operator_decision_record.recommendation_id = dashboard-<history12>-<policy>`（页面 05），是人工复核记录的引用，不是运行身份。

### 2.2 页面 05

- 请求 `build_run_request(page="customer_dashboard", ...)` 只产出 `request_sha256`，**没有 run_id / input_group_id**（`app_view_models.REQUEST_FIELDS`）。
- 输入身份：`build_input_fingerprint(page="decision_dashboard", history_sha256, site_digest, units, hour_count, currency, page_settings)`。`fingerprint_sha256` 摘要覆盖 history、site digest、units、hour_count、currency；`page_settings` 单独摘要，不进共享摘要。
- 该指纹只存 `st.session_state`，刷新/换会话即丢；页面只把它当“与其它页面输入是否一致”的提示。
- 结果摘要：`build_run_result_summary(page="customer_dashboard")` 的 `run_id`、`manifest_sha256`、`evidence_sha256` **恒为 `None`**，因为“优化运行”与“投资屏引用的运行”不是同一个。
- 年度投资绑定：`deterministic_run_id("run-dashboard", {dataset_sha256, site_configuration_sha256, history_sha256, recommended_policy, weights, project_life_years, currency})`，再 `create_run_manifest(project_id="streamlit-customer-decision-dashboard", ...)`。仅用于年度数字的引用，不是整个仪表盘的运行 id。

### 2.3 页面 06

- `deterministic_run_id("run", {dataset_sha256, site_configuration_sha256, window_end_utc, currency, optimizer_settings, availability})`。
- `dataset_sha256` 对上传 CSV 取**文件字节 hash**（`site.source_sha256`），对合成数据取 canonical history hash；两种来源的 id 语义不同。
- manifest `project_id="streamlit-joint-resource-workspace"`。
- 结果摘要带 `run_id`、`manifest_sha256`、`evidence_sha256`（`planning_run`）。
- 复算入口（`islandos_core/run_orchestration.py:375-382`，`transport /run`）用 `deterministic_run_id("run", {"request": request})`，与页面路径的 payload 不同，**同一份输入从页面和复算 API 得到不同 run_id**。

### 2.4 页面 09

- 请求有 `request_sha256`；结果 `build_device_flexibility_summary` 里 `run_id` 硬编码 `None`。
- 没有 canonical manifest、没有数据集身份；输入是任务列表 + 时间戳 + 电价，不能假装与 05/06 共享输入组。

### 2.5 PR #359（已核对 diff，未合并）

- `run_records`：`PRIMARY KEY(project_id, run_id)`；`run_id TEXT NOT NULL`（任意非空字符串）；`input_fingerprint_sha256 TEXT` **可空**；`history_sha256` 可空；`request_sha256` 必填；`canonical_manifest_json/sha256` 可空；`retention_mode` 二选一（metadata_only / retained_full_request）。
- 表上有不可变触发器；同 `(project_id, run_id)` 第二次写入直接 `run record already exists for this project; records are immutable`。
- 测试明确允许“同一 canonical run 存在两个项目”，并覆盖了同项目内不可替换、不可变的路径。
- 没有 `input_group_id` 列、没有状态字段、没有 attempt 字段。

## 3. 现有实现与目标方案的差距

| 编号 | 差距 | 证据 | 影响 |
| --- | --- | --- | --- |
| G1 | 没有跨页面、可持久化的输入组身份 | 05/06 只有会话内 `fingerprint_sha256`；09 没有 | 历史运行无法按“同一份数据”聚合 |
| G2 | 指纹把站点配置算进“共享输入” | `build_input_fingerprint` 含 `site_digest`；05 默认柴油 0 kW，06 默认 30 kW | 同一 CSV 默认参数下指纹不匹配（实测：`6d5c96f9…` vs `2bae8a40…`，指纹 `95132eb1…` vs `0fa314c7…`） |
| G3 | 上传数据的身份是文件字节，不是数据内容 | 05/06 `history_sha256 = site.source_sha256`；provenance 文本含文件名 | 同名不同字节、同数据重新编码都会改变身份 |
| G4 | 05 主运行、09 没有 run_id | 结果摘要 `run_id=None` | 无法引用“这次运行”，PR #359 无对象可存 |
| G5 | run_id payload 不统一 | 06 页面 vs `transport /run` 复算；05 年度绑定另起一套 | 同一运行两个入口两个 id，历史引用歧义 |
| G6 | PR #359 无幂等/失败语义 | 不可变 + 重复即拒 | 重跑、失败重试无法落库 |
| G7 | `project_id` 两套含义 | canonical manifest 硬编码 `streamlit-*`；workspace/PR #359 是真实项目库 id | 同一条运行记录无法归入客户项目 |
| G8 | 无历史查询接口 | 只有 `get_run_record` 级函数，无按输入组/页面查询的 HTTP 面 | 页面无法展示“相关历史运行” |
| G9 | 页面标识有三套命名 | 契约用 `customer_dashboard` / `joint_resource_optimizer` / `device_flexibility_planner`；`build_input_fingerprint` 用 `decision_dashboard` / `joint_optimizer`；UI 是 05/06/09 | 请求、指纹、运行记录无法按同一页面键关联 |

## 4. 身份定义（契约草案）

### 4.1 `input_group_id`：数据输入身份

**定义**：一组“被提供给模型的数据”的身份。它只回答“这是不是同一份数据”，不回答“这是不是同一个场景/同一次实验”。

包含：

- canonical history digest（时间戳 + 四个信号，六位小数量化，沿用 `canonical_history_sha256`）
- 信号的 canonical 名称与单位映射
- 行数（可由时间戳推出，仍显式入摘要以防截断歧义）

不包含：

- 文件名、上传字节 hash、provenance 文案、页面名
- 站点容量、柴油配置、SOC 边界、currency
- 页面参数（demand_scale、cost_priority 等）
- 执行时间、操作者、项目

生成规则：

```
H = canonical_history_sha256(timestamps, pv, wind, load, tariff)
units_digest = sha256(canonical_json({name: unit for name, unit in units.items()}))
input_group_sha256 = sha256(canonical_json({
  "schema": "islandos-input-group-v1",
  "history_sha256": H,
  "units_sha256": units_digest,
  "hour_count": N
}))
input_group_id = "ig-" + input_group_sha256[:16]
```

`input_group_sha256` 可选地随运行记录保存（PR #359 无此列，可放 `input_metadata`）；`input_group_id` 是展示和索引用的短 id。

判定：

- 同一 CSV 重新上传、字节完全相同 → 同组。
- 同一数据重新导出（列顺序/编码/文件名变化但时间戳与数值一致）→ 同组（因为以 canonical digest 为准，而不是文件 hash）。
- 单位从 kW 改成 MW（数值未换算）→ 不同组；同物理量的单位变化必须显式换算后才是同组。
- 增删一行、改一个时间戳、改一个数值 → 不同组。

**待确认**：是否把 currency 放进组。本文建议**不放**：currency 是展示/计价标签，同一份负荷数据可以用不同币种展示；但电价信号本身在数据里，换算错误应由 T1/T7 的输入校验拦截，而不是靠身份分组。

### 4.2 `run_id`：一次运行的定义身份

**定义**：在一个项目内，一个页面用确定的输入定义执行的一次运行。标识“运行定义”，不是“执行尝试”。

包含：

- `page`（`customer_dashboard` / `joint_resource_optimizer` / `device_flexibility_planner`）
- `input_group_id`（无输入组时为 `null`，并用 `input_group_bound=false`）
- 站点配置 digest（`SiteAssumptions.digest()`）
- 页面参数（`page_settings`，05 的 demand_scale/tariff_scale/cost_priority 等）
- 运行参数（`run_settings`：currency、investment、optimizer settings、availability）
- 模型/优化器 id 与版本（进入 manifest 的部分）

不包含：

- 执行时刻、操作者、项目 id、尝试次数、上传文件名
- 结果（结果变化不改身份；结果不同意味着输入或代码版本变化，需由 manifest/evidence 摘要解释）

生成规则：

```
run_id = "run-" + page_slug + "-" + sha256(canonical_json({
  "schema": "islandos-run-identity-v1",
  "page": page,
  "input_group_sha256": input_group_sha256,   # 无组时为 null
  "site_configuration_sha256": digest,
  "page_settings": {...},
  "run_settings": {...},
  "model_ids": {...},
  "optimizer": {"id": ..., "version": ...}
}))[:16]
```

页面 slug 固定：05=`05`，06=`06`，09=`09`。页面名进入摘要，保证 05/06 即使数据与参数完全相同也不会得到同一个 run_id——**不同页面的运行永不合并**。

唯一性：系统的运行唯一键是 `(project_id, run_id)`。同一 `run_id` 可以出现在两个项目（PR #359 已测试），此时它们是同一“运行定义”在两个项目里的两份记录，不是两次不同运行。

### 4.3 尝试、失败、重跑

- `run_id` 在执行前计算，执行后不因成功/失败改变。
- 失败：**不写 `run_records`**（表不可变且无状态字段）；只写审计事件 `run_failed`（含 `run_id`、`request_sha256`、错误类别，不写输入正文）。重试使用同一个 `run_id`，成功后再落一条记录。
- 成功后的重复运行（同项目、同 `run_id`）：视为**幂等重放**。若 `request_sha256` 相同，返回已有记录；若不同（说明身份算法或代码版本变了），返回冲突而不是覆盖。
- 需要保留“第几次尝试”时，用审计事件里的 `attempt_no`，**不要**把 attempt 塞进 `run_id`。
- 换了任何运行定义输入（页面参数、站点、模型版本）→ 新 `run_id`，但 `input_group_id` 可不变。

### 4.4 没有输入组的运行

- `input_group_id = null`，`input_group_bound = false`。
- 典型：页面 09 的演示任务、纯手工场景、未来没有历史数据的页面。
- 历史列表按 `input_group_id` 聚合时排除 `null`；页面显示“未绑定共享输入（演示/临时）”，不得显示成“与某 CSV 同组”。

### 4.5 七个设计问题的直接回答

1. **两个页面用同一 CSV**：由 CSV 解析出的 canonical history + units 得到同一个 `input_group_id`；05 与 06 的 `run_id` 不同（页面、站点、参数进入 run 摘要），历史列表按组关联，不合并为一次实验。站点默认值差异（柴油 0 vs 30）不影响组。
2. **同数据、不同参数**：`input_group_id` 相同；站点、demand_scale、cost_priority、optimizer settings 任一变化都会产生新 `run_id`。同组多 run 是“同一份数据的多个方案”，不是重复记录。
3. **重新上传相同文件**：按目标算法，只要 canonical 时间戳/数值/单位一致，就是同一个组，即使文件名、列顺序、编码变了；今天按文件字节 hash 的实现只保证字节相同才算同一身份（G3）。
4. **失败、重复、重跑**：失败不落 `run_records`，只记 `run_failed` 审计，重试沿用同一 `run_id`；成功后的完全重复视为幂等复用；改参数即新 `run_id`；attempt 计数放审计，不放进 id。
5. **关联历史运行**：以 `(project_id, input_group_id)` 聚合，按 `created_at` 排序，展示页面、参数摘要、结果摘要；不自动串成实验，不自动比较不同页面。
6. **没有输入组**：`input_group_id=null`、`input_group_bound=false`；典型是 09 的演示任务。列表聚合时排除 null，UI 明示“未绑定共享输入”。
7. **兼容 PR #359**：`(project_id, run_id)` 主键、任意字符串 run_id、可空 fingerprint 都兼容；需补 `input_group_id` 列/索引、幂等写入、失败审计三项（§7），且不要在本轮擅自改 #359 分支。

## 5. 生成与传递规则

1. **生成位置**：核心层（建议 `islandos_core/run_identity.py`，由 B-01 落地），页面不得自行拼 hash。
2. **顺序**：先算 `input_group_id`（需要解析后的 history + units），再算 `run_id`（需要组 id + 站点 + 参数）。
3. **请求契约**：新增 `run_identity` 块；`request_sha256` 仍按现有字段计算，**不包含** `run_identity`（否则 run_id 依赖 request_sha256、request_sha256 又依赖 run_id，形成循环）。
4. **结果契约**：`build_run_result_summary` 新增 `input_group_id`、`input_group_bound`；`run_id` 不再允许对 05 恒为 null（09 在无数据场景可为 null，但必须同时 `input_group_bound=false`）。
5. **manifest**：`create_run_manifest` 是 v1 不可变结构，直接加字段会改变所有 manifest 摘要。两条路线（待确认）：A. 新增 manifest v2 并在 `dataset` 块加 `input_group_id`；B. 不改 manifest，把 `input_group_id` 放运行记录旁路。本文建议 **B 先行**（不破坏已有摘要），v2 再收编。
6. **持久化**：运行记录必须同时保存 `run_id`、`input_group_id`、`request_sha256`、`history_sha256`（canonical）、`result_sha256`、`page`、`project_id`；`project_id` 必须是真实项目库 id，没有项目时显式 `unregistered`，不许沿用 `streamlit-*` 假项目名。

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
    "run_id": "run-05-4a91c2d7e0f3b685",
    "input_group_id": "ig-7c3e9a1b52d84f60",
    "input_group_bound": true
  },
  "site": {"pv_rated_kw": 40.0, "diesel_rated_kw": 0.0, "digest": "…"},
  "history": {"hour_count": 168, "provenance": "Customer-uploaded CSV", "source_sha256": "…"},
  "page_settings": {"demand_scale": 1.0, "tariff_scale": 1.0, "cost_priority": 0.7},
  "run_settings": {"currency": "USD", "investment": {"…": "…"}},
  "request_sha256": "…"
}
```

结果（05，节选）：

```json
{
  "record_type": "islandos_run_result_summary",
  "page": "customer_dashboard",
  "run_id": "run-05-4a91c2d7e0f3b685",
  "input_group_id": "ig-7c3e9a1b52d84f60",
  "input_group_bound": true,
  "manifest_sha256": null,
  "summary_sha256": "…"
}
```

PR #359 记录（节选）：

```json
{
  "project_id": "proj-north-microgrid",
  "run_id": "run-05-4a91c2d7e0f3b685",
  "page": "customer_dashboard",
  "input_group_id": "ig-7c3e9a1b52d84f60",
  "request_sha256": "…",
  "history_sha256": "…",
  "input_fingerprint_sha256": null,
  "retention_mode": "metadata_only"
}
```

## 6. 页面 05 / 06 / 09 怎么用

### 05 Customer Decision Dashboard

- 用解析后的历史（合成或上传）算 `input_group_id`；`history_sha256` 在上传场景不再直接等于文件字节 hash，文件 hash 降级为 provenance。
- `run_id` 涵盖：page=05、组 id、SiteAssumptions digest（PV/风电/并网/电池/SOC 边界/柴油 0）、page_settings（demand_scale、tariff_scale、cost_priority）、run_settings（currency）。
- 投资假设（CAPEX、年账单等）不进入技术运行 id；投资屏另用 `binding_sha256` 引用同一 `run_id`。当前年度 manifest 的 `run-dashboard-*` 把 `project_life_years`、weights 混进运行 id，属 G5，迁移时一并处理（待确认）。
- 页面展示：`Run`、`Input group`、`Data source`、`History SHA-256`；同组历史只列“同项目 + 同组”，不自动做实验合并。

### 06 Forecast-Led Joint Resource Optimizer

- `dataset_sha256` 继续作为 manifest 的数据摘要，但 `run_id` 计算改用 `input_group_id`；站点、窗口结束时刻、optimizer settings、availability 仍参与。
- 结果摘要已有 run_id/manifest/evidence，补 `input_group_id` 即可；页面 caption 显示组 id，供 05 对照。
- 复算入口 `transport /run` 必须使用与页面相同的身份算法，否则同输入两个 id（G5）。

### 09 Device Flexibility Planner

- 当前无历史数据：`input_group_id=null`、`input_group_bound=false`，`run_id` 可为 null；不要伪造组 id。
- 若未来接入站点历史，再按同一算法生成；任务列表与预算属于 `page_inputs`，进 run_id 而不进组 id。

## 7. 与 PR #359 的兼容性结论

| 项 | 结论 | 依据 |
| --- | --- | --- |
| `(project_id, run_id)` 主键 | **兼容**：`run_id` 是任意非空字符串，确定性 id 可直接写入 | PR diff `run_id TEXT NOT NULL`，测试用 `canonical-run-01` |
| 同 run 多项目 | **兼容**：测试明确允许同一 canonical run 存两个项目 | `test_same_canonical_run_id_can_be_saved_in_two_projects` |
| 无输入组的运行 | **兼容**：`input_fingerprint_sha256` 可空 | schema 无 NOT NULL |
| 输入组索引 | **不兼容（需改）**：无 `input_group_id` 列与索引；只有可空的 `input_fingerprint_sha256`，且其语义含页面配置，不能直接复用 | §2.5 |
| 重复/失败 | **不兼容（需定义）**：同 `(project, run_id)` 二次写入一律拒绝；无 status | 不可变触发器 + 唯一检查 |
| `project_id` 语义 | **需对齐**：canonical manifest 的 `streamlit-*` 不是项目库 id | §3 G7 |

建议由 B-01 在 #359 合并前补三件事（需 PR 作者同意，本任务不改他人分支）：

1. `run_records` 增可空 `input_group_id TEXT` + `INDEX(project_id, input_group_id, created_at)`；`input_fingerprint_sha256` 保留给 UI 指纹，不与组 id 混用。
2. 保存接口增加幂等规则：同 `(project, run_id)` 且 `request_sha256` 相同 → 返回已有记录（200）；不同 → 409。
3. 失败尝试只写 `audit_events`（`run_failed`），不进 `run_records`。

在 #359 未合并前，J-01 的实现应保持“身份计算在核心层、落库接口可插拔”，不要把 05/06 直接绑到未合并的表结构。

## 8. B-01 后端需要实现的接口与字段

### 8.1 数据模型

`run_records` 增列：

- `input_group_id TEXT NULL`（格式 `ig-[0-9a-f]{16}` 或 null）
- `input_group_bound INTEGER NOT NULL DEFAULT 0`（0/1，与 id 一致性由服务端校验）

索引：

- `(project_id, input_group_id, created_at DESC)`，用于“同组历史”
- `(project_id, page, created_at DESC)`

### 8.2 HTTP 契约（草案）

1. `POST /api/v1/projects/{project_id}/runs`
   请求体：`run_id`、`page`、`input_group_id`（可空）、`request_sha256`、`history_sha256`、`input_fingerprint_sha256`（可空）、`result_sha256`、`result`、`canonical_manifest`（可空）、`retention_mode`、`consent_to_store_result=true`。
   响应：201 新建；200 幂等命中；409 `run_id already used with a different request`；422 身份格式错误；403 未授权。
2. `GET /api/v1/projects/{project_id}/runs?input_group_id=&page=&limit=&before=`
   响应：`{runs: [{run_id, page, input_group_id, created_at, result_sha256, retention_mode, replayable}]}`；按 created_at 倒序。
3. `GET /api/v1/projects/{project_id}/runs/{run_id}`
   响应：完整记录（不含明文请求正文，除非 `retention_mode=retained_full_request` 且调用者有权限）。
4. `GET /api/v1/projects/{project_id}/input-groups/{input_group_id}`
   响应：组摘要 + 关联 run 列表 + 页面分布；`null` 组不提供该端点。
5. `POST /api/v1/projects/{project_id}/run-attempts`
   仅记录失败尝试（`run_id`、`request_sha256`、错误类别），不写结果正文。

通用要求：请求体不得记录密码、token；日志不得打印请求正文（沿用 `islandos_service_api.py` 的 `log_message` 约束）。

### 8.3 错误语义

- `409` 只用于“同 run_id 不同 request”，不得用于普通重复提交（后者 200 幂等）。
- `404` 用于项目/运行不存在，不泄露其他项目是否存在。
- `422` 用于 id 格式或 `input_group_bound` 与 id 不一致。

## 9. 需要团队确认、不能由 AI 自行决定的问题

1. **组的范围**：`input_group_id` 只含数据（本文建议），还是也含站点配置？若含站点，05/06 默认柴油差异会让同一 CSV 不同组（G2），跨页关联失效。
2. **重新编码算不算同一份数据**：本文建议按 canonical 数据摘要判定（算同一组），需要确认这与 T1/T7 的输入指纹口径一致。
3. **重跑语义**：同 `run_id` 幂等复用记录（本文建议），还是每次执行生成新 `run_id`/`attempt_id`？后者会让“可复现运行”失去稳定引用。
4. **失败是否落库**：本文建议只写审计、不写不可变 `run_records`；若产品要求“失败也能在历史里看到”，需要新增带状态的表。
5. **05 年度投资绑定**：保持现有 `run-dashboard-*`（破坏统一），还是改为“同一 run_id + 独立 binding_sha256”（本文建议后者）？这会改变已导出的报告引用。
6. **run_id 迁移**：新格式 `run-05-*`/`run-06-*` 会让现有 06 `run-*` 引用失效。是接受一次性破坏，还是新旧并存到某个版本？
7. **project_id 绑定**：05/06 当前硬编码 `streamlit-*`，是否改为真实项目库 id；未登录/无项目时是否允许 `unregistered` 落库。
8. **manifest 版本**：`input_group_id` 进 manifest v2（改变摘要）还是旁路保存（本文建议旁路先行）。
9. **09 是否要有 run_id**：无历史数据的演示运行是否值得落库，还是仅保留 `request_sha256`。
10. **currency 是否入组**：本文建议不入组；需要产品确认“同数据不同币种”是否应视为同一输入组。

## 10. 实施顺序建议（不改变本轮边界）

1. 先由 B-01 / #359 作者确认 §7 的三个表结构问题（组列、幂等、失败审计）。
2. 核心层新增纯函数 `derive_input_group_id` / `derive_run_id`，附单元测试与固定向量；页面暂不接入。
3. 05/06 先做**只读展示**（现有会话内指纹旁显示派生组 id），不动计算与导出；09 保持 null。
4. 等负责人对 §9 的 1/3/5/6 作出决定后，再改 `run_identity` 进入请求/结果契约并落库。
