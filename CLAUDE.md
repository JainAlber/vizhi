# Vizhi

Vizhi (விழி) means "eye/pupil" in Tamil. It is a real-time security monitoring tool for AI agents. It watches what AI agents do — commands executed, files accessed, network calls made — parses that activity as it happens, flags risky behavior with severity levels, and generates actionable session reports.

---

## Current Focus

**Version 1 — Proof of Concept (Claude Code Monitor)**
**Active Phase: 1.2 — Risk Classification Engine**

Goal: Build a rule-based classifier that takes a parsed ActionEvent and assigns it a risk severity level (critical/high/medium/low/info) with a plain-English reason. Update the live feed to display risk level with color coding.

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

## Current Phase Deliverables (v1.2)

- [ ] classifier.py with RiskLevel type and ClassifiedEvent dataclass
- [ ] Rule-based classify_event() function covering critical/high/medium/low/info
- [ ] watcher.py updated to show risk level and reason in live feed
- [ ] Color scheme updated to reflect risk level

---

## Notes for Claude Code

- We are building v1.1 only right now. Do not implement features from later phases unless explicitly asked.
- When suggesting code, prefer simple and readable over clever.
- Always use type hints.
- If something is a placeholder for a future phase, mark it with a `# TODO(vX.Y):` comment.