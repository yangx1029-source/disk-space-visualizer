"""Core data models for disk-space-visualizer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileInfo:
    path: Path
    size: int
    suffix: str
    modified_time: float


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

    @property
    def potential_saved_size(self) -> int:
        return self.size * max(0, len(self.files) - 1)
