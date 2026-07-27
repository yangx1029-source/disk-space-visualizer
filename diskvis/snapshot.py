"""Versioned snapshot persistence and deep history comparison."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__
from .exporter import export_json
from .formatter import format_size
from .service import AnalysisResult

CURRENT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class SnapshotMetadata:
    """Identity, scan semantics, and completeness information."""

    version: str
    timestamp: str
    root_path: str
    schema_version: int = 1
    app_version: str = ""
    platform: str = ""
    case_sensitive: bool = True
    scan_parameters: dict[str, Any] = field(default_factory=dict)
    tree_complete: bool = False
    tree_limited: bool = False
    error_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SnapshotSummary:
    total_size: int
    file_count: int
    folder_count: int
    error_count: int = 0


@dataclass(frozen=True)
class SnapshotFolder:
    """One complete directory aggregate (or a v1 first-level folder)."""

    name: str
    path: str
    relative_path: str
    file_count: int
    total_size: int
    depth: int = 1
    parent_relative_path: str | None = None
    direct_file_count: int = 0
    recursive_file_count: int | None = None
    direct_size: int = 0
    recursive_size: int | None = None
    error_count: int = 0

    def __post_init__(self) -> None:
        if self.recursive_file_count is None:
            object.__setattr__(self, "recursive_file_count", self.file_count)
        if self.recursive_size is None:
            object.__setattr__(self, "recursive_size", self.total_size)


@dataclass(frozen=True)
class SnapshotFile:
    path: str
    relative_path: str
    size: int
    suffix: str
    modified_time: float


@dataclass(frozen=True)
class DuplicateStatus:
    scanned: bool
    group_count: int
    potential_saved_size: int


@dataclass(frozen=True)
class Snapshot:
    metadata: SnapshotMetadata
    summary: SnapshotSummary
    folders: tuple[SnapshotFolder, ...]
    files: tuple[SnapshotFile, ...]
    duplicates: DuplicateStatus

    def to_dict(self) -> dict[str, Any]:
        is_v2 = self.metadata.schema_version >= CURRENT_SCHEMA_VERSION
        metadata = {
            "schema_version": self.metadata.schema_version,
            "app_version": self.metadata.app_version or self.metadata.version,
            "timestamp": self.metadata.timestamp,
            "root_path": self.metadata.root_path,
            "platform": self.metadata.platform or platform.system().lower(),
            "case_sensitive": self.metadata.case_sensitive,
            "scan_parameters": self.metadata.scan_parameters,
            "tree_complete": self.metadata.tree_complete,
            "tree_limited": self.metadata.tree_limited,
            "error_summary": self.metadata.error_summary,
        }
        if not is_v2:
            metadata = {
                "version": self.metadata.version,
                "timestamp": self.metadata.timestamp,
                "root_path": self.metadata.root_path,
            }
        summary = {
            "total_size": self.summary.total_size,
            "file_count": self.summary.file_count,
            "folder_count": self.summary.folder_count,
        }
        if is_v2:
            summary["error_count"] = self.summary.error_count
        folders = []
        for folder in self.folders:
            item = {
                "name": folder.name,
                "path": folder.path,
                "relative_path": folder.relative_path,
                "file_count": folder.file_count,
                "total_size": folder.total_size,
            }
            if is_v2:
                item.update(
                    {
                        "depth": folder.depth,
                        "parent_relative_path": folder.parent_relative_path,
                        "direct_file_count": folder.direct_file_count,
                        "recursive_file_count": folder.recursive_file_count,
                        "direct_size": folder.direct_size,
                        "recursive_size": folder.recursive_size,
                        "error_count": folder.error_count,
                    }
                )
            folders.append(item)
        return {
            "metadata": metadata,
            "summary": summary,
            "folders": folders,
            "files": [
                {
                    "path": file.path,
                    "relative_path": file.relative_path,
                    "size": file.size,
                    "suffix": file.suffix,
                    "modified_time": file.modified_time,
                }
                for file in self.files
            ],
            "duplicates": {
                "scanned": self.duplicates.scanned,
                "group_count": self.duplicates.group_count,
                "potential_saved_size": self.duplicates.potential_saved_size,
            },
        }


@dataclass(frozen=True)
class FolderChange:
    name: str
    path: str
    relative_path: str
    old_size: int
    new_size: int
    size_delta: int
    old_file_count: int
    new_file_count: int
    old_error_count: int = 0
    new_error_count: int = 0


@dataclass(frozen=True)
class SnapshotComparison:
    old: Snapshot
    new: Snapshot
    folder_changes: tuple[FolderChange, ...]
    entered_files: tuple[SnapshotFile, ...]
    left_files: tuple[SnapshotFile, ...]
    size_changed_files: tuple[tuple[SnapshotFile, SnapshotFile], ...]
    warnings: tuple[str, ...] = ()

    @property
    def total_size_delta(self) -> int:
        return self.new.summary.total_size - self.old.summary.total_size

    @property
    def growing_folders(self) -> tuple[FolderChange, ...]:
        return tuple(change for change in self.folder_changes if change.size_delta > 0)

    @property
    def shrinking_folders(self) -> tuple[FolderChange, ...]:
        return tuple(change for change in self.folder_changes if change.size_delta < 0)

    # v0.6 compatibility names. They describe Top-file list changes, not proof
    # that a file was physically created or deleted.
    @property
    def added_files(self) -> tuple[SnapshotFile, ...]:
        return self.entered_files

    @property
    def removed_files(self) -> tuple[SnapshotFile, ...]:
        return self.left_files


def _folder_name(path_text: str) -> str:
    if path_text == "[root files]":
        return path_text
    normalized = path_text.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", maxsplit=1)[-1] or path_text


def _relative_path(path_text: str, root_text: str) -> str:
    if path_text == "[root files]":
        return path_text
    try:
        path = Path(path_text).expanduser().resolve(strict=False)
        root = Path(root_text).expanduser().resolve(strict=False)
        return path.relative_to(root).as_posix()
    except (OSError, ValueError):
        return path_text.replace("\\", "/")


def _legacy_relative_path(path_text: str, root_text: str) -> str:
    if path_text == "[root files]":
        return path_text
    try:
        return str(
            Path(path_text).expanduser().resolve(strict=False).relative_to(
                Path(root_text).expanduser().resolve(strict=False)
            )
        )
    except (OSError, ValueError):
        return path_text


def _comparison_key(relative_path: str, case_sensitive: bool = True) -> str:
    normalized = relative_path.replace("\\", "/").strip("/") or "."
    return normalized if case_sensitive else normalized.casefold()


def _case_sensitive_for_platform() -> bool:
    return os.name != "nt"


def _snapshot_from_scan_result(result: AnalysisResult, timestamp: datetime) -> Snapshot:
    data = result.data
    scan_result = result.scan_result
    assert scan_result is not None
    options = result.options
    root_path = str(scan_result.root)
    folders = tuple(
        SnapshotFolder(
            name=node.display_name,
            path=str(scan_result.root / node.relative_path) if node.relative_path else root_path,
            relative_path=node.relative_path,
            file_count=node.recursive_file_count,
            total_size=node.recursive_size,
            depth=node.depth,
            parent_relative_path=node.parent_relative_path,
            direct_file_count=node.direct_file_count,
            recursive_file_count=node.recursive_file_count,
            direct_size=node.direct_size,
            recursive_size=node.recursive_size,
            error_count=node.error_count,
        )
        for node in scan_result.directories
        if node.relative_path
    )
    files = tuple(
        SnapshotFile(
            path=str(file["path"]),
            relative_path=_relative_path(str(file["path"]), root_path),
            size=int(file["size"]),
            suffix=str(file.get("suffix", "")),
            modified_time=float(file.get("modified_time", 0)),
        )
        for file in data.get("largest_files", [])
    )
    ignore_dirs = tuple(str(name) for name in (options.ignore_dirs or ())) if options else ()
    scan_parameters = {
        "min_size": options.min_size if options else 0,
        "ignore_dirs": ignore_dirs,
        "max_depth": options.max_depth if options else None,
        "max_nodes": options.max_nodes if options else None,
        "min_tree_size": options.min_tree_size if options else 0,
        "min_tree_ratio": options.min_tree_ratio if options else 0.0,
    }
    return Snapshot(
        metadata=SnapshotMetadata(
            version=__version__,
            timestamp=timestamp.isoformat(timespec="seconds"),
            root_path=root_path,
            schema_version=CURRENT_SCHEMA_VERSION,
            app_version=__version__,
            platform=platform.system().lower(),
            case_sensitive=_case_sensitive_for_platform(),
            scan_parameters=scan_parameters,
            tree_complete=True,
            tree_limited=not scan_result.tree_complete,
            error_summary={
                "count": len(scan_result.issues),
                "by_type": _error_counts(scan_result),
            },
        ),
        summary=SnapshotSummary(
            total_size=int(data["summary"]["total_size"]),
            file_count=int(data["summary"]["total_files"]),
            folder_count=int(data["summary"]["total_folders"]),
            error_count=len(scan_result.issues),
        ),
        folders=folders,
        files=files,
        duplicates=DuplicateStatus(
            scanned=bool(data.get("duplicates_scanned", False)),
            group_count=int(data.get("duplicate_group_count", 0)),
            potential_saved_size=int(data.get("duplicate_potential_saved_size", 0)),
        ),
    )


def _error_counts(result: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in result.issues:
        counts[issue.error_type] = counts.get(issue.error_type, 0) + 1
    return counts


def _legacy_snapshot(result: AnalysisResult, timestamp: datetime) -> Snapshot:
    """Keep callers that construct hand-written v0.6 AnalysisResult objects usable."""
    data = result.data
    summary = data["summary"]
    root_path = str(summary["root"])
    folders = tuple(
        SnapshotFolder(
            name=_folder_name(str(folder["path"])),
            path=str(folder["path"]),
            relative_path=_legacy_relative_path(str(folder["path"]), root_path),
            file_count=int(folder["count"]),
            total_size=int(folder["total_size"]),
        )
        for folder in data.get("all_folder_stats", data.get("folder_stats", []))
    )
    files = tuple(
        SnapshotFile(
            path=str(file["path"]),
            relative_path=_legacy_relative_path(str(file["path"]), root_path),
            size=int(file["size"]),
            suffix=str(file.get("suffix", "")),
            modified_time=float(file.get("modified_time", 0)),
        )
        for file in data.get("largest_files", [])
    )
    return Snapshot(
        metadata=SnapshotMetadata(
            version=__version__,
            timestamp=timestamp.isoformat(timespec="seconds"),
            root_path=root_path,
            schema_version=1,
            app_version=__version__,
        ),
        summary=SnapshotSummary(
            total_size=int(summary["total_size"]),
            file_count=int(summary["total_files"]),
            folder_count=int(summary["total_folders"]),
        ),
        folders=folders,
        files=files,
        duplicates=DuplicateStatus(
            scanned=bool(data.get("duplicates_scanned", False)),
            group_count=int(data.get("duplicate_group_count", 0)),
            potential_saved_size=int(data.get("duplicate_potential_saved_size", 0)),
        ),
    )


def create_snapshot(result: AnalysisResult, timestamp: datetime | None = None) -> Snapshot:
    """Build a v2 snapshot from the existing service result without re-analysis."""
    created_at = timestamp or datetime.now().astimezone()
    if created_at.tzinfo is None:
        created_at = created_at.astimezone()
    if result.scan_result is None:
        return _legacy_snapshot(result, created_at)
    return _snapshot_from_scan_result(result, created_at)


def default_snapshot_path(
    directory: Path = Path(".diskvis/snapshots"),
    timestamp: datetime | None = None,
) -> Path:
    created_at = timestamp or datetime.now().astimezone()
    if created_at.tzinfo is None:
        created_at = created_at.astimezone()
    stem = f"snapshot-{created_at:%Y%m%d-%H%M%S}"
    candidate = Path(directory) / f"{stem}.json"
    sequence = 2
    while candidate.exists():
        candidate = Path(directory) / f"{stem}-{sequence}.json"
        sequence += 1
    return candidate


def save_snapshot(
    result: AnalysisResult,
    output_path: Path | None = None,
    timestamp: datetime | None = None,
) -> Path:
    snapshot = create_snapshot(result, timestamp=timestamp)
    destination = Path(output_path) if output_path else default_snapshot_path(timestamp=timestamp)
    export_json(snapshot.to_dict(), destination)
    return destination


def _expect_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"invalid snapshot: {field} must be an object")
    return value


def _expect_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"invalid snapshot: {field} must be an array")
    return value


def _expect_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"invalid snapshot: {field} must be a string")
    return value


def _expect_non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid snapshot: {field} must be a non-negative integer")
    return value


def _expect_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid snapshot: {field} must be a number")
    return float(value)


def _parse_folder(value: Any, schema_version: int) -> SnapshotFolder:
    item = _expect_dict(value, "folders[]")
    return SnapshotFolder(
        name=_expect_string(item["name"], "folders[].name"),
        path=_expect_string(item["path"], "folders[].path"),
        relative_path=_expect_string(item["relative_path"], "folders[].relative_path"),
        file_count=_expect_non_negative_int(item["file_count"], "folders[].file_count"),
        total_size=_expect_non_negative_int(item["total_size"], "folders[].total_size"),
        depth=_expect_non_negative_int(item.get("depth", 1), "folders[].depth"),
        parent_relative_path=item.get("parent_relative_path"),
        direct_file_count=_expect_non_negative_int(
            item.get("direct_file_count", 0), "folders[].direct_file_count"
        ),
        recursive_file_count=_expect_non_negative_int(
            item.get("recursive_file_count", item["file_count"]),
            "folders[].recursive_file_count",
        ),
        direct_size=_expect_non_negative_int(item.get("direct_size", 0), "folders[].direct_size"),
        recursive_size=_expect_non_negative_int(
            item.get("recursive_size", item["total_size"]), "folders[].recursive_size"
        ),
        error_count=_expect_non_negative_int(item.get("error_count", 0), "folders[].error_count"),
    )


def _parse_file(value: Any) -> SnapshotFile:
    item = _expect_dict(value, "files[]")
    return SnapshotFile(
        path=_expect_string(item["path"], "files[].path"),
        relative_path=_expect_string(item["relative_path"], "files[].relative_path"),
        size=_expect_non_negative_int(item["size"], "files[].size"),
        suffix=_expect_string(item.get("suffix", ""), "files[].suffix"),
        modified_time=_expect_number(item.get("modified_time", 0), "files[].modified_time"),
    )


def snapshot_from_dict(data: dict[str, Any]) -> Snapshot:
    """Validate v1/v2 JSON, rejecting unsupported future schemas."""
    try:
        metadata_data = _expect_dict(data["metadata"], "metadata")
        schema_version = metadata_data.get("schema_version", 1)
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise ValueError("invalid snapshot: metadata.schema_version must be an integer")
        if schema_version > CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported snapshot schema version: {schema_version}"
            )
        summary_data = _expect_dict(data["summary"], "summary")
        folders_data = _expect_list(data["folders"], "folders")
        files_data = _expect_list(data["files"], "files")
        duplicate_data = _expect_dict(data["duplicates"], "duplicates")
        if schema_version >= 2:
            app_version = _expect_string(metadata_data["app_version"], "metadata.app_version")
            platform_name = _expect_string(metadata_data["platform"], "metadata.platform")
            case_sensitive = metadata_data["case_sensitive"]
            if not isinstance(case_sensitive, bool):
                raise ValueError("invalid snapshot: metadata.case_sensitive must be a boolean")
            scan_parameters = _expect_dict(
                metadata_data.get("scan_parameters", {}), "metadata.scan_parameters"
            )
            tree_complete = metadata_data.get("tree_complete", True)
            tree_limited = metadata_data.get("tree_limited", False)
            if not isinstance(tree_complete, bool) or not isinstance(tree_limited, bool):
                raise ValueError("invalid snapshot: tree completeness flags must be boolean")
            error_summary = _expect_dict(metadata_data.get("error_summary", {}), "metadata.error_summary")
            version = app_version
        else:
            version = _expect_string(metadata_data["version"], "metadata.version")
            app_version = version
            platform_name = ""
            case_sensitive = True
            scan_parameters = {}
            tree_complete = False
            tree_limited = True
            error_summary = {}
        metadata = SnapshotMetadata(
            version=version,
            timestamp=_expect_string(metadata_data["timestamp"], "metadata.timestamp"),
            root_path=_expect_string(metadata_data["root_path"], "metadata.root_path"),
            schema_version=schema_version,
            app_version=app_version,
            platform=platform_name,
            case_sensitive=case_sensitive,
            scan_parameters=scan_parameters,
            tree_complete=tree_complete,
            tree_limited=tree_limited,
            error_summary=error_summary,
        )
        summary = SnapshotSummary(
            total_size=_expect_non_negative_int(summary_data["total_size"], "summary.total_size"),
            file_count=_expect_non_negative_int(summary_data["file_count"], "summary.file_count"),
            folder_count=_expect_non_negative_int(summary_data["folder_count"], "summary.folder_count"),
            error_count=_expect_non_negative_int(summary_data.get("error_count", 0), "summary.error_count"),
        )
        folders = tuple(_parse_folder(item, schema_version) for item in folders_data)
        files = tuple(_parse_file(item) for item in files_data)
        scanned = duplicate_data["scanned"]
        if not isinstance(scanned, bool):
            raise ValueError("invalid snapshot: duplicates.scanned must be a boolean")
        duplicates = DuplicateStatus(
            scanned=scanned,
            group_count=_expect_non_negative_int(duplicate_data["group_count"], "duplicates.group_count"),
            potential_saved_size=_expect_non_negative_int(
                duplicate_data["potential_saved_size"], "duplicates.potential_saved_size"
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("invalid snapshot:"):
            raise
        raise ValueError(f"invalid snapshot structure: {exc}") from exc
    return Snapshot(metadata, summary, folders, files, duplicates)


def load_snapshot(path: Path) -> Snapshot:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid snapshot JSON: {source}") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid snapshot: root must be an object")
    return snapshot_from_dict(data)


def compare_snapshots(old: Snapshot, new: Snapshot) -> SnapshotComparison:
    """Compare complete directory trees and Top-file lists."""
    case_sensitive = old.metadata.case_sensitive and new.metadata.case_sensitive
    warnings: list[str] = []
    if old.metadata.case_sensitive != new.metadata.case_sensitive:
        warnings.append("路径大小写语义不同，比较结果可能需要人工复核")
    if old.metadata.platform and new.metadata.platform and old.metadata.platform != new.metadata.platform:
        warnings.append("快照来自不同操作系统，路径语义可能不同")
    if old.metadata.root_path.replace("\\", "/") != new.metadata.root_path.replace("\\", "/"):
        warnings.append("两个快照的扫描根路径不同")
    old_folders = {_comparison_key(folder.relative_path, case_sensitive): folder for folder in old.folders}
    new_folders = {_comparison_key(folder.relative_path, case_sensitive): folder for folder in new.folders}
    folder_changes: list[FolderChange] = []
    for key in old_folders.keys() | new_folders.keys():
        old_folder = old_folders.get(key)
        new_folder = new_folders.get(key)
        old_size = old_folder.total_size if old_folder else 0
        new_size = new_folder.total_size if new_folder else 0
        old_count = old_folder.file_count if old_folder else 0
        new_count = new_folder.file_count if new_folder else 0
        old_errors = old_folder.error_count if old_folder else 0
        new_errors = new_folder.error_count if new_folder else 0
        if old_size == new_size and old_count == new_count and old_errors == new_errors:
            continue
        current = new_folder or old_folder
        assert current is not None
        folder_changes.append(
            FolderChange(
                name=current.name,
                path=current.path,
                relative_path=current.relative_path,
                old_size=old_size,
                new_size=new_size,
                size_delta=new_size - old_size,
                old_file_count=old_count,
                new_file_count=new_count,
                old_error_count=old_errors,
                new_error_count=new_errors,
            )
        )
    folder_changes.sort(key=lambda change: (-abs(change.size_delta), change.relative_path))

    old_files = {_comparison_key(file.relative_path, case_sensitive): file for file in old.files}
    new_files = {_comparison_key(file.relative_path, case_sensitive): file for file in new.files}
    entered = tuple(
        sorted(
            (file for key, file in new_files.items() if key not in old_files),
            key=lambda file: (-file.size, file.relative_path),
        )
    )
    left = tuple(
        sorted(
            (file for key, file in old_files.items() if key not in new_files),
            key=lambda file: (-file.size, file.relative_path),
        )
    )
    changed = tuple(
        sorted(
            (
                (old_files[key], new_files[key])
                for key in old_files.keys() & new_files.keys()
                if old_files[key].size != new_files[key].size
            ),
            key=lambda pair: (-abs(pair[1].size - pair[0].size), pair[1].relative_path),
        )
    )
    return SnapshotComparison(old, new, tuple(folder_changes), entered, left, changed, tuple(warnings))


def format_size_delta(size_delta: int) -> str:
    if size_delta > 0:
        return f"+{format_size(size_delta)}"
    if size_delta < 0:
        return f"-{format_size(abs(size_delta))}"
    return "0 B"


def comparison_to_data(comparison: SnapshotComparison, top_n: int = 10) -> dict[str, Any]:
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    growing = sorted(comparison.growing_folders, key=lambda change: (-change.size_delta, change.relative_path))[:top_n]
    shrinking = sorted(comparison.shrinking_folders, key=lambda change: (change.size_delta, change.relative_path))[:top_n]
    largest_delta = max((abs(change.size_delta) for change in (*growing, *shrinking)), default=1)

    def folder_data(change: FolderChange) -> dict[str, Any]:
        return {
            "name": change.name,
            "path": change.path,
            "relative_path": change.relative_path,
            "old_size": change.old_size,
            "new_size": change.new_size,
            "size_delta": change.size_delta,
            "size_delta_human": format_size_delta(change.size_delta),
            "old_size_human": format_size(change.old_size),
            "new_size_human": format_size(change.new_size),
            "old_file_count": change.old_file_count,
            "new_file_count": change.new_file_count,
            "old_error_count": change.old_error_count,
            "new_error_count": change.new_error_count,
            "bar_percent": round(abs(change.size_delta) / largest_delta * 100, 2),
        }

    def file_data(file: SnapshotFile) -> dict[str, Any]:
        return {
            "path": file.path,
            "relative_path": file.relative_path,
            "size": file.size,
            "size_human": format_size(file.size),
            "suffix": file.suffix,
            "modified_time": file.modified_time,
        }

    return {
        "root_path": comparison.new.metadata.root_path,
        "roots_match": _comparison_key(comparison.old.metadata.root_path, comparison.old.metadata.case_sensitive)
        == _comparison_key(comparison.new.metadata.root_path, comparison.new.metadata.case_sensitive),
        "warnings": list(comparison.warnings),
        "completeness": {
            "old_tree_complete": comparison.old.metadata.tree_complete,
            "new_tree_complete": comparison.new.metadata.tree_complete,
            "old_schema_version": comparison.old.metadata.schema_version,
            "new_schema_version": comparison.new.metadata.schema_version,
            "old_error_count": comparison.old.summary.error_count,
            "new_error_count": comparison.new.summary.error_count,
        },
        "old": {
            "timestamp": comparison.old.metadata.timestamp,
            "root_path": comparison.old.metadata.root_path,
            "total_size": comparison.old.summary.total_size,
            "total_size_human": format_size(comparison.old.summary.total_size),
            "file_count": comparison.old.summary.file_count,
            "folder_count": comparison.old.summary.folder_count,
        },
        "new": {
            "timestamp": comparison.new.metadata.timestamp,
            "root_path": comparison.new.metadata.root_path,
            "total_size": comparison.new.summary.total_size,
            "total_size_human": format_size(comparison.new.summary.total_size),
            "file_count": comparison.new.summary.file_count,
            "folder_count": comparison.new.summary.folder_count,
        },
        "total_size_delta": comparison.total_size_delta,
        "total_size_delta_human": format_size_delta(comparison.total_size_delta),
        "growing_folders": [folder_data(change) for change in growing],
        "shrinking_folders": [folder_data(change) for change in shrinking],
        "entered_top_files": [file_data(file) for file in comparison.entered_files[:top_n]],
        "left_top_files": [file_data(file) for file in comparison.left_files[:top_n]],
        "size_changed_files": [
            {"old": file_data(old_file), "new": file_data(new_file)}
            for old_file, new_file in comparison.size_changed_files[:top_n]
        ],
        "added_files": [file_data(file) for file in comparison.entered_files[:top_n]],
        "removed_files": [file_data(file) for file in comparison.left_files[:top_n]],
    }
