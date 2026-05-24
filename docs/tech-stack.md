# Tech Stack

Every technology, library, format, tool, and standard that Vizhi uses today, plus what is planned for the next phase of the project.

For each entry: a beginner-friendly analogy, the exact version in use and where the version is pinned, the specific problem in Vizhi it solves, what the code would look like without it (what we would write manually), a concrete real example pulled from the codebase, and the alternatives we considered and why we did not pick them.

---

## Current Stack

### Python 3.11+

**Beginner-friendly analogy.** Python is the language we write all the code in. Like English vs. French as a way to write a novel — same ideas, different surface.

**Exact version.** `requires-python = ">=3.11"` in `pyproject.toml`. The minimum is Python 3.11. Python 3.12 is also supported (declared in the `classifiers` block). The version string lives at `pyproject.toml:10` and the classifier list at `pyproject.toml:17-25`.

**Problem it solves.** Provides the runtime, the standard library, the type system, and the syntax. Picking 3.11 specifically buys us: native `from __future__ import annotations` is no longer strictly required for forward references (the language now defers annotation evaluation by default in some contexts), the standard library's `datetime.fromisoformat` accepts the `Z` suffix natively, and the typing module has `Self`, `LiteralString`, and improved `Literal` handling.

**What the code would look like without it.** Without Python at all: every module would be written in another language (Go, Rust, Node) and the same data model — frozen dataclasses, Literal-typed risk levels, the rule engine — would have to be expressed in that language's idioms. Without specifically Python 3.11 (say, 3.9): we would need to replace `dict[str, str]` with `Dict[str, str]` (post-PEP 585 dict-as-generic), backport `tomllib`, manually handle the `Z` in ISO timestamps, and skip the cleaner `Literal` ergonomics.

**Concrete example.** Type-hinted function signatures we rely on:

```python
def find_latest_session(output_dir: str) -> str | None:
```

That `str | None` union syntax (PEP 604) requires Python 3.10+. We use it freely across the codebase.

**Alternatives and why not.** Go would buy us static typing and a single binary, but lose us the readability and the throwaway-script ergonomics that make a 1.5k-LOC CLI fast to evolve. Rust would buy us speed and memory safety, but the time-to-feature cost is too high for an alpha. Node + TypeScript would buy us a shared language with the eventual React frontend, but split the codebase between two ecosystems and force us to reimplement Python's mature `dataclasses` and `pathlib`.

---

### Click (>=8.1.0)

**Beginner-friendly analogy.** A library that turns Python functions into command-line commands. Instead of parsing `sys.argv` by hand and writing `if-elif` for each subcommand, you decorate a function and Click generates the parser, the `--help` text, and the error messages.

**Exact version.** `click>=8.1.0` in `pyproject.toml:29`. Click 8.x has the modern `@click.group` / `@click.command` API and the `click.Path` type validator.

**Problem it solves.** Vizhi has six subcommands (`start`, `report`, `hook`, `watch`, `install-hook`, `uninstall-hook`), each with its own options. Without Click we'd have to write our own subcommand dispatcher and option parser.

**What the code would look like without it.** A bespoke `argparse` setup with one `add_subparsers()` block and one `set_defaults(func=...)` per subcommand. Roughly 60 lines of imperative wiring. Plus we'd have to write our own `--version` flag, `--help` formatting, type coercion for `--output-dir`, and a registration mechanism for the installed CLI script. With Click it's six decorators and the work is done.

**Concrete example** from `cli.py:135-152`:

```python
@main.command(
    "watch",
    help="Tail a live Claude Code session JSONL log and report on Ctrl+C.",
)
@click.option(
    "--session-id",
    "session_id",
    default=None,
    help="Session ID to watch. If omitted, the most recent session is auto-detected.",
)
@click.option(
    "--output-dir",
    "output_dir",
    default=DEFAULT_OUTPUT_DIR,
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Directory containing session_<sessionId>.jsonl files.",
)
def watch_cmd(session_id: str | None, output_dir: str) -> None:
```

Six lines of decoration produce a fully validated subcommand with `--session-id`, `--output-dir`, `--help`, and type checking. The `click.Path(file_okay=False, dir_okay=True)` validator alone would be a dozen lines of manual `os.path` checks.

**Alternatives and why not.** `argparse` (standard library) is verbose, lacks built-in subcommand decorators, and produces uglier help text. `typer` is a thin wrapper over Click — same dependency tree but adds magic that obscures what's happening. `docopt` parses your help string, which is clever but fragile; reordering options can break parsing. `fire` auto-generates CLIs from any object, which is *too* magical for production use. Click is the boring, battle-tested choice.

---

### Rich (>=13.7.0)

**Beginner-friendly analogy.** A library that makes terminal output look good — colored text, formatted tables, bordered panels, syntax highlighting. Think of it as Bootstrap for the command line.

**Exact version.** `rich>=13.7.0` in both `pyproject.toml:28` and `requirements.txt:1`. Rich 13.x has the stable `Console`, `Panel`, `Table`, and `Text` APIs we use.

**Problem it solves.** Vizhi's value is largely visual: a color-coded live feed and a tabular session summary. Doing this with raw ANSI escape codes would be tedious and platform-fragile (Windows terminals historically required special handling).

**What the code would look like without it.** Every line of the live feed would be a hand-built ANSI string like `f"\x1b[1;31m{label}\x1b[0m"`. Each `Table` would be a manual column-width computation, padding loop, and divider character. The `Panel` border would be three lines of box-drawing characters. We would also have to detect terminal capability (TTY? color depth? width?) manually. Probably 200+ extra lines for what Rich does in 10.

**Concrete example** from `watcher.py:41-54`:

```python
def render_event(console: Console, classified: ClassifiedEvent) -> None:
    event = classified.event
    style = RISK_STYLES[classified.risk_level]
    label = RISK_LABELS[classified.risk_level]
    ts = event.timestamp.strftime("%H:%M:%S")

    line = Text()
    line.append(f"[{ts}] ", style="dim")
    line.append(f"{label} ", style=style)
    line.append(f"({event.action_type}) ", style="dim cyan")
    line.append(event.raw_text, style=style)
    line.append(f"  — {classified.reason}", style="dim")
    console.print(line)
```

`Text` and its `.append(text, style=...)` API let us compose styled output in five readable lines. Rich handles the ANSI generation, the TTY detection, the Windows compatibility, and the markdown-style style strings (`"bold red"`).

And from `reporter.py:90-104` for tables:

```python
table = Table(title="Risk Breakdown", header_style="bold", show_lines=False)
table.add_column("Risk", justify="left")
table.add_column("Count", justify="right")
table.add_column("Percent", justify="right")
...
for lvl in RISK_ORDER:
    count = report.risk_breakdown.get(lvl, 0)
    pct = (count / total) * 100.0 if report.total_actions else 0.0
    table.add_row(
        f"[{RISK_STYLES[lvl]}]{lvl}[/]",
        str(count),
        f"{pct:.1f}%",
    )
console.print(table)
```

**Alternatives and why not.** `colorama` only handles colors (not tables, panels, or layout) and requires explicit init calls on Windows. `prompt_toolkit` is heavyweight, oriented at interactive REPLs, not one-shot output. `blessed`/`blessings` have not kept up with modern terminal capabilities. Raw ANSI escapes would work but reinvent half of what Rich provides. Rich is the right scope: enough features, not too many, very widely adopted.

---

### Python `dataclasses` (standard library)

**Beginner-friendly analogy.** A decorator that turns a class-with-fields into a fully functional value object. Instead of writing `__init__`, `__repr__`, and `__eq__` by hand, you list the fields and Python writes those methods for you.

**Exact version.** Standard library. Available since Python 3.7. We use 3.11+ behavior. No pin needed — it ships with the interpreter.

**Problem it solves.** Three data types (`ActionEvent`, `ClassifiedEvent`, `SessionReport`) are pure value bundles. Writing each one as a regular class would mean ~15 lines of boilerplate per class (constructor, repr, equality). With `@dataclass`, it's the field list and that's it.

**What the code would look like without it.** A regular class:

```python
class ActionEvent:
    def __init__(self, timestamp, raw_text, action_type, metadata=None):
        self.timestamp = timestamp
        self.raw_text = raw_text
        self.action_type = action_type
        self.metadata = metadata if metadata is not None else {}

    def __repr__(self):
        return (f"ActionEvent(timestamp={self.timestamp!r}, raw_text={self.raw_text!r}, "
                f"action_type={self.action_type!r}, metadata={self.metadata!r})")

    def __eq__(self, other):
        if not isinstance(other, ActionEvent):
            return NotImplemented
        return (self.timestamp == other.timestamp and self.raw_text == other.raw_text
                and self.action_type == other.action_type and self.metadata == other.metadata)

    def __hash__(self):
        return hash((self.timestamp, self.raw_text, self.action_type))  # if hashable wanted
```

vs. the dataclass version (10 fewer lines and harder to forget a field):

```python
@dataclass(frozen=True)
class ActionEvent:
    timestamp: datetime
    raw_text: str
    action_type: ActionType
    metadata: dict[str, str] = field(default_factory=dict)
```

**Concrete example.** Every value type in the codebase: `ActionEvent` (`parser.py:53-61`), `ClassifiedEvent` (`classifier.py:79-85`), `SessionReport` (`reporter.py:32-42`).

**Alternatives and why not.** `attrs` is a third-party library that predates `dataclasses` and offers more features (validators, converters, `__slots__`). But `dataclasses` is in the standard library — no extra dependency for the same core feature set. Pydantic adds runtime validation and JSON-schema generation, useful for API boundaries; overkill for an internal value object that is already typed. Named tuples (`typing.NamedTuple`) are immutable by default but lack the field-default-factory and the per-field type annotations are stuck inside a tuple shape; they read worse for fields with mutable defaults like our `metadata: dict[str, str]`.

---

### Frozen dataclasses (`@dataclass(frozen=True)`)

**Beginner-friendly analogy.** A regular dataclass is a labeled cardboard box: open lid, swap contents, close lid. A frozen dataclass is a sealed envelope: once closed, the contents cannot be changed without breaking the seal.

**Exact version.** Standard library `dataclasses` module — `frozen=True` parameter is available since Python 3.7. Same version pin as `dataclasses` itself.

**Problem it solves.** Once an event has been classified and added to the session log, nothing in the pipeline should ever change its fields. Reassignments are a common source of subtle bugs — the live feed shows one thing, the saved JSON another, and you can't tell which version is "correct." Freezing the dataclass means every accidental mutation fails loudly at the moment it happens, with a clear `FrozenInstanceError`.

**What the code would look like without it.** Every consumer of `ClassifiedEvent` would have to either (a) trust that no other consumer mutates the shared instance, or (b) deep-copy defensively before every operation. We would also have to write manual `__setattr__` overrides to reject assignment. A frozen dataclass replaces all of that with one keyword argument.

**Concrete example** from `classifier.py:79-85`:

```python
@dataclass(frozen=True)
class ClassifiedEvent:
    event: ActionEvent
    risk_level: RiskLevel
    reason: str
```

If anywhere in the pipeline someone writes `classified.risk_level = "info"`, Python raises:

```
dataclasses.FrozenInstanceError: cannot assign to field 'risk_level'
```

Immediately, with the line number, instead of producing silently corrupted output 30 minutes later.

A second benefit: frozen dataclasses are hashable (`__hash__` is autogenerated). That means a future caller can deduplicate or group events using `set()` or dict keys without writing manual hashing logic.

**Alternatives and why not.** Manual `__setattr__` override is verbose and easy to break. `typing.Final` only marks variables as not-to-be-reassigned at the type-checker level; it does not enforce runtime immutability. `frozenset` and `tuple` are immutable but lose the named-field ergonomics. `attrs` offers `frozen=True` too, but `dataclasses` does it equally well without an extra dep.

---

### `Literal` types (`typing.Literal`)

**Beginner-friendly analogy.** A type that says "this value must be one of these exact strings." Like an enum, but the values themselves are first-class strings — no `.value` accessor, no boilerplate.

**Exact version.** Standard library `typing` module. Available since Python 3.8 (`Literal`). We use Python 3.11's enhanced Literal narrowing.

**Problem it solves.** Two of Vizhi's core categorical fields — `action_type` and `risk_level` — have small fixed sets of legal values. We want a typo (`"hgh"` instead of `"high"`) to be a type error at write time, not a runtime KeyError when someone tries to look it up in `RISK_STYLES`.

**What the code would look like without it.** Plain `str` with no type-level enforcement. A typed enum (`enum.Enum`) would add `.value` accessors and break JSON serialization (you'd serialize `RiskLevel.CRITICAL.value` instead of `"critical"`). String constants would not help the type checker.

**Concrete example** from `parser.py:9` and `classifier.py:10`:

```python
ActionType = Literal["command", "file_access", "network", "unknown"]
RiskLevel = Literal["critical", "high", "medium", "low", "info"]
```

Used in `parser.py:54-61`:

```python
@dataclass(frozen=True)
class ActionEvent:
    timestamp: datetime
    raw_text: str
    action_type: ActionType
    ...
```

And in `classifier.py:88`:

```python
def classify_event(event: ActionEvent) -> ClassifiedEvent:
```

If someone writes `event.action_type == "explosion"`, mypy/pyright flags it: `Argument 2 to "ActionEvent" has incompatible type "Literal['explosion']"; expected "Literal['command', 'file_access', 'network', 'unknown']"`.

**Alternatives and why not.** `enum.Enum` carries the `.value` overhead and forces JSON serialization gymnastics. Plain `str` constants like `ACTION_COMMAND = "command"` provide no type-checker help and are typo-prone. A `Final` constant of allowed values (`ALLOWED_TYPES: Final = ("command", ...)`) would catch nothing statically. `Literal` is the minimal-overhead solution.

---

### Type hints (PEP 484, PEP 604, PEP 585)

**Beginner-friendly analogy.** Notes you write next to each function parameter saying "this should be a string" or "this returns an integer." Optional — Python still runs without them — but they let editors and static checkers find bugs before you run the code.

**Exact version.** Built into Python. PEP 484 type hints are 3.5+; the `list[int]` / `dict[str, str]` syntax (PEP 585) is 3.9+; the `X | Y` union syntax (PEP 604) is 3.10+. We require 3.11+, so all three are available without `from __future__ import annotations`. We use the `__future__` import anyway as a defensive measure (see its own entry).

**Problem it solves.** Documentation that the editor enforces. Lets contributors and readers know exactly what every function expects and returns without spelunking through usages. A static checker (mypy, pyright) can catch entire bug classes before tests run.

**What the code would look like without them.** Functions defined as `def receive(source=None, output_dir="./vizhi_reports"):` with no signal about what `source` should be or what gets returned. Readers would have to infer types from usage; type checkers would be silent.

**Concrete example** from `hook_receiver.py:45-48`:

```python
def receive(
    source: IO[str] | None = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> int:
```

The signature tells you that `source` is a text I/O object or `None`, `output_dir` is a string, and the function returns an `int` (which the CLI uses as the process exit code). A reader who has never seen `receive()` can call it confidently without reading the body.

Or `session_viewer.py:54-58`:

```python
def tail_session(
    session_id: str,
    output_dir: str,
    console: Console,
) -> list[ClassifiedEvent]:
```

`list[ClassifiedEvent]` is PEP 585 — the lowercased generic. Without it we'd need `from typing import List` and write `List[ClassifiedEvent]`.

**Alternatives and why not.** Docstrings can document types but the type checker cannot read them. Comments are unenforceable. Runtime type checking (e.g. `pydantic`) catches bugs only when the code runs, not at edit time, and adds dependency overhead. Static type hints are free, optional, ignorable, and immediately useful.

---

### JSON Lines (JSONL) format

**Beginner-friendly analogy.** Imagine a notebook where each page is a separate JSON object. You can rip out a page and read it without flipping through the rest of the notebook. New entries get added to the back as new pages, not by re-binding the whole book.

**Exact version.** Format spec at https://jsonlines.org. No library required — it is literally "one JSON object per line, terminated by `\n`." Used in `hook_receiver._append_to_session_log` (writes) and `session_viewer._drain` / `_event_from_line` (reads).

**Problem it solves.** The hook receiver writes one event at a time, and the live tailer reads one event at a time. JSON arrays would force the writer to rewrite the whole file on every append (O(n²) over a session) and would leave the file unparseable after a mid-write crash. JSONL is O(1) per append, append-safe, and tail-friendly.

**What the code would look like without it.** Two options, both bad:
1. **Plain JSON array** — every hook firing reads the entire file, parses it as JSON, appends to the list, writes it back. For a 1000-event session that's a million read/write operations. A mid-write crash leaves an unterminated `[...,` that no parser will accept. Concurrent writes silently corrupt the file.
2. **Custom binary log** — invents a new format, requires a custom reader and writer, no `tail -f`-style debugging.

JSONL gives us a one-line writer (`f.write(json.dumps(record) + "\n")`), a one-line reader (`json.loads(line)`), and a debuggability win (`jq < session.jsonl` just works).

**Concrete example** from `hook_receiver.py:165-175`:

```python
record: dict[str, Any] = {
    "timestamp": classified.event.timestamp.isoformat(),
    "raw_text": classified.event.raw_text,
    "action_type": classified.event.action_type,
    "metadata": classified.event.metadata,
    "risk_level": classified.risk_level,
    "reason": classified.reason,
}
with path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

And the reader in `session_viewer.py:99-128`:

```python
def _drain(f: IO[str], events: list[ClassifiedEvent], console: Console) -> int:
    consumed = 0
    while True:
        pos = f.tell()
        line = f.readline()
        if not line:
            return consumed
        if not line.endswith("\n"):
            f.seek(pos)
            return consumed
        ...
```

Note the `f.tell()` / `f.seek(pos)` pattern — JSONL's per-line discipline makes mid-write recovery trivial. With a JSON array there is no equivalent.

**Alternatives and why not.** Plain JSON: O(n²), unsafe under partial writes, hostile to live tailing. SQLite: needs a schema migration story, locking under concurrent writers, harder for humans to grep. MessagePack / CBOR: binary formats, not greppable, not tail-friendly, force a dependency. CSV: lossy for nested fields like `metadata`. JSONL is the right shape for "many small append-only records you want to read incrementally."

---

### JSON format

**Beginner-friendly analogy.** A way to write structured data — objects, lists, strings, numbers — as plain text. Like XML's better-looking younger sibling. Universally readable by every language and tool.

**Exact version.** RFC 8259. Used via Python's standard library `json` module — no version pin needed.

**Problem it solves.** The final session report needs to be a single self-describing document with top-level aggregates (`total_actions`, `risk_breakdown`) and arrays of events. JSON is the natural fit: structured, language-agnostic, human-readable.

**What the code would look like without it.** A custom serializer for `SessionReport` (the work `_report_to_dict` and `_classified_to_dict` already do, plus the actual byte-level encoding). Probably 50 lines of escaping, indentation, and type conversion.

**Concrete example** from `reporter.py:132-143`:

```python
def save_report(report: SessionReport, output_dir: str = "./vizhi_reports") -> str:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    ts_slug = report.started_at.strftime("%Y%m%dT%H%M%SZ")
    filename = f"session_{report.session_id}_{ts_slug}.json"
    file_path = out_path / filename

    payload = _report_to_dict(report)
    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(file_path)
```

`json.dumps(payload, indent=2)` does all the formatting. UTF-8 encoding is explicit so the file is portable across OSes.

**Alternatives and why not.** YAML: human-friendlier for hand-edited configs but ambiguous (the `NO` country code parsing as `False`, indentation traps) and slower. TOML: better for configs but not for nested data with arrays. XML: verbose, requires an XML parser, hostile to humans reading it. Protobuf: schema-first, requires `.proto` files and code gen, overkill for a self-contained record. CSV: cannot represent nested fields. JSON is the universal lingua franca of structured-but-not-binary data.

---

### Claude Code PostToolUse hook system

**Beginner-friendly analogy.** Claude Code is a workshop where the AI is the carpenter. The PostToolUse hook is a CCTV camera that turns on every time the carpenter picks up a tool. The hook calls our program and shows us exactly which tool, what input, what came back.

**Exact version.** Documented at https://docs.claude.com/en/docs/claude-code/hooks. The contract: when a tool fires, Claude Code reads `~/.claude/settings.json`, finds the matching `PostToolUse` matcher, spawns the hook command (`type: "command"`), and pipes a JSON payload to its stdin. The payload includes `toolName`, `toolInput`, `toolResponse`, `sessionId`, `cwd`, `timestamp`. We capture the schema in `hook_receiver.py:71-86`.

**Problem it solves.** Without hooks, Vizhi can only see what Claude Code prints to its terminal — a lossy text view. With hooks, Vizhi sees the structured tool input directly, including parameters that never appear in stdout (file paths, URLs, command arguments).

**What the code would look like without it.** We would have to scrape Claude Code's stdout via the v1 stdin watcher and infer tool calls from text. Many tool calls would be partially or fully invisible. We would also lose the structured `sessionId`, which is what lets us group events into per-conversation logs.

**Concrete example** of how the hook is configured (the JSON Vizhi writes into `~/.claude/settings.json`):

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

The matcher `"*"` means "match every tool." After every tool call, Claude Code runs `python -m vizhi.hook_receiver` and pipes a payload like:

```json
{
  "hookEvent": "PostToolUse",
  "toolName": "Bash",
  "toolInput": {"command": "git status"},
  "toolResponse": {"stdout": "...", "exitCode": 0},
  "sessionId": "abc-123",
  "cwd": "C:\\Users\\jainp\\OneDrive\\Desktop\\Projects\\vizhi",
  "timestamp": "2026-05-24T15:07:00.123Z"
}
```

Our `receive()` function (`hook_receiver.py:45`) handles the parsing.

**Alternatives and why not.** Polling Claude Code's session files: undocumented, fragile, requires reverse-engineering. Eavesdropping on the LLM API: only works for the API path, not the CLI/IDE path; also exposes prompts that are sensitive. Stdin scraping via the v1 watcher: lossy and incomplete. Hooks are the documented, supported, structured channel — exactly what we want.

---

### Claude Code hooks (the broader hooks framework)

**Beginner-friendly analogy.** Claude Code's hooks system lets external programs run at specific lifecycle moments — before a tool runs (PreToolUse), after (PostToolUse), at session start (SessionStart), and so on. Each hook gets a JSON payload describing the event.

**Exact version.** Same as PostToolUse above — documented in https://docs.claude.com/en/docs/claude-code/hooks. Vizhi currently uses only PostToolUse. PreToolUse is on the roadmap (see `# TODO(v2.2):` in `hook_receiver.py:40`).

**Problem it solves.** Provides the integration surface between Claude Code and any external observer or interceptor. Vizhi uses it for observation today; v3 will likely use PreToolUse for blocking on critical risk.

**What the code would look like without it.** We would have to fork Claude Code (impossible — closed source) or build our own AI agent shell that integrates Vizhi directly. The hooks system is the only sanctioned way to inject behavior.

**Concrete example.** Vizhi's `installer.py:1-19` documents the schema we adhere to and writes:

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

The `matcher` field can be `"*"`, a specific tool name (`"Bash"`), or a list — we use `"*"` because we want to see every tool call.

**Alternatives and why not.** Building our own AI runtime: we'd lose the entire Claude Code ecosystem and become a competing product. MCP server wrapping every tool: complex, requires the user to reroute all their tools through Vizhi, and PreToolUse hooks already exist to do this in a sanctioned way. Patching Claude Code: not allowed and would break on every update.

---

### `pyproject.toml` + setuptools

**Beginner-friendly analogy.** `pyproject.toml` is the file that tells `pip` how to install your project — what the package is named, who wrote it, what dependencies it needs, and what command-line scripts it provides. Setuptools is the build tool that reads `pyproject.toml` and produces an installable artifact.

**Exact version.** `setuptools>=68` and `wheel` declared in `pyproject.toml:2`. `build-backend = "setuptools.build_meta"` at line 3. The PEP that defines the `[project]` table is PEP 621.

**Problem it solves.** Standardized packaging. `pyproject.toml` replaces the older `setup.py` (executable Python that ran at install time, often with side effects) with a declarative TOML file that pip can read without executing.

**What the code would look like without it.** A `setup.py` with a `setup()` call, plus a `setup.cfg` for declarative bits — the historical Python packaging story. More boilerplate, less standardized, more security surface (setup.py can run arbitrary code).

**Concrete example** from `pyproject.toml:5-30`:

```toml
[project]
name = "vizhi"
version = "0.1.0"
description = "Real-time security monitor for AI agents — watches commands, file access, and network calls, flags risky behavior, and generates session reports."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [
  { name = "Vizhi Contributors" },
]
keywords = ["security", "ai", "monitoring", "claude", "agents"]
classifiers = [...]
dependencies = [
  "rich>=13.7.0",
  "click>=8.1.0",
]

[project.scripts]
vizhi = "vizhi.cli:main"
```

The `[project.scripts]` block is what makes `vizhi` a command-line tool after `pip install -e .` — setuptools generates a wrapper script that imports `vizhi.cli:main` and invokes it.

**Alternatives and why not.** `poetry`: opinionated, alternative dependency resolver, but adds a tool layer between the developer and pip. `hatch`: similar tradeoffs. `flit`: simpler but less feature-complete. `setup.py` alone: legacy, executes arbitrary code at install. The PEP 621 + setuptools combination is the standard-library blessed path with the largest ecosystem of tooling.

---

### `pip install -e .` (editable installs)

**Beginner-friendly analogy.** Normally `pip install` copies the package files into Python's site-packages so they live separately from the source. An editable install instead creates a pointer from site-packages back to the source directory. You edit the source, you re-run the command, the change takes effect — no reinstall needed.

**Exact version.** Pip 21.3+ supports PEP 660 editable installs (which is what setuptools-backed `pyproject.toml` projects use). Earlier pip versions also support `-e` via setup.py.

**Problem it solves.** Lets developers iterate on Vizhi without re-installing after every edit. The installed `vizhi` script always reflects the current source.

**What the code would look like without it.** Every change would require `pip uninstall vizhi && pip install .`. Painful and slow.

**Concrete example.** The README documents `pip install -e .` as the canonical install. After running it once in the project root, every edit to `vizhi/cli.py` immediately changes what `vizhi --help` prints — no reinstall.

**Alternatives and why not.** `python -m vizhi.cli` directly: works during dev but doesn't exercise the same entry-point script the user will get from PyPI. `tox` / `nox` for tests: useful for CI but doesn't help the dev loop. `pipx install -e .`: similar but isolates into its own venv. `pip install -e .` is the minimum-friction option.

---

### Git

**Beginner-friendly analogy.** A time machine for code. Every commit is a snapshot; you can rewind, branch off into alternate histories, and merge them back together.

**Exact version.** Whatever the user has installed (we do not pin). The repo is initialized as a Git repository — `git log` shows commits like `ce04c3c docs: update CLAUDE.md to v2.4 scope`.

**Problem it solves.** Version control, collaboration, code review, and rollback. Without it the project would be a single mutable directory with no history.

**What the code would look like without it.** A directory full of files with no history. Every "what changed" question would require re-reading the source carefully. Every "let me try something" experiment would require manual file copies.

**Concrete example.** Recent commits visible via `git log`:

```
ce04c3c docs: update CLAUDE.md to v2.4 scope
...
```

The commit message convention (`<type>: <subject>`) is borrowed from Conventional Commits but kept loose — no enforced scope list yet.

**Alternatives and why not.** Mercurial (`hg`): essentially equivalent feature set, smaller ecosystem. Fossil: bundles bug-tracking and wiki, niche. Plain backups: no history, no branches, no diffs. SVN: centralized, harder for distributed work. Git is the universal default.

---

### Polling vs. native file watchers

**Beginner-friendly analogy.** Two ways to know when your laundry is done. Polling: open the dryer every 10 seconds and check. Native watcher: stick a button on the dryer that beeps when it finishes. Both work; polling is simpler and the dryer hasn't been modified.

**Exact version.** Polling uses Python's standard library `time.sleep` and `Path.exists` / `file.readline`. Native watchers would mean adding `watchdog` (latest 4.x as of 2026).

**Problem it solves.** The live tailer needs to know when new lines are appended to a JSONL file. Polling at 200ms is simple, dependency-free, and cross-platform.

**What the code would look like without polling (i.e. with `watchdog`).** Roughly 30 lines of event-handler boilerplate vs. the 6 lines of `_drain` + `time.sleep(POLL_INTERVAL_SECONDS)` we have today. Plus a new dependency tree (`watchdog` pulls in `pathtools` and platform-specific C extensions on some installs).

**Concrete example** from `session_viewer.py:70-82`:

```python
with path.open("r", encoding="utf-8") as f:
    _drain(f, events, console)
    try:
        while True:
            if _drain(f, events, console) == 0:
                time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        return events
```

Six lines. Cross-platform. No dependencies.

**Alternatives and why not.** `watchdog`: covered above. `inotify` (Linux-only): not portable. `FSEvents` (macOS-only): not portable. `ReadDirectoryChangesW` (Windows-only): not portable. Polling buys us cross-platform behavior for the cost of a sub-perceptual 200ms latency.

---

### `uuid` (standard library)

**Beginner-friendly analogy.** A way to generate a unique-looking random string that's astronomically unlikely to collide with any other unique-looking random string anyone else has ever generated. Like a lottery ticket with a 122-bit number.

**Exact version.** Standard library `uuid` module. Available in every Python version. We use `uuid.uuid4()` (random) and `uuid.UUID(string)` (parse).

**Problem it solves.** Every session needs an identifier that cannot collide with other sessions in the same output directory, and that does not rely on a central registry. UUID4 (random) gives us this for free.

**What the code would look like without it.** A counter (`session_001`, `session_002`) requires a persistent state file and breaks if two `vizhi start` commands race. A timestamp-only id (`session_20260521T120700Z`) collides if two sessions start the same second. Hashing the start time + hostname is more complicated and still collision-prone.

**Concrete example** from `watcher.py:66`:

```python
session_id = uuid.uuid4()
```

And the `_parse_session_uuid` helper at `cli.py:195-200`:

```python
def _parse_session_uuid(session_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(session_id)
    except ValueError:
        return uuid.uuid4()
```

**Alternatives and why not.** Counter: requires state, races. Timestamp: collides. ULID / NanoID: smaller and time-sortable but require a third-party library. Random hex string (`os.urandom(16).hex()`): basically a UUID4 with extra steps. `uuid.uuid4` is the boring obvious choice.

---

### Timezone-aware `datetime` (UTC everywhere)

**Beginner-friendly analogy.** A clock that knows what timezone it's in. A naive datetime is like a clock with no timezone label — you can read the numbers but you don't know if they're New York time or Tokyo time. A timezone-aware datetime is labeled, so converting between zones or comparing across machines is unambiguous.

**Exact version.** Standard library `datetime.datetime` and `datetime.timezone`. The convention "always UTC" is enforced by always calling `datetime.now(timezone.utc)`.

**Problem it solves.** A report generated in New York should be intelligible to a reviewer in London without ambiguity. Naive datetimes are a famous source of cross-timezone bugs.

**What the code would look like without it.** `datetime.now()` (naive) produces an unambiguous-within-one-machine timestamp that becomes ambiguous the moment it crosses a machine boundary. Comparing naive and timezone-aware datetimes raises `TypeError: can't subtract offset-naive and offset-aware datetimes`. We would have to defensively check every datetime's tzinfo or convert at every boundary.

**Concrete example** from `parser.py:78-83`:

```python
def parse_line(line: str) -> ActionEvent:
    return ActionEvent(
        timestamp=datetime.now(timezone.utc),
        raw_text=line.rstrip("\r\n"),
        action_type=classify(line),
    )
```

And from `hook_receiver.py:143-150`:

```python
def _parse_timestamp(raw: object) -> datetime:
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)
```

Every timestamp we mint is UTC. Every timestamp we parse from a hook payload is forced into UTC or fresh-from-now (also UTC).

**Alternatives and why not.** Local time: breaks on cross-machine reports. Pendulum / Arrow: better APIs than stdlib, but the stdlib does what we need and adds no dependency. Unix timestamp ints: lose human-readability and timezone info. ISO-8601 UTC datetimes are the universal record format.

---

### `pathlib`

**Beginner-friendly analogy.** Object-oriented file paths. Instead of stringly typed `os.path.join("a", "b", "c.txt")` and `os.path.exists(...)`, you do `Path("a") / "b" / "c.txt"` and `.exists()`.

**Exact version.** Standard library. Available since Python 3.4. The `Path.read_text(encoding=...)` keyword is 3.6+; we use 3.11+.

**Problem it solves.** Cross-platform path handling. `pathlib` abstracts away the difference between `/` and `\`, plus `os.path` vs. raw string manipulation. The OO interface is far more readable.

**What the code would look like without it.** `os.path.join(output_dir, f"session_{safe_id}.jsonl")` instead of `out / f"session_{safe_id}.jsonl"`. `os.makedirs(output_dir, exist_ok=True)` instead of `Path(output_dir).mkdir(parents=True, exist_ok=True)`. `open(filepath).read()` instead of `path.read_text()`. Each minor, but in aggregate they make the code noisier.

**Concrete example** from `hook_receiver.py:153-175`:

```python
def _append_to_session_log(
    classified: ClassifiedEvent,
    session_id: str,
    output_dir: str,
) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    safe_id = _sanitize_session_id(session_id)
    path = out / f"session_{safe_id}.jsonl"
    ...
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
```

Or `installer.py:37-43`:

```python
def get_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"
```

Three operators do the work; on Windows, the path string ends up using backslashes; on Linux, forward slashes; the code is identical.

**Alternatives and why not.** `os.path`: works but is procedural and stringly typed. Third-party libs like `path` or `plumbum.LocalPath`: not in the stdlib, no real win. `pathlib` is the modern stdlib answer.

---

### `from __future__ import annotations`

**Beginner-friendly analogy.** A switch that tells Python: "When you see a type hint, don't evaluate it immediately at the moment the class or function is defined — just remember it as a string and only resolve it if someone actually asks." Lets you reference types that aren't yet defined.

**Exact version.** Available since Python 3.7. Becomes default behavior in some PEP-563 / PEP-649 contexts going forward; we keep the explicit import as a safety net.

**Problem it solves.** Forward references (referring to a type before it is defined) and string-quoted annotations. Without it, `def foo() -> ClassDefinedBelow:` would fail at class-load time. With it, the annotation is just a string and resolution is lazy.

**What the code would look like without it.** Every forward reference would need to be quoted: `def foo() -> "ClassDefinedBelow":`. Imported-only-for-typing modules would need to live inside `if TYPE_CHECKING:` blocks to avoid runtime overhead.

**Concrete example.** First line of every non-trivial module in `vizhi/`:

```python
from __future__ import annotations
```

For example, `session_viewer.py:11`. The import lets us write `IO[str]` without importing `IO` from `typing` *and* without quoting it.

**Alternatives and why not.** Quoting every forward-referenced type by hand: noisy. Putting all typing imports inside `if TYPE_CHECKING:` blocks: works but doubles the import statements. The future import is one line at the top of each module that solves the whole class of problems.

---

## Planned Future Stack

The technologies below are not in use today. They are planned for v3.0+ when Vizhi grows from a local CLI to a multi-user dashboarded service. The exact dependency on each is recorded in `pyproject.toml`'s description and in `CLAUDE.md`'s Tech Stack table.

### FastAPI (planned for v3.0)

**Beginner-friendly analogy.** A library for building web APIs in Python. You decorate a function with `@app.get("/sessions/{id}")` and FastAPI handles the HTTP routing, request validation, JSON serialization, and OpenAPI doc generation.

**What role it will play in v3+.** The HTTP API server that the React dashboard talks to. Receives forwarded hook events (the `# TODO(v2.3): forward classified events to the FastAPI dashboard over HTTP.` in `hook_receiver.py:41` is the integration point), exposes endpoints to list and fetch sessions and reports, and streams live events via Server-Sent Events or WebSockets for the live feed in the browser.

**How it will connect to the existing Python codebase.** Reuses every existing module unchanged. The API endpoint that fetches a session report imports `reporter.SessionReport` and `_load_report`-equivalent logic. The endpoint that ingests a forwarded hook event imports `classifier.classify_event` and a new `persist_to_db` function. The data model (frozen dataclasses) is already JSON-serializable, so the wire format is settled.

**Why FastAPI over alternatives.** Native async support (useful for streaming live events). Built on Pydantic, which uses the same type hints we already write. Auto-generated OpenAPI docs and Swagger UI — invaluable when the React frontend is built by a different developer. Lighter and more modern than Flask, less opinionated than Django, no template-system overhead. Starlette under the hood is battle-tested.

---

### React (planned for v3.0)

**Beginner-friendly analogy.** A JavaScript library for building user interfaces by composing reusable components. Instead of writing imperative DOM manipulation, you write component functions that take props and return what to render; React figures out the minimal updates.

**What role it will play in v3+.** The dashboard frontend that human users open in a browser. Lists past sessions, lets them drill into a session's report, visualizes the risk breakdown over time, and shows a live feed for in-progress sessions (subscribed to the FastAPI server's SSE/WebSocket stream).

**How it will connect to the existing Python codebase.** Indirectly, through the FastAPI HTTP API. The React app makes `fetch()` calls; it never imports or knows about the Python modules directly. The contract between them is the OpenAPI schema FastAPI generates from the typed Python endpoints.

**Why React over alternatives.** Largest ecosystem, easiest hiring pool. Componentization story works well for our likely UI (list of sessions, drill-down detail view, live feed). Vue and Svelte would also work but have smaller communities. Angular is too heavy for our scope. Plain HTML + HTMX would suit the simplest version but caps the eventual interactivity.

---

### Supabase PostgreSQL (planned for v3.0)

**Beginner-friendly analogy.** Supabase is "Firebase for PostgreSQL" — a managed Postgres database with auth, real-time subscriptions, and a REST/GraphQL layer baked in. We will use the database part.

**What role it will play in v3+.** Persistent storage for sessions, classified events, users, organizations, and any custom rules a user defines. Replaces the per-machine `vizhi_reports/` directory with a central store queryable across machines.

**How it will connect to the existing Python codebase.** The FastAPI layer talks to PostgreSQL via SQLAlchemy or `asyncpg`. The hook receiver gets an optional `--forward-to-api` mode that POSTs each classified event to FastAPI; FastAPI writes it to Postgres. The existing JSONL files remain as a per-machine durable fallback; Postgres is the canonical store.

**Why PostgreSQL over alternatives.** Mature, ACID, supports the JSON column type for storing the `metadata` field without flattening, supports time-series queries we'll need for "events per minute over the last week." Supabase specifically gives us managed hosting, point-in-time recovery, and built-in auth integration. SQLite would work but doesn't scale to multi-user. MongoDB / DynamoDB are document stores that fit JSONL-like data but lose SQL's analytical query power. Snowflake / ClickHouse would be overkill for our scale.

---

### Supabase Auth (planned for v3.0)

**Beginner-friendly analogy.** A login system as a service. You don't have to write password hashing, email verification, magic links, or OAuth flows yourself — Supabase Auth gives you a SDK and a UI library.

**What role it will play in v3+.** Authenticates users of the web dashboard. Probably supports email/password, GitHub OAuth (developers' primary identity), and Google OAuth. Authorizes which sessions / organizations a user can see.

**How it will connect to the existing Python codebase.** FastAPI dependency-injects the user identity from a JWT issued by Supabase Auth (validates the token on every request). The Python code never sees raw passwords. The React frontend uses Supabase's official JS SDK to handle the login UI.

**Why Supabase Auth over alternatives.** Same vendor as the database — single integration, single billing relationship. Auth0 is more polished but more expensive and adds another vendor. Rolling our own is the obvious worst path (security-critical code we'd have to maintain). Clerk and Stytch are good Auth0 competitors but again add a vendor. Bundling auth with the DB is the path of least integration friction.

---

### Docker (planned for v3.0)

**Beginner-friendly analogy.** A way to bundle an application together with everything it needs to run — language runtime, libraries, OS dependencies — into a single image that runs the same way on any machine.

**What role it will play in v3+.** Packaging the FastAPI server (and any future worker processes) for deployment. A `Dockerfile` builds the image; a `docker-compose.yml` runs it locally with Postgres for development; production deploys the image to a container host (Fly.io, Railway, AWS ECS, GCP Cloud Run).

**How it will connect to the existing Python codebase.** The image's `CMD` runs `uvicorn vizhi.api:app` (or equivalent — the API entry point will be a new module). The existing CLI is not containerized (it's a developer tool that runs on the developer's machine), only the server side.

**Why Docker over alternatives.** Industry standard. Works with every cloud provider's container service. Local-to-prod parity (`docker compose up` on dev = production-like environment). Buildpacks (Heroku-style) are simpler but lock us into specific providers. Nix is theoretically purer but has a steep learning curve and tiny ecosystem. Python venvs alone don't isolate system dependencies and don't deploy as artifacts.
