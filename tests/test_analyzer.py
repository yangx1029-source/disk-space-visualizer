from pathlib import Path

from diskvis.analyzer import get_folder_stats, get_largest_files, get_summary, get_type_stats
from diskvis.models import FileInfo


def make_file(path: Path, size: int) -> FileInfo:
    suffix = path.suffix.lower() if path.suffix else "[no extension]"
    return FileInfo(path=path, size=size, suffix=suffix, modified_time=0)


def test_get_largest_files_sorts_descending(tmp_path: Path) -> None:
    files = [
        make_file(tmp_path / "a.txt", 10),
        make_file(tmp_path / "b.txt", 30),
        make_file(tmp_path / "c.txt", 20),
    ]

    result = get_largest_files(files, top_n=2)

    assert [file.path.name for file in result] == ["b.txt", "c.txt"]


def test_get_type_stats_groups_suffixes_and_no_extension(tmp_path: Path) -> None:
    files = [
        make_file(tmp_path / "a.TXT", 10),
        make_file(tmp_path / "b.txt", 20),
        make_file(tmp_path / "README", 5),
    ]

    result = get_type_stats(files, top_n=10)
    by_suffix = {stat.suffix: stat for stat in result}

    assert by_suffix[".txt"].count == 2
    assert by_suffix[".txt"].total_size == 30
    assert by_suffix["[no extension]"].count == 1


def test_get_folder_stats_groups_first_level_children(tmp_path: Path) -> None:
    root = tmp_path
    files = [
        make_file(root / "a.bin", 10),
        make_file(root / "photos" / "a.jpg", 20),
        make_file(root / "photos" / "nested" / "b.jpg", 30),
        make_file(root / "docs" / "c.pdf", 40),
    ]

    result = get_folder_stats(root, files, top_n=10)
    by_name = {stat.path.name: stat for stat in result}

    assert by_name["photos"].total_size == 50
    assert by_name["docs"].total_size == 40
    assert by_name["[root files]"].total_size == 10


def test_get_summary_can_preserve_scanned_folder_count(tmp_path: Path) -> None:
    files = [make_file(tmp_path / "nested" / "large.bin", 20)]

    summary = get_summary(tmp_path, files, scan_seconds=0.1, total_folders=3)

    assert summary.total_files == 1
    assert summary.total_folders == 3
