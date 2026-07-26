"""HTML report generation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__
from .exporter import to_jsonable


def _env() -> Environment:
    template_dir = Path(__file__).parent / "templates"
    return Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(("html", "xml", "j2")),
    )


def _json(value: Any) -> str:
    # Prevent a file name containing </script> from terminating the data block.
    return (
        json.dumps(to_jsonable(value), ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _clean_html(html: str) -> str:
    """Normalize generated HTML so checked-in examples have stable whitespace."""
    return "\n".join(line.rstrip() for line in html.splitlines()) + "\n"


def generate_html_report(
    data: dict[str, Any], output_path: Path, offline: bool = False
) -> None:
    """Render a self-contained report with optional CDN-free chart mode."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    template = _env().get_template("report.html.j2")
    context = dict(data)
    context.setdefault("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    context["app_version"] = __version__
    context["offline"] = offline
    context.update(
        type_chart_json=_json(data.get("type_stats", [])),
        largest_chart_json=_json(data.get("largest_files", [])),
        folder_chart_json=_json(data.get("folder_stats", [])),
        distribution_chart_json=_json(data.get("size_distribution", {})),
    )
    html = _clean_html(template.render(**context))
    output_path.write_text(html, encoding="utf-8")


def generate_comparison_report(
    data: dict[str, Any],
    output_path: Path,
) -> None:
    """Render a self-contained Liquid Glass snapshot comparison."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    template = _env().get_template("comparison.html.j2")
    html = _clean_html(
        template.render(comparison=data, app_version=__version__)
    )
    output_path.write_text(html, encoding="utf-8")
