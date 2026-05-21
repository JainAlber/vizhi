"""Rule-based risk classifier for ActionEvents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vizhi.parser import ActionEvent

RiskLevel = Literal["critical", "high", "medium", "low", "info"]


# TODO(v1.3): move rules into a YAML/JSON config so users can extend without editing code.
# TODO(v2.0): replace substring matching with proper tokenized command parsing
# (shlex + argv inspection) to cut false positives on quoted strings / comments.

CRITICAL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("sudo ",            "Privileged command (sudo) — full root access"),
    ("rm -rf",           "Recursive force delete — irreversible data loss"),
    ("rm -fr",           "Recursive force delete — irreversible data loss"),
    (" dd ",             "Raw disk write (dd) — can destroy filesystems"),
    ("dd if=",           "Raw disk write (dd) — can destroy filesystems"),
    ("chmod 777",        "World-writable permissions — severe security hole"),
    ("chmod -r 777",     "Recursive world-writable permissions"),
    ("/etc/passwd",      "Access to system password file"),
    ("/etc/shadow",      "Access to system shadow (hashed passwords) file"),
    ("~/.ssh",           "Access to SSH key directory"),
    ("/.ssh/",           "Access to SSH key directory"),
    ("mkfs",             "Filesystem format command — wipes target device"),
    (":(){:|:&};:",      "Classic fork-bomb signature"),
)

HIGH_PATTERNS: tuple[tuple[str, str], ...] = (
    ("rm -r",            "Recursive delete"),
    ("rm -f",            "Force delete"),
    (" rm ",             "Delete command"),
    ("del /f",           "Windows force delete"),
    ("rmdir /s",         "Windows recursive directory delete"),
    ("format ",          "Disk format command"),
    ("drop table",       "Destructive SQL — drops a table"),
    ("drop database",    "Destructive SQL — drops a database"),
    ("truncate table",   "Destructive SQL — empties a table"),
    (".env",             "Access to environment/secrets file"),
    ("id_rsa",           "Access to private SSH key"),
    ("id_ed25519",       "Access to private SSH key"),
    (".pem",             "Access to PEM private key / certificate"),
    (".key",             "Access to key file"),
    ("credentials",      "Access to a credentials path"),
    ("secrets/",         "Access to a secrets directory"),
    ("aws_secret",       "Possible AWS secret reference"),
    ("api_key",          "Possible API key reference"),
    ("password=",        "Password value in command/URL"),
    ("token=",           "Token value in command/URL"),
)

MEDIUM_FILE_WRITE_KEYWORDS: tuple[str, ...] = (
    "write(", "edit(", "writing file", "editing file",
    "creating file", "deleting file", " > ", " >> ",
)

MEDIUM_PROCESS_KEYWORDS: tuple[str, ...] = (
    "exec ", "spawn ", "bash(", "shell(", "powershell(",
    "running:", "executing:",
)

# Common dev/CI hosts treated as low-risk network calls.
KNOWN_SAFE_HOSTS: tuple[str, ...] = (
    "github.com", "raw.githubusercontent.com", "pypi.org",
    "files.pythonhosted.org", "registry.npmjs.org",
    "nodejs.org", "python.org", "docs.python.org",
    "localhost", "127.0.0.1", "::1",
)

LOW_FILE_READ_KEYWORDS: tuple[str, ...] = (
    "read(", "reading file", "glob(", "grep(", "open(",
)


@dataclass(frozen=True)
class ClassifiedEvent:
    """An ActionEvent paired with its assigned risk level and reason."""

    event: ActionEvent
    risk_level: RiskLevel
    reason: str


def classify_event(event: ActionEvent) -> ClassifiedEvent:
    """Assign a RiskLevel + plain-English reason to an ActionEvent."""
    text = event.raw_text.lower()

    hit = _first_match(text, CRITICAL_PATTERNS)
    if hit is not None:
        return ClassifiedEvent(event=event, risk_level="critical", reason=hit)

    hit = _first_match(text, HIGH_PATTERNS)
    if hit is not None:
        return ClassifiedEvent(event=event, risk_level="high", reason=hit)

    if event.action_type == "network":
        if _contains_any(text, KNOWN_SAFE_HOSTS):
            return ClassifiedEvent(
                event=event,
                risk_level="low",
                reason="Network call to a known-safe host",
            )
        return ClassifiedEvent(
            event=event,
            risk_level="medium",
            reason="Network call to an unknown domain",
        )

    if _contains_any(text, MEDIUM_FILE_WRITE_KEYWORDS):
        return ClassifiedEvent(
            event=event,
            risk_level="medium",
            reason="File write / modification",
        )

    if _contains_any(text, MEDIUM_PROCESS_KEYWORDS):
        return ClassifiedEvent(
            event=event,
            risk_level="medium",
            reason="New process execution",
        )

    if _contains_any(text, LOW_FILE_READ_KEYWORDS):
        return ClassifiedEvent(
            event=event,
            risk_level="low",
            reason="File read",
        )

    return ClassifiedEvent(
        event=event,
        risk_level="info",
        reason="No risk indicators matched",
    )


def _first_match(haystack: str, patterns: tuple[tuple[str, str], ...]) -> str | None:
    """Return the reason for the first matching pattern, or None."""
    for needle, reason in patterns:
        if needle in haystack:
            return reason
    return None


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle in haystack for needle in needles)
