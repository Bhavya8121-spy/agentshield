from __future__ import annotations

from pathlib import Path
from typing import Sequence, Tuple

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from .models import CleanableItem, Safety
from .presentation import describe_target, display_path
from .scanner import ScanReport
from .utils import format_size

console = Console()

_BADGE = {
    Safety.SAFE: ("✓ SAFE", "green"),
    Safety.REVIEW: ("! REVIEW", "yellow"),
    Safety.DANGEROUS: ("✗ DANGEROUS", "red"),
}
_ORDER = {Safety.SAFE: 0, Safety.REVIEW: 1, Safety.DANGEROUS: 2}


def banner() -> None:
    console.print(
        Panel.fit(
            "[bold]macclean[/bold]\n[dim]Safe macOS storage cleanup[/dim]",
            border_style="cyan",
        )
    )


def _badge(safety: Safety) -> str:
    text, color = _BADGE[safety]
    return f"[{color}]{text}[/{color}]"


def scan_table(report: ScanReport) -> Table:
    table = Table(box=box.SIMPLE_HEAD, header_style="bold")
    table.add_column("Safety", no_wrap=True)
    table.add_column("Item")
    table.add_column("Size", justify="right", no_wrap=True)
    table.add_column("Action", no_wrap=True)
    for item in sorted(report.items, key=lambda i: (_ORDER[i.safety], -i.size)):
        if item.report_only or item.safety is Safety.DANGEROUS:
            action = "[dim]report only[/dim]"
        elif item.safety is Safety.REVIEW:
            action = "needs --include-review"
        else:
            action = "cleanable"
        table.add_row(
            _badge(item.safety),
            escape(item.label),
            format_size(item.size),
            action,
        )
    return table


def print_scan(report: ScanReport) -> None:
    if not report.items:
        console.print("[green]Nothing significant found.[/green]")
    else:
        console.print(scan_table(report))
        console.print(f"  Safe to reclaim   [bold green]{format_size(report.safe_total)}[/bold green]")
        console.print(f"  Needs review      [bold yellow]{format_size(report.review_total)}[/bold yellow]")
        console.print(f"  Report only       [dim]{format_size(report.report_only_total)}[/dim]")
    for name, message in report.errors.items():
        console.print(f"[red]warning:[/red] {escape(name)} scan failed: {escape(message)}")


def plan_table(items: Sequence[CleanableItem], home: Path) -> Table:
    table = Table(box=box.SIMPLE_HEAD, header_style="bold")
    table.add_column("Safety", no_wrap=True)
    table.add_column("Will remove")
    table.add_column("Size", justify="right", no_wrap=True)
    for item in sorted(items, key=lambda i: (_ORDER[i.safety], -i.size)):
        table.add_row(
            _badge(item.safety),
            escape(describe_target(item, home)),
            format_size(item.size),
        )
    return table


def largest_table(rows: Sequence[Tuple[int, Path]], home: Path) -> Table:
    table = Table(box=box.SIMPLE_HEAD, header_style="bold")
    table.add_column("Size", justify="right", no_wrap=True)
    table.add_column("File")
    for size, path in rows:
        table.add_row(format_size(size), escape(display_path(path, home)))
    return table
