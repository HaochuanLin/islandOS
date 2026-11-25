# J-01 / PR #359 A1-A8 技术契约建议

- 状态：**建议，供 PR #359 作者确认；本轮未修改 #359 分支或数据库。**
- 基线：PR #359 head `94388ed`；`SCHEMA_VERSION="1.1"`；`run_records` 现有 PK `(project_id, run_id)`，`record_schema_version` 当前硬编码 `"1.0"`。
- 原则：旧记录不回填虚构 identity，不重写旧 `run_id`，不复用旧 `run_manifests` 主键，不破坏 audit chain，不改变 consent 含义。

## A1 `input_group_id` 列与索引

| 项目 | 建议 |
| --- | --- |
| 字段 | `input_group_id TEXT NULL` |
| 格式 | 新记录 `^ig-[0-9a-f]{16}$`；旧记录/无数据为 `NULL` |
| 索引 | `CREATE INDEX ... ON run_records(project_id, input_group_id, created_at)`；可加 `WHERE input_group_id IS NOT NULL` |
| 写入 | `record_run_record(..., input_group_id: str | None = None)`；新记录由 core 校验格式 |
| 查询 | `list_run_records(..., input_group_id=None)` 作为可选过滤 |
| 旧记录 | 保持 `NULL`，不补算、不猜测 |
| 迁移 | 若 #359 未合并：加入 `1.1` 的 `CREATE TABLE`；若已合并：新增 `1.1→1.2` 迁移 |

不建议把 `input_group_id` 塞进 `request_metadata`：它需要按项目/组查询，且应参与幂等比较。

## A2 `run_request_sha256`

| 项目 | 建议 |
| --- | --- |
| 字段 | `run_request_sha256 TEXT NULL` |
| 含义 | 只覆盖会改变设备配置、容量、预测、优化或调度结果的技术请求；排除投资参数及派生字段 |
| 写入 | 新记录必填（应用层校验）；旧记录 `NULL` |
| 校验 | 64 位小写 hex；与完整 `request_sha256` 分开保存 |
| 索引 | 不需要单独索引；幂等仍用 `(project_id, run_id)`，技术摘要用于冲突比较 |
| 迁移 | 同 A1：合并前加列，或合并后 1.1→1.2 |
| 旧记录 | `NULL`，不补算；不得用 `request_sha256` 代替 |

`request_sha256` 保留完整请求语义；`request_metadata` 仍受 64 KiB 与禁止键限制，不把原始历史放进去。

## A3 重复写入幂等

| 场景 | 建议行为 |
| --- | --- |
| 同 `(project_id, run_id)`，page/技术摘要/input group/result/retention 全部相同 | 返回已有记录，`replay=true`，不新增、不改 `created_at`/actor；HTTP 建议 200 |
| 同 `run_id`，page 不同 | `run_id_conflict`；HTTP 409 |
| 同 `run_id`，`run_request_sha256` 不同 | `run_request_conflict`；HTTP 409 |
| 同 `run_id`，`input_group_id` 不同 | `input_group_conflict`；HTTP 409 |
| 同技术请求，`result_sha256` 不同 | `run_result_conflict`；HTTP 409，不静默返回旧结果 |
| 首次保存 | 201（或作者统一的 200；本文件不替作者决定） |
| 并发 | 保留 PK 唯一约束；捕获 `IntegrityError` 后重新读取并判定 replay/冲突 |
| 不可变性 | 保留 `run_records_no_update` / `no_delete`；不新增 update 分支 |

不允许“同 id 不同内容覆盖”或“静默返回旧结果”。

## A4 failure audit API

| 项目 | 建议 |
| --- | --- |
| 入口 | `record_run_failure(db_path, *, project_id, run_id, page, run_request_sha256, input_group_id=None, error_code, attempt_no, actor_id, occurred_at=None)` |
| 存储 | 只写 `audit_events`，`event_type="run_failed"`；不建状态列、不建失败表 |
| payload | `run_id`, `page`, `run_request_sha256`, `input_group_id`, `error_code`, `attempt_no`, `occurred_at` |
| error_code | 受控枚举，例如 `validation_error`, `forecast_failed`, `optimizer_failed`, `persistence_error`, `internal_error` |
| 项目边界 | 建议要求真实 `project_id`；若不要求，payload 必须显式 `project_bound=false`，且不得写 `run_records` |
| 同意 | 失败审计不应复用 result-storage consent；是否需要单独同意待负责人确认 |
| 旧审计 | 只追加，不改已有事件哈希 |

不把异常堆栈、请求正文、原始历史或本地路径写进 payload。

## A5 page 值兼容

| 项目 | 建议 |
| --- | --- |
| 新写入 | `customer_dashboard`、`joint_resource_optimizer`、`device_flexibility_planner` |
| 旧值 | `05`、`06`、`09` 继续只读；旧测试/旧包不破坏 |
| 新写入是否允许旧短码 | 建议不允许；由 core 映射后再写 |
| 读路径 | 接受 canonical 名与旧短码；不重写旧记录 |
| 错误 | 未知 page 值 `unsupported_page`；空值仍拒绝 |
| 迁移 | 无 schema 变更 |

当前 #359 测试使用 `page="06"`，且只校验非空；如果强制 canonical 枚举，必须保留旧值兼容测试。

## A6 包导入导出兼容

| 项目 | 建议 |
| --- | --- |
| 导出 | `get_run_record` 输出新增 `input_group_id`、`run_request_sha256`、`identity_schema_version` |
| 导入 | 白名单重建 `record_run_record` 时传入新字段；不能只导出不导入 |
| record schema | 新记录建议 `"1.1"`；旧记录 `"1.0"`；包校验接受两者 |
| 旧包 | `1.0` 包继续可导入；缺失新字段按 legacy 处理 |
| 新包 round-trip | 新字段不得丢失；digest 重新校验 |
| 未知版本 | 拒绝并给出 `unsupported_record_schema_version` |

当前包校验严格只接受 `record_schema_version == "1.0"`；加入新字段后必须显式扩展，否则新导出无法 re-import。

## A7 旧 `run_manifests` 全局主键

| 项目 | 建议 |
| --- | --- |
| 新 canonical run | 只存 `run_records.canonical_manifest_json`；不复用旧 `run_manifests` 作为跨项目主键 |
| 旧表 | 保持原样，继续只读/导出；不做主键迁移 |
| 旧记录 | 不删除、不改写、不重算 |
| 若未来要第一类 manifest 表 | 另立迁移与复合键；不在 A1-A8 范围 |
| 兼容 | 包导出可继续包含旧 `run_manifests`；导入不依赖其主键 |

## A8 `identity_schema_version`

| 项目 | 建议 |
| --- | --- |
| 字段 | 优先 `identity_schema_version INTEGER NULL`；新记录 `1`，旧记录 `NULL` 或 `0` |
| 备选 | 放 `request_metadata` 受控字段；无 schema 迁移，但查询/校验较弱 |
| 包导入 | 缺失视为 `0`（legacy）；新包必须保留 |
| 响应 | 返回 `identity_schema_version`，与 `record_schema_version` 分开 |
| 迁移 | 列方案同 A1；metadata 方案无迁移 |
| 旧记录 | 不回填、不推断 |

不要把 `record_schema_version` 当作 identity 版本；两者语义不同。

## 迁移建议

1. **#359 尚未合并**：直接把 A1/A2/A8 列加入 `1.1` 的 `CREATE TABLE`，避免刚合并就发 1.2。
2. **#359 已合并**：发 `1.1→1.2` 迁移，更新 `workspace_meta`，写 `workspace_schema_migrated` 审计事件；不修改 1.0 历史。
3. 新增列全部 `NULL` 兼容；不设 `NOT NULL` 回填。
4. 索引只加在 `input_group_id`；其他字段不增加查询索引，避免写放大。
5. 任何迁移前先 `verify_audit_chain`；失败则停止。

## 旧记录与包兼容

- 旧记录：`input_group_id=NULL`、`run_request_sha256=NULL`、`identity_schema_version=0/NULL`；只读，不补算。
- 旧 `run_id`：不重写；新 id 正则与旧格式并存。
- 旧包：`record_schema_version="1.0"` 仍可导入；新字段缺失按 legacy。
- 旧 `run_manifests`：不迁移、不复用主键。
- audit chain：只追加；不重算历史事件哈希。
- consent：`consent_to_store_result` 与 `consent_to_retain_request` 继续独立；新字段不改变其含义。

## 仍需 #359 作者确认

1. 合并前改 1.1 DDL，还是合并后发 1.2。
2. A3 的 200/201 与冲突错误码命名。
3. A4 失败审计是否要求真实项目/单独同意。
4. A6 新记录 `record_schema_version` 用 `1.1` 还是保持 `1.0` + 可选字段。
5. A8 用列还是 metadata。
6. `run_request_sha256` 的精确排除字段由 core 还是 API 固定。
