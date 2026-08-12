"""Stable API contract helpers for the local dashboard."""

from __future__ import annotations

from http import HTTPStatus

API_VERSION = "1"
API_PREFIX = f"/api/v{API_VERSION}"
LEGACY_API_PREFIX = "/api"


class DashboardAPIError(Exception):
    """An expected client-facing API failure with a stable error code."""

    def __init__(self, status: HTTPStatus, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def normalize_api_path(path: str) -> str | None:
    """Return a version-independent API route while preserving v0.8 aliases."""
    if path == API_PREFIX:
        return "/"
    if path.startswith(f"{API_PREFIX}/"):
        return path[len(API_PREFIX) :]
    if path == LEGACY_API_PREFIX:
        return "/"
    if path.startswith(f"{LEGACY_API_PREFIX}/"):
        return path[len(LEGACY_API_PREFIX) :]
    return None


__all__ = [
    "API_PREFIX",
    "API_VERSION",
    "DashboardAPIError",
    "normalize_api_path",
]
