Vizhi
Vizhi (விழி) means "eye/pupil" in Tamil. It is a real-time security monitoring tool for AI agents. It watches what AI agents do — commands executed, files accessed, network calls made — parses that activity as it happens, flags risky behavior with severity levels, and generates actionable session reports.

Current Focus
Version 2 — Real Claude Code Integration (PostToolUse Hook)
Active Phase: 2.3 — Live Session Viewer
Goal: Build a vizhi watch command that tails the current Claude Code session's JSONL log file in real time, displaying a live risk-tagged feed in the terminal as Claude Code runs in another window. On Ctrl+C it generates and saves the full session report.

Tech Stack
LayerTechnologyLanguagePython 3.11+CLIpip-installable package (Click)API (future)FastAPIFrontend (future)ReactDatabase (future)Supabase (PostgreSQL)Auth (future)Supabase Auth

Folder Structure
vizhi/
├── vizhi/
│   ├── __init__.py
│   ├── watcher.py          # stdin watcher (v1.1) — kept for generic use
│   ├── parser.py           # action event parser (v1.1)
│   ├── classifier.py       # risk classification engine (v1.2)
│   ├── reporter.py         # session report generator (v1.3)
│   ├── cli.py              # CLI entrypoint (v1.4)
│   ├── hook_receiver.py    # PostToolUse hook handler (v2.1)
│   ├── installer.py        # hook install/uninstall logic (v2.2)
│   └── session_viewer.py   # live JSONL tail viewer (v2.3) ← CURRENT
├── tests/
├── CLAUDE.md
├── README.md
├── requirements.txt
└── pyproject.toml

How the PostToolUse Hook Works
Claude Code calls the hook receiver automatically after every tool execution by running:
python -m vizhi.hook_receiver
It passes the tool event as JSON via stdin. The payload looks like:
json{
  "hookEvent": "PostToolUse",
  "toolName": "Bash",
  "toolInput": { "command": "rm -rf /tmp/test" },
  "toolResponse": { "stdout": "...", "stderr": "...", "exitCode": 0 },
  "sessionId": "abc-123",
  "cwd": "C:\\Users\\...",
  "timestamp": "2026-05-21T..."
}
The receiver reads this, classifies the event, and appends it as a line to vizhi_reports/session_<sessionId>.jsonl.

Coding Conventions

Python 3.11+
Use type hints on all functions
Keep each module focused on one responsibility
Functions should be small and testable
Use rich library for terminal output formatting
All user-facing messages clear and plain English
No unnecessary dependencies — keep it lean


Current Phase Deliverables (v2.3)

 session_viewer.py module with a tail_session() function that watches a JSONL file for new lines in real time
 Reads each new line, deserializes it into a ClassifiedEvent, and renders it using the existing render_event() from watcher.py
 vizhi watch CLI command in cli.py that:

Accepts optional --session-id flag (if omitted, auto-detects the most recent active session from vizhi_reports/)
Accepts optional --output-dir flag (default: ./vizhi_reports)
Tails the correct session_<sessionId>.jsonl file
On Ctrl+C: reads all events from the JSONL, generates and saves a full session report using existing generate_report(), print_report(), save_report()


 Handles file not found gracefully (clear error message if session file doesn't exist yet)
 Polling interval of 0.2 seconds between file reads (no external dependencies)


Completed Phases

 v1.1 — stdout watcher and parser with action type classification
 v1.2 — risk classification engine with severity levels and updated live feed
 v1.3 — session report generator with terminal summary and JSON export
 v1.4 — CLI tool with vizhi start and vizhi report, pyproject.toml, README
 v2.1 — hook receiver with PostToolUse JSON parsing and session JSONL logging
 v2.2 — hook installer with vizhi install-hook and vizhi uninstall-hook


Notes for Claude Code

We are on v2.3 only right now. Do not implement v3 features unless explicitly asked.
When suggesting code, prefer simple and readable over clever.
Always use type hints.
If something is a placeholder for a future phase, mark it with a # TODO(vX.Y): comment.
For test cases: explain each test clearly in plain English, give every command as a single line for PowerShell, do not combine multiple commands with semicolons.