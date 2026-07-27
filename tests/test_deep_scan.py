from __future__ import annotations

import os
from pathlib import Path

import pytest

from diskvis.duplicates import find_duplicates
from diskvis.models import AnalysisCancelled, CancellationToken
from diskvis.scanner import scan_directory_result


def test_scan_result_aggregates_nested_directories_and_root_files(tmp_path: Path) -> None:
    (tmp_path / "root.txt").write_bytes(b"12")
    nested = tmp_path / "一级" / "二级"
    nested.mkdir(parents=True)
    (nested / "deep.bin").write_bytes(b"12345")

    result = scan_directory_result(tmp_path, ignore_dirs=[])
    by_path = {node.relative_path: node for node in result.directories}

    assert by_path[""].direct_size == 2
    assert by_path[""].recursive_size == 7
    assert by_path["一级"].recursive_size == 5
    assert by_path["一级/二级"].direct_size == 5
    assert result.progress.files_scanned == 2


def test_scan_cancellation_is_cooperative(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("data", encoding="utf-8")
    token = CancellationToken()
    token.cancel()

    with pytest.raises(AnalysisCancelled):
        scan_directory_result(tmp_path, ignore_dirs=[], cancellation=token)


def test_hard_link_alias_does_not_count_as_reclaimable_space(tmp_path: Path) -> None:
    original = tmp_path / "original.bin"
    alias = tmp_path / "alias.bin"
    original.write_bytes(b"same content")
    try:
        os.link(original, alias)
    except (OSError, NotImplementedError):
        pytest.skip("hard links are not available on this filesystem")

    result = scan_directory_result(tmp_path, ignore_dirs=[])
    groups = find_duplicates(list(result.files))

    assert groups
    assert sorted(path.name for path in groups[0].files) == ["alias.bin", "original.bin"]
    assert groups[0].potential_saved_size == 0
    assert alias in groups[0].hard_link_aliases
