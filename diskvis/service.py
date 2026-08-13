"""Application service shared by the CLI, GUI, snapshots, and reports."""

from __future__ import annotations

import time
from collections import defaultdict
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
from .models import (
    AnalysisCancelled,
    CancellationToken,
    DirectoryNode,
    DuplicateGroup,
    ScanParameters,
    ScanProgress,
    ScanResult,
)
from .recommender import generate_recommendations
from .scanner import (
    ScanProgressCallback,
    StructuredProgressCallback,
    scan_directory_result,
)


@dataclass(frozen=True)
class AnalysisOptions:
    """UI-independent configuration for one directory analysis run."""

    root: Path
    top: int = 10
    min_size: int = 0
    ignore_dirs: Collection[str] | None = None
    include_duplicates: bool = False
    max_depth: int | None = 4
    max_nodes: int | None = 250
    min_tree_size: int = 0
    min_tree_ratio: float = 0.0
    include_inventory: bool = False
    cancellation: CancellationToken | None = None


@dataclass(frozen=True)
class AnalysisResult:
    """Structured result and execution metadata for an analysis run."""

    data: dict[str, Any]
    duplicates_scanned: bool
    duplicate_group_count: int
    scanned_file_count: int
    scanned_folder_count: int
    scan_result: ScanResult | None = None
    options: AnalysisOptions | None = None
    progress: ScanProgress | None = None


def _node_payload(node: DirectoryNode) -> dict[str, Any]:
    payload = node.to_dict()
    payload.update(
        {
            "is_directory": True,
            "is_virtual": False,
            "is_aggregate": node.aggregated,
        }
    )
    return payload


def _virtual_files_node(parent: DirectoryNode) -> dict[str, Any] | None:
    if parent.direct_size <= 0 and parent.direct_file_count <= 0:
        return None
    relative = (
        "[root files]"
        if not parent.relative_path
        else f"{parent.relative_path}/[direct files]"
    )
    return {
        "relative_path": relative,
        "parent_relative_path": parent.relative_path,
        "display_name": "[root files]" if not parent.relative_path else "[direct files]",
        "depth": parent.depth + 1,
        "direct_file_count": parent.direct_file_count,
        "recursive_file_count": parent.direct_file_count,
        "direct_size": parent.direct_size,
        "recursive_size": parent.direct_size,
        "child_directories": [],
        "error_count": 0,
        "pruned": False,
        "aggregated": False,
        "is_directory": False,
        "is_virtual": True,
        "is_aggregate": False,
    }


def _aggregate_node(parent: DirectoryNode, omitted: list[dict[str, Any]]) -> dict[str, Any]:
    total_size = sum(int(item["recursive_size"]) for item in omitted)
    total_files = sum(int(item["recursive_file_count"]) for item in omitted)
    relative = f"{parent.relative_path}/其他" if parent.relative_path else "其他"
    return {
        "relative_path": relative,
        "parent_relative_path": parent.relative_path,
        "display_name": "其他",
        "depth": parent.depth + 1,
        "direct_file_count": 0,
        "recursive_file_count": total_files,
        "direct_size": 0,
        "recursive_size": total_size,
        "child_directories": [],
        "error_count": sum(int(item["error_count"]) for item in omitted),
        "pruned": True,
        "aggregated": True,
        "is_directory": True,
        "is_virtual": True,
        "is_aggregate": True,
        "aggregated_from_count": len(omitted),
    }


def _build_tree_nodes(
    scan_result: ScanResult,
    max_depth: int | None,
    max_nodes: int | None,
    min_size: int,
    min_ratio: float,
) -> tuple[list[dict[str, Any]], bool]:
    """Build a bounded presentation tree while preserving omitted space in ``其他``."""
    nodes = {node.relative_path: node for node in scan_result.directories}
    root = nodes.get("")
    if root is None:
        return [], False
    children: dict[str, list[DirectoryNode]] = defaultdict(list)
    for node in nodes.values():
        if node.parent_relative_path is not None:
            children[node.parent_relative_path].append(node)
    for siblings in children.values():
        siblings.sort(key=lambda item: (-item.recursive_size, item.relative_path))

    total_size = max(1, root.recursive_size)
    output: list[dict[str, Any]] = [_node_payload(root)]
    output_paths = {root.relative_path}
    pending: list[DirectoryNode] = [root]
    directory_budget = max_nodes if max_nodes is not None else 2**31
    limited = False
    while pending:
        parent = pending.pop(0)
        visible: list[dict[str, Any]] = []
        omitted: list[dict[str, Any]] = []
        direct_files = _virtual_files_node(parent)
        if direct_files:
            visible.append(direct_files)
        for child in children.get(parent.relative_path, []):
            item = _node_payload(child)
            ratio = child.recursive_size / total_size
            if (
                child.recursive_size < min_size
                or ratio < min_ratio
                or (max_depth is not None and child.depth > max_depth)
                or directory_budget <= 0
            ):
                omitted.append(item)
                limited = True
                continue
            directory_budget -= 1
            visible.append(item)
            pending.append(child)
        if omitted:
            visible.append(_aggregate_node(parent, omitted))
        for item in visible:
            if item["relative_path"] not in output_paths:
                output.append(item)
                output_paths.add(item["relative_path"])
    return output, not limited


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
    for node in jsonable.get("tree_stats", []):
        node["direct_size_human"] = format_size(node["direct_size"])
        node["recursive_size_human"] = format_size(node["recursive_size"])
    for group in jsonable["duplicates"]:
        group["size_human"] = format_size(group["size"])
        group["potential_saved_size"] = group.get(
            "potential_saved_size",
            group["size"] * max(0, len(group["files"]) - 1),
        )
        group["potential_saved_size_human"] = format_size(
            group["potential_saved_size"]
        )

    jsonable["duplicate_potential_saved_size_human"] = format_size(
        jsonable["duplicate_potential_saved_size"]
    )
    jsonable["tree_limits"] = dict(jsonable.get("tree_limits", {}))
    return jsonable


def _build_data(
    options: AnalysisOptions,
    scan_result: ScanResult,
    scan_seconds: float,
    duplicate_groups: list[DuplicateGroup],
) -> dict[str, Any]:
    files = list(scan_result.files)
    summary = get_summary(
        options.root,
        files,
        scan_seconds,
        total_folders=len(scan_result.directories),
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
    tree_stats, tree_complete = _build_tree_nodes(
        scan_result,
        options.max_depth,
        options.max_nodes,
        options.min_tree_size,
        options.min_tree_ratio,
    )

    data: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "largest_files": largest_files,
        "type_stats": type_stats,
        "folder_stats": folder_stats,
        "all_folder_stats": all_folder_stats,
        "size_distribution": get_size_distribution(files),
        "tree_stats": tree_stats,
        "tree_complete": tree_complete,
        "tree_limits": {
            "max_depth": options.max_depth,
            "max_nodes": options.max_nodes,
            "min_size": options.min_tree_size,
            "min_ratio": options.min_tree_ratio,
        },
        "scan_issues": scan_result.issues,
        "scan_error_count": len(scan_result.issues),
        "duplicates": displayed_duplicates,
        "duplicates_scanned": options.include_duplicates,
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_potential_saved_size": potential_saved_size(duplicate_groups),
        "recommendations": recommendations,
        "scan_parameters": ScanParameters(
            min_size=options.min_size,
            ignore_dirs=tuple(options.ignore_dirs or ()),
            max_depth=options.max_depth,
            max_nodes=options.max_nodes,
            min_tree_size=options.min_tree_size,
            min_tree_ratio=options.min_tree_ratio,
        ),
    }
    if options.include_inventory:
        data["files"] = files
    return _with_formatted_values(data)


def analyze_directory(
    options: AnalysisOptions,
    on_item: ScanProgressCallback | None = None,
    on_progress: StructuredProgressCallback | None = None,
) -> AnalysisResult:
    """Scan and analyze a directory without depending on a user interface."""
    if options.top < 1:
        raise ValueError("top must be at least 1")
    if options.min_size < 0:
        raise ValueError("min_size must be non-negative")
    if options.max_depth is not None and options.max_depth < 0:
        raise ValueError("max_depth must be non-negative")
    if options.max_nodes is not None and options.max_nodes < 1:
        raise ValueError("max_nodes must be at least 1")
    if not 0 <= options.min_tree_ratio <= 1:
        raise ValueError("min_tree_ratio must be between 0 and 1")

    token = options.cancellation or CancellationToken()
    started = time.perf_counter()
    scan_result = scan_directory_result(
        options.root,
        ignore_dirs=options.ignore_dirs,
        min_size=options.min_size,
        on_item=on_item,
        on_progress=on_progress,
        cancellation=token,
    )
    scan_seconds = time.perf_counter() - started
    duplicate_groups: list[DuplicateGroup] = []
    if options.include_duplicates:
        def duplicate_progress(event: ScanProgress) -> None:
            if on_progress is None:
                return
            on_progress(
                ScanProgress(
                    phase=event.phase,
                    current_path=event.current_path,
                    files_scanned=scan_result.progress.files_scanned,
                    dirs_scanned=scan_result.progress.dirs_scanned,
                    bytes_scanned=scan_result.progress.bytes_scanned,
                    errors=scan_result.progress.errors,
                    duplicate_candidates=event.duplicate_candidates,
                    hashes_completed=event.hashes_completed,
                    hashes_total=event.hashes_total,
                )
            )

        duplicate_groups = find_duplicates(
            list(scan_result.files),
            min_size=options.min_size,
            cancellation=token,
            on_progress=duplicate_progress,
        )
    data = _build_data(options, scan_result, scan_seconds, duplicate_groups)
    return AnalysisResult(
        data=data,
        duplicates_scanned=options.include_duplicates,
        duplicate_group_count=len(duplicate_groups),
        scanned_file_count=len(scan_result.files),
        scanned_folder_count=len(scan_result.directories),
        scan_result=scan_result,
        options=options,
        progress=scan_result.progress,
    )


__all__ = [
    "AnalysisCancelled",
    "AnalysisOptions",
    "AnalysisResult",
    "CancellationToken",
    "analyze_directory",
]
