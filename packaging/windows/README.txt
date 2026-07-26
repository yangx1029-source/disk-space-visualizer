Disk Space Visualizer v0.6.0
================================

推荐用法
--------
双击 DiskSpaceVisualizer.exe，选择要扫描的文件夹，然后点击“开始分析并生成报告”。
软件会生成最新版 Liquid Glass HTML 报告，默认使用离线图表，不需要联网。

如何确认版本
------------
GUI 窗口标题和 HTML 报告顶部都会显示 v0.6.0。
也可以在命令行执行：

    diskvis.exe --version

命令行工具
----------
    diskvis.exe scan PATH
    diskvis.exe report PATH --offline
    diskvis.exe duplicates PATH
    diskvis.exe snapshot PATH
    diskvis.exe compare OLD NEW --output comparison.html

注意
----
软件只分析文件，不会自动删除任何内容。
