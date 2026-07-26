"""Directory scanning logic."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path

from .models import FileInfo

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


def _normalize_ignore_dirs(ignore_dirs: Iterable[str] | None) -> set[str]:
    names = DEFAULT_IGNORE_DIRS if ignore_dirs is None else ignore_dirs
    return {name.casefold() for name in names if name}


def _file_info_from_path(path: Path) -> FileInfo | None:
    try:
        stat = path.stat()
    except (FileNotFoundError, PermissionError, OSError):
        return None

    suffix = path.suffix.lower() if path.suffix else "[no extension]"
    return FileInfo(
        path=path,
        size=stat.st_size,
        suffix=suffix,
        modified_time=stat.st_mtime,
    )


def scan_directory(
    root: Path,
    ignore_dirs: Iterable[str] | None = None,
    min_size: int = 0,
    on_item: ScanProgressCallback | None = None,
) -> list[FileInfo]:
    """Recursively scan a directory and return matching files.

    Symlinked directories are skipped to avoid loops. Files that disappear or
    become unreadable during scanning are ignored.
    """
    root = Path(root).expanduser().resolve()
    ignore_names = _normalize_ignore_dirs(ignore_dirs)

    if min_size < 0:
        raise ValueError("min_size must be non-negative")
    if not root.exists():
        raise FileNotFoundError(f"path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"path is not a directory: {root}")

    files: list[FileInfo] = []
    stack = [root]
    seen_dirs: set[tuple[int, int] | str] = set()

    while stack:
        current = stack.pop()
        try:
            stat = current.stat()
        except (FileNotFoundError, PermissionError, OSError):
            continue

        dir_identity: tuple[int, int] | str
        if os.name == "nt":
            dir_identity = str(current.resolve())
        else:
            dir_identity = (stat.st_dev, stat.st_ino)
        if dir_identity in seen_dirs:
            continue
        seen_dirs.add(dir_identity)

        if on_item:
            on_item(current, True)

        try:
            entries = list(current.iterdir())
        except (FileNotFoundError, PermissionError, OSError):
            continue

        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name.casefold() in ignore_names:
                        continue
                    stack.append(entry)
                    continue
                if not entry.is_file():
                    continue
            except (FileNotFoundError, PermissionError, OSError):
                continue

            info = _file_info_from_path(entry)
            if info is None or info.size < min_size:
                continue
            files.append(info)
            if on_item:
                on_item(entry, False)

    return files
