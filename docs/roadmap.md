# Roadmap

当前版本：`v0.9.0`。

## v0.1.0 基础扫描

- 递归扫描目录并安全处理权限错误。
- 统计文件数、文件夹数和总大小。
- 支持忽略目录与最小文件大小过滤。
- 使用 Rich 显示进度与终端表格。

## v0.2.0 文件类型统计

- 按扩展名聚合文件类型。
- 统计一级目录空间占用。
- 输出最大文件 Top N。
- 支持结构化 JSON 导出。

## v0.3.0 HTML 报告

- 使用 Jinja2 生成单文件 HTML 报告。
- 使用 ECharts 展示饼图、柱状图和大小分布图。
- 增加清理建议与响应式表格。
- 提供断网时可用的 SVG 图表降级。

## v0.4.0 重复文件检测

- 先按文件大小预分组。
- 仅对候选文件分块计算 SHA256。
- 输出重复文件组与理论可节省空间。
- 建立 Service 层，统一 CLI 与 GUI 业务流程。
- 完成 Windows GUI/CLI 可执行文件构建配置。

## v0.5.0 Liquid Glass Report

- 完成 iOS Liquid Glass 风格的 HTML 报告设计系统。
- 增加一级目录空间 Treemap 与点击详情。
- 完成深色/浅色主题切换、系统主题跟随与本地持久化。
- 保持 ECharts 5.5.1 在线图表和完整 SVG 离线降级。
- 完成 390px 与 1440px 真实浏览器布局验证。

## v0.6.0 Snapshot Comparison

- 保存、加载并校验带时区时间戳的 JSON 扫描快照。
- 比较两次扫描的总空间和一级目录增长/减少。
- 识别 Top 大文件新增与移出。
- 使用 Rich 展示变化排行。
- 生成带时间轴的 Liquid Glass HTML 对比报告。

## v0.7.0 Deep Tree & Reliability

- 增加深度目录树分析和多层级下钻。
- 增加结构化进度、取消、硬链接语义和文件稳定性保护。
- 完成 Snapshot schema v2 与深层目录比较。

## v0.8.0 Web Dashboard

- 仅绑定本机的后台扫描服务和 Liquid Glass Dashboard。
- 深度目录树、Treemap 下钻、搜索、取消和导出。
- Snapshot 趋势图、历史记录、增长目录和最近大文件榜变化。
- Dashboard API 与 390px/1440px Chromium 自动化测试。

## v0.9.0 Enterprise Hardening

- 固化 `/api/v1`，提供稳定错误码、请求 ID、健康检查和运行诊断。
- 增加 Host/Origin 校验、请求限制和本机结构化滚动日志。
- 搜索与目录文件分页，避免普通结果接口传输全量文件清单。
- 原子持久化 JSON、Snapshot 与 HTML 报告。
- 重新扫描失败、取消和 Snapshot 持久化失败时保留最近成功结果。
- 扩展 Ruff、API、故障恢复与真实浏览器质量门槛。

## v1.0.0 Stable Desktop Release

- 完成 GUI 状态机测试和大型目录性能基准。
- 定义 API 弃用周期、Snapshot 数据迁移和错误恢复长期支持策略。
- 提供签名 Windows 构建、安装说明和发布后附件校验。
- 扩展 Firefox/WebKit 兼容验证并完成稳定性文档。
