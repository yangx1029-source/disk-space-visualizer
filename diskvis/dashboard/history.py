"""Snapshot history loading and trend aggregation for the dashboard."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..formatter import format_size
from ..snapshot import Snapshot, compare_snapshots, load_snapshot


def _root_key(value: str, case_sensitive: bool) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    return normalized if case_sensitive else normalized.casefold()


def load_snapshot_history(directory: Path, root: Path) -> tuple[Snapshot, ...]:
    """Load valid snapshots for ``root`` without failing on unrelated files."""
    directory = Path(directory).expanduser()
    if not directory.is_dir():
        return ()
    requested = str(Path(root).expanduser().resolve())
    snapshots: list[Snapshot] = []
    for path in sorted(directory.glob("*.json")):
        try:
            snapshot = load_snapshot(path)
        except ValueError:
            continue
        case_sensitive = snapshot.metadata.case_sensitive
        if _root_key(snapshot.metadata.root_path, case_sensitive) != _root_key(
            requested, case_sensitive
        ):
            continue
        snapshots.append(snapshot)
    snapshots.sort(key=lambda item: item.metadata.timestamp)
    return tuple(snapshots)


def build_history_data(snapshots: Iterable[Snapshot], top_n: int = 10) -> dict[str, Any]:
    """Return chart-ready history and the most recent snapshot comparison."""
    ordered = tuple(sorted(snapshots, key=lambda item: item.metadata.timestamp))
    points = [
        {
            "timestamp": item.metadata.timestamp,
            "total_size": item.summary.total_size,
            "total_size_human": format_size(item.summary.total_size),
            "file_count": item.summary.file_count,
            "folder_count": item.summary.folder_count,
            "error_count": item.summary.error_count,
            "schema_version": item.metadata.schema_version,
            "tree_complete": item.metadata.tree_complete,
        }
        for item in ordered
    ]
    growing: list[dict[str, Any]] = []
    recent_files: list[dict[str, Any]] = []
    total_delta = 0
    if len(ordered) >= 2:
        comparison = compare_snapshots(ordered[-2], ordered[-1])
        total_delta = comparison.total_size_delta
        changes = sorted(
            comparison.growing_folders,
            key=lambda item: (-item.size_delta, item.relative_path),
        )[:top_n]
        growing = [
            {
                "name": item.name,
                "relative_path": item.relative_path,
                "size_delta": item.size_delta,
                "size_delta_human": f"+{format_size(item.size_delta)}",
                "file_count_delta": item.new_file_count - item.old_file_count,
            }
            for item in changes
        ]
        recent_files = [
            {
                "path": item.path,
                "relative_path": item.relative_path,
                "size": item.size,
                "size_human": format_size(item.size),
                "suffix": item.suffix,
            }
            for item in comparison.entered_files[:top_n]
        ]
    delta_human = format_size(abs(total_delta))
    if total_delta > 0:
        delta_human = f"+{delta_human}"
    elif total_delta < 0:
        delta_human = f"-{delta_human}"
    return {
        "records": points,
        "record_count": len(points),
        "total_size_delta": total_delta,
        "total_size_delta_human": delta_human,
        "growing_folders": growing,
        "recent_large_files": recent_files,
    }
