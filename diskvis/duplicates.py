"""Duplicate file detection with size pre-grouping and stable hashing."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from .models import CancellationToken, DuplicateGroup, FileInfo, ScanProgress

ProgressCallback = Callable[[ScanProgress], None]


def _sha256(
    path: Path,
    chunk_size: int = 1024 * 1024,
    cancellation: CancellationToken | None = None,
) -> str | None:
    """Hash in chunks and reject files that change during the read."""
    digest = hashlib.sha256()
    try:
        before = path.stat()
        with path.open("rb") as file:
            while chunk := file.read(chunk_size):
                if cancellation:
                    cancellation.raise_if_cancelled()
                digest.update(chunk)
        after = path.stat()
    except (FileNotFoundError, PermissionError, OSError):
        return None
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        return None
    return digest.hexdigest()


def _physical_key(file: FileInfo) -> tuple[int, int] | str:
    if file.device not in (None, 0) and file.inode not in (None, 0):
        return (file.device, file.inode)
    return str(file.path)


def find_duplicates(
    files: list[FileInfo],
    min_size: int = 0,
    cancellation: CancellationToken | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[DuplicateGroup]:
    """Find duplicate files by size, then SHA256.

    Hard-link aliases are reported in ``files`` but do not count as reclaimable
    copies because they already share the same physical storage.
    """
    by_size: dict[int, list[FileInfo]] = defaultdict(list)
    for file in files:
        if cancellation:
            cancellation.raise_if_cancelled()
        if file.size >= min_size:
            by_size[file.size].append(file)

    candidate_total = sum(
        len(same_size_files)
        for same_size_files in by_size.values()
        if len(same_size_files) >= 2
    )
    hashes_completed = 0
    duplicates: list[DuplicateGroup] = []
    for size, same_size_files in sorted(by_size.items()):
        if len(same_size_files) < 2:
            continue

        representatives: dict[tuple[int, int] | str, FileInfo] = {}
        aliases: dict[tuple[int, int] | str, list[Path]] = defaultdict(list)
        for file in same_size_files:
            key = _physical_key(file)
            if key in representatives:
                aliases[key].append(file.path)
            else:
                representatives[key] = file

        by_hash: dict[str, list[Path]] = defaultdict(list)
        physical_counts: dict[str, int] = defaultdict(int)
        hard_link_aliases: dict[str, list[Path]] = defaultdict(list)
        for key, file in representatives.items():
            if cancellation:
                cancellation.raise_if_cancelled()
            file_hash = _sha256(file.path, cancellation=cancellation)
            hashes_completed += 1
            if on_progress:
                on_progress(
                    ScanProgress(
                        phase="duplicates",
                        current_path=file.path,
                        duplicate_candidates=candidate_total,
                        hashes_completed=hashes_completed,
                        hashes_total=len(representatives),
                    )
                )
            if file_hash is None:
                continue
            by_hash[file_hash].append(file.path)
            physical_counts[file_hash] += 1
            if aliases.get(key):
                hard_link_aliases[file_hash].extend([file.path, *aliases[key]])

        for file_hash, paths in by_hash.items():
            if physical_counts[file_hash] >= 2 or hard_link_aliases[file_hash]:
                all_paths = list(dict.fromkeys(paths + hard_link_aliases[file_hash]))
                duplicates.append(
                    DuplicateGroup(
                        size=size,
                        hash=file_hash,
                        files=all_paths,
                        physical_file_count=physical_counts[file_hash],
                        hard_link_aliases=hard_link_aliases[file_hash],
                    )
                )

    return sorted(
        duplicates,
        key=lambda group: (-group.potential_saved_size, group.size, group.hash),
    )


def potential_saved_size(groups: list[DuplicateGroup]) -> int:
    return sum(group.potential_saved_size for group in groups)
