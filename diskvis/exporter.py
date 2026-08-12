"""JSON export utilities."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value


def export_json(data: Any, output_path: Path) -> None:
    text = json.dumps(to_jsonable(data), ensure_ascii=False, indent=2)
    atomic_write_text(text, output_path)


def atomic_write_text(text: str, output_path: Path) -> None:
    """Durably replace a text file without exposing partially written output."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        file = os.fdopen(descriptor, "w", encoding="utf-8", newline="")
        descriptor = -1
        with file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        if descriptor >= 0:
            with suppress(OSError):
                os.close(descriptor)
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)
        raise
