# Code Explained

This document describes every file, class, function, and module-level constant in the `vizhi/` Python package. Files are presented in dependency order: a file only depends on files listed above it. Read top-to-bottom and you will never encounter a symbol that has not yet been described.

For each function we cover: the exact signature with every type hint, what each parameter means in plain English, what the return value looks like, every edge case the function handles, why the function exists (what breaks without it), any non-obvious behavior, a concrete in/out example, and which other functions in the codebase call this function or are called by it.

For each class or dataclass we cover: every field with its type and purpose, why it is a dataclass rather than a regular class, why `frozen=True` is used where it is, and where instances are constructed.

For each module-level constant we cover: what it stores, why its container type was chosen (tuple, frozenset, dict, …), and where it is read.

---

## `__init__.py`

### Simple Explanation
The package entry point. When something else writes `import vizhi`, Python runs this file. It does nothing except declare a one-line docstring and pin the package's version number.

### Technical Explanation
A minimal Python package marker. The presence of this file (even empty) is what tells Python that the `vizhi/` directory is an importable package. Holding the `__version__` string here is a long-standing Python convention (PEP 396, since deprecated but still ubiquitous in tools that introspect packages) so that callers can do `import vizhi; print(vizhi.__version__)` without needing to consult `pyproject.toml` at runtime.

### Functions & Classes
None. The file contains a module docstring and one assignment.

### Module-Level Constants

#### `__version__`
- **Stored value:** the string `"0.1.0"`.
- **Type:** `str` (chosen because all Python package metadata standards — pip, setuptools, importlib.metadata — expect version numbers as strings, not tuples).
- **Why it exists:** allows runtime version introspection (`vizhi.__version__`), and `cli.py` passes it to Click's `@click.version_option(__version__, prog_name="vizhi")` so that `vizhi --version` prints the right number. If removed, `cli.py` would fail at import time with `ImportError: cannot import name '__version__' from 'vizhi'`.
- **Where used:** `cli.py` (`from vizhi import __version__`).

### Connections
- **Imported by:** `cli.py`.
- **Imports:** nothing.

---

## `parser.py`

### Simple Explanation
Takes a single line of text (typically a line of terminal output from an AI agent) and turns it into a structured object that the rest of the system can reason about. The structured object captures three things: when the line arrived, what the raw text was, and a rough guess at what kind of activity it represents (a shell command, a file access, a network call, or something it doesn't recognize).

### Technical Explanation
Implements the first stage of the v1 stdin-mode pipeline. It produces an immutable `ActionEvent` dataclass from a raw line via simple keyword matching. The classification is intentionally cheap and lossy — it errs toward the `"unknown"` action type when in doubt, leaving deeper analysis to the risk classifier downstream. The keyword tables are tuples of literal substrings (no regex) so that matching stays predictable, debuggable, and free of catastrophic-backtracking surprises.

### Module-Level Constants

#### `ActionType`
- **Stored value:** a `typing.Literal` type alias equal to `Literal["command", "file_access", "network", "unknown"]`.
- **Why a `Literal`:** restricts the set of legal values at type-check time. If you tried to assign `action_type = "explosion"` to an `ActionEvent`, a static type-checker (mypy, pyright) would flag it. Plain `str` would have allowed any value.
- **Why these four members:** they are the smallest set that covers everything the downstream classifier (`classifier.py`) needs to special-case. The classifier branches on `event.action_type == "network"` to apply host-allowlist logic; it never branches on subtypes of commands or file accesses, so we do not split them further at the parser layer.
- **Where used:** as the `action_type` field on `ActionEvent`, as the return type of `classify()`, and as the value type of `TOOL_TO_ACTION_TYPE` in `hook_receiver.py`.

#### `COMMAND_KEYWORDS`
- **Stored value:** the tuple `("$ ", "> ", "running:", "executing:", "bash(", "shell(", "powershell(", "exec ")`.
- **Why a `tuple[str, ...]`:** the keyword set is fixed at module import time and never mutated. A `tuple` is immutable, hashable, and slightly cheaper than a `list` to iterate; a `set` would be wrong because we need substring containment (`needle in haystack`), not exact membership.
- **What each entry catches:** shell prompts (`"$ "`, `"> "`), agent-emitted prefixes that announce shell execution (`"running:"`, `"executing:"`), and tool-call signatures that Claude Code (or other agents) might print verbatim into stdout (`"bash("`, `"shell("`, `"powershell("`, `"exec "`).
- **Where used:** only inside `classify()` in this same file.

#### `FILE_ACCESS_KEYWORDS`
- **Stored value:** the tuple `("read(", "write(", "edit(", "open(", "reading file", "writing file", "editing file", "creating file", "deleting file", "glob(", "grep(")`.
- **Why a `tuple[str, ...]`:** same reasoning as above — fixed at import, used only for substring matching.
- **What each entry catches:** the parenthesized forms catch Claude Code's tool-call serializations and Python-ish trace text; the phrase forms catch agents that narrate what they are doing in prose.
- **Where used:** only inside `classify()`.

#### `NETWORK_KEYWORDS`
- **Stored value:** the tuple `("http://", "https://", "curl ", "wget ", "fetch(", "webfetch(", "websearch(", "request to", "downloading", "uploading")`.
- **Why a `tuple[str, ...]`:** same reasoning.
- **What each entry catches:** URL schemes catch any printed URL; CLI tools (`"curl "`, `"wget "`); Claude Code tool calls (`"fetch("`, `"webfetch("`, `"websearch("`); and prose forms (`"request to"`, `"downloading"`, `"uploading"`).
- **Where used:** only inside `classify()`.

### Functions & Classes

#### `class ActionEvent`
```python
@dataclass(frozen=True)
class ActionEvent:
    timestamp: datetime
    raw_text: str
    action_type: ActionType
    metadata: dict[str, str] = field(default_factory=dict)
```

- **Why a dataclass:** the only purpose of this type is to bundle four related fields and pass them around. A `@dataclass` autogenerates `__init__`, `__repr__`, and `__eq__` from the field declarations, saving roughly 15 lines of mechanical boilerplate per class.
- **Why `frozen=True`:** the parser's contract is that an event, once observed, is immutable history. Setting `frozen=True` makes Python raise `dataclasses.FrozenInstanceError` if anything later in the pipeline tries to mutate a field (`event.raw_text = "..."`). This catches accidental tampering at the moment it happens, instead of producing silently corrupted reports. As a bonus, frozen dataclasses are hashable, so they can be used as dict keys or set members if a future caller wants to deduplicate.

- **Fields:**
  - `timestamp: datetime` — the UTC moment the line was observed. Always timezone-aware (set to `datetime.now(timezone.utc)` in `parse_line()` or to the hook payload's `timestamp` field in `hook_receiver.py`).
  - `raw_text: str` — the original line, stripped of trailing `\r` and `\n` (so it pretty-prints cleanly in the terminal feed) but otherwise unmodified. This is what the risk classifier scans, so any normalization done here propagates downstream.
  - `action_type: ActionType` — one of `"command" | "file_access" | "network" | "unknown"`. Computed by `classify()`.
  - `metadata: dict[str, str] = field(default_factory=dict)` — a free-form bag for source-specific extras. `parse_line()` leaves it empty (`{}`); `hook_receiver.py` populates it with `{"tool_name": ..., "source": "hook", "cwd": ...}`. The `field(default_factory=dict)` idiom is required because using `{}` directly as a dataclass default would share one dict across every instance — a notorious Python footgun.

- **Where instances are created:**
  - `parser.parse_line()` — when reading from stdin (v1 mode).
  - `hook_receiver.receive()` — when receiving a PostToolUse hook payload (v2 mode).
  - `cli._event_from_dict()` and `session_viewer._event_from_line()` — when rehydrating events from disk during report rendering or live tailing.

#### `classify(line: str) -> ActionType`
- **Signature:** `def classify(line: str) -> ActionType`.
- **Parameter `line`:** a single line of raw text. Trailing newlines are tolerated (they do not affect matching because everything is lowercased and matched as substrings).
- **Return:** one of `"command"`, `"file_access"`, `"network"`, or `"unknown"`. Always exactly one of the four — never `None`, never raised.
- **What it does:** lowercases the input once, then checks the three keyword tables in order: `COMMAND_KEYWORDS`, then `FILE_ACCESS_KEYWORDS`, then `NETWORK_KEYWORDS`. First match wins. If none match, returns `"unknown"`.
- **Edge cases:**
  - Empty string: lowercased to `""`, no keyword is a substring of `""`, returns `"unknown"`.
  - Mixed-case input (`"BASH(ls)"`): lowercased before matching so `"bash("` still matches.
  - A line containing both a URL and a shell prompt (e.g. `"$ curl https://x"`): the `COMMAND_KEYWORDS` check runs first, so the line is classified as `"command"`. This is intentional: shell context dominates network context.
- **Why it exists:** every downstream consumer needs to know what kind of action a line represents before it can apply category-specific rules (e.g. the classifier's known-safe-host check only fires for `action_type == "network"`). If removed, every event would have to be re-classified ad hoc inside each consumer.
- **Gotcha:** because matching is substring-based and ordered, adding a future keyword that overlaps an existing one can subtly reorder priorities. For example, adding `"http"` to `COMMAND_KEYWORDS` would steal every URL into the command bucket.
- **Concrete example:**
  - Input: `"$ curl https://api.github.com\n"`
  - Lowercased: `"$ curl https://api.github.com\n"`
  - `"$ "` is in `COMMAND_KEYWORDS`, matches, returns `"command"`.
- **Called by:** `parse_line()` (same file).
- **Calls:** `_contains_any()` (same file).

#### `parse_line(line: str) -> ActionEvent`
- **Signature:** `def parse_line(line: str) -> ActionEvent`.
- **Parameter `line`:** a single raw line of agent output, exactly as read from stdin. May include a trailing `\r\n` or `\n`; both are stripped from the stored `raw_text`.
- **Return:** a freshly constructed `ActionEvent` whose `timestamp` is "right now" (UTC), `raw_text` is the input with trailing newlines stripped, `action_type` is the result of `classify(line)`, and `metadata` is an empty dict.
- **What it does:** the public single-line parsing entry point. Composes `classify()` plus a current-time stamp into one immutable object.
- **Edge cases:**
  - A blank line (`"\n"`) becomes `ActionEvent(raw_text="", action_type="unknown", ...)`. Note: the watcher (`stream_lines`) filters blanks out before they reach `parse_line()`, so in practice the parser never sees them.
  - Trailing `\r\n` (Windows): `rstrip("\r\n")` strips both characters.
  - A line containing internal newlines (e.g. from a `print()` of a multi-line string): only the trailing run is stripped; internal `\n`s survive. This is fine because the matching is case-insensitive substring containment.
- **Why it exists:** the single, canonical conversion from "raw text" to "structured event" in stdin mode. The hook-mode pipeline does not call this function — it builds the `ActionEvent` directly inside `hook_receiver.receive()` because the hook payload is structured JSON, not free text.
- **Concrete example:**
  - Input: `"running: rm -rf /tmp/foo\n"`
  - Output: `ActionEvent(timestamp=<now UTC>, raw_text="running: rm -rf /tmp/foo", action_type="command", metadata={})`.
- **Called by:** `watcher.watch()`.
- **Calls:** `classify()`, `datetime.now(timezone.utc)`, the `ActionEvent` constructor.

#### `_contains_any(haystack: str, needles: tuple[str, ...]) -> bool`
- **Signature:** `def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool`.
- **Parameter `haystack`:** any string (expected to be already lowercased by the caller).
- **Parameter `needles`:** a tuple of literal substring keywords.
- **Return:** `True` if at least one needle is a substring of the haystack, else `False`.
- **What it does:** the standard "is any of these substrings present?" check, expressed via `any(needle in haystack for needle in needles)`. Short-circuits on the first match.
- **Why it exists:** purely a readability extract — keeps `classify()` and the very similar `_contains_any()` inside `classifier.py` looking declarative instead of nested.
- **Why the leading underscore:** Python's convention for "module-private — don't import this from outside." Anyone importing this from another module is signaling they should be doing something else.
- **Concrete example:**
  - `_contains_any("$ ls -la", ("$ ", "> "))` → `True`.
  - `_contains_any("hello world", ("$ ", "> "))` → `False`.
- **Called by:** `classify()` (same file).
- **Calls:** none beyond the builtin `any()`.

### Connections
- **Imports:** `dataclasses.dataclass`, `dataclasses.field`, `datetime.datetime`, `datetime.timezone`, `typing.Literal`, plus `from __future__ import annotations`.
- **Imported by:**
  - `classifier.py` — imports `ActionEvent`.
  - `watcher.py` — imports `parse_line`.
  - `hook_receiver.py` — imports `ActionEvent` and `ActionType`.
  - `cli.py` — imports `ActionEvent` (for rehydration in `_event_from_dict`).
  - `session_viewer.py` — imports `ActionEvent` (for rehydration in `_event_from_line`).

---

## `classifier.py`

### Simple Explanation
Takes a structured `ActionEvent` (the output of the parser, or the output of the hook receiver) and assigns it a risk level — one of `critical`, `high`, `medium`, `low`, or `info` — together with a one-line plain-English explanation of why. It is the heart of Vizhi's security judgment.

### Technical Explanation
A pure, deterministic, side-effect-free rule engine. The pipeline is a strict cascade: it checks the highest severity first (`CRITICAL_PATTERNS`), and the first match wins. If no severe pattern matches, it falls through to category-specific rules: network calls are split into "known-safe host" (low) vs "unknown domain" (medium); file writes and process spawns are medium; file reads are low. Anything else is `info`. The patterns themselves are tuples of `(needle, reason)` pairs so that a single table lookup produces both the verdict and the human-readable justification, eliminating any chance of the two falling out of sync.

### Module-Level Constants

#### `RiskLevel`
- **Stored value:** the `Literal` type alias `Literal["critical", "high", "medium", "low", "info"]`.
- **Why a `Literal`:** same reason as `ActionType` — restricts the set of legal values at type-check time and makes every reader of `risk_level` know the complete value space at a glance.
- **Why exactly these five members:** standard five-tier severity scale used by most SIEM and AppSec tooling, mapped to terminal colors that are easy to scan: bold red, red, yellow, green, dim white.
- **Where used:** as the `risk_level` field on `ClassifiedEvent`, as the return type of `classify_event()`, and as the key type of `RISK_STYLES` and `RISK_LABELS` in `watcher.py` and `RISK_STYLES` in `reporter.py`.

#### `CRITICAL_PATTERNS`
- **Stored value:** a tuple of `(needle, reason)` string pairs covering thirteen specific high-impact patterns: `sudo `, `rm -rf`, `rm -fr`, ` dd `, `dd if=`, `chmod 777`, `chmod -R 777`, `/etc/passwd`, `/etc/shadow`, `~/.ssh`, `/.ssh/`, `mkfs`, and the classic fork-bomb signature `:(){:|:&};:`.
- **Why a `tuple[tuple[str, str], ...]`:** outer tuple because the rule set is fixed at import time and must remain in a defined order (first match wins, so order matters). Inner tuples bind a pattern to its rationale; using a `dict[str, str]` would have lost ordering before Python 3.7 and still reads worse — `(needle, reason)` is the natural shape for "ordered list of (pattern, why)".
- **Why these are critical:** each represents an action whose consequences cannot reasonably be reversed by reading a log after the fact — root escalation, mass deletion, format/dd that wipes physical media, exposure of credential vaults, or a fork-bomb that hangs the host.
- **Where used:** only by `classify_event()` (this file).

#### `HIGH_PATTERNS`
- **Stored value:** a tuple of `(needle, reason)` pairs covering twenty-one patterns: less severe deletes (`rm -r`, `rm -f`, ` rm `, `del /f`, `rmdir /s`), destructive disk/db operations (`format `, `drop table`, `drop database`, `truncate table`), and secret-bearing path/keyword indicators (`.env`, `id_rsa`, `id_ed25519`, `.pem`, `.key`, `credentials`, `secrets/`, `aws_secret`, `api_key`, `password=`, `token=`).
- **Why a `tuple[tuple[str, str], ...]`:** identical reasoning to `CRITICAL_PATTERNS`.
- **Where used:** only by `classify_event()`.

#### `MEDIUM_FILE_WRITE_KEYWORDS`
- **Stored value:** the tuple `("write(", "edit(", "writing file", "editing file", "creating file", "deleting file", " > ", " >> ")`.
- **Why a `tuple[str, ...]`:** medium-tier rules do not need per-pattern reasons (the reason is always the generic `"File write / modification"`), so the simpler keyword-only structure is enough.
- **Why these specifically:** Claude Code tool-call serializations (`"write("`, `"edit("`), prose narration of file mutation, and shell redirection operators (`" > "`, `" >> "`) — the leading and trailing spaces are deliberate so `--graph` or `arg>file` do not false-match.
- **Where used:** only by `classify_event()`.

#### `MEDIUM_PROCESS_KEYWORDS`
- **Stored value:** the tuple `("exec ", "spawn ", "bash(", "shell(", "powershell(", "running:", "executing:")`.
- **Why a `tuple[str, ...]`:** medium-tier reason is fixed (`"New process execution"`), so the keyword-only shape suffices.
- **Why these specifically:** these are the same patterns the parser's `COMMAND_KEYWORDS` uses. They reappear here because a line can pass the parser as `action_type == "command"` and still need a risk assignment if it does not match any critical/high pattern — at that point a generic "new process" verdict is appropriate.
- **Where used:** only by `classify_event()`.

#### `KNOWN_SAFE_HOSTS`
- **Stored value:** the tuple `("github.com", "raw.githubusercontent.com", "pypi.org", "files.pythonhosted.org", "registry.npmjs.org", "nodejs.org", "python.org", "docs.python.org", "localhost", "127.0.0.1", "::1")`.
- **Why a `tuple[str, ...]`:** fixed allowlist used only for substring matching against a single haystack — `tuple` is the right immutable, sequence-preserving container.
- **Why these hosts:** they are the common, low-risk targets of dev/CI traffic — package registries, language download mirrors, GitHub, and loopback addresses (IPv4 `127.0.0.1` and IPv6 `::1`).
- **Where used:** only by `classify_event()` inside the network branch.

#### `LOW_FILE_READ_KEYWORDS`
- **Stored value:** the tuple `("read(", "reading file", "glob(", "grep(", "open(")`.
- **Why a `tuple[str, ...]`:** low-tier rules also have a fixed reason (`"File read"`).
- **Where used:** only by `classify_event()`.

### Functions & Classes

#### `class ClassifiedEvent`
```python
@dataclass(frozen=True)
class ClassifiedEvent:
    event: ActionEvent
    risk_level: RiskLevel
    reason: str
```

- **Why a dataclass:** it is, again, a pure data bundle (an inner event plus two annotations). The autogenerated `__init__`, `__repr__`, `__eq__` are exactly what we need; nothing custom would belong on this class.
- **Why `frozen=True`:** once the classifier issues a verdict, downstream code (the watcher, the reporter, the live tailer) reads it but must never mutate it. Freezing the dataclass enforces this at runtime and gives us hashable instances for free.
- **Why composition (`event: ActionEvent`) rather than inheritance:** the `ActionEvent` is a fact about the world; the `ClassifiedEvent` is an opinion layered on top. Composition keeps the opinion separable from the fact — you can serialize one without the other, you can swap classifiers without changing the parser, and the type signatures make it obvious which layer a function lives at.

- **Fields:**
  - `event: ActionEvent` — the underlying parsed event being classified. Carries the timestamp, raw text, action type, and any metadata the source attached.
  - `risk_level: RiskLevel` — the chosen severity label.
  - `reason: str` — a short, human-readable phrase explaining the verdict. Either copied from the matched `(needle, reason)` pair in `CRITICAL_PATTERNS`/`HIGH_PATTERNS`, or a fixed generic string for the medium/low/info branches.

- **Where instances are created:**
  - `classifier.classify_event()` — the only place new instances are minted from a live `ActionEvent`.
  - `cli._event_from_dict()` and `session_viewer._event_from_line()` — when rehydrating events from JSON / JSONL on disk.

#### `classify_event(event: ActionEvent) -> ClassifiedEvent`
- **Signature:** `def classify_event(event: ActionEvent) -> ClassifiedEvent`.
- **Parameter `event`:** any `ActionEvent`. The function reads `event.raw_text` (case-insensitively) and `event.action_type`; it does not consult timestamps or metadata.
- **Return:** a `ClassifiedEvent` wrapping the input plus a `risk_level` and `reason`. Always returns a valid object — never `None`, never raises.
- **What it does:** runs the cascade described in the module-level Technical Explanation above. Pseudocode of the priority order:
  1. If any `CRITICAL_PATTERNS` needle is in the lowercased `raw_text` → `critical`, reason from the matched pair.
  2. Else if any `HIGH_PATTERNS` needle matches → `high`, reason from the matched pair.
  3. Else if `event.action_type == "network"` → `low` if any `KNOWN_SAFE_HOSTS` substring is present, otherwise `medium`.
  4. Else if any `MEDIUM_FILE_WRITE_KEYWORDS` needle matches → `medium`, reason `"File write / modification"`.
  5. Else if any `MEDIUM_PROCESS_KEYWORDS` needle matches → `medium`, reason `"New process execution"`.
  6. Else if any `LOW_FILE_READ_KEYWORDS` needle matches → `low`, reason `"File read"`.
  7. Else → `info`, reason `"No risk indicators matched"`.
- **Edge cases:**
  - Empty `raw_text`: cascades through every branch and returns `info`.
  - Both a critical and a high pattern present in one line: critical wins (first cascade check).
  - A network call to `https://github.com/evil-org` containing `.env` in its path: the cascade checks `HIGH_PATTERNS` (which contains `".env"`) before the network branch, so this is flagged `high`, not `low`. This is intentional — secret-shaped paths dominate host reputation.
  - An action with `action_type == "command"` whose text is just `"ls"`: no critical, no high, no network, no write keyword, no process keyword (the bare command does not contain `"exec "`, `"bash("`, etc.), no read keyword → `info`. The classifier deliberately does not raise an alarm on neutral commands.
- **Why it exists:** the entire purpose of the package. Removing it would leave Vizhi with no opinion about what is risky and what is not, reducing the tool to a colorful `tee`.
- **Gotchas:**
  - Substring matching is intentionally loose. A line like `"# rm -rf was discussed yesterday"` would be flagged `critical`. The TODO at the top of the file (`# TODO(v2.0): replace substring matching with proper tokenized command parsing`) tracks this.
  - The order of patterns inside each tuple matters because the first match wins. Reordering `CRITICAL_PATTERNS` could change which reason string appears on a line that matches multiple needles.
- **Concrete example:**
  - Input: `ActionEvent(raw_text="sudo rm -rf /tmp", action_type="command", ...)`.
  - Lowercased text: `"sudo rm -rf /tmp"`.
  - First critical pattern checked is `("sudo ", "Privileged command (sudo) — full root access")`. `"sudo "` is in the text → match.
  - Output: `ClassifiedEvent(event=<input>, risk_level="critical", reason="Privileged command (sudo) — full root access")`.
- **Called by:** `watcher.watch()` (stdin mode), `hook_receiver.receive()` (hook mode).
- **Calls:** `_first_match()`, `_contains_any()`.

#### `_first_match(haystack: str, patterns: tuple[tuple[str, str], ...]) -> str | None`
- **Signature:** `def _first_match(haystack: str, patterns: tuple[tuple[str, str], ...]) -> str | None`.
- **Parameter `haystack`:** any lowercased string (the caller is responsible for lowercasing).
- **Parameter `patterns`:** an ordered tuple of `(needle, reason)` pairs. Order matters — the first pair whose needle is a substring of the haystack wins.
- **Return:** the `reason` string of the matching pair, or `None` if none match.
- **What it does:** linear scan over the pairs, short-circuits on the first hit. Returning the `reason` directly (rather than the pair) lets the caller write `if hit is not None: return ClassifiedEvent(..., reason=hit)` without unpacking.
- **Why it exists:** factors out the "search for the first matching `(needle, reason)` pair" logic so the cascade in `classify_event()` reads as two clean calls instead of two duplicated explicit loops.
- **Concrete example:**
  - `_first_match("ssh into /etc/shadow", CRITICAL_PATTERNS)` → `"Access to system shadow (hashed passwords) file"`.
  - `_first_match("hello world", CRITICAL_PATTERNS)` → `None`.
- **Called by:** `classify_event()` (same file).
- **Calls:** none beyond a simple for-loop.

#### `_contains_any(haystack: str, needles: tuple[str, ...]) -> bool`
- **Signature:** identical to the one in `parser.py`.
- **Return:** `True` if any needle is a substring of the haystack, else `False`.
- **Why duplicated rather than imported:** the helper is small (one line) and lives in two distinct modules with overlapping but not identical responsibilities. Duplication avoids cross-module dependency for a trivial utility and keeps each module self-contained.
- **Called by:** `classify_event()` (same file).
- **Calls:** the builtin `any()`.

### Connections
- **Imports:** `dataclasses.dataclass`, `typing.Literal`, `vizhi.parser.ActionEvent`, plus `from __future__ import annotations`.
- **Imported by:**
  - `watcher.py` — imports `ClassifiedEvent`, `RiskLevel`, `classify_event`.
  - `reporter.py` — imports `ClassifiedEvent`, `RiskLevel`.
  - `cli.py` — imports `ClassifiedEvent`.
  - `hook_receiver.py` — imports `ClassifiedEvent`, `classify_event`.
  - `session_viewer.py` — imports `ClassifiedEvent`.

---

## `watcher.py`

### Simple Explanation
Reads agent output line-by-line from standard input, runs each line through the parser and classifier as it arrives, prints a color-coded live feed to the terminal, and writes a session report when the input stream ends or the user presses `Ctrl+C`. This is the v1 mode of Vizhi — used by `vizhi start` and by `cat session.log | vizhi start`-style pipelines.

### Technical Explanation
Implements the original stdin-driven monitoring loop. It is a thin orchestration layer wrapping `parser.parse_line()`, `classifier.classify_event()`, and `reporter.generate_report()` / `print_report()` / `save_report()`. The loop yields line-by-line from a configurable source (defaulting to `sys.stdin`), classifies each line, appends the verdict to an in-memory list, and renders it via Rich. On EOF or `KeyboardInterrupt` it hands the accumulated list to the reporter for summary printing and JSON persistence. Two module-level dictionaries — `RISK_STYLES` and `RISK_LABELS` — drive the terminal styling.

### Module-Level Constants

#### `RISK_STYLES`
- **Stored value:** the dict `{"critical": "bold red", "high": "red", "medium": "yellow", "low": "green", "info": "dim white"}`.
- **Why a `dict[RiskLevel, str]`:** O(1) lookup keyed by the typed `RiskLevel` value. The `Literal` keys mean a typo (`"hgh"`) is a type error.
- **Why these styles:** they are Rich's color tokens for the standard severity ladder used by most CLI security tools. Bold red for critical demands attention; dim white for info recedes into the background.
- **Where used:** `render_event()` (this file) — looks up the style for the current event's `risk_level`. Note: `reporter.py` declares its own `RISK_STYLES` constant rather than importing this one, to keep the two modules decoupled.

#### `RISK_LABELS`
- **Stored value:** the dict `{"critical": "CRIT", "high": "HIGH", "medium": " MED", "low": " LOW", "info": "INFO"}`.
- **Why a `dict[RiskLevel, str]`:** O(1) lookup; the typed `RiskLevel` key catches typos.
- **Why padded to four characters:** so each rendered line's risk badge takes the same horizontal space, making the live feed visually align even when severities mix. `MED` and `LOW` get a leading space to match the four-character width.
- **Where used:** `render_event()` (this file).

### Functions & Classes

#### `stream_lines(source: IO[str]) -> Iterator[str]`
- **Signature:** `def stream_lines(source: IO[str]) -> Iterator[str]`.
- **Parameter `source`:** any text I/O object that supports `.readline()` (real stdin, an open file, a `StringIO`).
- **Return:** a generator that yields lines (still terminated by `\n`) one at a time. Blank lines are filtered out.
- **What it does:** wraps the standard `iter(source.readline, "")` idiom. `readline()` returns `""` on EOF (and only on EOF — a blank line returns `"\n"`), so `iter(callable, sentinel)` produces a clean generator that exits when the stream closes. The `if line.strip(): yield line` filter drops blank lines without consuming them in the parser.
- **Edge cases:**
  - Closed pipe / EOF: `readline()` returns `""`, the iterator stops, the generator ends, the for-loop in `watch()` exits normally.
  - A line containing only whitespace (`"   \n"`): `line.strip()` is `""` (falsy), the line is skipped.
  - A very long line (no `\n` for a long time): blocked until either the line is complete or the source closes — this is just `readline()`'s contract.
- **Why it exists:** decouples the producer (whatever the watcher is reading from) from the consumer (the parse/classify/render loop). The same loop works for stdin, a captured log file via `cat`, or a test `StringIO`.
- **Concrete example:**
  - `source` is a `StringIO("ls\n\n$ pwd\n")`.
  - First iteration yields `"ls\n"`; second iteration skips `"\n"` (blank); third yields `"$ pwd\n"`; fourth ends the iterator.
- **Called by:** `watch()` (same file).
- **Calls:** `iter()`, `source.readline()`.

#### `render_event(console: Console, classified: ClassifiedEvent) -> None`
- **Signature:** `def render_event(console: Console, classified: ClassifiedEvent) -> None`.
- **Parameter `console`:** a Rich `Console` instance used as the print target. Passed in so the live tailer (`session_viewer.py`) can share a console with the rest of the CLI.
- **Parameter `classified`:** the event to render. The function reads its timestamp, action type, raw text, risk level, and reason.
- **Return:** `None`. The function's effect is the printed line.
- **What it does:** builds a Rich `Text` object with five styled segments, then prints it:
  1. `[HH:MM:SS]` in dim style (timestamp).
  2. `CRIT|HIGH| MED| LOW|INFO ` in the risk-level style (the badge).
  3. `(action_type) ` in dim cyan.
  4. The raw text in the risk-level style.
  5. `  — <reason>` in dim style.
- **Edge cases:**
  - A raw text containing markup characters (e.g. `[red]hi[/]`): Rich would normally interpret these. They are passed as a plain text argument to `Text.append()`, which treats them literally — no injection risk.
  - A very long raw text: Rich wraps it according to the console width.
- **Why it exists:** the single canonical way to render one event line. Shared by the v1 watcher (`watch()` calls it on every classified event) and the v2 live tailer (`session_viewer._drain()` calls it for every line it reads from the JSONL log). Centralizing it guarantees both modes produce visually identical feeds.
- **Concrete example:**
  - Input: a `ClassifiedEvent` with `raw_text="sudo rm -rf /"`, `risk_level="critical"`, `reason="Privileged command (sudo) — full root access"`.
  - Output (rendered to a Rich console):
    ```
    [12:07:00] CRIT (command) sudo rm -rf /  — Privileged command (sudo) — full root access
    ```
    with the badge, raw text, and reason colored bold red.
- **Called by:** `watch()` (same file), `session_viewer._drain()` (cross-file).
- **Calls:** `RISK_STYLES.__getitem__`, `RISK_LABELS.__getitem__`, `event.timestamp.strftime`, `Text()`, `Text.append()`, `console.print()`.

#### `watch(source: IO[str] | None = None, console: Console | None = None, output_dir: str = "./vizhi_reports") -> None`
- **Signature:** `def watch(source: IO[str] | None = None, console: Console | None = None, output_dir: str = "./vizhi_reports") -> None`.
- **Parameter `source`:** the input stream to read lines from. `None` means "use `sys.stdin`" — the canonical CLI use. Tests pass a `StringIO`.
- **Parameter `console`:** the Rich console to print to. `None` means "construct a fresh `Console()`" — fine for the CLI, but tests can inject a mock to capture output.
- **Parameter `output_dir`:** the directory the final JSON report is written into. Defaults to `./vizhi_reports`. Created if missing (by `save_report()`).
- **Return:** `None`. Side effects: prints to the console, writes one JSON file at session end.
- **What it does, in order:**
  1. Generates a fresh session UUID (`uuid.uuid4()`).
  2. Captures `started_at = datetime.now(timezone.utc)`.
  3. Prints a "Vizhi watcher started" banner with the session ID.
  4. Iterates over `stream_lines(source)`, calling `parse_line()` then `classify_event()` then `render_event()` on each. Each classified event is appended to a local `events` list.
  5. On `KeyboardInterrupt` (Ctrl+C), prints a "stopped" banner and falls through.
  6. In a `finally` block, calls `_finalize_session()` which builds the report, prints it, and writes the JSON file.
- **Edge cases:**
  - Stream closes immediately (empty input): the for-loop iterates zero times, `events` stays empty, `_finalize_session()` still runs and produces a report whose `total_actions=0`, `risk_breakdown` is all zeros, `flagged_events=[]`. The "no critical or high-risk events" message is printed.
  - User Ctrl+Cs mid-stream: every event observed before the interrupt is preserved (the list is built incrementally, not at the end), so the report is partial but complete-up-to-the-interrupt.
  - Any exception other than `KeyboardInterrupt` inside the loop: would propagate out of the function, but the `finally` block still runs `_finalize_session()` so no work is lost. The exception then surfaces to the CLI layer.
- **Why it exists:** v1 mode's main loop. Without it the stdin-piping workflow (`vizhi start`, `cat log | vizhi start`) does not exist.
- **Gotchas:**
  - `Console()` constructed without arguments uses Rich's autodetection — it may disable colors when not attached to a TTY (e.g. when output is itself being piped). The CLI does not override this.
  - The `events` list lives in memory for the entire session. For very long sessions this is unbounded growth, but is acceptable for the alpha; a v2.5+ implementation could roll over to disk.
- **Concrete example:**
  - `echo '$ ls' | vizhi start` runs `watch()` with `source=sys.stdin`. One line is observed, parsed (`action_type="command"`), classified (`info`, no risky pattern), rendered (`[HH:MM:SS] INFO (command) $ ls  — No risk indicators matched`), and the report is generated and saved to `./vizhi_reports/session_<uuid>_<ts>.json`.
- **Called by:** `cli.start_cmd()` (with default args).
- **Calls:** `uuid.uuid4`, `datetime.now`, `console.print`, `stream_lines`, `parse_line`, `classify_event`, `render_event`, `_finalize_session`.

#### `_finalize_session(*, console: Console, events: list[ClassifiedEvent], session_id: uuid.UUID, started_at: datetime, output_dir: str) -> None`
- **Signature:** keyword-only args, return `None`.
- **Parameter `console`:** the Rich console (already used by the live feed) on which to print the final report.
- **Parameter `events`:** the accumulated classified events from the session.
- **Parameter `session_id`:** the UUID generated at session start. Threaded through so the report and the live banner agree.
- **Parameter `started_at`:** the timestamp captured at session start.
- **Parameter `output_dir`:** where to write the JSON file.
- **Return:** `None`. Side effects: terminal print + JSON write.
- **What it does:** calls `generate_report()` to build the `SessionReport`, then `print_report()` to render it to the console, then `save_report()` to write the JSON file. Prints the resulting file path so the user can find it.
- **Why it exists:** packages the three end-of-session steps into one call so both the normal exit (EOF) and the interrupt path (`except KeyboardInterrupt`) trigger the same finalization. Pulled out as a separate function so `watch()`'s control flow reads cleanly.
- **Why keyword-only args (the leading `*`):** the function has five logically equal parameters and zero natural order. Forcing keyword-call (`_finalize_session(console=..., events=..., session_id=...)`) prevents the common positional bug of passing `events` where `session_id` is expected.
- **Called by:** `watch()` (same file).
- **Calls:** `generate_report`, `print_report`, `save_report`, `console.print`.

### Connections
- **Imports:** `sys`, `uuid`, `datetime.datetime`, `datetime.timezone`, `typing.IO`, `typing.Iterator`, `rich.console.Console`, `rich.text.Text`, `vizhi.classifier.ClassifiedEvent`, `vizhi.classifier.RiskLevel`, `vizhi.classifier.classify_event`, `vizhi.parser.parse_line`, `vizhi.reporter.generate_report`, `vizhi.reporter.print_report`, `vizhi.reporter.save_report`, plus `from __future__ import annotations`.
- **Imported by:**
  - `cli.py` — imports `watch`.
  - `session_viewer.py` — imports `render_event`.

---

## `reporter.py`

### Simple Explanation
After a session ends, this module turns the list of classified events into two things: a tidy printed summary that appears in the terminal, and a JSON file on disk that captures the full session for later inspection. It also computes the risk breakdown (how many critical / high / medium / low / info events occurred) and selects which events should be highlighted as "flagged."

### Technical Explanation
Aggregator and serializer. `generate_report()` is pure: it takes a list of events plus optional timing/session-id inputs and returns an immutable `SessionReport`. `print_report()` renders that report via Rich (a header panel, a risk-breakdown table, and a flagged-events table). `save_report()` serializes it to a UTF-8 JSON file with a deterministic filename pattern (`session_<uuid>_<YYYYMMDDTHHMMSSZ>.json`) inside a target directory. The serialization helpers are private (`_report_to_dict`, `_classified_to_dict`) and produce hand-crafted dicts rather than using `dataclasses.asdict()`, so we can control timestamp formatting and field ordering.

### Module-Level Constants

#### `RISK_ORDER`
- **Stored value:** the tuple `("critical", "high", "medium", "low", "info")`.
- **Why a `tuple[RiskLevel, ...]`:** fixed, ordered, immutable. We need the order specifically — both the printed table and the JSON breakdown iterate in this exact order to present severities high-to-low.
- **Where used:** `generate_report()` (initializes the breakdown dict with all five keys at zero), `print_report()` (iterates to build the table rows), `_report_to_dict()` (iterates to emit the breakdown dict in fixed order).

#### `FLAGGED_LEVELS`
- **Stored value:** the frozenset `frozenset({"critical", "high"})`.
- **Why a `frozenset[RiskLevel]`:** O(1) membership check, immutable so callers cannot accidentally mutate the policy, and explicit about the fact that order is irrelevant for membership-only use.
- **Where used:** `generate_report()` builds `flagged = [ce for ce in events if ce.risk_level in FLAGGED_LEVELS]`. Changing the policy of what counts as "flagged" is a one-line edit here.

#### `RISK_STYLES`
- **Stored value:** identical to `watcher.RISK_STYLES` — the dict `{"critical": "bold red", "high": "red", "medium": "yellow", "low": "green", "info": "dim white"}`.
- **Why duplicated rather than imported:** keeps `reporter.py` free of a dependency on `watcher.py`. Both modules colorize independently of each other; coupling them would force a change to one to ripple to the other for no real benefit.
- **Where used:** `print_report()` — colors the rows in the risk-breakdown table and the badges in the flagged-events table.

### Functions & Classes

#### `class SessionReport`
```python
@dataclass(frozen=True)
class SessionReport:
    session_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    total_actions: int
    risk_breakdown: dict[RiskLevel, int]
    flagged_events: list[ClassifiedEvent]
    all_events: list[ClassifiedEvent]
```

- **Why a dataclass:** plain data aggregate; autogen `__init__`, `__repr__`, `__eq__` are what we need.
- **Why `frozen=True`:** once a session is summarized, the summary is the historical record. Freezing the top-level dataclass prevents callers from rewriting history by mutating the fields. The fields hold mutable containers (`dict`, `list`) — `frozen=True` does not deep-freeze, so technically `report.risk_breakdown["critical"] = 99` would still succeed. The protection is against accidental reassignment (`report.total_actions = 0`), which is the common bug, and it documents the dataclass's read-only intent.

- **Fields:**
  - `session_id: uuid.UUID` — the same UUID used in the live banner and embedded into the saved filename. UUID rather than `str` because it is type-safe and self-formatting.
  - `started_at: datetime` — timezone-aware UTC moment the watcher started (stdin mode) or the watch command began (v2 mode). Used for duration calculation and the filename slug.
  - `ended_at: datetime` — timezone-aware UTC moment the watcher stopped.
  - `total_actions: int` — convenience cache of `len(all_events)`. Stored explicitly because the JSON file's consumers (a human reading it, a future dashboard) read this field directly without recomputing.
  - `risk_breakdown: dict[RiskLevel, int]` — count of events per severity level. Always contains all five keys (initialized to zero in `generate_report`) so consumers can iterate without `KeyError`.
  - `flagged_events: list[ClassifiedEvent]` — the subset of events whose `risk_level` is in `FLAGGED_LEVELS`. Pre-extracted so the printed and JSON-rendered "Top Flagged" tables don't need to filter again.
  - `all_events: list[ClassifiedEvent]` — the full event log for the session. Stored so the JSON file is a faithful, lossless record of what happened.

- **Where instances are created:**
  - `reporter.generate_report()` — the only place.

#### `generate_report(events, started_at=None, ended_at=None, session_id=None) -> SessionReport`
- **Signature:** `def generate_report(events: list[ClassifiedEvent], started_at: datetime | None = None, ended_at: datetime | None = None, session_id: uuid.UUID | None = None) -> SessionReport`.
- **Parameter `events`:** the classified events to summarize. The function does not consume or mutate the list — it stores a shallow copy (`list(events)`) on the report.
- **Parameter `started_at`:** the session start moment. If `None` and `events` is non-empty, falls back to the timestamp of the first event. If `None` and `events` is empty, falls back to `ended_at` (so duration is zero). Type: timezone-aware `datetime` (the rest of the system always supplies UTC).
- **Parameter `ended_at`:** the session end moment. If `None`, defaults to `datetime.now(timezone.utc)`.
- **Parameter `session_id`:** the session UUID. If `None`, generates a fresh one with `uuid.uuid4()`.
- **Return:** a fresh `SessionReport` whose fields are all populated.
- **What it does:**
  1. Decides effective `sid`, `end`, `start` from the args using the fallback rules above.
  2. Initializes `breakdown` with every `RiskLevel` key set to `0` (so even severities that didn't occur appear in the table).
  3. Increments `breakdown[ce.risk_level]` for every event.
  4. Builds `flagged` by list comprehension over `events`.
  5. Returns a fresh `SessionReport`.
- **Edge cases:**
  - `events == []`: `breakdown` stays all zeros, `flagged` is empty, `total_actions == 0`. The report is still valid.
  - `events` non-empty but all `info`: `flagged` is empty, breakdown reflects the info count.
  - All three optional args `None`: a fully autonomous report is built — useful for tests.
- **Why it exists:** the single function that turns a stream of judgments into a structured artifact. Removing it would force every caller (`watcher._finalize_session`, `cli.watch_cmd`) to duplicate the aggregation logic, and the two paths would inevitably drift.
- **Gotcha:** does not deduplicate or sort `events` — it preserves observation order. If a caller wants chronological order it must pre-sort.
- **Concrete example:**
  - Input: `events = [ClassifiedEvent(..., risk_level="critical"), ClassifiedEvent(..., risk_level="info")]`, `started_at=T1`, `ended_at=T2`, `session_id=UUID('abc...')`.
  - Output: `SessionReport(session_id=UUID('abc...'), started_at=T1, ended_at=T2, total_actions=2, risk_breakdown={"critical":1,"high":0,"medium":0,"low":0,"info":1}, flagged_events=[<the critical one>], all_events=[<both>])`.
- **Called by:** `watcher._finalize_session()`, `cli.watch_cmd()`.
- **Calls:** `uuid.uuid4`, `datetime.now`, dict/list comprehensions, the `SessionReport` constructor.

#### `print_report(report: SessionReport, console: Console) -> None`
- **Signature:** `def print_report(report: SessionReport, console: Console) -> None`.
- **Parameter `report`:** the `SessionReport` to render.
- **Parameter `console`:** the Rich `Console` to print to. Injected so callers can capture or theme the output.
- **Return:** `None`. Side effect: a multi-block summary printed to the console.
- **What it does, in order:**
  1. Computes `duration_secs` from `ended_at - started_at`.
  2. Builds a header string with session id, started/ended timestamps (`isoformat(timespec="seconds")`), human-friendly duration, and `total_actions`. Wraps it in a Rich `Panel` with cyan border and the title `"Vizhi Session Report"`.
  3. Builds a Rich `Table` titled `"Risk Breakdown"` with columns `Risk | Count | Percent`. One row per `RISK_ORDER` entry, coloring the risk label using `RISK_STYLES`. Percentages use `total = max(report.total_actions, 1)` to avoid division-by-zero on empty sessions.
  4. If `flagged_events` is empty, prints `"No critical or high-risk events this session."` in green and returns.
  5. Otherwise builds a second `Table` titled `"Top Flagged Events (critical / high)"` with columns `Time | Risk | Type | Action | Reason`, one row per flagged event.
- **Edge cases:**
  - Empty session (`total_actions == 0`): table still renders with all zero counts and `0.0%` rows; flagged table is skipped.
  - Negative duration (clock skew): `_fmt_duration()` clamps to zero.
- **Why it exists:** the single rendering of a `SessionReport`. Without it, callers would have to know about Panel and Table APIs.
- **Called by:** `watcher._finalize_session()`, `cli.report_cmd()`, `cli.watch_cmd()`.
- **Calls:** `_fmt_duration`, `RISK_STYLES.__getitem__`, `Panel`, `Table`, `console.print`.

#### `save_report(report: SessionReport, output_dir: str = "./vizhi_reports") -> str`
- **Signature:** `def save_report(report: SessionReport, output_dir: str = "./vizhi_reports") -> str`.
- **Parameter `report`:** the report to persist.
- **Parameter `output_dir`:** the directory to write into. Created (with `parents=True, exist_ok=True`) if missing.
- **Return:** the full path of the written file, as a `str` (not a `Path`, because Click prints it directly).
- **What it does:**
  1. Ensures `output_dir` exists.
  2. Builds the filename `session_<uuid>_<YYYYMMDDTHHMMSSZ>.json` using `report.started_at.strftime("%Y%m%dT%H%M%SZ")`.
  3. Serializes the report via `_report_to_dict()` and writes pretty-printed JSON (`indent=2`) as UTF-8.
  4. Returns the path string.
- **Edge cases:**
  - `output_dir` already exists: tolerated.
  - `output_dir` exists but is a file: raises an `OSError` from `mkdir` (intentional — caller should fix the conflict).
  - Reports from the same session within the same second collide on filename: would overwrite. Not a problem in practice because the session UUID is in the filename, and one session does not generate two reports.
- **Why it exists:** persisting the report is the difference between an ephemeral terminal print and a durable audit record. Without this, the `vizhi report` command would have nothing to read.
- **Concrete example:**
  - `save_report(report, "./vizhi_reports")` with `report.session_id = UUID('abc-...')` and `report.started_at = 2026-05-21T12:07:00Z` writes `./vizhi_reports/session_abc-..._20260521T120700Z.json` and returns that path.
- **Called by:** `watcher._finalize_session()`, `cli.watch_cmd()`.
- **Calls:** `Path.mkdir`, `Path.write_text`, `json.dumps`, `_report_to_dict`, `datetime.strftime`.

#### `_report_to_dict(report: SessionReport) -> dict`
- **Signature:** `def _report_to_dict(report: SessionReport) -> dict`.
- **Parameter `report`:** the report to serialize.
- **Return:** a plain `dict` that is JSON-serializable via `json.dumps`.
- **What it does:** hand-crafts the dict in a fixed key order: `session_id`, `started_at`, `ended_at`, `duration_seconds`, `total_actions`, `risk_breakdown`, `flagged_events`, `all_events`. UUIDs are converted to `str`, datetimes to ISO-8601, and inner `ClassifiedEvent`s delegated to `_classified_to_dict()`. The breakdown is rebuilt from `RISK_ORDER` so all five keys always appear in the same order even if the source dict was iterated differently.
- **Why hand-crafted (not `dataclasses.asdict`):** `asdict()` would not know how to format `UUID` or `datetime`, and would emit fields in declaration order with no opportunity to add derived fields like `duration_seconds`.
- **Why a separate function:** keeps the JSON shape explicit and grep-able, makes it easy to add or rename fields in one place, and lets `save_report()` stay tiny.
- **Called by:** `save_report()` (same file).
- **Calls:** `str(uuid)`, `datetime.isoformat`, `_classified_to_dict`.

#### `_classified_to_dict(ce: ClassifiedEvent) -> dict`
- **Signature:** `def _classified_to_dict(ce: ClassifiedEvent) -> dict`.
- **Parameter `ce`:** a single `ClassifiedEvent`.
- **Return:** a flat dict with keys `timestamp`, `action_type`, `raw_text`, `metadata`, `risk_level`, `reason`. The inner `ActionEvent` is flattened into the parent dict (no nested `"event"` key) because the JSON consumer (humans, the future dashboard, and the rehydration logic in `cli._event_from_dict()` and `session_viewer._event_from_line()`) prefers a flat record.
- **Why hand-crafted:** controls the field order and converts `datetime` to ISO-8601.
- **Called by:** `_report_to_dict()` and indirectly by `save_report()`. The JSONL log written by `hook_receiver._append_to_session_log()` uses the same shape (also hand-crafted there).
- **Calls:** `datetime.isoformat`, `dict()`.

#### `_fmt_duration(seconds: float) -> str`
- **Signature:** `def _fmt_duration(seconds: float) -> str`.
- **Parameter `seconds`:** a duration in seconds. Negative values are clamped to zero.
- **Return:** a compact string like `"3h 14m 7s"`, `"42m 17s"`, or `"9s"`. Empty leading units are omitted.
- **What it does:** clamps to zero, integer-divides by 3600 for hours and 60 for minutes, formats conditionally so a 9-second duration renders as `"9s"` not `"0h 0m 9s"`.
- **Edge cases:**
  - Negative input (clock skew): clamped to `0.0` → returns `"0s"`.
  - Fractional seconds: truncated by the `int()` cast.
- **Why it exists:** the only consumer is `print_report()`. Pulled out for readability and so a future test can verify the formatting independently.
- **Called by:** `print_report()` (same file).
- **Calls:** `max`, `divmod`, `int`.

### Connections
- **Imports:** `json`, `uuid`, `dataclasses.dataclass`, `datetime.datetime`, `datetime.timezone`, `pathlib.Path`, `rich.console.Console`, `rich.panel.Panel`, `rich.table.Table`, `vizhi.classifier.ClassifiedEvent`, `vizhi.classifier.RiskLevel`, plus `from __future__ import annotations`.
- **Imported by:**
  - `watcher.py` — imports `generate_report`, `print_report`, `save_report`.
  - `cli.py` — imports `SessionReport`, `generate_report`, `print_report`, `save_report`.

---

## `cli.py`

### Simple Explanation
The command-line surface of Vizhi. This file uses the Click library to declare a top-level `vizhi` command with six subcommands: `start` (run the v1 stdin watcher), `report` (pretty-print the most recent JSON report), `hook` (handle one PostToolUse payload from stdin), `watch` (tail a live session JSONL log and report on Ctrl+C), `install-hook`, and `uninstall-hook` (install/uninstall the hook entry in Claude Code's settings).

### Technical Explanation
Pure orchestration. Every subcommand is a Click-decorated function that does input plumbing (option parsing, file path resolution), calls a library function from the other modules, and prints user-facing messages via Rich. There is no business logic in this file — only command wiring, error display, and exit-code handling. The `main` group is declared first; subcommands attach via `@main.command("name", help="...")`. The entry point name `vizhi` is registered in `pyproject.toml`'s `[project.scripts]` block: `vizhi = "vizhi.cli:main"`.

### Module-Level Constants

#### `DEFAULT_OUTPUT_DIR`
- **Stored value:** the string `"./vizhi_reports"`.
- **Why a `str`:** Click's `click.Path` option type wants a string. The value is converted to a `Path` by downstream modules as needed.
- **Why this specific path:** a relative-to-cwd default makes session reports land in the project the user is currently working on, which is the natural place to keep them.
- **Where used:** as the `default=` of every subcommand's `--output-dir` option.

### Functions & Classes

(No classes are defined in `cli.py`. The file contains command functions plus a handful of private helpers.)

#### `main() -> None`
- **Signature:** `@click.group(help="Vizhi — real-time security monitor for AI agents.") @click.version_option(__version__, prog_name="vizhi") def main() -> None`.
- **Parameter:** none — Click handles all CLI arg parsing through the decorator chain.
- **Return:** `None`.
- **What it does:** declares the top-level command group. The function body is a docstring only because Click invokes the actual subcommand based on the user's args; `main()` itself never runs business logic.
- **Why it exists:** Click requires a `@click.group` to register subcommands against (via `@main.command(...)`). It is also the entry point referenced in `pyproject.toml`'s `[project.scripts]` table — `vizhi = "vizhi.cli:main"` — so `pip install -e .` produces a `vizhi` shell script that invokes this function.
- **Called by:** the installed `vizhi` script (via setuptools' generated wrapper) and `python -m vizhi.cli`.
- **Calls:** none directly; Click dispatches to a subcommand function.

#### `start_cmd(output_dir: str) -> None`
- **Signature:** decorated with `@main.command("start", help="Start the watcher. Reads agent output from stdin.")` and `@click.option("--output-dir", "output_dir", default=DEFAULT_OUTPUT_DIR, show_default=True, type=click.Path(file_okay=False, dir_okay=True), help="...")`.
- **Parameter `output_dir`:** path to the directory the final JSON report will be written into. Defaults to `DEFAULT_OUTPUT_DIR`. Click validates that the path is not a file.
- **Return:** `None`.
- **What it does:** calls `watch(output_dir=output_dir)` from `watcher.py`. That is all.
- **Why it exists:** the thin wrapper that exposes `vizhi start` on the CLI.
- **Called by:** Click's dispatch on `vizhi start ...`.
- **Calls:** `watch`.

#### `report_cmd(output_dir: str) -> None`
- **Signature:** decorated with `@main.command("report", help="Pretty-print the most recent session report.")` and the same `--output-dir` option.
- **Parameter `output_dir`:** directory to search for `session_*.json` files.
- **Return:** `None`. Side effect: prints the report or an error.
- **What it does:**
  1. Constructs a `Console()`.
  2. Calls `_latest_report_path(output_dir)`.
  3. If `None`, prints a yellow "No reports found" message including a hint to run `vizhi start`, and raises `SystemExit(1)`.
  4. Otherwise prints `[dim]Loading report:[/] <path>`, calls `_load_report(path)`, then `print_report(report, console)`.
- **Edge cases:**
  - Directory doesn't exist: `_latest_report_path` returns `None`, same as "no files."
  - Directory exists but is empty: same as "no files."
  - File is unreadable or malformed JSON: `_load_report` raises (JSONDecodeError or KeyError) — Click prints the traceback to stderr.
- **Why it exists:** the canonical way to revisit a past session without grepping `vizhi_reports/`.
- **Called by:** Click on `vizhi report ...`.
- **Calls:** `Console`, `_latest_report_path`, `_load_report`, `print_report`.

#### `_latest_report_path(output_dir: str) -> Path | None`
- **Signature:** `def _latest_report_path(output_dir: str) -> Path | None`.
- **Parameter `output_dir`:** directory to search.
- **Return:** the `Path` of the most-recently-modified `session_*.json` file, or `None` if none found (or the directory doesn't exist).
- **What it does:** `Path(output_dir).glob("session_*.json")`, sorted by `st_mtime` descending, first element returned (or `None`).
- **Why it exists:** simple, fast "give me the newest" helper used only by `report_cmd`.
- **Gotcha:** uses modification time, not creation time. On most filesystems this is correct because the file is written once and never touched again. If a user `touch`es an old file, that file becomes "most recent."
- **Concrete example:**
  - `./vizhi_reports/` contains two files: `session_a_20260521T120000Z.json` (mtime older), `session_b_20260522T130000Z.json` (mtime newer). Returns `Path("./vizhi_reports/session_b_...")`.
- **Called by:** `report_cmd()`.
- **Calls:** `Path.exists`, `Path.glob`, `sorted`, `Path.stat`.

#### `_load_report(path: Path) -> SessionReport`
- **Signature:** `def _load_report(path: Path) -> SessionReport`.
- **Parameter `path`:** the file path to read.
- **Return:** a fresh `SessionReport` reconstructed from the JSON.
- **What it does:** reads UTF-8 text, parses it with `json.loads`, then rebuilds the report:
  - `session_id` parsed via `uuid.UUID(data["session_id"])`.
  - `started_at`, `ended_at` parsed via `datetime.fromisoformat()`.
  - `total_actions` cast to `int`.
  - `risk_breakdown` copied as `dict(data["risk_breakdown"])`.
  - `flagged_events` and `all_events` rebuilt via `_event_from_dict()` per element.
- **Edge cases:**
  - Missing keys: raises `KeyError` — surfaces to the user as an unhandled traceback (intentional — a bad report file should be loud).
  - Datetime strings without timezone offset: `fromisoformat` returns a naive datetime; `print_report`'s duration math still works arithmetically but the values lose UTC awareness.
- **Why it exists:** without it `vizhi report` could not deserialize older sessions.
- **Concrete example:** given the JSON file produced by `save_report`, returns a structurally equivalent `SessionReport` (same field values, same nested events).
- **Called by:** `report_cmd()`.
- **Calls:** `Path.read_text`, `json.loads`, `uuid.UUID`, `datetime.fromisoformat`, `int`, `dict`, `_event_from_dict`, `SessionReport`.

#### `hook_cmd(output_dir: str) -> None`
- **Signature:** decorated with `@main.command("hook", help="Receive a single PostToolUse JSON payload from stdin (for Claude Code hooks).")` and the standard `--output-dir` option.
- **Parameter `output_dir`:** directory where `session_<sessionId>.jsonl` lives. Created by the receiver if missing.
- **Return:** `None`. The command exits via `SystemExit` with the receiver's return code (always 0 in the current implementation).
- **What it does:** `raise SystemExit(hook_receive(output_dir=output_dir))`. The receiver does the actual work; this wrapper just exposes it as a CLI subcommand. Note: Claude Code's hook configuration installed by `install_hook()` invokes `python -m vizhi.hook_receiver`, not `vizhi hook`. The CLI subcommand exists as an alternative invocation path useful for tests or curl-style debugging (`echo '{"toolName":"Bash",...}' | vizhi hook`).
- **Called by:** Click on `vizhi hook ...`.
- **Calls:** `hook_receive` (i.e., `vizhi.hook_receiver.receive`).

#### `watch_cmd(session_id: str | None, output_dir: str) -> None`
- **Signature:** decorated with `@main.command("watch", help="Tail a live Claude Code session JSONL log and report on Ctrl+C.")`, plus `--session-id` (default `None`) and `--output-dir` (default `DEFAULT_OUTPUT_DIR`).
- **Parameter `session_id`:** the session whose log to tail. If `None`, auto-detects the most-recent session via `find_latest_session()`.
- **Parameter `output_dir`:** directory containing `session_<sessionId>.jsonl` files.
- **Return:** `None`.
- **What it does, in order:**
  1. Constructs a `Console()`.
  2. If `session_id is None`, calls `find_latest_session(output_dir)`. If that also returns `None`, prints a red "No session logs found" message with a hint to run `install-hook` and `SystemExit(1)`.
  3. Prints a cyan "Vizhi watch started. Tailing session <id> in <dir>. Ctrl+C to end." banner.
  4. Captures `started_at = datetime.now(timezone.utc)`.
  5. Calls `tail_session(session_id, output_dir, console)`, wrapped in a `try/except` that catches `FileNotFoundError` (print red error and exit 1) and `KeyboardInterrupt` (defensive: `tail_session` already catches internally, but this guards against a race during interpreter shutdown).
  6. Prints "Watch stopped. Generating session report..." and calls `generate_report(events, started_at=..., ended_at=now(), session_id=_parse_session_uuid(session_id))`, then `print_report`, then `save_report`.
  7. Prints the saved report path.
- **Edge cases:**
  - Auto-detect with empty directory: handled by the early `SystemExit(1)`.
  - Session ID provided but file doesn't appear within 3 seconds: `FileNotFoundError` from `_wait_for_file` is caught and surfaced.
  - User Ctrl+Cs immediately: `events` is empty, report still generated (zero actions).
- **Why it exists:** the user-facing way to invoke the live tailer. Without it, the entire v2.3 viewer would be unreachable from the CLI.
- **Called by:** Click on `vizhi watch ...`.
- **Calls:** `Console`, `find_latest_session`, `tail_session`, `_parse_session_uuid`, `generate_report`, `print_report`, `save_report`, `datetime.now`.

#### `_parse_session_uuid(session_id: str) -> uuid.UUID`
- **Signature:** `def _parse_session_uuid(session_id: str) -> uuid.UUID`.
- **Parameter `session_id`:** the raw session id, which might or might not be a UUID. Claude Code sends UUIDs, but tests and ad-hoc invocations may use arbitrary strings like `"smoke-001"`.
- **Return:** a `uuid.UUID` instance — either parsed from `session_id` or freshly generated if parsing fails.
- **What it does:** `try: return uuid.UUID(session_id) except ValueError: return uuid.uuid4()`. Best-effort.
- **Why it exists:** `SessionReport.session_id` is typed as `uuid.UUID`. The v2 mode reuses the hook's `session_id` string for the report; this helper makes the type fit without crashing on non-UUID inputs.
- **Gotcha:** when fallback fires (non-UUID input), the saved JSON report's `session_id` will not match the JSONL log's filename. The JSONL filename keeps the original string; the JSON's session UUID is fresh. This is a minor traceability quirk, acceptable in alpha and tracked implicitly by the JSONL file's separate stable name.
- **Called by:** `watch_cmd()` (same file).
- **Calls:** `uuid.UUID`, `uuid.uuid4`.

#### `install_hook_cmd() -> None`
- **Signature:** decorated with `@main.command("install-hook", help="Install the vizhi PostToolUse hook into ~/.claude/settings.json.")`. Takes no options.
- **Return:** `None`.
- **What it does, in order:**
  1. `Console()`.
  2. `path = get_settings_path()` — resolves `~/.claude/settings.json`.
  3. Calls `load_settings(path)` inside a try/except that catches `json.JSONDecodeError` and `ValueError` (both raised by the loader for malformed JSON or non-dict roots). On error, prints a red message naming the file and the exception, and `SystemExit(1)`.
  4. `updated, already_installed = install_hook(settings)`.
  5. If `already_installed`, prints a yellow "already installed" message and returns (no file write).
  6. Otherwise calls `save_settings(path, updated)` and prints a green success banner explaining that Claude Code will now invoke `python -m vizhi.hook_receiver` after every tool call.
- **Why it exists:** the user-facing entry point that automates the otherwise-manual hook setup. Without it the user would have to hand-edit `~/.claude/settings.json` to add the matcher and command.
- **Idempotent:** running twice produces the "already installed" yellow message — no duplicate entry is created.
- **Called by:** Click on `vizhi install-hook`.
- **Calls:** `Console`, `get_settings_path`, `load_settings`, `install_hook`, `save_settings`.

#### `uninstall_hook_cmd() -> None`
- **Signature:** decorated with `@main.command("uninstall-hook", help="Remove the vizhi PostToolUse hook from ~/.claude/settings.json.")`. Takes no options.
- **Return:** `None`.
- **What it does:**
  1. `Console()`.
  2. `path = get_settings_path()`.
  3. If `path` does not exist, prints a yellow "no settings file — nothing to remove" message and returns.
  4. Otherwise calls `load_settings(path)` with the same error handling as install.
  5. `updated, was_removed = uninstall_hook(settings)`.
  6. If `not was_removed`, prints a yellow "Vizhi hook not found" message and returns.
  7. Otherwise `save_settings(path, updated)` and prints a green "Removed" message.
- **Why it exists:** the matching teardown for `install-hook`. Without it, users can't cleanly disable vizhi hooks from Claude Code without hand-editing.
- **Called by:** Click on `vizhi uninstall-hook`.
- **Calls:** `Console`, `get_settings_path`, `Path.exists`, `load_settings`, `uninstall_hook`, `save_settings`.

#### `_event_from_dict(d: dict) -> ClassifiedEvent`
- **Signature:** `def _event_from_dict(d: dict) -> ClassifiedEvent`.
- **Parameter `d`:** a dict shaped like the output of `reporter._classified_to_dict()` (keys: `timestamp`, `raw_text`, `action_type`, `metadata`, `risk_level`, `reason`).
- **Return:** a fresh `ClassifiedEvent` wrapping a fresh `ActionEvent`.
- **What it does:** parses `timestamp` via `datetime.fromisoformat`, copies `metadata` defensively via `dict(...)`, then builds the two dataclasses.
- **Why it exists:** the inverse of `_classified_to_dict`. Used by `_load_report` to rehydrate a saved report so `print_report` can render it.
- **Gotcha:** does not validate field types — relies on the saved JSON being well-formed (which it is, because `save_report` is the only writer).
- **Called by:** `_load_report()`.
- **Calls:** `datetime.fromisoformat`, `dict`, the `ActionEvent` and `ClassifiedEvent` constructors.

### Connections
- **Imports:** `json`, `uuid`, `datetime.datetime`, `datetime.timezone`, `pathlib.Path`, `click`, `rich.console.Console`, `vizhi.__version__`, `vizhi.classifier.ClassifiedEvent`, `vizhi.hook_receiver.receive` (aliased as `hook_receive`), `vizhi.installer.{get_settings_path, install_hook, load_settings, save_settings, uninstall_hook}`, `vizhi.parser.ActionEvent`, `vizhi.reporter.{SessionReport, generate_report, print_report, save_report}`, `vizhi.session_viewer.{find_latest_session, tail_session}`, `vizhi.watcher.watch`, plus `from __future__ import annotations`.
- **Imported by:** none inside `vizhi/` — this is the top-level entry point. Setuptools generates a `vizhi` shell script that imports `vizhi.cli:main` and invokes it.

---

## `hook_receiver.py`

### Simple Explanation
The bridge between Claude Code and Vizhi. Claude Code is configured (by `install_hook`) to run `python -m vizhi.hook_receiver` after every tool call. This module receives the resulting JSON payload on stdin, decides what kind of action it represents, runs it through the same classifier the v1 watcher uses, and appends the classified result as one line to a JSONL file named after the session.

### Technical Explanation
A defensive JSON-in, JSONL-out adapter. The `receive()` function reads stdin once, parses it as JSON, extracts the fields Claude Code sends (`toolName`, `toolInput`, `sessionId`, `cwd`, `timestamp`), maps the tool name to a vizhi `ActionType` via `TOOL_TO_ACTION_TYPE`, synthesizes a `raw_text` string suitable for the existing classifier via `_build_raw_text()`, constructs an `ActionEvent` plus a metadata dict tagging the source as `"hook"`, runs `classify_event()`, and appends the result to `session_<sanitized-id>.jsonl`. Every failure mode — empty stdin, malformed JSON, missing fields, wrong types — is logged to stderr and the function returns `0` so Claude Code never sees a non-zero hook exit (which would interrupt the agent).

### Module-Level Constants

#### `DEFAULT_OUTPUT_DIR`
- **Stored value:** the string `"./vizhi_reports"`.
- **Why a `str`:** matches the surrounding API; converted to `Path` inside `_append_to_session_log`.
- **Where used:** as the default value of `receive()`'s `output_dir` parameter and indirectly via `cli.hook_cmd`.

#### `TOOL_TO_ACTION_TYPE`
- **Stored value:** the dict `{"Bash": "command", "Shell": "command", "Read": "file_access", "Write": "file_access", "Edit": "file_access", "MultiEdit": "file_access", "WebFetch": "network", "WebSearch": "network"}`.
- **Why a `dict[str, ActionType]`:** O(1) lookup, typed values (so a typo like `"comand"` is a type error). Plain dict because the set of Claude Code tool names evolves and may be edited; a tuple-of-pairs would be needlessly awkward to extend.
- **Why these mappings:** they cover Claude Code's standard built-in tools. Anything not in the map (e.g. a third-party MCP tool) falls back to `"unknown"`.
- **Where used:** `receive()` does `action_type = TOOL_TO_ACTION_TYPE.get(str(tool_name), "unknown")`.

#### `FILE_PATH_TOOLS`
- **Stored value:** the frozenset `frozenset({"Read", "Write", "Edit", "MultiEdit"})`.
- **Why a `frozenset[str]`:** O(1) membership check; immutable so the policy cannot be accidentally mutated; explicit signal that order does not matter.
- **Why these specifically:** these are the tools whose `toolInput` dict carries a `file_path` field. Lumping them lets `_build_raw_text()` use one branch instead of four.
- **Where used:** only inside `_build_raw_text()`.

### Functions & Classes

(No classes are defined in this module.)

#### `receive(source: IO[str] | None = None, output_dir: str = DEFAULT_OUTPUT_DIR) -> int`
- **Signature:** `def receive(source: IO[str] | None = None, output_dir: str = DEFAULT_OUTPUT_DIR) -> int`.
- **Parameter `source`:** the text stream to read from. `None` defaults to `sys.stdin` (the canonical hook invocation). Tests pass a `StringIO`.
- **Parameter `output_dir`:** directory where `session_<sessionId>.jsonl` is appended.
- **Return:** the process exit code. **Always `0`** on handled failure paths — Claude Code interprets non-zero hook exits as "the hook failed, abort the agent's tool call." We never want to do that, so we swallow every error.
- **What it does, in order:**
  1. Reads all of stdin into `raw`.
  2. If `raw.strip()` is empty, calls `_warn("empty stdin — no payload to process")` and returns `0`.
  3. Parses `raw` with `json.loads`. On `JSONDecodeError`, warns and returns `0`.
  4. If the parsed payload is not a dict, warns and returns `0`.
  5. Pulls `tool_name` via `_get_field(payload, "toolName", "tool_name")` (tolerates both camelCase and snake_case keys), `tool_input` via the same helper, `session_id` similarly, plus `timestamp` and `cwd` directly.
  6. If `tool_name` is missing → warn and return `0`. Same for `session_id`.
  7. If `tool_input` is not a dict, warn and coerce to `{}`.
  8. Looks up `action_type = TOOL_TO_ACTION_TYPE.get(str(tool_name), "unknown")`.
  9. Builds the `raw_text` via `_build_raw_text(str(tool_name), tool_input)`.
  10. Parses the timestamp via `_parse_timestamp(timestamp_raw)`.
  11. Builds a `metadata` dict containing `{"tool_name": str(tool_name), "source": "hook"}` and optionally `"cwd"` if present.
  12. Constructs an `ActionEvent`, runs `classify_event()`, and calls `_append_to_session_log()` to write the JSONL record.
  13. Prints a one-line status message to stderr (`[vizhi hook] <risk> <toolName> → <path>`). Returns `0`.
- **Edge cases:**
  - Empty stdin (e.g. Claude Code fires the hook with no payload for some reason): swallowed, warned, exit `0`.
  - Malformed JSON: same.
  - JSON that is a list or string at the root: same.
  - `toolInput` is a list rather than an object: warned, coerced to `{}`, classification proceeds with whatever `raw_text` the fallback branch produces.
  - `timestamp` missing or malformed: `_parse_timestamp` falls back to `datetime.now(timezone.utc)`.
  - Tool name we don't recognize (e.g. a custom MCP tool): `action_type` is `"unknown"`, `_build_raw_text` falls back to `f"{tool_name}({json.dumps(tool_input)[:500]})"`.
- **Why it exists:** without this, Vizhi cannot observe Claude Code's actual tool calls. The v1 stdin watcher only sees what Claude prints to its terminal, which is a lossy text view; the hook receives the structured tool inputs themselves.
- **Gotchas:**
  - The function silently swallows every error. This is intentional (do not block the agent), but means a misconfiguration can lead to silent under-logging. The stderr warnings are the only signal.
  - Sanitization of `session_id` is permissive: it keeps any alphanumeric, dash, or underscore character. A `sessionId` containing slashes (path traversal attempt) is stripped clean.
- **Concrete example:**
  - Stdin: `{"hookEvent":"PostToolUse","toolName":"Bash","toolInput":{"command":"sudo cat /etc/shadow"},"sessionId":"abc-123","timestamp":"2026-05-21T12:07:00Z","cwd":"C:\\\\Users\\\\jainp"}`.
  - The function builds `ActionEvent(timestamp=2026-05-21T12:07:00+00:00, raw_text="sudo cat /etc/shadow", action_type="command", metadata={"tool_name":"Bash","source":"hook","cwd":"C:\\Users\\jainp"})`, classifies it as critical (`sudo ` is in CRITICAL_PATTERNS), appends one line to `./vizhi_reports/session_abc-123.jsonl`, prints to stderr `[vizhi hook] critical Bash → vizhi_reports/session_abc-123.jsonl`, and returns `0`.
- **Called by:** `python -m vizhi.hook_receiver` (via the `if __name__ == "__main__"` block at file end) and `cli.hook_cmd()`.
- **Calls:** `source.read`, `json.loads`, `_get_field`, `_warn`, `_build_raw_text`, `_parse_timestamp`, `ActionEvent`, `classify_event`, `_append_to_session_log`, `print`.

#### `_build_raw_text(tool_name: str, tool_input: dict[str, Any]) -> str`
- **Signature:** `def _build_raw_text(tool_name: str, tool_input: dict[str, Any]) -> str`.
- **Parameter `tool_name`:** the tool's name string (already coerced to `str`).
- **Parameter `tool_input`:** the tool's input dict, already validated to be a dict (possibly empty).
- **Return:** a single string that the classifier can scan. Per-tool synthesis rules:
  - For `Bash`/`Shell`: if `tool_input["command"]` is a non-empty string, return it verbatim. (So `Bash({"command":"sudo rm -rf /"})` becomes `"sudo rm -rf /"`, which the classifier flags as critical.)
  - For `Read`/`Write`/`Edit`/`MultiEdit` (i.e. `FILE_PATH_TOOLS`): return `f"{tool_name}({file_path})"` if a non-empty `file_path` is present. (So `Read({"file_path":"~/.ssh/id_rsa"})` becomes `"Read(~/.ssh/id_rsa)"`, which triggers a critical pattern via the `~/.ssh` substring.)
  - For `WebFetch`: `f"WebFetch({url})"`.
  - For `WebSearch`: `f"WebSearch({query})"`.
  - Fallback: `f"{tool_name}({json.dumps(tool_input)[:500] + '...' if too long})"`. The truncation cap of 500 chars keeps very large tool inputs from blowing up the log.
- **Edge cases:**
  - Missing expected key: falls through to the fallback branch (so `Read({})` becomes `"Read({})"`).
  - Non-string command/path/url: falls through to fallback.
  - Tool inputs containing non-ASCII characters: `ensure_ascii=False` in the fallback preserves them as readable Unicode.
- **Why it exists:** the classifier was originally designed for free-text agent stdout. The hook payload is structured; this function projects the structure back into a text shape the classifier can scan. Without it the classifier would see only the raw JSON dump of `toolInput`, which would still flag `sudo` and `rm -rf` substrings but would lose the natural-looking `"Read(~/.ssh/id_rsa)"` projection that humans read in the live feed.
- **Concrete examples:**
  - `_build_raw_text("Bash", {"command":"ls"})` → `"ls"`.
  - `_build_raw_text("Read", {"file_path":"/etc/passwd"})` → `"Read(/etc/passwd)"`.
  - `_build_raw_text("WebFetch", {"url":"https://github.com/x"})` → `"WebFetch(https://github.com/x)"`.
  - `_build_raw_text("UnknownTool", {"foo":"bar"})` → `'UnknownTool({"foo": "bar"})'`.
- **Called by:** `receive()` (same file).
- **Calls:** `dict.get`, `isinstance`, `json.dumps`, string slicing.

#### `_parse_timestamp(raw: object) -> datetime`
- **Signature:** `def _parse_timestamp(raw: object) -> datetime`.
- **Parameter `raw`:** the value pulled from `payload["timestamp"]` — typed as `object` because it might be a string, missing, or something weird.
- **Return:** a `datetime`. Always timezone-aware if the input was ISO-8601 with timezone or `Z`; otherwise `datetime.now(timezone.utc)`.
- **What it does:** if `raw` is a non-empty string, replaces a trailing `Z` (ISO's UTC shorthand) with `+00:00` (which `fromisoformat` understands) and calls `datetime.fromisoformat`. On `ValueError`, falls through. In all fallback cases returns `datetime.now(timezone.utc)`.
- **Edge cases:**
  - Empty string: fallback to now.
  - Malformed ISO string: caught, fallback to now.
  - Non-string input (None, dict, …): fallback to now.
  - Already-formed ISO string with `+00:00`: `replace("Z", "+00:00")` is a no-op on it, so it parses fine.
- **Why it exists:** the hook payload's timestamp format is whatever Claude Code chose to send. The trailing-`Z` swap is the one specific incompatibility between ISO-8601 and Python 3.10's `fromisoformat` that we observed and chose to handle. (Python 3.11's `fromisoformat` already accepts `Z`, but the `replace` is harmless and supports older runs.)
- **Concrete examples:**
  - `_parse_timestamp("2026-05-21T12:07:00Z")` → `datetime(2026,5,21,12,7,0, tzinfo=timezone.utc)`.
  - `_parse_timestamp(None)` → `datetime.now(timezone.utc)` (current moment).
- **Called by:** `receive()` (same file).
- **Calls:** `isinstance`, `str.replace`, `datetime.fromisoformat`, `datetime.now`.

#### `_append_to_session_log(classified: ClassifiedEvent, session_id: str, output_dir: str) -> Path`
- **Signature:** `def _append_to_session_log(classified: ClassifiedEvent, session_id: str, output_dir: str) -> Path`.
- **Parameter `classified`:** the event to record.
- **Parameter `session_id`:** the session identifier (already coerced to `str`). Sanitized inside.
- **Parameter `output_dir`:** target directory; created if missing.
- **Return:** the `Path` of the JSONL file that was appended to.
- **What it does:**
  1. Ensures `output_dir` exists.
  2. Sanitizes the session ID via `_sanitize_session_id()` and constructs `path = out / f"session_{safe_id}.jsonl"`.
  3. Builds a flat record dict with `timestamp` (ISO-8601), `raw_text`, `action_type`, `metadata`, `risk_level`, `reason`.
  4. Opens the file in append mode (`"a"`) and writes `json.dumps(record, ensure_ascii=False) + "\n"`.
  5. Returns the path.
- **Edge cases:**
  - File doesn't exist yet: append-mode `open` creates it.
  - Concurrent writes from multiple hook invocations: each call opens, writes one line including the trailing `\n`, then closes. On POSIX, a single line written via one `write()` call is atomic up to PIPE_BUF size; lines longer than that may interleave with concurrent writers. In practice tool-call records are well under any reasonable PIPE_BUF, and Claude Code typically serializes hook firings anyway.
  - JSON serialization failure: would raise — but every field passed in is already JSON-serializable (strings, dicts of strings).
- **Why it exists:** the only way to persist a single classified event without rebuilding the entire report each time. The JSONL format (one JSON object per line) is what enables the live tailer to read events incrementally.
- **Why JSONL and not JSON:** see `Project Explained` for the full discussion. Short version: JSONL is append-only — you write one line and you're done. A whole-file JSON array would require reading, parsing, mutating, and rewriting the entire file on every hook invocation, which is O(n²) over a session and prone to corruption mid-write.
- **Concrete example:**
  - Inputs: classified event with `raw_text="sudo cat /etc/shadow"`, `risk_level="critical"`, `session_id="abc-123"`, `output_dir="./vizhi_reports"`.
  - Effect: appends one line to `./vizhi_reports/session_abc-123.jsonl`:
    ```json
    {"timestamp":"2026-05-21T12:07:00+00:00","raw_text":"sudo cat /etc/shadow","action_type":"command","metadata":{"tool_name":"Bash","source":"hook","cwd":"C:\\Users\\jainp"},"risk_level":"critical","reason":"Privileged command (sudo) — full root access"}
    ```
  - Returns: `WindowsPath('vizhi_reports/session_abc-123.jsonl')` (or `PosixPath` equivalent).
- **Called by:** `receive()` (same file).
- **Calls:** `Path.mkdir`, `_sanitize_session_id`, `Path.open` (append mode), `json.dumps`.

#### `_sanitize_session_id(session_id: str) -> str`
- **Signature:** `def _sanitize_session_id(session_id: str) -> str`.
- **Parameter `session_id`:** any string.
- **Return:** the input with all characters that are not alphanumeric, dash, or underscore stripped out. If the result is empty, returns `"unknown"`.
- **What it does:** path-traversal defense. A `session_id` containing `..` or `/` could be used to write outside `output_dir`. We allow only the strict subset that is safe in filenames on every OS.
- **Edge cases:**
  - `"../../../etc/passwd"` → `"etcpasswd"`.
  - `""` → `"unknown"` (fallback so we never produce `session_.jsonl`).
  - `"abc-123_DEF"` → `"abc-123_DEF"` (unchanged).
- **Why it exists:** without it a malicious or buggy `sessionId` could direct the JSONL output anywhere on the filesystem.
- **Called by:** `_append_to_session_log()` (same file).
- **Calls:** `str.isalnum`, `str.join`.

#### `_get_field(payload: dict[str, Any], *names: str) -> Any`
- **Signature:** `def _get_field(payload: dict[str, Any], *names: str) -> Any`.
- **Parameter `payload`:** the JSON payload dict.
- **Parameter `*names`:** one or more candidate key names. The function returns the value of the first key that is present and not `None`.
- **Return:** the first matching value or `None`.
- **What it does:** convenience for "this field might be `toolName` or `tool_name` depending on which Claude Code build is calling us." Iterates the names in order, returning the first non-`None` `payload.get(name)`.
- **Why it exists:** decouples the receiver from a specific casing convention in the hook payload. Future-proofs against schema variants.
- **Concrete example:**
  - `_get_field({"toolName": "Bash"}, "toolName", "tool_name")` → `"Bash"`.
  - `_get_field({"tool_name": "Bash"}, "toolName", "tool_name")` → `"Bash"`.
  - `_get_field({}, "toolName", "tool_name")` → `None`.
- **Called by:** `receive()` (same file).
- **Calls:** `dict.get`.

#### `_warn(msg: str) -> None`
- **Signature:** `def _warn(msg: str) -> None`.
- **Parameter `msg`:** a short description of the problem.
- **Return:** `None`. Side effect: one line on stderr prefixed with `[vizhi hook warning]`.
- **What it does:** `print(f"[vizhi hook warning] {msg}", file=sys.stderr)`.
- **Why it exists:** centralizes the warning format so future improvements (structured logging, telemetry) only need to touch one function.
- **Called by:** `receive()` (same file).
- **Calls:** `print`.

### Connections
- **Imports:** `json`, `sys`, `datetime.datetime`, `datetime.timezone`, `pathlib.Path`, `typing.IO`, `typing.Any`, `vizhi.classifier.ClassifiedEvent`, `vizhi.classifier.classify_event`, `vizhi.parser.ActionEvent`, `vizhi.parser.ActionType`, plus `from __future__ import annotations`.
- **Imported by:** `cli.py` — imports `receive` (aliased as `hook_receive`). Also invoked as a module via `python -m vizhi.hook_receiver` by the installed Claude Code hook.

---

## `installer.py`

### Simple Explanation
Adds or removes Vizhi's entry from Claude Code's settings file (`~/.claude/settings.json`). The entry tells Claude Code: "after every tool call you make, also run `python -m vizhi.hook_receiver`." Everything else in the settings file is left exactly as the user has it.

### Technical Explanation
Idempotent settings-file editor. Two top-level operations — `install_hook` and `uninstall_hook` — take a parsed settings dict, return `(updated_dict, did_change_flag)`. Both operations are pure: they do not touch the filesystem. Filesystem I/O is the responsibility of `load_settings` and `save_settings`, which the CLI calls before and after. This separation keeps the merge logic unit-testable and makes the destructive write opt-in.

The hook entry follows Claude Code's documented settings schema:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [{"type": "command", "command": "python -m vizhi.hook_receiver"}]
      }
    ]
  }
}
```

Install adds this entry if not already present; uninstall removes any inner hook whose command equals `HOOK_COMMAND`, then cascades pruning (drop empty matcher entries, drop an empty `PostToolUse` list, drop an empty top-level `hooks` key) so the file ends up exactly as it was before install, byte-for-byte except for the indent / trailing newline normalization that `save_settings` applies.

### Module-Level Constants

#### `HOOK_EVENT`
- **Stored value:** the string `"PostToolUse"`.
- **Why a `str`:** the value is a JSON key in Claude Code's settings schema; using a named constant makes intent obvious and lets future changes (e.g. adding `PreToolUse`) reuse the variable name pattern.
- **Where used:** as the key into `settings["hooks"]["PostToolUse"]` in `install_hook` and `uninstall_hook`.

#### `HOOK_MATCHER`
- **Stored value:** the string `"*"` (Claude Code's wildcard meaning "any tool").
- **Why a `str`:** identical reasoning.
- **Where used:** in `_vizhi_matcher_entry`.

#### `HOOK_TYPE`
- **Stored value:** the string `"command"`.
- **Why a `str`:** Claude Code's schema requires this to be one of a small enum of strings; `"command"` is the shell-invocation variant.
- **Where used:** in `_vizhi_matcher_entry`.

#### `HOOK_COMMAND`
- **Stored value:** the string `"python -m vizhi.hook_receiver"`.
- **Why a `str`:** this is the literal shell command Claude Code runs. Pinning it here makes "is this Vizhi's hook?" an exact-string-equality check rather than a fuzzy match.
- **Why bare `python` (not `python3` or an absolute path):** portable across OS conventions. Users with multiple Python versions can intercept by adjusting their `PATH` or `PYTHONHOME`. The TODO at the top of the file (`# TODO(v2.3): support a custom interpreter / venv path instead of bare 'python'.`) tracks the eventual upgrade.
- **Where used:** in `_vizhi_matcher_entry` (when installing) and `_is_vizhi_hook` (when matching existing entries for uninstall or duplicate-detection).

### Functions & Classes

(No classes are defined in this module.)

#### `get_settings_path() -> Path`
- **Signature:** `def get_settings_path() -> Path`.
- **Parameter:** none.
- **Return:** `Path.home() / ".claude" / "settings.json"`. On Windows this typically resolves to `C:\Users\<name>\.claude\settings.json`; on macOS/Linux to `~/.claude/settings.json`.
- **What it does:** the canonical location of Claude Code's user-level settings file. Centralized in a function so future "project-local settings" support (`.claude/settings.json` in the cwd) can be added with one branch.
- **Why it exists:** every command that touches the settings needs this exact path. Without the helper, the literal `Path.home() / ".claude" / "settings.json"` would be sprinkled across multiple files.
- **Called by:** `cli.install_hook_cmd()`, `cli.uninstall_hook_cmd()`.
- **Calls:** `Path.home`.

#### `load_settings(path: Path) -> dict[str, Any]`
- **Signature:** `def load_settings(path: Path) -> dict[str, Any]`.
- **Parameter `path`:** the file to read.
- **Return:** a dict. Returns `{}` if the file does not exist or contains only whitespace.
- **What it does:**
  1. If `path` doesn't exist → return `{}`.
  2. Reads the file as UTF-8.
  3. If the text is whitespace-only → return `{}`.
  4. Parses with `json.loads`. **Lets `JSONDecodeError` propagate** — the caller is expected to surface this so we don't silently overwrite a user-corrupted file.
  5. If the parsed JSON is not a dict (e.g. a list at the root), raises `ValueError` with a descriptive message.
- **Edge cases:**
  - Missing file: returns `{}` (lets `install_hook` start from a fresh dict).
  - Empty file or whitespace-only: returns `{}`.
  - Malformed JSON: raises `JSONDecodeError`; CLI prints the error and exits.
  - JSON is `[]` or `"hello"`: raises `ValueError`; CLI prints and exits.
- **Why it exists:** safe parsing of a user-edited config that may not exist yet. Without the early returns, `install_hook` would have to special-case "file doesn't exist."
- **Concrete example:**
  - Path containing `{"theme": "dark"}` → returns `{"theme": "dark"}`.
  - Path that does not exist → returns `{}`.
- **Called by:** `cli.install_hook_cmd()`, `cli.uninstall_hook_cmd()`.
- **Calls:** `Path.exists`, `Path.read_text`, `json.loads`.

#### `save_settings(path: Path, settings: dict[str, Any]) -> None`
- **Signature:** `def save_settings(path: Path, settings: dict[str, Any]) -> None`.
- **Parameter `path`:** target file (`~/.claude/settings.json`).
- **Parameter `settings`:** the dict to serialize.
- **Return:** `None`. Side effect: writes the file (creating parent directory if missing).
- **What it does:** `path.parent.mkdir(parents=True, exist_ok=True)`, then writes `json.dumps(settings, indent=2, ensure_ascii=False) + "\n"`.
- **Edge cases:**
  - Parent directory missing: created.
  - File exists: overwritten.
  - Write permission denied: raises `PermissionError` (intentional — should not silently fail).
- **Why it exists:** centralizes the "overwrite, with parent creation, pretty-printed, with trailing newline" formatting. Without it, `install_hook_cmd` would need to know about indent levels and newlines.
- **Why `indent=2` and a trailing `\n`:** keeps the file diff-friendly in git and avoids the common "no newline at end of file" warning many editors emit.
- **Why `ensure_ascii=False`:** preserves Unicode characters in any non-vizhi settings the user may have (e.g. a custom prompt with non-ASCII characters), instead of escaping them to `\uXXXX`.
- **Called by:** `cli.install_hook_cmd()`, `cli.uninstall_hook_cmd()`.
- **Calls:** `Path.mkdir`, `Path.write_text`, `json.dumps`.

#### `install_hook(settings: dict[str, Any]) -> tuple[dict[str, Any], bool]`
- **Signature:** `def install_hook(settings: dict[str, Any]) -> tuple[dict[str, Any], bool]`.
- **Parameter `settings`:** the parsed settings dict (possibly empty).
- **Return:** `(updated_settings, already_installed)`.
  - `updated_settings` is the same dict reference, mutated in place (returned for chaining).
  - `already_installed` is `True` if a Vizhi entry was already present (no change made); `False` if a new entry was added.
- **What it does, in order:**
  1. `hooks_root = settings.setdefault("hooks", {})`. If `"hooks"` is present but not a dict, raises `ValueError`.
  2. `post_tool_use = hooks_root.setdefault(HOOK_EVENT, [])`. If `"PostToolUse"` is present but not a list, raises `ValueError`.
  3. If `_vizhi_hook_present(post_tool_use)` returns `True`, returns `(settings, True)` unchanged.
  4. Otherwise, `post_tool_use.append(_vizhi_matcher_entry())` and returns `(settings, False)`.
- **Edge cases:**
  - Settings has `"hooks": [1, 2]` (wrong type): raises `ValueError("settings.hooks is not an object ...")`.
  - Settings has `"hooks": {"PostToolUse": "string"}`: raises similarly for `PostToolUse`.
  - Settings has an unrelated `"hooks": {"PreToolUse": [...]}` but no `"PostToolUse"`: `setdefault` creates `PostToolUse: []`, we add our entry, the existing `PreToolUse` is untouched.
  - Multiple existing `PostToolUse` matcher entries from other tools: we append a new matcher entry alongside; we never merge into someone else's matcher block.
- **Why it exists:** the whole purpose of the installer module. Without it, users would have to hand-edit JSON to enable Vizhi.
- **Idempotence:** if a Vizhi command is already anywhere under any matcher entry under `PostToolUse`, we report "already installed." This means calling install twice does not produce two entries.
- **Why mutate in place rather than deep-copying:** the CLI immediately calls `save_settings(path, updated)` on the result, and the input `settings` is constructed fresh from disk on every call. In-place mutation is faster and simpler; copying would be defensive without purpose.
- **Concrete example:**
  - Input: `{}`. Output: `({"hooks": {"PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python -m vizhi.hook_receiver"}]}]}}, False)`.
  - Input: result of the previous call. Output: same dict, `True`.
- **Called by:** `cli.install_hook_cmd()`.
- **Calls:** `dict.setdefault`, `isinstance`, `_vizhi_hook_present`, `_vizhi_matcher_entry`, `list.append`.

#### `uninstall_hook(settings: dict[str, Any]) -> tuple[dict[str, Any], bool]`
- **Signature:** `def uninstall_hook(settings: dict[str, Any]) -> tuple[dict[str, Any], bool]`.
- **Parameter `settings`:** the parsed settings dict.
- **Return:** `(updated_settings, was_removed)`. `was_removed` is `True` iff at least one Vizhi hook entry was deleted.
- **What it does, in order:**
  1. If `settings["hooks"]` is missing or not a dict, returns `(settings, False)` unchanged.
  2. If `settings["hooks"]["PostToolUse"]` is missing or not a list, returns `(settings, False)`.
  3. Walks each matcher entry in `PostToolUse`. For each:
     - If the matcher entry is not a dict, keep it untouched (don't mess with foreign shapes).
     - If its inner `hooks` field is not a list, keep it untouched.
     - Otherwise, build `kept_inner = [h for h in inner if not _is_vizhi_hook(h)]`. If the length changed, set `removed = True`.
     - If `kept_inner` is non-empty, write it back onto the matcher entry and keep the matcher entry.
     - Else (matcher's inner hooks list is now empty), drop the matcher entry entirely.
  4. If the resulting list of matcher entries is non-empty, write it back to `hooks_root[HOOK_EVENT]`. Otherwise pop `HOOK_EVENT` from `hooks_root`.
  5. If `hooks_root` is now empty, pop `"hooks"` from `settings`.
  6. Return `(settings, removed)`.
- **Edge cases:**
  - User has Vizhi installed alongside other PostToolUse hooks: only Vizhi's entry is removed; the other matcher blocks are preserved.
  - The Vizhi matcher block contained only the Vizhi command: the entire matcher block is pruned.
  - PostToolUse becomes empty after pruning: the `PostToolUse` key is removed.
  - The top-level `hooks` key becomes empty: it is removed too. This is the cascade pruning that ensures uninstall reverses install cleanly.
- **Why it exists:** matches the `install_hook` operation. Without the cascade pruning, repeated install/uninstall cycles would leave the settings file littered with `{}` placeholders.
- **Why preserve non-Vizhi entries even if they look broken:** the function is opinionated only about Vizhi. Anything else is the user's business; we don't second-guess it.
- **Concrete example:**
  - Input: `{"hooks": {"PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python -m vizhi.hook_receiver"}]}]}}`.
  - Output: `({}, True)` — everything is pruned because the only entry was Vizhi's.
  - Input: `{"theme": "dark", "hooks": {"PostToolUse": [{"matcher": "*", "hooks": [{"type":"command","command":"python -m vizhi.hook_receiver"},{"type":"command","command":"echo hi"}]}]}}`.
  - Output: `({"theme": "dark", "hooks": {"PostToolUse": [{"matcher": "*", "hooks": [{"type":"command","command":"echo hi"}]}]}}, True)` — only the Vizhi line is removed; the user's other hook and theme survive.
- **Called by:** `cli.uninstall_hook_cmd()`.
- **Calls:** `dict.get`, `isinstance`, `_is_vizhi_hook`, list/dict mutations.

#### `_vizhi_matcher_entry() -> dict[str, Any]`
- **Signature:** `def _vizhi_matcher_entry() -> dict[str, Any]`.
- **Return:** the literal dict `{"matcher": "*", "hooks": [{"type": "command", "command": "python -m vizhi.hook_receiver"}]}`.
- **What it does:** factory for the install entry. Centralizes the shape so a future schema change is a one-line edit.
- **Called by:** `install_hook()` (same file).

#### `_vizhi_hook_present(post_tool_use: list[Any]) -> bool`
- **Signature:** `def _vizhi_hook_present(post_tool_use: list[Any]) -> bool`.
- **Parameter `post_tool_use`:** the value of `settings["hooks"]["PostToolUse"]`.
- **Return:** `True` if any inner hook anywhere under any matcher equals the Vizhi command.
- **What it does:** flat traversal across all matcher entries' inner `hooks` lists, returns on first match.
- **Why it exists:** the idempotence check for `install_hook`.
- **Called by:** `install_hook()` (same file).
- **Calls:** `isinstance`, `dict.get`, `_is_vizhi_hook`, `any`.

#### `_is_vizhi_hook(entry: Any) -> bool`
- **Signature:** `def _is_vizhi_hook(entry: Any) -> bool`.
- **Parameter `entry`:** any value from a hooks inner list.
- **Return:** `True` if `entry` is a dict whose `"command"` key equals `HOOK_COMMAND`.
- **What it does:** the precise definition of "this is Vizhi's hook entry." Used by both the install duplicate-check and the uninstall removal pass.
- **Why a separate function:** keeps the matching rule in exactly one place. If `HOOK_COMMAND` ever changes (e.g. picks up a custom Python path), updating one constant updates both code paths.
- **Called by:** `_vizhi_hook_present()`, `uninstall_hook()`.

### Connections
- **Imports:** `json`, `pathlib.Path`, `typing.Any`, plus `from __future__ import annotations`.
- **Imported by:** `cli.py` — imports `get_settings_path`, `install_hook`, `load_settings`, `save_settings`, `uninstall_hook`.

---

## `session_viewer.py`

### Simple Explanation
Watches a session's JSONL log file as it is being written and prints each new event live, in the same color-coded format the v1 watcher uses. When the user presses `Ctrl+C`, returns the full list of events it has seen so the CLI can generate a final report.

### Technical Explanation
Polling tail. Opens `session_<sessionId>.jsonl` for reading, drains every complete line already in the file (rendering and collecting each), then loops: every `POLL_INTERVAL_SECONDS` (0.2s) check for new complete lines, render them, sleep again. Partial lines (no trailing `\n`) are not consumed — the file position is rewound so the same line will be re-read once it completes. `KeyboardInterrupt` is caught internally and treated as a clean stop, returning the events list to the caller. If the target file does not exist when the function starts, `_wait_for_file()` blocks for up to `FILE_WAIT_SECONDS` (3s) before raising `FileNotFoundError` with a hint-laden message.

The choice of polling over a native file watcher (`watchdog`, inotify, FSEvents, ReadDirectoryChangesW) is deliberate: zero new dependencies, identical behavior on Windows / macOS / Linux, and 200ms latency is below human perception for a live feed.

### Module-Level Constants

#### `POLL_INTERVAL_SECONDS`
- **Stored value:** the float `0.2`.
- **Why a `float`:** `time.sleep` accepts a float, and 200ms is the natural granularity. Stored as a module constant so a single edit changes both the production polling cadence and the `_wait_for_file` retry cadence.
- **Why 0.2s specifically:** below the ~250ms perceptual threshold for "feels instant" but high enough that 5 polls/second is negligible CPU and I/O cost.
- **Where used:** `tail_session()` (sleep between drains) and `_wait_for_file()` (sleep between existence checks).

#### `FILE_WAIT_SECONDS`
- **Stored value:** the float `3.0`.
- **Why this value:** long enough that "Claude Code is about to fire its first hook" can race with the user starting `vizhi watch` (we want the watch to succeed in that race); short enough that a genuinely wrong session ID errors out quickly.
- **Where used:** `tail_session()` passes it to `_wait_for_file()`.

### Functions & Classes

(No classes are defined in this module.)

#### `find_latest_session(output_dir: str) -> str | None`
- **Signature:** `def find_latest_session(output_dir: str) -> str | None`.
- **Parameter `output_dir`:** directory to scan for `session_*.jsonl` files.
- **Return:** the session ID (the substring between `session_` and `.jsonl`) of the most-recently-modified file, or `None` if the directory does not exist or contains no matching files.
- **What it does:** `Path(output_dir).glob("session_*.jsonl")`, sorted by `st_mtime` descending, takes the first filename, strips the prefix and suffix.
- **Edge cases:**
  - Directory missing: returns `None`.
  - Directory empty (or contains only non-matching files): returns `None`.
  - File named `session_.jsonl` (no id): would return the empty string. Not produced by our writer because `_sanitize_session_id` falls back to `"unknown"`, but tolerated.
- **Why it exists:** lets `vizhi watch` auto-detect the active session without forcing the user to copy a UUID off another window. Without it, every invocation of `watch` would require the explicit `--session-id` flag.
- **Gotcha:** "most recently modified" assumes Claude Code is actively writing to the latest session. If the user runs an old session report and the OS bumps the mtime, that older file would be picked. In practice the auto-detect is right almost always; explicit `--session-id` is the escape hatch.
- **Concrete example:**
  - `./vizhi_reports/` contains `session_abc-123.jsonl` (newer) and `session_old-456.jsonl` (older). Returns `"abc-123"`.
- **Called by:** `cli.watch_cmd()`.
- **Calls:** `Path.exists`, `Path.glob`, `sorted`, `Path.stat`, string slicing.

#### `tail_session(session_id: str, output_dir: str, console: Console) -> list[ClassifiedEvent]`
- **Signature:** `def tail_session(session_id: str, output_dir: str, console: Console) -> list[ClassifiedEvent]`.
- **Parameter `session_id`:** the session whose log to tail. Used to construct the filename `session_<id>.jsonl`.
- **Parameter `output_dir`:** directory containing the log.
- **Parameter `console`:** the Rich console for live rendering. Shared with the CLI so banners and event lines interleave naturally.
- **Return:** the full list of `ClassifiedEvent`s observed during the tail, in arrival order. Empty list if `Ctrl+C` is pressed before any events appear.
- **What it does, in order:**
  1. Builds `path = Path(output_dir) / f"session_{session_id}.jsonl"`.
  2. Calls `_wait_for_file(path, FILE_WAIT_SECONDS)` — blocks up to 3 seconds for the file to appear, raises `FileNotFoundError` otherwise.
  3. Opens the file for text reading (UTF-8 default).
  4. Drains any pre-existing lines via `_drain(f, events, console)`.
  5. Loops forever: `_drain(...)`; if no lines consumed this cycle, `time.sleep(POLL_INTERVAL_SECONDS)`; if some were consumed, immediately try again (drain may yield a burst).
  6. On `KeyboardInterrupt` inside the loop, returns `events`.
- **Edge cases:**
  - File never appears: `_wait_for_file` raises after 3 seconds.
  - File appears but is empty: `_drain` consumes zero lines, the poll sleep kicks in, the loop waits for content.
  - Malformed JSON line mid-stream: `_drain` prints a `[vizhi watch] skipping malformed line` warning in dim red and keeps going.
  - File rotated or truncated by another process: not specifically handled; `f.tell()` / `f.seek()` would behave oddly. In practice the JSONL files are append-only.
- **Why it exists:** the user-facing live view of a session. Without it, the user would have to `tail -f session_*.jsonl | jq` and lose the color-coded rendering.
- **Why `KeyboardInterrupt` is caught inside (not at the CLI layer):** spec asked for it. Having the function return cleanly with the partial events list lets the CLI generate a report; raising would force the CLI to either lose events or catch and re-implement the return.
- **Concrete example:**
  - Pre-existing file `./vizhi_reports/session_abc-123.jsonl` has two lines (one Bash `ls`, one Read of `/etc/passwd`). The function prints both immediately (one info, one critical), then waits. The user runs a Bash command in Claude Code; the hook appends one more line; this function picks it up within 200ms, renders it, appends to the list. The user presses Ctrl+C. The function returns the three-event list.
- **Called by:** `cli.watch_cmd()`.
- **Calls:** `Path`, `_wait_for_file`, `Path.open`, `_drain`, `time.sleep`.

#### `_wait_for_file(path: Path, timeout_seconds: float) -> None`
- **Signature:** `def _wait_for_file(path: Path, timeout_seconds: float) -> None`.
- **Parameter `path`:** the file to wait for.
- **Parameter `timeout_seconds`:** how long to wait. Uses `time.monotonic()` so wall-clock adjustments do not skew the deadline.
- **Return:** `None`. Raises `FileNotFoundError` with a long helpful message on timeout.
- **What it does:** computes a `deadline = time.monotonic() + timeout_seconds`. Loops: if path exists, return; else if past the deadline, raise; else sleep `POLL_INTERVAL_SECONDS` and try again.
- **Edge cases:**
  - File already exists: returns immediately without sleeping.
  - File appears within the window: returns as soon as the next poll observes it (worst-case latency = `POLL_INTERVAL_SECONDS`).
  - File never appears: raises with a message that names the path and recommends `vizhi install-hook`.
- **Why it exists:** the race between `vizhi watch` and Claude Code's first hook fire is common (especially in scripted tests). Tolerating a brief absence is the difference between "it just works" and "race-flaky."
- **Why `time.monotonic` and not `time.time`:** monotonic is unaffected by NTP corrections, so a system clock adjustment during the wait will not extend or shrink the window.
- **Called by:** `tail_session()` (same file).
- **Calls:** `time.monotonic`, `Path.exists`, `time.sleep`.

#### `_drain(f: IO[str], events: list[ClassifiedEvent], console: Console) -> int`
- **Signature:** `def _drain(f: IO[str], events: list[ClassifiedEvent], console: Console) -> int`.
- **Parameter `f`:** the open file handle (text mode).
- **Parameter `events`:** the running list to append to.
- **Parameter `console`:** the Rich console for live rendering.
- **Return:** an `int` — the number of complete lines consumed on this call. The tail loop uses this to decide whether to sleep (0 = "nothing new, wait") or immediately try another drain (>0 = "there might be more pending").
- **What it does:**
  1. Loops indefinitely.
  2. `pos = f.tell()` — remember our position before the read.
  3. `line = f.readline()`. If `line == ""`, we hit EOF → return `consumed`.
  4. If `not line.endswith("\n")`, the line is partial (the writer is mid-line); `f.seek(pos)` to put us back, return `consumed`. The next drain will re-read this line.
  5. Strip whitespace. If empty, continue (skip blank lines).
  6. Try `_event_from_line(stripped)`. On JSON / Key / Value error, print a `[vizhi watch] skipping malformed line` warning in dim red and continue.
  7. Append the event, render it, increment `consumed`.
- **Edge cases:**
  - Empty file: first `readline` returns `""`, return 0.
  - A line written character-by-character and observed partway: detected by the `endswith("\n")` check; we rewind to `pos` and re-read on the next poll. Without this guard, a half-line would be misparsed as JSON and discarded.
  - A line that round-trips fine but represents an event we cannot decode (e.g. missing `risk_level` key): caught as `KeyError`, line is skipped with a warning.
- **Why it exists:** the inner "read whatever is there right now without blocking" loop. Without partial-line handling, the tailer would corrupt every event whose write straddled a poll boundary.
- **Why `f.tell()` / `f.seek()` matter:** they are the only correct way to roll back a partial read in Python's text mode. Just buffering the partial line in memory would also work but adds state we do not need.
- **Concrete example:**
  - File contains `{"timestamp":...,"raw_text":"ls",...}\n`. `_drain` reads the line, parses it, renders it, appends to `events`, returns `1`.
  - File contains `{"timestamp":...,"raw_text":"ls",...}` (no trailing newline yet). `_drain` reads the bytes, sees no `\n`, seeks back to the start of the line, returns `0`. On the next call (perhaps after the writer's flush), the now-complete line is consumed.
- **Called by:** `tail_session()` (same file).
- **Calls:** `f.tell`, `f.readline`, `f.seek`, `str.endswith`, `str.strip`, `_event_from_line`, `list.append`, `render_event`, `console.print`.

#### `_event_from_line(raw: str) -> ClassifiedEvent`
- **Signature:** `def _event_from_line(raw: str) -> ClassifiedEvent`.
- **Parameter `raw`:** a single line of JSON (no trailing newline expected — the caller strips).
- **Return:** a fresh `ClassifiedEvent` containing a fresh `ActionEvent`.
- **What it does:** `data = json.loads(raw)`; validates it is a dict; constructs `ActionEvent(timestamp=datetime.fromisoformat(data["timestamp"]), raw_text=data["raw_text"], action_type=data["action_type"], metadata=dict(data.get("metadata", {})))`; constructs `ClassifiedEvent(event=event, risk_level=data["risk_level"], reason=data["reason"])`.
- **Edge cases:**
  - `data` is a list at the root: raises `ValueError`, surfaced as a malformed-line warning by `_drain`.
  - Missing required key: raises `KeyError`, surfaced similarly.
  - Timestamp not parseable: raises `ValueError` from `fromisoformat`, surfaced similarly.
  - `metadata` absent: defaults to `{}` via `data.get("metadata", {})`.
- **Why it exists:** the symmetric inverse of `hook_receiver._append_to_session_log`'s record builder. Pulled out as a separate function so the parsing is in one place and the error types are easy to enumerate at the call site.
- **Concrete example:**
  - Input: `'{"timestamp":"2026-05-21T12:07:00+00:00","raw_text":"ls","action_type":"command","metadata":{},"risk_level":"info","reason":"No risk indicators matched"}'`.
  - Output: a fresh `ClassifiedEvent` wrapping a fresh `ActionEvent` with those field values.
- **Called by:** `_drain()` (same file).
- **Calls:** `json.loads`, `isinstance`, `datetime.fromisoformat`, `dict`, the `ActionEvent` and `ClassifiedEvent` constructors.

### Connections
- **Imports:** `json`, `time`, `datetime.datetime`, `pathlib.Path`, `typing.IO`, `rich.console.Console`, `vizhi.classifier.ClassifiedEvent`, `vizhi.parser.ActionEvent`, `vizhi.watcher.render_event`, plus `from __future__ import annotations`.
- **Imported by:** `cli.py` — imports `find_latest_session`, `tail_session`.
