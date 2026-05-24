# Tech Stack

Every technology, library, format, tool, and standard that Vizhi uses today, plus what is planned for the next phase of the project.

Each entry follows the same structure:

- **What it is (simple)** — one or two sentences in plain English.
- **What it is (technical)** — the precise definition with proper terminology.
- **Why chosen over alternatives** — what other options exist and why Vizhi prefers this one.
- **Where used in Vizhi** — concrete file references so you can read the code.

---

## Python 3.11+

### What it is (simple)
Python is the programming language Vizhi is written in. The `3.11+` requirement means you need at least Python 3.11 installed to run Vizhi.

### What it is (technical)
Python 3.11 (released October 2022) is the minimum supported interpreter. Vizhi targets the CPython reference implementation. Python 3.11 brought significant interpreter speedups via the "Faster CPython" project (PEP 659 specialising adaptive interpreter), better error messages (PEP 657 fine-grained error locations), and several typing improvements that Vizhi relies on (`Self`, more flexible `TypedDict`).

### Why chosen over alternatives
- **vs. Python 3.9/3.10:** Vizhi uses `from __future__ import annotations` (PEP 563) so most modern annotations compile on older versions, but several features — better error messages, faster startup, the union syntax for runtime use cases — are 3.11+. Pinning to 3.11+ avoids a long tail of conditional compatibility code.
- **vs. Node/TypeScript:** Python has a deeper ecosystem for security tooling, an obvious story for ML/rules engines, and a much simpler distribution story for a CLI (`pip install`).
- **vs. Go/Rust:** Faster to iterate; the performance gap is irrelevant for an I/O-bound tool that processes a few hundred events per session.

### Where used in Vizhi
Everywhere. The `requires-python = ">=3.11"` declaration is in `pyproject.toml`.

---

## Click

### What it is (simple)
Click is a library for building command-line tools. It is what makes `vizhi start`, `vizhi report`, `vizhi watch`, `vizhi install-hook`, etc. feel like a single coherent program with sensible `--help` output.

### What it is (technical)
[Click](https://click.palletsprojects.com/) is a declarative CLI framework that builds command trees out of Python decorators (`@click.group`, `@click.command`, `@click.option`, `@click.argument`). It handles argument parsing, type coercion, help generation, version flags, and shell completion. Vizhi pins `click>=8.1.0` (PEP 621-style optional dependencies, Python 3.11+ compatibility, modern Context API).

### Why chosen over alternatives
- **vs. `argparse` (stdlib):** Click reads top-down — one decorator per option, one function per subcommand — which keeps `cli.py` short and grep-friendly. Argparse imperative builder code grows fast.
- **vs. `typer`:** Typer is Click underneath, with extra type-hint magic. Vizhi already commits to explicit type hints throughout, so Click's lighter API is enough.
- **vs. `docopt`:** Docopt parses help text into a CLI; great for prototypes but awkward to refactor as commands evolve.

### Where used in Vizhi
`vizhi/cli.py` — every `@main.command`, every `@click.option`, the `@click.group` that defines the `main` entry point, the `@click.version_option` that wires `vizhi --version`.

---

## Rich

### What it is (simple)
Rich is the library that paints colour onto Vizhi's terminal output — the red `CRIT`, the yellow ` MED`, the boxes around the session-report header, the tidy aligned columns of the risk breakdown.

### What it is (technical)
[Rich](https://rich.readthedocs.io/) is a Python library for advanced terminal rendering: styled text, panels, tables, syntax highlighting, progress bars, tracebacks. It detects terminal capabilities (truecolour, 256-colour, no-colour) and degrades gracefully. Vizhi pins `rich>=13.7.0`.

### Why chosen over alternatives
- **vs. raw ANSI escape codes:** Cross-platform-safe (handles Windows Terminal vs. legacy `cmd.exe` properly), and the high-level primitives (`Panel`, `Table`) save dozens of lines of manual layout code.
- **vs. `colorama`:** Colorama only handles colour on Windows. Rich does that *and* tables, panels, markup, etc.
- **vs. `blessings`/`urwid`:** Those are full TUI frameworks aimed at interactive apps. Rich is the right level of abstraction for "structured output" without committing to a screen-redraw model.

### Where used in Vizhi
- `vizhi/watcher.py` — `Console`, `Text`, `RISK_STYLES` for the live feed.
- `vizhi/reporter.py` — `Console`, `Panel`, `Table` for the session report.
- `vizhi/session_viewer.py` — re-uses `render_event()` from `watcher.py`.
- `vizhi/cli.py` — `Console` for all user-facing messages.

---

## dataclasses

### What it is (simple)
A `@dataclass` is a quick way to make a Python class that just stores a few named fields. Python writes the constructor, repr, and equality logic for you so you don't have to.

### What it is (technical)
[`@dataclass`](https://docs.python.org/3/library/dataclasses.html) is a standard-library decorator (PEP 557, Python 3.7+) that generates `__init__`, `__repr__`, `__eq__`, and optionally other dunders from class-level type-annotated attributes. It eliminates boilerplate while keeping the result a plain Python class — no metaclass magic, fully introspectable.

### Why chosen over alternatives
- **vs. plain classes with `__init__`:** Dataclasses cut field-storage classes from 15 lines to 5.
- **vs. `attrs`:** A third-party dependency for something the stdlib now does well.
- **vs. `pydantic`:** Pydantic adds runtime validation and serialisation hooks — useful for API boundaries (and likely worth it once FastAPI lands), but overkill for internal data shapes.
- **vs. `NamedTuple`:** NamedTuples are immutable and indexable by position; dataclasses are more flexible and have clearer semantics for "this is a value object."

### Where used in Vizhi
- `vizhi/parser.py` — `ActionEvent`.
- `vizhi/classifier.py` — `ClassifiedEvent`.
- `vizhi/reporter.py` — `SessionReport`.

---

## Frozen dataclasses

### What it is (simple)
A *frozen* dataclass is a dataclass whose fields can't be changed after the object is created. Once you've built one, it stays that way forever. This makes it safe to share between different parts of the program.

### What it is (technical)
`@dataclass(frozen=True)` blocks attribute assignment after `__init__` (raises `FrozenInstanceError`) and generates `__hash__` based on the field values. This gives instances *value semantics* — two instances with the same field values compare equal and hash identically — and lets them be used as dict keys or set members.

### Why chosen over alternatives
- **vs. mutable dataclasses:** Vizhi's event records are conceptually immutable: an event happened, it has a fixed timestamp and raw text, it should never be mutated by a downstream consumer. Freezing them encodes that invariant in the type system.
- **vs. `typing.NamedTuple`:** Comparable immutability, but you cannot have a mutable default for a field (e.g. `metadata: dict[str, str] = field(default_factory=dict)`).
- **vs. raw tuples:** No field names, much worse readability.

### Where used in Vizhi
All three primary data types — `ActionEvent`, `ClassifiedEvent`, `SessionReport` — are frozen.

---

## Literal types

### What it is (simple)
A `Literal` type lets you say "this value can only be one of these exact strings." For example, an action type is exactly one of `"command"`, `"file_access"`, `"network"`, or `"unknown"` — nothing else.

### What it is (technical)
`typing.Literal[...]` (PEP 586, Python 3.8+) is a type form whose values are constrained to specific literal constants. Static type checkers (mypy, pyright) will reject any value not in the literal set, catching typos at lint time. There is no runtime enforcement — `Literal` is purely a typing hint.

### Why chosen over alternatives
- **vs. `str`:** Replacing `str` with `Literal["command", "file_access", ...]` turns "I forgot to add `"netwrok"` to the dispatch" into a compile-time error.
- **vs. `enum.Enum`:** Enums are full Python classes with members, repr, etc. Useful when you need behaviour attached. Vizhi's categories are plain strings flowing through JSON serialisation, so the simpler `Literal` shape avoids enum-to-string conversion at every boundary.

### Where used in Vizhi
- `vizhi/parser.py` — `ActionType = Literal["command", "file_access", "network", "unknown"]`.
- `vizhi/classifier.py` — `RiskLevel = Literal["critical", "high", "medium", "low", "info"]`.

---

## Type hints

### What it is (simple)
Type hints are annotations on Python code that say what kind of value a variable, parameter, or return holds. They help your editor catch bugs before you run the code.

### What it is (technical)
Python type hints (PEP 484, refined by 526, 544, 612, 646, 695, …) are static metadata read by tools like `mypy` and `pyright` but ignored by the interpreter at runtime (with rare exceptions like `dataclass` field detection). They form a structural type system over Python's nominal one and enable IDE intelligence, static analysis, and runtime introspection.

Vizhi declares full type hints on every function — including private helpers — and on every dataclass field. The `from __future__ import annotations` import at the top of every module makes all annotations strings at runtime, which (a) avoids forward-reference quoting, (b) sidesteps import cycles, and (c) costs nothing.

### Why chosen over alternatives
- **vs. unannotated Python:** Catches an entire class of bugs (passing the wrong argument shape) at edit time. Doubles as documentation.
- **vs. `typing.Any` everywhere:** Defeats the purpose. Vizhi reserves `Any` for places where it actually means "we don't constrain this" — e.g. inside `installer.py` where settings.json shape is genuinely user-controlled.

### Where used in Vizhi
Every `def`, every dataclass field, every variable that benefits. CLAUDE.md enforces this as a hard rule: "Use type hints on all functions."

---

## JSONL format

### What it is (simple)
JSONL is a file format where each line of the file is one complete JSON object. It looks like a stack of JSON snippets separated by newlines, one per line. It is what Vizhi writes when streaming session events.

### What it is (technical)
[JSON Lines](https://jsonlines.org/) (a.k.a. NDJSON, `*.jsonl`) is a text format defined by three rules: UTF-8 encoding, one valid JSON value per line, lines delimited by `\n`. It is not a formal standard, but is supported natively by `jq`, pandas (`read_json(lines=True)`), Spark, BigQuery, and many ML data pipelines.

### Why chosen over alternatives
- **vs. one big JSON array:** Appending a record to a JSON array requires reading the existing file, parsing it, mutating the array, and re-writing the entire file. That races the live tailer and corrupts the file on crash. JSONL appends are a single `write(line)` — atomic at OS-level for small writes, and crash-safe.
- **vs. CSV:** Vizhi's events have nested metadata. CSV has no notion of nested fields.
- **vs. binary formats (Avro, Parquet):** Not human-readable. JSONL can be inspected with `Get-Content` and any text editor.

### Where used in Vizhi
- `vizhi/hook_receiver.py` writes JSONL via `_append_to_session_log()` to `vizhi_reports/session_<sessionId>.jsonl`.
- `vizhi/session_viewer.py` reads JSONL via `_drain()` and `_event_from_line()`.

---

## JSON

### What it is (simple)
JSON is the universal way of writing structured data as text — objects, arrays, strings, numbers, booleans. Almost every programming language can read and write it.

### What it is (technical)
[JSON](https://www.json.org/) is a text-based data interchange format standardised as [ECMA-404](https://ecma-international.org/publications-and-standards/standards/ecma-404/) and [RFC 8259](https://datatracker.ietf.org/doc/html/rfc8259). Python's standard-library `json` module (`json.loads`, `json.dumps`) is the reference parser/serializer Vizhi uses.

### Why chosen over alternatives
- **vs. YAML:** YAML's indentation-sensitive grammar and many edge cases (Norway problem, anchors, references) make it a poor choice for machine-written artefacts.
- **vs. TOML:** Great for hand-written config; clunky for nested arrays of objects.
- **vs. binary (MessagePack, Protobuf):** Loses human-readability and require schema files.

### Where used in Vizhi
- `vizhi/reporter.py` writes the final session report as a single pretty-printed JSON file (`indent=2`).
- `vizhi/hook_receiver.py` reads the hook payload from stdin via `json.loads`.
- `vizhi/installer.py` reads, mutates, and writes `~/.claude/settings.json`.
- `vizhi/session_viewer.py` reads each JSONL line via `json.loads`.

---

## PostToolUse hook system

### What it is (simple)
A "hook" is a way to tell a tool: "every time you do X, also run this other command." Claude Code has a hook called PostToolUse that fires every time it finishes using a tool. Vizhi installs itself into that hook so it sees every tool Claude Code runs.

### What it is (technical)
The PostToolUse hook is one of several lifecycle hooks exposed by Claude Code. When a hook fires, Claude Code spawns the configured command as a subprocess, pipes a JSON payload describing the event to its stdin, and reads its exit code (with non-zero meaning "fail the operation" for blocking hooks, but PostToolUse is informational — exit codes are advisory only). Vizhi installs a single matcher-`*` entry that runs `python -m vizhi.hook_receiver` after every tool call.

### Why chosen over alternatives
- **vs. scraping stdout:** stdout gives you a rendered string; the hook gives you the actual tool name plus the structured `toolInput` dict — far higher fidelity.
- **vs. an LSP-style MCP server:** A long-running process would require its own process supervisor; the hook model is one short-lived subprocess per event, which is simpler and more crash-resistant.
- **vs. file watchers on a tool log:** Claude Code does not write a stable on-disk tool log; the hook is the official extension point.

### Where used in Vizhi
- `vizhi/installer.py` writes the hook entry into `~/.claude/settings.json`.
- `vizhi/hook_receiver.py` is the subprocess Claude Code spawns.

---

## Claude Code hooks

### What it is (simple)
The broader family of hook events Claude Code exposes for extending its behaviour. PostToolUse is the one Vizhi uses today; others exist for "before a tool runs" and "when the user submits a prompt."

### What it is (technical)
Claude Code's hook system is a configuration-driven extensibility surface in `settings.json` under the top-level `hooks` key. Each event type (`PostToolUse`, `PreToolUse`, `UserPromptSubmit`, …) maps to an array of *matcher entries*, each containing a regex/glob `matcher` plus a list of inner hook commands. The schema is:

```json
{
  "hooks": {
    "<EventName>": [
      {
        "matcher": "<glob>",
        "hooks": [ { "type": "command", "command": "<shell command>" } ]
      }
    ]
  }
}
```

Hooks receive a JSON payload on stdin and may write to stdout/stderr for diagnostics. The exit code is interpreted differently per event — informational for PostToolUse, blocking for PreToolUse.

### Why chosen over alternatives
- The PostToolUse hook is the most reliable real-time signal Claude Code emits. PreToolUse would also be valuable (Vizhi has a `# TODO(v2.2)` to add it for blocking critical actions), but PostToolUse fires unconditionally and is enough for monitoring/reporting.

### Where used in Vizhi
The matcher-`*` PostToolUse entry written by `installer.py`. PreToolUse blocking is on the roadmap.

---

## `pyproject.toml` and setuptools

### What it is (simple)
`pyproject.toml` is the configuration file that tells Python how to install Vizhi as a real command-line tool. Setuptools is the engine that reads it and builds the package.

### What it is (technical)
[`pyproject.toml`](https://packaging.python.org/en/latest/specifications/pyproject-toml/) is the canonical Python project metadata file defined by PEP 517 / 518 / 621 / 660. It declares the build system, project metadata, dependencies, and entry points. Vizhi's `pyproject.toml` declares `setuptools>=68` + `wheel` as the build backend and uses the modern PEP 621 `[project]` table for metadata.

The crucial entry is the console-script binding:

```toml
[project.scripts]
vizhi = "vizhi.cli:main"
```

This tells `pip` to create a `vizhi` executable in the user's `Scripts/` (or `bin/`) directory that calls `vizhi.cli:main()`.

### Why chosen over alternatives
- **vs. `setup.py`:** `setup.py` is being phased out by the Python packaging ecosystem; PEP 517/518 made `pyproject.toml` the standard.
- **vs. `poetry` / `hatch`:** Both wrap `pyproject.toml` with extra DX. Vizhi's needs are simple enough that the stock `setuptools` backend is fine.
- **vs. publishing to PyPI:** Vizhi is alpha and not yet published; local `pip install -e .` is the install path for now.

### Where used in Vizhi
`/pyproject.toml` at the repo root.

---

## pip editable installs (`pip install -e .`)

### What it is (simple)
An "editable install" links the installed `vizhi` command to your local source code, so every edit you make in `vizhi/` takes effect immediately without re-installing.

### What it is (technical)
`pip install -e .` (PEP 660 editable installs) generates a `.pth` file in the active environment's `site-packages` that points back to the project source directory. Imports of `vizhi.cli` resolve to the live source on disk, and the console-script wrapper is regenerated on each install. Iteration cycle is: edit `.py` → run `vizhi <cmd>` → see effect. No build step.

### Why chosen over alternatives
- **vs. `pip install .`:** Non-editable installs copy the source into `site-packages`; you'd have to re-install after every change. Painful during development.
- **vs. `python -m vizhi.cli` directly:** Works, but loses the `vizhi` console script that users will actually type. Editable installs give you the production-shaped command without sacrificing iteration speed.

### Where used in Vizhi
The README's installation section instructs `pip install -e .` from the project root.

---

## Git

### What it is (simple)
Git is the version-control system that tracks every change to Vizhi's code over time. You can roll back, branch, merge, and share history with collaborators.

### What it is (technical)
[Git](https://git-scm.com/) is a distributed content-addressable version-control system whose object model — blobs, trees, commits, tags — is fundamentally a Merkle DAG. Vizhi uses the standard branching model (`main` as the trunk, feature commits land on `main` directly during alpha) and conventional commit-message prefixes (`docs:`, `feat:`, `chore:`, …).

### Why chosen over alternatives
- **vs. Mercurial / SVN / Fossil:** Git's network effect — GitHub, GitLab, IDE integrations, CI providers — is overwhelming. Mercurial's cleaner UX cannot overcome the ecosystem gap.
- **vs. no VCS:** Unthinkable for a security-relevant tool. Every classifier-rule change should be traceable.

### Where used in Vizhi
The whole repo. The user pushes to a GitHub remote (`origin/main`).

---

## Polling vs native file watchers

### What it is (simple)
There are two ways to know when a file changes: ask the operating system to *tell* you (native watchers, like `inotify` on Linux), or check the file yourself every fraction of a second (polling). Vizhi uses polling.

### What it is (technical)
**Native watchers** are platform-specific kernel APIs that deliver file-system events asynchronously: `inotify` (Linux), `FSEvents` (macOS), `ReadDirectoryChangesW` (Windows). The cross-platform wrapper of choice is the [watchdog](https://pypi.org/project/watchdog/) Python library. Latency is sub-millisecond, but each platform has subtle behavioural quirks (e.g. Windows fires duplicate events under some buffered I/O patterns).

**Polling** repeatedly checks the file (`f.readline()` on an open handle) at a fixed interval. Latency is bounded by the interval (Vizhi uses 200 ms), but the behaviour is identical on every OS. There are no native bindings, no compiled wheels, no event-coalescing semantics to learn.

### Why chosen over alternatives
For Vizhi's specific use case — tailing a small append-only file — polling at 200 ms is:
- **Cross-platform-identical.** No "works on Mac, weird on Windows" bug reports.
- **Dependency-free.** Adds zero new wheels to the install.
- **Below human perception.** A user staring at the terminal cannot tell the difference between 50 ms and 200 ms latency.

The `# TODO(v2.4)` in `session_viewer.py` reserves the option to make `watchdog` an *optional* dependency for users who want lower latency.

### Where used in Vizhi
`vizhi/session_viewer.py` — the `tail_session()` polling loop with `time.sleep(POLL_INTERVAL_SECONDS)`.

---

## `uuid`

### What it is (simple)
A UUID is a long random string that's almost guaranteed to be unique. Vizhi uses one to label each watching session so two sessions never collide.

### What it is (technical)
The standard-library [`uuid`](https://docs.python.org/3/library/uuid.html) module implements [RFC 4122](https://datatracker.ietf.org/doc/html/rfc4122) Universally Unique IDentifiers. Vizhi uses `uuid.uuid4()` (random) — 122 random bits, collision probability negligible — for session IDs in v1's `watcher.watch()` and as the canonical `SessionReport.session_id` field.

In v2, the hook payload includes Claude Code's `sessionId`, which Vizhi preserves verbatim as the JSONL filename. `cli.watch_cmd` does a best-effort `uuid.UUID(session_id)` parse to pull it through to the report; if Claude Code emits a non-UUID ID, the parse fails gracefully and a fresh UUID is allocated for the report.

### Why chosen over alternatives
- **vs. incrementing integers:** Need a central counter, race on concurrent watchers, leak total-session-count information.
- **vs. timestamp + hostname:** Not collision-safe and reveals private host data.
- **vs. KSUID / ULID:** Slightly nicer (sortable, shorter), but adds a dependency for marginal benefit.

### Where used in Vizhi
- `vizhi/watcher.py` — `uuid.uuid4()` in `watch()`.
- `vizhi/reporter.py` — `SessionReport.session_id: uuid.UUID`.
- `vizhi/cli.py` — `_parse_session_uuid()` and `_load_report()` re-parsing UUIDs from saved JSON.

---

## Timezone-aware datetime

### What it is (simple)
Timestamps in Vizhi always include the time zone they were taken in — specifically UTC. This avoids the bug where "the event happened at 14:00" means different things to different people.

### What it is (technical)
Python's `datetime` module exposes two flavours: *naive* (`datetime.now()`) and *aware* (`datetime.now(timezone.utc)`). Vizhi *exclusively* uses aware datetimes anchored to UTC. ISO-8601 serialisation via `.isoformat()` includes the `+00:00` offset; parsing via `datetime.fromisoformat()` round-trips it.

The `_parse_timestamp()` helper in `hook_receiver.py` also accepts the `Z` suffix (replacing it with `+00:00`) because Claude Code may emit either form.

### Why chosen over alternatives
- **vs. naive datetimes:** Naive datetimes are a fertile source of bugs. Comparing a naive `datetime` to an aware one raises `TypeError`; converting them implicitly to local time silently corrupts logs.
- **vs. epoch integers:** Less human-readable in saved reports; no automatic ISO-8601 serialisation in pandas / jq.

### Where used in Vizhi
- `vizhi/parser.py` — `datetime.now(timezone.utc)` in `parse_line()`.
- `vizhi/watcher.py` — `started_at = datetime.now(timezone.utc)`.
- `vizhi/hook_receiver.py` — `_parse_timestamp()` always returns an aware datetime.
- `vizhi/reporter.py` — start/end timestamps and the `_fmt_duration` calculation.
- `vizhi/cli.py` — re-construction of timestamps in `_event_from_dict()`.

---

## `pathlib`

### What it is (simple)
`pathlib` is the standard-library way to work with file paths in Python. It writes the same on Windows and Mac and Linux, and lets you say things like `path / "subfolder" / "file.txt"` instead of `os.path.join(...)`.

### What it is (technical)
The [`pathlib`](https://docs.python.org/3/library/pathlib.html) module (Python 3.4+) is an object-oriented filesystem-path API built around the `Path` class. It exposes platform-correct path operations, `glob`, `mkdir`, `read_text`/`write_text`, `home()`, `stat()`, and operator-overload joining (`/`). Vizhi uses only `Path`, never raw strings, for any operation that involves the filesystem.

### Why chosen over alternatives
- **vs. `os.path`:** String-based, easy to forget the separator, no method chaining.
- **vs. third-party path libraries:** Stdlib `pathlib` is now feature-complete enough that third-party alternatives are rarely worth the dependency.

### Where used in Vizhi
- `vizhi/installer.py` — `Path.home() / ".claude" / "settings.json"`, `path.read_text`, `path.write_text`, `path.parent.mkdir`.
- `vizhi/reporter.py` — output-dir creation, filename construction.
- `vizhi/cli.py` — `_latest_report_path()` globbing.
- `vizhi/hook_receiver.py` — output-dir + JSONL path resolution.
- `vizhi/session_viewer.py` — file-existence polling and glob-based session discovery.

---

## `from __future__ import annotations`

### What it is (simple)
A one-line import at the top of every Vizhi module that turns all type annotations into strings instead of being evaluated at import time. This makes annotations cheaper, lets you forward-reference types, and sidesteps a class of import-cycle bugs.

### What it is (technical)
[PEP 563](https://peps.python.org/pep-0563/) postponed evaluation of annotations. With `from __future__ import annotations` at the top of a file, every annotation in that file is stored as a string in `__annotations__` instead of being evaluated when the module is loaded. The string can be resolved later via `typing.get_type_hints()` if anything needs the real object (rare in Vizhi — dataclasses' `field` resolution is the one place where it matters, and that still works).

Concretely:

```python
def f(x: int) -> "MyClass":  # old way: forward references are strings
    ...
```

becomes:

```python
from __future__ import annotations

def f(x: int) -> MyClass:  # all annotations are now strings; forward refs free
    ...
```

### Why chosen over alternatives
- **vs. not importing it:** You'd have to quote every forward reference and pay a small startup cost for annotation evaluation. Including it is free and consistent.
- **vs. relying on Python 3.12+'s deferred evaluation (PEP 649):** Not yet the default in 3.11. The `__future__` import gives the same behaviour today.

### Where used in Vizhi
First import line of every `.py` file in the `vizhi/` package.

---

# Planned Future Stack

Technologies that are *not* yet in the codebase but are explicitly on the roadmap, with their planned role.

---

## FastAPI

### What it is (simple)
FastAPI is a Python library for building web APIs — JSON-over-HTTP endpoints that web pages and other programs can call.

### What it is (technical)
[FastAPI](https://fastapi.tiangolo.com/) is a modern Python web framework built on Starlette (ASGI) and Pydantic. It uses type-hint-driven request/response validation and produces an OpenAPI schema (Swagger UI) automatically from endpoint signatures.

### Planned use in Vizhi
The future web dashboard's API tier. Endpoints would expose:
- Session list and filtering.
- Streamed live events over WebSocket / Server-Sent Events.
- Cross-session risk aggregates.
- Webhooks for alerting integrations.

The CLI's existing reporter modules will be re-used unchanged — FastAPI handlers will call the same `generate_report()` and serve the same `SessionReport` shapes that `vizhi report` produces today.

---

## React

### What it is (simple)
React is the most popular library for building interactive web pages. It is what the future Vizhi dashboard will be written in.

### What it is (technical)
[React](https://react.dev/) is a declarative, component-based UI library that renders a virtual DOM and reconciles it against the real DOM on state changes. The Vizhi dashboard plan pairs it with TypeScript and a routing/build toolchain (likely Vite + React Router) for the front-end shell.

### Planned use in Vizhi
The web dashboard UI:
- Live session feed mirroring the terminal output.
- Searchable historical session browser.
- Cross-session aggregates (risk trends, most-flagged commands).
- Team views once Supabase Auth is wired up.

---

## Supabase PostgreSQL

### What it is (simple)
Supabase is a hosted PostgreSQL database with a JSON API and built-in auth. It is the database Vizhi will use once sessions need to be shared across machines or users.

### What it is (technical)
[Supabase](https://supabase.com/) is an open-source Firebase-style backend-as-a-service built on PostgreSQL. It exposes a PostgREST-compatible HTTP API and a Realtime subscription channel. Vizhi would model sessions and classified events as two tables joined by `session_id`, with row-level security tied to Supabase Auth users/teams.

### Planned use in Vizhi
- Replace local JSON / JSONL persistence with a remote-first model.
- Enable cross-session analytics over many users' data.
- Power the live-feed Realtime subscription that the React dashboard listens on.

---

## Supabase Auth

### What it is (simple)
The authentication layer that comes with Supabase — sign-up, log-in, password resets, social providers, all handled for you.

### What it is (technical)
[Supabase Auth](https://supabase.com/docs/guides/auth) is a GoTrue-based identity provider with JWT sessions, e-mail/password, OAuth (GitHub, Google, etc.), magic-link, and SAML. It integrates with PostgreSQL row-level security via the `auth.uid()` function so policies can be expressed in SQL.

### Planned use in Vizhi
Turn Vizhi from a single-user CLI tool into a team product:
- Per-user accounts.
- Team / organisation grouping for sessions.
- RLS policies so a team admin can see all team sessions but not other teams' data.
- OAuth so users sign in with their GitHub identity, matching the dev tools they already use.

---

## Docker

### What it is (simple)
Docker is the standard way to package a piece of software with everything it needs to run, into one bundle that runs identically anywhere.

### What it is (technical)
[Docker](https://www.docker.com/) packages applications and their dependencies into images — read-only layered filesystems based on the OCI image spec — which are instantiated as containers using Linux kernel features (cgroups, namespaces) or platform equivalents on Windows/macOS via the Docker Desktop VM.

### Planned use in Vizhi
- Reproducible local development environment for new contributors (`docker compose up` brings up FastAPI + a Supabase-compatible local PG + the React dev server).
- Production deployment of the future Vizhi web dashboard.
- CI image used by GitHub Actions for running tests in a known environment.

The CLI itself will continue to be pip-installable — Docker is for the web tier and CI, not for the end-user CLI surface.
