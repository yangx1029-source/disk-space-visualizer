from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from typer.testing import CliRunner

from diskvis.cli import app
from diskvis.dashboard.server import DashboardConfig
from diskvis.service import AnalysisOptions, analyze_directory

runner = CliRunner()


def test_version_option() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "diskvis 0.9.0"


def test_dashboard_command_starts_local_server(
    tmp_path: Path, monkeypatch: Any
) -> None:
    calls: dict[str, object] = {}

    class FakeServer:
        url = "http://127.0.0.1:43210/"

        def __init__(self, config: object) -> None:
            calls["config"] = config

        def serve_forever(self, open_browser: bool = True) -> None:
            calls["open_browser"] = open_browser

        def close(self) -> None:
            calls["closed"] = True

    monkeypatch.setattr("diskvis.dashboard.server.DashboardServer", FakeServer)
    result = runner.invoke(
        app,
        [
            "dashboard",
            str(tmp_path),
            "--port",
            "0",
            "--no-open-browser",
            "--no-save-snapshot",
            "--log-dir",
            str(tmp_path / "logs"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Dashboard ready:" in result.output
    assert calls["open_browser"] is False
    assert calls["closed"] is True
    assert str(cast(DashboardConfig, calls["config"]).log_dir) == str(tmp_path / "logs")


def test_scan_command_exports_json(tmp_path: Path) -> None:
    scan_root = tmp_path / "scan-root"
    scan_root.mkdir()
    (scan_root / "small.txt").write_text("abc", encoding="utf-8")
    (scan_root / "nested").mkdir()
    (scan_root / "nested" / "large.bin").write_bytes(b"123456")
    output = tmp_path / "result.json"

    result = runner.invoke(
        app,
        ["scan", str(scan_root), "--top", "1", "--json", str(output)],
        terminal_width=240,
    )

    assert result.exit_code == 0, result.output
    assert "Scan Summary" in result.output
    assert "JSON exported:" in result.output
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"]["root"] == str(scan_root.resolve())
    assert data["summary"]["total_files"] == 2
    assert data["summary"]["total_folders"] == 2
    assert data["summary"]["total_size"] == 9
    assert len(data["largest_files"]) == 1
    assert data["largest_files"][0]["path"].endswith("large.bin")


def test_scan_command_matches_service_result(tmp_path: Path) -> None:
    scan_root = tmp_path / "consistent-root"
    scan_root.mkdir()
    (scan_root / "one.txt").write_bytes(b"123")
    (scan_root / "two.bin").write_bytes(b"123456")
    output = tmp_path / "consistent.json"

    service_result = analyze_directory(AnalysisOptions(root=scan_root, top=2))
    cli_result = runner.invoke(
        app,
        ["scan", str(scan_root), "--top", "2", "--json", str(output)],
        terminal_width=240,
    )
    cli_data = json.loads(output.read_text(encoding="utf-8"))

    assert cli_result.exit_code == 0, cli_result.output
    assert cli_data["summary"]["total_size"] == service_result.data["summary"]["total_size"]
    assert cli_data["summary"]["total_files"] == service_result.scanned_file_count
    assert cli_data["summary"]["total_folders"] == service_result.scanned_folder_count
    assert [
        Path(item["path"]).name for item in cli_data["largest_files"]
    ] == [
        Path(item["path"]).name for item in service_result.data["largest_files"]
    ]


def test_ignore_can_repeat_and_keeps_default_rules(tmp_path: Path) -> None:
    scan_root = tmp_path / "ignore-root"
    scan_root.mkdir()
    (scan_root / "keep.txt").write_text("keep", encoding="utf-8")
    for directory in (".git", "custom-one", "custom-two"):
        ignored = scan_root / directory
        ignored.mkdir()
        (ignored / "hidden.txt").write_text("hidden", encoding="utf-8")
    output = tmp_path / "ignore-result.json"

    result = runner.invoke(
        app,
        [
            "scan",
            str(scan_root),
            "--ignore",
            "custom-one",
            "--ignore",
            "custom-two",
            "--json",
            str(output),
        ],
        terminal_width=240,
    )

    assert result.exit_code == 0, result.output
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"]["total_files"] == 1
    assert data["largest_files"][0]["path"].endswith("keep.txt")


def test_report_command_includes_duplicate_files(tmp_path: Path) -> None:
    scan_root = tmp_path / "report-root"
    scan_root.mkdir()
    (scan_root / "first.bin").write_bytes(b"duplicate")
    (scan_root / "second.bin").write_bytes(b"duplicate")
    output = tmp_path / "report.html"

    result = runner.invoke(
        app,
        [
            "report",
            str(scan_root),
            "--output",
            str(output),
            "--include-duplicates",
        ],
        terminal_width=240,
    )

    assert result.exit_code == 0, result.output
    assert "HTML report generated:" in result.output
    html = output.read_text(encoding="utf-8")
    assert "重复文件组" in html
    assert "first.bin" in html
    assert "second.bin" in html
    assert "9 B" in html


def test_report_command_offline_uses_embedded_fallback(tmp_path: Path) -> None:
    scan_root = tmp_path / "offline-root"
    scan_root.mkdir()
    (scan_root / "file.txt").write_text("offline", encoding="utf-8")
    output = tmp_path / "offline-report.html"

    result = runner.invoke(
        app,
        ["report", str(scan_root), "--output", str(output), "--offline"],
        terminal_width=240,
    )

    assert result.exit_code == 0, result.output
    html = output.read_text(encoding="utf-8")
    assert "https://cdn.jsdelivr.net/npm/echarts" not in html
    assert "renderFallbackCharts" in html
    assert "离线模式" in html


def test_duplicates_command_prints_paths_and_savings(tmp_path: Path) -> None:
    scan_root = tmp_path / "duplicates-root"
    scan_root.mkdir()
    (scan_root / "one.bin").write_bytes(b"same")
    (scan_root / "two.bin").write_bytes(b"same")

    result = runner.invoke(
        app,
        ["duplicates", str(scan_root), "--top", "1"],
        terminal_width=240,
    )

    assert result.exit_code == 0, result.output
    unwrapped_output = result.output.replace("\n", "")
    assert "Duplicate Groups" in result.output
    assert str(scan_root / "one.bin") in unwrapped_output
    assert str(scan_root / "two.bin") in unwrapped_output
    assert "Potential saved space:" in result.output
    assert "4 B" in result.output


def test_scan_command_reports_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    result = runner.invoke(app, ["scan", str(missing)])

    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "path does not exist" in result.output


def test_scan_command_rejects_invalid_min_size(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path), "--min-size", "large"])

    assert result.exit_code == 2
    assert "Invalid value" in result.output
    assert "invalid size" in result.output


def test_snapshot_command_saves_structured_json(tmp_path: Path) -> None:
    scan_root = tmp_path / "snapshot-root"
    folder = scan_root / "Downloads"
    folder.mkdir(parents=True)
    (folder / "archive.zip").write_bytes(b"snapshot")
    output = tmp_path / "snapshot.json"

    result = runner.invoke(
        app,
        ["snapshot", str(scan_root), "--output", str(output)],
        terminal_width=240,
    )

    assert result.exit_code == 0, result.output
    assert "Snapshot saved:" in result.output
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["metadata"]["root_path"] == str(scan_root.resolve())
    assert data["summary"]["total_size"] == 8
    assert data["summary"]["file_count"] == 1
    assert data["folders"][0]["name"] == "Downloads"
    assert data["files"][0]["path"].endswith("archive.zip")


def test_compare_command_prints_changes_and_generates_html(
    tmp_path: Path,
) -> None:
    scan_root = tmp_path / "compare-root"
    folder = scan_root / "Downloads"
    folder.mkdir(parents=True)
    (folder / "existing.txt").write_bytes(b"old")
    old_snapshot = tmp_path / "old.json"
    new_snapshot = tmp_path / "new.json"
    html_output = tmp_path / "comparison.html"

    old_result = runner.invoke(
        app,
        ["snapshot", str(scan_root), "--output", str(old_snapshot)],
        terminal_width=240,
    )
    (folder / "new.iso").write_bytes(b"0123456789")
    new_result = runner.invoke(
        app,
        ["snapshot", str(scan_root), "--output", str(new_snapshot)],
        terminal_width=240,
    )
    compare_result = runner.invoke(
        app,
        [
            "compare",
            str(old_snapshot),
            str(new_snapshot),
            "--output",
            str(html_output),
        ],
        terminal_width=240,
    )

    assert old_result.exit_code == 0, old_result.output
    assert new_result.exit_code == 0, new_result.output
    assert compare_result.exit_code == 0, compare_result.output
    assert "Space Change" in compare_result.output
    assert "Top Growing Folders" in compare_result.output
    assert "New Large Files" in compare_result.output
    assert "new.iso" in compare_result.output.replace("\n", "")
    assert "Comparison report generated:" in compare_result.output
    html = html_output.read_text(encoding="utf-8")
    assert "磁盘空间历史对比" in html
    assert "new.iso" in html


def test_all_commands_reject_unknown_options(tmp_path: Path) -> None:
    for command in ("scan", "report", "duplicates", "snapshot", "dashboard"):
        result = runner.invoke(app, [command, str(tmp_path), "--tpo", "5"])

        assert result.exit_code == 2, (command, result.output)
        assert "No such option" in result.output


def test_unknown_option_value_is_not_treated_as_ignore_directory(tmp_path: Path) -> None:
    for command in ("scan", "report", "duplicates", "snapshot", "dashboard"):
        result = runner.invoke(app, [command, str(tmp_path), "--foobar", "skip"])

        assert result.exit_code == 2, (command, result.output)
        assert "No such option" in result.output
