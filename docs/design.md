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
6. HTML 文件写入目标路径，生成结果可直接在浏览器打开。

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
