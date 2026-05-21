"""Real-time stdin watcher that prints a live risk-tagged feed of agent activity."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from typing import IO, Iterator

from rich.console import Console
from rich.text import Text

from vizhi.classifier import ClassifiedEvent, RiskLevel, classify_event
from vizhi.parser import parse_line
from vizhi.reporter import generate_report, print_report, save_report

RISK_STYLES: dict[RiskLevel, str] = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "green",
    "info": "dim white",
}

RISK_LABELS: dict[RiskLevel, str] = {
    "critical": "CRIT",
    "high": "HIGH",
    "medium": " MED",
    "low": " LOW",
    "info": "INFO",
}


def stream_lines(source: IO[str]) -> Iterator[str]:
    """Yield lines from `source` as they arrive, skipping blanks."""
    for line in iter(source.readline, ""):
        if line.strip():
            yield line


def render_event(console: Console, classified: ClassifiedEvent) -> None:
    """Print one ClassifiedEvent to the console with risk-level color coding."""
    event = classified.event
    style = RISK_STYLES[classified.risk_level]
    label = RISK_LABELS[classified.risk_level]
    ts = event.timestamp.strftime("%H:%M:%S")

    line = Text()
    line.append(f"[{ts}] ", style="dim")
    line.append(f"{label} ", style=style)
    line.append(f"({event.action_type}) ", style="dim cyan")
    line.append(event.raw_text, style=style)
    line.append(f"  — {classified.reason}", style="dim")
    console.print(line)


def watch(
    source: IO[str] | None = None,
    console: Console | None = None,
    output_dir: str = "./vizhi_reports",
) -> None:
    """Read lines from `source` (default stdin), classify live, then report on exit."""
    source = source if source is not None else sys.stdin
    console = console if console is not None else Console()

    session_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)
    events: list[ClassifiedEvent] = []

    console.print(
        f"[bold cyan]Vizhi watcher started.[/] Session [dim]{session_id}[/]. "
        "Waiting for input on stdin... (Ctrl+C to end session)",
        highlight=False,
    )

    try:
        for line in stream_lines(source):
            event = parse_line(line)
            classified = classify_event(event)
            events.append(classified)
            render_event(console, classified)
    except KeyboardInterrupt:
        console.print("\n[bold cyan]Vizhi watcher stopped. Generating session report...[/]")
    finally:
        _finalize_session(
            console=console,
            events=events,
            session_id=session_id,
            started_at=started_at,
            output_dir=output_dir,
        )


def _finalize_session(
    *,
    console: Console,
    events: list[ClassifiedEvent],
    session_id: uuid.UUID,
    started_at: datetime,
    output_dir: str,
) -> None:
    """Build, display, and persist the session report."""
    report = generate_report(
        events,
        started_at=started_at,
        ended_at=datetime.now(timezone.utc),
        session_id=session_id,
    )
    print_report(report, console)
    path = save_report(report, output_dir=output_dir)
    console.print(f"[bold cyan]Report saved:[/] {path}")


if __name__ == "__main__":
    watch()
