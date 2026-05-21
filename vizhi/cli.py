"""Vizhi CLI entrypoint (Click-based)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console

from vizhi import __version__
from vizhi.classifier import ClassifiedEvent
from vizhi.parser import ActionEvent
from vizhi.reporter import SessionReport, print_report
from vizhi.watcher import watch

DEFAULT_OUTPUT_DIR = "./vizhi_reports"

# TODO(v1.5): add `vizhi list` (list past reports) + `vizhi show <id>` (show specific report).
# TODO(v2.0): add `vizhi watch --adapter <name>` once we support adapters beyond Claude Code.


@click.group(help="Vizhi — real-time security monitor for AI agents.")
@click.version_option(__version__, prog_name="vizhi")
def main() -> None:
    """Top-level CLI group. Subcommands attach below."""


@main.command("start", help="Start the watcher. Reads agent output from stdin.")
@click.option(
    "--output-dir",
    "output_dir",
    default=DEFAULT_OUTPUT_DIR,
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Directory where the session JSON report is written on exit.",
)
def start_cmd(output_dir: str) -> None:
    """Run the live watcher until Ctrl+C / EOF, then write the session report."""
    watch(output_dir=output_dir)


@main.command("report", help="Pretty-print the most recent session report.")
@click.option(
    "--output-dir",
    "output_dir",
    default=DEFAULT_OUTPUT_DIR,
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Directory to search for session_*.json reports.",
)
def report_cmd(output_dir: str) -> None:
    """Load the latest JSON report from `output_dir` and render it."""
    console = Console()
    path = _latest_report_path(output_dir)
    if path is None:
        console.print(
            f"[yellow]No reports found in[/] [bold]{output_dir}[/]. "
            "Run [bold]vizhi start[/] first."
        )
        raise SystemExit(1)

    console.print(f"[dim]Loading report:[/] {path}")
    report = _load_report(path)
    print_report(report, console)


def _latest_report_path(output_dir: str) -> Path | None:
    """Return the most-recently-modified `session_*.json` in `output_dir`, or None."""
    out = Path(output_dir)
    if not out.exists():
        return None
    candidates = sorted(
        out.glob("session_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _load_report(path: Path) -> SessionReport:
    """Deserialize a SessionReport from its JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))

    all_events = [_event_from_dict(d) for d in data.get("all_events", [])]
    flagged_events = [_event_from_dict(d) for d in data.get("flagged_events", [])]

    return SessionReport(
        session_id=uuid.UUID(data["session_id"]),
        started_at=datetime.fromisoformat(data["started_at"]),
        ended_at=datetime.fromisoformat(data["ended_at"]),
        total_actions=int(data["total_actions"]),
        risk_breakdown=dict(data["risk_breakdown"]),
        flagged_events=flagged_events,
        all_events=all_events,
    )


def _event_from_dict(d: dict) -> ClassifiedEvent:
    """Rebuild a ClassifiedEvent (and its inner ActionEvent) from a JSON dict."""
    action = ActionEvent(
        timestamp=datetime.fromisoformat(d["timestamp"]),
        raw_text=d["raw_text"],
        action_type=d["action_type"],
        metadata=dict(d.get("metadata", {})),
    )
    return ClassifiedEvent(
        event=action,
        risk_level=d["risk_level"],
        reason=d["reason"],
    )


if __name__ == "__main__":
    main()
