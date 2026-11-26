# J-01 / PR #359 A1-A8 技术契约

- 状态：**已由仓库负责人确认，并已在 PR #359 分支实现。**
- 基线：PR #359 本地 rebase 到 main `b42c624`；workspace `SCHEMA_VERSION="1.1"`；`run_records` PK 为 `(project_id, run_id)`。
- 原则：旧记录不回填虚构 identity，不重写旧 `run_id`，不复用旧 `run_manifests` 主键，不破坏 audit chain，不改变 consent 含义。

## A1 `input_group_id` 列与索引

| 项目 | 已实现口径 |
| --- | --- |
| 字段 | `input_group_id TEXT NULL` |
| 格式 | 新记录 `^ig-[0-9a-f]{16}$`；旧记录/无数据为 `NULL` |
| 索引 | `run_records_project_input_group_idx` on `(project_id, input_group_id, created_at)`，`WHERE input_group_id IS NOT NULL` |
| 写入 | `record_run_record(..., input_group_id: str | None = None)`；core 校验格式；identity=0 的旧格式记录不允许携带该字段 |
| 查询 | `list_run_records(..., input_group_id=None)` 可选过滤 |
| 旧记录 | `NULL`，不补算、不猜测 |
| 迁移 | #359 未合并，因此直接加入 1.1 `CREATE TABLE`；另加 `_ensure_run_record_identity_columns()` 对已存在的 1.1 表补列并建索引 |

`input_group_id` 不放进 `request_metadata`：它需要按项目/组查询，并参与幂等比较。

## A2 `run_request_sha256`

| 项目 | 已实现口径 |
| --- | --- |
| 字段 | `run_request_sha256 TEXT NULL` |
| 含义 | 只覆盖会改变设备配置、容量、预测、优化或调度结果的技术请求；排除投资参数及派生字段 |
| 写入 | 提供该摘要时创建 identity=1 新记录，`record_schema_version="1.1"`，该字段必填；未提供时写入 identity=0 旧格式记录，保持 NULL |
| 校验 | 64 位小写 hex；与完整 `request_sha256` 分开保存，不用后者代替 |
| 索引 | 不需要单独索引；幂等使用 `(project_id, run_id)`，技术摘要用于冲突比较 |
| 旧记录 | `NULL`，不补算 |
| 生成 | `RunIdentity.run_identity_sha256`；由 `run_record_identity_fields()` 映射，不对 `run_id` 二次 hash，不用完整 `request_sha256` 代替 |

`request_sha256` 保留完整请求语义；`request_metadata` 仍受 64 KiB 与禁止键限制，不把原始历史放进去。

## A3 重复写入幂等

| 场景 | 已实现行为 |
| --- | --- |
| 同 `(project_id, run_id)`，page/技术摘要/input group/result/retention 全部相同 | 返回已有记录，`idempotent_replay=true`，不新增记录、不新增审计、不改 `created_at`/actor |
| 同 `run_id`，page 不同 | `RunRecordConflict("run_id_conflict")`，`http_status=409` |
| 同 `run_id`，`run_request_sha256` 不同 | `RunRecordConflict("run_request_conflict")`，409 |
| 同 `run_id`，`input_group_id` 不同 | `RunRecordConflict("input_group_conflict")`，409 |
| 同技术请求，`result_sha256` 不同 | `RunRecordConflict("run_result_conflict")`，409，不静默返回旧结果 |
| retention mode 或保留的完整请求不同 | `RunRecordConflict("retention_conflict")`，409 |
| 并发 | 保留 PK 唯一约束；捕获 `sqlite3.IntegrityError` 后重新读取并判定 replay/冲突 |
| 不可变性 | 保留 `run_records_no_update` / `no_delete` 触发器；没有 update 分支 |

“完全重放”不比较 `request_sha256`（完整请求），否则仅因投资参数等非技术字段变化就无法重放；技术摘要才是 A2/A3 的冲突依据。identity=0 旧格式记录没有技术摘要，退化为比较完整 `request_sha256`。

## A4 failure audit API

| 项目 | 已实现口径 |
| --- | --- |
| 入口 | `record_run_failure(db_path, *, project_id, run_id, page, run_request_sha256, input_group_id=None, error_code, attempt_no, actor_id, occurred_at=None)` |
| 存储 | 只写 `audit_events`，`event_type="run_failed"`；不建状态列、不建失败表，不写 `run_records` |
| payload | `run_id`, `page`, `run_request_sha256`, `input_group_id`, `error_code`, `attempt_no`, `occurred_at`, `identity_schema_version=1`, `project_bound=true` |
| error_code | `validation_error`, `forecast_failed`, `optimizer_failed`, `persistence_error`, `internal_error` |
| 项目边界 | 要求真实 `project_id`；不存在则拒绝，不写 `project_bound=false` 的模糊事件 |
| 同意 | 失败审计不复用 result-storage consent，也不写结果/请求正文；当前不需要额外 consent 参数 |
| 旧审计 | 只追加，不改已有事件哈希 |

不把异常堆栈、请求正文、原始历史或本地路径写进 payload。

## A5 page 值兼容

| 项目 | 已实现口径 |
| --- | --- |
| 新写入 | canonical：`customer_dashboard`、`joint_resource_optimizer`、`device_flexibility_planner` |
| 旧值 | `05`、`06`、`09` 仅 identity=0 旧格式记录/旧包可读、可导入 |
| 新写入是否允许旧短码 | identity=1 新记录不允许；identity=0 兼容记录允许 |
| 读路径 | 接受 canonical 与旧短码；不重写旧记录 |
| 错误 | 未知 page 值抛 `WorkspaceStoreError("unsupported page")`；空值仍拒绝 |

现有测试大量使用 `page="06"` 且不传 `run_request_sha256`，因此保留为 legacy 路径；新测试使用 canonical page + 技术摘要。

## A6 包导入导出兼容

| 项目 | 已实现口径 |
| --- | --- |
| 导出 | `get_run_record` 输出新增 `input_group_id`、`run_request_sha256`、`identity_schema_version`，包内原样导出 |
| 导入 | 白名单重建 `record_run_record` 时传入三个新字段；不是只导出不导入 |
| record schema | 新记录 `"1.1"`；旧记录 `"1.0"`；包校验接受两者 |
| 旧包 | `1.0` 包继续可导入；缺失新字段按 legacy（identity=0、NULL）处理 |
| 新包 round-trip | 新字段不得丢失；digest 重新校验；1.1 记录必须使用 canonical page 与 identity=1 |
| 未知/不一致版本 | 拒绝；1.1 缺技术摘要或 identity 不是 1 也拒绝 |
| package schema | 仍为 `1.0`；本次只扩展 `record_schema_version`，不升 package 版本 |

## A7 旧 `run_manifests` 全局主键

| 项目 | 已实现口径 |
| --- | --- |
| 新 canonical run | 只存 `run_records.canonical_manifest_json`；不复用旧 `run_manifests` 作为跨项目主键 |
| 旧表 | 保持原样，继续只读/导出；不做主键迁移 |
| 旧记录 | 不删除、不改写、不重算 |
| 若未来要第一类 manifest 表 | 另立迁移与复合键；不在 A1-A8 范围 |
| 兼容 | 包导出可继续包含旧 `run_manifests`；导入不依赖其主键 |

## A8 `identity_schema_version`

| 项目 | 已实现口径 |
| --- | --- |
| 字段 | `identity_schema_version INTEGER NOT NULL DEFAULT 0` |
| 新记录 | `1`；并提供 `run_request_sha256` |
| 旧记录 | `0`；不回填、不推断 |
| 包导入 | 1.0 包缺失视为 `0`；1.1 包必须为 `1` |
| 响应 | 返回 `identity_schema_version`，与 `record_schema_version` 分开 |
| 约束 | CHECK：只允许 0/1；identity=1 时 `run_request_sha256` 必须非空 |
| 迁移 | 列方案同 A1；旧 1.1 表通过 `ALTER TABLE` 补列 |

不要把 `record_schema_version` 当作 identity 版本；两者语义不同。

## 迁移实现

1. **#359 合并前**：A1/A2/A8 列直接进入 `1.1` 的 `CREATE TABLE`，未额外发 1.2；现已随 #359 合并。
2. 已存在的 1.1 `run_records` 表由 `_ensure_run_record_identity_columns()` 检测缺列，`ALTER TABLE` 补 `run_request_sha256`、`input_group_id`、`identity_schema_version`，再建部分索引。
3. 新增列全部向后兼容；旧行得到 `NULL/NULL/0`，不设回填。
4. 索引只加在 `input_group_id`；其他字段不增加查询索引，避免写放大。
5. 不改 `workspace_meta` 的 `SCHEMA_VERSION`（仍为 1.1），不写迁移审计事件；`#359` 合并后如需 1.2 再单独处理。

## 旧记录与包兼容

- 旧记录：`input_group_id=NULL`、`run_request_sha256=NULL`、`identity_schema_version=0`；只读，不补算。
- 旧 `run_id`：不重写；新 id 正则与旧格式并存。
- 旧包：`record_schema_version="1.0"` 仍可导入；新字段缺失按 legacy。
- 旧 `run_manifests`：不迁移、不复用主键。
- audit chain：只追加；不重算历史事件哈希。
- consent：`consent_to_store_result` 与 `consent_to_retain_request` 继续独立；新字段不改变其含义。

## 验证覆盖

- `tests/test_workspace_store.py`：1.1 三列写入、部分索引、完全重放不加审计、五类 409 冲突、失败只写审计、按 input group 过滤、旧 06 记录仍为 1.0。
- `tests/test_site_workspace.py`：1.0 包仍可导入、1.1 包 round-trip 保留三列。
- 全量 `python -m pytest -q` 作为合并门禁。

## 已确认事项

1. 合并前直接改 1.1 DDL，不先发 1.2。
2. 冲突使用 `RunRecordConflict` + `http_status=409` + A3 五个错误码；重放字段为 `idempotent_replay`。
3. A4 失败审计要求真实项目、只写 audit、不引入额外 consent。
4. A6 新记录 `record_schema_version="1.1"`，旧包保持 `"1.0"`；package schema 不变。
5. A8 使用独立列 `identity_schema_version`，不使用 metadata。
6. `run_request_sha256` 的排除字段规则由 core/API 在生成摘要处固定，存储层只校验 64 位小写 hex 与冲突语义。
