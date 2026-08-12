from __future__ import annotations

from pathlib import Path

from diskvis.models import ScanProgress
from diskvis.service import AnalysisOptions, analyze_directory


def test_analyze_directory_returns_execution_metadata(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "small.txt").write_text("abc", encoding="utf-8")
    (nested / "large.bin").write_bytes(b"123456")

    result = analyze_directory(AnalysisOptions(root=tmp_path, top=1))

    assert result.duplicates_scanned is False
    assert result.duplicate_group_count == 0
    assert result.scanned_file_count == 2
    assert result.scanned_folder_count == 2
    assert result.data["summary"]["total_size"] == 9
    assert len(result.data["largest_files"]) == 1
    assert result.data["largest_files"][0]["path"].endswith("large.bin")
    assert result.data["duplicates_scanned"] is False


def test_analyze_directory_respects_ignore_and_min_size(tmp_path: Path) -> None:
    ignored = tmp_path / "ignored"
    ignored.mkdir()
    (ignored / "large.bin").write_bytes(b"123456")
    (tmp_path / "small.txt").write_bytes(b"123")
    (tmp_path / "kept.txt").write_bytes(b"12345")

    result = analyze_directory(
        AnalysisOptions(
            root=tmp_path,
            min_size=5,
            ignore_dirs=["ignored"],
        )
    )

    assert result.scanned_file_count == 1
    assert result.data["summary"]["total_size"] == 5
    assert result.data["largest_files"][0]["path"].endswith("kept.txt")


def test_duplicate_scan_state_without_duplicates(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one", encoding="utf-8")
    (tmp_path / "two.txt").write_text("two", encoding="utf-8")

    result = analyze_directory(
        AnalysisOptions(root=tmp_path, include_duplicates=True)
    )

    assert result.duplicates_scanned is True
    assert result.duplicate_group_count == 0
    assert result.data["duplicates"] == []
    assert result.data["duplicate_potential_saved_size"] == 0


def test_duplicate_scan_state_with_duplicates(tmp_path: Path) -> None:
    (tmp_path / "one.bin").write_bytes(b"duplicate")
    (tmp_path / "two.bin").write_bytes(b"duplicate")

    result = analyze_directory(
        AnalysisOptions(root=tmp_path, include_duplicates=True)
    )

    assert result.duplicates_scanned is True
    assert result.duplicate_group_count == 1
    assert result.data["duplicate_group_count"] == 1
    assert result.data["duplicate_potential_saved_size"] == 9
    assert result.data["duplicate_potential_saved_size_human"] == "9 B"


def test_duplicate_progress_preserves_scan_totals(tmp_path: Path) -> None:
    (tmp_path / "one.bin").write_bytes(b"duplicate")
    (tmp_path / "two.bin").write_bytes(b"duplicate")
    events: list[ScanProgress] = []

    analyze_directory(
        AnalysisOptions(root=tmp_path, include_duplicates=True),
        on_progress=events.append,
    )

    duplicate_events = [event for event in events if event.phase == "duplicates"]
    assert duplicate_events
    assert all(event.files_scanned == 2 for event in duplicate_events)
    assert all(event.dirs_scanned == 1 for event in duplicate_events)
