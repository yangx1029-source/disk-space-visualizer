"""Streaming, cross-platform directory scanning with recoverable errors."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path

from .models import (
    CancellationToken,
    DirectoryNode,
    FileInfo,
    ScanIssue,
    ScanProgress,
    ScanResult,
)

DEFAULT_IGNORE_DIRS = {
    "node_modules",
    ".git",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    ".idea",
    ".vscode",
}

ScanProgressCallback = Callable[[Path, bool], None]
StructuredProgressCallback = Callable[[ScanProgress], None]


def _normalize_ignore_dirs(ignore_dirs: Iterable[str] | None) -> set[str]:
    names = DEFAULT_IGNORE_DIRS if ignore_dirs is None else ignore_dirs
    return {str(name).casefold() for name in names if str(name)}


def _relative_path(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path.name
    return relative.as_posix() if relative.parts else ""


def _directory_identity(path: Path, stat: os.stat_result) -> tuple[int, int] | str:
    if stat.st_ino and stat.st_dev:
        return (stat.st_dev, stat.st_ino)
    normalized = os.path.normcase(os.path.abspath(str(path)))
    return normalized


def _file_info_from_entry(entry: os.DirEntry[str]) -> FileInfo | None:
    try:
        stat = entry.stat(follow_symlinks=False)
    except (FileNotFoundError, PermissionError, OSError):
        return None
    # Some Windows filesystem providers expose zero inode values through
    # DirEntry.stat(). Fall back to Path.stat only when physical identity is
    # unavailable, preserving hard-link semantics without slowing normal scans.
    device = getattr(stat, "st_dev", None)
    inode = getattr(stat, "st_ino", None)
    link_count = getattr(stat, "st_nlink", 1) or 1
    if device in (None, 0) or inode in (None, 0):
        try:
            fallback = Path(entry.path).stat()
        except (FileNotFoundError, PermissionError, OSError):
            fallback = None
        if fallback is not None:
            device = getattr(fallback, "st_dev", device)
            inode = getattr(fallback, "st_ino", inode)
            link_count = getattr(fallback, "st_nlink", link_count) or link_count

    suffix = Path(entry.name).suffix.lower() or "[no extension]"
    return FileInfo(
        path=Path(entry.path),
        size=stat.st_size,
        suffix=suffix,
        modified_time=stat.st_mtime,
        device=device,
        inode=inode,
        hard_link_count=link_count,
    )


def scan_directory_result(
    root: Path,
    ignore_dirs: Iterable[str] | None = None,
    min_size: int = 0,
    on_item: ScanProgressCallback | None = None,
    on_progress: StructuredProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> ScanResult:
    """Scan ``root`` without recursive Python calls.

    ``os.scandir`` keeps directory iteration streaming and lets the operating
    system provide cached ``DirEntry.stat`` information. Directories are
    aggregated on exit from an explicit stack, so very deep paths do not grow
    the Python call stack.
    """
    root = Path(root).expanduser().resolve()
    ignore_names = _normalize_ignore_dirs(ignore_dirs)
    if min_size < 0:
        raise ValueError("min_size must be non-negative")
    if not root.exists():
        raise FileNotFoundError(f"path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"path is not a directory: {root}")

    token = cancellation or CancellationToken()
    files: list[FileInfo] = []
    issues: list[ScanIssue] = []
    directories: dict[str, DirectoryNode] = {}
    seen_dirs: set[tuple[int, int] | str] = set()
    files_scanned = dirs_scanned = bytes_scanned = error_count = 0

    def emit(phase: str, current_path: Path | None = None) -> None:
        if on_progress:
            on_progress(
                ScanProgress(
                    phase=phase,
                    current_path=current_path,
                    files_scanned=files_scanned,
                    dirs_scanned=dirs_scanned,
                    bytes_scanned=bytes_scanned,
                    errors=error_count,
                )
            )

    def add_issue(path: Path, operation: str, error: BaseException) -> None:
        nonlocal error_count
        error_count += 1
        issues.append(
            ScanIssue(
                path=path,
                operation=operation,
                error_type=type(error).__name__,
                message=str(error) or type(error).__name__,
            )
        )
        emit("scan", path)

    root_stat = root.stat()
    root_key = ""
    directories[root_key] = DirectoryNode(
        relative_path=root_key,
        parent_relative_path=None,
        display_name=root.name or root.anchor or str(root),
        depth=0,
    )

    # Entries are explicit stack records: enter, then exit after streamed children.
    stack: list[tuple[str, Path, str, str | None, os.stat_result | None]] = [
        ("enter", root, root_key, None, root_stat)
    ]
    while stack:
        token.raise_if_cancelled()
        action, current, relative, parent_relative, pending_stat = stack.pop()
        if action == "exit":
            node = directories.get(relative)
            if node is None:
                continue
            node.recursive_file_count = node.direct_file_count
            node.recursive_size = node.direct_size
            for child_relative in node.child_directories:
                child = directories.get(child_relative)
                if child:
                    node.recursive_file_count += child.recursive_file_count
                    node.recursive_size += child.recursive_size
                    node.error_count += child.error_count
            emit("scan", current)
            continue

        try:
            stat = pending_stat or current.stat()
        except (FileNotFoundError, PermissionError, OSError) as error:
            add_issue(current, "stat", error)
            continue
        identity = _directory_identity(current, stat)
        if identity in seen_dirs:
            continue
        seen_dirs.add(identity)

        node = directories.setdefault(
            relative,
            DirectoryNode(
                relative_path=relative,
                parent_relative_path=parent_relative,
                display_name=current.name or current.anchor or str(current),
                depth=len(Path(relative).parts) if relative else 0,
            ),
        )
        dirs_scanned += 1
        if on_item:
            on_item(current, True)
        emit("scan", current)
        stack.append(("exit", current, relative, parent_relative, None))

        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    token.raise_if_cancelled()
                    entry_path = Path(entry.path)
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.casefold() in ignore_names:
                                continue
                            child_relative = _relative_path(root, entry_path)
                            if child_relative not in node.child_directories:
                                node.child_directories.append(child_relative)
                            directories.setdefault(
                                child_relative,
                                DirectoryNode(
                                    relative_path=child_relative,
                                    parent_relative_path=relative,
                                    display_name=entry.name,
                                    depth=len(Path(child_relative).parts),
                                ),
                            )
                            stack.append(
                                ("enter", entry_path, child_relative, relative, None)
                            )
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except (FileNotFoundError, PermissionError, OSError) as error:
                        add_issue(entry_path, "inspect", error)
                        continue

                    info = _file_info_from_entry(entry)
                    if info is None:
                        add_issue(entry_path, "stat", FileNotFoundError(str(entry_path)))
                        continue
                    if info.size < min_size:
                        continue
                    files.append(info)
                    node.direct_file_count += 1
                    node.direct_size += info.size
                    files_scanned += 1
                    bytes_scanned += info.size
                    if on_item:
                        on_item(info.path, False)
                    emit("scan", info.path)
        except (FileNotFoundError, PermissionError, OSError) as error:
            add_issue(current, "scandir", error)

    # Rebuild recursive totals bottom-up after all streamed children are known.
    for node in sorted(directories.values(), key=lambda item: item.depth, reverse=True):
        node.recursive_file_count = node.direct_file_count
        node.recursive_size = node.direct_size
        node.child_directories.sort()
        for child_relative in node.child_directories:
            child = directories.get(child_relative)
            if child:
                node.recursive_file_count += child.recursive_file_count
                node.recursive_size += child.recursive_size

    files.sort(key=lambda item: str(item.path).casefold())

    progress = ScanProgress(
        phase="complete",
        current_path=root,
        files_scanned=files_scanned,
        dirs_scanned=dirs_scanned,
        bytes_scanned=bytes_scanned,
        errors=error_count,
    )
    if on_progress:
        on_progress(progress)
    return ScanResult(
        root=root,
        files=tuple(files),
        directories=tuple(sorted(directories.values(), key=lambda item: (item.depth, item.relative_path))),
        issues=tuple(issues),
        progress=progress,
    )


def scan_directory(
    root: Path,
    ignore_dirs: Iterable[str] | None = None,
    min_size: int = 0,
    on_item: ScanProgressCallback | None = None,
    on_progress: StructuredProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> list[FileInfo]:
    """Backward-compatible list-returning scanner wrapper."""
    return list(
        scan_directory_result(
            root,
            ignore_dirs=ignore_dirs,
            min_size=min_size,
            on_item=on_item,
            on_progress=on_progress,
            cancellation=cancellation,
        ).files
    )
