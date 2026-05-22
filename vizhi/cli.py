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
from vizhi.hook_receiver import receive as hook_receive
from vizhi.installer import (
    get_settings_path,
    install_hook,
    load_settings,
    save_settings,
    uninstall_hook,
)
from vizhi.parser import ActionEvent
from vizhi.reporter import SessionReport, print_report
from vizhi.watcher import watch

DEFAULT_OUTPUT_DIR = "./vizhi_reports"

# TODO(v1.5): add `vizhi list` (list past reports) + `vizhi show <id>` (show specific report).
# TODO(v2.0): add `vizhi watch --adapter <name>` once we support adapters beyond Claude Code.
# TODO(v2.2): add `vizhi hook --pre` for PreToolUse blocking decisions.
# TODO(v2.3): add `--scope project` flag to install-hook (project-local .claude/settings.json).


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


@main.command(
    "hook",
    help="Receive a single PostToolUse JSON payload from stdin (for Claude Code hooks).",
)
@click.option(
    "--output-dir",
    "output_dir",
    default=DEFAULT_OUTPUT_DIR,
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Directory where session_<sessionId>.jsonl is appended.",
)
def hook_cmd(output_dir: str) -> None:
    """Entry point invoked by Claude Code's PostToolUse hook.

    Reads one JSON payload from stdin, classifies it, and appends a JSON line
    to session_<sessionId>.jsonl in `output_dir`. Never crashes on bad input —
    failures are logged to stderr and the command exits cleanly.
    """
    raise SystemExit(hook_receive(output_dir=output_dir))


@main.command(
    "install-hook",
    help="Install the vizhi PostToolUse hook into ~/.claude/settings.json.",
)
def install_hook_cmd() -> None:
    """Add the vizhi PostToolUse hook so Claude Code invokes it after every tool call."""
    console = Console()
    path = get_settings_path()
    try:
        settings = load_settings(path)
    except (json.JSONDecodeError, ValueError) as exc:
        console.print(
            f"[red]Could not read[/] [bold]{path}[/]: {exc}\n"
            "Fix or remove the file, then retry."
        )
        raise SystemExit(1)

    updated, already_installed = install_hook(settings)
    if already_installed:
        console.print(
            f"[yellow]Vizhi hook already installed in[/] [bold]{path}[/]. "
            "No changes made."
        )
        return

    save_settings(path, updated)
    console.print(
        f"[green]Installed Vizhi PostToolUse hook[/] in [bold]{path}[/].\n"
        "Claude Code will now call [bold]python -m vizhi.hook_receiver[/] "
        "after every tool execution."
    )


@main.command(
    "uninstall-hook",
    help="Remove the vizhi PostToolUse hook from ~/.claude/settings.json.",
)
def uninstall_hook_cmd() -> None:
    """Remove the vizhi PostToolUse hook, leaving all other settings untouched."""
    console = Console()
    path = get_settings_path()
    if not path.exists():
        console.print(
            f"[yellow]No settings file at[/] [bold]{path}[/] — nothing to remove."
        )
        return

    try:
        settings = load_settings(path)
    except (json.JSONDecodeError, ValueError) as exc:
        console.print(
            f"[red]Could not read[/] [bold]{path}[/]: {exc}\n"
            "Fix or remove the file, then retry."
        )
        raise SystemExit(1)

    updated, was_removed = uninstall_hook(settings)
    if not was_removed:
        console.print(
            f"[yellow]Vizhi hook not found in[/] [bold]{path}[/]. "
            "No changes made."
        )
        return

    save_settings(path, updated)
    console.print(
        f"[green]Removed Vizhi PostToolUse hook[/] from [bold]{path}[/]."
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
