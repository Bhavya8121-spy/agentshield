from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional, Sequence

from rich.markup import escape
from rich.prompt import Confirm
from rich.table import Table

from . import __version__
from .cleaning import clean_items
from .cleaners import UnknownCategoryError, all_names, build_cleaners
from .health import run_health_checks
from .largest import find_largest
from .models import CleanableItem
from .scanner import ScanReport, scan, select_items
from .ui import banner, console, largest_table, plan_table, print_scan
from .utils import format_size
from .web.server import DashboardServer
from .web.service import DashboardService

EXIT_OK = 0
EXIT_DECLINED = 1
EXIT_BAD_INPUT = 2
EXIT_INTERRUPTED = 130
DEFAULT_PORT = 8765


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="macclean",
        description="Safe, developer-focused macOS storage cleanup.",
    )
    parser.add_argument("--version", action="version", version=f"macclean {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="show what is using space (changes nothing)")
    _add_scan_options(scan_p)

    clean_p = sub.add_parser("clean", help="remove regenerable files (dry run by default)")
    _add_scan_options(clean_p)
    clean_p.add_argument(
        "--include-review", action="store_true", help="also clean REVIEW items"
    )
    clean_p.add_argument(
        "--execute", action="store_true", help="actually delete (default is a dry run)"
    )
    clean_p.add_argument(
        "-y", "--yes", action="store_true", help="skip the confirmation prompt"
    )

    largest_p = sub.add_parser("largest", help="list the biggest files (report only)")
    largest_p.add_argument("path", nargs="?", default="~")
    largest_p.add_argument("-n", "--number", type=int, default=20)
    largest_p.add_argument(
        "--min-size", type=int, default=100, metavar="MB", help="ignore files smaller than this"
    )

    sub.add_parser("doctor", help="check tools and permissions")

    web_p = sub.add_parser("web", help="open the dashboard in your browser")
    web_p.add_argument("--port", type=int, default=DEFAULT_PORT, help="0 picks a free port")
    web_p.add_argument("--no-browser", action="store_true", help="only print the address")
    return parser


def _add_scan_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--deep", action="store_true", help="also scan for stale node_modules (slower)"
    )
    parser.add_argument(
        "-c",
        "--category",
        action="append",
        metavar="NAME",
        help=f"limit to a category (repeatable): {', '.join(all_names())}",
    )


def _scan_with_spinner(args: argparse.Namespace) -> ScanReport:
    """Raises UnknownCategoryError for a bad --category."""
    cleaners = build_cleaners(deep=args.deep, only=args.category)
    with console.status("Scanning…"):
        return scan(cleaners)


def cmd_scan(args: argparse.Namespace) -> int:
    banner()
    report = _scan_with_spinner(args)
    print_scan(report)
    if any(item.cleanable for item in report.items):
        console.print("\nRun [bold]macclean clean[/bold] to review what would be removed.")
    return EXIT_OK


def cmd_clean(args: argparse.Namespace) -> int:
    banner()
    report = _scan_with_spinner(args)
    selected = select_items(report.items, include_review=args.include_review)
    if not selected:
        _explain_nothing_to_clean(report, args.include_review)
        return EXIT_OK

    total = sum(item.size for item in selected)
    console.print(plan_table(selected, Path.home()))
    console.print(f"  Total: [bold]{format_size(total)}[/bold] in {len(selected)} item(s)")

    if not args.execute:
        console.print(
            "\n[cyan]Dry run: nothing was deleted.[/cyan] "
            "Re-run with [bold]--execute[/bold] to remove these."
        )
        return EXIT_OK
    if not (args.yes or _user_confirms_deletion(selected, total)):
        console.print("Aborted. Nothing was deleted.")
        return EXIT_DECLINED
    return _delete_and_report(selected)


def _explain_nothing_to_clean(report: ScanReport, included_review: bool) -> None:
    console.print("[green]Nothing to clean.[/green]")
    if not included_review and any(item.cleanable for item in report.items):
        console.print("Some items need review: re-run with [bold]--include-review[/bold].")


def _user_confirms_deletion(items: Sequence[CleanableItem], total: int) -> bool:
    question = f"\nDelete these {len(items)} item(s) ({format_size(total)})?"
    return Confirm.ask(question, default=False)


def _delete_and_report(items: Sequence[CleanableItem]) -> int:
    result = clean_items(items, dry_run=False)
    console.print(f"\n[bold green]Freed {format_size(result.freed)}[/bold green]")
    for error in result.errors:
        console.print(f"[red]error:[/red] {escape(error)}")
    if not result.errors:
        return EXIT_OK
    console.print("[dim]Tip: run `macclean doctor` to check permissions.[/dim]")
    return EXIT_DECLINED


def cmd_largest(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser()
    if not root.is_dir():
        console.print(f"[red]error:[/red] not a directory: {escape(str(root))}")
        return EXIT_BAD_INPUT
    with console.status("Looking for large files…"):
        rows = find_largest(root, limit=args.number, min_size=args.min_size * 1_000_000)
    if not rows:
        console.print(f"No files over {args.min_size} MB found.")
        return EXIT_OK
    console.print(largest_table(rows, Path.home()))
    console.print("[dim]Report only: macclean never deletes these.[/dim]")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    table = Table(header_style="bold")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Notes")
    for check in run_health_checks():
        table.add_row(check.name, check.status, check.note)
    console.print(table)
    return EXIT_OK


def cmd_web(args: argparse.Namespace) -> int:
    try:
        server = DashboardServer(args.port, DashboardService())
    except OSError as exc:
        console.print(
            f"[red]error:[/red] can't listen on port {args.port}: {escape(exc.strerror or str(exc))}"
        )
        console.print("Try [bold]--port 0[/bold] to pick a free port.")
        return EXIT_BAD_INPUT
    console.print(f"macclean dashboard: [bold]{server.url}[/bold]  (Ctrl-C to stop)")
    if not args.no_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return EXIT_OK


COMMANDS = {
    "scan": cmd_scan,
    "clean": cmd_clean,
    "largest": cmd_largest,
    "doctor": cmd_doctor,
    "web": cmd_web,
}


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except UnknownCategoryError as exc:
        console.print(f"[red]error:[/red] {escape(str(exc))}")
        return EXIT_BAD_INPUT
    except KeyboardInterrupt:
        console.print("\nInterrupted.")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
