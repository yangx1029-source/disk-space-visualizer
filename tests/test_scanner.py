from pathlib import Path

import pytest

from diskvis.scanner import scan_directory


def test_scan_directory_counts_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("world", encoding="utf-8")

    files = scan_directory(tmp_path, ignore_dirs=[])

    assert len(files) == 2


def test_scan_directory_ignores_directories(tmp_path: Path) -> None:
    (tmp_path / "keep").mkdir()
    (tmp_path / "skip").mkdir()
    (tmp_path / "keep" / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "skip" / "b.txt").write_text("b", encoding="utf-8")

    files = scan_directory(tmp_path, ignore_dirs=["skip"])

    assert [file.path.name for file in files] == ["a.txt"]


def test_scan_directory_ignore_names_are_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / ".GIT").mkdir()
    (tmp_path / ".GIT" / "config").write_text("secret", encoding="utf-8")

    files = scan_directory(tmp_path, ignore_dirs=[".git"])

    assert files == []


def test_scan_directory_empty_ignore_list_disables_defaults(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("tracked", encoding="utf-8")

    files = scan_directory(tmp_path, ignore_dirs=[])

    assert [file.path.name for file in files] == ["config"]


def test_scan_directory_min_size(tmp_path: Path) -> None:
    (tmp_path / "small.bin").write_bytes(b"1")
    (tmp_path / "large.bin").write_bytes(b"12345")

    files = scan_directory(tmp_path, ignore_dirs=[], min_size=5)

    assert [file.path.name for file in files] == ["large.bin"]


def test_scan_directory_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        scan_directory(tmp_path / "missing")
