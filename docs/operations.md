# Operations Guide

本指南用于本机 Dashboard 的启动、健康检查、日志和常见故障排查。

## Start And Stop

```bash
diskvis dashboard ./Downloads
diskvis dashboard ./Downloads --port 8765 --no-open-browser
```

服务默认只监听 `127.0.0.1`。终端按 `Ctrl+C` 会停止 HTTP 服务，并向正在运行的扫描发送
协作式取消信号。Dashboard 不会创建删除任务，也不会修改扫描目录中的文件。

## Health Checks

```text
GET http://127.0.0.1:8765/health
GET http://127.0.0.1:8765/ready
GET http://127.0.0.1:8765/api/v1/diagnostics
```

- `/health` 返回应用和 API 版本，适合确认进程可访问。
- `/ready` 返回当前任务状态和是否已有结果。
- `/diagnostics` 返回 Python、操作系统、进程、日志路径和分析状态。

## Logs

默认日志：

```text
Windows: %USERPROFILE%\.diskvis\logs\dashboard.jsonl
macOS/Linux: ~/.diskvis/logs/dashboard.jsonl
```

日志为 UTF-8 JSON Lines，每条 HTTP 记录包含 UTC 时间、请求 ID、方法、路径、状态和耗时。
单文件上限 2 MiB，保留三个轮换备份。日志目录不可写时服务仍会启动，原因可在“系统”页
或 `/diagnostics` 的 `logging_error` 中查看。

日志不会主动记录文件清单或查询结果，但异常堆栈可能包含正在处理的本机路径。分享日志前
应检查并移除敏感路径。

## Data Locations

| Data | Default location |
| --- | --- |
| Snapshot history | `~/.diskvis/snapshots/` |
| Dashboard log | `~/.diskvis/logs/dashboard.jsonl` |
| CLI report | `reports/report.html` |

JSON、Snapshot 和 HTML 先在目标目录写入临时文件，刷新到磁盘后再原子替换目标文件。
失败时保留旧文件并清理临时文件。

## Troubleshooting

### Port Already In Use

使用其他端口，例如 `diskvis dashboard PATH --port 8766`。不要改为 `0.0.0.0`；服务会
拒绝非回环地址。

### Scan Failed But Old Data Is Visible

这是预期的故障恢复行为。状态中的 `result_stale=true` 表示页面正在展示最近成功结果，
错误信息属于刚结束的新任务。检查请求 ID、Dashboard 日志和目标目录权限后重新扫描。

### Snapshot Save Failed

分析结果和导出仍可使用。检查 Snapshot 目录是否存在、磁盘是否已满以及当前用户是否有
写权限。状态中的 `snapshot_error` 会保留具体原因。

### Browser Shows A Host Or Origin Error

只使用程序输出的 `http://127.0.0.1:PORT/` 地址。代理、域名重写和远程访问会被安全策略
拒绝。该限制用于防止浏览器 DNS 重绑定攻击。

## Release Validation

```bash
python -m ruff check .
python -m pytest
python -m build
python -m pip check
python scripts/check_version.py
```

Windows 便携包还应验证 `diskvis.exe --version`、`diskvis.exe dashboard --help`、
`/health` 和 GUI 启动。发布附件应保留 CI 生成的 `SHA256SUMS.txt`。
