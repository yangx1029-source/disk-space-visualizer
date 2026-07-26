from pathlib import Path

from diskvis.duplicates import find_duplicates, potential_saved_size
from diskvis.models import FileInfo


def file_info(path: Path) -> FileInfo:
    stat = path.stat()
    return FileInfo(
        path=path,
        size=stat.st_size,
        suffix=path.suffix.lower() if path.suffix else "[no extension]",
        modified_time=stat.st_mtime,
    )


def test_same_content_files_are_detected(tmp_path: Path) -> None:
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    c = tmp_path / "c.bin"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    c.write_bytes(b"different")

    groups = find_duplicates([file_info(a), file_info(b), file_info(c)])

    assert len(groups) == 1
    assert sorted(path.name for path in groups[0].files) == ["a.bin", "b.bin"]
    assert potential_saved_size(groups) == 4


def test_same_size_different_content_is_not_duplicate(tmp_path: Path) -> None:
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"abcd")
    b.write_bytes(b"wxyz")

    groups = find_duplicates([file_info(a), file_info(b)])

    assert groups == []


def test_min_size_filters_duplicate_detection(tmp_path: Path) -> None:
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"same")
    b.write_bytes(b"same")

    groups = find_duplicates([file_info(a), file_info(b)], min_size=10)

    assert groups == []
