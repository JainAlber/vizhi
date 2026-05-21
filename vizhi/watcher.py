"""Real-time stdin watcher that prints a live flagged feed of agent activity."""

from __future__ import annotations

import sys
from typing import IO, Iterator

from rich.console import Console
from rich.text import Text

from vizhi.parser import ActionEvent, ActionType, parse_line

ACTION_STYLES: dict[ActionType, str] = {
    "command": "bold red",
    "file_access": "bold yellow",
    "network": "bold magenta",
    "unknown": "dim white",
}

ACTION_LABELS: dict[ActionType, str] = {
    "command": "CMD ",
    "file_access": "FILE",
    "network": "NET ",
    "unknown": "????",
}


def stream_lines(source: IO[str]) -> Iterator[str]:
    """Yield lines from `source` as they arrive, skipping blanks."""
    for line in iter(source.readline, ""):
        if line.strip():
            yield line


def render_event(console: Console, event: ActionEvent) -> None:
    """Print one ActionEvent to the console with color coding."""
    style = ACTION_STYLES[event.action_type]
    label = ACTION_LABELS[event.action_type]
    ts = event.timestamp.strftime("%H:%M:%S")

    line = Text()
    line.append(f"[{ts}] ", style="dim")
    line.append(f"{label} ", style=style)
    line.append(event.raw_text)
    console.print(line)


def watch(source: IO[str] | None = None, console: Console | None = None) -> None:
    """Read lines from `source` (default stdin), parse, and print live feed."""
    source = source if source is not None else sys.stdin
    console = console if console is not None else Console()

    console.print(
        "[bold cyan]Vizhi watcher started.[/] Waiting for input on stdin...",
        highlight=False,
    )

    try:
        for line in stream_lines(source):
            event = parse_line(line)
            render_event(console, event)
            # TODO(v1.2): forward event to classifier for risk severity tagging
            # TODO(v1.3): append event to session log for reporter
    except KeyboardInterrupt:
        console.print("\n[bold cyan]Vizhi watcher stopped.[/]")


if __name__ == "__main__":
    watch()
