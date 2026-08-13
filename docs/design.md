# Design

## 项目架构

Disk Space Visualizer 采用分层结构：

- `models.py` 定义核心 dataclass 数据结构。
- `scanner.py` 负责遍历文件系统并生成 `FileInfo`。
- `analyzer.py` 负责从 `FileInfo` 列表计算统计结果。
- `duplicates.py` 负责重复文件检测。
- `recommender.py` 负责生成清理建议。
- `service.py` 负责统一编排扫描、分析、重复检测和报告数据格式化，不依赖 Typer、Rich 或 Tkinter。
- `exporter.py` 负责 JSON 序列化。
- `snapshot.py` 负责快照 schema、保存加载和历史差异计算。
- `report.py` 和两个 Jinja2 模板负责当前扫描与历史对比报告。
- `cli.py` 只负责 Typer 命令、严格参数校验和 Rich 输出。
- `gui.py` 只负责 Tkinter 界面、后台线程和调用 Service。

## 数据流

```text
CLI / GUI 参数
  -> scan_directory()
  -> list[FileInfo]
  -> analyzer/recommender/duplicates
  -> AnalysisResult
  -> Rich 表格 / GUI / JSON 文件 / HTML 报告
  -> Snapshot JSON -> SnapshotComparison -> Rich 表格 / Comparison HTML
```

所有核心模块都围绕 dataclass 传递数据。`AnalysisOptions` 定义一次分析的输入，`AnalysisResult` 同时返回报告数据和扫描元数据。只有在导出 JSON 和渲染模板前，才统一转换为可序列化结构。GUI 不导入 CLI，两个入口只依赖 Service。

## 扫描流程

1. 将输入路径转换为 `Path` 并展开 `~`。
2. 校验路径存在且为目录。
3. 使用栈进行递归遍历，避免深层目录导致递归调用过深。
4. 跳过软链接目录，降低循环风险。
5. 跳过命中 ignore 规则的目录。
6. 读取文件 stat，记录路径、大小、后缀和修改时间。
7. 文件消失、无权限或其他 OS 错误时跳过该文件。
8. 根据 `min_size` 过滤小文件。

## 分析流程

分析层只依赖 `list[FileInfo]`：

- `get_summary` 汇总总大小、文件数、估算文件夹数和扫描耗时。
- `get_largest_files` 按文件大小降序排序。
- `get_type_stats` 按小写后缀聚合，无后缀文件归类为 `[no extension]`。
- `get_folder_stats` 使用相对路径第一段统计扫描根目录下一级子文件夹占用，根目录直接文件归类为 `[root files]`。
- `get_size_distribution` 将文件分入固定大小区间，供柱状图展示。

## 报告生成流程

1. CLI 或 GUI 调用 Service 扫描并构建完整数据。
2. `report.py` 使用 Jinja2 加载 `report.html.j2`。
3. dataclass 和 `Path` 被转换为 JSON 友好的结构。
4. 模板渲染总览卡片、表格和图表数据。
5. 在线模式优先使用固定版本 ECharts 5.5.1；`--offline` 模式不加载外部脚本，使用内置 SVG 降级渲染器。
6. HTML 先写入目标目录中的临时文件，再通过原子替换发布，生成结果可直接在浏览器打开。

CLI 使用 Typer/Click 的标准未知选项校验。`--ignore` 是可重复的单值选项；自定义目录会和默认忽略目录合并，不通过 `ctx.args` 接收未声明参数。

## Snapshot 与对比流程

1. `diskvis snapshot` 调用现有 Service 获得 `AnalysisResult`。
2. `snapshot.py` 从结果中提取稳定字段，不重新扫描也不调用 Analyzer。
3. 快照保存版本、带时区时间、根路径、摘要、一级目录、Top 大文件和重复检测状态。
4. 一级目录和大文件同时保存相对路径，作为跨快照比较键。
5. `compare_snapshots` 对目录集合做并集：新增目录从 0 开始，删除目录归零。
6. Top 大文件按相对路径集合计算新增和移出。
7. `comparison.html.j2` 使用 Jinja2 渲染完全离线的 Liquid Glass 时间轴与排行。

## 错误处理策略

- 输入路径不存在或不是目录时，CLI 输出友好错误并以非 0 状态退出。
- 扫描中遇到 `PermissionError`、`FileNotFoundError` 或其他 `OSError` 时跳过当前文件或目录。
- 重复文件检测中无法读取的文件会被跳过。
- `parse_size` 对非法大小字符串抛出 `ValueError`，CLI 转换为 Typer 参数错误。
- 报告文本由 Jinja2 自动转义，注入浏览器的数据块会转义 HTML 特殊字符，降低文件名导致的 XSS 风险。
- 离线报告不依赖 CDN，即使网络不可用也会渲染 SVG 图表。
- 快照加载会校验必需对象、数组、字段类型以及大小/数量非负约束。
- 快照路径在对比 HTML 中继续使用 Jinja2 自动转义。
- 表格横向滚动被限制在 `.table-scroll` 容器内，长路径保持单词级可读性，完整 Hash 通过 `<details>` 展开。
- 项目默认不删除任何文件，只输出报告和建议。

## 性能优化思路

- 使用迭代式目录遍历，避免深层目录递归栈风险。
- 通过 ignore 规则跳过常见高噪声目录。
- 用 `min_size` 提前过滤文件，减少分析和导出数据量。
- 重复文件检测先按大小分组，只对候选组计算 SHA256。
- SHA256 使用分块读取，避免大文件一次性读入内存。
- HTML 报告只展示 Top N 图表数据，避免浏览器渲染过多节点。
- Playwright smoke test 使用 Chromium 检查离线 SVG、CDN 失败降级、XSS 防护和 390px/1440px 布局尺寸。

## v0.7 深度目录树与可靠性

`scanner.py` 通过 `os.scandir` 流式读取目录，并使用显式栈记录 enter/exit
事件，因此不依赖 Python 递归深度。每个 `DirectoryNode` 同时记录直接文件和
递归汇总值，`ScanResult` 还保留问题、进度和完整性信息。软链接目录不跟随，
权限错误、文件消失和目录变化会记录为 `ScanIssue` 后继续扫描。

```text
os.scandir -> FileInfo + DirectoryNode + ScanIssue
                         |
                         v
              AnalysisResult / ScanResult
                  |                 |
          CLI / GUI progress   Report tree crop
                  |                 |
             Snapshot v2 -> Deep comparison
```

报告展示树可以按最大深度、最大节点数、最小大小和占比裁剪；被裁剪的目录会
确定性地合并为“其他”，而 Snapshot 保存完整目录统计，避免展示限制污染历史
数据。普通报告不携带全量文件库存，`scan --json` 才启用完整清单导出。

取消采用 `CancellationToken` 协作式传播，在目录、文件和 SHA256 分块之间检查；
取消后不会写出不完整 HTML 或 Snapshot。GUI 只在主线程处理 Queue 事件，后台线程
只调用 Service 并回传进度，因此异常和取消都能恢复按钮状态。

重复检测使用 `(size, physical identity)` 预分组，再对稳定文件分块计算 SHA256。
同一个 inode 的硬链接只显示别名，不计入可释放空间；哈希前后 stat 不一致的文件
会被跳过，避免把正在写入的文件误报为重复。

Snapshot schema v2 保存平台、大小写敏感性、扫描参数、树完整性和错误摘要。加载
v1/v0.6 文件时只在内存中迁移并标记为不完整，不覆盖原 JSON；比较时不再无条件
`casefold`，会根据两份快照的路径语义产生明确警告。

## v0.8 本地 Web Dashboard

Dashboard 位于 `diskvis/dashboard/`，只依赖 Python 标准库 HTTP Server、Jinja2 和现有
Service。Web 请求不会直接调用 Scanner：`DashboardManager` 创建 `AnalysisOptions`，
后台线程调用 `analyze_directory()`，再把不可变结果建立为目录和文件查询索引。

```text
Browser -> Local HTTP API -> DashboardManager -> Service -> Scanner / Analyzer
                         |                    -> Snapshot
                         +-> CSV / JSON / HTML export
```

默认监听 `127.0.0.1`，不配置 CORS。POST 端点只接受有大小上限的 JSON；HTML 使用随机
nonce Content Security Policy，动态路径通过 `textContent` 写入。后台状态由锁保护，
同一时间只允许一个任务；取消通过 `CancellationToken` 传播，服务关闭时也会请求取消。

扫描进度以 50ms 为最小写入间隔，浏览器以 450ms 轮询，降低大型目录中锁和 DOM 更新
开销。目录索引在扫描完成后一次构建；搜索使用有限数量的 Top 结果，避免对匹配结果
进行全量排序。预计剩余时间优先使用最近同根目录 Snapshot 的文件数，首次扫描无法可靠
估算时明确显示“计算中”。

## v0.9 企业级可靠性

Dashboard 对外契约固定为 `/api/v1`，v0.8 的 `/api/*` 暂时作为兼容别名。每个错误响应
同时提供 HTTP 状态、稳定 `code`、可读 `error` 和 `request_id`；响应头包含应用版本与
API 版本。`/health` 用于确认进程存活，`/ready` 表示服务可接受请求，`/diagnostics`
提供运行时、日志和分析状态，且不返回完整文件清单。

```text
Browser -> Host / Origin validation -> API v1 -> DashboardManager
                                             |-> atomic result + indexes
                                             |-> paginated tree / search
                                             |-> export-only inventory
                                             +-> JSONL rotating log
```

服务只允许 IPv4 回环地址或 `localhost`，并限制 URI 长度、查询字段数、分页范围、JSON
内容类型、传输编码、请求体大小和 Socket 读取时间。随机 CSP nonce、同源策略、CSV
公式防护与 Jinja2 自动转义继续生效。日志按 JSON Lines 写入，每条 HTTP 记录包含请求 ID、
状态和耗时，单文件达到 2 MiB 后轮换并保留三个备份。

扫描结果与目录索引先在线程私有变量中完整构建，再在同一把锁内一次替换。重新扫描期间
旧结果仍可读取；新任务失败或取消时将其标记为 stale，但不会清空最近成功结果。
Snapshot 持久化是非致命步骤，失败会出现在状态和诊断中。JSON、Snapshot 和 HTML 均
使用同目录临时文件、`fsync` 与 `os.replace()`，避免进程中断留下半写入文件。
