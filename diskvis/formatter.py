"""Formatting helpers for sizes and user input."""

from __future__ import annotations

import re

_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")
_UNIT_FACTORS = {unit: 1024**index for index, unit in enumerate(_SIZE_UNITS)}


def format_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable value."""
    if size_bytes < 0:
        raise ValueError("size_bytes must be non-negative")

    value = float(size_bytes)
    unit = "B"
    for unit in _SIZE_UNITS:
        if value < 1024 or unit == _SIZE_UNITS[-1]:
            break
        value /= 1024

    if unit == "B":
        return f"{int(value)} B"
    return f"{value:.2f} {unit}"


def parse_size(size_text: str) -> int:
    """Parse strings like '100MB', '1 GB', or '512' into bytes."""
    text = size_text.strip().upper()
    if not text:
        raise ValueError("size text cannot be empty")

    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([KMGTPE]?B)?", text)
    if not match:
        raise ValueError(f"invalid size value: {size_text!r}")

    number_text, unit = match.groups()
    unit = unit or "B"
    if unit not in _UNIT_FACTORS:
        raise ValueError(f"unsupported size unit: {unit}")

    return int(float(number_text) * _UNIT_FACTORS[unit])
