from pathlib import Path

from diskvis.report import generate_html_report


def _report_data() -> dict[str, object]:
    return {
        "generated_at": "2026-07-25 12:00:00",
        "summary": {
            "root": "demo",
            "total_size_human": "4 B",
            "total_files": 1,
            "total_folders": 1,
            "scan_seconds_text": "0.01s",
        },
        "largest_files": [{"path": "demo/file.bin", "size": 4, "size_human": "4 B"}],
        "type_stats": [],
        "folder_stats": [
            {
                "path": "demo/media",
                "count": 2,
                "total_size": 4,
                "total_size_human": "4 B",
            }
        ],
        "size_distribution": {},
        "duplicates": [],
        "duplicates_scanned": False,
        "duplicate_group_count": 0,
        "duplicate_potential_saved_size": 0,
        "duplicate_potential_saved_size_human": "0 B",
        "recommendations": ["检查大文件"],
    }


def test_generate_html_report_escapes_paths_and_script_data(tmp_path: Path) -> None:
    dangerous_path = "</script><script>alert(1)</script>"
    data = _report_data()
    data["largest_files"] = [
        {"path": dangerous_path, "size": 4, "size_human": "4 B"}
    ]
    output = tmp_path / "report.html"

    generate_html_report(data, output)
    html = output.read_text(encoding="utf-8")

    assert "\\u003c/script\\u003e" in html
    assert "&lt;/script&gt;" in html


def test_report_shows_duplicate_scan_not_run(tmp_path: Path) -> None:
    output = tmp_path / "not-scanned.html"

    generate_html_report(_report_data(), output, offline=True)
    html = output.read_text(encoding="utf-8")

    assert "未执行重复文件检测" in html
    assert "可释放 0 B" not in html
    assert "重复文件可节省" not in html


def test_report_shows_duplicate_scan_with_no_results(tmp_path: Path) -> None:
    data = _report_data()
    data["duplicates_scanned"] = True
    output = tmp_path / "no-duplicates.html"

    generate_html_report(data, output, offline=True)
    html = output.read_text(encoding="utf-8")

    assert "未发现重复文件" in html
    assert "可释放 0 B" not in html


def test_report_shows_duplicate_groups_and_savings(tmp_path: Path) -> None:
    data = _report_data()
    data["duplicates_scanned"] = True
    data["duplicate_group_count"] = 1
    data["duplicate_potential_saved_size"] = 4
    data["duplicate_potential_saved_size_human"] = "4 B"
    data["duplicates"] = [
        {
            "size": 4,
            "hash": "a" * 64,
            "files": ["demo/a.bin", "demo/b.bin"],
            "size_human": "4 B",
            "potential_saved_size": 4,
            "potential_saved_size_human": "4 B",
        }
    ]
    output = tmp_path / "duplicates.html"

    generate_html_report(data, output, offline=True)
    html = output.read_text(encoding="utf-8")

    assert "发现 1 组重复文件，可释放 4 B" in html
    assert "demo/a.bin" in html
    assert "demo/b.bin" in html


def test_report_has_theme_tokens_and_pinned_echarts(tmp_path: Path) -> None:
    online_output = tmp_path / "online.html"
    offline_output = tmp_path / "offline.html"

    generate_html_report(_report_data(), online_output, offline=False)
    generate_html_report(_report_data(), offline_output, offline=True)
    online_html = online_output.read_text(encoding="utf-8")
    offline_html = offline_output.read_text(encoding="utf-8")

    assert "v0.9.0" in online_html
    assert "--glass-bg" in online_html
    assert "--glass-border" in online_html
    assert "--glass-shadow" in online_html
    assert "--glass-blur" in online_html
    assert "--text-primary" in online_html
    assert "--text-secondary" in online_html
    assert "--accent-color" in online_html
    assert ".theme-dark" in online_html
    assert ".theme-light" in online_html
    assert "echarts@5.5.1/dist/echarts.min.js" in online_html
    assert "echarts@5/dist/echarts.min.js" not in online_html
    assert online_html.count("backgroundColor: 'transparent'") == 5
    assert "cdn.jsdelivr.net" not in offline_html


def test_report_contains_liquid_glass_material_and_motion(tmp_path: Path) -> None:
    output = tmp_path / "liquid-glass.html"

    generate_html_report(_report_data(), output, offline=True)
    html = output.read_text(encoding="utf-8")

    assert "backdrop-filter: blur(var(--glass-blur)) saturate(165%)" in html
    assert "-webkit-backdrop-filter" in html
    assert "radial-gradient" in html
    assert "inset 0 1px 0" in html
    assert "@keyframes ambient-shift" in html
    assert "@media (prefers-reduced-motion: reduce)" in html


def test_report_contains_persistent_theme_switcher(tmp_path: Path) -> None:
    output = tmp_path / "themes.html"

    generate_html_report(_report_data(), output, offline=True)
    html = output.read_text(encoding="utf-8")

    assert 'id="themeToggle"' in html
    assert "diskvis-theme" in html
    assert "localStorage.getItem" in html
    assert "localStorage.setItem" in html
    assert "prefers-color-scheme: light" in html
    assert "document.documentElement.dataset.theme" in html


def test_report_contains_treemap_data_and_svg_fallback(tmp_path: Path) -> None:
    output = tmp_path / "treemap.html"

    generate_html_report(_report_data(), output, offline=True)
    html = output.read_text(encoding="utf-8")

    assert 'id="treemapChart"' in html
    assert "const treemapData = folderStats.map" in html
    assert "type: 'treemap'" in html
    assert "renderFallbackTreemap" in html
    assert "treeBreadcrumbs" in html
    assert "treeSearch" in html
    assert "treeStats" in html
    assert '"path": "demo/media"' in html
    assert '"total_size": 4' in html


def test_report_defines_mobile_and_desktop_layouts(tmp_path: Path) -> None:
    output = tmp_path / "responsive.html"

    generate_html_report(_report_data(), output, offline=True)
    html = output.read_text(encoding="utf-8")

    assert "width: min(1220px, calc(100% - 32px))" in html
    assert "@media (max-width: 420px)" in html
    assert "overflow-x: auto" in html
    assert "max-width: 100%" in html
