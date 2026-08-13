# Dashboard API v1

Disk Space Visualizer `v0.9.0` 在本机提供只读优先的 HTTP API。默认地址为
`http://127.0.0.1:8765/api/v1`。API 不用于远程部署，不提供删除、移动或修改用户文件的
端点。

## Compatibility

- 当前稳定前缀：`/api/v1`。
- v0.8 的 `/api/*` 路由在 v0.9 中保留为兼容别名。
- 每个响应包含 `X-DiskVis-Version`、`X-DiskVis-API-Version` 和 `X-Request-ID`。
- JSON 错误对象包含 `error`、稳定的 `code` 和 `request_id`。

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | 进程存活、应用版本和 API 版本 |
| `GET` | `/ready` | 服务是否可接受请求及当前任务状态 |
| `GET` | `/api/v1/status` | 扫描阶段、进度、速度、错误和结果新鲜度 |
| `GET` | `/api/v1/result` | 当前分析摘要；不包含完整文件清单 |
| `GET` | `/api/v1/tree` | 目录节点、子目录和分页后的直接文件 |
| `GET` | `/api/v1/search` | 按名称/路径和最小大小分页搜索文件 |
| `GET` | `/api/v1/history` | Snapshot 趋势和最近变化 |
| `GET` | `/api/v1/diagnostics` | 版本、运行时、日志和任务诊断 |
| `GET` | `/api/v1/export/csv` | 下载完整文件清单 CSV |
| `GET` | `/api/v1/export/json` | 下载包含完整文件清单的 JSON |
| `GET` | `/api/v1/export/html` | 下载完全离线 HTML 报告 |
| `POST` | `/api/v1/scan` | 启动新扫描，返回 `202 Accepted` |
| `POST` | `/api/v1/cancel` | 请求取消当前扫描，返回 `202 Accepted` |

`POST` 请求必须设置 `Content-Type: application/json`，请求体使用空对象 `{}`。

## Pagination

目录直接文件：

```text
GET /api/v1/tree?path=Projects/src&offset=0&limit=100
```

文件搜索：

```text
GET /api/v1/search?q=backup&min_size=104857600&offset=0&limit=100
```

`limit` 范围为 1 到 500。响应提供 `offset`、`limit`、返回数量、总数量和 `has_more`。
搜索按文件大小降序返回；相同大小按路径稳定排序。

## Task State

`status.state` 可能为 `idle`、`running`、`completed`、`cancelled` 或 `error`。
`has_result` 表示是否存在最近成功结果；`result_stale` 表示该结果来自早于当前任务的扫描。
因此重新扫描失败或取消后，客户端可以继续安全展示最近成功结果，并同时提示其状态。

## Error Contract

```json
{
  "error": "request Host is not trusted",
  "code": "UNTRUSTED_HOST",
  "request_id": "b0b3d9b1263a7c71"
}
```

常见错误码包括 `INVALID_ARGUMENT`、`RESULT_NOT_READY`、`DIRECTORY_NOT_FOUND`、
`SCAN_ALREADY_RUNNING`、`NO_ACTIVE_SCAN`、`UNSUPPORTED_MEDIA_TYPE`、`BODY_TOO_LARGE`、
`UNTRUSTED_HOST` 和 `UNTRUSTED_ORIGIN`。报告问题时应附上 `request_id` 和对应时间附近的
Dashboard JSONL 日志。

## Security Boundary

服务只接受 IPv4 回环地址或 `localhost`，校验 `Host` 与 `Origin`，不启用 CORS，并限制
请求大小和读取超时。它不是面向公网的 Web 服务；不要使用反向代理把 Dashboard 暴露到
局域网或互联网。
