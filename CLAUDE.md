Vizhi
Vizhi (விழி) means "eye/pupil" in Tamil. It is a real-time security monitoring tool for AI agents. It watches what AI agents do — commands executed, files accessed, network calls made — parses that activity as it happens, flags risky behavior with severity levels, and generates actionable session reports.

Current Focus
Version 2 — Real Claude Code Integration (PostToolUse Hook)
Active Phase: 2.2 — Hook Installer
Goal: Build CLI commands that automatically install and uninstall the PostToolUse hook in ~/.claude/settings.json so users never have to manually edit config files.

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
│   └── installer.py        # hook install/uninstall logic (v2.2) ← CURRENT
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


Current Phase Deliverables (v2.2)

 installer.py with get_settings_path(), load_settings(), save_settings(), install_hook(), uninstall_hook()
 vizhi install-hook command — adds PostToolUse hook to ~/.claude/settings.json
 vizhi uninstall-hook command — removes hook cleanly
 Detects if hook already installed and warns instead of duplicating
 Handles missing settings.json gracefully (creates it if needed)
 Preserves all existing settings.json content when adding/removing hook
 Prints clear confirmation messages on success


Completed Phases

 v1.1 — stdout watcher and parser with action type classification
 v1.2 — risk classification engine with severity levels and updated live feed
 v1.3 — session report generator with terminal summary and JSON export
 v1.4 — CLI tool with vizhi start and vizhi report, pyproject.toml, README
 v2.1 — hook receiver with PostToolUse JSON parsing and session JSONL logging


Notes for Claude Code

We are on v2.2 only right now. Do not implement v2.3 unless explicitly asked.
When suggesting code, prefer simple and readable over clever.
Always use type hints.
If something is a placeholder for a future phase, mark it with a # TODO(vX.Y): comment.