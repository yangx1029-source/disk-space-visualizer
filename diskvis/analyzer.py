"""Analysis helpers for scanned files."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from .models import FileInfo, FolderStat, ScanSummary, TypeStat


def _folder_count_from_files(root: Path, files: list[FileInfo]) -> int:
    root = root.resolve()
    folders = {root}
    for file in files:
        try:
            file_path = file.path.resolve()
        except OSError:
            continue
        for parent in file_path.parents:
            folders.add(parent)
            if parent == root:
                break
    return len(folders)


def get_summary(
    root: Path,
    files: list[FileInfo],
    scan_seconds: float,
    total_folders: int | None = None,
) -> ScanSummary:
    root = Path(root).expanduser().resolve()
    return ScanSummary(
        root=root,
        total_size=sum(file.size for file in files),
        total_files=len(files),
        total_folders=(
            total_folders
            if total_folders is not None
            else _folder_count_from_files(Path(root), files)
        ),
        scan_seconds=scan_seconds,
    )


def get_largest_files(files: list[FileInfo], top_n: int = 10) -> list[FileInfo]:
    return sorted(files, key=lambda file: file.size, reverse=True)[:top_n]


def get_type_stats(files: list[FileInfo], top_n: int = 10) -> list[TypeStat]:
    grouped: dict[str, list[FileInfo]] = defaultdict(list)
    for file in files:
        suffix = file.suffix.lower() if file.suffix else "[no extension]"
        grouped[suffix].append(file)

    stats = [
        TypeStat(
            suffix=suffix,
            count=len(group_files),
            total_size=sum(file.size for file in group_files),
        )
        for suffix, group_files in grouped.items()
    ]
    return sorted(stats, key=lambda stat: stat.total_size, reverse=True)[:top_n]


def get_folder_stats(root: Path, files: list[FileInfo], top_n: int = 10) -> list[FolderStat]:
    root = Path(root).resolve()
    grouped: dict[Path, list[FileInfo]] = defaultdict(list)

    for file in files:
        try:
            relative = file.path.resolve().relative_to(root)
        except (OSError, ValueError):
            key = file.path.parent
        else:
            parts = relative.parts
            key = Path("[root files]") if len(parts) <= 1 else root / parts[0]
        grouped[key].append(file)

    stats = [
        FolderStat(
            path=path,
            count=len(group_files),
            total_size=sum(file.size for file in group_files),
        )
        for path, group_files in grouped.items()
    ]
    return sorted(stats, key=lambda stat: stat.total_size, reverse=True)[:top_n]


def get_size_distribution(files: list[FileInfo]) -> dict[str, int]:
    buckets = Counter(
        {
            "< 1 MB": 0,
            "1 MB - 10 MB": 0,
            "10 MB - 100 MB": 0,
            "100 MB - 1 GB": 0,
            ">= 1 GB": 0,
        }
    )
    for file in files:
        if file.size < 1024**2:
            buckets["< 1 MB"] += 1
        elif file.size < 10 * 1024**2:
            buckets["1 MB - 10 MB"] += 1
        elif file.size < 100 * 1024**2:
            buckets["10 MB - 100 MB"] += 1
        elif file.size < 1024**3:
            buckets["100 MB - 1 GB"] += 1
        else:
            buckets[">= 1 GB"] += 1
    return dict(buckets)
