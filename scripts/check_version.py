"""Validate that package metadata and the runtime report the same version."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    version_source = (root / "diskvis" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', version_source)
    if not match:
        print("Could not find diskvis.__version__", file=sys.stderr)
        return 1
    version = match.group(1)
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    if 'path = "diskvis/version.py"' not in pyproject:
        print("pyproject.toml does not use the single version source", file=sys.stderr)
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
