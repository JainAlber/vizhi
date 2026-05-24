# Project Explained

This document is the single-source-of-truth overview of Vizhi: what it is, why it exists, how every piece fits together, what was built when, and what is intentionally not yet built.

It is meant to be read top-to-bottom. The simple and technical sections at the top establish the *what*; the seven scenario walkthroughs in the middle establish the *how* by tracing every function call and data transformation; the architecture, version-history, design-decisions, and limitations sections explain the *why* and the *not-yet*.

---

## Simple Explanation

**Vizhi** (விழி, Tamil for "eye" or "pupil") is a security camera for AI agents. When an AI assistant like Claude Code runs commands on your computer, opens files, or makes network calls, Vizhi watches all of it as it happens, decides which actions look dangerous, and writes down a report of the whole session at the end.

It works in two ways:

1. **Pipe mode** (`vizhi start`) — you pipe the agent's terminal output into Vizhi and it analyzes the text line-by-line.
2. **Hook mode** (`vizhi install-hook` then `vizhi watch`) — Vizhi installs itself into Claude Code's settings file so Claude Code automatically tells Vizhi about every tool it runs. Vizhi logs each tool call to a file, and `vizhi watch` shows you a live color-coded feed of what the agent is doing.

For each action, Vizhi prints one line: a timestamp, a color-coded severity tag (`CRIT`, `HIGH`, `MED`, `LOW`, `INFO`), what kind of action it was (`command`, `file_access`, `network`, `unknown`), the literal action, and a one-line reason explaining the verdict. When the session ends, you get a printed summary and a JSON file you can keep, share, or feed into another tool.

---

## Technical Explanation

Vizhi is a pip-installable Python 3.11+ CLI that ships as a single package (`vizhi/`) exposing one entry point (`vizhi`) backed by Click. It has nine modules:

- `__init__.py` — package marker, pins `__version__`.
- `parser.py` — turns a raw line of text into an `ActionEvent` dataclass with a coarse action-type tag.
- `classifier.py` — turns an `ActionEvent` into a `ClassifiedEvent` (event + risk level + reason) via a cascading rule engine.
- `watcher.py` — the v1 mode loop: read stdin, parse, classify, render, finalize.
- `reporter.py` — aggregates a list of classified events into a `SessionReport`; renders to terminal; persists to JSON.
- `cli.py` — Click command surface (`start`, `report`, `hook`, `watch`, `install-hook`, `uninstall-hook`).
- `hook_receiver.py` — receives one Claude Code PostToolUse payload on stdin and appends a classified record to `session_<sessionId>.jsonl`.
- `installer.py` — idempotently adds/removes Vizhi's entry from `~/.claude/settings.json`.
- `session_viewer.py` — live tails `session_<sessionId>.jsonl`, rendering each new event with the same color scheme as the v1 watcher.

The data model is built around three frozen dataclasses (`ActionEvent`, `ClassifiedEvent`, `SessionReport`). All persisted data is JSON or JSONL. There is no database, no daemon, no network listener, and no shared state — every CLI invocation runs end-to-end and exits. The only files Vizhi writes are inside `--output-dir` (default `./vizhi_reports`) and the user's `~/.claude/settings.json` (only when `install-hook` / `uninstall-hook` runs).

Dependencies are deliberately minimal: `rich` for terminal formatting, `click` for CLI parsing. Both are pinned in `pyproject.toml` (`rich>=13.7.0`, `click>=8.1.0`). Everything else (`json`, `uuid`, `pathlib`, `datetime`, `time`, `dataclasses`, `typing`) is in Python's standard library.

---

## Scenario Walkthroughs

Below, every supported user path traced step-by-step. For each scenario we list every function that runs in order, every file that is read or written, and the exact shape of each in-flight data structure at the moments it is created and consumed.

### Scenario 1 — `vizhi start` with a piped stream

User runs `cat agent.log | vizhi start` (or `claude --print "audit this repo" | vizhi start`).

**Step-by-step trace:**

1. The OS reads `pyproject.toml`'s `[project.scripts]` entry to find that `vizhi` resolves to `vizhi.cli:main`. The shell launches `python -m vizhi.cli` (or the installed wrapper script), which imports `vizhi.cli`.
2. Click sees `start` as the subcommand and dispatches to `start_cmd(output_dir="./vizhi_reports")`.
3. `start_cmd` calls `watch(output_dir=output_dir)` from `watcher.py`.
4. `watch()` constructs `source = sys.stdin`, `console = Console()`, generates a session UUID with `uuid.uuid4()`, captures `started_at = datetime.now(timezone.utc)`, and starts the live banner: `Vizhi watcher started. Session <uuid>. Waiting for input on stdin... (Ctrl+C to end session)`.
5. The `try:` block enters `for line in stream_lines(sys.stdin)`. `stream_lines` is a generator that repeatedly calls `sys.stdin.readline()`, yielding non-blank lines until the stream closes.
6. For the first non-blank line — say `"$ sudo rm -rf /tmp/cache"` — the loop runs three transformations:
   - `event = parse_line(line)` returns `ActionEvent(timestamp=2026-05-21T12:07:00.123Z, raw_text="$ sudo rm -rf /tmp/cache", action_type="command", metadata={})`. The classification was done by `classify(line)` inside `parse_line`, which lowercased the line and matched `"$ "` in `COMMAND_KEYWORDS`.
   - `classified = classify_event(event)` runs the cascade. `"$ sudo rm -rf /tmp/cache".lower()` contains `"sudo "` (the first entry of `CRITICAL_PATTERNS`). Returns `ClassifiedEvent(event=<above>, risk_level="critical", reason="Privileged command (sudo) — full root access")`.
   - `events.append(classified)` adds it to the in-memory list.
   - `render_event(console, classified)` prints one line: `[12:07:00] CRIT (command) $ sudo rm -rf /tmp/cache  — Privileged command (sudo) — full root access`, colored bold red.
7. Steps 5–6 repeat for every line. The `events` list grows.
8. When the producer closes its end of the pipe, `sys.stdin.readline()` returns `""`. `iter(callable, sentinel)` stops, the generator ends, the for-loop exits cleanly.
9. (Alternative exit) If the user presses Ctrl+C, `KeyboardInterrupt` is caught by the `except` clause, which prints `Vizhi watcher stopped. Generating session report...`. Control falls through to the `finally`.
10. The `finally:` block runs `_finalize_session(console=..., events=events, session_id=session_id, started_at=started_at, output_dir=output_dir)`.
11. `_finalize_session` calls `generate_report(events, started_at=started_at, ended_at=datetime.now(timezone.utc), session_id=session_id)`. The result is a fresh `SessionReport`:
    ```
    SessionReport(
      session_id=UUID('abc...'),
      started_at=<T0>,
      ended_at=<T1>,
      total_actions=42,
      risk_breakdown={"critical":3,"high":5,"medium":8,"low":7,"info":19},
      flagged_events=[<3+5 critical/high ClassifiedEvents>],
      all_events=[<all 42 ClassifiedEvents>],
    )
    ```
12. `print_report(report, console)` renders three blocks:
    - A Rich `Panel` titled "Vizhi Session Report" with session id, start/end timestamps, duration (`_fmt_duration(seconds)`), and total actions.
    - A Rich `Table` titled "Risk Breakdown" with one row per `RISK_ORDER` entry (critical → info).
    - If `report.flagged_events` is non-empty: a Rich `Table` titled "Top Flagged Events (critical / high)" with one row per flagged event. Otherwise prints `No critical or high-risk events this session.` in green.
13. `save_report(report, output_dir=output_dir)` runs:
    - `Path("./vizhi_reports").mkdir(parents=True, exist_ok=True)`.
    - `filename = f"session_{report.session_id}_{report.started_at.strftime('%Y%m%dT%H%M%SZ')}.json"`, e.g. `session_abc..._20260521T120700Z.json`.
    - `payload = _report_to_dict(report)` — a hand-crafted dict with keys `session_id`, `started_at`, `ended_at`, `duration_seconds`, `total_actions`, `risk_breakdown`, `flagged_events`, `all_events`. Inner events go through `_classified_to_dict`.
    - `file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")`.
    - Returns the string path.
14. `_finalize_session` prints `Report saved: ./vizhi_reports/session_..._20260521T120700Z.json`. The function returns. `watch()` returns. `start_cmd` returns. Click exits with code 0.

**Files written this scenario:**

- One file: `./vizhi_reports/session_<uuid>_<YYYYMMDDTHHMMSSZ>.json` (created at session end).

**Data structures created and consumed:**

| When | Structure | Created by | Consumed by |
|------|-----------|------------|-------------|
| Per line | `ActionEvent` | `parse_line()` | `classify_event()` |
| Per line | `ClassifiedEvent` | `classify_event()` | `render_event()`, `events.append`, later `generate_report()` |
| Session-end | `SessionReport` | `generate_report()` | `print_report()`, `save_report()` |
| Session-end | serialized dict | `_report_to_dict()` | `json.dumps` → file |

---

### Scenario 2 — Claude Code fires the PostToolUse hook

Assumes the user has previously run `vizhi install-hook`. The user is running Claude Code in some terminal; Claude decides to run `Bash({"command":"git status"})` as part of its work.

**Step-by-step trace:**

1. Claude Code executes the tool internally and obtains its `toolResponse`.
2. Claude Code reads `~/.claude/settings.json`, sees `settings["hooks"]["PostToolUse"]` contains a matcher entry `{"matcher": "*", "hooks": [{"type":"command","command":"python -m vizhi.hook_receiver"}]}`, and decides to fire it for this tool call (the `"*"` matcher matches everything).
3. Claude Code spawns a child process: `python -m vizhi.hook_receiver`. It passes the hook payload to that child via stdin:
    ```json
    {
      "hookEvent": "PostToolUse",
      "toolName": "Bash",
      "toolInput": {"command": "git status"},
      "toolResponse": {"stdout": "...", "stderr": "", "exitCode": 0},
      "sessionId": "abc-123",
      "cwd": "C:\\Users\\jainp\\OneDrive\\Desktop\\Projects\\vizhi",
      "timestamp": "2026-05-24T15:07:00.123Z"
    }
    ```
4. Python's `runpy` mechanism loads `vizhi/hook_receiver.py`. The `if __name__ == "__main__":` block at the file's bottom runs `sys.exit(receive())`.
5. `receive()` enters:
    - `source = sys.stdin`; `raw = source.read()` consumes the entire payload (Claude Code closes its end after writing).
    - `raw.strip()` is non-empty → no early exit.
    - `payload = json.loads(raw)` succeeds → the dict above.
    - `isinstance(payload, dict)` is True → no early exit.
    - `tool_name = _get_field(payload, "toolName", "tool_name")` → `"Bash"`.
    - `tool_input = _get_field(payload, "toolInput", "tool_input") or {}` → `{"command": "git status"}`.
    - `session_id = _get_field(payload, "sessionId", "session_id")` → `"abc-123"`.
    - `timestamp_raw = payload.get("timestamp")` → `"2026-05-24T15:07:00.123Z"`.
    - `cwd = payload.get("cwd")` → the project path.
6. Field validation: `tool_name` and `session_id` are both non-empty. `tool_input` is a dict. No warnings, no early exits.
7. `action_type = TOOL_TO_ACTION_TYPE.get("Bash", "unknown")` → `"command"`.
8. `raw_text = _build_raw_text("Bash", {"command": "git status"})`. Inside `_build_raw_text`:
    - `tool_name in ("Bash", "Shell")` → True.
    - `command = tool_input.get("command")` → `"git status"`, a non-empty string.
    - Returns `"git status"`.
9. `timestamp = _parse_timestamp("2026-05-24T15:07:00.123Z")`. Replaces `Z` with `+00:00` → `"2026-05-24T15:07:00.123+00:00"`. `datetime.fromisoformat` parses it into a timezone-aware `datetime`.
10. `metadata = {"tool_name": "Bash", "source": "hook", "cwd": "C:\\Users\\jainp\\OneDrive\\Desktop\\Projects\\vizhi"}`.
11. `event = ActionEvent(timestamp=..., raw_text="git status", action_type="command", metadata=metadata)`. The dataclass is frozen; constructed in one go.
12. `classified = classify_event(event)`. The cascade:
    - Lowercased text: `"git status"`.
    - `_first_match(text, CRITICAL_PATTERNS)` returns `None` (no critical needle present).
    - `_first_match(text, HIGH_PATTERNS)` returns `None`.
    - `action_type != "network"` → skip network branch.
    - `_contains_any(text, MEDIUM_FILE_WRITE_KEYWORDS)` → `False`.
    - `_contains_any(text, MEDIUM_PROCESS_KEYWORDS)` → `False` (none of `"exec "`, `"bash("`, `"running:"`, etc. appear in `"git status"`).
    - `_contains_any(text, LOW_FILE_READ_KEYWORDS)` → `False`.
    - Falls through to `info`. Result: `ClassifiedEvent(event=<above>, risk_level="info", reason="No risk indicators matched")`.
13. `path = _append_to_session_log(classified, "abc-123", "./vizhi_reports")`. Inside:
    - `out = Path("./vizhi_reports")`; `out.mkdir(parents=True, exist_ok=True)`.
    - `safe_id = _sanitize_session_id("abc-123")` → `"abc-123"` (already safe).
    - `path = out / "session_abc-123.jsonl"`.
    - `record = {"timestamp": "2026-05-24T15:07:00.123000+00:00", "raw_text": "git status", "action_type": "command", "metadata": {"tool_name":"Bash","source":"hook","cwd":"C:\\Users\\jainp\\OneDrive\\Desktop\\Projects\\vizhi"}, "risk_level": "info", "reason": "No risk indicators matched"}`.
    - `with path.open("a", encoding="utf-8") as f: f.write(json.dumps(record, ensure_ascii=False) + "\n")`. One line appended.
    - Returns the path.
14. `print(f"[vizhi hook] info Bash → vizhi_reports/session_abc-123.jsonl", file=sys.stderr)`.
15. `receive()` returns `0`. `sys.exit(0)` ends the hook child process.
16. Claude Code observes exit code `0` and continues normally. The user's agent flow is uninterrupted.

**Files touched this scenario:**

- Read: `~/.claude/settings.json` (by Claude Code, not by Vizhi).
- Written: `./vizhi_reports/session_abc-123.jsonl` — one line appended.

If subsequent tool calls fire, each one repeats steps 3–16 with a new process. Steps 13 always appends to the same file because `session_id` is stable for the duration of one Claude Code conversation.

---

### Scenario 3 — `vizhi watch` monitors live

User runs `vizhi watch` in a second terminal while Claude Code is running in the first.

**Step-by-step trace:**

1. Click dispatches to `watch_cmd(session_id=None, output_dir="./vizhi_reports")`.
2. `console = Console()`.
3. `session_id is None` → `find_latest_session("./vizhi_reports")` is called.
4. Inside `find_latest_session`:
    - `out = Path("./vizhi_reports")`; exists → continue.
    - `Path.glob("session_*.jsonl")` → list of all session log files. Suppose there's one: `session_abc-123.jsonl`.
    - Sort by `st_mtime` descending; first is `session_abc-123.jsonl`.
    - Strip prefix and suffix → returns `"abc-123"`.
5. Back in `watch_cmd`: prints `Vizhi watch started. Tailing session abc-123 in ./vizhi_reports. Ctrl+C to end.`.
6. `started_at = datetime.now(timezone.utc)`.
7. `events: list[ClassifiedEvent] = []`.
8. `events = tail_session("abc-123", "./vizhi_reports", console)` is called inside a try/except for `FileNotFoundError` and `KeyboardInterrupt`.
9. Inside `tail_session`:
    - `path = Path("./vizhi_reports") / "session_abc-123.jsonl"`.
    - `_wait_for_file(path, 3.0)`. The file exists → returns immediately.
    - `with path.open("r", encoding="utf-8") as f:` opens it.
    - `_drain(f, events, console)` runs once to consume everything currently in the file.
10. Inside `_drain` (first call):
    - Loop iteration 1: `pos = f.tell()` (0). `line = f.readline()` → the first record. Ends in `\n` → consume.
    - `_event_from_line(stripped)` parses the JSON, builds the `ClassifiedEvent`. (Suppose the line is the `"git status"` record from Scenario 2.)
    - `events.append(classified)`; `render_event(console, classified)` prints `[15:07:00] INFO (command) git status  — No risk indicators matched`.
    - `consumed = 1`.
    - Loop iteration 2: `line = f.readline()` → `""` (EOF). Return `consumed = 1`.
11. Back in `tail_session`: enters the polling loop.
    - `_drain(...)` again, returns 0 → `time.sleep(0.2)`.
    - 200ms later, another drain. Still 0 → sleep.
    - This continues. The user sees only the banner and the one existing line.
12. The user, in the other terminal, asks Claude to do something. Claude runs `Read({"file_path":"/etc/passwd"})`. The PostToolUse hook fires (Scenario 2), appends one line to `session_abc-123.jsonl`. The write is `{"timestamp":"...","raw_text":"Read(/etc/passwd)","action_type":"file_access","metadata":{...},"risk_level":"critical","reason":"Access to system password file"}\n`.
13. Within at most 200ms, the polling loop in `tail_session` calls `_drain` again. This time:
    - `pos = f.tell()` (offset just past the first line).
    - `line = f.readline()` → the new full line, ending in `\n`.
    - `_event_from_line` parses it → `ClassifiedEvent(event=..., risk_level="critical", reason="Access to system password file")`.
    - `render_event` prints `[15:08:12] CRIT (file_access) Read(/etc/passwd)  — Access to system password file` in bold red.
    - `events.append(classified)`. `consumed = 1`.
    - Loop iteration 2: EOF, return 1.
14. The drain returned >0, so `tail_session` immediately calls drain again (no sleep this poll), in case more lines are pending. They aren't → returns 0 → sleep.
15. This continues for as long as the user lets it. Each new hook firing produces one new line within 200ms.
16. User presses Ctrl+C in the `vizhi watch` terminal. `KeyboardInterrupt` propagates up through `time.sleep` into the `while True` loop. The `except KeyboardInterrupt: return events` clause catches it and returns the accumulated list.
17. Back in `watch_cmd`: prints `Watch stopped. Generating session report...`.
18. `report = generate_report(events, started_at=started_at, ended_at=datetime.now(timezone.utc), session_id=_parse_session_uuid("abc-123"))`. Since `"abc-123"` is not a UUID, `_parse_session_uuid` falls back to `uuid.uuid4()` — the report gets a fresh UUID (not equal to `"abc-123"`).
19. `print_report(report, console)` renders the summary.
20. `path = save_report(report, output_dir="./vizhi_reports")` writes the JSON report.
21. Prints `Report saved: ./vizhi_reports/session_<fresh-uuid>_<ts>.json`. Click exits.

**Files written this scenario:**

- Hook (separate process, one per tool call): appends to `./vizhi_reports/session_abc-123.jsonl`.
- Watch (on Ctrl+C): writes `./vizhi_reports/session_<fresh-uuid>_<ts>.json` (the final report).

**Latency:** worst case 200ms from line written to line rendered. Average 100ms.

---

### Scenario 4 — `vizhi report` views the last session

User has previously generated at least one report (via `vizhi start` or `vizhi watch` ending in Ctrl+C). Now they run `vizhi report`.

**Step-by-step trace:**

1. Click dispatches to `report_cmd(output_dir="./vizhi_reports")`.
2. `console = Console()`.
3. `path = _latest_report_path("./vizhi_reports")` is called.
4. Inside `_latest_report_path`:
    - `out = Path("./vizhi_reports")`; exists.
    - `out.glob("session_*.json")` returns a list of report files. Suppose there are three.
    - `sorted(..., key=lambda p: p.stat().st_mtime, reverse=True)` orders them newest-first.
    - Returns the first → `Path("./vizhi_reports/session_<latest-uuid>_<ts>.json")`.
5. (If `path is None`) prints a yellow `No reports found in ./vizhi_reports. Run vizhi start first.` and `SystemExit(1)`.
6. Otherwise prints `Loading report: <path>` in dim style.
7. `report = _load_report(path)`. Inside:
    - `data = json.loads(path.read_text(encoding="utf-8"))` → a dict.
    - `all_events = [_event_from_dict(d) for d in data.get("all_events", [])]`. Each call to `_event_from_dict`:
      - `action = ActionEvent(timestamp=datetime.fromisoformat(d["timestamp"]), raw_text=d["raw_text"], action_type=d["action_type"], metadata=dict(d.get("metadata", {})))`.
      - Returns `ClassifiedEvent(event=action, risk_level=d["risk_level"], reason=d["reason"])`.
    - `flagged_events = [_event_from_dict(d) for d in data.get("flagged_events", [])]`.
    - Returns `SessionReport(session_id=uuid.UUID(data["session_id"]), started_at=datetime.fromisoformat(data["started_at"]), ended_at=datetime.fromisoformat(data["ended_at"]), total_actions=int(data["total_actions"]), risk_breakdown=dict(data["risk_breakdown"]), flagged_events=flagged_events, all_events=all_events)`.
8. `print_report(report, console)` renders the same panel + tables described in Scenario 1.
9. Click exits with 0. Nothing is written.

**Files touched this scenario:**

- Read: the chosen `session_*.json`.
- Written: none.

---

### Scenario 5 — `vizhi install-hook` (first time)

User runs `vizhi install-hook` on a machine where `~/.claude/settings.json` does not yet exist (or exists with no hooks).

**Step-by-step trace:**

1. Click dispatches to `install_hook_cmd()`.
2. `console = Console()`.
3. `path = get_settings_path()` → `Path("C:\\Users\\jainp\\.claude\\settings.json")` (on Windows; other OSes get the equivalent `~/.claude/settings.json`).
4. `settings = load_settings(path)`. Two cases:
    - File does not exist → `load_settings` returns `{}`.
    - File exists with `{"theme": "dark"}` → returns `{"theme": "dark"}`.
5. (If `load_settings` raises `json.JSONDecodeError` or `ValueError`, the CLI prints a red message naming the file and exits with code 1.)
6. `updated, already_installed = install_hook(settings)`. Inside `install_hook`:
    - `hooks_root = settings.setdefault("hooks", {})` → `settings` now has `"hooks": {}`.
    - `post_tool_use = hooks_root.setdefault("PostToolUse", [])` → now `settings["hooks"]["PostToolUse"] == []`.
    - `_vizhi_hook_present([])` → `False`.
    - `post_tool_use.append(_vizhi_matcher_entry())`. The list now contains one entry: `{"matcher": "*", "hooks": [{"type": "command", "command": "python -m vizhi.hook_receiver"}]}`.
    - Returns `(settings, False)`. `settings` now has full structure: `{"theme":"dark","hooks":{"PostToolUse":[<vizhi entry>]}}` (or `{"hooks":{...}}` if the file was originally empty).
7. `already_installed is False` → proceed.
8. `save_settings(path, updated)`. Inside:
    - `path.parent.mkdir(parents=True, exist_ok=True)` — creates `~/.claude/` if missing.
    - `text = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"`.
    - `path.write_text(text, encoding="utf-8")` — writes the file.
9. Prints `Installed Vizhi PostToolUse hook in <path>. Claude Code will now call python -m vizhi.hook_receiver after every tool execution.` in green.

**Files written this scenario:**

- `~/.claude/settings.json` — created or updated with the Vizhi entry added. All other user settings preserved.

**Resulting file shape (if originally empty):**

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {"type": "command", "command": "python -m vizhi.hook_receiver"}
        ]
      }
    ]
  }
}
```

---

### Scenario 6 — `vizhi install-hook` (already installed)

User runs `vizhi install-hook` a second time.

**Step-by-step trace:**

1. Steps 1–5 of Scenario 5 are identical. `load_settings` returns the same dict that includes the Vizhi entry.
2. `updated, already_installed = install_hook(settings)`. Inside:
    - `hooks_root = settings.setdefault("hooks", {})` → returns the existing `hooks` dict (no mutation).
    - `post_tool_use = hooks_root.setdefault("PostToolUse", [])` → returns the existing list.
    - `_vizhi_hook_present(post_tool_use)` walks every matcher entry's inner `hooks` list. Finds one with `command == "python -m vizhi.hook_receiver"` → returns `True`.
    - Returns `(settings, True)`. No mutation.
3. Back in `install_hook_cmd`: `already_installed is True` → prints `Vizhi hook already installed in <path>. No changes made.` in yellow. Returns without calling `save_settings`.

**Files written this scenario:**

- None. The file is not touched.

**Why this matters:** running the install command twice is safe. The user can put `vizhi install-hook` in a setup script and it won't break.

---

### Scenario 7 — `vizhi uninstall-hook`

User runs `vizhi uninstall-hook`. Assumes a previous `install-hook` ran and the settings file contains the Vizhi entry alongside an unrelated user-added hook for some other tool.

**Step-by-step trace:**

1. Click dispatches to `uninstall_hook_cmd()`.
2. `console = Console()`.
3. `path = get_settings_path()`.
4. If the file doesn't exist → prints `No settings file at <path> — nothing to remove.` in yellow and returns.
5. Else `settings = load_settings(path)`. Suppose the file currently contains:
    ```json
    {
      "theme": "dark",
      "hooks": {
        "PostToolUse": [
          {
            "matcher": "*",
            "hooks": [
              {"type": "command", "command": "python -m vizhi.hook_receiver"},
              {"type": "command", "command": "echo done"}
            ]
          },
          {
            "matcher": "Bash",
            "hooks": [
              {"type": "command", "command": "log_bash_tool.sh"}
            ]
          }
        ]
      }
    }
    ```
6. `updated, was_removed = uninstall_hook(settings)`. Inside:
    - `hooks_root = settings.get("hooks")` → the dict above.
    - `post_tool_use = hooks_root.get("PostToolUse")` → the two-element list.
    - For each matcher entry:
      - First entry: `inner = [vizhi_hook, echo_hook]`. `kept_inner = [echo_hook]` (Vizhi filtered out). `removed = True`. `kept_inner` is non-empty → write it back and keep the matcher entry.
      - Second entry: `inner = [log_bash_hook]`. `kept_inner == inner`. No removal.
    - `pruned_matchers` is non-empty → write it back to `hooks_root["PostToolUse"]`.
    - `hooks_root` is non-empty → don't pop `"hooks"`.
    - Returns `(settings, True)`.
7. Back in `uninstall_hook_cmd`: `was_removed is True` → `save_settings(path, updated)` and print `Removed Vizhi PostToolUse hook from <path>.` in green.

**Resulting file:**

```json
{
  "theme": "dark",
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {"type": "command", "command": "echo done"}
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {"type": "command", "command": "log_bash_tool.sh"}
        ]
      }
    ]
  }
}
```

**Cascade-pruning corner case:** if the Vizhi matcher entry's inner list had contained only the Vizhi hook (no `echo done`), the cascade would have dropped the matcher entry, then noticed `pruned_matchers` is `[<bash log entry>]` (still non-empty) and written that back. If `pruned_matchers` had become empty, the cascade would have popped `"PostToolUse"` from `hooks_root`. If `hooks_root` then became empty, the cascade would have popped `"hooks"` from `settings`. The end-state contract: after uninstall, the file looks like it did before install, modulo whitespace normalization.

---

## Why JSONL was chosen over plain JSON for the live session log

JSONL (JSON Lines, one JSON object per line) is the right format for an append-only, possibly-still-being-written log. A plain JSON array (`[{...},{...}]`) is the wrong format. Concretely:

**Append cost.** With JSONL, appending one event is O(1): open in `"a"` mode, write `json.dumps(record) + "\n"`, close. With a JSON array, every append requires reading the entire existing file, parsing it, mutating the in-memory list, and rewriting the whole thing. Over a session with N tool calls, JSONL is O(N); JSON array is O(N²).

**Mid-write safety.** With JSONL, if the writer crashes between writing the `\n` of one line and starting the next, every previously written line is still valid and readable. With a JSON array, a crash mid-file leaves the array unterminated — `json.loads` will reject the whole file. The reader of a partial JSON array has no way to recover individual records.

**Live tailing.** With JSONL, a reader can `readline()` to get one complete record at a time. The `_drain` function in `session_viewer.py` uses exactly this pattern, plus a partial-line guard (`f.tell()` / `f.seek()`) to handle the case where a poll happens mid-write. With a JSON array, there is no way to read "the most recent record" incrementally — you have to wait for the writer to close the array, or parse the file as a stream with a non-stock library.

**Concurrency.** With JSONL, two writers can each append a line with reasonable atomicity (a single `write()` of bytes under PIPE_BUF is atomic on POSIX). With a JSON array, concurrent writes require either external locking or a single-writer architecture.

**What would break if we used JSON?**

- The `vizhi watch` command would either need to wait for session end (defeating the purpose) or implement its own JSON-array-streaming parser (an extra hundred lines of code and a new dependency).
- The hook receiver would spend O(N) time per hook firing, slowing down Claude Code linearly with session length.
- A crash mid-write would lose every event in the session, not just the last one.
- Two concurrent hook firings (e.g. parallel tool calls) could corrupt the file.

The price of JSONL is one minor inconvenience: the file is not a valid JSON document, so you cannot `json.loads(file_text)` it as one structure. You must parse line by line. This is a fair trade.

The final `session_*.json` report is plain JSON — appropriate there because it is written once at session end as a whole document.

---

## Why polling was chosen over native file watchers

The live tailer (`session_viewer.tail_session`) checks the JSONL file every 200ms using `time.sleep(0.2)`. An alternative would be a native file watcher: `watchdog` (cross-platform Python wrapper), or platform-native APIs (`inotify` on Linux, `FSEvents` on macOS, `ReadDirectoryChangesW` on Windows).

**Why polling wins for Vizhi:**

- **Zero new dependencies.** `time.sleep` is in Python's standard library. `watchdog` is a 100KB+ dependency tree with platform-specific compiled wheels.
- **Identical behavior on Windows, macOS, Linux.** Polling has no OS-specific edge cases. Native watchers each have their own quirks (inotify event coalescing, FSEvents directory-level granularity, Windows lock semantics).
- **Predictable latency.** 200ms is below the human perceptual threshold for "feels instant." Native watchers can be faster (~10ms) but the difference is invisible to a human reading a live feed.
- **Negligible cost.** Five poll cycles per second is 5 syscalls — orders of magnitude less than what the OS does for the network stack every second.
- **Simpler partial-line handling.** Polling reads "whatever is there right now" with a partial-line guard. A native watcher fires on every write, including partial ones, and a naive consumer would parse half-records.

**Tradeoffs we accepted:**

- The first new line shows up in 100ms on average, up to 200ms worst case. A Slack alert this latency would be unacceptable; for a live terminal feed it is fine.
- Constant 5Hz polling, even with no new events. Cost is negligible but not literally zero.

**Why we didn't pick `watchdog`:**

- Adds a dependency.
- Adds platform-specific compiled code that can break on niche architectures.
- Replaces 6 lines of polling code with ~30 lines of event-handler boilerplate.
- Buys nothing the user can perceive.

The `# TODO(v2.4): swap polling for a native file watcher (watchdog) for lower latency.` comment in `session_viewer.py` exists to mark this as a future option, not a current need.

---

## Why frozen dataclasses were chosen

All three of Vizhi's main data types — `ActionEvent`, `ClassifiedEvent`, `SessionReport` — are declared with `@dataclass(frozen=True)`. The freeze does three things:

**Prevents accidental mutation.** Once an event is observed and classified, the rest of the pipeline reads it but should never change it. Without `frozen=True`, a bug like `classified.risk_level = "info"` would silently corrupt the report — the live feed would show one thing and the saved JSON another. With `frozen=True`, that assignment raises `dataclasses.FrozenInstanceError` immediately, pointing at the bug.

**Documents intent.** `frozen=True` is a one-line declaration that says "this is read-only after construction." Readers of the code know they can pass instances around without defensive copies.

**Enables hashing.** Frozen dataclasses get an autogenerated `__hash__`. This means instances can be used as dict keys or set members. We don't use that today, but it costs nothing now and unlocks future deduplication, caching, and grouping logic.

**The mutability problem it prevents.** Without freeze:

```python
classified = classify_event(event)         # critical
report = generate_report([classified])     # 1 critical event
classified.risk_level = "info"             # someone reassigns
print(report.flagged_events)               # still contains the event
print(report.flagged_events[0].risk_level) # now says "info"!
```

The report's flagged list and the event's own risk level disagree. With freeze, the third line raises an exception at the moment of the bug, not three hours later when someone notices the dashboard is wrong.

**What freeze does not do.** It does not deep-freeze. `SessionReport.risk_breakdown` is a dict — `report.risk_breakdown["critical"] = 99` still works. The deep freeze would require an `immutables.Map` dependency. The shallow freeze catches the common bug (reassigning a top-level field) while staying within the standard library.

---

## Full risk classification pipeline: tracing `sudo rm -rf /tmp` from raw text to `ClassifiedEvent`

This walkthrough follows a single string from the moment it enters the system to the moment it becomes a `ClassifiedEvent`. Either path (stdin or hook) ends at the same classifier function, so we show both.

### Path A — via stdin (`vizhi start`)

**Start:** the user pipes a log file containing the line `"$ sudo rm -rf /tmp\n"` into `vizhi start`.

**Step 1 — read.** `stream_lines(sys.stdin)` yields the line `"$ sudo rm -rf /tmp\n"`. The blank-line filter passes it (non-empty after strip).

**Step 2 — parse.** `parse_line("$ sudo rm -rf /tmp\n")` runs:
- Builds the timestamp: `datetime.now(timezone.utc)` → say `2026-05-24T15:07:00.123456+00:00`.
- Strips trailing newlines: `"$ sudo rm -rf /tmp"`.
- Calls `classify("$ sudo rm -rf /tmp\n")` to compute the action type:
  - `lowered = "$ sudo rm -rf /tmp\n"`.
  - `_contains_any(lowered, COMMAND_KEYWORDS)` checks `"$ "` first → found → returns `True`.
  - `classify` returns `"command"`.
- Returns `ActionEvent(timestamp=2026-05-24T15:07:00.123456+00:00, raw_text="$ sudo rm -rf /tmp", action_type="command", metadata={})`.

### Path B — via hook (`vizhi install-hook` then a Bash call in Claude Code)

**Start:** Claude Code calls `Bash({"command":"sudo rm -rf /tmp"})`. The PostToolUse hook fires `python -m vizhi.hook_receiver` with the JSON payload on stdin.

**Step 1 — read.** `receive()` reads stdin into `raw`, parses JSON, extracts `tool_name="Bash"`, `tool_input={"command":"sudo rm -rf /tmp"}`, `session_id="abc-123"`, `timestamp="2026-05-24T15:07:00.123Z"`.

**Step 2 — synthesize raw_text.** `_build_raw_text("Bash", {"command":"sudo rm -rf /tmp"})` returns `"sudo rm -rf /tmp"` verbatim (the `command` branch).

**Step 3 — construct event.** `event = ActionEvent(timestamp=<parsed>, raw_text="sudo rm -rf /tmp", action_type="command", metadata={"tool_name":"Bash","source":"hook","cwd":"..."})`. Notice the `raw_text` differs slightly from Path A: no leading `$ ` because Claude's hook gave us the structured command, not a shell prompt rendering.

### Steps from here are identical for both paths

**Step 3/4 — classify.** `classify_event(event)` runs:

1. `text = event.raw_text.lower()`. Path A: `"$ sudo rm -rf /tmp"`. Path B: `"sudo rm -rf /tmp"`.
2. `hit = _first_match(text, CRITICAL_PATTERNS)`. Inside `_first_match`:
    - First pattern: `("sudo ", "Privileged command (sudo) — full root access")`. Is `"sudo "` in the text? Yes (both paths). Returns `"Privileged command (sudo) — full root access"`.
    - (If `"sudo "` had not matched, the second pattern `("rm -rf", "Recursive force delete — irreversible data loss")` would also have matched. First match wins, so `sudo` is the reason. Reordering the patterns inside `CRITICAL_PATTERNS` would change the reason text but not the verdict.)
3. `hit is not None` → returns `ClassifiedEvent(event=event, risk_level="critical", reason="Privileged command (sudo) — full root access")`.

**Step 4/5 — render and persist.**

- Path A: `render_event(console, classified)` prints `[15:07:00] CRIT (command) $ sudo rm -rf /tmp  — Privileged command (sudo) — full root access` (bold red). The event is appended to the in-memory `events` list. At session end, `generate_report` includes it in `flagged_events` and `all_events`, `print_report` shows it in the "Top Flagged" table, and `save_report` writes it to the JSON file.
- Path B: `_append_to_session_log(classified, "abc-123", "./vizhi_reports")` appends one line to `session_abc-123.jsonl`. That line is:
    ```json
    {"timestamp":"2026-05-24T15:07:00.123000+00:00","raw_text":"sudo rm -rf /tmp","action_type":"command","metadata":{"tool_name":"Bash","source":"hook","cwd":"..."},"risk_level":"critical","reason":"Privileged command (sudo) — full root access"}
    ```
   - If `vizhi watch` is running, `_drain` picks this line up within 200ms, `_event_from_line` rehydrates it into the same `ClassifiedEvent` shape, and `render_event` prints the same bold-red line as Path A.

**The pipeline's universal property:** any path that produces an `ActionEvent` ends at `classify_event`, which is deterministic and pure. Given the same `(raw_text, action_type)`, you always get the same `(risk_level, reason)`. This is what makes the rule engine debuggable: rerun the classifier on the saved JSON's `raw_text` and you must get the same verdict.

---

## What happens at session end: report generation step by step

Session end is triggered by stdin EOF, by Ctrl+C in the watcher, or by Ctrl+C in `vizhi watch`. In all cases the path converges on `generate_report` → `print_report` → `save_report`. Detailed steps:

**Step 1 — collect inputs.** The end-of-session caller has three things in scope:
- `events: list[ClassifiedEvent]` — the accumulated event list.
- `started_at: datetime` — captured at the start of the session (UTC).
- `session_id: uuid.UUID` — generated at the start (or derived from the hook session ID via `_parse_session_uuid`).

**Step 2 — `generate_report`.** Called with `(events, started_at=..., ended_at=datetime.now(timezone.utc), session_id=...)`.
- Resolves `sid` (provided or fresh UUID), `end` (provided or now), `start` (provided, else first event's timestamp, else `end`).
- Initializes `breakdown` with every `RiskLevel` key at 0: `{"critical":0,"high":0,"medium":0,"low":0,"info":0}`.
- Loops every `ce in events`, increments `breakdown[ce.risk_level]`.
- Builds `flagged = [ce for ce in events if ce.risk_level in FLAGGED_LEVELS]` (i.e. critical or high).
- Returns `SessionReport(session_id=sid, started_at=start, ended_at=end, total_actions=len(events), risk_breakdown=breakdown, flagged_events=flagged, all_events=list(events))`.

**Step 3 — `print_report`.** Called with `(report, console)`.
- Computes `duration_secs = (report.ended_at - report.started_at).total_seconds()`.
- Builds a header string. Wraps it in a Rich `Panel` with title `"Vizhi Session Report"`, border style `"cyan"`. Prints the panel.
- Builds a Rich `Table` titled `"Risk Breakdown"`. Iterates `RISK_ORDER`, computes percent with `total = max(report.total_actions, 1)` (avoids div-by-zero on empty sessions), adds one row per severity with the count and percentage. Prints the table.
- If `report.flagged_events` is empty: prints `No critical or high-risk events this session.` in green and returns.
- Else: builds a second `Table` titled `"Top Flagged Events (critical / high)"` with columns `Time | Risk | Type | Action | Reason`. One row per flagged event, colorized by risk level via `RISK_STYLES`. Prints the table.

**Step 4 — `save_report`.** Called with `(report, output_dir)`.
- `Path(output_dir).mkdir(parents=True, exist_ok=True)`.
- `filename = f"session_{report.session_id}_{report.started_at.strftime('%Y%m%dT%H%M%SZ')}.json"`.
- `payload = _report_to_dict(report)`. The hand-crafted dict has fixed key order: `session_id`, `started_at`, `ended_at`, `duration_seconds`, `total_actions`, `risk_breakdown`, `flagged_events`, `all_events`. UUIDs → `str`; datetimes → ISO-8601; inner events flattened via `_classified_to_dict`.
- `file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")`.
- Returns the path string.

**Step 5 — final user message.** The caller (`_finalize_session` for stdin mode, `watch_cmd` for hook-watch mode) prints `Report saved: <path>`.

After this, no more I/O happens. The Python process exits with code 0.

---

## Difference between `session_*.jsonl` (live log) and `session_*.json` (final report)

These are two distinct file formats serving two distinct purposes. They are intentionally separate.

### `session_<sessionId>.jsonl` — the live log

- **Written by:** `hook_receiver._append_to_session_log` on every PostToolUse hook firing.
- **Format:** JSON Lines. One `ClassifiedEvent`-shaped JSON object per line, terminated by `\n`.
- **Filename:** `session_<sessionId>.jsonl` where `<sessionId>` is whatever Claude Code's hook payload calls the session (typically a UUID, sanitized via `_sanitize_session_id`).
- **Naming stability:** stable for the lifetime of the Claude Code session. Multiple hook firings all append to the same file.
- **Lifecycle:** created on the first hook firing of a session, appended to thereafter, never closed or rotated by Vizhi itself.
- **Mutability:** append-only. Existing lines are never modified or removed.
- **Per-record schema:**
  ```json
  {
    "timestamp": "<ISO-8601 with timezone>",
    "raw_text": "<the action text the classifier scanned>",
    "action_type": "<command|file_access|network|unknown>",
    "metadata": {"tool_name":"<Bash|Read|...>","source":"hook","cwd":"<optional>"},
    "risk_level": "<critical|high|medium|low|info>",
    "reason": "<one-line explanation>"
  }
  ```
- **Consumed by:** `session_viewer.tail_session` (live tail) and `cli.watch_cmd` (which then generates a report from the accumulated events). Also human-readable with `tail -f` or `jq`.
- **Purpose:** the durable, append-safe truth of "what tool calls have happened in this session," as they happen.

### `session_<uuid>_<YYYYMMDDTHHMMSSZ>.json` — the final report

- **Written by:** `reporter.save_report` at the end of a session (stdin mode end, or `vizhi watch` Ctrl+C).
- **Format:** a single JSON object (pretty-printed with `indent=2`).
- **Filename:** `session_<UUID>_<UTC start timestamp slug>.json`.
- **Naming stability:** unique per session-end. A second session-end on the same session would produce a new file (different timestamp).
- **Lifecycle:** written once, at session end. Never appended to.
- **Mutability:** immutable after write.
- **Schema:**
  ```json
  {
    "session_id": "<UUID>",
    "started_at": "<ISO-8601>",
    "ended_at": "<ISO-8601>",
    "duration_seconds": <float>,
    "total_actions": <int>,
    "risk_breakdown": {"critical":<int>,"high":<int>,"medium":<int>,"low":<int>,"info":<int>},
    "flagged_events": [<ClassifiedEvent records>],
    "all_events": [<every ClassifiedEvent record>]
  }
  ```
- **Consumed by:** `cli.report_cmd` (renders to terminal). Future v3 dashboard will ingest these.
- **Purpose:** the human- and tool-readable summary of one completed session. A self-contained audit artifact.

### Why two formats, not one?

- **Different consumers, different needs.** The live tail needs an append-safe streamable format. The report needs a single self-describing document with aggregates.
- **JSONL is bad at summaries.** You cannot put a top-level `total_actions` or `risk_breakdown` field in a JSONL file without breaking the one-record-per-line invariant.
- **JSON is bad at appends.** Writing a single record to a JSON array requires O(n) cost; concurrent writes risk corruption.
- **The two files are derivable from each other.** The `.json` report's `all_events` field contains every event from the `.jsonl` log (when the report is generated from a `vizhi watch` session). The redundancy is intentional: the `.jsonl` log is the durable per-tool-call record; the `.json` is the closed-book snapshot.

### What if a session ends without `vizhi watch` running?

The `.jsonl` file still gets appended to as long as the hook is installed and Claude Code is running. No `.json` report will be generated automatically — the user would need to run `vizhi watch --session-id <id>` (then immediately Ctrl+C) or manually reconstruct a report from the JSONL log. The latter is a `# TODO(v2.5):` for a `vizhi report --from-jsonl <path>` command.

---

## Architecture Diagram

```
                              ┌─────────────────────────────────────────┐
                              │                CLAUDE CODE                │
                              │                                          │
                              │   user prompt → LLM → tool decision      │
                              │                         │                │
                              │                         ▼                │
                              │   ┌────────────┐   tool execution        │
                              │   │  ~/.claude/│         │                │
                              │   │settings.   │◀───┐    │                │
                              │   │  json      │    │    ▼                │
                              │   └─────┬──────┘    │  tool result        │
                              │         │           │    │                │
                              │         │ "PostTool │    │                │
                              │         │  Use:    "│    │                │
                              │         │  python  "│    │                │
                              │         │  -m vizhi"│    │                │
                              │         │  .hook_  "│    │                │
                              │         │  receiver"│    │                │
                              │         ▼           │    ▼                │
                              │     ┌─────────────────────────┐           │
                              │     │  spawn hook process w/  │           │
                              │     │  JSON payload on stdin  │           │
                              │     └────────┬────────────────┘           │
                              └──────────────┼───────────────────────────┘
                                             │
                                             │  PostToolUse JSON payload
                                             ▼
       ┌──────────────────────────────────────────────────────────────────┐
       │                       VIZHI HOOK RECEIVER                         │
       │  (python -m vizhi.hook_receiver)                                  │
       │                                                                   │
       │  receive() → parse JSON → _build_raw_text() →                     │
       │  ActionEvent → classify_event() → ClassifiedEvent →               │
       │  _append_to_session_log()                                         │
       └──────────────────────────────────┬───────────────────────────────┘
                                          │  one JSON line
                                          ▼
                          ┌──────────────────────────────────┐
                          │  vizhi_reports/                   │
                          │     session_<sessionId>.jsonl    │  ◀── live log
                          │     (append-only)                 │
                          └────────┬──────────────────┬──────┘
                                   │                  │
                                   │ poll every 200ms │ read entirely
                                   ▼                  ▼
            ┌──────────────────────────────────┐  ┌──────────────────────────────────┐
            │   VIZHI WATCH                     │  │   (future v3: dashboard ingest)  │
            │   (session_viewer.tail_session)   │  │                                  │
            │                                   │  └──────────────────────────────────┘
            │   _drain() → _event_from_line() → │
            │   render_event() → events.append  │
            │                                   │
            │   on Ctrl+C: return events list   │
            └────────────────┬──────────────────┘
                             │  ClassifiedEvent[]
                             ▼
            ┌──────────────────────────────────┐
            │   REPORT GENERATION               │
            │   (reporter.generate_report)     │
            │                                   │
            │   events → SessionReport →        │
            │   print_report() (terminal) +    │
            │   save_report() (JSON file)      │
            └─────────────────┬────────────────┘
                              │  one JSON document
                              ▼
                  ┌─────────────────────────────────────┐
                  │  vizhi_reports/                       │
                  │   session_<uuid>_<ts>.json            │ ◀── final report
                  │   (written once, immutable)           │
                  └─────────────────────────────────────┘

         ════════════════════════════════════════════════════════════════════

                    LEGACY v1 PATH (still supported, separate flow):

           agent stdout/log file
                 │
                 │  `cat file.log | vizhi start`
                 ▼
       ┌──────────────────────────────────────────────────────────────────┐
       │                       VIZHI WATCHER (stdin)                       │
       │  (watcher.watch)                                                  │
       │                                                                   │
       │  stream_lines() → parse_line() → classify_event() →               │
       │  render_event() (terminal) + events.append                        │
       │                                                                   │
       │  on EOF or Ctrl+C: _finalize_session() → generate_report →        │
       │  print_report + save_report                                       │
       └──────────────────────────────────┬───────────────────────────────┘
                                          │
                                          ▼
                            session_<uuid>_<ts>.json
                                          
         ════════════════════════════════════════════════════════════════════

                    SETTINGS MANAGEMENT (side channel):

           `vizhi install-hook` / `vizhi uninstall-hook`
                 │
                 ▼
       ┌──────────────────────────────────────────────────────────────────┐
       │                       VIZHI INSTALLER                             │
       │  (installer.install_hook / installer.uninstall_hook)              │
       │                                                                   │
       │  load_settings(~/.claude/settings.json) → mutate dict →           │
       │  save_settings(~/.claude/settings.json)                           │
       │                                                                   │
       │  idempotent: install twice = no duplicate.                        │
       │  cascade-prune on uninstall.                                      │
       └──────────────────────────────────────────────────────────────────┘
```

---

## Version History

### v1.1 — stdout watcher and parser with action-type classification

**What was built.** The core `parser.py` and `watcher.py` modules. The parser turned each line into an `ActionEvent` with a coarse `action_type` (command / file_access / network / unknown). The watcher streamed stdin, parsed each line, and printed a basic feed via Rich. No risk classification yet — the live feed showed action type but every event was rendered the same color.

**Why.** Before we could reason about risk, we needed the structural primitive: a typed, timestamped event per line of agent activity. Building the structure first kept the v1.2 classifier work clean — just plug new logic in after the parser.

**Problem solved.** Established the data model. Provided a working "watch a stream and tag what kind of action each line is" tool.

### v1.2 — risk classification engine with severity levels and updated live feed

**What was built.** The `classifier.py` module: `RiskLevel`, the cascading `classify_event` function, the `CRITICAL_PATTERNS` / `HIGH_PATTERNS` / `MEDIUM_*` / `KNOWN_SAFE_HOSTS` / `LOW_FILE_READ_KEYWORDS` constants, and the `ClassifiedEvent` dataclass. Updated `watcher.py` to call `classify_event` and to color-code each rendered line by severity.

**Why.** The action-type tag from v1.1 told us *what kind* of activity, but not *whether to worry*. A live feed where everything is white is barely useful. The cascade architecture (critical → high → category-based → info) lets us add new patterns without restructuring existing logic.

**Problem solved.** Vizhi now has an opinion. The live feed visually surfaces dangerous actions, and the downstream reporter can compute breakdowns.

### v1.3 — session report generator with terminal summary and JSON export

**What was built.** The `reporter.py` module: `SessionReport` dataclass, `generate_report` (aggregation), `print_report` (terminal rendering via Rich `Panel` and `Table`), `save_report` (JSON persistence), plus the `_report_to_dict` and `_classified_to_dict` serializers. Wired it into `watcher.py` via `_finalize_session`.

**Why.** The live feed is ephemeral. Without a session summary, the only way to revisit a past run was to scroll up. Without a JSON dump, the only consumer was a human. Persisting structured reports is the foundation for future v3 dashboard ingest.

**Problem solved.** Sessions are now durable artifacts. The `risk_breakdown` and `flagged_events` provide at-a-glance summaries without re-reading the full feed.

### v1.4 — CLI tool with `vizhi start` and `vizhi report`, `pyproject.toml`, README

**What was built.** The `cli.py` module with `start_cmd` and `report_cmd`. `pyproject.toml` with the Click entry point (`vizhi = "vizhi.cli:main"`). README.md with installation and usage docs.

**Why.** Up to this point, Vizhi was invoked via `python -m vizhi.watcher`. A real CLI is required to feel like a tool. Pip-installability unlocks the `pipx`/`pip install -e .` user experience and prepares for PyPI publication.

**Problem solved.** Vizhi is now usable as `vizhi start` and `vizhi report`. The package is installable in editable mode for development.

### v2.1 — hook receiver with PostToolUse JSON parsing and session JSONL logging

**What was built.** The `hook_receiver.py` module: `receive`, `_build_raw_text`, `_parse_timestamp`, `_append_to_session_log`, `_sanitize_session_id`, `_get_field`, `_warn`, plus the `TOOL_TO_ACTION_TYPE` and `FILE_PATH_TOOLS` constants. The CLI got a `hook` subcommand.

**Why.** The v1 stdin pipe sees only what the agent *prints*. Real tool calls — their arguments, their structure — are richer. Claude Code's PostToolUse hook delivers the structured tool input directly. Hooking lets Vizhi see what the agent is actually doing, not just what it narrates.

**Problem solved.** Vizhi can now observe Claude Code's real tool calls instead of inferring them from stdout. The defensive error handling (always exit 0) ensures Vizhi never breaks the agent.

### v2.2 — hook installer with `vizhi install-hook` and `vizhi uninstall-hook`

**What was built.** The `installer.py` module: `get_settings_path`, `load_settings`, `save_settings`, `install_hook`, `uninstall_hook`, `_vizhi_matcher_entry`, `_vizhi_hook_present`, `_is_vizhi_hook`. The CLI got `install-hook` and `uninstall-hook` subcommands.

**Why.** Without the installer, the user had to hand-edit `~/.claude/settings.json` to enable the hook. That is error-prone (JSON syntax mistakes, wrong matcher shape) and unfriendly. Automating it with cascade-pruning uninstall makes the setup feel one-shot.

**Problem solved.** End-to-end setup is now `pip install -e . && vizhi install-hook`. Idempotence makes the install command safe in scripts.

### v2.3 — live session viewer with `vizhi watch` command

**What was built.** The `session_viewer.py` module: `find_latest_session`, `tail_session`, `_wait_for_file`, `_drain`, `_event_from_line`, plus the `POLL_INTERVAL_SECONDS` and `FILE_WAIT_SECONDS` constants. The CLI got a `watch` subcommand and a `_parse_session_uuid` helper.

**Why.** The hook writes silently to a JSONL file — useful for forensics but invisible in real time. Without a live tail, the user has no way to see Vizhi's verdicts as the agent works. The polling design avoids cross-platform watchdog dependencies. On Ctrl+C, the tailer generates the same report the v1 watcher does, so hook mode has feature parity with stdin mode.

**Problem solved.** Hook mode now has a live feed. The user can run Claude Code in one terminal, `vizhi watch` in another, and see every tool call color-coded in real time.

### v2.4 — comprehensive documentation (current phase)

**What is being built.** Three documentation files: `docs/code-explained.md` (per-file deep dive), `docs/project-explained.md` (this file), `docs/tech-stack.md` (every technology used and why). README.md is updated with a `## Documentation` section pointing at them.

**Why.** As the codebase reaches v2.3, the surface area is large enough that new contributors or evaluators (interviewers, security reviewers, the developers themselves three months from now) cannot pick it up by reading source alone. The docs codify the design decisions and trace data flow so anyone can follow the architecture end-to-end.

**Problem solved.** The project becomes onboardable without the original author present.

---

## Key Design Decisions

**Cascade-based rule classifier rather than ML.** A simple ordered list of substring patterns with explicit reason strings is debuggable, deterministic, and editable by anyone who can read English. ML models would be a moving target: opaque verdicts, training data drift, dependency on a model artifact, and risk of false negatives on inputs that look benign to the model but are obviously bad to a human (e.g. `sudo`). The cascade is also fast: 30-something `str.contains` calls per event is microseconds, even on slow hardware. The trade-off is recall: a sufficiently obfuscated payload will slip past, and substring matching has known false positives on quoted or commented text. The TODO at the top of `classifier.py` tracks the eventual `shlex`-based tokenization upgrade.

**Two output formats — JSONL for live, JSON for final.** Each format suits its use case (see "Why JSONL was chosen" above). Trying to use one format for both would either slow the hook receiver to O(n²) per session (using JSON arrays) or strip the report of its top-level aggregates (using JSONL with no header).

**Polling for the live tailer.** Zero new dependencies, identical cross-platform behavior, and a 200ms worst-case latency that is below human perception. The cost is a small constant CPU/IO load, which is negligible.

**Frozen dataclasses for the entire data model.** Catches accidental mutation at the moment of the bug, documents read-only intent, and gives free hashability. The shallow-freeze quirk (mutable inner containers) is acceptable in the alpha and known.

**Defensive hook receiver (exit 0 always).** Claude Code interprets non-zero hook exit codes as "abort the agent." Even on every malformed payload, we never block the user's tool call. Warnings go to stderr for debugging.

**Idempotent installer with cascade pruning.** Install twice = no duplicate. Uninstall after install = byte-for-byte original file (minus indent normalization). Users can re-run setup scripts safely.

**Click for CLI, Rich for terminal output, nothing else.** Two well-maintained, widely used libraries. Every other dependency is in Python's standard library. Keeps the install footprint small and the surface area trivial to audit.

**Session UUIDs.** Each session gets a UUID embedded in its report filename. Multiple sessions in the same directory never collide. UUIDs are also self-formatting and length-fixed, which is friendly to grep and to dashboard databases.

**UTC everywhere.** All `datetime`s are constructed with `timezone.utc`. Avoids the timezone-conversion bugs that plague any tool whose logs travel across machines.

---

## Current Limitations

**Substring matching has false positives and false negatives.** A comment like `"# rm -rf was discussed yesterday"` would be flagged critical. A command like `bash -c "$(echo s)udo whoami"` would slip through. The `# TODO(v2.0): replace substring matching with proper tokenized command parsing` comment in `classifier.py` tracks the planned upgrade.

**No PreToolUse blocking.** Vizhi sees tool calls *after* they execute. A critical action is recorded, but it has already happened. PreToolUse hooks (which let the hook reject a tool call before it runs) are planned in `# TODO(v2.2): also support PreToolUse hooks so vizhi can block on critical risk.` in `hook_receiver.py`.

**Hardcoded interpreter path in hook command.** `HOOK_COMMAND = "python -m vizhi.hook_receiver"` uses bare `python`. Users with multiple Python versions or virtualenvs may need to make sure the right one is on `PATH`. The `# TODO(v2.3): support a custom interpreter / venv path` in `installer.py` tracks the fix.

**Rules are not user-extensible without code changes.** All patterns live in `classifier.py` constants. A user who wants to flag their internal `secret_company_dir/` cannot do so without editing the source. `# TODO(v1.3): move rules into a YAML/JSON config so users can extend without editing code.` tracks the move to a config file.

**No multi-session tailing.** `vizhi watch` follows exactly one session. Watching every active session at once requires a separate invocation per session. `# TODO(v2.4): support --follow-all to multiplex multiple session files at once.` tracks the feature.

**No native file watcher.** `vizhi watch` polls. 200ms worst-case is invisible to a human but lossy for a future dashboard ingest pipeline that wants real-time. `# TODO(v2.4): swap polling for a native file watcher (watchdog) for lower latency.` tracks the upgrade.

**Reports are local files only.** No dashboard, no central store. Cross-session analysis requires manually grepping `vizhi_reports/`. The planned FastAPI + React + Supabase dashboard (v3) is the solution.

**Memory grows linearly with session length.** The v1 watcher and the live tailer both keep every event in an in-memory list until session end. A 24-hour session with one tool call per second would hold ~86k events — fine on a developer machine, not fine on a constrained host. Rolling to disk is a v2.5+ concern.

**No automated tests.** The `tests/` directory exists but is empty. v2.4 is documentation; v2.5+ will add `pytest` + coverage. The `# TODO(v1.5)` in `pyproject.toml` tracks the optional `[project.optional-dependencies]` groups for `dev`/`test`.

**No alerting.** Critical events are visible in the live feed and the report, but they do not page anyone. Webhooks / Slack / email are v3+ work.

**No structured logging.** The hook receiver's stderr warnings are unstructured `print` calls. A future improvement would route through `logging` with JSON formatting.

**No PreToolUse — repeats above for emphasis.** This is the single biggest limitation: Vizhi cannot prevent harm, only record it. The classifier's verdicts are perfect for audit and post-mortem; they cannot stop the agent from doing damage in the first place.
