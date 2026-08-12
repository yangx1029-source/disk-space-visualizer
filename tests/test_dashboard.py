from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from diskvis import __version__
from diskvis.dashboard.api import API_PREFIX, API_VERSION
from diskvis.dashboard.history import build_history_data
from diskvis.dashboard.manager import DashboardManager, DashboardScanOptions
from diskvis.dashboard.server import DashboardConfig, DashboardServer
from diskvis.service import AnalysisOptions, analyze_directory
from diskvis.snapshot import create_snapshot


def _wait_for_completion(manager: DashboardManager, timeout: float = 10) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.status()
        if status["state"] != "running":
            return status
        time.sleep(0.02)
    raise AssertionError("dashboard scan did not complete")


def _request_json(
    url: str,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    request_headers = dict(headers or {})
    if body is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        url,
        method=method,
        data=body,
        headers=request_headers,
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _error_payload(error: urllib.error.HTTPError) -> dict[str, object]:
    return json.loads(error.read().decode("utf-8"))


def test_dashboard_manager_reuses_service_and_exposes_views(tmp_path: Path) -> None:
    root = tmp_path / "scan-root"
    nested = root / "Projects" / "Archive"
    nested.mkdir(parents=True)
    (root / "root.txt").write_bytes(b"root")
    (nested / "large.bin").write_bytes(b"123456789")
    snapshots = tmp_path / "snapshots"
    manager = DashboardManager(
        DashboardScanOptions(root=root, snapshot_dir=snapshots, save_snapshot=True)
    )

    manager.start_scan()
    status = _wait_for_completion(manager)

    assert status["state"] == "completed"
    assert status["files_scanned"] == 2
    result = manager.result_data()
    assert result["summary"]["total_files"] == 2
    assert "files" not in result
    assert result["overview"]["disk_total"] > 0
    tree = manager.tree_data("")
    assert tree["directories"][0]["relative_path"] == "Projects"
    assert tree["file_page"]["total"] == 1
    nested_tree = manager.tree_data("Projects")
    assert nested_tree["breadcrumbs"][-1]["name"] == "Projects"
    search = manager.search("large", min_size=5)
    assert search["count"] == 1
    assert search["results"][0]["name"] == "large.bin"
    assert manager.export_csv_bytes().startswith(b"\xef\xbb\xbfpath,")
    json_export = json.loads(manager.export_json_bytes())
    assert json_export["summary"]["total_files"] == 2
    assert len(json_export["files"]) == 2
    assert b"Disk Space Visualizer" in manager.export_html_bytes()
    assert len(list(snapshots.glob("*.json"))) == 1
    manager.close()


def test_dashboard_search_and_directory_pagination(tmp_path: Path) -> None:
    root = tmp_path / "pagination-root"
    root.mkdir()
    for index in range(5):
        (root / f"file-{index}.bin").write_bytes(bytes(index + 1))
    manager = DashboardManager(
        DashboardScanOptions(root=root, snapshot_dir=tmp_path / "snapshots")
    )

    manager.start_scan()
    assert _wait_for_completion(manager)["state"] == "completed"

    first_page = manager.search("file", limit=2)
    second_page = manager.search("file", limit=2, offset=2)
    assert first_page["count"] == 5
    assert first_page["returned_count"] == 2
    assert first_page["has_more"] is True
    assert {item["name"] for item in first_page["results"]}.isdisjoint(
        item["name"] for item in second_page["results"]
    )
    directory_page = manager.tree_data("", offset=2, limit=2)
    assert directory_page["file_page"] == {
        "offset": 2,
        "limit": 2,
        "total": 5,
        "returned": 2,
        "has_more": True,
    }
    manager.close()


def test_snapshot_history_builds_trend_and_recent_changes(tmp_path: Path) -> None:
    root = tmp_path / "history-root"
    root.mkdir()
    first = root / "first.bin"
    first.write_bytes(b"123")
    old_result = analyze_directory(AnalysisOptions(root=root, top=10))
    old = create_snapshot(old_result)
    (root / "new.iso").write_bytes(b"1234567890")
    new_result = analyze_directory(AnalysisOptions(root=root, top=10))
    new = create_snapshot(new_result)

    data = build_history_data((old, new))

    assert data["record_count"] == 2
    assert data["total_size_delta"] == 10
    assert data["total_size_delta_human"] == "+10 B"
    assert data["recent_large_files"][0]["relative_path"] == "new.iso"


def test_dashboard_http_api_security_and_observability(tmp_path: Path) -> None:
    root = tmp_path / "api-root"
    (root / "Folder").mkdir(parents=True)
    (root / "Folder" / "file.txt").write_text("dashboard", encoding="utf-8")
    server = DashboardServer(
        DashboardConfig(
            root=root,
            port=0,
            snapshot_dir=tmp_path / "snapshots",
            log_dir=tmp_path / "logs",
            save_snapshot=False,
        )
    )
    server.start_background()
    try:
        assert _wait_for_completion(server.manager)["state"] == "completed"
        code, health = _request_json(f"{server.url}health")
        assert code == 200
        assert health["version"] == __version__
        assert health["api_version"] == API_VERSION

        code, result = _request_json(f"{server.url}{API_PREFIX}/result")
        assert code == 200
        assert result["summary"]["total_files"] == 1
        assert "files" not in result
        code, legacy_result = _request_json(f"{server.url}api/result")
        assert code == 200
        assert legacy_result["summary"] == result["summary"]
        code, tree = _request_json(f"{server.url}{API_PREFIX}/tree?path=Folder")
        assert code == 200
        assert tree["files"][0]["name"] == "file.txt"
        code, diagnostics = _request_json(f"{server.url}{API_PREFIX}/diagnostics")
        assert code == 200
        assert diagnostics["application"]["api_version"] == API_VERSION
        assert diagnostics["server"]["logging_enabled"] is True

        with urllib.request.urlopen(server.url, timeout=5) as response:
            html = response.read().decode("utf-8")
            assert response.headers["X-Frame-Options"] == "DENY"
            assert response.headers["X-DiskVis-API-Version"] == API_VERSION
            assert response.headers["X-Request-ID"]
            assert response.headers["Server"] == f"DiskVisDashboard/{__version__}"
            assert "script-src 'nonce-" in response.headers["Content-Security-Policy"]
        assert "Disk Space Visualizer" in html
        assert f'const API_PREFIX = "{API_PREFIX}"' in html
        assert "系统诊断" in html

        missing_content_type = urllib.request.Request(
            f"{server.url}{API_PREFIX}/scan", method="POST", data=b"{}"
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(missing_content_type, timeout=5)
        assert exc_info.value.code == 415
        error = _error_payload(exc_info.value)
        assert error["code"] == "UNSUPPORTED_MEDIA_TYPE"
        assert error["request_id"]

        bad_origin = urllib.request.Request(
            f"{server.url}{API_PREFIX}/status",
            headers={"Origin": "http://attacker.invalid"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(bad_origin, timeout=5)
        assert exc_info.value.code == 403
        assert _error_payload(exc_info.value)["code"] == "UNTRUSTED_ORIGIN"

        malformed_origin = urllib.request.Request(
            f"{server.url}{API_PREFIX}/status",
            headers={"Origin": "http://localhost:not-a-port"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(malformed_origin, timeout=5)
        assert exc_info.value.code == 400
        assert _error_payload(exc_info.value)["code"] == "INVALID_HEADER"

        address = urlsplit(server.url)
        connection = http.client.HTTPConnection(address.hostname, address.port, timeout=5)
        connection.request("GET", f"{API_PREFIX}/status", headers={"Host": "evil.test"})
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        assert response.status == 421
        assert payload["code"] == "UNTRUSTED_HOST"

        head_request = urllib.request.Request(f"{server.url}health", method="HEAD")
        with urllib.request.urlopen(head_request, timeout=5) as response:
            assert response.status == 200
            assert response.read() == b""

        connection = http.client.HTTPConnection(address.hostname, address.port, timeout=5)
        connection.request("TRACE", "/health")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        assert response.status == 405
        assert payload["code"] == "METHOD_NOT_ALLOWED"
    finally:
        server.close()
        server.close()

    assert server.log_path is not None
    records = [json.loads(line) for line in server.log_path.read_text(encoding="utf-8").splitlines()]
    assert any(item.get("event") == "server_started" for item in records)
    assert any(item.get("event") == "http_request" for item in records)
    assert any(item.get("event") == "server_stopped" for item in records)


def test_dashboard_preserves_last_successful_result_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "stable-result-root"
    root.mkdir()
    (root / "good.txt").write_text("good", encoding="utf-8")
    manager = DashboardManager(
        DashboardScanOptions(root=root, snapshot_dir=tmp_path / "snapshots")
    )
    first_task = manager.start_scan()
    assert _wait_for_completion(manager)["state"] == "completed"

    def fail_analysis(*_: object, **__: object) -> object:
        raise OSError("simulated read failure")

    monkeypatch.setattr("diskvis.dashboard.manager.analyze_directory", fail_analysis)
    second_task = manager.start_scan()
    status = _wait_for_completion(manager)

    assert second_task > first_task
    assert status["state"] == "error"
    assert status["has_result"] is True
    assert status["result_task_id"] == first_task
    assert status["result_stale"] is True
    assert manager.result_data()["summary"]["total_files"] == 1
    manager.close()


def test_snapshot_failure_does_not_discard_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "snapshot-failure-root"
    root.mkdir()
    (root / "file.txt").write_text("content", encoding="utf-8")
    manager = DashboardManager(
        DashboardScanOptions(root=root, snapshot_dir=tmp_path / "snapshots")
    )

    def fail_snapshot(*_: object, **__: object) -> Path:
        raise OSError("snapshot directory is read-only")

    monkeypatch.setattr("diskvis.dashboard.manager.save_snapshot", fail_snapshot)
    manager.start_scan()
    status = _wait_for_completion(manager)

    assert status["state"] == "completed"
    assert status["snapshot_error"] == "snapshot directory is read-only"
    assert manager.result_data()["summary"]["total_files"] == 1
    manager.close()


def test_dashboard_rejects_parallel_scans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "cancel-root"
    root.mkdir()
    manager = DashboardManager(
        DashboardScanOptions(root=root, snapshot_dir=tmp_path / "snapshots")
    )

    def slow_analysis(options: AnalysisOptions, **_: object) -> object:
        assert options.cancellation is not None
        while not options.cancellation.is_cancelled:
            time.sleep(0.01)
        options.cancellation.raise_if_cancelled()
        raise AssertionError("unreachable")

    monkeypatch.setattr("diskvis.dashboard.manager.analyze_directory", slow_analysis)
    manager.start_scan()
    with pytest.raises(RuntimeError, match="already running"):
        manager.start_scan()
    assert manager.cancel() is True
    status = _wait_for_completion(manager)
    assert status["state"] == "cancelled"
    with pytest.raises(RuntimeError, match="not ready"):
        manager.result_data()
    manager.close()


def test_dashboard_config_rejects_non_loopback_bind(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        DashboardConfig(root=tmp_path, host="0.0.0.0")


def test_dashboard_degrades_when_log_directory_is_unwritable(tmp_path: Path) -> None:
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupied", encoding="utf-8")
    server = DashboardServer(
        DashboardConfig(root=tmp_path, port=0, log_dir=blocked, save_snapshot=False)
    )
    server.start_background(start_scan=False)
    try:
        assert server.log_path is None
        assert server.logging_error
        code, diagnostics = _request_json(f"{server.url}{API_PREFIX}/diagnostics")
        assert code == 200
        assert diagnostics["server"]["logging_enabled"] is False
        assert diagnostics["server"]["logging_error"]
    finally:
        server.close()


def test_dashboard_scan_option_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="top"):
        DashboardScanOptions(root=tmp_path, snapshot_dir=tmp_path, top=0)
    with pytest.raises(ValueError, match="min_size"):
        DashboardScanOptions(root=tmp_path, snapshot_dir=tmp_path, min_size=-1)
    with pytest.raises(ValueError, match="max_depth"):
        DashboardScanOptions(root=tmp_path, snapshot_dir=tmp_path, max_depth=-1)
    with pytest.raises(ValueError, match="max_nodes"):
        DashboardScanOptions(root=tmp_path, snapshot_dir=tmp_path, max_nodes=0)
