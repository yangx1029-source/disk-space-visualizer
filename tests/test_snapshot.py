from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from diskvis import __version__
from diskvis.service import AnalysisResult
from diskvis.snapshot import (
    compare_snapshots,
    comparison_to_data,
    create_snapshot,
    load_snapshot,
    save_snapshot,
    snapshot_from_dict,
)


def _analysis_result(root: Path) -> AnalysisResult:
    return AnalysisResult(
        data={
            "summary": {
                "root": root,
                "total_size": 12,
                "total_files": 2,
                "total_folders": 2,
            },
            "folder_stats": [
                {
                    "path": root / "Downloads",
                    "count": 2,
                    "total_size": 12,
                }
            ],
            "largest_files": [
                {
                    "path": root / "Downloads" / "archive.zip",
                    "size": 12,
                    "suffix": ".zip",
                    "modified_time": 100.0,
                }
            ],
            "duplicates_scanned": True,
            "duplicate_group_count": 1,
            "duplicate_potential_saved_size": 6,
        },
        duplicates_scanned=True,
        duplicate_group_count=1,
        scanned_file_count=2,
        scanned_folder_count=2,
    )


def _snapshot_data(
    root: Path,
    *,
    timestamp: str,
    total_size: int,
    folders: list[dict[str, object]],
    files: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "metadata": {
            "version": "0.6.0",
            "timestamp": timestamp,
            "root_path": str(root),
        },
        "summary": {
            "total_size": total_size,
            "file_count": len(files or []),
            "folder_count": len(folders) + 1,
        },
        "folders": folders,
        "files": files or [],
        "duplicates": {
            "scanned": False,
            "group_count": 0,
            "potential_saved_size": 0,
        },
    }


def test_save_snapshot_writes_expected_json_structure(tmp_path: Path) -> None:
    root = tmp_path / "root"
    output = tmp_path / "snapshot.json"
    timestamp = datetime(2026, 7, 26, 8, 30, tzinfo=timezone.utc)

    saved_path = save_snapshot(
        _analysis_result(root),
        output_path=output,
        timestamp=timestamp,
    )
    data = json.loads(output.read_text(encoding="utf-8"))

    assert saved_path == output
    assert set(data) == {
        "metadata",
        "summary",
        "folders",
        "files",
        "duplicates",
    }
    assert data["metadata"] == {
        "version": __version__,
        "timestamp": "2026-07-26T08:30:00+00:00",
        "root_path": str(root),
    }
    assert data["summary"] == {
        "total_size": 12,
        "file_count": 2,
        "folder_count": 2,
    }
    assert data["folders"][0]["relative_path"] == "Downloads"
    assert data["files"][0]["relative_path"] == str(
        Path("Downloads") / "archive.zip"
    )
    assert data["duplicates"] == {
        "scanned": True,
        "group_count": 1,
        "potential_saved_size": 6,
    }


def test_load_snapshot_round_trips_saved_result(tmp_path: Path) -> None:
    root = tmp_path / "root"
    output = tmp_path / "snapshot.json"
    result = _analysis_result(root)

    save_snapshot(result, output_path=output)
    loaded = load_snapshot(output)
    expected = create_snapshot(result)

    assert loaded.summary == expected.summary
    assert loaded.folders == expected.folders
    assert loaded.files == expected.files
    assert loaded.duplicates == expected.duplicates
    assert loaded.metadata.root_path == str(root)


def test_save_snapshot_uses_default_history_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    saved_path = save_snapshot(
        _analysis_result(tmp_path / "root"),
        timestamp=datetime(2026, 7, 26, 14, 30, tzinfo=timezone.utc),
    )

    assert saved_path == Path(
        ".diskvis/snapshots/snapshot-20260726-143000.json"
    )
    assert saved_path.is_file()


def test_snapshot_prefers_complete_first_level_folder_stats(
    tmp_path: Path,
) -> None:
    result = _analysis_result(tmp_path / "root")
    result.data["all_folder_stats"] = [
        {
            "path": tmp_path / "root" / "Downloads",
            "count": 2,
            "total_size": 12,
        },
        {
            "path": tmp_path / "root" / "Archive",
            "count": 1,
            "total_size": 4,
        },
    ]

    snapshot = create_snapshot(result)

    assert [folder.name for folder in snapshot.folders] == [
        "Downloads",
        "Archive",
    ]


def test_compare_calculates_folder_growth_and_added_large_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    old = snapshot_from_dict(
        _snapshot_data(
            root,
            timestamp="2026-07-25T10:00:00+08:00",
            total_size=10,
            folders=[
                {
                    "name": "Downloads",
                    "path": str(root / "Downloads"),
                    "relative_path": "Downloads",
                    "file_count": 1,
                    "total_size": 10,
                }
            ],
        )
    )
    new = snapshot_from_dict(
        _snapshot_data(
            root,
            timestamp="2026-07-26T10:00:00+08:00",
            total_size=25,
            folders=[
                {
                    "name": "Downloads",
                    "path": str(root / "Downloads"),
                    "relative_path": "Downloads",
                    "file_count": 2,
                    "total_size": 25,
                }
            ],
            files=[
                {
                    "path": str(root / "Downloads" / "new.iso"),
                    "relative_path": str(Path("Downloads") / "new.iso"),
                    "size": 15,
                    "suffix": ".iso",
                    "modified_time": 0,
                }
            ],
        )
    )

    comparison = compare_snapshots(old, new)
    data = comparison_to_data(comparison)

    assert comparison.total_size_delta == 15
    assert comparison.growing_folders[0].name == "Downloads"
    assert comparison.growing_folders[0].size_delta == 15
    assert comparison.added_files[0].path.endswith("new.iso")
    assert data["total_size_delta_human"] == "+15 B"


def test_compare_calculates_removed_folder_and_file(tmp_path: Path) -> None:
    root = tmp_path / "root"
    old = snapshot_from_dict(
        _snapshot_data(
            root,
            timestamp="2026-07-25T10:00:00+08:00",
            total_size=8,
            folders=[
                {
                    "name": "Cache",
                    "path": str(root / "Cache"),
                    "relative_path": "Cache",
                    "file_count": 1,
                    "total_size": 8,
                }
            ],
            files=[
                {
                    "path": str(root / "Cache" / "old.bin"),
                    "relative_path": str(Path("Cache") / "old.bin"),
                    "size": 8,
                    "suffix": ".bin",
                    "modified_time": 0,
                }
            ],
        )
    )
    new = snapshot_from_dict(
        _snapshot_data(
            root,
            timestamp="2026-07-26T10:00:00+08:00",
            total_size=0,
            folders=[],
        )
    )

    comparison = compare_snapshots(old, new)

    assert comparison.total_size_delta == -8
    assert comparison.shrinking_folders[0].name == "Cache"
    assert comparison.shrinking_folders[0].size_delta == -8
    assert comparison.removed_files[0].path.endswith("old.bin")


def test_load_snapshot_rejects_invalid_structure(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"metadata": {}}', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid snapshot structure"):
        load_snapshot(path)


def test_snapshot_rejects_invalid_boolean_type(tmp_path: Path) -> None:
    root = tmp_path / "root"
    data = _snapshot_data(
        root,
        timestamp="2026-07-26T10:00:00+08:00",
        total_size=0,
        folders=[],
    )
    data["duplicates"]["scanned"] = "false"  # type: ignore[index]

    with pytest.raises(
        ValueError,
        match="duplicates.scanned must be a boolean",
    ):
        snapshot_from_dict(data)
