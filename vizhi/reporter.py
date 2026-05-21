"""Session report generator: collect classified events and emit terminal + JSON summary."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from vizhi.classifier import ClassifiedEvent, RiskLevel

# TODO(v1.4): make output format pluggable (markdown, HTML) alongside JSON.
# TODO(v2.0): persist reports to a database (Supabase) instead of local JSON only.

RISK_ORDER: tuple[RiskLevel, ...] = ("critical", "high", "medium", "low", "info")
FLAGGED_LEVELS: frozenset[RiskLevel] = frozenset({"critical", "high"})

RISK_STYLES: dict[RiskLevel, str] = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "green",
    "info": "dim white",
}


@dataclass(frozen=True)
class SessionReport:
    """Aggregated summary of one Vizhi watcher session."""

    session_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    total_actions: int
    risk_breakdown: dict[RiskLevel, int]
    flagged_events: list[ClassifiedEvent]
    all_events: list[ClassifiedEvent]


def generate_report(
    events: list[ClassifiedEvent],
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    session_id: uuid.UUID | None = None,
) -> SessionReport:
    """Aggregate a list of ClassifiedEvents into a SessionReport."""
    sid = session_id if session_id is not None else uuid.uuid4()
    end = ended_at if ended_at is not None else datetime.now(timezone.utc)
    if started_at is not None:
        start = started_at
    elif events:
        start = events[0].event.timestamp
    else:
        start = end

    breakdown: dict[RiskLevel, int] = {lvl: 0 for lvl in RISK_ORDER}
    for ce in events:
        breakdown[ce.risk_level] += 1

    flagged = [ce for ce in events if ce.risk_level in FLAGGED_LEVELS]

    return SessionReport(
        session_id=sid,
        started_at=start,
        ended_at=end,
        total_actions=len(events),
        risk_breakdown=breakdown,
        flagged_events=flagged,
        all_events=list(events),
    )


def print_report(report: SessionReport, console: Console) -> None:
    """Print a rich-formatted summary of a SessionReport to the console."""
    duration_secs = (report.ended_at - report.started_at).total_seconds()
    header = (
        f"[bold]Session:[/]       {report.session_id}\n"
        f"[bold]Started:[/]       {report.started_at.isoformat(timespec='seconds')}\n"
        f"[bold]Ended:[/]         {report.ended_at.isoformat(timespec='seconds')}\n"
        f"[bold]Duration:[/]      {_fmt_duration(duration_secs)}\n"
        f"[bold]Total actions:[/] {report.total_actions}"
    )
    console.print(Panel(header, title="Vizhi Session Report", border_style="cyan"))

    table = Table(title="Risk Breakdown", header_style="bold", show_lines=False)
    table.add_column("Risk", justify="left")
    table.add_column("Count", justify="right")
    table.add_column("Percent", justify="right")

    total = max(report.total_actions, 1)
    for lvl in RISK_ORDER:
        count = report.risk_breakdown.get(lvl, 0)
        pct = (count / total) * 100.0 if report.total_actions else 0.0
        table.add_row(
            f"[{RISK_STYLES[lvl]}]{lvl}[/]",
            str(count),
            f"{pct:.1f}%",
        )
    console.print(table)

    if not report.flagged_events:
        console.print("[green]No critical or high-risk events this session.[/]")
        return

    flagged_table = Table(
        title="Top Flagged Events (critical / high)",
        header_style="bold",
    )
    flagged_table.add_column("Time", style="dim")
    flagged_table.add_column("Risk")
    flagged_table.add_column("Type", style="dim cyan")
    flagged_table.add_column("Action")
    flagged_table.add_column("Reason", style="dim")

    for ce in report.flagged_events:
        ts = ce.event.timestamp.strftime("%H:%M:%S")
        flagged_table.add_row(
            ts,
            f"[{RISK_STYLES[ce.risk_level]}]{ce.risk_level}[/]",
            ce.event.action_type,
            ce.event.raw_text,
            ce.reason,
        )
    console.print(flagged_table)


def save_report(report: SessionReport, output_dir: str = "./vizhi_reports") -> str:
    """Write `report` to a JSON file under `output_dir`. Returns the file path."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    ts_slug = report.started_at.strftime("%Y%m%dT%H%M%SZ")
    filename = f"session_{report.session_id}_{ts_slug}.json"
    file_path = out_path / filename

    payload = _report_to_dict(report)
    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(file_path)


def _report_to_dict(report: SessionReport) -> dict:
    """Convert a SessionReport to a JSON-serializable dict."""
    return {
        "session_id": str(report.session_id),
        "started_at": report.started_at.isoformat(),
        "ended_at": report.ended_at.isoformat(),
        "duration_seconds": (report.ended_at - report.started_at).total_seconds(),
        "total_actions": report.total_actions,
        "risk_breakdown": {lvl: report.risk_breakdown.get(lvl, 0) for lvl in RISK_ORDER},
        "flagged_events": [_classified_to_dict(ce) for ce in report.flagged_events],
        "all_events": [_classified_to_dict(ce) for ce in report.all_events],
    }


def _classified_to_dict(ce: ClassifiedEvent) -> dict:
    """Convert a ClassifiedEvent (and its inner ActionEvent) to a JSON-safe dict."""
    return {
        "timestamp": ce.event.timestamp.isoformat(),
        "action_type": ce.event.action_type,
        "raw_text": ce.event.raw_text,
        "metadata": dict(ce.event.metadata),
        "risk_level": ce.risk_level,
        "reason": ce.reason,
    }


def _fmt_duration(seconds: float) -> str:
    """Format a duration in seconds as `Hh Mm Ss` (omitting empty leading units)."""
    seconds = max(0.0, seconds)
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"
