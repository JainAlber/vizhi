# Code Explained

This document walks through every file inside the `vizhi/` package. For each file you get a plain-English explanation, a technical explanation, a function-by-function reference, and a map of how the file connects to the rest of the codebase.

The files are presented in dependency order — bottom layer first, top layer last — so that by the time you reach `cli.py`, `hook_receiver.py`, `installer.py`, and `session_viewer.py`, every primitive they use has already been introduced.

---

## `__init__.py`

### Simple Explanation

Every Python package needs a small file called `__init__.py` that announces "this folder is a package, not just a folder full of loose files." Vizhi's `__init__.py` does exactly that, and adds one extra thing — a single version string that the CLI prints when you run `vizhi --version`. Think of it as the cover page of a book: thin, but it tells you what edition you are holding.

### Technical Explanation

`vizhi/__init__.py` is the package-initialization module that Python executes the very first time anything inside the `vizhi` namespace is imported. It is the canonical place to expose package-level metadata.

Vizhi keeps this module deliberately minimal — there is no eager side-effect import of submodules, no logging configuration, no module-level state. The only public symbol is `__version__`, a `str` literal that follows [PEP 440](https://peps.python.org/pep-0440/) version semantics. Both `pyproject.toml` (`[project].version`) and this file hard-code `"0.1.0"`; they must be kept in sync until a build-time `setuptools_scm`-style mechanism is introduced.

### Functions & Classes

There are no functions or classes. The only symbol is:

- **`__version__: str = "0.1.0"`** — the project version string. Imported by `cli.py` to feed `click.version_option()` so that `vizhi --version` prints `vizhi 0.1.0`.

### Connections

- **Imported by:** `vizhi/cli.py` (uses `__version__` in the Click version option).
- **Imports:** Nothing.

---

## `parser.py`

### Simple Explanation

`parser.py` takes a single line of text — the kind you would see scrolling past in a terminal when Claude Code is working — and turns it into a small, structured record. Its job is to look at the line and decide which broad category of activity it represents: did Claude run a shell command, touch a file, make a network call, or do something else? It does not yet decide whether the activity is dangerous; that is the next layer's job. Think of it as the receptionist who labels each visitor before passing them on.

### Technical Explanation

`parser.py` defines the first stage of Vizhi's processing pipeline. It exposes:

- The `ActionType` type alias — a [`typing.Literal`](https://docs.python.org/3/library/typing.html#typing.Literal) of four string values that narrows what a downstream consumer can expect.
- The `ActionEvent` dataclass — Vizhi's canonical in-memory representation of one observed agent action. It is `frozen=True`, which gives it value semantics, structural equality, and hashability for free.
- The `classify()` function — a pure keyword-matching classifier that maps a raw line to one of the four `ActionType` values.
- The `parse_line()` function — the public entry point that pairs a raw line with the current UTC timestamp and the inferred `ActionType` into a fully populated `ActionEvent`.

The classifier is deliberately keyword-based (substring matching against lowercased input). This is a `O(n × k)` scan per line, where `n` is line length and `k` is the number of keywords — fast enough that the stdin watcher can keep up with realistic agent output rates without buffering. A `# TODO(v1.2)` comment marks the planned upgrade to a tokenized parser once Vizhi consumes Claude Code's structured tool-use envelopes directly (which is now what `hook_receiver.py` does — see below).

### Functions & Classes

**`ActionType`** — `Literal["command", "file_access", "network", "unknown"]`
A type alias used everywhere a function returns or accepts an action category. `Literal` types let the type checker reject typos at lint time (e.g. `"netwrok"` would never be accepted in place of `"network"`).

**`ActionEvent` (dataclass, frozen)**
- Fields:
  - `timestamp: datetime` — the moment the event was observed, in UTC.
  - `raw_text: str` — the original line with trailing `\r\n` stripped.
  - `action_type: ActionType` — the broad category.
  - `metadata: dict[str, str]` — free-form key/value pairs, defaulting to empty. Populated by the hook receiver with things like the originating tool name and current working directory.
- `frozen=True` means instances cannot be mutated after construction, so you can safely hash them or stash them in sets/dicts without worrying about a downstream consumer accidentally rewriting a field.

**`classify(line: str) -> ActionType`**
- Lowercases the input and runs it through three keyword tuples in priority order: `COMMAND_KEYWORDS`, `FILE_ACCESS_KEYWORDS`, `NETWORK_KEYWORDS`.
- Returns the first matching category, or `"unknown"` if nothing matches.
- Edge case: empty strings hit no keyword and return `"unknown"`.

**`parse_line(line: str) -> ActionEvent`**
- Records `datetime.now(timezone.utc)` so the event is timezone-aware (avoids the silent local-time vs UTC bugs that plague naive `datetime.now()` usage).
- Calls `classify()` to infer the action type.
- Strips trailing newline characters from `raw_text` so display layers don't double-space the feed.

**`_contains_any(haystack: str, needles: tuple[str, ...]) -> bool`** — private helper. Returns `True` if any needle is a substring of `haystack`. Uses a generator expression so it short-circuits on the first match.

### Connections

- **Imported by:** `vizhi/watcher.py` (uses `parse_line()` on each stdin line), `vizhi/cli.py` (uses `ActionEvent` to rebuild events when reading saved JSON reports), `vizhi/hook_receiver.py` (uses `ActionEvent` and `ActionType` when building events from hook payloads), `vizhi/session_viewer.py` (uses `ActionEvent` when deserializing JSONL lines), `vizhi/classifier.py` (imports `ActionEvent` as the type its rules consume).
- **Imports:** Standard library only — `dataclasses`, `datetime`, `typing`. No third-party dependencies.

---

## `classifier.py`

### Simple Explanation

`classifier.py` is Vizhi's safety judge. Once `parser.py` has labelled what *kind* of activity happened, the classifier asks the more important question: *how risky is it?* It assigns a severity colour — from "critical" (red alarm) down to "info" (silent dim white) — and writes a one-sentence reason explaining why it picked that level. Everything Vizhi later renders on screen or summarises in a report ultimately depends on the verdict this module produces.

### Technical Explanation

`classifier.py` is a rule-based, deterministic expert system. It implements a fixed-priority match chain that walks through tiers of pattern tuples until one matches:

1. `CRITICAL_PATTERNS` — irrecoverable destruction or root-level privilege escalation.
2. `HIGH_PATTERNS` — sensitive file access, destructive SQL, leaked credentials.
3. Network calls — split into `low` (known-safe host) and `medium` (unknown domain) based on `action_type == "network"` + the `KNOWN_SAFE_HOSTS` allow-list.
4. File-write keywords → `medium`.
5. Process-execution keywords → `medium`.
6. File-read keywords → `low`.
7. Fallback → `info`.

The module exposes:

- `RiskLevel` — a `Literal["critical", "high", "medium", "low", "info"]` type alias.
- `ClassifiedEvent` — a frozen dataclass wrapping an `ActionEvent` with its assigned `risk_level` and a human-readable `reason`.
- `classify_event()` — the only public function. Takes an `ActionEvent` and returns a `ClassifiedEvent`.

A rule-based approach is intentional. Vizhi's threat model includes the case where a user pipes a malicious agent's output into the watcher — so the classifier itself must be deterministic and inspectable. There is no model weight file, no network call, no learned probability. Every verdict can be traced to a specific pattern tuple, which makes the system auditable and easy to extend.

The `# TODO(v2.0)` comment flags the planned upgrade: replacing substring matching with `shlex`-based command tokenisation. Substring matching has known false positives (the literal string `"rm -rf"` inside a quoted comment is flagged the same as the real command), and proper argv inspection would eliminate that class of error.

### Functions & Classes

**`RiskLevel`** — `Literal["critical", "high", "medium", "low", "info"]`. Used as the type of `ClassifiedEvent.risk_level` and as the key type for the various `RISK_STYLES` / `RISK_LABELS` dictionaries elsewhere.

**Pattern constants**
- `CRITICAL_PATTERNS: tuple[tuple[str, str], ...]` — pairs of `(needle, reason)`. Each `needle` is the case-insensitive substring to match; `reason` is the plain-English explanation surfaced to the user.
- `HIGH_PATTERNS: tuple[tuple[str, str], ...]` — same shape, lower severity.
- `MEDIUM_FILE_WRITE_KEYWORDS`, `MEDIUM_PROCESS_KEYWORDS`, `LOW_FILE_READ_KEYWORDS` — flat tuples of substrings without per-needle reasons; they all share a single canned reason.
- `KNOWN_SAFE_HOSTS: tuple[str, ...]` — the network allow-list (GitHub, PyPI, npm, localhost, …).

**`ClassifiedEvent` (dataclass, frozen)**
- Fields: `event: ActionEvent`, `risk_level: RiskLevel`, `reason: str`.
- Frozen for the same reasons as `ActionEvent` — value semantics and safe sharing across collectors, reporters, and renderers.

**`classify_event(event: ActionEvent) -> ClassifiedEvent`**
- Lowercases `event.raw_text` once at the top and uses that for every substring check (cheaper than re-lowering inside each rule).
- Walks the priority chain described above. Returns at the first match.
- Edge case: an event whose `action_type` is `"network"` but whose `raw_text` happens to mention nothing identifiable still goes to `medium` (unknown domain) because the type signal is enough on its own.
- Always returns a fully populated `ClassifiedEvent` — the fallback branch guarantees no `None` ever escapes.

**`_first_match(haystack: str, patterns: tuple[tuple[str, str], ...]) -> str | None`** — private helper that walks `(needle, reason)` tuples and returns the reason for the first hit (or `None`).

**`_contains_any(haystack: str, needles: tuple[str, ...]) -> bool`** — private helper identical in spirit to the one in `parser.py`. Kept duplicated rather than imported because each module is meant to stand alone.

### Connections

- **Imported by:** `vizhi/watcher.py` (calls `classify_event()` on each parsed line; uses `RiskLevel` for its render styling), `vizhi/reporter.py` (uses `RiskLevel` and `ClassifiedEvent` to build session summaries), `vizhi/hook_receiver.py` (calls `classify_event()` on hook payloads), `vizhi/session_viewer.py` (deserialises JSONL records back into `ClassifiedEvent`), `vizhi/cli.py` (rebuilds events from saved reports).
- **Imports:** `vizhi/parser.py` for `ActionEvent`; standard library `dataclasses` and `typing`.

---

## `watcher.py`

### Simple Explanation

`watcher.py` is the original "live monitor" mode (v1). You point Vizhi's stdin at the terminal output of any AI agent — for example by piping `claude --print "audit this repo" | vizhi start` — and `watcher.py` reads that stream line by line, parses each line, classifies it, and prints a colour-coded feed showing what just happened and how risky it was. When you stop the stream (Ctrl+C, or the upstream process exits), the watcher hands the collected events off to the reporter so you get a final summary.

### Technical Explanation

`watcher.py` implements the v1 pipeline as a streaming consumer of `sys.stdin`. The pipeline is:

```
stdin → stream_lines (generator) → parse_line → classify_event
      → render_event (live, side effect) → events.append (collected)
      → on EOF/Ctrl+C: generate_report + print_report + save_report
```

Key design choices:

- **Generator-based ingest.** `stream_lines()` uses `iter(source.readline, "")`, the two-argument form of `iter`, which yields lines as they arrive and terminates cleanly when `readline()` returns `""` (i.e. EOF). This avoids buffering the entire input.
- **Rich for output.** The `Console` and `Text` classes from `rich` give per-segment colouring. The `RISK_STYLES` and `RISK_LABELS` dicts keyed on `RiskLevel` mirror those in `reporter.py` so the live feed and the final report use a consistent vocabulary.
- **Try/except/finally lifecycle.** The `watch()` function wraps its event loop in `try / except KeyboardInterrupt / finally`. The `finally` block guarantees the report is produced even when the user kills the watcher.
- **UTC timestamps.** A `datetime.now(timezone.utc)` is recorded at the start of the session and passed through to the reporter so the report's elapsed time is exact.

The module is *also* used as a library by `session_viewer.py`, which re-uses `render_event()` to keep the v2.3 live tail visually identical to the v1 stdin watcher.

### Functions & Classes

**Constants**
- `RISK_STYLES: dict[RiskLevel, str]` — maps risk level to a Rich style string (`"bold red"`, `"yellow"`, etc.).
- `RISK_LABELS: dict[RiskLevel, str]` — short uppercase labels (`"CRIT"`, `"HIGH"`, `" MED"`, `" LOW"`, `"INFO"`). The padded space in `" MED"`/`" LOW"` keeps columns aligned in the feed.

**`stream_lines(source: IO[str]) -> Iterator[str]`**
- Yields one non-blank line from `source` at a time using `iter(source.readline, "")`.
- Skips blank lines so the feed isn't cluttered with empties.
- Terminates when `readline()` returns `""`, the canonical EOF sentinel.

**`render_event(console: Console, classified: ClassifiedEvent) -> None`**
- Builds a `rich.text.Text` segment by segment: timestamp, risk label, action type, raw text, reason.
- Side-effect only — returns nothing.
- Reused by `session_viewer.py` so the live JSONL tail has identical output formatting to the stdin watcher.

**`watch(source: IO[str] | None = None, console: Console | None = None, output_dir: str = "./vizhi_reports") -> None`**
- The session entry point. Allocates a fresh `uuid.uuid4()` as the session ID and records `started_at`.
- Iterates `stream_lines(source)`, parsing + classifying each line, appending to `events`, and rendering.
- `KeyboardInterrupt` produces a friendly "stopped" message; the `finally` block always finalises the session.
- Edge cases: an empty stream still produces a (mostly empty) report with zero events; injecting `source` and `console` for tests is supported via the optional kwargs.

**`_finalize_session(...) -> None`**
- Private helper called from `watch()`'s `finally`. Builds the `SessionReport`, prints it, saves the JSON, and echoes the saved-path message.

### Connections

- **Imported by:** `vizhi/cli.py` (the `vizhi start` command calls `watch()`), `vizhi/session_viewer.py` (imports `render_event` so the v2 live tail reuses the same row format).
- **Imports:** `vizhi/parser.py` (`parse_line`), `vizhi/classifier.py` (`ClassifiedEvent`, `RiskLevel`, `classify_event`), `vizhi/reporter.py` (`generate_report`, `print_report`, `save_report`), plus `rich` and standard library `sys`, `uuid`, `datetime`, `typing`.

---

## `reporter.py`

### Simple Explanation

`reporter.py` is the bookkeeper. While the watcher is busy printing the live feed, the reporter waits for the session to end, then assembles everything into a tidy final report. That report has two forms: a colourful summary printed to the terminal so the user can see what happened at a glance, and a JSON file saved to disk so the same information can be re-read, e-mailed, or analysed later. It is also the layer responsible for deciding which events are worth highlighting in the "top flagged" table — currently every `critical` and `high` event.

### Technical Explanation

`reporter.py` is the aggregation and output layer. It exposes:

- The `SessionReport` frozen dataclass — an immutable snapshot of one session.
- `generate_report()` — builds a `SessionReport` from a list of `ClassifiedEvent` objects.
- `print_report()` — renders a `SessionReport` to the terminal using `rich.Panel` for the header, `rich.Table` for the risk breakdown, and a second `rich.Table` for the flagged-events list.
- `save_report()` — serialises a `SessionReport` to a `session_<uuid>_<timestampslug>.json` file under the configured output directory.

The risk-ordering tuple `RISK_ORDER` (critical → info) and the `FLAGGED_LEVELS` `frozenset` are the canonical ordering / membership constants used everywhere a report is printed or filtered. They are defined once here to avoid drift.

Serialisation uses `json.dumps(..., indent=2)` — pretty-printed so the saved reports are human-readable. Timestamps go through `datetime.isoformat()` and UUIDs through `str()` to keep the JSON portable to any language that can read ISO-8601 strings.

A `# TODO(v1.4)` flags making the output format pluggable (Markdown, HTML); a `# TODO(v2.0)` flags moving persistence from local JSON to Supabase.

### Functions & Classes

**Constants**
- `RISK_ORDER: tuple[RiskLevel, ...]` — canonical iteration order for printing breakdown rows. Critical to least-risky.
- `FLAGGED_LEVELS: frozenset[RiskLevel]` — the set of risk levels that qualify for the "flagged events" table. Currently `{"critical", "high"}`.
- `RISK_STYLES: dict[RiskLevel, str]` — duplicated from `watcher.py` so the report can be styled even when the watcher isn't loaded (e.g. when running `vizhi report` standalone).

**`SessionReport` (dataclass, frozen)**
- Fields: `session_id: uuid.UUID`, `started_at: datetime`, `ended_at: datetime`, `total_actions: int`, `risk_breakdown: dict[RiskLevel, int]`, `flagged_events: list[ClassifiedEvent]`, `all_events: list[ClassifiedEvent]`.
- Frozen, so once built it cannot be mutated — which means a `SessionReport` can be safely passed across threads or saved/loaded without identity drift.

**`generate_report(events, started_at=None, ended_at=None, session_id=None) -> SessionReport`**
- Resolves defaults for the three optional parameters: a fresh UUID if `session_id` is missing, `now(UTC)` if `ended_at` is missing, and the first event's timestamp (or `ended_at` if there are no events) for `started_at`.
- Builds the risk breakdown with all five levels pre-seeded to zero so the printout always has every row, even if some levels saw no events.
- Filters `flagged_events` from the full list using `FLAGGED_LEVELS`.

**`print_report(report: SessionReport, console: Console) -> None`**
- Prints a `Panel` header with session ID, start, end, duration, total actions.
- Prints the risk-breakdown table with count and percent columns; percent is computed against `max(total_actions, 1)` to avoid division-by-zero in empty sessions.
- If no events are flagged, prints a green "No critical or high-risk events this session." message and returns early.
- Otherwise prints the flagged-events table with time, risk, type, action, reason.

**`save_report(report: SessionReport, output_dir: str = "./vizhi_reports") -> str`**
- Creates `output_dir` with `mkdir(parents=True, exist_ok=True)` so a missing directory is not a failure.
- Builds a filename of the form `session_<uuid>_<timestampslug>.json`. The slug uses `strftime("%Y%m%dT%H%M%SZ")` to embed the start time directly in the filename, which sorts naturally and is unambiguous across timezones.
- Returns the full path as a string.

**`_report_to_dict(report) -> dict`** — internal serialiser. Walks the dataclass and converts non-JSON-native types to strings.

**`_classified_to_dict(ce) -> dict`** — internal serialiser for one `ClassifiedEvent`. Mirrors the schema written by `hook_receiver.py` so the JSONL log and the JSON report agree on field names.

**`_fmt_duration(seconds: float) -> str`** — private helper. Formats an integer number of seconds as `"Hh Mm Ss"`, dropping empty leading units. Edge case: clamps negative inputs to zero.

### Connections

- **Imported by:** `vizhi/watcher.py` (for `generate_report`, `print_report`, `save_report`), `vizhi/cli.py` (for `SessionReport`, `generate_report`, `print_report`, `save_report` — used by `vizhi report` and `vizhi watch`).
- **Imports:** `vizhi/classifier.py` for `ClassifiedEvent` and `RiskLevel`; `rich` for `Console`, `Panel`, `Table`; standard library `json`, `uuid`, `dataclasses`, `datetime`, `pathlib`.

---

## `cli.py`

### Simple Explanation

`cli.py` is the front door — the command-line interface. When you type `vizhi start`, `vizhi report`, `vizhi watch`, `vizhi hook`, `vizhi install-hook`, or `vizhi uninstall-hook`, this file is what handles your request. Internally it doesn't do much real work itself; instead it routes to the right specialist module: the stdin watcher, the report loader, the live tailer, the hook receiver, or the hook installer. Think of it as the receptionist who reads your form and walks you down the right corridor.

### Technical Explanation

`cli.py` is a Click command group with six subcommands:

| Subcommand        | Calls                                          | Purpose                                                                 |
|-------------------|------------------------------------------------|-------------------------------------------------------------------------|
| `start`           | `watcher.watch`                                | v1 stdin watcher.                                                       |
| `report`          | `_latest_report_path` + `_load_report` + `print_report` | Pretty-prints the most recent saved JSON report.                 |
| `hook`            | `hook_receiver.receive`                        | Receives one PostToolUse payload from stdin (legacy CLI entry point).   |
| `watch`           | `session_viewer.find_latest_session` + `session_viewer.tail_session` + `generate_report` + `print_report` + `save_report` | v2.3 live JSONL tail. |
| `install-hook`    | `installer.load_settings` + `installer.install_hook` + `installer.save_settings` | Installs the PostToolUse hook into `~/.claude/settings.json`. |
| `uninstall-hook`  | `installer.load_settings` + `installer.uninstall_hook` + `installer.save_settings` | Removes it.                                              |

Click's `@click.group` + `@main.command` decorators are used so the module exposes a single `main()` callable that dispatches based on `sys.argv`. `pyproject.toml`'s `[project.scripts]` block wires `main()` to the `vizhi` console script, which is what `pip install -e .` installs to the user's `Scripts/` directory on Windows.

The CLI is deliberately thin: every command is at most twenty lines, every line of business logic lives in a sibling module. Errors from those modules surface as either `SystemExit(1)` (for usage failures, e.g. corrupt `settings.json` or no session log found) or `SystemExit(0)` (for hook receiver failures, which must never block the agent — see `hook_receiver.py`).

### Functions & Classes

**`main()`** — the Click group. Decorated with `@click.group(help=...)` and `@click.version_option(__version__, prog_name="vizhi")`. Its body is empty (just a docstring) because all the work is in the subcommands.

**`start_cmd(output_dir: str)`** — the `vizhi start` command. Single call to `watcher.watch(output_dir=output_dir)`.

**`report_cmd(output_dir: str)`** — the `vizhi report` command. Finds the most recent `session_*.json`, deserialises it with `_load_report()`, and prints it with `print_report()`. Exits with code 1 if there are no reports.

**`hook_cmd(output_dir: str)`** — the `vizhi hook` command. Delegates to `hook_receiver.receive()` and propagates its return code as the exit code.

**`watch_cmd(session_id: str | None, output_dir: str)`** — the `vizhi watch` command.
- Auto-detects the most recent session via `find_latest_session()` if `--session-id` is not provided.
- Records `started_at` at watch-start, although the report's `generate_report()` will still prefer the first event's timestamp if events exist.
- Wraps `tail_session()` in a `try/except FileNotFoundError` (clear error + exit 1) and `try/except KeyboardInterrupt` (clean stop). `tail_session()` itself also catches `KeyboardInterrupt` and returns the collected events, so the outer except is defensive.
- After the tail ends, calls `generate_report` → `print_report` → `save_report` and prints the path of the saved JSON.

**`install_hook_cmd()`** — `vizhi install-hook`. Loads settings, installs the hook, prints a clear "already installed" warning if it was already there, otherwise writes the file and prints success.

**`uninstall_hook_cmd()`** — `vizhi uninstall-hook`. Loads settings, removes the hook, prints "not found" warning if no removal happened, otherwise writes the file and prints success. Handles a missing `settings.json` gracefully (clean no-op).

**`_latest_report_path(output_dir: str) -> Path | None`** — private. Returns the most-recently-modified `session_*.json` in `output_dir`, or `None`.

**`_load_report(path: Path) -> SessionReport`** — private. Deserialises a saved JSON report back into a `SessionReport`. Walks the `all_events` and `flagged_events` lists, calling `_event_from_dict()` on each.

**`_event_from_dict(d: dict) -> ClassifiedEvent`** — private. Inverse of `_classified_to_dict()` in `reporter.py`. Reconstructs the inner `ActionEvent` (with parsed `datetime` and copied metadata) and wraps it in a `ClassifiedEvent`.

**`_parse_session_uuid(session_id: str) -> uuid.UUID`** — private. Best-effort parse: tries `uuid.UUID(session_id)`; on `ValueError`, returns a fresh `uuid.uuid4()`. This lets a JSONL session ID that *is* a UUID flow through to the report, while non-UUID IDs from custom agents still produce a valid report.

### Connections

- **Imported by:** Nothing (it is the entry point). `pyproject.toml`'s console-script binding `vizhi = "vizhi.cli:main"` is the only "import" — handled by `pip` at install time.
- **Imports:** `vizhi/__init__.py` (`__version__`), `vizhi/classifier.py` (`ClassifiedEvent`), `vizhi/hook_receiver.py` (`receive`), `vizhi/installer.py` (all five public functions), `vizhi/parser.py` (`ActionEvent`), `vizhi/reporter.py` (`SessionReport`, `generate_report`, `print_report`, `save_report`), `vizhi/session_viewer.py` (`find_latest_session`, `tail_session`), `vizhi/watcher.py` (`watch`), plus `click` and `rich.console`.

---

## `hook_receiver.py`

### Simple Explanation

`hook_receiver.py` is the bridge that lets Claude Code itself feed events into Vizhi. Whenever Claude Code finishes running a tool — a Bash command, a file read, a web fetch — its hook system runs `python -m vizhi.hook_receiver`. That subprocess reads one JSON payload from standard input describing what just happened, asks the classifier how risky it was, and appends one line to a session log file. Because Claude Code waits for the hook to finish, any crash here would freeze the agent — so the receiver swallows every error and always exits cleanly. It is the *eye* in "வீழி".

### Technical Explanation

`hook_receiver.py` is the v2 ingestion entry point. It is invoked by Claude Code's `PostToolUse` hook with a JSON payload on stdin (see `installer.py`'s schema documentation). The receiver:

1. Reads stdin into a string. Empty stdin is logged to stderr and returns `0`.
2. Parses JSON. Malformed JSON is logged and returns `0`.
3. Validates that the payload is a dict and contains `toolName` and `sessionId`. Missing fields → logged + `0`.
4. Maps the tool name to a vizhi `ActionType` via `TOOL_TO_ACTION_TYPE`. Unknown tools fall back to `"unknown"`.
5. Builds a `raw_text` string from `toolInput` using `_build_raw_text()`. The format mirrors what the v1 watcher would see in stdin (e.g. `"Read(/etc/passwd)"`, `"WebFetch(https://...)"`, or the raw Bash command).
6. Parses the timestamp with `_parse_timestamp()` (falls back to `now(UTC)` on parse failure).
7. Builds an `ActionEvent`, classifies it with `classify_event()`, and appends one JSON line to `session_<sessionId>.jsonl` under the output directory.
8. Prints one summary line to stderr (`[vizhi hook] <risk_level> <toolName> → <path>`) so the user running Claude Code can see Vizhi reacting in real time.

The receiver follows the v2.1 contract verbatim: **"never block the agent."** Every recoverable failure path logs to stderr via `_warn()` and returns `0`. The only way the receiver can crash is an unrecoverable filesystem error (e.g. permission denied on the output directory), which still surfaces as a non-zero exit but should not propagate to the agent in practice because Claude Code runs the hook in a subprocess.

### Functions & Classes

**Constants**
- `DEFAULT_OUTPUT_DIR: str = "./vizhi_reports"` — fallback when no explicit dir is passed.
- `TOOL_TO_ACTION_TYPE: dict[str, ActionType]` — maps Claude Code tool names (`"Bash"`, `"Shell"`, `"Read"`, `"Write"`, `"Edit"`, `"MultiEdit"`, `"WebFetch"`, `"WebSearch"`) to vizhi `ActionType` values. Unmapped tools fall to `"unknown"`.
- `FILE_PATH_TOOLS: frozenset[str]` — the subset whose `toolInput` carries a `file_path` field.

**`receive(source: IO[str] | None = None, output_dir: str = DEFAULT_OUTPUT_DIR) -> int`**
- The main entry point. Returns the intended process exit code (always `0` on handled errors).
- Optional `source` lets tests pass an in-memory `StringIO`.
- Robust to missing optional fields: `cwd`, `timestamp`, and `toolInput` are all optional; only `toolName` and `sessionId` are required.

**`_build_raw_text(tool_name: str, tool_input: dict[str, Any]) -> str`**
- Bash/Shell → returns the raw `command` string if present.
- Read/Write/Edit/MultiEdit → returns `"<ToolName>(<file_path>)"`.
- WebFetch → `"WebFetch(<url>)"`. WebSearch → `"WebSearch(<query>)"`.
- Unknown / unmapped tools → JSON-serialises the entire `tool_input`, truncated at 500 characters, prefixed with the tool name.
- The output is the string the classifier sees, so the format chosen here is what feeds risk detection.

**`_parse_timestamp(raw: object) -> datetime`**
- Tries `datetime.fromisoformat(raw.replace("Z", "+00:00"))` to handle both `Z` and `+00:00` suffixes.
- Falls back to `datetime.now(timezone.utc)` on any failure.
- Always returns a timezone-aware datetime.

**`_append_to_session_log(classified: ClassifiedEvent, session_id: str, output_dir: str) -> Path`**
- Creates `output_dir` if missing.
- Sanitises the session ID with `_sanitize_session_id()` so a malicious or odd ID can't traverse out of the output directory.
- Opens the file in append-text mode and writes one `json.dumps(record) + "\n"` line.
- Returns the `Path` of the file written for use in the stderr summary.

**`_sanitize_session_id(session_id: str) -> str`**
- Keeps only `[A-Za-z0-9_-]`. Strips everything else (including path separators).
- Returns `"unknown"` if nothing survives.

**`_get_field(payload: dict, *names) -> Any`**
- Returns the first non-`None` value among the listed keys. Used to accept both `toolName` and `tool_name` styles.

**`_warn(msg: str) -> None`** — prints to stderr with a `[vizhi hook warning]` prefix.

### Connections

- **Imported by:** `vizhi/cli.py` (`receive` re-exported as `hook_receive` for the `vizhi hook` subcommand). The PostToolUse hook itself does not import from anywhere — Claude Code spawns the process directly with `python -m vizhi.hook_receiver`.
- **Imports:** `vizhi/classifier.py` (`ClassifiedEvent`, `classify_event`), `vizhi/parser.py` (`ActionEvent`, `ActionType`); standard library `json`, `sys`, `datetime`, `pathlib`, `typing`.

---

## `installer.py`

### Simple Explanation

`installer.py` is what lets Vizhi plug itself into Claude Code without the user having to hand-edit any JSON. When you run `vizhi install-hook`, this module finds Claude Code's settings file (`~/.claude/settings.json`), adds a small "every time you finish a tool, run vizhi" instruction to it, and saves it back. Running `vizhi uninstall-hook` cleanly removes exactly that instruction and nothing else, even if you've added other hooks of your own. The installer is deliberately surgical — it never overwrites the rest of your settings.

### Technical Explanation

`installer.py` owns all interaction with `~/.claude/settings.json`. It exposes a small, deliberately functional API — no class, no module-level state, every operation pure-ish (only `save_settings()` mutates the filesystem; everything else takes a `dict`, returns a `dict`).

The hook entry that gets written conforms to Claude Code's settings schema:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "python -m vizhi.hook_receiver" }
        ]
      }
    ]
  }
}
```

The four constants — `HOOK_EVENT`, `HOOK_MATCHER`, `HOOK_TYPE`, `HOOK_COMMAND` — are the single source of truth for what counts as "vizhi's hook." `_is_vizhi_hook()` and `_vizhi_hook_present()` use `HOOK_COMMAND` for identity, so as long as the command string matches, install and uninstall are guaranteed to agree.

Both install and uninstall are *idempotent*:

- `install_hook()` returns `(settings, True)` if the entry was already there and makes no changes.
- `uninstall_hook()` returns `(settings, False)` if nothing was found to remove.

Uninstall performs **cascade pruning**: an inner `hooks` list becomes empty → drop the surrounding matcher entry; the `PostToolUse` array becomes empty → drop the event key; the top-level `hooks` block becomes empty → drop it entirely. The goal is that "install then uninstall" produces a settings file byte-identical to the original (assuming JSON key ordering matches, which `json.dumps` preserves in Python 3.7+).

Defensive `isinstance(..., dict)` / `isinstance(..., list)` checks throughout mean that if a user has hand-edited their settings to an unexpected shape, the installer raises `ValueError` rather than silently overwriting it. The CLI catches `ValueError` and surfaces a clear "fix or remove the file, then retry" message.

### Functions & Classes

**Constants**
- `HOOK_EVENT: str = "PostToolUse"`
- `HOOK_MATCHER: str = "*"` — matches every tool.
- `HOOK_TYPE: str = "command"`
- `HOOK_COMMAND: str = "python -m vizhi.hook_receiver"` — the canonical command string. Identity for install/uninstall is on this exact value.

**`get_settings_path() -> Path`**
- Returns `Path.home() / ".claude" / "settings.json"`. Resolves the user's home directory cross-platform (`%USERPROFILE%` on Windows, `$HOME` on POSIX).

**`load_settings(path: Path) -> dict[str, Any]`**
- Returns `{}` if the file does not exist or is empty/whitespace-only.
- Raises `json.JSONDecodeError` if the file is non-JSON (callers handle this).
- Raises `ValueError` if the file is JSON but not an object (so we never overwrite a list/scalar settings file).

**`save_settings(path: Path, settings: dict[str, Any]) -> None`**
- Creates the parent directory if missing (`parents=True, exist_ok=True`).
- Writes `json.dumps(settings, indent=2, ensure_ascii=False) + "\n"` — 2-space indent, no ASCII escaping (preserves Unicode glyphs verbatim — useful for users with non-Latin paths), trailing newline (git/editor-friendly).

**`install_hook(settings: dict[str, Any]) -> tuple[dict[str, Any], bool]`**
- Uses `setdefault("hooks", {}).setdefault("PostToolUse", [])` so existing structure is preserved.
- Calls `_vizhi_hook_present()` to detect idempotent re-install.
- If not present, appends `_vizhi_matcher_entry()` to the PostToolUse list.
- Returns `(updated_settings, was_already_installed)`.

**`uninstall_hook(settings: dict[str, Any]) -> tuple[dict[str, Any], bool]`**
- Walks each matcher entry under `PostToolUse`, filters out any inner hook whose command equals `HOOK_COMMAND`.
- Empty matcher entries (`hooks: []` after filtering) are dropped entirely.
- An empty `PostToolUse` list is dropped from `hooks`.
- An empty `hooks` block is dropped from `settings`.
- Returns `(updated_settings, was_removed)`.

**`_vizhi_matcher_entry() -> dict[str, Any]`** — builds a fresh `{matcher: "*", hooks: [{type: "command", command: HOOK_COMMAND}]}` dict.

**`_vizhi_hook_present(post_tool_use: list[Any]) -> bool`** — true iff some matcher entry contains a hook whose command equals `HOOK_COMMAND`.

**`_is_vizhi_hook(entry: Any) -> bool`** — returns `True` iff `entry` is a dict with `command == HOOK_COMMAND`. Defensive against non-dict entries.

### Connections

- **Imported by:** `vizhi/cli.py` (for `get_settings_path`, `install_hook`, `load_settings`, `save_settings`, `uninstall_hook`).
- **Imports:** Standard library only — `json`, `pathlib`, `typing`. No third-party dependencies.

---

## `session_viewer.py`

### Simple Explanation

`session_viewer.py` is the live tail. While Claude Code runs in one terminal window with the hook installed, you open another window and run `vizhi watch`. This module finds the right session log file, prints any events that already happened, and then sits and watches the file like `tail -f`. Every time the hook writes a new line, the viewer reads it within a fifth of a second, decodes the JSON, and prints a colour-coded row — same look as the v1 stdin watcher. When you press Ctrl+C, it hands the collected events to the reporter so you get a full session report.

### Technical Explanation

`session_viewer.py` implements a poll-based JSONL tailer. Polling was chosen over a native file-system-event watcher (`watchdog`, `inotify`, `FSEvents`, `ReadDirectoryChangesW`) for three reasons:

1. **Zero new dependencies.** Vizhi's runtime deps are exactly `rich` and `click`; adding `watchdog` would triple the wheel size and bring in platform-specific compiled code.
2. **Cross-platform parity.** Polling behaves identically on Windows, macOS, and Linux. Native watchers diverge in subtle ways (e.g. Windows' `ReadDirectoryChangesW` does not always fire on appends through Python's buffered I/O).
3. **Acceptable latency.** A `POLL_INTERVAL_SECONDS = 0.2` cadence is below human perception for "live" — the user sees events appear effectively instantly.

The tailer is robust to *partial writes*. If `_drain()` reads a line that doesn't end in `\n`, it `seek()`s back to the start of that partial line and returns; the next poll will re-read it once the hook receiver flushes the trailing newline. This avoids the failure mode where a half-written JSON object crashes `json.loads()`.

The viewer also tolerates a file that does not exist yet: `_wait_for_file()` polls for up to `FILE_WAIT_SECONDS = 3.0` seconds before raising `FileNotFoundError` with a clear, actionable message that the CLI surfaces verbatim.

`tail_session()` catches `KeyboardInterrupt` internally and returns the collected events, so the CLI's outer `try/except KeyboardInterrupt` is a belt-and-suspenders defensive layer (it would only fire if Ctrl+C arrived before `tail_session()` began).

### Functions & Classes

**Constants**
- `POLL_INTERVAL_SECONDS: float = 0.2` — sleep between polls.
- `FILE_WAIT_SECONDS: float = 3.0` — how long to wait for the session file to appear before giving up.

**`find_latest_session(output_dir: str) -> str | None`**
- Globs `session_*.jsonl` under `output_dir`, sorts by `mtime` descending, returns the session ID extracted from the newest filename.
- Returns `None` if the directory does not exist or contains no matching files.
- The session ID is the substring between `session_` and `.jsonl` — preserves whatever ID the hook receiver wrote (typically Claude Code's UUID session ID).

**`tail_session(session_id: str, output_dir: str, console: Console) -> list[ClassifiedEvent]`**
- Computes the file path, calls `_wait_for_file()` (raises `FileNotFoundError` on timeout).
- Opens the file in text-read mode and calls `_drain()` once to consume pre-existing lines.
- Enters an infinite polling loop: each iteration calls `_drain()`; if zero lines were consumed, sleeps for `POLL_INTERVAL_SECONDS`.
- `KeyboardInterrupt` is caught inside the loop and the function returns the accumulated `events` list — the report can be generated from whatever was seen so far, including across the polling boundary.
- Returns `list[ClassifiedEvent]`.

**`_wait_for_file(path: Path, timeout_seconds: float) -> None`**
- Polls `path.exists()` every `POLL_INTERVAL_SECONDS`.
- Raises `FileNotFoundError` with a multi-line, user-facing message when the deadline passes.

**`_drain(f: IO[str], events: list[ClassifiedEvent], console: Console) -> int`**
- Reads all currently available *complete* lines from the file handle.
- A line is considered complete only when it ends in `\n`. Partial lines are seeked-back and left for the next call. Returns the number of lines consumed.
- Blank lines are skipped silently.
- Malformed JSON (`json.JSONDecodeError`), missing required keys (`KeyError`), or schema violations (`ValueError`) are logged as a dim red `[vizhi watch] skipping malformed line: <exc>` and the line is dropped — the tailer never crashes mid-stream.

**`_event_from_line(raw: str) -> ClassifiedEvent`**
- Parses one JSON line and rebuilds a `ClassifiedEvent`.
- Validates that the parsed JSON is an object; otherwise raises `ValueError`.
- Mirrors the schema written by `hook_receiver._append_to_session_log()`.

### Connections

- **Imported by:** `vizhi/cli.py` (`find_latest_session`, `tail_session` for the `vizhi watch` command).
- **Imports:** `vizhi/classifier.py` (`ClassifiedEvent`), `vizhi/parser.py` (`ActionEvent`), `vizhi/watcher.py` (`render_event` — shares the v1 row format); plus `rich.console`, standard library `json`, `time`, `datetime`, `pathlib`, `typing`.
