"""Dependency-free structured logging for the local dashboard."""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_EXTRA_FIELDS = (
    "event",
    "request_id",
    "method",
    "path",
    "status",
    "duration_ms",
    "task_id",
    "state",
    "error_type",
)


class JsonLogFormatter(logging.Formatter):
    """Render one compact JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def create_dashboard_logger(
    log_dir: Path,
    instance_id: str,
) -> tuple[logging.Logger, Path | None, str | None]:
    """Create an isolated rotating logger, degrading safely on read-only hosts."""
    logger = logging.getLogger(f"diskvis.dashboard.{instance_id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()
    try:
        destination = Path(log_dir).expanduser().resolve() / "dashboard.jsonl"
        destination.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            destination,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError as exc:
        logger.addHandler(logging.NullHandler())
        return logger, None, str(exc)
    handler.setFormatter(JsonLogFormatter())
    logger.addHandler(handler)
    return logger, destination, None


def close_dashboard_logger(logger: logging.Logger) -> None:
    """Flush and detach handlers so a packaged executable can exit cleanly."""
    for handler in tuple(logger.handlers):
        with suppress(Exception):
            handler.flush()
        with suppress(Exception):
            handler.close()
        logger.removeHandler(handler)


__all__ = ["close_dashboard_logger", "create_dashboard_logger"]
