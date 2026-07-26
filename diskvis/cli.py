"""Command line interface for diskvis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from . import __version__
from .exporter import export_json
from .formatter import format_size, parse_size
from .report import generate_comparison_report, generate_html_report
from .scanner import DEFAULT_IGNORE_DIRS
from .service import AnalysisOptions, AnalysisResult, analyze_directory
from .snapshot import (
    compare_snapshots,
    comparison_to_data,
    load_snapshot,
    save_snapshot,
)

app = typer.Typer(
    help="Scan disk usage, save snapshots, and generate visual HTML reports.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"diskvis {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed version and exit.",
    ),
) -> None:
    """Disk Space Visualizer command line interface."""


def _merge_ignore(ignore: list[str] | None) -> list[str]:
    values = set(DEFAULT_IGNORE_DIRS)
    values.update(ignore or [])
    return sorted(value for value in values if value)


def _parse_min_size(min_size: str | None) -> int:
    if not min_size:
        return 0
    try:
        return parse_size(min_size)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _analyze_with_progress(options: AnalysisOptions) -> AnalysisResult:
    with Progress(
        SpinnerColumn("line"),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Scanning files...", total=None)

        def on_item(path: Path, is_dir: bool) -> None:
            label = "folder" if is_dir else "file"
            progress.update(task_id, description=f"Scanning {label}: {escape(path.name[:48])}")

        return analyze_directory(options, on_item=on_item)


def _summary_table(summary: dict[str, Any]) -> Table:
    table = Table(title="Scan Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Root", escape(str(summary["root"])))
    table.add_row("Total Size", summary["total_size_human"])
    table.add_row("Files", str(summary["total_files"]))
    table.add_row("Folders", str(summary["total_folders"]))
    table.add_row("Scan Time", summary["scan_seconds_text"])
    return table


def _largest_table(files: list[dict[str, Any]]) -> Table:
    table = Table(title="Largest Files")
    table.add_column("#", justify="right")
    table.add_column("Size", justify="right", style="green")
    table.add_column("Path")
    for index, file in enumerate(files, start=1):
        table.add_row(str(index), file["size_human"], escape(str(file["path"])))
    return table


def _type_table(stats: list[dict[str, Any]]) -> Table:
    table = Table(title="File Types")
    table.add_column("Type", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Size", justify="right", style="green")
    for stat in stats:
        table.add_row(stat["suffix"], str(stat["count"]), stat["total_size_human"])
    return table


def _folder_table(stats: list[dict[str, Any]]) -> Table:
    table = Table(title="Top Folders")
    table.add_column("Folder", style="cyan")
    table.add_column("Files", justify="right")
    table.add_column("Size", justify="right", style="green")
    for stat in stats:
        table.add_row(escape(str(stat["path"])), str(stat["count"]), stat["total_size_human"])
    return table


def _duplicates_table(groups: list[dict[str, Any]]) -> Table:
    table = Table(title="Duplicate Groups")
    table.add_column("#", justify="right")
    table.add_column("Files", justify="right")
    table.add_column("Each Size", justify="right", style="green")
    table.add_column("Potential Saved", justify="right", style="yellow")
    table.add_column("Hash")
    for index, group in enumerate(groups, start=1):
        table.add_row(
            str(index),
            str(len(group["files"])),
            group["size_human"],
            group["potential_saved_size_human"],
            group["hash"][:16] + "...",
        )
    return table


def _print_duplicate_paths(groups: list[dict[str, Any]]) -> None:
    for index, group in enumerate(groups, start=1):
        console.print(f"[cyan]Group {index} paths:[/cyan]")
        for path in group["files"]:
            console.print(f"  • {escape(str(path))}", overflow="fold")


def _print_scan_result(data: dict[str, Any]) -> None:
    console.print(_summary_table(data["summary"]))
    console.print(_largest_table(data["largest_files"]))
    console.print(_type_table(data["type_stats"]))
    console.print(_folder_table(data["folder_stats"]))


def _comparison_summary_table(data: dict[str, Any]) -> Table:
    table = Table(title="Space Change")
    table.add_column("Metric", style="cyan")
    table.add_column("Old", justify="right")
    table.add_column("New", justify="right")
    table.add_column("Change", justify="right", style="yellow")
    table.add_row(
        "Total Size",
        data["old"]["total_size_human"],
        data["new"]["total_size_human"],
        data["total_size_delta_human"],
    )
    table.add_row(
        "Files",
        str(data["old"]["file_count"]),
        str(data["new"]["file_count"]),
        f"{data['new']['file_count'] - data['old']['file_count']:+d}",
    )
    table.add_row(
        "Folders",
        str(data["old"]["folder_count"]),
        str(data["new"]["folder_count"]),
        f"{data['new']['folder_count'] - data['old']['folder_count']:+d}",
    )
    return table


def _folder_changes_table(
    changes: list[dict[str, Any]],
    title: str,
) -> Table:
    table = Table(title=title)
    table.add_column("Folder", style="cyan")
    table.add_column("Old", justify="right")
    table.add_column("New", justify="right")
    table.add_column("Change", justify="right", style="yellow")
    if not changes:
        table.add_row("No changes", "-", "-", "0 B")
        return table
    for change in changes:
        table.add_row(
            escape(str(change["name"])),
            change["old_size_human"],
            change["new_size_human"],
            change["size_delta_human"],
        )
    return table


def _file_changes_table(
    files: list[dict[str, Any]],
    title: str,
) -> Table:
    table = Table(title=title)
    table.add_column("Size", justify="right", style="green")
    table.add_column("Path", overflow="fold")
    if not files:
        table.add_row("-", "No files")
        return table
    for file in files:
        table.add_row(file["size_human"], escape(str(file["path"])))
    return table


@app.command()
def scan(
    path: Path = typer.Argument(..., help="Directory to scan."),
    top: int = typer.Option(10, "--top", min=1, help="Number of top results to display."),
    ignore: list[str] | None = typer.Option(
        None,
        "--ignore",
        "-i",
        help="Ignored directory name. Repeat this option for multiple names.",
    ),
    min_size: str | None = typer.Option(None, "--min-size", help="Only include files >= this size."),
    json_output: Path | None = typer.Option(None, "--json", help="Export scan result to JSON."),
) -> None:
    """Scan a directory and print terminal tables."""
    ignore_dirs = _merge_ignore(ignore)
    min_size_bytes = _parse_min_size(min_size)

    try:
        result = _analyze_with_progress(
            AnalysisOptions(
                root=path,
                top=top,
                min_size=min_size_bytes,
                ignore_dirs=ignore_dirs,
            )
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    data = result.data
    _print_scan_result(data)

    if json_output:
        try:
            export_json(data, json_output)
        except OSError as exc:
            console.print(f"[red]Could not write JSON:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        console.print(f"[green]JSON exported:[/green] {json_output}")


@app.command()
def report(
    path: Path = typer.Argument(..., help="Directory to scan."),
    output: Path = typer.Option(Path("reports/report.html"), "--output", "-o", help="HTML output path."),
    top: int = typer.Option(10, "--top", min=1, help="Number of chart/table rows."),
    ignore: list[str] | None = typer.Option(
        None,
        "--ignore",
        "-i",
        help="Ignored directory name. Repeat this option for multiple names.",
    ),
    min_size: str | None = typer.Option(None, "--min-size", help="Only include files >= this size."),
    include_duplicates: bool = typer.Option(
        False,
        "--include-duplicates",
        help="Run duplicate detection and include results in the report.",
    ),
    offline: bool = typer.Option(
        False,
        "--offline",
        help="Do not load ECharts from a CDN; use the built-in SVG fallback charts.",
    ),
) -> None:
    """Generate an HTML visual report."""
    ignore_dirs = _merge_ignore(ignore)
    min_size_bytes = _parse_min_size(min_size)

    try:
        result = _analyze_with_progress(
            AnalysisOptions(
                root=path,
                top=top,
                min_size=min_size_bytes,
                ignore_dirs=ignore_dirs,
                include_duplicates=include_duplicates,
            )
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    data = result.data
    try:
        generate_html_report(data, output, offline=offline)
    except OSError as exc:
        console.print(f"[red]Could not write HTML report:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]HTML report generated:[/green] {output}")


@app.command("duplicates")
def duplicates_cmd(
    path: Path = typer.Argument(..., help="Directory to scan."),
    ignore: list[str] | None = typer.Option(
        None,
        "--ignore",
        "-i",
        help="Ignored directory name. Repeat this option for multiple names.",
    ),
    min_size: str | None = typer.Option(None, "--min-size", help="Only check files >= this size."),
    top: int = typer.Option(10, "--top", min=1, help="Number of duplicate groups to display."),
) -> None:
    """Find duplicate files without deleting anything."""
    ignore_dirs = _merge_ignore(ignore)
    min_size_bytes = _parse_min_size(min_size)

    try:
        result = _analyze_with_progress(
            AnalysisOptions(
                root=path,
                top=top,
                min_size=min_size_bytes,
                ignore_dirs=ignore_dirs,
                include_duplicates=True,
            )
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    data = result.data
    console.print(_summary_table(data["summary"]))
    console.print(_duplicates_table(data["duplicates"]))
    _print_duplicate_paths(data["duplicates"])
    console.print(
        f"[yellow]Potential saved space:[/yellow] {data['duplicate_potential_saved_size_human']}"
    )


@app.command("snapshot")
def snapshot_cmd(
    path: Path = typer.Argument(..., help="Directory to scan."),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Snapshot JSON path. Defaults to .diskvis/snapshots/.",
    ),
    top: int = typer.Option(
        10,
        "--top",
        min=1,
        help="Number of large files retained.",
    ),
    ignore: list[str] | None = typer.Option(
        None,
        "--ignore",
        "-i",
        help="Ignored directory name. Repeat this option for multiple names.",
    ),
    min_size: str | None = typer.Option(
        None,
        "--min-size",
        help="Only include files >= this size.",
    ),
    include_duplicates: bool = typer.Option(
        False,
        "--include-duplicates",
        help="Run duplicate detection and retain its status.",
    ),
) -> None:
    """Scan a directory and save a versioned JSON snapshot."""
    ignore_dirs = _merge_ignore(ignore)
    min_size_bytes = _parse_min_size(min_size)

    try:
        result = _analyze_with_progress(
            AnalysisOptions(
                root=path,
                top=top,
                min_size=min_size_bytes,
                ignore_dirs=ignore_dirs,
                include_duplicates=include_duplicates,
            )
        )
        destination = save_snapshot(result, output_path=output)
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    summary = result.data["summary"]
    console.print(
        f"[green]Snapshot saved:[/green] {destination}\n"
        f"[cyan]Captured:[/cyan] {summary['total_files']} files, "
        f"{summary['total_folders']} folders, "
        f"{format_size(summary['total_size'])}"
    )


@app.command("compare")
def compare_cmd(
    old: Path = typer.Argument(..., help="Older snapshot JSON path."),
    new: Path = typer.Argument(..., help="Newer snapshot JSON path."),
    top: int = typer.Option(
        10,
        "--top",
        min=1,
        help="Number of folder and file changes to display.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Optional Liquid Glass HTML comparison report.",
    ),
) -> None:
    """Compare two saved snapshots."""
    try:
        old_snapshot = load_snapshot(old)
        new_snapshot = load_snapshot(new)
        comparison = compare_snapshots(old_snapshot, new_snapshot)
        data = comparison_to_data(comparison, top_n=top)
    except (FileNotFoundError, PermissionError, OSError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(_comparison_summary_table(data))
    console.print(
        _folder_changes_table(data["growing_folders"], "Top Growing Folders")
    )
    console.print(
        _folder_changes_table(data["shrinking_folders"], "Top Shrinking Folders")
    )
    console.print(_file_changes_table(data["added_files"], "New Large Files"))
    console.print(_file_changes_table(data["removed_files"], "Removed Large Files"))

    if not data["roots_match"]:
        console.print(
            "[yellow]Warning:[/yellow] snapshots use different root paths."
        )
    if output:
        try:
            generate_comparison_report(data, output)
        except OSError as exc:
            console.print(f"[red]Could not write comparison report:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        console.print(f"[green]Comparison report generated:[/green] {output}")


if __name__ == "__main__":
    app()
