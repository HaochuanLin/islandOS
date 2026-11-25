# 本地 Customer Console 登录 500 故障诊断

- 状态：**已定位，属启动顺序/代理问题，不是认证失败或服务端异常**。
- 环境：Windows 本机，`D:\code\islandOS`；前端 `http://127.0.0.1:5173/`，API `127.0.0.1:8766`。
- 证据时间：2026-11-25 14:58–16:17（本地时间 UTC+8）。
- 约束：未使用、未记录任何账号初始密码；未重置 owner；未修改他人代码与数据库。

## 1. 检查项与结果

| 检查项 | 实际结果 | 结论 |
| --- | --- | --- |
| 前端请求地址 | `frontend/src/api.ts` 所有请求使用相对路径 `/api/v1/...`，`fetch` 同源，无 `VITE_*` 基址 | 请求打到 5173，由 Vite 代理转发 |
| 代理配置 | `frontend/vite.config.ts`：`/api` → `http://127.0.0.1:8766`，`strictPort: true`，`changeOrigin:false` | 端口与 API 一致，配置无误 |
| 端口监听 | 5173（node/vite）、8766（`python islandos_service_api.py`）、8765（transport）均在监听 | 当前进程齐全 |
| 健康接口（直连） | `GET http://127.0.0.1:8766/api/v1/health` → `200 {"status":"ok","api_version":"v1",...}` | 服务存活 |
| 健康接口（代理） | `GET http://127.0.0.1:5173/api/v1/health` → 同上 200 | 代理链路正常 |
| 登录接口（直连/代理） | 用无效账号探针 → 两边均 `401 {"error":"invalid credentials"}` | 认证逻辑正常，错误语义清晰 |
| 后端访问日志 | `build/console-api.err.log` 从 15:19 起登录与列表接口全部 `200`；无任何 `5xx`；仅本次探针产生 3 条 `401` | 服务端没有 500 |
| Vite 日志 | `frontend/dev-server.log` 在 14:58:58、14:59:36、15:00:03 记录 `http proxy error: /api/v1/health` 与 `/api/v1/auth/login`，`connect ECONNREFUSED 127.0.0.1:8766` | 当时 8766 未启动 |
| API 启动时间 | 主服务进程启动于 15:19:27（`console-api.log` 首行监听 8766） | 前端页面早于 API 启动约 20 分钟 |
| 数据库 | `build/islandos-service.sqlite3`：1 个 tenant、1 个 owner（`owner@islandos.local`）、审计含 9 次 `auth.login` 与 1 次 `auth.logout`，最近登录 15:57:18 成功 | 账号与库正常，未触发重置 |

## 2. 根因

1. 陈韵竹先打开了 `http://127.0.0.1:5173/`，此时 8766 端口的 API 进程尚未启动。
2. 页面挂载即调用 `api.health()`；Vite 代理连不上 8766，记录 `ECONNREFUSED`。Vite 默认把代理失败转成 HTTP 500（**合理推断**：日志证明了连接被拒，500 的具体包装由代理完成），前端把 `health` 置为 `"offline"`。
3. 同一时段提交登录，代理同样 `ECONNREFUSED`，前端收到 `Request failed (500)`。
4. API 于 15:19 启动后，所有请求恢复 200；但 `health` 只在挂载时检查一次（`App.tsx` 的 `useEffect` 无重试），页面不刷新就一直显示 `API offline`。
5. 因此截图里的 500 与 offline 是**同一原因的两个表现**：API 未启动 → 代理 500 + 健康检查失败；不是密码错误，也不是后端崩溃。

排除项：

- **认证失败**：认证失败返回 401 且带 `invalid credentials`（已用无效账号验证），不会出现 500。
- **服务端异常**：`console-api.err.log` 无 traceback、无 5xx；若 handler 抛异常，连接会被重置，通常表现为 `Failed to fetch`，而不是稳定的 500。
- **环境变量不一致**：前端没有 API 基址环境变量；API 默认 8766，实际启动参数也是 8766；不存在两套地址。

## 3. 现在是否还存在

不存在。当前实测：

- 直连与代理的健康接口均为 200；
- 无效账号返回 401（符合预期）；
- 访问日志显示 15:19 之后全部 200。

如果页面仍显示 offline，是打开页面时的旧状态，刷新即可。

## 4. 若再次复现，需要陈韵竹提供的证据

以下命令只读，不含密码：

```powershell
Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 5173,8766
Invoke-WebRequest http://127.0.0.1:8766/api/v1/health -UseBasicParsing | Select-Object StatusCode,Content
Invoke-WebRequest http://127.0.0.1:5173/api/v1/health -UseBasicParsing | Select-Object StatusCode,Content
Get-Content D:\code\islandOS\frontend\dev-server.log -Tail 30
Get-Content D:\code\islandOS\build\console-api.err.log -Tail 30
```

另需：

- 浏览器 DevTools → Network：失败请求的 URL、状态码、响应体、发生时间；
- API 启动命令与工作目录（必须让相对路径 `build/islandos-service.sqlite3` 落在仓库根目录）；
- 若登录返回 401 而非 500，说明 API 已启动但账号/密码不匹配，此时只做核对，不重置 owner。

## 5. 建议的修复（不在本轮改代码）

1. 启动顺序固定：先 `python islandos_service_api.py --port 8766`，再 `npm run dev`；提供一键脚本或 README 顺序说明。
2. 前端健康检查加一次重试/轮询（例如挂载后 30 秒内每 5 秒重试），避免 API 后启动时页面永久显示 offline（`App.tsx`）。
3. 代理错误可读化：Vite 代理 500 时前端提示“本地 API 未启动”，而不是暴露 `Request failed (500)`。
4. 在 API 启动日志里打印实际数据库绝对路径，减少“连到别的库”的排查成本。

以上 2、3 属于前端体验改动，应走独立分支与评审，本轮未实施。
