from __future__ import annotations

import json
from pathlib import Path

import pytest

from diskvis.service import AnalysisOptions, analyze_directory
from diskvis.snapshot import (
    compare_snapshots,
    comparison_to_data,
    load_snapshot,
    save_snapshot,
    snapshot_from_dict,
)


def test_real_analysis_snapshot_uses_v2_and_complete_tree(tmp_path: Path) -> None:
    nested = tmp_path / "Downloads" / "Images"
    nested.mkdir(parents=True)
    (nested / "photo.jpg").write_bytes(b"1234")
    result = analyze_directory(AnalysisOptions(root=tmp_path, max_depth=None, max_nodes=None))
    output = tmp_path / "snapshot.json"

    save_snapshot(result, output)
    data = json.loads(output.read_text(encoding="utf-8"))
    loaded = load_snapshot(output)

    assert data["metadata"]["schema_version"] == 2
    assert data["metadata"]["app_version"] == "0.7.0"
    assert data["metadata"]["tree_complete"] is True
    assert any(folder["relative_path"] == "Downloads/Images" for folder in data["folders"])
    assert loaded.metadata.schema_version == 2


def test_future_snapshot_schema_is_rejected() -> None:
    data = {
        "metadata": {"schema_version": 99},
    }
    with pytest.raises(ValueError, match="unsupported snapshot schema"):
        snapshot_from_dict(data)


def test_deep_compare_reports_entered_left_and_size_changed_files(tmp_path: Path) -> None:
    root = str(tmp_path)

    def make(timestamp: str, total: int, file_size: int, include_new: bool) -> dict[str, object]:
        files = [
            {
                "path": str(tmp_path / "same.bin"),
                "relative_path": "same.bin",
                "size": file_size,
                "suffix": ".bin",
                "modified_time": 0,
            }
        ]
        if include_new:
            files.append(
                {
                    "path": str(tmp_path / "new.iso"),
                    "relative_path": "new.iso",
                    "size": 20,
                    "suffix": ".iso",
                    "modified_time": 0,
                }
            )
        return {
            "metadata": {
                "schema_version": 2,
                "app_version": "0.7.0",
                "timestamp": timestamp,
                "root_path": root,
                "platform": "windows",
                "case_sensitive": False,
                "scan_parameters": {},
                "tree_complete": True,
                "tree_limited": False,
                "error_summary": {},
            },
            "summary": {"total_size": total, "file_count": len(files), "folder_count": 1},
            "folders": [],
            "files": files,
            "duplicates": {"scanned": False, "group_count": 0, "potential_saved_size": 0},
        }

    old = snapshot_from_dict(make("2026-07-26T10:00:00+08:00", 10, 10, False))
    new = snapshot_from_dict(make("2026-07-27T10:00:00+08:00", 30, 20, True))
    comparison = compare_snapshots(old, new)
    data = comparison_to_data(comparison)

    assert [item.relative_path for item in comparison.entered_files] == ["new.iso"]
    assert comparison.size_changed_files[0][1].size == 20
    assert data["entered_top_files"][0]["relative_path"] == "new.iso"
