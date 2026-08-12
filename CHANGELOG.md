# Changelog

## [0.9.0] - 2026-08-12

### Added

- 稳定的 Dashboard `/api/v1` 契约、兼容旧路由、请求 ID 和机器可读错误码。
- `/health`、`/ready`、`/api/v1/diagnostics` 运行状态接口与 Dashboard 系统诊断页。
- 搜索结果和目录直接文件的服务端分页及浏览器翻页控件。
- 每实例隔离的 JSON Lines 滚动日志，默认写入 `~/.diskvis/logs/dashboard.jsonl`。
- API 安全、日志、分页、故障恢复、原子写入和浏览器诊断页测试。

### Changed

- Dashboard 普通结果接口不再返回完整文件清单，CSV/JSON 导出仍保留全量数据。
- 重新扫描时继续展示最近一次成功结果；失败、取消或 Snapshot 写入失败不会清空结果。
- JSON、Snapshot 与 HTML 报告改为同目录临时文件加 `os.replace()` 的原子写入。
- Ruff 扩展启用命名、推导式、简化、Ruff 专项和代码质量规则。
- 版本、Windows 文件属性、便携包名称和文档统一升级到 `0.9.0`。

### Security

- Dashboard 仅允许 IPv4 回环地址或 `localhost`，校验 `Host` 与 `Origin` 以防 DNS 重绑定。
- 增加请求 URI、查询字段、分页、内容类型、传输编码、请求体大小和 Socket 超时限制。
- 响应增加 API 版本、请求 ID、跨源隔离和权限策略安全头。

## [0.8.0] - 2026-08-12

### Added

- `diskvis dashboard PATH` 本地 Web Dashboard，默认仅监听 `127.0.0.1`。
- 后台扫描状态、当前路径、文件速度、历史估算剩余时间和浏览器安全取消。
- 多层目录浏览、Treemap 下钻、面包屑、返回上级和当前目录占比。
- 文件/路径搜索、大文件过滤以及 CSV、JSON、完全离线 HTML 导出。
- Snapshot 趋势折线图、历史扫描记录、增长目录和进入大文件榜展示。
- Dashboard API、任务管理、趋势数据与 1440px/390px Chromium 测试。

### Changed

- 版本统一升级到 `0.8.0`，Windows 便携包包含 Dashboard 模板。
- Service 在重复检测阶段保留扫描文件、目录、字节和错误进度。
- CLI 与 Dashboard 的高频进度 UI 更新进行节流，减少大型扫描的显示开销。
- 报告展示树构建使用集合索引，避免节点去重的重复线性扫描。

### Security

- Dashboard 使用随机 nonce CSP、同源 API、JSON POST 和本机默认绑定。
- CSV 导出对公式起始字符进行防护，动态文件路径只通过安全 DOM 文本写入。

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
