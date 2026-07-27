# Changelog

## [0.7.0] - 2026-07-27

### Added

- 深度目录树扫描与可下钻 Treemap，支持搜索、面包屑、返回、移动端布局和确定性“其他”聚合。
- 结构化扫描进度、错误记录、协作式取消和 GUI Cancel 工作流。
- Snapshot schema v2，保存完整目录树、平台路径语义、扫描参数和完整性信息。
- 深层目录比较、进入/离开 Top 文件、大小变化文件和路径语义警告。
- 硬链接别名识别、文件稳定性校验和更保守的可释放空间计算。

### Changed

- `diskvis.version` 成为唯一版本来源，CLI、GUI、报告和 Windows 元数据统一为 `0.7.0`。
- 普通报告数据不再携带全量文件清单；只有 `scan --json` 输出完整清单。
- Scanner 使用 `os.scandir` 流式遍历，保留旧 `scan_directory()` API 兼容性。
- CI 增加多 Python 版本、平台路径、构建和依赖检查；新增 tag 驱动发布工作流。

### Compatibility

- v0.6/v1 Snapshot JSON 可以读取并参与比较，加载后标记为不完整树；不会改写原文件。

本项目的所有重要变更都会记录在此文件中。版本格式遵循
[Semantic Versioning](https://semver.org/)。

## [0.6.0] - 2026-07-26

### Added

- 基于 `AnalysisResult` 的版本化 JSON Snapshot 系统。
- `diskvis snapshot PATH` 命令及 `.diskvis/snapshots/` 默认历史目录。
- `diskvis compare OLD NEW` 历史差异命令。
- 一级目录增长、减少与整目录删除计算。
- Top 大文件新增和移出识别。
- 带时间轴、变化排行和主题切换的 Liquid Glass 对比报告。
- Snapshot schema、保存加载、差异算法、CLI 和 HTML 安全测试。
- GUI、CLI、HTML 报告与 Windows 文件属性中的统一 `v0.6.0` 标识。
- Windows 盘符根目录的可读报告文件名，例如 `E-report.html`。

### Changed

- CLI 增加 `snapshot` 与 `compare`，现有扫描和报告命令保持兼容。
- wheel 同时打包当前扫描报告与历史对比报告模板。
- README、Roadmap 和版本元数据更新至 v0.6.0。
- Windows GUI/CLI 重新构建，并提供可直接分发的便携压缩包。

### Security

- Snapshot 加载执行结构、类型和非负数值校验。
- 对比报告继续使用 Jinja2 自动转义，不信任快照中的路径文本。

## [0.5.0] - 2026-07-26

### Added

- iOS Liquid Glass 风格 HTML 报告设计系统。
- 基于一级目录统计数据的 ECharts Treemap。
- 完全离线可用的 SVG Treemap 与其余图表降级渲染。
- 深色/浅色主题切换、`prefers-color-scheme` 跟随和 `localStorage` 持久化。
- 顶部悬浮导航、轻量入场动画与移动端响应式布局。
- Liquid Glass、主题、Treemap、XSS 和 390px/1440px 浏览器测试。

### Changed

- HTML 报告图表统一使用透明背景和主题化 tooltip。
- 报告卡片升级为带模糊、饱和、反射和内外高光的玻璃材质。
- README、Roadmap、示例报告与展示截图更新到 v0.5.0。

### Security

- 保留 Jinja2 自动转义与脚本 JSON 安全编码。
- ECharts HTML tooltip 对动态路径执行二次转义。

## [0.4.0] - 2026-07-26

### Added

- 独立 Service 业务层，CLI 与 GUI 统一调用。
- 重复文件检测的三态报告展示。
- CLI 端到端测试和 HTML 浏览器 smoke tests。
- Windows GUI 与 CLI 的 PyInstaller 构建流程。
- Ruff 代码质量配置。

## [0.3.0]

### Added

- Jinja2 + ECharts HTML 可视化报告。
- 在线图表失败时的 SVG 降级模式。

## [0.2.0]

### Added

- 文件类型、一级目录、最大文件和大小区间统计。
- JSON 数据导出。

## [0.1.0]

### Added

- 跨平台目录扫描、忽略规则和最小大小过滤。
- Typer CLI 与 Rich 进度、表格输出。
