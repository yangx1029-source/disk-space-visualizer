"""Generate the public demo report from examples/sample-data.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from diskvis.report import (  # noqa: E402
    generate_comparison_report,
    generate_html_report,
)
from diskvis.snapshot import (  # noqa: E402
    compare_snapshots,
    comparison_to_data,
    load_snapshot,
)


def main() -> None:
    data_path = PROJECT_ROOT / "examples" / "sample-data.json"
    output_path = PROJECT_ROOT / "examples" / "sample-report.html"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    generate_html_report(data, output_path, offline=True)
    print(f"Generated demo report: {output_path}")

    old_snapshot = load_snapshot(
        PROJECT_ROOT / "examples" / "sample-snapshot-old.json"
    )
    new_snapshot = load_snapshot(
        PROJECT_ROOT / "examples" / "sample-snapshot-new.json"
    )
    comparison_output = PROJECT_ROOT / "examples" / "sample-comparison.html"
    comparison = compare_snapshots(old_snapshot, new_snapshot)
    generate_comparison_report(
        comparison_to_data(comparison),
        comparison_output,
    )
    print(f"Generated comparison report: {comparison_output}")


if __name__ == "__main__":
    main()
