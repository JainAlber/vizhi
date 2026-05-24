# Project Explained

This document is the single-source-of-truth overview of Vizhi: what it is, why it exists, how every piece fits together, what was built when, and what is intentionally not yet built.

It is meant to be read top-to-bottom. The simple and technical sections at the top establish the *what*; the data-flow, architecture, and version-history sections explain the *how*; the design-decisions and limitations sections explain the *why* and the *not-yet*.

---

## Simple Explanation

**Vizhi (விழி)** means *"eye"* or *"pupil"* in Tamil. It is a real-time security monitor for AI agents.

AI agents like Claude Code do real, irreversible work on your computer: they run shell commands, edit files, fetch URLs, and call APIs. Every one of those actions is a chance to make a destructive mistake or — worse — to be tricked by a prompt-injected webpage into doing something the user never asked for. Today, most users have no way to see what the agent is *actually* doing while it works, and even less ability to spot risky behaviour at the moment it happens.

Vizhi is that visibility layer. It watches every tool the agent uses, decides how risky each one is, prints a colour-coded live feed in your terminal, and writes a permanent session log so you can audit exactly what happened after the fact. Critical events (privileged commands, secret-file access, destructive deletes) are flagged in red the instant they occur, so a human can intervene before damage is done.

It is the *eye* on the agent.

---

## Technical Explanation

Vizhi is a Python 3.11+ command-line tool, distributed as the pip-installable `vizhi` package, with three operational modes:

1. **Stdin watcher mode (v1).** `vizhi start` reads any agent's terminal output from `stdin`, parses each line into an `ActionEvent`, classifies it via a deterministic rule engine into one of five risk levels (`critical | high | medium | low | info`), and renders a live colour-coded feed. On exit, it writes a JSON session report. This mode is adapter-agnostic — it works on any agent whose activity reaches a TTY.

2. **PostToolUse hook mode (v2.1+).** Vizhi installs itself as a `PostToolUse` hook in Claude Code's `~/.claude/settings.json`. After every tool call, Claude Code spawns `python -m vizhi.hook_receiver`, which receives a structured JSON payload describing the tool call, classifies it, and appends a JSON Lines record to `vizhi_reports/session_<sessionId>.jsonl`. This is far more reliable than scraping stdout — Vizhi sees the actual tool arguments, not a rendered string approximation.

3. **Live session viewer mode (v2.3).** `vizhi watch` tails the active session's JSONL file at 5 Hz, rendering each new line with the same colour scheme as the v1 watcher. On Ctrl+C it generates and saves a full session report from everything seen.

The risk classifier is **rule-based and inspectable** — there is no model file, no remote API call, no probabilistic verdict. Every "this is critical because X" reason can be traced to one of a few dozen pattern tuples in `classifier.py`. This is intentional: a security tool that uses opaque ML to decide what is dangerous is itself an attack surface.

The architecture is layered. Each layer does exactly one thing and depends only on layers below it:

```
parser → classifier → (watcher | hook_receiver | session_viewer) → reporter → cli
```

Every layer below `cli` is library-clean — no global state, no `sys.exit` calls, no `print` to stdout. This keeps the CLI thin and testable.

---

## Full Data Flow

This is the end-to-end journey of one tool call, from Claude Code firing the tool to Vizhi rendering it and saving it to a report. The hook-mode flow (v2) is the canonical path; the v1 stdin-mode flow is summarised at the bottom for reference.

### Hook-mode flow (v2)

**Step 1 — Claude Code finishes a tool call.**
The user has previously run `vizhi install-hook`, which wrote this entry into `~/.claude/settings.json`:

```json
{ "hooks": { "PostToolUse": [
  { "matcher": "*", "hooks": [
    { "type": "command", "command": "python -m vizhi.hook_receiver" }
  ]}
]}}
```

When any tool finishes, Claude Code spawns a subprocess running that command and pipes a JSON payload to its stdin.

*Files touched at this step:* `vizhi/installer.py` (wrote the entry earlier), `~/.claude/settings.json` (reads it now).

**Step 2 — `python -m vizhi.hook_receiver` runs.**
Python resolves the `__main__` block at the bottom of `vizhi/hook_receiver.py`, which calls `sys.exit(receive())`.

*Files touched:* `vizhi/hook_receiver.py`.

**Step 3 — `receive()` parses stdin.**
Reads the entire payload, calls `json.loads`, validates that it is a dict, and pulls out `toolName`, `toolInput`, `sessionId`, `timestamp`, and `cwd`. Missing required fields → `_warn()` to stderr and return `0` (never block the agent).

*Files touched:* `vizhi/hook_receiver.py`.

**Step 4 — The receiver builds an `ActionEvent`.**
- `tool_name` → `ActionType` via `TOOL_TO_ACTION_TYPE` (`"Bash"` → `"command"`, `"Read"` → `"file_access"`, `"WebFetch"` → `"network"`, etc.).
- `tool_input` → a `raw_text` string via `_build_raw_text()` (e.g. the literal Bash command, or `"Read(/etc/passwd)"`, or `"WebFetch(<url>)"`).
- `timestamp` → parsed via `_parse_timestamp()` (accepts `Z` and `+00:00`).
- `metadata` → `{"tool_name": ..., "source": "hook", "cwd": ...}`.

These four pieces are passed to the `ActionEvent` dataclass constructor defined in `vizhi/parser.py`.

*Files touched:* `vizhi/hook_receiver.py`, `vizhi/parser.py`.

**Step 5 — The classifier assigns a risk level.**
`classify_event(event)` runs the lowercased `raw_text` through `CRITICAL_PATTERNS`, `HIGH_PATTERNS`, the network-type branch, the medium write/exec keywords, and the low read keywords, in that order. The first match wins. If nothing matches, the verdict is `info`.

*Files touched:* `vizhi/classifier.py`.

**Step 6 — The receiver appends one JSON line to the session log.**
`_append_to_session_log(classified, session_id, output_dir)`:
- Sanitises `session_id` with `_sanitize_session_id()` (`[A-Za-z0-9_-]` only).
- Ensures `output_dir` exists.
- Opens `vizhi_reports/session_<sanitized_id>.jsonl` in append mode.
- Writes one JSON object per line. The schema:

```json
{
  "timestamp": "2026-05-22T12:00:00+00:00",
  "raw_text": "sudo rm -rf /tmp",
  "action_type": "command",
  "metadata": { "tool_name": "Bash", "source": "hook" },
  "risk_level": "critical",
  "reason": "Privileged command (sudo) — full root access"
}
```

*Files touched:* `vizhi/hook_receiver.py`, `vizhi_reports/session_<id>.jsonl`.

**Step 7 — The receiver prints a stderr summary and exits 0.**
`print(f"[vizhi hook] {risk_level} {tool_name} → {path}", file=sys.stderr)` — visible to the user running Claude Code if they look at the hook output. Then `return 0` so Claude Code's hook subsystem is happy.

*Files touched:* `vizhi/hook_receiver.py`.

**Step 8 (parallel, in another terminal) — `vizhi watch` is tailing the JSONL file.**
- `find_latest_session(output_dir)` resolved the session ID (or the user passed `--session-id` explicitly).
- `tail_session(session_id, output_dir, console)` opened `session_<id>.jsonl` and is polling it every 0.2 seconds.

*Files touched:* `vizhi/cli.py`, `vizhi/session_viewer.py`.

**Step 9 — The tailer picks up the new line.**
`_drain()` calls `f.readline()`, sees a complete line (`\n`-terminated), and calls `_event_from_line(raw)`. That helper:
- `json.loads(raw)` → dict.
- Rebuilds `ActionEvent` (using `datetime.fromisoformat` on the timestamp).
- Wraps it in a `ClassifiedEvent` carrying the already-decided `risk_level` and `reason`.

The event is appended to the in-memory `events` list and rendered.

*Files touched:* `vizhi/session_viewer.py`, `vizhi/parser.py`, `vizhi/classifier.py`.

**Step 10 — The event is rendered to the terminal.**
`render_event(console, classified)` (imported from `vizhi/watcher.py`) builds a Rich `Text` segment with timestamp, risk label, action type, raw text, and reason — colour-coded via `RISK_STYLES` and `RISK_LABELS`. The user sees something like:

```
[12:00:00] CRIT (command) sudo rm -rf /tmp  — Privileged command (sudo) — full root access
```

*Files touched:* `vizhi/watcher.py` (function), `vizhi/session_viewer.py` (caller).

**Step 11 — User presses Ctrl+C.**
`tail_session()` catches `KeyboardInterrupt` inside its polling loop and `return events`. Control returns to `vizhi/cli.py`'s `watch_cmd`.

*Files touched:* `vizhi/session_viewer.py`, `vizhi/cli.py`.

**Step 12 — The report is generated, printed, and saved.**
`watch_cmd`:
- Calls `generate_report(events, started_at, ended_at, session_id)` from `vizhi/reporter.py`. That builds a `SessionReport` dataclass with `risk_breakdown`, `flagged_events` (critical + high), and `all_events`.
- Calls `print_report(report, console)` → prints the rich Panel + risk-breakdown table + flagged-events table.
- Calls `save_report(report, output_dir)` → writes `session_<uuid>_<timestamp>.json` and returns the path.
- Prints `Report saved: <path>`.

*Files touched:* `vizhi/cli.py`, `vizhi/reporter.py`, `vizhi_reports/session_<uuid>_<ts>.json`.

### Stdin-mode flow (v1, summary)

For agents that do not support hooks (or for replaying captured logs), `vizhi start` runs `watcher.watch()`, which:

1. Reads stdin line by line via `stream_lines()`.
2. Calls `parser.parse_line(line)` → `ActionEvent`.
3. Calls `classifier.classify_event(event)` → `ClassifiedEvent`.
4. Calls `render_event(console, classified)` → live colour-coded row.
5. Appends to `events`.
6. On Ctrl+C / EOF → `_finalize_session()` → `generate_report` + `print_report` + `save_report`.

The same `parser`, `classifier`, `reporter`, and `render_event` are used by both modes — only the *source* of events differs.

---

## Architecture Diagram

```
                ┌─────────────────────────────────────────────────────────┐
                │                       Claude Code                       │
                │                    (other terminal)                     │
                │                                                         │
                │   1. Runs a tool (Bash, Read, WebFetch, ...)            │
                │   2. Fires PostToolUse hook with JSON payload via stdin │
                └─────────────────────────────┬───────────────────────────┘
                                              │
                                              │  stdin (JSON payload)
                                              ▼
              ┌────────────────────────────────────────────────────────┐
              │              python -m vizhi.hook_receiver             │
              │                                                        │
              │  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐  │
              │  │   parser.py  │ │ classifier.py│ │ hook_receiver  │  │
              │  │ ActionEvent  │◀┤classify_event│◀┤_build_raw_text │  │
              │  │ ActionType   │ │ RiskLevel    │ │_parse_timestamp│  │
              │  └──────────────┘ └──────────────┘ └────────┬───────┘  │
              │                                             │          │
              │                                             ▼          │
              │                              _append_to_session_log    │
              │                                             │          │
              └─────────────────────────────────────────────┼──────────┘
                                                            │ JSONL line
                                                            ▼
                              ┌────────────────────────────────────────┐
                              │  vizhi_reports/session_<sessionId>.jsonl  │
                              │  (append-only, one JSON object per line)  │
                              └────────────────────────────────┬───────┘
                                                               │
                                                               │  poll @ 5 Hz
                                                               ▼
              ┌─────────────────────────────────────────────────────────┐
              │                       vizhi watch                       │
              │                    (your terminal)                      │
              │                                                         │
              │  ┌────────────────────────┐  ┌───────────────────────┐  │
              │  │   session_viewer.py    │  │      watcher.py       │  │
              │  │  find_latest_session   │  │     render_event      │  │
              │  │  tail_session  ────────┼─▶│  (live colour feed)   │  │
              │  │  _drain                │  └───────────────────────┘  │
              │  │  _event_from_line      │                             │
              │  └────────────────────────┘                             │
              │                                                         │
              │            (Ctrl+C)                                     │
              │                                                         │
              │  ┌─────────────────────────────────────────────────┐    │
              │  │                  reporter.py                    │    │
              │  │  generate_report → SessionReport                │    │
              │  │  print_report (Rich Panel + Tables)             │    │
              │  │  save_report → session_<uuid>_<ts>.json         │    │
              │  └─────────────────────────────────────────────────┘    │
              └─────────────────────────────────────────────────────────┘

  ──────────────────────────────────────────────────────────────────────
  Out of band (one-time setup):

    vizhi install-hook
        │
        ▼
   ┌──────────────────────┐         ┌────────────────────────────┐
   │     installer.py     │  ────▶  │  ~/.claude/settings.json   │
   │  get_settings_path   │         │  (PostToolUse hook entry)  │
   │  load/save_settings  │         └────────────────────────────┘
   │  install_hook        │
   │  uninstall_hook      │
   └──────────────────────┘

  ──────────────────────────────────────────────────────────────────────
  Legacy v1 path (still supported):

    <agent stdout> | vizhi start
            │
            ▼
   ┌─────────────────────────────────────────────────────────┐
   │                       watcher.py                         │
   │  stream_lines → parse_line → classify_event              │
   │              → render_event (live)                       │
   │              → events.append                             │
   │  (EOF/Ctrl+C) → reporter.generate/print/save_report      │
   └─────────────────────────────────────────────────────────┘
```

---

## Version History

Every phase below is in the codebase today. Each entry describes what was built, *why* it was built, and what user-facing problem it solved.

### v1.1 — Stdin watcher and parser

**Built:** `vizhi/parser.py`, `vizhi/watcher.py` (`stream_lines`, the initial `watch()`), the keyword-based `classify()` function returning a four-value `ActionType` (`command | file_access | network | unknown`).

**Why:** Before anything else can be classified or reported, raw agent output needs to be turned into structured records. v1.1 established the canonical `ActionEvent` dataclass and the streaming-generator ingestion pattern that every later mode would re-use.

**Problem solved:** "How do I get from a stream of arbitrary terminal text to a typed, timestamped record I can reason about?"

### v1.2 — Risk classification engine

**Built:** `vizhi/classifier.py` — the `RiskLevel` literal, the five-tier pattern tuples (`CRITICAL_PATTERNS` through to network/file-write/exec/read keyword groups), the `ClassifiedEvent` frozen dataclass, and `classify_event()`. The watcher was rewired to render risk colours via `RISK_STYLES` and `RISK_LABELS`.

**Why:** A timestamped record by itself is not actionable; the user needs to know *which* records to look at. v1.2 introduced the five-level severity scale and the human-readable `reason` field so every flagged event is self-explanatory.

**Problem solved:** "Of the hundred things the agent just did, which two should I actually worry about?"

### v1.3 — Session report generator

**Built:** `vizhi/reporter.py` — the `SessionReport` dataclass, `generate_report()`, `print_report()` (with the rich `Panel` header, the risk-breakdown `Table`, and the flagged-events `Table`), `save_report()` for JSON persistence.

**Why:** A live feed disappears the moment your terminal scrolls. Users need a permanent summary they can review after the agent finishes — and the same data in a machine-readable form (JSON) for later analysis or sharing with a teammate.

**Problem solved:** "I wasn't watching the screen at 02:14 when the critical event happened — show me what I missed."

### v1.4 — CLI tool

**Built:** `vizhi/cli.py` with `vizhi start` and `vizhi report` subcommands; `vizhi/__init__.py` with `__version__`; `pyproject.toml` with the `vizhi` console-script entry point; `README.md`.

**Why:** Up to v1.3, Vizhi was importable Python only. v1.4 turned it into a real installable tool you could `pip install -e .` and invoke as `vizhi` from any directory.

**Problem solved:** "How do I actually run this thing without writing a Python wrapper script?"

### v2.1 — Hook receiver

**Built:** `vizhi/hook_receiver.py` — the `PostToolUse` JSON payload parser, the `TOOL_TO_ACTION_TYPE` mapping, `_build_raw_text()`, JSONL session-log writing, the never-crash-the-agent error contract.

**Why:** The stdin watcher works for any agent that produces visible output, but it has two limitations: it only sees what the agent *prints*, not what it actually *runs*; and it requires the user to remember to pipe their session through `vizhi start`. Claude Code's PostToolUse hook gives Vizhi the actual tool name + arguments as structured JSON, automatically, after every tool — both problems solved at once.

**Problem solved:** "How do I capture the exact arguments the agent passed to its tools, even when those arguments never appear on screen?"

### v2.2 — Hook installer

**Built:** `vizhi/installer.py` — `get_settings_path()`, `load_settings()`, `save_settings()`, `install_hook()`, `uninstall_hook()` with cascade pruning. `vizhi install-hook` and `vizhi uninstall-hook` CLI commands.

**Why:** v2.1 required users to hand-edit `~/.claude/settings.json` to wire up the hook. v2.2 made that one-step (`vizhi install-hook`) and reversible (`vizhi uninstall-hook`), preserving every other settings key in the process.

**Problem solved:** "How do I turn Vizhi on (and off) without manually editing JSON?"

### v2.3 — Live session viewer

**Built:** `vizhi/session_viewer.py` — `find_latest_session()`, `tail_session()`, the partial-line-safe poller, the 3-second file-existence wait. `vizhi watch` CLI command.

**Why:** Once Vizhi was running as a hook, its activity was invisible — the user had to wait until the end and run `vizhi report`. v2.3 closes the loop: now `vizhi watch` in a second terminal gives the same live feed you got with the v1 stdin watcher, but driven by the much-richer hook payload data.

**Problem solved:** "How do I see what the hook is catching in real time, without waiting for the session to end?"

---

## Key Design Decisions

This section explains the *whys* behind choices that may not be obvious from reading the code alone.

### Why the PostToolUse hook is the canonical path now

The v1 stdin watcher is adapter-agnostic and still in the codebase, but the hook path (v2) is strictly better when it is available:

- **Sees the real arguments.** When Claude Code's UI prints `Read(C:\Users\…\.env)`, the rendered string is what stdin sees. The hook sees `{"toolName": "Read", "toolInput": {"file_path": "C:\\Users\\…\\.env"}}` — the actual argument, before any rendering, truncation, or pretty-printing.
- **Always-on.** Once installed, the hook fires for every tool of every session. The user does not have to remember to pipe anything.
- **Structured, not heuristic.** Stdin parsing relies on keyword matching (`"running:"`, `"Read("`, `"http://"`). The hook gets a typed payload, so misclassifying a quoted Bash string as a real command is impossible.

The v1 path is kept because it is the only option for agents that don't expose a hook system.

### Why the JSONL format for session logs

The hook receiver writes append-only JSON Lines (`.jsonl`) — one complete JSON object per line, terminated with `\n` — rather than a single growing JSON array. This is a deliberate trade-off:

- **Append-safe.** Appending one record requires nothing more than `open("a")` + `write(line)`. There is no need to read the existing file, mutate the array, and rewrite — which would race the live tailer.
- **Tail-friendly.** The viewer can `readline()` indefinitely with no schema-aware parser; each line is self-contained JSON.
- **Crash-safe.** If the process is killed mid-write, the worst case is a single trailing partial line. The tailer detects partial lines (no `\n`) and leaves them for the next poll. A growing-array format could corrupt the entire file with one bad write.
- **Stream-friendly.** Tools like `jq -c .` and pandas' `read_json(lines=True)` consume JSONL natively.

The final session report (after Ctrl+C) is a single pretty-printed JSON file because it is a *snapshot* — the array shape is appropriate for read-only analysis.

### Why rule-based risk classification (not ML)

A classifier whose verdicts cannot be explained is a bad fit for a security tool:

- **Auditability.** Every "this is critical because X" can be traced to a specific tuple in `CRITICAL_PATTERNS` or `HIGH_PATTERNS`. The user can read `vizhi/classifier.py` end-to-end in five minutes.
- **No new attack surface.** A learned model is itself something an attacker could attempt to poison or evade. A static rule list is, at worst, incomplete — not exploitable.
- **No runtime cost.** Substring matching is `O(text × rules)` per event, well under a millisecond for any realistic command. There is no model load time and no inference cost.
- **User-extensible (v1.3 todo).** Rules are tuples of `(needle, reason)`. The planned upgrade is to read them from a YAML config so users can add domain-specific patterns without editing code.

The current substring approach has known false positives (e.g. `"rm -rf"` inside a quoted string flags as critical). The `# TODO(v2.0)` in `classifier.py` plans a `shlex`-based argv parser as the principled fix.

### Why polling instead of native file-system events

`session_viewer.py` polls the JSONL file every 200 ms instead of using `watchdog`, `inotify`, `FSEvents`, or `ReadDirectoryChangesW`. Three reasons:

1. Zero new runtime dependencies — Vizhi installs with just `rich` and `click`.
2. Identical behaviour on Windows, macOS, and Linux — native watchers have platform quirks.
3. 200 ms latency is below human perception of "live."

The `# TODO(v2.4)` in `session_viewer.py` plans an optional `watchdog`-backed fast path for users who want sub-100 ms latency.

### Why frozen dataclasses everywhere

`ActionEvent`, `ClassifiedEvent`, and `SessionReport` are all `@dataclass(frozen=True)`. This costs nothing at runtime and gives:

- Value semantics — two events with the same fields are equal.
- Hashability — events can be used as dict keys or set members for free.
- Safety — once produced, a record cannot be mutated by a downstream consumer.

Mutation is reserved for explicit collections (`events: list[ClassifiedEvent]`).

### Why every layer below `cli.py` is library-clean

No layer below the CLI calls `sys.exit`, prints to stdout, or touches `os.environ`. They take parameters, return values, raise exceptions. This means:

- Each module can be unit-tested in isolation by handing it a `StringIO` source and a `Console(file=devnull)`.
- The CLI is the only thing that knows about exit codes and global state.
- Future surfaces (FastAPI handlers, MCP servers, a `vizhi.api` Python interface) can re-use the same internals without rewriting them.

---

## Current Limitations

Things Vizhi does *not* do today, and the future versions that will address each:

- **No PreToolUse blocking.** Vizhi sees a critical event only after the tool has already run. A future PreToolUse hook (planned, see `hook_receiver.py`'s `# TODO(v2.2)`) would let Vizhi return a non-zero exit code to actively cancel a dangerous tool call before it executes.
- **Rules are hard-coded in Python.** Users who want custom patterns must edit `classifier.py`. v1.3's `# TODO` is to load rules from a YAML/JSON config so the rule set can be extended without code changes.
- **No web dashboard.** Reports live as local JSON files. Future work (v3.0) is a FastAPI + React + Supabase web app that lets teams see cross-session history.
- **Single user, single machine.** There is no auth, no multi-tenancy, no central log. The hook writes JSONL to a local directory only. Supabase Auth + PostgreSQL persistence is on the v3.0 roadmap.
- **Substring matching has false positives.** A literal `"rm -rf"` inside a quoted comment is flagged the same as the real command. `# TODO(v2.0)` in `classifier.py` plans a `shlex`-based argv parser.
- **Polling adds 100 ms p50 latency.** Acceptable for the live feed today; `# TODO(v2.4)` in `session_viewer.py` plans an optional native-watcher fast path.
- **No alerting.** Critical events are visible only to a user watching the terminal. Future work is configurable alerting (Slack, e-mail, webhooks) on critical events.
- **Single adapter.** Only Claude Code is wired up via the PostToolUse hook today. Other agents (other CLI tools, IDE plugins, MCP servers) are planned as additional adapters.
- **No automated tests yet.** The `tests/` directory exists but is empty; coverage will come once the surface area stabilises.
