"""Application service shared by the CLI and GUI."""

from __future__ import annotations

import time
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .analyzer import (
    get_folder_stats,
    get_largest_files,
    get_size_distribution,
    get_summary,
    get_type_stats,
)
from .duplicates import find_duplicates, potential_saved_size
from .exporter import to_jsonable
from .formatter import format_size
from .models import DuplicateGroup, FileInfo
from .recommender import generate_recommendations
from .scanner import ScanProgressCallback, scan_directory


@dataclass(frozen=True)
class AnalysisOptions:
    """Configuration for one directory analysis run."""

    root: Path
    top: int = 10
    min_size: int = 0
    ignore_dirs: Collection[str] | None = None
    include_duplicates: bool = False


@dataclass(frozen=True)
class AnalysisResult:
    """Structured result and execution metadata for an analysis run."""

    data: dict[str, Any]
    duplicates_scanned: bool
    duplicate_group_count: int
    scanned_file_count: int
    scanned_folder_count: int


def _with_formatted_values(data: dict[str, Any]) -> dict[str, Any]:
    jsonable = to_jsonable(data)
    summary = jsonable["summary"]
    summary["total_size_human"] = format_size(summary["total_size"])
    summary["scan_seconds_text"] = f"{summary['scan_seconds']:.2f}s"

    for file in jsonable["largest_files"]:
        file["size_human"] = format_size(file["size"])
    for stat in jsonable["type_stats"]:
        stat["total_size_human"] = format_size(stat["total_size"])
    for stat in jsonable["folder_stats"]:
        stat["total_size_human"] = format_size(stat["total_size"])
    for stat in jsonable.get("all_folder_stats", []):
        stat["total_size_human"] = format_size(stat["total_size"])
    for group in jsonable["duplicates"]:
        group["size_human"] = format_size(group["size"])
        group["potential_saved_size"] = group["size"] * max(
            0, len(group["files"]) - 1
        )
        group["potential_saved_size_human"] = format_size(
            group["potential_saved_size"]
        )

    jsonable["duplicate_potential_saved_size_human"] = format_size(
        jsonable["duplicate_potential_saved_size"]
    )
    return jsonable


def _build_data(
    options: AnalysisOptions,
    files: list[FileInfo],
    scan_seconds: float,
    folder_count: int,
    duplicate_groups: list[DuplicateGroup],
) -> dict[str, Any]:
    summary = get_summary(
        options.root,
        files,
        scan_seconds,
        total_folders=folder_count,
    )
    largest_files = get_largest_files(files, options.top)
    type_stats = get_type_stats(files, options.top)
    folder_stats = get_folder_stats(options.root, files, options.top)
    all_type_stats = get_type_stats(
        files,
        max(1, len({file.suffix for file in files})),
    )
    all_folder_stats = get_folder_stats(
        options.root,
        files,
        max(1, len({file.path.parent for file in files})),
    )
    displayed_duplicates = duplicate_groups[: options.top]
    recommendations = generate_recommendations(
        summary,
        largest_files,
        all_type_stats,
        all_folder_stats,
        duplicate_groups,
    )

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "largest_files": largest_files,
        "type_stats": type_stats,
        "folder_stats": folder_stats,
        "all_folder_stats": all_folder_stats,
        "size_distribution": get_size_distribution(files),
        "duplicates": displayed_duplicates,
        "duplicates_scanned": options.include_duplicates,
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_potential_saved_size": potential_saved_size(duplicate_groups),
        "recommendations": recommendations,
        "files": files,
    }
    return _with_formatted_values(data)


def analyze_directory(
    options: AnalysisOptions,
    on_item: ScanProgressCallback | None = None,
) -> AnalysisResult:
    """Scan and analyze a directory without depending on a user interface."""
    if options.top < 1:
        raise ValueError("top must be at least 1")
    if options.min_size < 0:
        raise ValueError("min_size must be non-negative")

    folder_count = 0

    def track_item(path: Path, is_dir: bool) -> None:
        nonlocal folder_count
        if is_dir:
            folder_count += 1
        if on_item:
            on_item(path, is_dir)

    started = time.perf_counter()
    files = scan_directory(
        options.root,
        ignore_dirs=options.ignore_dirs,
        min_size=options.min_size,
        on_item=track_item,
    )
    scan_seconds = time.perf_counter() - started
    duplicate_groups = (
        find_duplicates(files, min_size=options.min_size)
        if options.include_duplicates
        else []
    )
    data = _build_data(
        options,
        files,
        scan_seconds,
        folder_count,
        duplicate_groups,
    )
    return AnalysisResult(
        data=data,
        duplicates_scanned=options.include_duplicates,
        duplicate_group_count=len(duplicate_groups),
        scanned_file_count=len(files),
        scanned_folder_count=folder_count,
    )
