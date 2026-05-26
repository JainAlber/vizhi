# Vizhi

**Vizhi** (விழி) means *"eye"* or *"pupil"* in Tamil.

Real-time security monitor for AI agents. Vizhi watches what Claude Code does — commands executed, files accessed, network calls made — classifies each action by risk level as it happens, streams a live color-coded feed, and generates a session report at the end.

---

## Documentation

In-depth docs live under [`docs/`](docs/):

- [**Code Explained**](docs/code-explained.md) — every file, class, function, and constant in `vizhi/` explained, with cross-file connection maps.
- [**Project Explained**](docs/project-explained.md) — full project overview, end-to-end data flow, scenario walkthroughs, ASCII architecture diagram, and version history.
- [**Tech Stack**](docs/tech-stack.md) — every technology used in Vizhi, why it was chosen over alternatives, and where it appears in the code.

---

## Installation

From the project root:

```bash
pip install -e .
```

This installs Vizhi in editable mode and registers the `vizhi` CLI entrypoint.

Requires Python 3.11+.

---

## Usage

The primary workflow hooks directly into Claude Code. Vizhi installs a `PostToolUse` hook that captures every tool execution, and `vizhi watch` tails that live activity in a separate terminal.

### 1. `vizhi install-hook` (run once)

Install the Vizhi `PostToolUse` hook into `~/.claude/settings.json`:

```bash
vizhi install-hook
```

After this, Claude Code automatically calls `python -m vizhi.hook_receiver` after every tool it runs, appending each classified event to `vizhi_reports/session_<sessionId>.jsonl`. You only need to do this once — the hook persists across Claude Code sessions until you uninstall it.

### 2. Give Claude Code a prompt

Start a new Claude Code session and give it a task, for example:

```bash
claude
> audit this repo for hardcoded secrets
```

This creates the session log file that Vizhi will tail.

### 3. `vizhi watch` (in a separate terminal)

In a **second terminal**, start the live watcher:

```bash
vizhi watch
```

It auto-detects the most recent session and streams a color-coded, risk-tagged feed of everything Claude Code does. Press `Ctrl+C` to end the watch, print the session summary, and write the final JSON report.

> ⚠️ **Order matters.** `vizhi watch` must start **after** Claude Code has begun a new session. The watcher tails an existing session log — if no session has started yet, there is no log file to follow, and `vizhi watch` will report that no session logs were found. Always: install the hook, give Claude Code a prompt, *then* run `vizhi watch`.

To watch a specific session instead of the latest:

```bash
vizhi watch --session-id <sessionId>
```

### `vizhi report`

Pretty-print the most recent session report from the output directory:

```bash
vizhi report
vizhi report --output-dir ./my_reports
```

### `vizhi uninstall-hook`

Remove the Vizhi `PostToolUse` hook from `~/.claude/settings.json`, leaving all other settings untouched:

```bash
vizhi uninstall-hook
```

---

## Legacy / Alternative Usage

> This is the original **v1** method. It still works, but it is no longer the primary workflow — prefer the hook + `vizhi watch` flow above.

Vizhi can read a stream of agent activity directly from `stdin` and write a JSON session report on exit. Pipe Claude Code's output into the watcher:

```bash
claude --print "audit this repo" | vizhi start
```

Or replay a captured log file:

```bash
cat claude_session.log | vizhi start
```

PowerShell:

```powershell
claude --print "audit this repo" | vizhi start
Get-Content claude_session.log | vizhi start
```

When the upstream process exits, Vizhi finalizes the session, prints the summary, and writes `vizhi_reports/session_<uuid>_<timestamp>.json`.

---

## Risk Levels

| Level    | Color      | Examples                                                              |
|----------|------------|-----------------------------------------------------------------------|
| critical | bold red   | `sudo`, `rm -rf`, `chmod 777`, `/etc/passwd`, `~/.ssh`                |
| high     | red        | other destructive commands, `.env`, private keys, `credentials/`      |
| medium   | yellow     | file writes, network calls to unknown domains, new process execution  |
| low      | green      | file reads, network calls to known-safe hosts (GitHub, PyPI, npm)     |
| info     | dim white  | everything else                                                       |

---

## Version

Current version: **v2.4**

---

## License

MIT
