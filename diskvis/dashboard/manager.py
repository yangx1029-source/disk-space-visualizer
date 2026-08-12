"""Thread-safe dashboard task state built on the application service layer."""

from __future__ import annotations

import csv
import io
import json
import logging
import shutil
import tempfile
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from ..exporter import to_jsonable
from ..formatter import format_size
from ..models import AnalysisCancelled, CancellationToken, DirectoryNode, FileInfo, ScanProgress
from ..report import generate_html_report
from ..scanner import DEFAULT_IGNORE_DIRS
from ..service import AnalysisOptions, AnalysisResult, analyze_directory
from ..snapshot import save_snapshot
from .history import build_history_data, load_snapshot_history


@dataclass(frozen=True)
class DashboardScanOptions:
    root: Path
    snapshot_dir: Path
    top: int = 20
    min_size: int = 0
    include_duplicates: bool = False
    ignore_dirs: tuple[str, ...] = tuple(sorted(DEFAULT_IGNORE_DIRS))
    max_depth: int | None = 8
    max_nodes: int | None = 1500
    save_snapshot: bool = True

    def __post_init__(self) -> None:
        if self.top < 1 or self.top > 500:
            raise ValueError("top must be between 1 and 500")
        if self.min_size < 0:
            raise ValueError("min_size must be non-negative")
        if self.max_depth is not None and self.max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        if self.max_nodes is not None and self.max_nodes < 1:
            raise ValueError("max_nodes must be at least 1")


DashboardState = Literal["idle", "running", "completed", "cancelled", "error"]


class DashboardManager:
    """Own one background analysis task and expose read-only dashboard views."""

    def __init__(
        self,
        options: DashboardScanOptions,
        logger: logging.Logger | None = None,
    ) -> None:
        self.options = options
        self._logger = logger or logging.getLogger("diskvis.dashboard.manager")
        self.root = Path(options.root).expanduser().resolve()
        self.snapshot_dir = Path(options.snapshot_dir).expanduser().resolve()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._token: CancellationToken | None = None
        self._result: AnalysisResult | None = None
        self._state: DashboardState = "idle"
        self._error: str | None = None
        self._progress = ScanProgress(phase="idle", current_path=self.root)
        self._started_monotonic = 0.0
        self._started_at: str | None = None
        self._completed_at: str | None = None
        self._completed_monotonic = 0.0
        self._task_id = 0
        self._result_task_id: int | None = None
        self._result_completed_at: str | None = None
        self._snapshot_path: Path | None = None
        self._snapshot_error: str | None = None
        self._cancellation_requested = False
        self._expected_files: int | None = self._history_file_estimate()
        self._directories: dict[str, DirectoryNode] = {}
        self._children: dict[str, list[DirectoryNode]] = {}
        self._files_by_parent: dict[str, list[FileInfo]] = {}
        self._files_by_size: tuple[FileInfo, ...] = ()
        self._last_progress_at = 0.0
        self._last_progress_phase = ""

    def _history_file_estimate(self) -> int | None:
        history = load_snapshot_history(self.snapshot_dir, self.root)
        return history[-1].summary.file_count if history else None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._state == "running"

    def start_scan(self) -> int:
        """Start a scan and return its monotonically increasing task id."""
        with self._lock:
            if self._state == "running":
                raise RuntimeError("an analysis is already running")
            self._task_id += 1
            task_id = self._task_id
            self._token = CancellationToken()
            self._state = "running"
            self._error = None
            self._snapshot_path = None
            self._snapshot_error = None
            self._cancellation_requested = False
            self._progress = ScanProgress(phase="scan", current_path=self.root)
            self._started_monotonic = time.monotonic()
            self._completed_monotonic = 0.0
            self._started_at = datetime.now().astimezone().isoformat(timespec="seconds")
            self._completed_at = None
            self._last_progress_at = 0.0
            self._last_progress_phase = ""
            token = self._token
            thread = threading.Thread(
                target=self._run_scan,
                args=(task_id, token),
                name=f"diskvis-dashboard-{task_id}",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            self._logger.info(
                "analysis started",
                extra={"event": "analysis_started", "task_id": task_id, "state": "running"},
            )
            return task_id

    def _on_progress(self, event: ScanProgress) -> None:
        now = time.monotonic()
        with self._lock:
            if event.phase == self._last_progress_phase and now - self._last_progress_at < 0.05:
                return
            self._progress = event
            self._last_progress_at = now
            self._last_progress_phase = event.phase

    def _run_scan(self, task_id: int, token: CancellationToken) -> None:
        try:
            result = analyze_directory(
                AnalysisOptions(
                    root=self.root,
                    top=self.options.top,
                    min_size=self.options.min_size,
                    ignore_dirs=self.options.ignore_dirs,
                    include_duplicates=self.options.include_duplicates,
                    max_depth=self.options.max_depth,
                    max_nodes=self.options.max_nodes,
                    include_inventory=True,
                    cancellation=token,
                ),
                on_progress=self._on_progress,
            )
            token.raise_if_cancelled()
            indexes = self._build_indexes(result)
            snapshot_path: Path | None = None
            snapshot_error: str | None = None
            if self.options.save_snapshot:
                try:
                    snapshot_path = save_snapshot(
                        result,
                        output_path=self._next_snapshot_path(),
                    )
                except (OSError, TypeError, ValueError) as exc:
                    snapshot_error = str(exc)
                    self._logger.warning(
                        "snapshot persistence failed",
                        extra={
                            "event": "snapshot_failed",
                            "task_id": task_id,
                            "error_type": type(exc).__name__,
                        },
                    )
        except AnalysisCancelled:
            self._finish_task(task_id, "cancelled")
            return
        except Exception as exc:
            self._logger.exception(
                "analysis failed",
                extra={
                    "event": "analysis_failed",
                    "task_id": task_id,
                    "state": "error",
                    "error_type": type(exc).__name__,
                },
            )
            self._finish_task(task_id, "error", error=str(exc))
            return
        with self._lock:
            if task_id != self._task_id:
                return
            self._result = result
            self._result_task_id = task_id
            self._result_completed_at = datetime.now().astimezone().isoformat(
                timespec="seconds"
            )
            (
                self._directories,
                self._children,
                self._files_by_parent,
                self._files_by_size,
            ) = indexes
            self._snapshot_path = snapshot_path
            self._snapshot_error = snapshot_error
            self._state = "completed"
            self._completed_at = self._result_completed_at
            self._completed_monotonic = time.monotonic()
            self._progress = ScanProgress(
                phase="complete",
                current_path=self.root,
                files_scanned=result.scanned_file_count,
                dirs_scanned=result.scanned_folder_count,
                bytes_scanned=int(result.data["summary"]["total_size"]),
                errors=int(result.data.get("scan_error_count", 0)),
            )
            self._expected_files = result.scanned_file_count
        self._logger.info(
            "analysis completed",
            extra={
                "event": "analysis_completed",
                "task_id": task_id,
                "state": "completed",
            },
        )

    def _finish_task(
        self,
        task_id: int,
        state: Literal["cancelled", "error"],
        error: str | None = None,
    ) -> None:
        with self._lock:
            if task_id != self._task_id:
                return
            self._state = state
            self._error = error
            self._completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
            self._completed_monotonic = time.monotonic()
            progress = self._progress
            self._progress = ScanProgress(
                phase=state,
                current_path=progress.current_path,
                files_scanned=progress.files_scanned,
                dirs_scanned=progress.dirs_scanned,
                bytes_scanned=progress.bytes_scanned,
                errors=progress.errors,
                duplicate_candidates=progress.duplicate_candidates,
                hashes_completed=progress.hashes_completed,
                hashes_total=progress.hashes_total,
            )
        self._logger.info(
            f"analysis {state}",
            extra={"event": f"analysis_{state}", "task_id": task_id, "state": state},
        )

    def _next_snapshot_path(self) -> Path:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        candidate = self.snapshot_dir / f"snapshot-{stamp}.json"
        counter = 2
        while candidate.exists():
            candidate = self.snapshot_dir / f"snapshot-{stamp}-{counter}.json"
            counter += 1
        return candidate

    def _build_indexes(
        self,
        result: AnalysisResult,
    ) -> tuple[
        dict[str, DirectoryNode],
        dict[str, list[DirectoryNode]],
        dict[str, list[FileInfo]],
        tuple[FileInfo, ...],
    ]:
        if result.scan_result is None:
            return {}, {}, {}, ()
        directories = {item.relative_path: item for item in result.scan_result.directories}
        children: dict[str, list[DirectoryNode]] = defaultdict(list)
        for node in result.scan_result.directories:
            if node.parent_relative_path is not None:
                children[node.parent_relative_path].append(node)
        for items in children.values():
            items.sort(key=lambda item: (-item.recursive_size, item.relative_path))
        files_by_parent: dict[str, list[FileInfo]] = defaultdict(list)
        for file in result.scan_result.files:
            try:
                relative = file.path.relative_to(result.scan_result.root).as_posix()
            except ValueError:
                relative = file.path.name
            parent = str(PurePosixPath(relative).parent)
            files_by_parent["" if parent == "." else parent].append(file)
        for items in files_by_parent.values():
            items.sort(key=lambda item: (-item.size, str(item.path).casefold()))
        files_by_size = tuple(
            sorted(
                result.scan_result.files,
                key=lambda item: (-item.size, str(item.path).casefold()),
            )
        )
        return directories, dict(children), dict(files_by_parent), files_by_size

    def cancel(self) -> bool:
        with self._lock:
            if self._state != "running" or self._token is None:
                return False
            self._cancellation_requested = True
            self._token.cancel()
            self._logger.info(
                "cancellation requested",
                extra={
                    "event": "cancellation_requested",
                    "task_id": self._task_id,
                    "state": "running",
                },
            )
            return True

    def close(self, timeout: float = 5.0) -> None:
        self.cancel()
        with self._lock:
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        if thread and thread.is_alive():
            self._logger.warning(
                "analysis worker did not stop before timeout",
                extra={"event": "worker_stop_timeout", "task_id": self._task_id},
            )

    def status(self) -> dict[str, Any]:
        with self._lock:
            progress = self._progress
            end = (
                time.monotonic()
                if self._state == "running"
                else self._completed_monotonic
            )
            elapsed = max(0.0, end - self._started_monotonic) if end else 0.0
            speed = progress.files_scanned / elapsed if elapsed > 0 else 0.0
            eta = None
            if (
                self._state == "running"
                and progress.phase == "scan"
                and self._expected_files
                and speed > 0
                and self._expected_files > progress.files_scanned
            ):
                eta = (self._expected_files - progress.files_scanned) / speed
            return {
                "task_id": self._task_id,
                "state": self._state,
                "phase": progress.phase,
                "root": str(self.root),
                "current_path": str(progress.current_path) if progress.current_path else None,
                "files_scanned": progress.files_scanned,
                "dirs_scanned": progress.dirs_scanned,
                "bytes_scanned": progress.bytes_scanned,
                "bytes_scanned_human": format_size(progress.bytes_scanned),
                "errors": progress.errors,
                "duplicate_candidates": progress.duplicate_candidates,
                "hashes_completed": progress.hashes_completed,
                "hashes_total": progress.hashes_total,
                "files_per_second": round(speed, 1),
                "estimated_remaining_seconds": round(eta) if eta is not None else None,
                "expected_files": self._expected_files,
                "elapsed_seconds": round(elapsed, 3),
                "started_at": self._started_at,
                "completed_at": self._completed_at,
                "error": self._error,
                "snapshot_path": str(self._snapshot_path) if self._snapshot_path else None,
                "snapshot_error": self._snapshot_error,
                "cancellation_requested": self._cancellation_requested,
                "has_result": self._result is not None,
                "result_task_id": self._result_task_id,
                "result_stale": (
                    self._result is not None and self._result_task_id != self._task_id
                ),
            }

    def result_data(self, include_inventory: bool = False) -> dict[str, Any]:
        """Return dashboard data, excluding the full inventory unless exporting."""
        with self._lock:
            result = self._result
            result_task_id = self._result_task_id
            result_completed_at = self._result_completed_at
        if result is None:
            raise RuntimeError("analysis result is not ready")
        data = dict(result.data)
        if not include_inventory:
            data.pop("files", None)
        try:
            usage = shutil.disk_usage(self.root)
        except OSError:
            disk_total = disk_used = disk_free = 0
            disk_available = False
        else:
            disk_total, disk_used, disk_free = usage
            disk_available = True
        data["overview"] = {
            "root": str(self.root),
            "disk_available": disk_available,
            "disk_total": disk_total,
            "disk_total_human": format_size(disk_total),
            "disk_used": disk_used,
            "disk_used_human": format_size(disk_used),
            "disk_free": disk_free,
            "disk_free_human": format_size(disk_free),
            "disk_used_percent": round(disk_used / max(1, disk_total) * 100, 1),
            "last_scan_time": result_completed_at,
            "result_task_id": result_task_id,
        }
        return to_jsonable(data)

    def tree_data(
        self,
        relative_path: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        normalized = relative_path.replace("\\", "/").strip("/")
        with self._lock:
            result = self._result
            if result is None:
                raise RuntimeError("analysis result is not ready")
            current = self._directories.get(normalized)
            children = list(self._children.get(normalized, ()))
            all_files = self._files_by_parent.get(normalized, ())
            total_files = len(all_files)
            files = list(all_files[offset : offset + limit])
            parent = current.parent_relative_path if current else None
            parent_node = self._directories.get(parent) if parent is not None else None
        if current is None:
            raise KeyError(f"directory not found: {relative_path}")
        current_size = max(1, current.recursive_size)
        parent_size = parent_node.recursive_size if parent_node else current_size
        root_name = (
            result.scan_result.root.name
            if result.scan_result is not None
            else self.root.name
        )
        breadcrumbs = [{"name": root_name or str(self.root), "path": ""}]
        if normalized:
            parts = PurePosixPath(normalized).parts
            for index, part in enumerate(parts):
                breadcrumbs.append({"name": part, "path": "/".join(parts[: index + 1])})
        return {
            "current": self._directory_payload(current, parent_size),
            "parent_path": parent,
            "breadcrumbs": breadcrumbs,
            "directories": [self._directory_payload(item, current_size) for item in children],
            "files": [self._file_payload(item) for item in files],
            "truncated_files": offset + len(files) < total_files,
            "file_page": {
                "offset": offset,
                "limit": limit,
                "total": total_files,
                "returned": len(files),
                "has_more": offset + len(files) < total_files,
            },
        }

    @staticmethod
    def _directory_payload(node: DirectoryNode, parent_size: int) -> dict[str, Any]:
        return {
            "name": node.display_name,
            "relative_path": node.relative_path,
            "direct_file_count": node.direct_file_count,
            "recursive_file_count": node.recursive_file_count,
            "direct_size": node.direct_size,
            "direct_size_human": format_size(node.direct_size),
            "recursive_size": node.recursive_size,
            "recursive_size_human": format_size(node.recursive_size),
            "child_count": len(node.child_directories),
            "error_count": node.error_count,
            "percent": round(node.recursive_size / max(1, parent_size) * 100, 2),
        }

    def search(
        self,
        query: str,
        min_size: int = 0,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        if len(query) > 512:
            raise ValueError("query must not exceed 512 characters")
        if min_size < 0:
            raise ValueError("min_size must be non-negative")
        if offset < 0 or offset > 100_000:
            raise ValueError("offset is outside the allowed range")
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        with self._lock:
            result = self._result
            files_by_size = self._files_by_size
        if result is None:
            raise RuntimeError("analysis result is not ready")
        if result.scan_result is None:
            return {
                "query": query,
                "results": [],
                "count": 0,
                "returned_count": 0,
                "offset": offset,
                "limit": limit,
                "has_more": False,
            }
        needle = query.casefold().strip()
        total = 0
        page: list[FileInfo] = []
        for file in files_by_size:
            if file.size < min_size:
                break
            if needle and needle not in str(file.path).casefold():
                continue
            if total >= offset and len(page) < limit:
                page.append(file)
            total += 1
        return {
            "query": query,
            "min_size": min_size,
            "count": total,
            "returned_count": len(page),
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < total,
            "results": [self._file_payload(file) for file in page],
        }

    def history_data(self) -> dict[str, Any]:
        return build_history_data(load_snapshot_history(self.snapshot_dir, self.root))

    def export_json_bytes(self) -> bytes:
        return json.dumps(
            self.result_data(include_inventory=True), ensure_ascii=False, indent=2
        ).encode("utf-8")

    def export_csv_bytes(self) -> bytes:
        result = self._require_result()
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["path", "size_bytes", "size_human", "suffix", "modified_time"])
        if result.scan_result:
            for file in result.scan_result.files:
                writer.writerow(
                    [
                        self._csv_safe(str(file.path)),
                        file.size,
                        format_size(file.size),
                        file.suffix,
                        file.modified_time,
                    ]
                )
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    @staticmethod
    def _csv_safe(value: str) -> str:
        return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value

    def export_html_bytes(self) -> bytes:
        result = self._require_result()
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        try:
            generate_html_report(result.data, temporary_path, offline=True)
            return temporary_path.read_bytes()
        finally:
            temporary_path.unlink(missing_ok=True)

    def _require_result(self) -> AnalysisResult:
        with self._lock:
            if self._result is None:
                raise RuntimeError("analysis result is not ready")
            return self._result

    def _file_payload(self, file: FileInfo) -> dict[str, Any]:
        try:
            relative = file.path.relative_to(self.root).as_posix()
        except ValueError:
            relative = file.path.name
        return {
            "name": file.path.name,
            "path": str(file.path),
            "relative_path": relative,
            "size": file.size,
            "size_human": format_size(file.size),
            "suffix": file.suffix,
            "modified_time": file.modified_time,
        }
