from __future__ import annotations

import json
from pathlib import Path

import pytest

from diskvis.exporter import atomic_write_text, export_json


def test_export_json_replaces_destination_atomically(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "result.json"

    export_json({"path": tmp_path, "name": "磁盘"}, destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "path": str(tmp_path),
        "name": "磁盘",
    }
    assert list(destination.parent.glob("*.tmp")) == []


def test_atomic_write_keeps_existing_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "report.html"
    destination.write_text("old report", encoding="utf-8")

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError(f"cannot replace {source} with {target}")

    monkeypatch.setattr("diskvis.exporter.os.replace", fail_replace)

    with pytest.raises(OSError, match="cannot replace"):
        atomic_write_text("new report", destination)

    assert destination.read_text(encoding="utf-8") == "old report"
    assert list(tmp_path.glob(".*.tmp")) == []
