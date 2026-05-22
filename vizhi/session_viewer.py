"""Live tail of a session_<sessionId>.jsonl log file.

Watches the JSONL log written by `hook_receiver.receive()`, deserializes each
new line into a ClassifiedEvent, and renders it via `render_event()` so the
user sees a live risk-tagged feed while Claude Code runs in another window.

Polling is used (no inotify / fsevents dependency) so the module works
identically on Windows, macOS, and Linux.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import IO

from rich.console import Console

from vizhi.classifier import ClassifiedEvent
from vizhi.parser import ActionEvent
from vizhi.watcher import render_event

POLL_INTERVAL_SECONDS: float = 0.2
FILE_WAIT_SECONDS: float = 3.0

# TODO(v2.4): swap polling for a native file watcher (watchdog) for lower latency.
# TODO(v2.4): support `--follow-all` to multiplex multiple session files at once.


def find_latest_session(output_dir: str) -> str | None:
    """Return the session ID of the most-recently-modified session_*.jsonl in `output_dir`.

    Returns None if `output_dir` does not exist or contains no matching files.
    The session ID is the substring between `session_` and `.jsonl` in the filename.
    """
    out = Path(output_dir)
    if not out.exists():
        return None

    candidates = sorted(
        out.glob("session_*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None

    name = candidates[0].name
    return name[len("session_") : -len(".jsonl")]


def tail_session(
    session_id: str,
    output_dir: str,
    console: Console,
) -> list[ClassifiedEvent]:
    """Tail session_<sessionId>.jsonl in `output_dir` and render each new event live.

    Reads any pre-existing lines first, renders them, then polls every
    POLL_INTERVAL_SECONDS for new lines. Returns the full list of events seen
    once polling ends (Ctrl+C is treated as a clean stop).

    Raises FileNotFoundError if the session file does not appear within
    FILE_WAIT_SECONDS — caller is expected to surface the message to the user.
    """
    path = Path(output_dir) / f"session_{session_id}.jsonl"
    _wait_for_file(path, FILE_WAIT_SECONDS)

    events: list[ClassifiedEvent] = []

    with path.open("r", encoding="utf-8") as f:
        _drain(f, events, console)
        try:
            while True:
                if _drain(f, events, console) == 0:
                    time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            return events

    return events


def _wait_for_file(path: Path, timeout_seconds: float) -> None:
    """Block until `path` exists or `timeout_seconds` elapse. Raise FileNotFoundError on timeout."""
    deadline = time.monotonic() + timeout_seconds
    while not path.exists():
        if time.monotonic() >= deadline:
            raise FileNotFoundError(
                f"Session file not found: {path}\n"
                "Either the session ID is wrong or Claude Code has not yet run "
                "a tool in this session. Run `vizhi install-hook` and trigger any "
                "tool in Claude Code, then retry."
            )
        time.sleep(POLL_INTERVAL_SECONDS)


def _drain(f: IO[str], events: list[ClassifiedEvent], console: Console) -> int:
    """Read all complete lines currently available on `f`, render + collect them.

    A line is only consumed if it ends in `\\n` — partial writes are left in
    place and re-read on the next poll. Returns the number of lines consumed
    on this call.
    """
    consumed = 0
    while True:
        pos = f.tell()
        line = f.readline()
        if not line:
            return consumed
        if not line.endswith("\n"):
            f.seek(pos)
            return consumed

        stripped = line.strip()
        if not stripped:
            continue

        try:
            classified = _event_from_line(stripped)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            console.print(f"[dim red][vizhi watch] skipping malformed line: {exc}[/]")
            continue

        events.append(classified)
        render_event(console, classified)
        consumed += 1


def _event_from_line(raw: str) -> ClassifiedEvent:
    """Deserialize one JSONL record into a ClassifiedEvent."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object, got {type(data).__name__}")

    event = ActionEvent(
        timestamp=datetime.fromisoformat(data["timestamp"]),
        raw_text=data["raw_text"],
        action_type=data["action_type"],
        metadata=dict(data.get("metadata", {})),
    )
    return ClassifiedEvent(
        event=event,
        risk_level=data["risk_level"],
        reason=data["reason"],
    )
