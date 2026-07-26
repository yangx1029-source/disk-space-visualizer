"""Duplicate file detection."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

from .models import DuplicateGroup, FileInfo


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            while chunk := file.read(chunk_size):
                digest.update(chunk)
    except (FileNotFoundError, PermissionError, OSError):
        return None
    return digest.hexdigest()


def find_duplicates(files: list[FileInfo], min_size: int = 0) -> list[DuplicateGroup]:
    """Find duplicate files by size pre-grouping and SHA256 hashing."""
    by_size: dict[int, list[FileInfo]] = defaultdict(list)
    for file in files:
        if file.size >= min_size:
            by_size[file.size].append(file)

    duplicates: list[DuplicateGroup] = []
    for size, same_size_files in by_size.items():
        if len(same_size_files) < 2:
            continue

        by_hash: dict[str, list[Path]] = defaultdict(list)
        for file in same_size_files:
            file_hash = _sha256(file.path)
            if file_hash is None:
                continue
            by_hash[file_hash].append(file.path)

        for file_hash, paths in by_hash.items():
            if len(paths) >= 2:
                duplicates.append(DuplicateGroup(size=size, hash=file_hash, files=paths))

    return sorted(duplicates, key=lambda group: group.potential_saved_size, reverse=True)


def potential_saved_size(groups: list[DuplicateGroup]) -> int:
    return sum(group.potential_saved_size for group in groups)
