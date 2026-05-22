"""Receive Claude Code PostToolUse hook payloads and append classified events.

Reads one JSON payload from stdin, maps the tool name to an ActionType, builds a
raw_text string suitable for the existing classifier, runs classify_event(), and
appends the result as one JSON line to vizhi_reports/session_<sessionId>.jsonl.

Designed to be invoked by Claude Code's hook system as `vizhi hook`. Failures
(empty stdin, malformed JSON, missing required fields) log to stderr and exit
cleanly so they never block the agent.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

from vizhi.classifier import ClassifiedEvent, classify_event
from vizhi.parser import ActionEvent, ActionType

DEFAULT_OUTPUT_DIR = "./vizhi_reports"

# Map Claude Code tool names → vizhi ActionType.
TOOL_TO_ACTION_TYPE: dict[str, ActionType] = {
    "Bash": "command",
    "Shell": "command",
    "Read": "file_access",
    "Write": "file_access",
    "Edit": "file_access",
    "MultiEdit": "file_access",
    "WebFetch": "network",
    "WebSearch": "network",
}

# Tool names whose input has a `file_path` field.
FILE_PATH_TOOLS: frozenset[str] = frozenset({"Read", "Write", "Edit", "MultiEdit"})

# TODO(v2.2): also support PreToolUse hooks so vizhi can block on critical risk.
# TODO(v2.3): forward classified events to the FastAPI dashboard over HTTP.
# TODO(v2.4): load output_dir + custom rules from a config file.


def receive(
    source: IO[str] | None = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> int:
    """Read one PostToolUse payload from `source`, classify, append to session log.

    Returns the process exit code. Always 0 on handled failures so the hook does
    not interrupt the agent.
    """
    source = source if source is not None else sys.stdin

    raw = source.read()
    if not raw.strip():
        _warn("empty stdin — no payload to process")
        return 0

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _warn(f"malformed JSON payload: {exc}")
        return 0

    if not isinstance(payload, dict):
        _warn("payload is not a JSON object")
        return 0

    tool_name = _get_field(payload, "toolName", "tool_name")
    tool_input = _get_field(payload, "toolInput", "tool_input") or {}
    session_id = _get_field(payload, "sessionId", "session_id")
    timestamp_raw = payload.get("timestamp")
    cwd = payload.get("cwd")

    if not tool_name:
        _warn("missing required field: toolName")
        return 0
    if not session_id:
        _warn("missing required field: sessionId")
        return 0
    if not isinstance(tool_input, dict):
        _warn(f"toolInput is not an object (got {type(tool_input).__name__}) — coercing")
        tool_input = {}

    action_type = TOOL_TO_ACTION_TYPE.get(str(tool_name), "unknown")
    raw_text = _build_raw_text(str(tool_name), tool_input)
    timestamp = _parse_timestamp(timestamp_raw)

    metadata: dict[str, str] = {
        "tool_name": str(tool_name),
        "source": "hook",
    }
    if cwd:
        metadata["cwd"] = str(cwd)

    event = ActionEvent(
        timestamp=timestamp,
        raw_text=raw_text,
        action_type=action_type,
        metadata=metadata,
    )
    classified = classify_event(event)
    path = _append_to_session_log(classified, str(session_id), output_dir)

    print(
        f"[vizhi hook] {classified.risk_level} {tool_name} → {path}",
        file=sys.stderr,
    )
    return 0


def _build_raw_text(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Build a raw_text string from toolInput for the classifier."""
    if tool_name in ("Bash", "Shell"):
        command = tool_input.get("command")
        if isinstance(command, str) and command:
            return command

    if tool_name in FILE_PATH_TOOLS:
        file_path = tool_input.get("file_path")
        if isinstance(file_path, str) and file_path:
            return f"{tool_name}({file_path})"

    if tool_name == "WebFetch":
        url = tool_input.get("url")
        if isinstance(url, str) and url:
            return f"WebFetch({url})"

    if tool_name == "WebSearch":
        query = tool_input.get("query")
        if isinstance(query, str) and query:
            return f"WebSearch({query})"

    # Fallback: short serialization for unknown / unmapped tools.
    serialized = json.dumps(tool_input, default=str, ensure_ascii=False)
    if len(serialized) > 500:
        serialized = serialized[:497] + "..."
    return f"{tool_name}({serialized})"


def _parse_timestamp(raw: object) -> datetime:
    """Parse an ISO-8601 timestamp from the payload, fall back to now() on failure."""
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _append_to_session_log(
    classified: ClassifiedEvent,
    session_id: str,
    output_dir: str,
) -> Path:
    """Append one classified event as a JSON line to session_<sessionId>.jsonl."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    safe_id = _sanitize_session_id(session_id)
    path = out / f"session_{safe_id}.jsonl"

    record: dict[str, Any] = {
        "timestamp": classified.event.timestamp.isoformat(),
        "raw_text": classified.event.raw_text,
        "action_type": classified.event.action_type,
        "metadata": classified.event.metadata,
        "risk_level": classified.risk_level,
        "reason": classified.reason,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def _sanitize_session_id(session_id: str) -> str:
    """Strip path separators / dangerous chars from a session id."""
    cleaned = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return cleaned or "unknown"


def _get_field(payload: dict[str, Any], *names: str) -> Any:
    """Return the first present value among `names` in `payload` (or None)."""
    for name in names:
        value = payload.get(name)
        if value is not None:
            return value
    return None


def _warn(msg: str) -> None:
    print(f"[vizhi hook warning] {msg}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(receive())
