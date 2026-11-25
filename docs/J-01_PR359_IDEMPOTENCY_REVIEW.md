# PR #359 只读兼容性审查：幂等写入、input_group_id、失败审计

- 审查对象：PR #359 `feat: persist immutable local run records`，head `94388ed`，分支 `feat/persistent-run-records-2026-11-25`。
- 审查方式：只读 `git show` + 临时 detached worktree（`D:\code\islandOS-pr359-review`，已删除）运行 `tests/test_workspace_store.py`，结果 **22 passed**。
- 边界：**未修改、未推送、未评论 #359 分支**；以下是最小改动建议，供 #359 作者与 B-01 决定。
- 结论：现有表结构与 J-01 的两级身份**基本兼容**，但三处必须补：`input_group_id` 列/索引、幂等分支、失败审计。都不需要改主键、不可变触发器或 retention 约束。

## 1. 现状核对（代码级）

| 项 | 现状 | 位置（PR 文件） |
| --- | --- | --- |
| 主键 | `PRIMARY KEY(project_id, run_id)`，`run_id TEXT NOT NULL` | `workspace_store.py:223-252` |
| 写入函数 | `record_run_record(...)`，参数含 `request_sha256`、`result`、`input_fingerprint_sha256`，无 `input_group_id` | `559-674` |
| 重复处理 | 先 `SELECT 1 ... (project_id, run_id)`，存在即抛 `WorkspaceStoreError("run record already exists for this project; records are immutable")` | `626-630` |
| 不可变 | `run_records_no_update` / `no_delete` 触发器 | `253-260` |
| 组身份 | 无 `input_group_id` 列、无索引；`input_fingerprint_sha256` 可空但语义含页面配置 | `243` |
| 失败状态 | 无 status 列、无失败表；`audit_events` 只追加、哈希链 | `261-279` |
| 查询 | `get_run_record(project_id, run_id)`；`list_run_records(project_id)` 逐条回查 | `678-746` |
| Schema | `SCHEMA_VERSION="1.1"`，已有 1.0→1.1 迁移 | `26`、`161-322` |
| 事务 | `_connect` 退出时 commit，异常 rollback；`busy_timeout=5000` | `89-105` |

## 2. 最小数据库改动

### 2.1 推荐：合并前直接改 CREATE TABLE（不引入 1.2 迁移）

PR 尚未合并，且当前只有 1.1 测试库；在 `CREATE TABLE run_records` 增加：

```sql
input_group_id TEXT,
```

并新增索引：

```sql
CREATE INDEX IF NOT EXISTS run_records_input_group
    ON run_records(project_id, input_group_id, created_at DESC);
CREATE INDEX IF NOT EXISTS run_records_page
    ON run_records(project_id, page, created_at DESC);
```

不加列：

- 不加 `input_group_bound`：由 `input_group_id IS NOT NULL` 推导，避免双字段不一致。
- 不加 `status` / `failure_reason`：失败不进成功表（PD-4）。
- 不加 `identity_schema_version` 列：先放 `request_metadata`（见 §4.3）；若后续要索引再升列。
- 不改 PK、不改不可变触发器、不改 retention CHECK。

### 2.2 若 #359 先合并，再做 1.2 迁移

同一 DDL 走 `Schema 1.1 → 1.2` 的 additive migration：`ALTER TABLE run_records ADD COLUMN input_group_id TEXT;` + 索引 + `workspace_meta` 版本更新 + 审计事件。旧行保持 `NULL`，不回填。

**兼容性**：旧记录不受影响；新列可空；查询需容忍 `NULL`。

## 3. 幂等写入的最小 API/函数改动

### 3.1 函数签名

`record_run_record` 增加：

```python
input_group_id: str | None = None,
identity_schema_version: int = 1,
```

校验：`input_group_id` 为空或匹配 `^ig-[0-9a-f]{16}$`；`identity_schema_version` 只允许 `{0, 1}`（0 仅用于 legacy 迁移，正常写入为 1）。

### 3.2 判定顺序（同项目内）

```
existing = SELECT * FROM run_records WHERE project_id=? AND run_id=?
if existing is None:
    INSERT ... (含 input_group_id)
    append audit "run_record_created"
    return record, replay=False

# 已有记录：只读比较，绝不 UPDATE
if existing.page != page
   or existing.request_sha256 != request_sha256
   or existing.input_group_id != input_group_id:
       raise run_id_conflict

if existing.result_sha256 != result_sha256:
       raise run_result_conflict       # 同请求不同结果，提示非确定性/代码版本变化

if existing.retention_mode != requested_retention_mode:
       raise retention_conflict        # 不得把 metadata_only 升级为 retained_full_request

return record_from_row(existing), replay=True
```

- 幂等命中**不写** `run_record_created`；可选追加 `run_record_replayed` 审计（建议加，便于观测重复提交）。
- 返回结构增加 `"idempotent_replay": true/false`，其余字段来自首次记录（`created_at`、`actor_id` 保持首次值）。
- 冲突使用明确异常类型（如 `RunIdConflict(WorkspaceStoreError)` / `RunResultConflict` / `RetentionConflict`），API 层映射 409 与稳定的 `error_code`。

### 3.3 并发与事务

两个进程同时通过 `SELECT` 后插入，唯一键会抛 `sqlite3.IntegrityError`。在 `INSERT` 外包一层：

```python
try:
    INSERT ...
except sqlite3.IntegrityError:
    existing = re-select(...)
    if existing is None:
        raise
    # 重走 §3.2 的比较分支：命中返回 200，内容不同抛冲突
```

不需要 `BEGIN IMMEDIATE` 也能保证不产生重复记录；若要减少重试，可在 `_connect` 内用 `BEGIN IMMEDIATE`，但会增加锁竞争，非必需。

### 3.4 查询接口

- `get_run_record` 返回增加 `input_group_id`、`input_group_bound`、`identity_schema_version`。
- `list_run_records(..., input_group_id: str | None = None, page: str | None = None)`；过滤在 SQL 层完成，避免逐条回查。
- 新增 `list_run_records_by_input_group(project_id, input_group_id)` 或复用上面的参数；`input_group_id=None` 表示“不过滤”，不是“查 null 组”。

**兼容性**：函数新增可选参数，旧调用不变；响应只增字段；旧客户端可忽略。

## 4. 失败审计的最小改动

### 4.1 不新增表，复用 `audit_events`

新增 core 函数：

```python
def record_run_failure(
    db_path: str | Path,
    *,
    project_id: str,
    run_id: str,
    page: str,
    request_sha256: str,
    error_code: str,
    actor_id: str,
    input_group_id: str | None = None,
    attempt_no: int = 1,
    created_at: datetime | None = None,
) -> dict[str, Any]:
```

校验：项目存在；`run_id`/`page`/`actor_id` 非空；`request_sha256` 64 位 hex；`input_group_id` 格式；`error_code` 取自受控枚举（如 `input_invalid`、`forecast_failed`、`optimizer_failed`、`internal_error`）；`attempt_no >= 1`。

写入：`_append_event(event_type="run_failed", payload={run_id, page, request_sha256, input_group_id, error_code, attempt_no, occurred_at})`；**不写请求正文、不写异常堆栈、不写结果**。

### 4.2 不做的改动

- 不加 `run_records.status`。
- 不加 `run_failures` 表。
- 不让失败记录占用 `(project_id, run_id)` 主键（否则成功重试无法写入）。
- 不改审计链结构；新事件类型不需要 CHECK 约束。

**兼容性**：审计事件只追加；现有 `verify_audit_chain` 逻辑对新事件类型透明；旧记录不受影响。

## 5. API 层建议（B-01）

| 端点 | 变更 |
| --- | --- |
| `POST /projects/{id}/runs` | 请求体加 `input_group_id`、`identity_schema_version`；201 新建 / 200 幂等 / 409 冲突 |
| `GET /projects/{id}/runs?input_group_id=&page=` | 支持按组/页面过滤；返回组字段 |
| `GET /projects/{id}/runs/{run_id}` | 返回组字段与 legacy 标识 |
| `GET /projects/{id}/input-groups/{ig}` | 汇总该组运行与页面分布 |
| `POST /projects/{id}/run-attempts` | 写 `run_failed` 审计，返回事件 id；不落结果 |

错误码建议：`run_id_conflict`、`run_result_conflict`、`retention_conflict`、`input_invalid`、`project_not_found`。统一 409/422/404，不泄露其他项目是否存在。

## 6. 需要新增的测试（交给 #359 作者/B-01，本任务未写）

1. 首次写入 201；完全相同重复写入 200 且记录数不变、`created_at`/`actor_id` 不变、`idempotent_replay=true`。
2. 同 id 不同 `request_sha256` → 冲突，原记录逐字节不变。
3. 同 id 同请求不同 `result_sha256` → `run_result_conflict`。
4. 同 id 不同 `input_group_id` / `page` → 冲突。
5. 首次 metadata_only，二次请求 full retention → `retention_conflict`，不升级。
6. 并发两线程同 id 写入：一个成功、一个 200 或冲突，绝不两条记录。
7. 失败审计写入后，成功重试可用同一 `(project, run_id)` 写入；失败事件数=attempt 数。
8. 旧 1.0 工作区迁移后 `input_group_id` 为 NULL，旧记录可读。
9. 同 canonical run 在两个项目仍允许（回归 #359 现有测试）。

## 7. 兼容性与风险

- **旧数据**：`input_group_id` NULL 即 legacy/unbound；不 backfill，不推断分组。
- **旧 API**：新增字段只增不减；重复提交从报错变为 200，属行为变更，需要客户端契约同步。
- **并发**：唯一键兜底；必须捕获 `IntegrityError` 后重查，否则并发下会把幂等请求变成 500。
- **retention**：不可变表不能升级留存级别；必须显式 409，不能用幂等命中掩盖。
- **schema**：合并前改 CREATE 最省事；已合并后必须走 1.2 迁移，测试需覆盖 1.1→1.2。
- **审计**：`run_failed` 只记录受控错误码，避免把异常文本/请求内容写入链。

## 8. 结论

| 需求 | 是否兼容现有 #359 | 最小改动 |
| --- | --- | --- |
| `input_group_id` | 表结构可加列；现有 API 无该参数 | 加可空列 + 两个索引；`record_run_record`/查询加字段 |
| 幂等写入 | 需要改重复分支，不改主键/触发器 | 先查后比；200/409；并发兜底 |
| 失败审计 | 完全复用 `audit_events` | 新增 `record_run_failure` + API |
| 旧 run_id | 完全兼容（主键是字符串） | 不改写、不 backfill、读路径兼容 |

不建议在 #359 未定稿前由 J-01 侧直接改其分支；以上作为评审输入，由作者决定合并前改表还是合并后迁移。
