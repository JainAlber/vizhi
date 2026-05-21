"""Real-time stdin watcher that prints a live risk-tagged feed of agent activity."""

from __future__ import annotations

import sys
from typing import IO, Iterator

from rich.console import Console
from rich.text import Text

from vizhi.classifier import ClassifiedEvent, RiskLevel, classify_event
from vizhi.parser import parse_line

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


def watch(source: IO[str] | None = None, console: Console | None = None) -> None:
    """Read lines from `source` (default stdin), classify, and print live feed."""
    source = source if source is not None else sys.stdin
    console = console if console is not None else Console()

    console.print(
        "[bold cyan]Vizhi watcher started.[/] Waiting for input on stdin...",
        highlight=False,
    )

    try:
        for line in stream_lines(source):
            event = parse_line(line)
            classified = classify_event(event)
            render_event(console, classified)
            # TODO(v1.3): append classified event to session log for reporter
    except KeyboardInterrupt:
        console.print("\n[bold cyan]Vizhi watcher stopped.[/]")


if __name__ == "__main__":
    watch()
