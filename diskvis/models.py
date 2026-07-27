"""Core data models for disk-space-visualizer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any


@dataclass(frozen=True)
class FileInfo:
    path: Path
    size: int
    suffix: str
    modified_time: float
    device: int | None = None
    inode: int | None = None
    hard_link_count: int = 1


@dataclass(frozen=True)
class ScanSummary:
    root: Path
    total_size: int
    total_files: int
    total_folders: int
    scan_seconds: float


@dataclass(frozen=True)
class TypeStat:
    suffix: str
    count: int
    total_size: int


@dataclass(frozen=True)
class FolderStat:
    path: Path
    count: int
    total_size: int


@dataclass(frozen=True)
class DuplicateGroup:
    size: int
    hash: str
    files: list[Path]
    physical_file_count: int | None = None
    hard_link_aliases: list[Path] = field(default_factory=list)

    @property
    def potential_saved_size(self) -> int:
        count = self.physical_file_count
        if count is None:
            count = len(self.files)
        return self.size * max(0, count - 1)


@dataclass(frozen=True)
class ScanIssue:
    """A non-fatal filesystem issue encountered during scanning."""

    path: Path
    operation: str
    error_type: str
    message: str


@dataclass(frozen=True)
class ScanProgress:
    """A UI-agnostic progress event shared by the CLI and GUI."""

    phase: str
    current_path: Path | None = None
    files_scanned: int = 0
    dirs_scanned: int = 0
    bytes_scanned: int = 0
    errors: int = 0
    duplicate_candidates: int = 0
    hashes_completed: int = 0
    hashes_total: int = 0


@dataclass
class CancellationToken:
    """Thread-safe cooperative cancellation used by scan and hash phases."""

    _event: Event = field(default_factory=Event, init=False, repr=False)

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise AnalysisCancelled("analysis cancelled")


class AnalysisCancelled(RuntimeError):
    """Raised when a user cancels a long-running analysis."""


@dataclass
class DirectoryNode:
    """Aggregated statistics for one directory in the scanned tree."""

    relative_path: str
    parent_relative_path: str | None
    display_name: str
    depth: int
    direct_file_count: int = 0
    recursive_file_count: int = 0
    direct_size: int = 0
    recursive_size: int = 0
    child_directories: list[str] = field(default_factory=list)
    error_count: int = 0
    pruned: bool = False
    aggregated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "parent_relative_path": self.parent_relative_path,
            "display_name": self.display_name,
            "depth": self.depth,
            "direct_file_count": self.direct_file_count,
            "recursive_file_count": self.recursive_file_count,
            "direct_size": self.direct_size,
            "recursive_size": self.recursive_size,
            "child_directories": list(self.child_directories),
            "error_count": self.error_count,
            "pruned": self.pruned,
            "aggregated": self.aggregated,
        }


@dataclass(frozen=True)
class ScanResult:
    """Full scan output, including directory aggregation and recoverable issues."""

    root: Path
    files: tuple[FileInfo, ...]
    directories: tuple[DirectoryNode, ...]
    issues: tuple[ScanIssue, ...]
    progress: ScanProgress
    tree_complete: bool = True


@dataclass(frozen=True)
class ScanParameters:
    """Portable scan settings persisted into v2 snapshots."""

    min_size: int = 0
    ignore_dirs: tuple[str, ...] = ()
    max_depth: int | None = None
    max_nodes: int | None = None
    min_tree_size: int = 0
    min_tree_ratio: float = 0.0
