from __future__ import annotations

from pathlib import Path

from diskvis.report import generate_comparison_report


def _comparison_data() -> dict[str, object]:
    return {
        "root_path": "demo",
        "roots_match": True,
        "old": {
            "timestamp": "2026-07-25T10:00:00+08:00",
            "root_path": "demo",
            "total_size_human": "1.00 GB",
            "file_count": 10,
            "folder_count": 2,
        },
        "new": {
            "timestamp": "2026-07-26T10:00:00+08:00",
            "root_path": "demo",
            "total_size_human": "2.00 GB",
            "file_count": 12,
            "folder_count": 2,
        },
        "total_size_delta": 1073741824,
        "total_size_delta_human": "+1.00 GB",
        "growing_folders": [
            {
                "name": "Downloads",
                "path": "demo/Downloads",
                "old_size_human": "1.00 GB",
                "new_size_human": "2.00 GB",
                "size_delta_human": "+1.00 GB",
                "bar_percent": 100,
            }
        ],
        "shrinking_folders": [],
        "added_files": [
            {
                "path": "demo/new.iso",
                "suffix": ".iso",
                "size_human": "1.00 GB",
            }
        ],
        "removed_files": [],
    }


def test_comparison_report_contains_liquid_glass_timeline_and_changes(
    tmp_path: Path,
) -> None:
    output = tmp_path / "comparison.html"

    generate_comparison_report(_comparison_data(), output)
    html = output.read_text(encoding="utf-8")

    assert "v0.7.0" in html
    assert "--glass-bg" in html
    assert "--glass-blur" in html
    assert "backdrop-filter: blur(var(--glass-blur)) saturate(165%)" in html
    assert "快照时间轴" in html
    assert "Top 增长目录" in html
    assert "Downloads" in html
    assert "+1.00 GB" in html
    assert "new.iso" in html
    assert 'id="themeToggle"' in html
    assert "localStorage.setItem" in html
    assert "@media (max-width: 420px)" in html


def test_comparison_report_escapes_dynamic_paths(tmp_path: Path) -> None:
    data = _comparison_data()
    data["added_files"] = [
        {
            "path": "</script><script>window.__xss = true</script>",
            "suffix": ".txt",
            "size_human": "1 B",
        }
    ]
    output = tmp_path / "safe.html"

    generate_comparison_report(data, output)
    html = output.read_text(encoding="utf-8")

    assert "&lt;/script&gt;" in html
    assert "</script><script>window.__xss = true</script>" not in html
