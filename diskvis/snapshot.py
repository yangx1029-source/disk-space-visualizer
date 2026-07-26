"""Snapshot persistence and comparison for analysis results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__
from .exporter import export_json
from .formatter import format_size
from .service import AnalysisResult


@dataclass(frozen=True)
class SnapshotMetadata:
    """Identity and origin of a saved scan."""

    version: str
    timestamp: str
    root_path: str


@dataclass(frozen=True)
class SnapshotSummary:
    """Stable summary fields used for historical comparisons."""

    total_size: int
    file_count: int
    folder_count: int


@dataclass(frozen=True)
class SnapshotFolder:
    """One first-level folder retained in a snapshot."""

    name: str
    path: str
    relative_path: str
    file_count: int
    total_size: int


@dataclass(frozen=True)
class SnapshotFile:
    """One Top-N large file retained in a snapshot."""

    path: str
    relative_path: str
    size: int
    suffix: str
    modified_time: float


@dataclass(frozen=True)
class DuplicateStatus:
    """Duplicate detection state captured with a scan."""

    scanned: bool
    group_count: int
    potential_saved_size: int


@dataclass(frozen=True)
class Snapshot:
    """Serializable snapshot document."""

    metadata: SnapshotMetadata
    summary: SnapshotSummary
    folders: tuple[SnapshotFolder, ...]
    files: tuple[SnapshotFile, ...]
    duplicates: DuplicateStatus

    def to_dict(self) -> dict[str, Any]:
        """Return the public JSON schema."""
        return {
            "metadata": {
                "version": self.metadata.version,
                "timestamp": self.metadata.timestamp,
                "root_path": self.metadata.root_path,
            },
            "summary": {
                "total_size": self.summary.total_size,
                "file_count": self.summary.file_count,
                "folder_count": self.summary.folder_count,
            },
            "folders": [
                {
                    "name": folder.name,
                    "path": folder.path,
                    "relative_path": folder.relative_path,
                    "file_count": folder.file_count,
                    "total_size": folder.total_size,
                }
                for folder in self.folders
            ],
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
    """Space delta for one first-level folder."""

    name: str
    path: str
    relative_path: str
    old_size: int
    new_size: int
    size_delta: int
    old_file_count: int
    new_file_count: int


@dataclass(frozen=True)
class SnapshotComparison:
    """Calculated differences between two snapshots."""

    old: Snapshot
    new: Snapshot
    folder_changes: tuple[FolderChange, ...]
    added_files: tuple[SnapshotFile, ...]
    removed_files: tuple[SnapshotFile, ...]

    @property
    def total_size_delta(self) -> int:
        return self.new.summary.total_size - self.old.summary.total_size

    @property
    def growing_folders(self) -> tuple[FolderChange, ...]:
        return tuple(change for change in self.folder_changes if change.size_delta > 0)

    @property
    def shrinking_folders(self) -> tuple[FolderChange, ...]:
        return tuple(change for change in self.folder_changes if change.size_delta < 0)


def _folder_name(path_text: str) -> str:
    if path_text == "[root files]":
        return path_text
    normalized = path_text.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", maxsplit=1)[-1] or path_text


def _relative_path(path_text: str, root_text: str) -> str:
    if path_text == "[root files]":
        return path_text
    try:
        return str(
            Path(path_text)
            .resolve(strict=False)
            .relative_to(Path(root_text).resolve(strict=False))
        )
    except (OSError, ValueError):
        return path_text


def _comparison_key(relative_path: str) -> str:
    return relative_path.replace("\\", "/").casefold()


def create_snapshot(
    result: AnalysisResult,
    timestamp: datetime | None = None,
) -> Snapshot:
    """Build a snapshot from the existing service result without re-analysis."""
    data = result.data
    summary = data["summary"]
    root_path = str(summary["root"])
    created_at = timestamp or datetime.now().astimezone()
    if created_at.tzinfo is None:
        created_at = created_at.astimezone()

    folders = tuple(
        SnapshotFolder(
            name=_folder_name(str(folder["path"])),
            path=str(folder["path"]),
            relative_path=_relative_path(str(folder["path"]), root_path),
            file_count=int(folder["count"]),
            total_size=int(folder["total_size"]),
        )
        for folder in data.get(
            "all_folder_stats",
            data.get("folder_stats", []),
        )
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

    return Snapshot(
        metadata=SnapshotMetadata(
            version=__version__,
            timestamp=created_at.isoformat(timespec="seconds"),
            root_path=root_path,
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
            potential_saved_size=int(
                data.get("duplicate_potential_saved_size", 0)
            ),
        ),
    )


def default_snapshot_path(
    directory: Path = Path(".diskvis/snapshots"),
    timestamp: datetime | None = None,
) -> Path:
    """Return a collision-safe default snapshot path."""
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
    """Create and save one AnalysisResult snapshot."""
    snapshot = create_snapshot(result, timestamp=timestamp)
    destination = Path(output_path) if output_path else default_snapshot_path(
        timestamp=timestamp
    )
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
        raise ValueError(
            f"invalid snapshot: {field} must be a non-negative integer"
        )
    return value


def _expect_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid snapshot: {field} must be a number")
    return float(value)


def _parse_folder(value: Any) -> SnapshotFolder:
    item = _expect_dict(value, "folders[]")
    return SnapshotFolder(
        name=_expect_string(item["name"], "folders[].name"),
        path=_expect_string(item["path"], "folders[].path"),
        relative_path=_expect_string(
            item["relative_path"],
            "folders[].relative_path",
        ),
        file_count=_expect_non_negative_int(
            item["file_count"],
            "folders[].file_count",
        ),
        total_size=_expect_non_negative_int(
            item["total_size"],
            "folders[].total_size",
        ),
    )


def _parse_file(value: Any) -> SnapshotFile:
    item = _expect_dict(value, "files[]")
    return SnapshotFile(
        path=_expect_string(item["path"], "files[].path"),
        relative_path=_expect_string(
            item["relative_path"],
            "files[].relative_path",
        ),
        size=_expect_non_negative_int(item["size"], "files[].size"),
        suffix=_expect_string(item.get("suffix", ""), "files[].suffix"),
        modified_time=_expect_number(
            item.get("modified_time", 0),
            "files[].modified_time",
        ),
    )


def snapshot_from_dict(data: dict[str, Any]) -> Snapshot:
    """Validate and construct a Snapshot from decoded JSON."""
    try:
        metadata_data = _expect_dict(data["metadata"], "metadata")
        summary_data = _expect_dict(data["summary"], "summary")
        folders_data = _expect_list(data["folders"], "folders")
        files_data = _expect_list(data["files"], "files")
        duplicate_data = _expect_dict(data["duplicates"], "duplicates")

        metadata = SnapshotMetadata(
            version=_expect_string(metadata_data["version"], "metadata.version"),
            timestamp=_expect_string(
                metadata_data["timestamp"],
                "metadata.timestamp",
            ),
            root_path=_expect_string(
                metadata_data["root_path"],
                "metadata.root_path",
            ),
        )
        summary = SnapshotSummary(
            total_size=_expect_non_negative_int(
                summary_data["total_size"],
                "summary.total_size",
            ),
            file_count=_expect_non_negative_int(
                summary_data["file_count"],
                "summary.file_count",
            ),
            folder_count=_expect_non_negative_int(
                summary_data["folder_count"],
                "summary.folder_count",
            ),
        )
        folders = tuple(_parse_folder(item) for item in folders_data)
        files = tuple(_parse_file(item) for item in files_data)
        scanned = duplicate_data["scanned"]
        if not isinstance(scanned, bool):
            raise ValueError(
                "invalid snapshot: duplicates.scanned must be a boolean"
            )
        duplicates = DuplicateStatus(
            scanned=scanned,
            group_count=_expect_non_negative_int(
                duplicate_data["group_count"],
                "duplicates.group_count",
            ),
            potential_saved_size=_expect_non_negative_int(
                duplicate_data["potential_saved_size"],
                "duplicates.potential_saved_size",
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("invalid snapshot:"):
            raise
        raise ValueError(f"invalid snapshot structure: {exc}") from exc

    return Snapshot(
        metadata=metadata,
        summary=summary,
        folders=folders,
        files=files,
        duplicates=duplicates,
    )


def load_snapshot(path: Path) -> Snapshot:
    """Load and validate a UTF-8 snapshot JSON file."""
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid snapshot JSON: {source}") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid snapshot: root must be an object")
    return snapshot_from_dict(data)


def compare_snapshots(old: Snapshot, new: Snapshot) -> SnapshotComparison:
    """Compare two loaded snapshots using relative first-level paths."""
    old_folders = {
        _comparison_key(folder.relative_path): folder for folder in old.folders
    }
    new_folders = {
        _comparison_key(folder.relative_path): folder for folder in new.folders
    }
    folder_changes: list[FolderChange] = []
    for key in old_folders.keys() | new_folders.keys():
        old_folder = old_folders.get(key)
        new_folder = new_folders.get(key)
        old_size = old_folder.total_size if old_folder else 0
        new_size = new_folder.total_size if new_folder else 0
        if old_size == new_size:
            continue
        current = new_folder or old_folder
        if current is None:
            continue
        folder_changes.append(
            FolderChange(
                name=current.name,
                path=current.path,
                relative_path=current.relative_path,
                old_size=old_size,
                new_size=new_size,
                size_delta=new_size - old_size,
                old_file_count=old_folder.file_count if old_folder else 0,
                new_file_count=new_folder.file_count if new_folder else 0,
            )
        )

    folder_changes.sort(
        key=lambda change: (-abs(change.size_delta), change.name.casefold())
    )
    old_files = {
        _comparison_key(file.relative_path): file for file in old.files
    }
    new_files = {
        _comparison_key(file.relative_path): file for file in new.files
    }
    added_files = tuple(
        sorted(
            (
                file
                for key, file in new_files.items()
                if key not in old_files
            ),
            key=lambda file: (-file.size, file.relative_path.casefold()),
        )
    )
    removed_files = tuple(
        sorted(
            (
                file
                for key, file in old_files.items()
                if key not in new_files
            ),
            key=lambda file: (-file.size, file.relative_path.casefold()),
        )
    )
    return SnapshotComparison(
        old=old,
        new=new,
        folder_changes=tuple(folder_changes),
        added_files=added_files,
        removed_files=removed_files,
    )


def format_size_delta(size_delta: int) -> str:
    """Format a signed byte delta for CLI and reports."""
    if size_delta > 0:
        return f"+{format_size(size_delta)}"
    if size_delta < 0:
        return f"-{format_size(abs(size_delta))}"
    return "0 B"


def comparison_to_data(
    comparison: SnapshotComparison,
    top_n: int = 10,
) -> dict[str, Any]:
    """Convert a comparison into presentation-ready data."""
    if top_n < 1:
        raise ValueError("top_n must be at least 1")

    growing = sorted(
        comparison.growing_folders,
        key=lambda change: (-change.size_delta, change.name.casefold()),
    )[:top_n]
    shrinking = sorted(
        comparison.shrinking_folders,
        key=lambda change: (change.size_delta, change.name.casefold()),
    )[:top_n]
    largest_delta = max(
        (
            abs(change.size_delta)
            for change in (*growing, *shrinking)
        ),
        default=1,
    )

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
        "roots_match": (
            _comparison_key(comparison.old.metadata.root_path)
            == _comparison_key(comparison.new.metadata.root_path)
        ),
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
        "total_size_delta_human": format_size_delta(
            comparison.total_size_delta
        ),
        "growing_folders": [folder_data(change) for change in growing],
        "shrinking_folders": [folder_data(change) for change in shrinking],
        "added_files": [
            file_data(file) for file in comparison.added_files[:top_n]
        ],
        "removed_files": [
            file_data(file) for file in comparison.removed_files[:top_n]
        ],
    }
