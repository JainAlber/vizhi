# Vizhi

Vizhi (விழி) means "eye/pupil" in Tamil. It is a real-time security monitoring tool for AI agents. It watches what AI agents do — commands executed, files accessed, network calls made — parses that activity as it happens, flags risky behavior with severity levels, and generates actionable session reports.

---

## Current Focus

**Version 1 — Proof of Concept (Claude Code Monitor)**
**Active Phase: 1.3 — Session Report Generator**

Goal: At the end of each Claude Code session, automatically generate a summary report showing total actions, risk breakdown, top flagged events, and a timeline. Output as terminal summary and JSON file.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python |
| CLI | pip-installable package |
| API (future) | FastAPI |
| Frontend (future) | React |
| Database (future) | Supabase (PostgreSQL) |
| Auth (future) | Supabase Auth |

---

## Folder Structure

```
vizhi/
├── vizhi/                  # Main Python package
│   ├── __init__.py
│   ├── watcher.py          # stdout watcher (Phase 1.1)
│   ├── parser.py           # action event parser (Phase 1.1)
│   ├── classifier.py       # risk classification engine (Phase 1.2)
│   ├── reporter.py         # session report generator (Phase 1.3)
│   └── cli.py              # CLI entrypoint (Phase 1.4)
├── tests/                  # Unit tests
├── CLAUDE.md               # This file
├── README.md
├── requirements.txt
└── pyproject.toml
```

---

## Coding Conventions

- Python 3.11+
- Use type hints on all functions
- Keep each module focused on one responsibility
- Functions should be small and testable
- Use `rich` library for terminal output formatting (colors, tables)
- All user-facing messages should be clear and plain English
- No unnecessary dependencies — keep it lean

---

## Current Phase Deliverables (v1.3)

- [ ] reporter.py that collects all ClassifiedEvents from a session
- [ ] Generates terminal summary using rich (total actions, risk breakdown table, top flagged events)
- [ ] Exports full session report as a JSON file
- [ ] watcher.py updated to collect events and trigger report on session end (Ctrl+C)

---

## Notes for Claude Code

- We are building v1.1 only right now. Do not implement features from later phases unless explicitly asked.
- When suggesting code, prefer simple and readable over clever.
- Always use type hints.
- If something is a placeholder for a future phase, mark it with a `# TODO(vX.Y):` comment.