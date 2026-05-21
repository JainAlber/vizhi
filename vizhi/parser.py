"""Parse raw terminal output lines into structured action events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

ActionType = Literal["command", "file_access", "network", "unknown"]


# TODO(v1.2): replace keyword matching with structured tool-call detection
# (e.g. parse Claude Code's actual tool-use JSON envelopes when available).
COMMAND_KEYWORDS: tuple[str, ...] = (
    "$ ",
    "> ",
    "running:",
    "executing:",
    "bash(",
    "shell(",
    "powershell(",
    "exec ",
)

FILE_ACCESS_KEYWORDS: tuple[str, ...] = (
    "read(",
    "write(",
    "edit(",
    "open(",
    "reading file",
    "writing file",
    "editing file",
    "creating file",
    "deleting file",
    "glob(",
    "grep(",
)

NETWORK_KEYWORDS: tuple[str, ...] = (
    "http://",
    "https://",
    "curl ",
    "wget ",
    "fetch(",
    "webfetch(",
    "websearch(",
    "request to",
    "downloading",
    "uploading",
)


@dataclass(frozen=True)
class ActionEvent:
    """A single structured event parsed from one line of agent output."""

    timestamp: datetime
    raw_text: str
    action_type: ActionType
    # TODO(v1.2): add risk severity + classifier metadata
    metadata: dict[str, str] = field(default_factory=dict)


def classify(line: str) -> ActionType:
    """Return the action_type for a raw line via keyword matching."""
    lowered = line.lower()

    if _contains_any(lowered, COMMAND_KEYWORDS):
        return "command"
    if _contains_any(lowered, FILE_ACCESS_KEYWORDS):
        return "file_access"
    if _contains_any(lowered, NETWORK_KEYWORDS):
        return "network"
    return "unknown"


def parse_line(line: str) -> ActionEvent:
    """Parse a single raw line into an ActionEvent."""
    return ActionEvent(
        timestamp=datetime.now(timezone.utc),
        raw_text=line.rstrip("\r\n"),
        action_type=classify(line),
    )


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle in haystack for needle in needles)
